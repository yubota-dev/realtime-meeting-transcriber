"""複数の音声ストリーム（自分／相手）を、それぞれ silero-VAD で発話区間に
切り出し、faster-whisper で文字起こし、非日本語なら qwen2.5:14b で日本語訳。

タイムスタンプは「発話開始時刻（録音時刻）」で打つ。これは音声コールバックが
各フレームに付けた壁時計時刻を辿るので、whisper や翻訳の処理遅延に左右されない。
（従来は確定時刻＝処理完了時に打っていたため、長い発話ほど時刻がずれていた）

Whisper モデルは1つを共有（VRAM 節約・並列transcribe回避）し、ストリームごとに
VAD と発話バッファを分ける。別スレッドで動く。
"""
import datetime as dt
import queue
import threading
import time

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


class _StreamState:
    """1ストリーム分の VAD・発話バッファ・録音時刻ポインタ。"""

    def __init__(self, speaker, audio_queue, vad_model):
        self.speaker = speaker
        self.q = audio_queue
        self.vad = VADIterator(vad_model, sampling_rate=SAMPLE_RATE)
        self.buf = np.zeros(0, dtype=np.float32)  # VAD窓に満たない端数
        self.utter = []                           # 発話中のサンプル
        self.in_speech = False
        self.clock = 0.0                          # 現在処理中フレームの録音時刻
        self.utter_start = None                   # 発話開始の録音時刻


class Transcriber(threading.Thread):
    def __init__(self, sources, on_entry, stop_event):
        """sources: list[tuple[str speaker, queue.Queue audio_queue]]
        audio_queue の要素は (capture_time: float, samples: np.ndarray)"""
        super().__init__(daemon=True)
        self.on_entry = on_entry          # callback(entry_dict)
        self.stop_event = stop_event

        print("[whisper] large-v3 をロード中...")
        self.model = WhisperModel("large-v3", device="cuda", compute_type="float16")
        self.vad_model = load_silero_vad()  # 本体は共有、Iterator だけ分ける
        self.streams = [_StreamState(spk, q, self.vad_model) for spk, q in sources]

    def run(self):
        print("[whisper] 待機中")
        while not self.stop_event.is_set():
            got_any = False
            for st in self.streams:
                try:
                    while True:
                        t_chunk, chunk = st.q.get_nowait()
                        got_any = True
                        st.clock = t_chunk
                        st.buf = np.concatenate([st.buf, chunk])
                        while len(st.buf) >= VAD_WINDOW:
                            window = st.buf[:VAD_WINDOW]
                            st.buf = st.buf[VAD_WINDOW:]
                            wt = st.clock
                            st.clock += VAD_WINDOW / SAMPLE_RATE
                            self._feed_vad(st, window, wt)
                except queue.Empty:
                    pass
            if not got_any:
                time.sleep(0.05)
        for st in self.streams:           # 終了時に残りをフラッシュ
            if st.utter:
                self._finalize(st)

    def _feed_vad(self, st, window, wt):
        if st.in_speech:
            st.utter.append(window)
        res = st.vad(torch.from_numpy(window), return_seconds=False)
        if res is None:
            return
        if "start" in res:
            st.in_speech = True
            st.utter = [window]
            st.utter_start = wt           # ★発話開始の録音時刻を記録
        if "end" in res:
            st.in_speech = False
            self._finalize(st)

    def _finalize(self, st):
        if not st.utter:
            return
        audio = np.concatenate(st.utter)
        utter_start = st.utter_start
        st.utter = []
        st.utter_start = None
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

        # 発話開始時刻でタイムスタンプを打つ（処理遅延に依らない）
        when = utter_start if utter_start is not None else time.time()
        self.on_entry({
            "ts": dt.datetime.fromtimestamp(when).strftime("%H:%M:%S"),
            "speaker": st.speaker,
            "lang": lang,
            "original": text,
            "ja": ja,
        })
