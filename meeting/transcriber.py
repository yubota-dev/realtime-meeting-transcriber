"""複数音声streamのVAD分割とfaster-whisper文字起こし。"""
from __future__ import annotations

import datetime as dt
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass

import numpy as np
import torch
from faster_whisper import WhisperModel
from silero_vad import VADIterator, load_silero_vad

from .audio import AudioChunk

SAMPLE_RATE = 16000
VAD_WINDOW = 512
MIN_UTTER_SEC = 0.4
MIN_TEXT_LEN = 3
SUPPORTED_LANGUAGES = ("ja", "en", "zh")
LOW_AVG_LOGPROB = -1.0
HIGH_NO_SPEECH_PROB = 0.6
HIGH_COMPRESSION_RATIO = 2.4

_HALLUCINATION_PHRASES = (
    "ご視聴ありがとうございました",
    "チャンネル登録",
    "字幕 by",
    "thank you for watching",
    "subscribe",
)


def is_hallucination_candidate(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).lower()
    if any(p.replace(" ", "") in compact for p in _HALLUCINATION_PHRASES):
        return True
    units = re.findall(r"[^。.!?！？]+[。.!?！？]?", text)
    normalized = [re.sub(r"\s+", "", x).lower() for x in units if x.strip()]
    return len(normalized) >= 3 and len(set(normalized)) <= len(normalized) // 2


def resolve_language(info, language_lock: str = "auto") -> tuple[str, dict[str, float]]:
    if language_lock != "auto":
        return language_lock, {language_lock: 1.0}
    probs = dict(getattr(info, "all_language_probs", None) or [])
    filtered = {k: float(probs.get(k, 0.0)) for k in SUPPORTED_LANGUAGES}
    detected = getattr(info, "language", None)
    if detected in SUPPORTED_LANGUAGES:
        return detected, filtered
    if any(filtered.values()):
        return max(filtered, key=filtered.get), filtered
    return "ja", filtered


def _segment_metadata(segments) -> dict:
    segments = list(segments)
    if not segments:
        return {
            "no_speech_prob": 1.0,
            "avg_logprob": -99.0,
            "compression_ratio": 0.0,
        }
    durations = np.array([max(float(s.end) - float(s.start), 0.01) for s in segments])
    weights = durations / durations.sum()
    return {
        "no_speech_prob": float(max(getattr(s, "no_speech_prob", 0.0) for s in segments)),
        "avg_logprob": float(sum(
            float(getattr(s, "avg_logprob", -99.0)) * w for s, w in zip(segments, weights)
        )),
        "compression_ratio": float(max(
            getattr(s, "compression_ratio", 0.0) for s in segments
        )),
    }


def _low_confidence(meta: dict) -> bool:
    return (
        meta["no_speech_prob"] >= HIGH_NO_SPEECH_PROB
        or meta["avg_logprob"] <= LOW_AVG_LOGPROB
        or meta["compression_ratio"] >= HIGH_COMPRESSION_RATIO
    )


@dataclass
class _StreamState:
    speaker: str
    q: queue.Queue
    language_lock: str = "auto"

    def __post_init__(self):
        # Silero model自身がrecurrent stateを持つため、入力stream間で共有しない。
        self.vad = VADIterator(load_silero_vad(), sampling_rate=SAMPLE_RATE)
        self.buf = np.zeros(0, dtype=np.float32)
        self.buf_start = None
        self.utter: list[np.ndarray] = []
        self.in_speech = False
        self.clock = 0.0
        self.utter_start = None
        self.pending_dropped_samples = 0


