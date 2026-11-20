"""Torch'suz, ONNX Runtime ile akış hâlinde Silero VAD.

Desteklenen iki model arayüzü:
  * faster-whisper paketindeki `silero_vad_v6.onnx`  -> girişler: input(N,576), h, c
  * Silero'nun resmi `silero_vad.onnx` (v5/v6)        -> girişler: input(1,576), state, sr
Model yolu sırayla: ASR_VAD_MODEL_PATH -> faster-whisper içindeki dosya -> models/silero_vad.onnx
(yoksa resmi depodan indirilir).
"""
from __future__ import annotations

import logging
import threading
import urllib.request
from pathlib import Path

import numpy as np

logger = logging.getLogger("asr.vad")

OFFICIAL_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
FRAME = 512
CONTEXT = 64

_session_cache: dict[str, object] = {}
_lock = threading.Lock()


def _project_model_dir() -> Path:
    from django.conf import settings

    return Path(settings.BASE_DIR) / "models"


def _load_session(path: str):
    import onnxruntime

    with _lock:
        if path not in _session_cache:
            opts = onnxruntime.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            opts.log_severity_level = 4
            _session_cache[path] = onnxruntime.InferenceSession(
                path, providers=["CPUExecutionProvider"], sess_options=opts
            )
        return _session_cache[path]


def _detect_kind(session) -> str | None:
    names = {i.name for i in session.get_inputs()}
    if {"input", "h", "c"} <= names:
        return "hc"
    if {"input", "state", "sr"} <= names:
        return "state"
    return None


def _candidate_paths(explicit: str | None) -> list[str]:
    paths = []
    if explicit:
        paths.append(explicit)
    try:
        from faster_whisper.utils import get_assets_path

        assets = Path(get_assets_path())
        paths += [str(p) for p in sorted(assets.glob("silero_vad*.onnx"), reverse=True)]
    except Exception:  # pragma: no cover - faster-whisper yoksa
        pass
    paths.append(str(_project_model_dir() / "silero_vad.onnx"))
    return paths


def download_official_model() -> str:
    target = _project_model_dir() / "silero_vad.onnx"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Silero VAD modeli indiriliyor: %s", OFFICIAL_URL)
        tmp = target.with_suffix(".part")
        urllib.request.urlretrieve(OFFICIAL_URL, tmp)
        tmp.replace(target)
    return str(target)


def resolve_model(explicit: str | None = None) -> tuple[str, str]:
    """(yol, arayüz türü) döndürür; uygun model yoksa resmi modeli indirir."""
    for path in _candidate_paths(explicit):
        if not Path(path).exists():
            continue
        try:
            kind = _detect_kind(_load_session(path))
        except Exception as exc:  # bozuk dosya vb.
            logger.warning("VAD modeli yüklenemedi (%s): %s", path, exc)
            continue
        if kind:
            return path, kind
        logger.warning("VAD modelinin arayüzü tanınmadı, atlanıyor: %s", path)
    path = download_official_model()
    kind = _detect_kind(_load_session(path))
    if not kind:
        raise RuntimeError("Silero VAD ONNX modeli beklenen arayüze sahip değil")
    return path, kind


class StreamingVAD:
    """Her 512 örneklik (32 ms) çerçeve için konuşma olasılığı döndürür.

    Durum (LSTM gizli durumu + 64 örneklik bağlam) çağrılar arasında korunur;
    her konuşmacı akışı kendi örneğini kullanmalıdır (oturum paylaşılır).
    """

    def __init__(self, model_path: str | None = None, sample_rate: int = 16000):
        if sample_rate != 16000:
            raise ValueError("Yalnızca 16 kHz destekleniyor")
        self.path, self.kind = resolve_model(model_path)
        self.session = _load_session(self.path)
        self.reset()

    def reset(self):
        self._context = np.zeros(CONTEXT, dtype=np.float32)
        if self.kind == "hc":
            self._h = np.zeros((1, 1, 128), dtype=np.float32)
            self._c = np.zeros((1, 1, 128), dtype=np.float32)
        else:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            self._sr = np.array(16000, dtype=np.int64)

    def __call__(self, frame: np.ndarray) -> float:
        frame = np.asarray(frame, dtype=np.float32)
        if frame.shape != (FRAME,):
            raise ValueError(f"Çerçeve {FRAME} örnek olmalı, gelen: {frame.shape}")
        x = np.concatenate([self._context, frame])[None, :]
        self._context = frame[-CONTEXT:].copy()
        if self.kind == "hc":
            out, self._h, self._c = self.session.run(None, {"input": x, "h": self._h, "c": self._c})
        else:
            out, self._state = self.session.run(None, {"input": x, "state": self._state, "sr": self._sr})
        return float(np.asarray(out).reshape(-1)[0])
