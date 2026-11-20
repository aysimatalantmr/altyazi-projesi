"""Canlı ses hattı: PCM -> Silero VAD bölümleme -> faster-whisper -> geri çağrılar.

Django Channels'tan bağımsızdır; WebSocket tüketicisi ve `demo_stream --yerel`
aynı sınıfı kullanır.
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Callable

import numpy as np
from django.conf import settings

from .segmenter import SAMPLE_RATE, Segment, SpeechSegmenter
from .transcriber import build_prompt, get_partial_transcriber, get_transcriber

logger = logging.getLogger("asr.pipeline")

# Tüm Whisper işleri tek iş parçacığında sırayla yürür (CPU'yu boğmamak için)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")
# Geride kalındığında tek çağrıda birleştirilecek en fazla ses (Whisper penceresi 30 sn)
MAX_BATCH_SECONDS = 25.0

PartialCallback = Callable[[str], Awaitable[None]]
FinalCallback = Callable[[str, int, int], Awaitable[None]]


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    if len(pcm) % 2:
        pcm = pcm[:-1]
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


class LivePipeline:
    def __init__(
        self,
        *,
        domain_name: str,
        term_names: list[str],
        on_partial: PartialCallback,
        on_final: FinalCallback,
        time_offset_ms: int = 0,
        vad=None,
        transcriber=None,
        partial_transcriber=None,
    ):
        cfg = settings.ASR
        self.cfg = cfg
        self.domain_name = domain_name
        self.term_names = term_names
        self.on_partial = on_partial
        self.on_final = on_final
        self.time_offset_ms = time_offset_ms
        self._vad = vad
        self._transcriber = transcriber
        self._partial_transcriber = partial_transcriber or transcriber
        self.segmenter: SpeechSegmenter | None = None
        self._queue: asyncio.Queue[Segment | None] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._partial_task: asyncio.Task | None = None
        self._final_busy = False
        self._last_partial_at = 0.0
        self._partial_cost = 0.0
        self._prev_text = ""
        self.closed = False

    # --- yaşam döngüsü -------------------------------------------------------
    async def prepare(self):
        """VAD ve Whisper modellerini (gerekirse indirerek) yükler."""
        loop = asyncio.get_running_loop()
        if self._vad is None:
            from .vad import StreamingVAD

            self._vad = await loop.run_in_executor(None, StreamingVAD, self.cfg["VAD_MODEL_PATH"])
        if self._transcriber is None:
            self._transcriber = await loop.run_in_executor(_EXECUTOR, get_transcriber)
        if self._partial_transcriber is None and self.cfg["PARTIALS"]:
            self._partial_transcriber = await loop.run_in_executor(_EXECUTOR, get_partial_transcriber)
        self.segmenter = SpeechSegmenter(
            self._vad,
            threshold=self.cfg["VAD_THRESHOLD"],
            min_silence_ms=self.cfg["MIN_SILENCE_MS"],
            min_speech_ms=self.cfg["MIN_SPEECH_MS"],
            speech_pad_ms=self.cfg["SPEECH_PAD_MS"],
            max_segment_s=self.cfg["MAX_SEGMENT_SECONDS"],
        )
        self._worker = asyncio.create_task(self._final_loop())

    async def feed(self, pcm: bytes):
        if self.closed or self.segmenter is None:
            return
        for seg in self.segmenter.feed(pcm16_to_float(pcm)):
            self._queue.put_nowait(seg)
        self._maybe_partial()

    async def flush(self):
        """Açık bölümü kapatır ve bekleyen tüm kesin transkripsiyonları bitirir."""
        if self.segmenter is None:
            return
        seg = self.segmenter.flush()
        if seg is not None:
            self._queue.put_nowait(seg)
        await self._queue.join()
        if self._partial_task:
            await asyncio.gather(self._partial_task, return_exceptions=True)

    async def close(self):
        if self.closed:
            return
        try:
            await self.flush()
        finally:
            self.closed = True
            if self._worker:
                self._queue.put_nowait(None)
                await asyncio.gather(self._worker, return_exceptions=True)

    @property
    def elapsed_ms(self) -> int:
        return self.time_offset_ms + (self.segmenter.elapsed_ms if self.segmenter else 0)

    # --- iç işler ------------------------------------------------------------------
    def _prompt(self) -> str:
        previous = self._prev_text if self.cfg.get("PROMPT_PREVIOUS") else ""
        return build_prompt(self.domain_name, self.term_names, previous, self.cfg["PROMPT_MAX_CHARS"])

    def _maybe_partial(self):
        if not self.cfg["PARTIALS"] or self.closed or self._partial_transcriber is None:
            return
        if self._partial_task and not self._partial_task.done():
            return
        if self._final_busy or not self._queue.empty() or not self.segmenter.in_speech:
            return
        now = time.monotonic()
        # Kısmi transkripsiyon CPU'da aralıktan uzun sürüyorsa aralığı kendiliğinden aç
        interval = max(self.cfg["PARTIAL_INTERVAL"], self._partial_cost * 1.5)
        if now - self._last_partial_at < interval:
            return
        audio = self.segmenter.current_audio()
        if audio is None or audio.size < SAMPLE_RATE * 0.6:
            return
        self._last_partial_at = now
        self._partial_task = asyncio.create_task(self._run_partial(audio, self.segmenter.segment_index))

    async def _run_partial(self, audio: np.ndarray, seg_index: int):
        loop = asyncio.get_running_loop()
        started = time.monotonic()
        try:
            text = await loop.run_in_executor(
                _EXECUTOR, self._partial_transcriber.transcribe, audio, self._prompt(), False
            )
        except Exception:
            logger.exception("Kısmi transkripsiyon hatası")
            return
        self._partial_cost = time.monotonic() - started
        # Bu arada bölüm kesinleştiyse eski kısmi metni gösterme
        if text and not self.closed and seg_index == self.segmenter.segment_index and self.segmenter.in_speech:
            await self.on_partial(text)

    def _take_batch(self, first: Segment) -> tuple[list[Segment], bool]:
        """Kuyrukta bekleyen bölümleri (toplam ≤ MAX_BATCH_SECONDS) ilkine ekler.

        Whisper her çağrıda 30 sn'lik pencere işlediğinden maliyet bölüm uzunluğundan
        neredeyse bağımsızdır; CPU geride kalınca birleştirmek gecikme birikmesini önler.
        """
        batch, stop = [first], False
        total = first.audio.size
        limit = int(MAX_BATCH_SECONDS * SAMPLE_RATE)
        while not self._queue.empty():
            nxt = self._queue._queue[0]  # peek
            if nxt is None:
                self._queue.get_nowait()
                stop = True
                break
            if total + nxt.audio.size > limit:
                break
            batch.append(self._queue.get_nowait())
            total += nxt.audio.size
        return batch, stop

    async def _final_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            seg = await self._queue.get()
            if seg is None:
                self._queue.task_done()
                break
            batch, stop = self._take_batch(seg)
            self._final_busy = True
            try:
                audio = batch[0].audio if len(batch) == 1 else np.concatenate([s.audio for s in batch])
                started = time.monotonic()
                text = await loop.run_in_executor(_EXECUTOR, self._transcriber.transcribe, audio, self._prompt(), True)
                logger.info(
                    "Bölüm %s (%.1f sn, %s) %.1f sn'de çözüldü: %s",
                    ",".join(str(s.index) for s in batch),
                    audio.size / SAMPLE_RATE,
                    batch[-1].reason,
                    time.monotonic() - started,
                    text[:80],
                )
                if text:
                    self._prev_text = text
                    await self.on_final(
                        text, batch[0].start_ms + self.time_offset_ms, batch[-1].end_ms + self.time_offset_ms
                    )
                else:
                    await self.on_partial("")
            except Exception:
                logger.exception("Kesin transkripsiyon hatası")
            finally:
                self._final_busy = False
                for _ in batch:
                    self._queue.task_done()
                if stop:
                    self._queue.task_done()
            if stop:
                break
