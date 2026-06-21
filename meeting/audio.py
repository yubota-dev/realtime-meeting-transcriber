"""WASAPI で2系統の音声を取り込み、16kHzモノラルの float32 フレームを
それぞれのキューに流す。各フレームには「録音時刻（壁時計）」を付与し、
タイムスタンプが処理遅延に左右されないようにする。

- LoopbackRecorder : スピーカー出力（＝会議相手の声）をループバックで取得
- MicRecorder      : 既定のマイク入力（＝自分の声）を取得

キューに入る要素は (capture_time: float, samples: np.ndarray)。
capture_time はそのフレーム先頭の time.time() 相当（ストリーム開始＋経過秒）。

デバイス名の確認:  python -m meeting.audio
出力デバイス指定:  環境変数 LOOPBACK_HINT（例: "ヘッドセット"）
入力デバイス指定:  環境変数 MIC_HINT（例: "ヘッドセット"）
"""
import math
import os
import queue
import threading
import time

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample_poly

TARGET_RATE = 16000

# 環境変数で対象デバイスを名前指定できる
LOOPBACK_HINT = os.environ.get("LOOPBACK_HINT", "")
MIC_HINT = os.environ.get("MIC_HINT", "")


class _BaseRecorder:
    """デバイス選択以外（リサンプル・モノラル化・時刻付与・管理）の共通処理。"""

    label = "audio"

    def __init__(self):
        self.q = queue.Queue()
        self._stop = threading.Event()
        self._pa = pyaudio.PyAudio()
        self._stream = None
        self._device = self._find_device()
        self._rate = int(self._device["defaultSampleRate"])
        self._channels = max(1, int(self._device["maxInputChannels"]))
        g = math.gcd(TARGET_RATE, self._rate)
        self._up, self._down = TARGET_RATE // g, self._rate // g
        self._t0 = 0.0          # ストリーム開始時刻
        self._emitted = 0       # これまでにキューへ出した 16kHz サンプル数

    def _find_device(self):
        raise NotImplementedError

    def _callback(self, in_data, frame_count, time_info, status):
        if self._stop.is_set():
            return (None, pyaudio.paComplete)
        audio = np.frombuffer(in_data, dtype=np.float32)
        if self._channels > 1:
            audio = audio.reshape(-1, self._channels).mean(axis=1)  # ステレオ→モノラル
        if self._up != self._down:
            audio = resample_poly(audio, self._up, self._down)      # →16kHz
        out = audio.astype(np.float32)
        # このフレーム先頭の録音時刻（出した総サンプル数から算出。処理遅延に依らない）
        t_start = self._t0 + self._emitted / TARGET_RATE
        self._emitted += len(out)
        self.q.put((t_start, out))
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
        self._t0 = time.time()
        self._stream.start_stream()
        print(f"[audio] {self.label} 取り込み開始: {self._device['name']} "
              f"({self._rate}Hz, {self._channels}ch → {TARGET_RATE}Hz mono)")

    def stop(self):
        self._stop.set()
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        self._pa.terminate()


class LoopbackRecorder(_BaseRecorder):
    """既定の出力デバイスに対応するループバック（＝会議相手の声）を取得。
    LOOPBACK_HINT が設定されていれば、その名前を含む出力を優先する。"""

    label = "相手(loopback)"

    def _find_device(self):
        if LOOPBACK_HINT:
            for lb in self._pa.get_loopback_device_info_generator():
                if LOOPBACK_HINT in lb["name"]:
                    return lb
        wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        spk = self._pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if spk.get("isLoopbackDevice"):
            return spk
        for lb in self._pa.get_loopback_device_info_generator():
            if spk["name"] in lb["name"]:
                return lb
        raise RuntimeError("ループバックデバイスが見つかりません")


class MicRecorder(_BaseRecorder):
    """マイク（入力デバイス）を取得。見つけ方を多段にフォールバックする。
    MIC_HINT が設定されていれば、その名前を含む入力を優先する。"""

    label = "自分(mic)"

    def _find_device(self):
        # 1) 名前ヒント優先（非ループバックの入力から探す）
        if MIC_HINT:
            for i in range(self._pa.get_device_count()):
                d = self._pa.get_device_info_by_index(i)
                if (d["maxInputChannels"] > 0
                        and not d.get("isLoopbackDevice")
                        and MIC_HINT in d["name"]):
                    return d

        # 2) WASAPI の既定入力
        wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        idx = wasapi.get("defaultInputDevice", -1)
        if idx is not None and idx >= 0:
            return self._pa.get_device_info_by_index(idx)

        # 3) PyAudio 全体の既定入力（API 問わず）
        try:
            d = self._pa.get_default_input_device_info()
            if d and d["maxInputChannels"] > 0:
                return d
        except Exception:
            pass

        # 4) 任意の非ループバック入力デバイス
        for i in range(self._pa.get_device_count()):
            d = self._pa.get_device_info_by_index(i)
            if d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"):
                return d

        raise RuntimeError(
            "マイク（入力デバイス）が見つかりません。"
            "Bluetooth ヘッドセットなら接続・録音デバイスの有効化を確認するか、"
            "MIC_HINT で名前を指定してください（一覧: python -m meeting.audio）"
        )


def _list_devices():
    """利用可能な音声デバイスを一覧表示する（診断用）。"""
    pa = pyaudio.PyAudio()
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        print(f"WASAPI 既定入力 index = {wasapi.get('defaultInputDevice')}")
        print(f"WASAPI 既定出力 index = {wasapi.get('defaultOutputDevice')}")
        print("-" * 60)
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            kinds = []
            if d["maxInputChannels"] > 0:
                kinds.append("in")
            if d["maxOutputChannels"] > 0:
                kinds.append("out")
            if d.get("isLoopbackDevice"):
                kinds.append("loopback")
            api = pa.get_host_api_info_by_index(d["hostApi"])["name"]
            print(f"[{i:2}] {d['name']}  "
                  f"({api}, {'/'.join(kinds) or '-'}, {int(d['defaultSampleRate'])}Hz)")
    finally:
        pa.terminate()


if __name__ == "__main__":
    _list_devices()
