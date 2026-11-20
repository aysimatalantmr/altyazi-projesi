"""Bir ses dosyasını gerçek zamanlı hızda konuşmacı hattına besler.

Varsayılan: çalışan sunucuya konuşmacı olarak WebSocket ile bağlanır (öğrenciler
altyazıyı tarayıcıda canlı görür). --yerel: sunucu olmadan aynı süreçte çalıştırır.

    python manage.py demo_stream K7M2QX ornek.wav
    python manage.py demo_stream K7M2QX ders.mp3 --hiz 2 --durdur
    python manage.py demo_stream K7M2QX ornek.wav --yerel
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from channels.db import database_sync_to_async
from django.core.management.base import BaseCommand, CommandError

from lectures import services
from lectures.models import LectureSession, normalize_room_code

SAMPLE_RATE = 16000
CHUNK_MS = 320


def resample(audio: np.ndarray, src_rate: int, dst_rate: int = SAMPLE_RATE) -> np.ndarray:
    if src_rate == dst_rate or audio.size == 0:
        return audio.astype(np.float32)
    if src_rate > dst_rate:
        # Basit örtüşme önleyici: kutu filtresi (konuşma için yeterli)
        width = max(1, int(round(src_rate / dst_rate)))
        if width > 1:
            audio = np.convolve(audio, np.ones(width) / width, mode="same")
    n_out = int(round(audio.size * dst_rate / src_rate))
    x_old = np.arange(audio.size) / src_rate
    x_new = np.arange(n_out) / dst_rate
    return np.interp(x_new, x_old, audio).astype(np.float32)


def read_wav(path: str) -> np.ndarray:
    import wave

    with wave.open(path, "rb") as wf:
        channels, width, rate = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Desteklenmeyen örnek genişliği: {width * 8} bit")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return resample(data, rate)


def load_audio(path: str) -> np.ndarray:
    """Ses dosyasını 16 kHz mono float32'ye çevirir.

    PCM WAV standart kütüphaneyle okunur; diğer biçimler (mp3, m4a, float WAV...)
    için faster-whisper'ın PyAV tabanlı çözücüsü kullanılır.
    """
    if path.lower().endswith(".wav"):
        try:
            return read_wav(path)
        except Exception:
            pass
    from faster_whisper import decode_audio

    return decode_audio(path, sampling_rate=SAMPLE_RATE)


def to_pcm16_chunks(audio: np.ndarray, chunk_ms: int = CHUNK_MS):
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    step = SAMPLE_RATE * chunk_ms // 1000
    for i in range(0, len(pcm), step):
        yield pcm[i : i + step].tobytes()


class Command(BaseCommand):
    help = "Ses dosyasını gerçek zamanlı hızda bir oturumun konuşmacı hattına besler (mikrofonsuz demo/test)."

    def add_arguments(self, parser):
        parser.add_argument("oda_kodu")
        parser.add_argument("dosya", help="WAV (veya PyAV'nin açabildiği herhangi bir ses dosyası)")
        parser.add_argument("--url", default="ws://127.0.0.1:8000", help="Sunucu adresi (varsayılan: %(default)s)")
        parser.add_argument("--hiz", type=float, default=1.0, help="Oynatma hızı çarpanı (1 = gerçek zamanlı)")
        parser.add_argument("--durdur", action="store_true", help="Dosya bitince oturumu 'bitti' durumuna al")
        parser.add_argument("--yerel", action="store_true", help="Sunucuya bağlanmadan bu süreçte çalıştır")
        parser.add_argument("--sessizlik", type=float, default=1.0, help="Sona eklenecek sessizlik (sn)")

    def handle(self, *args, **opts):
        code = normalize_room_code(opts["oda_kodu"])
        session = LectureSession.objects.select_related("speaker").filter(room_code=code).first()
        if session is None:
            raise CommandError(f"'{code}' kodlu oturum bulunamadı.")
        path = Path(opts["dosya"])
        if not path.exists():
            raise CommandError(f"Dosya bulunamadı: {path}")
        if opts["hiz"] <= 0:
            raise CommandError("--hiz pozitif olmalı")

        audio = load_audio(str(path))
        audio = np.concatenate([audio, np.zeros(int(SAMPLE_RATE * opts["sessizlik"]), dtype=np.float32)])
        self.stdout.write(f"Ses: {path.name} — {len(audio) / SAMPLE_RATE:.1f} sn, oturum: {session.title} ({code})")

        if opts["yerel"]:
            asyncio.run(self._run_local(session, audio, opts))
        else:
            asyncio.run(self._run_ws(session, audio, opts))

    # --- yardımcılar -------------------------------------------------------------
    def _print_partial(self, text: str):
        self.stdout.write(self.style.HTTP_NOT_MODIFIED(f"  … {text}"))

    def _print_final(self, event: dict):
        seg = event["segment"]
        s = seg["start_ms"] // 1000
        terms = ", ".join(t["term"] for t in event.get("terms", []))
        self.stdout.write(f"[{s // 60:02d}:{s % 60:02d}] {seg['text']}")
        if terms:
            self.stdout.write(self.style.SUCCESS(f"         terimler: {terms}"))

    async def _stream(self, chunks, send, speed: float):
        """Parçaları duvar saatine göre hizalı gönderir (kayma birikmez)."""
        interval = CHUNK_MS / 1000 / speed
        started = time.monotonic()
        for i, chunk in enumerate(chunks):
            await send(chunk)
            delay = started + (i + 1) * interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)

    # --- WebSocket modu ---------------------------------------------------------------
    def _make_login_cookie(self, user) -> tuple[str, object]:
        from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
        from django.contrib.sessions.backends.db import SessionStore

        store = SessionStore()
        store[SESSION_KEY] = str(user.pk)
        store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
        store[HASH_SESSION_KEY] = user.get_session_auth_hash()
        store.set_expiry(3600 * 6)
        store.create()
        return store.session_key, store

    async def _run_ws(self, session, audio, opts):
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:  # pragma: no cover
            raise CommandError("websockets paketi gerekli: pip install websockets") from exc
        from django.conf import settings

        base = opts["url"].rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme not in {"ws", "wss"}:
            raise CommandError("--url ws:// veya wss:// ile başlamalı")
        origin = ("https://" if parsed.scheme == "wss" else "http://") + parsed.netloc
        key, store = await database_sync_to_async(self._make_login_cookie)(session.speaker)
        cookie = f"{settings.SESSION_COOKIE_NAME}={key}"
        url = f"{base}/ws/konusmaci/{session.room_code}/"

        ready = asyncio.Event()
        flushed = asyncio.Event()

        async def reader(ws):
            async for raw in ws:
                if not isinstance(raw, str):
                    continue
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "partial" and msg.get("text"):
                    self._print_partial(msg["text"])
                elif kind == "final":
                    self._print_final(msg)
                elif kind == "info":
                    self.stdout.write(self.style.NOTICE(msg["message"]))
                    if msg["message"] == "Yayın başladı":
                        ready.set()
                elif kind == "error":
                    self.stderr.write(self.style.ERROR(msg["message"]))
                    ready.set()
                elif kind == "flushed":
                    flushed.set()

        try:
            async with connect(url, origin=origin, additional_headers={"Cookie": cookie}, max_size=None) as ws:
                task = asyncio.create_task(reader(ws))
                await ws.send(json.dumps({"action": "start"}))
                self.stdout.write("Model hazırlanıyor (ilk çalıştırmada indirme sürebilir)…")
                await asyncio.wait_for(ready.wait(), timeout=1800)
                self.stdout.write(self.style.SUCCESS(f"Gönderiliyor (hız ×{opts['hiz']:g}). Öğrenci sayfası: /oda/{session.room_code}/"))
                await self._stream(to_pcm16_chunks(audio), ws.send, opts["hiz"])
                await ws.send(json.dumps({"action": "stop" if opts["durdur"] else "flush"}))
                await asyncio.wait_for(flushed.wait(), timeout=600)
                task.cancel()
        except (OSError, asyncio.TimeoutError) as exc:
            raise CommandError(f"Sunucuya bağlanılamadı veya yanıt gelmedi ({url}): {exc!r}") from exc
        except Exception as exc:
            if exc.__class__.__name__ == "InvalidStatus":
                raise CommandError(f"Bağlantı reddedildi: {exc}. ALLOWED_HOSTS ve --url değerini kontrol edin.") from exc
            raise
        finally:
            await database_sync_to_async(store.delete)()
        self.stdout.write(self.style.SUCCESS("Bitti."))

    # --- yerel mod ---------------------------------------------------------------------
    async def _run_local(self, session, audio, opts):
        from channels.layers import get_channel_layer

        from asr.pipeline import LivePipeline

        ctx = await database_sync_to_async(services.get_session_context)(session.room_code)
        layer = get_channel_layer()

        async def publish(payload):
            # Redis kullanılıyorsa sunucudaki öğrencilere de ulaşır
            await layer.group_send(ctx.group_name, {"type": "caption.event", "payload": payload})

        async def on_partial(text):
            if text:
                self._print_partial(text)
            await publish({"type": "partial", "text": text})

        async def on_final(text, start_ms, end_ms):
            event = await database_sync_to_async(services.save_final_segment)(ctx.id, ctx.domain_id, text, start_ms, end_ms)
            self._print_final(event)
            await publish(event)

        offset = await database_sync_to_async(services.next_time_offset)(ctx.id)
        pipeline = LivePipeline(
            domain_name=ctx.domain_name,
            term_names=ctx.term_names,
            on_partial=on_partial,
            on_final=on_final,
            time_offset_ms=offset,
        )
        self.stdout.write("Model hazırlanıyor (ilk çalıştırmada indirme sürebilir)…")
        await pipeline.prepare()
        status = await database_sync_to_async(services.set_status)(ctx.id, True)
        await publish({"type": "status", "status": status})
        started = time.monotonic()
        await self._stream(to_pcm16_chunks(audio), pipeline.feed, opts["hiz"])
        await pipeline.close()
        elapsed = time.monotonic() - started
        if opts["durdur"]:
            status = await database_sync_to_async(services.set_status)(ctx.id, False)
            await publish({"type": "status", "status": status})
        self.stdout.write(
            self.style.SUCCESS(f"Bitti: {len(audio) / SAMPLE_RATE:.1f} sn ses, {elapsed:.1f} sn sürdü.")
        )
