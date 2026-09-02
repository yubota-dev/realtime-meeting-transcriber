"""WASAPI音声取得。

PortAudio callbackでは音声のコピーと時刻付与だけを行い、モノラル化、
16kHz化、WAV保存はworker threadで処理する。queueは有界で、過負荷時の
欠落サンプル数をAudioChunkに記録する。
"""
from __future__ import annotations

import math
import os
import queue
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample_poly

TARGET_RATE = 16000
RAW_QUEUE_SIZE = 64
OUTPUT_QUEUE_SIZE = 512

LOOPBACK_HINT = os.environ.get("LOOPBACK_HINT", "")
MIC_HINT = os.environ.get("MIC_HINT", "")


@dataclass(frozen=True)
class AudioChunk:
    capture_time: float
    samples: np.ndarray
    dropped_samples: int = 0


@dataclass(frozen=True)
class _RawChunk:
    capture_time: float
    samples: np.ndarray


def _put_latest(q: queue.Queue, item, dropped_size) -> int:
    """満杯なら滞留分を捨て、最新itemを格納して欠落量を返す。"""
    dropped = 0
    try:
        q.put_nowait(item)
        return 0
    except queue.Full:
        pass
    while True:
        try:
            old = q.get_nowait()
            dropped += dropped_size(old)
        except queue.Empty:
            break
    q.put_nowait(item)
    return dropped


def _put_drop_oldest(q: queue.Queue, item, dropped_size) -> int:
    """callback向け。満杯時に最古1件だけを捨てる定数時間処理。"""
    try:
        q.put_nowait(item)
        return 0
    except queue.Full:
        try:
            old = q.get_nowait()
            dropped = dropped_size(old)
        except queue.Empty:
            dropped = 0
        q.put_nowait(item)
        return dropped


def _put_audio_latest(q: queue.Queue, chunk: AudioChunk) -> int:
    """満杯時のbacklogを破棄し、欠落量を付けた最新音声を一度だけ投入する。"""
    try:
        q.put_nowait(chunk)
        return 0
    except queue.Full:
        pass
    dropped = 0
    while True:
        try:
            old = q.get_nowait()
            dropped += len(old.samples) + old.dropped_samples
        except queue.Empty:
            break
    q.put_nowait(AudioChunk(
        chunk.capture_time, chunk.samples, chunk.dropped_samples + dropped,
    ))
    return dropped


class _BaseRecorder:
    label = "audio"

    def __init__(self, output_path: str | Path | None = None):
        self.q: queue.Queue[AudioChunk] = queue.Queue(maxsize=OUTPUT_QUEUE_SIZE)
        self._raw_q: queue.Queue[_RawChunk] = queue.Queue(maxsize=RAW_QUEUE_SIZE)
        self._capture_stop = threading.Event()
        self._worker_stop = threading.Event()
        self._worker = threading.Thread(target=self._process_audio, daemon=True)
        self._pa = pyaudio.PyAudio()
        self._stream = None
        self._device = self._find_device()
        self._rate = int(self._device["defaultSampleRate"])
        self._channels = max(1, int(self._device["maxInputChannels"]))
        g = math.gcd(TARGET_RATE, self._rate)
        self._up, self._down = TARGET_RATE // g, self._rate // g
        self._t0 = 0.0
        self._captured_frames = 0
        self._raw_dropped_frames = 0
        self._output_path = Path(output_path) if output_path else None
        self._wave = None

    @property
    def started_at(self) -> float:
        return self._t0

    @property
    def audio_path(self) -> Path | None:
        return self._output_path

    def _find_device(self):
        raise NotImplementedError

    def _callback(self, in_data, frame_count, time_info, status):
        if self._capture_stop.is_set():
            return (None, pyaudio.paComplete)
        samples = np.frombuffer(in_data, dtype=np.float32).copy()
        t_start = self._t0 + self._captured_frames / self._rate
        self._captured_frames += frame_count
        raw = _RawChunk(t_start, samples)
        dropped = _put_drop_oldest(
            self._raw_q, raw,
            lambda x: len(x.samples) // self._channels,
        )
        self._raw_dropped_frames += dropped
        return (None, pyaudio.paContinue)

    def _open_wave(self):
        if not self._output_path:
            return
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._wave = wave.open(str(self._output_path), "wb")
        self._wave.setnchannels(1)
        self._wave.setsampwidth(2)
        self._wave.setframerate(TARGET_RATE)

    def _write_wave(self, audio: np.ndarray):
        if self._wave is None:
            return
        pcm = np.clip(audio, -1.0, 1.0)
        self._wave.writeframes((pcm * 32767).astype("<i2").tobytes())

    def _process_audio(self):
        self._open_wave()
        expected_time = None
        try:
            while not self._worker_stop.is_set() or not self._raw_q.empty():
                try:
                    raw = self._raw_q.get(timeout=0.05)
                except queue.Empty:
                    continue
                audio = raw.samples
                if self._channels > 1:
                    audio = audio.reshape(-1, self._channels).mean(axis=1)
                if self._up != self._down:
                    audio = resample_poly(audio, self._up, self._down)
                out = audio.astype(np.float32, copy=False)

                gap = 0
                if expected_time is not None and raw.capture_time > expected_time + 0.002:
                    gap = int(round((raw.capture_time - expected_time) * TARGET_RATE))
                    self._write_wave(np.zeros(gap, dtype=np.float32))
                expected_time = raw.capture_time + len(out) / TARGET_RATE
                self._write_wave(out)

                _put_audio_latest(self.q, AudioChunk(raw.capture_time, out, gap))
        finally:
            if self._wave is not None:
                self._wave.close()

    def start(self):
        self._t0 = time.time()
        self._worker.start()
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
        saved = f", WAV={self._output_path}" if self._output_path else ""
        print(f"[audio] {self.label} 取り込み開始: {self._device['name']} "
              f"({self._rate}Hz, {self._channels}ch -> {TARGET_RATE}Hz mono{saved})")

    def stop(self):
        self._capture_stop.set()
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        self._worker_stop.set()
        if self._worker.is_alive():
            self._worker.join()
        self._pa.terminate()
        if self._raw_dropped_frames:
            seconds = self._raw_dropped_frames / self._rate
            print(f"[warn] {self.label}: callback queue過負荷で約{seconds:.2f}秒欠落")


class LoopbackRecorder(_BaseRecorder):
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
    label = "自分(mic)"

    def _find_device(self):
        if MIC_HINT:
            for i in range(self._pa.get_device_count()):
                d = self._pa.get_device_info_by_index(i)
                if (d["maxInputChannels"] > 0
                        and not d.get("isLoopbackDevice")
                        and MIC_HINT in d["name"]):
                    return d
        wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        idx = wasapi.get("defaultInputDevice", -1)
        if idx is not None and idx >= 0:
            return self._pa.get_device_info_by_index(idx)
        try:
            d = self._pa.get_default_input_device_info()
            if d and d["maxInputChannels"] > 0:
                return d
        except Exception:
            pass
        for i in range(self._pa.get_device_count()):
            d = self._pa.get_device_info_by_index(i)
            if d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"):
                return d
        raise RuntimeError(
            "マイクが見つかりません。接続を確認するかMIC_HINTを指定してください"
        )


def _list_devices():
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
            print(f"[{i:2}] {d['name']} ({api}, {'/'.join(kinds) or '-'}, "
                  f"{int(d['defaultSampleRate'])}Hz)")
    finally:
        pa.terminate()


if __name__ == "__main__":
    _list_devices()
