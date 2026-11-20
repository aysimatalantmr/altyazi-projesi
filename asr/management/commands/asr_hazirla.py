"""Modelleri önceden indirir/yükler; ilk dersin başında beklemeyi önler.

    python manage.py asr_hazirla
"""
import time

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Whisper, Silero VAD ve zeyrek modellerini indirir ve kısa bir deneme yapar."

    def handle(self, *args, **opts):
        from asr.transcriber import get_partial_transcriber, get_transcriber
        from asr.vad import StreamingVAD
        from glossary.matcher import warm_up

        cfg = settings.ASR
        t = time.monotonic()
        vad = StreamingVAD(cfg["VAD_MODEL_PATH"])
        self.stdout.write(self.style.SUCCESS(f"Silero VAD hazır: {vad.path} (arayüz: {vad.kind})"))

        self.stdout.write(f"Whisper '{cfg['MODEL_SIZE']}' ({cfg['DEVICE']}/{cfg['COMPUTE_TYPE']}) yükleniyor…")
        sample = np.zeros(16000, dtype=np.float32)
        get_transcriber().transcribe(sample)
        self.stdout.write(self.style.SUCCESS("Whisper hazır."))
        if cfg["PARTIALS"] and cfg["PARTIAL_MODEL_SIZE"] and cfg["PARTIAL_MODEL_SIZE"] != cfg["MODEL_SIZE"]:
            self.stdout.write(f"Kısmi metin modeli '{cfg['PARTIAL_MODEL_SIZE']}' yükleniyor…")
            get_partial_transcriber().transcribe(sample)
            self.stdout.write(self.style.SUCCESS("Kısmi metin modeli hazır."))

        warm_up()
        self.stdout.write(self.style.SUCCESS(f"zeyrek hazır. Toplam {time.monotonic() - t:.1f} sn."))
