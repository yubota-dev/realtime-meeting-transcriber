"""リアルタイム会議文字起こし、翻訳、根拠付き要約。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import threading
import time
from pathlib import Path

from . import audio, llm, transcriber

LOG_DIR = Path("data/meetings")
AUDIO_DIR = Path("data/audio")
LANG_CHOICES = ("auto", "ja", "en", "zh")
TARGET_LANGUAGE_CHOICES = ("ja", "en", "zh")


class MeetingSession:
    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.session_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.entries = []
        self.by_id = {}
        self.lock = threading.Lock()
        self.away_time = None
        self.jsonl_path = LOG_DIR / f"{self.session_id}.jsonl"
        self.summary_path = LOG_DIR / f"{self.session_id}_summary.md"
        self.summary_json_path = LOG_DIR / f"{self.session_id}_summary.json"
        self._jsonl = self.jsonl_path.open("a", encoding="utf-8")

    def _append_record(self, record):
        self._jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._jsonl.flush()

    def add_session_metadata(self, args):
        with self.lock:
            self._append_record({
                "type": "session_start",
                "session_id": self.session_id,
                "created_at": dt.datetime.now().isoformat(timespec="milliseconds"),
                "mode": args.mode,
                "target_language": args.target_language,
                "mic_language": args.mic_language,
                "loopback_language": args.loopback_language,
                "asr_model": args.asr_model,
                "asr_provenance": {
                    "provider": "OpenAI" if "whisper" in args.asr_model
                    or "large-v3" in args.asr_model else "verify",
                    "license": "MIT" if "large-v3" in args.asr_model else "verify",
                },
                "llm_model": args.llm_model,
                "llm_provenance": llm.model_provenance(args.llm_model),
                "translation_model": args.translation_model,
                "translation_model_provenance": llm.model_provenance(
                    args.translation_model
                ),
                "context_detection": "automatic",
                "audio_saved": bool(args.save_audio),
                "audio_encrypted": False,
            })

    def add_entry(self, entry):
        with self.lock:
            self.entries.append(entry)
            if entry.get("event_id"):
                self.by_id[entry["event_id"]] = entry
            self._append_record(entry)
        if entry.get("type") == "gap":
            print(f"[{entry['ts']}][{entry['speaker']}] "
                  f"[音声欠落 {entry['dropped_seconds']:.3f}秒]")
            return
        confidence = " [LOW]" if entry.get("low_confidence") else ""
        print(f"[{entry['ts']}][{entry.get('speaker', '')}/{entry.get('lang', '')}]"
              f"{confidence} {entry.get('original', '')}")

    def update_entry(self, event_id, fields):
        with self.lock:
            entry = self.by_id.get(event_id)
            if entry is None:
                return
            entry.update(fields)
            self._append_record({
                "type": "translation",
                "event_id": event_id,
                **fields,
            })
        target = fields.get("translation_language")
        translated = fields.get(target) if target else fields.get("ja")
        if translated:
            confidence = " [LOW]" if fields.get("translation_low_confidence") else ""
            print(f"        -> [{target or 'ja'}]{confidence} {translated}")
        elif fields.get("translation_error"):
            print(f"        -> (翻訳失敗: {fields['translation_error']})")

    def _snapshot(self, since_time=None, prefer_accuracy=False):
        with self.lock:
            items = [dict(e) for e in self.entries if e.get("type") == "transcript"]
        if prefer_accuracy and any(e.get("pass") == "accuracy" for e in items):
            items = [e for e in items if e.get("pass") == "accuracy"]
        else:
            items = [e for e in items if e.get("pass") != "accuracy"]
        items.sort(key=lambda e: (e.get("capture_time", 0), e.get("ts", "")))
        if since_time is not None:
            items = [e for e in items if e.get("capture_time", 0) >= since_time]
        return items

    def mark_away(self):
        with self.lock:
            self.away_time = time.time()
        print(">>> 離席を記録しました。戻ったら b で要約します。")

    def summarize_away(self):
        if self.away_time is None:
            print(">>> 離席が記録されていません（a で記録）")
            return
        window = self._snapshot(since_time=self.away_time)
        self.away_time = None
        self._print_summary(window, "あなたが離席していた間")

    def summarize_recent(self, minutes=5):
        cutoff = time.time() - minutes * 60
        self._print_summary(self._snapshot(since_time=cutoff), f"直近{minutes}分")

    def _print_summary(self, entries, label):
        if not entries:
            print(">>> 対象発言はありません")
            return
        print(f">>> {label}の要約を生成中...\n")
        print(llm.summarize_log(entries, label))

    def summarize_full(self, *, prefer_accuracy=False):
        window = self._snapshot(prefer_accuracy=prefer_accuracy)
        if not window:
            print(">>> 記録がありません")
            return
        label = "会議全体（高精度再処理）" if prefer_accuracy else "会議全体"
        print(">>> 会議全体の要約を生成中...\n")
        try:
            data, summary = llm.summarize_with_data(window, label)
            self.summary_json_path.write_text(json.dumps({
                "session_id": self.session_id,
                "scope": label,
                "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                "summary": data,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as ex:
            summary = f"(要約失敗: {ex})"
        self.summary_path.write_text(summary + "\n", encoding="utf-8")
        print(summary)
        print(f"\n>>> 要約を保存しました: {self.summary_path}")

    def close(self):
        self._jsonl.close()


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode", choices=("concurrent", "translate", "accuracy"),
        default="concurrent",
        help="concurrent=並行表示 / translate=短い発話で翻訳優先 / accuracy=終了後再処理",
    )
    ap.add_argument("--mic-language", choices=LANG_CHOICES, default="auto")
    ap.add_argument("--loopback-language", choices=LANG_CHOICES, default="auto")
    ap.add_argument(
        "--target-language", choices=TARGET_LANGUAGE_CHOICES,
        default=os.environ.get("TARGET_LANGUAGE", "ja"),
        help="翻訳先言語。既定はja。原文と翻訳を両方表示します",
    )
    ap.add_argument("--asr-model", default=os.environ.get("ASR_MODEL", "large-v3"))
    ap.add_argument("--llm-model", default=llm.MODEL)
    ap.add_argument(
        "--translation-model", default=llm.TRANSLATION_MODEL,
        help="Ollama翻訳モデル。既定は翻訳専用translategemma:4b",
    )
    ap.add_argument("--save-audio", action="store_true",
                    help="16kHz WAVを保存（既定OFF・暗号化なし）")
    ap.add_argument("--audio-dir", default=str(AUDIO_DIR))
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.mode == "accuracy":
        args.save_audio = True
    stop_event = threading.Event()
    session = MeetingSession()
    session.add_session_metadata(args)

    audio_dir = Path(args.audio_dir)
    if args.save_audio:
        print("[privacy] 音声保存ON: WAVは暗号化されません。保存先のアクセス権を確認してください。")

    def wav_path(source):
        return audio_dir / f"{session.session_id}_{source}.wav" if args.save_audio else None

    recorders = [("相手", audio.LoopbackRecorder(wav_path("loopback")),
                  args.loopback_language)]
    try:
        recorders.append(("自分", audio.MicRecorder(wav_path("mic")), args.mic_language))
    except RuntimeError as ex:
        print(f"[warn] マイクを初期化できません: {ex}")
        print("[warn] 相手(loopback)のみで続行します")

    translator = llm.TranslationWorker(
        session.update_entry, model=args.translation_model,
        target_language=args.target_language, warmup=True,
    )

    if args.llm_model != args.translation_model:
        try:
            llm.unload_model(args.llm_model)
        except Exception as ex:
            print(f"[warn] 要約modelを事前解放できませんでした: {ex}")

    detected_context = {"name": None}

    def on_entry(entry):
        session.add_entry(entry)
        detected = llm.detect_conversation_context(entry.get("original", ""))
        if detected == "cafe" and detected_context["name"] != "cafe":
            detected_context["name"] = "cafe"
            trans.set_context(llm.CAFE_ASR_PROMPT, llm.CAFE_HOTWORDS)
            print("[context] カフェ接客を自動検出しました")
        translator.submit(entry)

    sources = [(label, rec.q, language) for label, rec, language in recorders]
    trans = transcriber.Transcriber(
        sources, on_entry, stop_event, model_name=args.asr_model, mode=args.mode,
    )
    translator.start()
    if not translator.ready.wait(timeout=llm.MODEL_LOAD_TIMEOUT + 5):
        print("[warn] 翻訳modelの準備待ちがtimeoutしました。処理は継続します")
    trans.start()
    for _, rec, _ in recorders:
        rec.start()

    print(
        "\n=== コマンド ===\n"
        " a : 離席を記録\n"
        " b : 復帰（離席中を要約）\n"
        " s : 直近5分を要約\n"
        " f : 会議全体を要約して保存\n"
        " q : 終了\n"
    )
    try:
        while True:
            cmd = input().strip().lower()
            if (args.mode == "translate" and cmd in ("b", "s", "f")
                    and not translator.is_idle()):
                print(">>> 翻訳優先モード: 翻訳queue処理中のため要約を保留します")
                continue
            if cmd == "a":
                session.mark_away()
            elif cmd == "b":
                session.summarize_away()
            elif cmd == "s":
                session.summarize_recent()
            elif cmd == "f":
                session.summarize_full()
            elif cmd == "q":
                break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        print("\n>>> 終了処理中...")
        # producerから順に止め、各段のqueueをdrainする。
        for _, rec, _ in recorders:
            rec.stop()
        stop_event.set()
        trans.join()

        if args.mode == "accuracy":
            print(">>> 保存音声をlarge-v3で高精度再処理中...")
            for label, rec, language in recorders:
                if rec.audio_path and rec.audio_path.exists():
                    trans.reprocess_file(
                        rec.audio_path, label, rec.started_at, language_lock=language,
                    )

        translator.stop()
        translator.join()
        if args.llm_model != args.translation_model:
            try:
                llm.unload_model(args.translation_model)
            except Exception as ex:
                print(f"[warn] 翻訳modelを解放できませんでした: {ex}")
        session.summarize_full(prefer_accuracy=args.mode == "accuracy")
        session.close()
        print(">>> 終了しました")


if __name__ == "__main__":
    main()
