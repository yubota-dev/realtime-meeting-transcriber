"""WASAPIループバックでスピーカー出力（＝会議相手の声）を取り込み、
16kHzモノラルの float32 フレームをキューに流す。

Whisper は 16kHz モノラルを要求するため、デバイスの既定レート
（通常 48kHz ステレオ）から変換する。
"""
import math
import queue
import threading

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample_poly

TARGET_RATE = 16000


class LoopbackRecorder:
    def __init__(self):
        self.q = queue.Queue()
        self._stop = threading.Event()
        self._pa = pyaudio.PyAudio()
        self._stream = None
        self._device = self._find_loopback()
        self._rate = int(self._device["defaultSampleRate"])
        self._channels = int(self._device["maxInputChannels"])
        g = math.gcd(TARGET_RATE, self._rate)
        self._up, self._down = TARGET_RATE // g, self._rate // g

    def _find_loopback(self):
        """既定の出力デバイスに対応するループバックデバイスを探す。"""
        wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        spk = self._pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if spk.get("isLoopbackDevice"):
            return spk
        for lb in self._pa.get_loopback_device_info_generator():
            if spk["name"] in lb["name"]:
                return lb
        raise RuntimeError("ループバックデバイスが見つかりません")

    def _callback(self, in_data, frame_count, time_info, status):
        if self._stop.is_set():
            return (None, pyaudio.paComplete)
        audio = np.frombuffer(in_data, dtype=np.float32)
        if self._channels > 1:
            audio = audio.reshape(-1, self._channels).mean(axis=1)  # ステレオ→モノラル
        if self._up != self._down:
            audio = resample_poly(audio, self._up, self._down)      # →16kHz
        self.q.put(audio.astype(np.float32))
        return (None, pyaudio.paContinue)

    def start(self):
        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self._channels,
            rate=self._rate,
            frames_per_buffer=4096,
            input=True,
            input_device_index=self._device["index"],
            stream_callback=self._callback,
        )
        self._stream.start_stream()
        print(f"[audio] 取り込み開始: {self._device['name']} "
              f"({self._rate}Hz, {self._channels}ch → {TARGET_RATE}Hz mono)")

    def stop(self):
        self._stop.set()
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        self._pa.terminate()
