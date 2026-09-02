"""ローカル音声対話。マイク発話 -> Whisper -> Ollama -> 読み上げ。

会議文字起こしと同じ取り込み・ASR部品を再利用し、応答生成と読み上げだけを
足したもの。応答はstreamで受け取り、文が閉じた時点で読み上げに回すので、
生成完了を待たずに声が返る。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import threading
import time
from pathlib import Path

from . import audio, llm, transcriber, tts

LOG_DIR = Path("data/voice_chat")
SENTENCE_END = re.compile(r"[。．！？!?\n]|(?<=[.?!])\s")
DEFAULT_SYSTEM = (
    "あなたは音声で会話するアシスタントです。"
    "読み上げられることを前提に、1〜3文の短い話し言葉で答えてください。"
    "箇条書き、記号、絵文字、Markdownは使わないでください。"
)
# 読み上げ終了直後はスピーカー残響がマイクに入りやすいので、この秒数は無視する。
ECHO_GUARD_SEC = 0.6


def _split_sentences(buffer):
    """未確定bufferから、確定した文のlistと残りを返す。"""
    out = []
    while True:
        m = SENTENCE_END.search(buffer)
        if not m:
            return out, buffer
        end = m.end()
        sentence = buffer[:end].strip()
        buffer = buffer[end:]
        if sentence:
            out.append(sentence)


def _speakable(text):
    """記号だけの断片を読み上げに送らないための最小フィルタ。"""
    return bool(re.search(r"[0-9A-Za-z぀-ヿ一-鿿]", text))


class VoiceChat:
    def __init__(self, args):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.args = args
        self.session_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = LOG_DIR / f"{self.session_id}.jsonl"
        self._log = self.log_path.open("a", encoding="utf-8")
        self.history = []
        self.lock = threading.Lock()
        self.speech = tts.SpeechWorker(tts.make_tts(args.tts))
        self.stop_event = threading.Event()
        self._busy = threading.Lock()

    def _record(self, role, text):
        self._log.write(json.dumps({
            "ts": dt.datetime.now().isoformat(timespec="milliseconds"),
            "role": role,
            "text": text,
        }, ensure_ascii=False) + "\n")
        self._log.flush()

    def _is_own_voice(self, entry):
        """自分の読み上げをマイクが拾ったものかを判定する。

        音響エコーキャンセルは持っていないため、読み上げ中と直後の発話は
        既定では捨てる。--barge-inを付けたときだけ割り込みとして扱う。
        """
        captured = entry.get("capture_time", time.time())
        if self.speech.speaking.is_set():
            return True
        return captured < self.speech.last_end + ECHO_GUARD_SEC

    def on_entry(self, entry):
        if entry.get("type") != "transcript":
            return
        text = entry.get("original", "").strip()
        if not text or entry.get("discard_candidate"):
            return
        if self._is_own_voice(entry):
            if not self.args.barge_in:
                return
            print("\n[割り込み] 読み上げを中断しました")
            self.speech.cancel()
        print(f"\n[you] {text}")
        self._record("user", text)
        threading.Thread(target=self._respond, args=(text,), daemon=True).start()

    def _respond(self, text):
        # 応答生成中に次の発話が来ても、順序が壊れないよう直列化する。
        with self._busy:
            with self.lock:
                self.history.append({"role": "user", "content": text})
                messages = list(self.history)[-2 * self.args.history_turns:]
            print("[ai] ", end="", flush=True)
            buffer, spoken, reply = "", [], []
            try:
                for piece in llm.chat_stream(
                    messages, model=self.args.model, system=self.args.system,
                    temperature=self.args.temperature, think=self.args.think,
                ):
                    print(piece, end="", flush=True)
                    reply.append(piece)
                    buffer += piece
                    sentences, buffer = _split_sentences(buffer)
                    for s in sentences:
                        if _speakable(s):
                            spoken.append(s)
                            self.speech.submit(s)
            except Exception as ex:
                print(f"\n[warn] 応答生成に失敗しました: {ex}")
                return
            tail = buffer.strip()
            if tail and _speakable(tail):
                spoken.append(tail)
                self.speech.submit(tail)
            print()
            answer = "".join(reply).strip()
            if answer:
                with self.lock:
                    self.history.append({"role": "assistant", "content": answer})
                self._record("assistant", answer)

    def run(self):
        try:
            mic = audio.MicRecorder()
        except RuntimeError as ex:
            raise SystemExit(f"マイクを初期化できません: {ex}")
        trans = transcriber.Transcriber(
            [("自分", mic.q, self.args.language)], self.on_entry, self.stop_event,
            model_name=self.args.asr_model, mode="translate",
        )
        try:
            llm.warmup_model(self.args.model)
        except Exception as ex:
            print(f"[warn] LLMのwarmupに失敗しました: {ex}")
        self.speech.start()
        trans.start()
        mic.start()
        print(f"\n=== 音声対話 (model={self.args.model}, tts={self.args.tts}) ===")
        print(f"話しかけてください。終了は Ctrl+C。ログ: {self.log_path}\n")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            print("\n>>> 終了処理中...")
            mic.stop()
            self.stop_event.set()
            trans.join()
            self.speech.wait_idle(timeout=10)
            self.speech.stop()
            self.speech.join(timeout=5)
            self.speech.backend.close()
            self._log.close()
            print(f">>> ログを保存しました: {self.log_path}")


def build_parser():
    ap = argparse.ArgumentParser(description="ローカルLLMと音声で会話する")
    ap.add_argument("--model", default=llm.MODEL, help="Ollamaの対話model")
    ap.add_argument("--tts", default="sapi", choices=sorted(tts.BACKENDS),
                    help="読み上げbackend。既定はWindows標準のsapi")
    ap.add_argument("--language", choices=("auto", "ja", "en", "zh"), default="ja",
                    help="ASRの言語固定。autoは短い発話で誤判定しやすい")
    ap.add_argument("--asr-model", default="large-v3")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--history-turns", type=int, default=8,
                    help="LLMに渡す直近の往復数")
    ap.add_argument("--system", default=DEFAULT_SYSTEM)
    ap.add_argument("--think", action="store_true",
                    help="thinking modelの推論出力を有効にする。応答開始が数秒遅れる")
    ap.add_argument("--barge-in", action="store_true",
                    help="読み上げ中の発話を割り込みとして扱う（ヘッドホン推奨）")
    return ap


def main(argv=None):
    VoiceChat(build_parser().parse_args(argv)).run()


if __name__ == "__main__":
    main()
