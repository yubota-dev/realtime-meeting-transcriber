"""読み上げbackend。既定は追加インストール不要のWindows SAPI。

いずれのbackendも「途中で止められる」ことを前提にする。ユーザーが割り込んで
話し始めたとき、読み上げを最後まで流し切ると会話にならないため。
"""
from __future__ import annotations

import io
import os
import queue
import subprocess
import threading
import time
import wave

import pyaudiowpatch as pyaudio
import requests

SAPI_VOICE = os.environ.get("TTS_VOICE", "")
SAPI_RATE = int(os.environ.get("TTS_RATE", "1"))
VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
VOICEVOX_SPEAKER = int(os.environ.get("VOICEVOX_SPEAKER", "3"))

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class NullTTS:
    """音声出力なし。CLIだけで動作確認したいときに使う。"""

    name = "none"

    def speak(self, text):
        print(f"[tts:none] {text}")

    def stop(self):
        pass

    def close(self):
        pass


class SapiTTS:
    """Windows標準のSystem.Speech。追加インストールが不要な代わりに声は硬い。"""

    name = "sapi"

    def __init__(self, voice=SAPI_VOICE, rate=SAPI_RATE):
        self._voice = voice
        self._rate = rate
        self._proc = None
        self._lock = threading.Lock()

    def _script(self, text):
        literal = text.replace("'", "''")
        select = f"$s.SelectVoice('{self._voice}');" if self._voice else ""
        return (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"{select}"
            f"$s.Rate = {self._rate};"
            f"$s.Speak('{literal}');"
        )

    def speak(self, text):
        cmd = ["powershell", "-NoProfile", "-NonInteractive",
               "-Command", self._script(text)]
        with self._lock:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
            )
            proc = self._proc
        proc.wait()
        with self._lock:
            if self._proc is proc:
                self._proc = None

    def stop(self):
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            proc.kill()

    def close(self):
        self.stop()


class VoicevoxTTS:
    """VOICEVOX engine (localhost:50021) が起動している場合に使う。"""

    name = "voicevox"

    def __init__(self, base_url=VOICEVOX_URL, speaker=VOICEVOX_SPEAKER):
        self._base = base_url.rstrip("/")
        self._speaker = speaker
        self._cancel = threading.Event()
        self._pa = pyaudio.PyAudio()

    def _synthesize(self, text):
        q = requests.post(f"{self._base}/audio_query",
                          params={"text": text, "speaker": self._speaker}, timeout=30)
        q.raise_for_status()
        r = requests.post(f"{self._base}/synthesis",
                          params={"speaker": self._speaker}, json=q.json(), timeout=60)
        r.raise_for_status()
        return r.content

    def speak(self, text):
        self._cancel.clear()
        wav_bytes = self._synthesize(text)
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            stream = self._pa.open(
                format=self._pa.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(), rate=wf.getframerate(), output=True,
            )
            try:
                while not self._cancel.is_set():
                    data = wf.readframes(1024)
                    if not data:
                        break
                    stream.write(data)
            finally:
                stream.stop_stream()
                stream.close()

    def stop(self):
        self._cancel.set()

    def close(self):
        self.stop()
        self._pa.terminate()


BACKENDS = {"sapi": SapiTTS, "voicevox": VoicevoxTTS, "none": NullTTS}


def make_tts(name):
    try:
        return BACKENDS[name]()
    except KeyError:
        raise SystemExit(f"未知のTTS backend: {name} (選択肢: {', '.join(BACKENDS)})")


class SpeechWorker(threading.Thread):
    """文単位で受け取り、順に読み上げる。読み上げ中かどうかを外へ公開する。"""

    def __init__(self, backend):
        super().__init__(daemon=True)
        self.backend = backend
        self._q: queue.Queue[str | None] = queue.Queue()
        self._stop = threading.Event()
        self.speaking = threading.Event()
        self.last_end = 0.0
        self._idle = threading.Event()
        self._idle.set()

    def submit(self, text):
        text = text.strip()
        if text:
            self._idle.clear()
            self._q.put(text)

    def cancel(self):
        """再生待ちを捨て、再生中の1文も打ち切る。割り込み発話用。"""
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self.backend.stop()

    def is_idle(self):
        return self._idle.is_set()

    def wait_idle(self, timeout=None):
        return self._idle.wait(timeout)

    def run(self):
        while not self._stop.is_set():
            try:
                text = self._q.get(timeout=0.1)
            except queue.Empty:
                if self._q.empty():
                    self._idle.set()
                continue
            if text is None:
                break
            self.speaking.set()
            try:
                self.backend.speak(text)
            except Exception as ex:
                print(f"[warn] 読み上げ失敗: {ex}")
            finally:
                self.speaking.clear()
                self.last_end = time.time()
                if self._q.empty():
                    self._idle.set()

    def stop(self):
        self._stop.set()
        self.cancel()
        self._q.put(None)
