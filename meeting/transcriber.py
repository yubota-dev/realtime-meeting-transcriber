"""silero-VAD で発話区間を切り出し、faster-whisper で文字起こし、
非日本語なら qwen2.5:14b で日本語に訳す。別スレッドで動く。
"""
import datetime as dt
import threading

import numpy as np
import torch
from faster_whisper import WhisperModel
from silero_vad import load_silero_vad, VADIterator

from . import llm

SAMPLE_RATE = 16000
VAD_WINDOW = 512        # silero の固定窓サイズ（16kHz）
MIN_UTTER_SEC = 0.4     # これ未満の断片は捨てる
MIN_TEXT_LEN = 3        # これ未満の文字数は幻聴とみなし破棄
MIN_TRANSLATE_LEN = 8   # これ未満の非日本語は翻訳しない（誤翻訳防止）
LANG_NAME = {"ja": "日本語", "en": "英語", "zh": "中国語"}


class Transcriber(threading.Thread):
    def __init__(self, audio_queue, on_entry, stop_event):
        super().__init__(daemon=True)
        self.audio_queue = audio_queue
        self.on_entry = on_entry          # callback(entry_dict)
        self.stop_event = stop_event

        print("[whisper] large-v3 をロード中...")
        self.model = WhisperModel("large-v3", device="cuda", compute_type="float16")
        self.vad_model = load_silero_vad()
        self.vad = VADIterator(self.vad_model, sampling_rate=SAMPLE_RATE)

        self._buf = np.zeros(0, dtype=np.float32)  # VAD窓に満たない端数を貯める
        self._utter = []                           # 発話中のサンプル
        self._in_speech = False

    def run(self):
        print("[whisper] 待機中")
        while not self.stop_event.is_set():
            try:
                chunk = self.audio_queue.get(timeout=0.5)
            except Exception:
                continue
            self._buf = np.concatenate([self._buf, chunk])
            while len(self._buf) >= VAD_WINDOW:
                window = self._buf[:VAD_WINDOW]
                self._buf = self._buf[VAD_WINDOW:]
                self._feed_vad(window)
        if self._utter:          # 終了時に残りをフラッシュ
            self._finalize()

    def _feed_vad(self, window):
        if self._in_speech:
            self._utter.append(window)
        res = self.vad(torch.from_numpy(window), return_seconds=False)
        if res is None:
            return
        if "start" in res:
            self._in_speech = True
            self._utter = [window]
        if "end" in res:
            self._in_speech = False
            self._finalize()

    def _finalize(self):
        if not self._utter:
            return
        audio = np.concatenate(self._utter)
        self._utter = []
        if len(audio) < SAMPLE_RATE * MIN_UTTER_SEC:
            return

        segments, info = self.model.transcribe(
            audio,
            language=None,
            beam_size=5,
            vad_filter=True,                  # 無音区間を除外し幻聴を抑制
            no_speech_threshold=0.6,          # 無音判定を強める
            condition_on_previous_text=False, # 直前テキストへの引きずられ防止
        )
        text = "".join(s.text for s in segments).strip()
        if len(text) < MIN_TEXT_LEN:          # 極短フラグメントは破棄
            return

        lang = info.language
        ja = ""
        if lang != "ja" and len(text) >= MIN_TRANSLATE_LEN:
            try:
                ja = llm.translate_to_ja(text, LANG_NAME.get(lang, lang))
            except Exception as ex:
                ja = f"(翻訳失敗: {ex})"

        self.on_entry({
            "ts": dt.datetime.now().strftime("%H:%M:%S"),
            "lang": lang,
            "original": text,
            "ja": ja,
        })
