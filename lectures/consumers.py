"""WebSocket tüketicileri.

/ws/konusmaci/<oda>/  : konuşmacı — binary 16 kHz Int16 PCM + JSON kontrol mesajları
/ws/ogrenci/<oda>/    : öğrenci   — yalnızca dinler

Sunucudan gelen olaylar (JSON):
  history {status, segments, terms} · partial {text} · final {segment, terms}
  status {status} · info {message} · error {message} · flushed
"""
from __future__ import annotations

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from . import services

logger = logging.getLogger("lectures.ws")

CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


class CaptionGroupMixin:
    """Oturum grubuna yayınlanan olayları istemciye iletir."""

    ctx: services.SessionContext | None = None

    async def caption_event(self, event):
        await self.send(text_data=json.dumps(event["payload"], ensure_ascii=False))

    async def broadcast(self, payload: dict):
        await self.channel_layer.group_send(self.ctx.group_name, {"type": "caption.event", "payload": payload})

    async def send_json(self, payload: dict):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False))

    async def join_group(self):
        await self.channel_layer.group_add(self.ctx.group_name, self.channel_name)

    async def disconnect(self, code):
        if self.ctx:
            await self.channel_layer.group_discard(self.ctx.group_name, self.channel_name)


class StudentConsumer(CaptionGroupMixin, AsyncWebsocketConsumer):
    async def connect(self):
        room_code = self.scope["url_route"]["kwargs"]["room_code"]
        self.ctx = await database_sync_to_async(services.get_session_context)(room_code)
        await self.accept()
        if self.ctx is None:
            await self.close(code=CLOSE_NOT_FOUND)
            return
        await self.join_group()
        await self.send_json(await database_sync_to_async(services.session_history)(self.ctx.id))

    async def receive(self, text_data=None, bytes_data=None):
        pass  # öğrenci yalnızca dinler


class SpeakerConsumer(CaptionGroupMixin, AsyncWebsocketConsumer):
    pipeline = None

    async def connect(self):
        room_code = self.scope["url_route"]["kwargs"]["room_code"]
        self.ctx = await database_sync_to_async(services.get_session_context)(room_code)
        user = self.scope.get("user")
        await self.accept()
        if self.ctx is None:
            await self.close(code=CLOSE_NOT_FOUND)
            return
        if not (user and user.is_authenticated and (user.pk == self.ctx.speaker_id or user.is_superuser)):
            self.ctx = None
            await self.close(code=CLOSE_FORBIDDEN)
            return
        await self.join_group()
        await self.send_json(await database_sync_to_async(services.session_history)(self.ctx.id))

    async def disconnect(self, code):
        # Bağlantı koparsa açık cümleyi kaybetmeyelim; oturum "canlı" kalır,
        # konuşmacı yeniden bağlandığında yayın sürer.
        await self._close_pipeline()
        await super().disconnect(code)

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data is not None:
            if self.pipeline is not None:
                await self.pipeline.feed(bytes_data)
            return
        try:
            msg = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return
        action = msg.get("action")
        if action == "start":
            await self._start()
        elif action == "stop":
            await self._stop()
        elif action == "flush":
            if self.pipeline is not None:
                await self.pipeline.flush()
            await self._send_flushed()

    async def _send_flushed(self):
        # Kendi kanalımız üzerinden gönderiyoruz: böylece kuyrukta bekleyen
        # son "final" olaylarından SONRA ulaşır (doğrudan send() onları sollardı).
        await self.channel_layer.send(self.channel_name, {"type": "caption.event", "payload": {"type": "flushed"}})

    async def _start(self):
        if self.pipeline is None:
            from asr.pipeline import LivePipeline

            await self.send_json({"type": "info", "message": "Konuşma tanıma hazırlanıyor…"})
            offset = await database_sync_to_async(services.next_time_offset)(self.ctx.id)
            pipeline = LivePipeline(
                domain_name=self.ctx.domain_name,
                term_names=self.ctx.term_names,
                on_partial=self._on_partial,
                on_final=self._on_final,
                time_offset_ms=offset,
            )
            try:
                await pipeline.prepare()
            except Exception as exc:
                logger.exception("Konuşma tanıma başlatılamadı")
                await self.send_json({"type": "error", "message": f"Konuşma tanıma başlatılamadı: {exc}"})
                return
            self.pipeline = pipeline
        status = await database_sync_to_async(services.set_status)(self.ctx.id, True)
        await self.broadcast({"type": "status", "status": status})
        await self.send_json({"type": "info", "message": "Yayın başladı"})

    async def _stop(self):
        await self._close_pipeline()
        status = await database_sync_to_async(services.set_status)(self.ctx.id, False)
        await self.broadcast({"type": "status", "status": status})
        await self._send_flushed()

    async def _close_pipeline(self):
        pipeline, self.pipeline = self.pipeline, None
        if pipeline is not None:
            try:
                await pipeline.close()
            except Exception:
                logger.exception("Ses hattı kapatılırken hata")

    async def _on_partial(self, text: str):
        await self.broadcast({"type": "partial", "text": text})

    async def _on_final(self, text: str, start_ms: int, end_ms: int):
        event = await database_sync_to_async(services.save_final_segment)(
            self.ctx.id, self.ctx.domain_id, text, start_ms, end_ms
        )
        await self.broadcast(event)
