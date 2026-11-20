"""VAD olasılıklarına göre akan sesi konuşma bölümlerine ayırır.

Bu modül model bağımsızdır: `prob_fn` (512 örneklik çerçeve -> konuşma olasılığı)
dışarıdan verilir; böylece testlerde sahte bir VAD kullanılabilir.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np

SAMPLE_RATE = 16000
FRAME = 512  # Silero VAD 16 kHz'de 512 örneklik (32 ms) çerçeve ister
FRAME_MS = FRAME * 1000 / SAMPLE_RATE


@dataclass
class Segment:
    index: int
    audio: np.ndarray
    start_ms: int
    end_ms: int
    reason: str  # "silence" | "max" | "flush"


class SpeechSegmenter:
    def __init__(
        self,
        prob_fn: Callable[[np.ndarray], float],
        threshold: float = 0.5,
        min_silence_ms: int = 600,
        min_speech_ms: int = 250,
        speech_pad_ms: int = 200,
        max_segment_s: float = 10.0,
    ):
        self.prob_fn = prob_fn
        self.threshold = threshold
        self.neg_threshold = max(threshold - 0.15, 0.01)
        self.min_silence_frames = max(1, round(min_silence_ms / FRAME_MS))
        self.min_speech_frames = max(1, round(min_speech_ms / FRAME_MS))
        self.pad_frames = max(0, round(speech_pad_ms / FRAME_MS))
        self.max_frames = max(self.min_silence_frames + 1, round(max_segment_s * 1000 / FRAME_MS))
        # Uzun konuşmada kesme noktası bu pencere içindeki en sessiz çerçeveden seçilir
        self.cut_search_frames = min(round(2000 / FRAME_MS), self.max_frames // 2)

        self._pending = np.zeros(0, dtype=np.float32)
        self._frames_seen = 0  # akış başından beri işlenen çerçeve sayısı
        self._preroll: deque[np.ndarray] = deque(maxlen=self.pad_frames)
        self._seg_frames: list[np.ndarray] = []
        self._seg_probs: list[float] = []
        self._seg_start_frame = 0
        self._voiced = 0
        self._silence_run = 0
        self.in_speech = False
        self.segment_index = 0  # şu anki (açık) bölümün numarası

    # --- dış arayüz -------------------------------------------------------
    def feed(self, audio: np.ndarray) -> list[Segment]:
        """float32 [-1, 1] ses ekler; kapanan bölümleri döndürür."""
        if audio.size:
            self._pending = np.concatenate([self._pending, audio.astype(np.float32, copy=False)])
        done: list[Segment] = []
        while self._pending.size >= FRAME:
            frame, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            seg = self._process_frame(frame)
            if seg is not None:
                done.append(seg)
        return done

    def current_audio(self) -> np.ndarray | None:
        """Kısmi transkripsiyon için açık bölümün o ana kadarki sesi."""
        if not self.in_speech or not self._seg_frames:
            return None
        return np.concatenate(self._seg_frames)

    def flush(self) -> Segment | None:
        """Açık bölümü (varsa) zorla kapatır."""
        if self.in_speech and self._voiced >= self.min_speech_frames:
            return self._close(len(self._seg_frames), "flush")
        self._reset_segment()
        return None

    @property
    def elapsed_ms(self) -> int:
        return int(self._frames_seen * FRAME_MS)

    # --- iç mantık --------------------------------------------------------
    def _process_frame(self, frame: np.ndarray) -> Segment | None:
        prob = float(self.prob_fn(frame))
        self._frames_seen += 1

        if not self.in_speech:
            if prob >= self.threshold:
                self.in_speech = True
                self._seg_frames = list(self._preroll) + [frame]
                self._seg_probs = [0.0] * len(self._preroll) + [prob]
                self._seg_start_frame = self._frames_seen - len(self._seg_frames)
                self._voiced = 1
                self._silence_run = 0
                self._preroll.clear()
            else:
                self._preroll.append(frame)
            return None

        self._seg_frames.append(frame)
        self._seg_probs.append(prob)
        if prob >= self.threshold:
            self._voiced += 1
            self._silence_run = 0
        elif prob < self.neg_threshold:
            self._silence_run += 1
        else:
            # Kararsız bölge: sessizliği uzatmaz, sıfırlamaz da
            pass

        if self._silence_run >= self.min_silence_frames:
            keep = len(self._seg_frames) - self._silence_run + self.pad_frames
            if self._voiced < self.min_speech_frames:
                self._reset_segment()
                return None
            return self._close(keep, "silence")

        if len(self._seg_frames) >= self.max_frames:
            return self._close(self._best_cut(), "max")
        return None

    def _best_cut(self) -> int:
        """Son ~2 sn içinde konuşma olasılığı en düşük çerçeveden keser."""
        n = len(self._seg_frames)
        lo = n - self.cut_search_frames
        window = self._seg_probs[lo:n]
        return lo + int(np.argmin(window)) + 1

    def _close(self, keep: int, reason: str) -> Segment:
        keep = max(1, min(keep, len(self._seg_frames)))
        frames, rest = self._seg_frames[:keep], self._seg_frames[keep:]
        rest_probs = self._seg_probs[keep:]
        start_ms = int(self._seg_start_frame * FRAME_MS)
        end_ms = int((self._seg_start_frame + keep) * FRAME_MS)
        seg = Segment(self.segment_index, np.concatenate(frames), start_ms, end_ms, reason)
        self.segment_index += 1

        if reason == "max" and rest:
            # Konuşma sürüyor: kalan çerçevelerle yeni bölüm açık kalır
            self._seg_start_frame += keep
            self._seg_frames = rest
            self._seg_probs = rest_probs
            self._voiced = sum(1 for p in rest_probs if p >= self.threshold)
            self._silence_run = 0
        else:
            tail = self._seg_frames[-self.pad_frames :] if self.pad_frames else []
            self._reset_segment()
            self._preroll.extend(tail)
        return seg

    def _reset_segment(self):
        self.in_speech = False
        self._seg_frames = []
        self._seg_probs = []
        self._voiced = 0
        self._silence_run = 0
