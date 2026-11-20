import asyncio

import numpy as np
from django.test import SimpleTestCase, override_settings
from django.conf import settings

from .pipeline import LivePipeline
from .segmenter import FRAME, SpeechSegmenter
from .transcriber import build_prompt, is_hallucination


class EnergyVAD:
    """Testler için sahte VAD: genliği yüksek çerçeve = konuşma."""

    def __call__(self, frame):
        return 1.0 if np.abs(frame).mean() > 0.05 else 0.0


def tone(seconds):
    n = int(16000 * seconds)
    return (0.3 * np.sin(np.arange(n) / 5)).astype(np.float32)


def silence(seconds):
    return np.zeros(int(16000 * seconds), dtype=np.float32)


def feed_all(seg, audio, chunk=5120):
    out = []
    for i in range(0, len(audio), chunk):
        out += seg.feed(audio[i : i + chunk])
    return out


class SegmenterTests(SimpleTestCase):
    def test_splits_on_silence(self):
        seg = SpeechSegmenter(EnergyVAD(), min_silence_ms=500, speech_pad_ms=100)
        audio = np.concatenate([silence(0.5), tone(1.5), silence(1.0), tone(2.0), silence(1.0)])
        segments = feed_all(seg, audio)
        self.assertEqual(len(segments), 2)
        self.assertEqual([s.reason for s in segments], ["silence", "silence"])
        first = segments[0]
        self.assertAlmostEqual(first.start_ms, 400, delta=70)  # 100 ms ön dolgu
        self.assertAlmostEqual(first.audio.size / 16000, 1.7, delta=0.1)
        self.assertFalse(seg.in_speech)

    def test_max_segment_length(self):
        seg = SpeechSegmenter(EnergyVAD(), max_segment_s=10.0)
        segments = feed_all(seg, tone(25))
        self.assertGreaterEqual(len(segments), 2)
        for s in segments:
            self.assertEqual(s.reason, "max")
            self.assertLessEqual(s.audio.size / 16000, 10.01)
        self.assertTrue(seg.in_speech)
        last = seg.flush()
        total = sum(s.audio.size for s in segments) + last.audio.size
        self.assertEqual(total, 25 * 16000 // FRAME * FRAME)  # hiçbir örnek kaybolmadı

    def test_cut_prefers_quiet_frame(self):
        seg = SpeechSegmenter(EnergyVAD(), max_segment_s=10.0, min_silence_ms=600)
        # 9 sn konuşma, 0.2 sn kısa duraklama (min_silence'dan kısa), 3 sn konuşma
        audio = np.concatenate([tone(9.0), silence(0.2), tone(3.0)])
        segments = feed_all(seg, audio)
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0].end_ms, 9200, delta=250)

    def test_short_noise_is_dropped(self):
        seg = SpeechSegmenter(EnergyVAD(), min_speech_ms=250)
        self.assertEqual(feed_all(seg, np.concatenate([tone(0.1), silence(1.5)])), [])

    def test_current_audio_for_partials(self):
        seg = SpeechSegmenter(EnergyVAD())
        self.assertIsNone(seg.current_audio())
        feed_all(seg, tone(1.0))
        self.assertGreater(seg.current_audio().size, 15000)


class PromptTests(SimpleTestCase):
    def test_prompt_respects_budget_and_keeps_context(self):
        terms = [f"terim{i}" for i in range(500)]
        prompt = build_prompt("Bilgisayar Mühendisliği", terms, "önceki cümle burada", max_chars=300)
        self.assertLessEqual(len(prompt), 300)
        self.assertTrue(prompt.startswith("Bilgisayar Mühendisliği dersi. Terimler: terim0"))
        self.assertTrue(prompt.endswith("önceki cümle burada"))

    def test_hallucination_filter(self):
        self.assertTrue(is_hallucination("Altyazı M.K."))
        self.assertTrue(is_hallucination("İzlediğiniz için teşekkürler."))
        self.assertFalse(is_hallucination("Yığın son giren ilk çıkar mantığıyla çalışır."))


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, prompt=None, final=True):
        self.calls.append((round(audio.size / 16000, 1), final, prompt))
        return f"{'kesin' if final else 'kısmi'} {audio.size / 16000:.1f}"


class PipelineTests(SimpleTestCase):
    def run_pipeline(self, audio, **asr_overrides):
        asr = {**settings.ASR, "PARTIAL_INTERVAL": 0.0, **asr_overrides}
        partials, finals = [], []

        async def on_partial(text):
            partials.append(text)

        async def on_final(text, start, end):
            finals.append((text, start, end))

        async def main():
            fake = FakeTranscriber()
            p = LivePipeline(
                domain_name="Test",
                term_names=["yığın", "kuyruk"],
                on_partial=on_partial,
                on_final=on_final,
                time_offset_ms=5000,
                vad=EnergyVAD(),
                transcriber=fake,
            )
            await p.prepare()
            pcm = (audio * 32767).astype("<i2").tobytes()
            for i in range(0, len(pcm), 10240):
                await p.feed(pcm[i : i + 10240])
                await asyncio.sleep(0)
            await p.close()
            return fake

        with override_settings(ASR=asr):
            fake = asyncio.run(main())
        return partials, finals, fake

    def test_finals_with_offset_and_prompt(self):
        audio = np.concatenate([tone(1.5), silence(1.0), tone(1.0), silence(1.0)])
        partials, finals, fake = self.run_pipeline(audio, PARTIALS=False)
        self.assertEqual(len(finals), 2)
        self.assertEqual(partials, [])
        self.assertGreaterEqual(finals[0][1], 5000)  # zaman kaydırması uygulandı
        final_prompts = [c[2] for c in fake.calls if c[1]]
        self.assertIn("yığın, kuyruk", final_prompts[0])
        self.assertNotIn(finals[0][0], final_prompts[1])  # varsayılan: önceki cümle istemde yok

    def test_previous_text_in_prompt_when_enabled(self):
        audio = np.concatenate([tone(1.5), silence(1.0), tone(1.0), silence(1.0)])
        _, finals, fake = self.run_pipeline(audio, PARTIALS=False, PROMPT_PREVIOUS=True)
        final_prompts = [c[2] for c in fake.calls if c[1]]
        self.assertTrue(final_prompts[1].endswith(finals[0][0]))

    def test_backlog_is_batched_into_one_call(self):
        from .segmenter import Segment

        finals = []

        async def on_final(text, start, end):
            finals.append((text, start, end))

        async def noop(text):
            pass

        async def main():
            fake = FakeTranscriber()
            p = LivePipeline(domain_name="T", term_names=[], on_partial=noop, on_final=on_final,
                             vad=EnergyVAD(), transcriber=fake)
            await p.prepare()
            # İşçi daha çalışmadan 3 bölüm birikmiş olsun (CPU geride kalmış gibi)
            for i, (a, b) in enumerate([(0, 3000), (3500, 6000), (6500, 9000)]):
                p._queue.put_nowait(Segment(i, tone((b - a) / 1000), a, b, "silence"))
            await p.close()
            return fake

        with override_settings(ASR={**settings.ASR, "PARTIALS": False}):
            fake = asyncio.run(main())
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(finals, [("kesin 8.0", 0, 9000)])

    def test_partials_enabled(self):
        audio = np.concatenate([tone(3.0), silence(1.0)])
        partials, finals, fake = self.run_pipeline(audio, PARTIALS=True)
        self.assertEqual(len(finals), 1)
        self.assertTrue(any(c[1] is False for c in fake.calls))
        self.assertTrue(all(p.startswith("kısmi") for p in partials if p))
