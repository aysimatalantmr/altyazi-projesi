"""faster-whisper sarmalayıcısı (süreç başına tek model)."""
from __future__ import annotations

import logging
import os
import re
import threading
import time

import numpy as np
from django.conf import settings

logger = logging.getLogger("asr.whisper")

# Whisper'ın Türkçe sessizlik/gürültüde sık ürettiği "halüsinasyon" kalıpları
_HALLUCINATIONS = [
    r"altyaz[ıi]\s*m\.?\s*k\.?",
    r"altyaz[ıi].*(?:taraf[ıi]ndan|hazırlan)",
    r"izledi[ğg]iniz i[çc]in te[şs]ekk[üu]r",
    r"abone olmay[ıi] unutmay[ıi]n",
    r"bir sonraki videoda g[öo]r[üu][şs]mek",
    r"^\W*(?:m[üu]zik|alk[ıi][şs]|g[üu]l[üu][şs]meler)\W*$",
]
_HALLUCINATION_RE = re.compile("|".join(_HALLUCINATIONS), re.IGNORECASE)


def is_hallucination(text: str) -> bool:
    return bool(_HALLUCINATION_RE.search(text))


class WhisperTranscriber:
    def __init__(self, model_size: str | None = None):
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from faster_whisper import WhisperModel

        cfg = settings.ASR
        self.model_size = model_size or cfg["MODEL_SIZE"]
        started = time.monotonic()
        logger.info(
            "Whisper modeli yükleniyor: %s (%s, %s) — ilk çalıştırmada indirilir",
            self.model_size,
            cfg["DEVICE"],
            cfg["COMPUTE_TYPE"],
        )
        self.model = WhisperModel(
            self.model_size,
            device=cfg["DEVICE"],
            compute_type=cfg["COMPUTE_TYPE"],
            cpu_threads=cfg["CPU_THREADS"],
            download_root=cfg["MODEL_DIR"],
        )
        self.language = cfg["LANGUAGE"]
        self.beam_size = cfg["BEAM_SIZE"]
        self._lock = threading.Lock()
        logger.info("Whisper modeli hazır: %s (%.1f sn)", self.model_size, time.monotonic() - started)

    def transcribe(self, audio: np.ndarray, prompt: str | None = None, final: bool = True) -> str:
        if audio.size < 16000 * 0.3:
            return ""
        with self._lock:
            segments, _info = self.model.transcribe(
                audio,
                language=self.language,
                task="transcribe",
                beam_size=self.beam_size if final else 1,
                best_of=self.beam_size if final else 1,
                temperature=0.0 if not final else [0.0, 0.2, 0.4],
                initial_prompt=prompt or None,
                condition_on_previous_text=False,
                without_timestamps=True,
                vad_filter=False,  # bölümleme zaten bizim VAD'imizde yapıldı
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
                suppress_blank=True,
            )
            parts = []
            for seg in segments:
                if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
                    continue
                text = seg.text.strip()
                if text and not is_hallucination(text):
                    parts.append(text)
        return " ".join(parts).strip()


_instances: dict[str, WhisperTranscriber] = {}
_instance_lock = threading.Lock()


def get_transcriber(model_size: str | None = None) -> WhisperTranscriber:
    """Model boyutu başına süreçte tek örnek."""
    size = model_size or settings.ASR["MODEL_SIZE"]
    if size not in _instances:
        with _instance_lock:
            if size not in _instances:
                _instances[size] = WhisperTranscriber(size)
    return _instances[size]


def get_partial_transcriber() -> WhisperTranscriber:
    return get_transcriber(settings.ASR["PARTIAL_MODEL_SIZE"] or None)


def build_prompt(domain_name: str, term_names: list[str], previous_text: str = "", max_chars: int = 600) -> str:
    """initial_prompt: alan adı + terimler (+ varsa önceki cümle).

    Whisper istemin sonunu daha çok dikkate alır ve ~224 token'dan fazlasını
    baştan kırpar; bu yüzden toplam uzunluk sınırlanır ve önceki cümle sona konur.
    """
    tail = ""
    if previous_text:
        tail = " " + previous_text.strip()[-160:]
    head = f"{domain_name} dersi. Terimler: "
    budget = max(0, max_chars - len(head) - len(tail) - 1)
    chosen: list[str] = []
    used = 0
    for name in term_names:
        cost = len(name) + 2
        if used + cost > budget:
            break
        chosen.append(name)
        used += cost
    prompt = head + ", ".join(chosen) + "." + tail if chosen else (domain_name + " dersi." + tail)
    return prompt.strip()