class Transcriber(threading.Thread):
    def __init__(self, sources, on_entry, stop_event, *, model_name="large-v3",
                 mode="concurrent", initial_prompt=None, hotwords=None):
        """sources: list[(speaker, audio_queue, language_lock)]。"""
        super().__init__(daemon=True)
        self.on_entry = on_entry
        self.stop_event = stop_event
        self.mode = mode
        self.max_utter_sec = 8 if mode == "translate" else 20
        self.english_translate_max_utter_sec = 4
        self.initial_prompt = initial_prompt
        self.hotwords = hotwords
        print(f"[whisper] {model_name} をロード中...")
        self.model = WhisperModel(model_name, device="cuda", compute_type="float16")
        self.streams = [_StreamState(*source) for source in sources]

    def set_context(self, initial_prompt=None, hotwords=None):
        """会話内容から自動検出したASR contextを後続発話へ適用する。"""
        self.initial_prompt = initial_prompt
        self.hotwords = hotwords

    def _queues_empty(self):
        return all(st.q.empty() for st in self.streams)

    def run(self):
        print("[whisper] 待機中")
        while not self.stop_event.is_set() or not self._queues_empty():
            got_any = False
            for st in self.streams:
                try:
                    while True:
                        item = st.q.get_nowait()
                        got_any = True
                        if isinstance(item, AudioChunk):
                            t_chunk, chunk = item.capture_time, item.samples
                            st.pending_dropped_samples += item.dropped_samples
                        else:  # 旧tuple入力との互換
                            t_chunk, chunk = item[:2]
                        if st.pending_dropped_samples:
                            self._emit_gap(st, t_chunk, st.pending_dropped_samples)
                            st.pending_dropped_samples = 0
                        if len(st.buf) == 0:
                            st.buf_start = t_chunk
                        st.buf = np.concatenate([st.buf, chunk])
                        while len(st.buf) >= VAD_WINDOW:
                            window = st.buf[:VAD_WINDOW]
                            st.buf = st.buf[VAD_WINDOW:]
                            wt = st.buf_start
                            st.buf_start += VAD_WINDOW / SAMPLE_RATE
                            self._feed_vad(st, window, wt)
                        if len(st.buf) == 0:
                            st.buf_start = None
                except queue.Empty:
                    pass
            if not got_any:
                time.sleep(0.05)
        for st in self.streams:
            if len(st.buf):
                padded = np.pad(st.buf, (0, VAD_WINDOW - len(st.buf)))
                self._feed_vad(st, padded, st.buf_start or time.time())
                st.buf = np.zeros(0, dtype=np.float32)
                st.buf_start = None
            if st.utter:
                self._finalize(st)

    def _emit_gap(self, st, when, dropped_samples):
        captured = dt.datetime.fromtimestamp(when)
        self.on_entry({
            "type": "gap",
            "event_id": str(uuid.uuid4()),
            "ts": captured.strftime("%H:%M:%S.%f")[:-3],
            "capture_time": when,
            "captured_at": captured.isoformat(timespec="milliseconds"),
            "speaker": st.speaker,
            "dropped_samples": int(dropped_samples),
            "dropped_seconds": round(dropped_samples / SAMPLE_RATE, 3),
            "pass": "realtime",
        })

    def _feed_vad(self, st, window, wt):
        if st.in_speech:
            st.utter.append(window)
        res = st.vad(torch.from_numpy(window), return_seconds=False)
        if res is not None and "start" in res:
            st.in_speech = True
            st.utter = [window]
            st.utter_start = wt
        if res is not None and "end" in res:
            st.in_speech = False
            self._finalize(st)
        elif (st.in_speech and sum(map(len, st.utter))
              >= self._max_utter_seconds(st) * SAMPLE_RATE):
            self._finalize(st)
            st.in_speech = False
            st.vad.reset_states()

    def _max_utter_seconds(self, st):
        if self.mode == "translate" and st.language_lock == "en":
            return self.english_translate_max_utter_sec
        return self.max_utter_sec

    def _transcribe(self, audio, language_lock="auto", beam_size=5):
        forced = None if language_lock == "auto" else language_lock
        segments, info = self.model.transcribe(
            audio, language=forced, beam_size=beam_size, vad_filter=True,
            no_speech_threshold=HIGH_NO_SPEECH_PROB,
            condition_on_previous_text=False,
            initial_prompt=self.initial_prompt, hotwords=self.hotwords,
        )
        segments = list(segments)
        lang, probs = resolve_language(info, language_lock)
        # ja/en/zh以外へ判定された場合は、許可言語内の最大確率で再実行する。
        if forced is None and getattr(info, "language", None) not in SUPPORTED_LANGUAGES:
            segments, info = self.model.transcribe(
                audio, language=lang, beam_size=beam_size, vad_filter=True,
                no_speech_threshold=HIGH_NO_SPEECH_PROB,
                condition_on_previous_text=False,
                initial_prompt=self.initial_prompt, hotwords=self.hotwords,
            )
            segments = list(segments)
        return segments, info, lang, probs

    def _finalize(self, st):
        if not st.utter:
            return
        audio = np.concatenate(st.utter)
        utter_start = st.utter_start
        st.utter = []
        st.utter_start = None
        if len(audio) < SAMPLE_RATE * MIN_UTTER_SEC:
            return
        segments, info, lang, probs = self._transcribe(audio, st.language_lock)
        self._emit_transcript(
            segments, lang, probs, st.speaker,
            utter_start if utter_start is not None else time.time(),
            pass_name="realtime",
        )

    def _emit_transcript(self, segments, lang, probs, speaker, when, *, pass_name):
        text = "".join(s.text for s in segments).strip()
        if len(text) < MIN_TEXT_LEN:
            return
        meta = _segment_metadata(segments)
        low = _low_confidence(meta)
        hallucination = is_hallucination_candidate(text)
        captured = dt.datetime.fromtimestamp(when)
        self.on_entry({
            "type": "transcript",
            "event_id": str(uuid.uuid4()),
            "ts": captured.strftime("%H:%M:%S.%f")[:-3],
            "capture_time": when,
            "captured_at": captured.isoformat(timespec="milliseconds"),
            "speaker": speaker,
            "lang": lang,
            "language_probs": probs,
            "original": text,
            "ja": "",
            "metadata": meta,
            "low_confidence": low,
            "hallucination_candidate": hallucination,
            "discard_candidate": bool(low and hallucination),
            "pass": pass_name,
        })

    def reprocess_file(self, audio_path, speaker, started_at, language_lock="auto"):
        """保存WAVをlarge-v3で会議後に高精度再処理する。"""
        segments, info, lang, probs = self._transcribe(
            str(audio_path), language_lock, beam_size=10,
        )
        for seg in segments:
            self._emit_transcript(
                [seg], lang, probs, speaker, started_at + float(seg.start),
                pass_name="accuracy",
            )
