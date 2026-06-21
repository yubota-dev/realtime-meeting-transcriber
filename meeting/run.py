"""Web会議リアルタイム文字起こし＋離席要約＋会議後要約。

相手の声（ループバック）と自分の声（マイク）の2系統を取り込む。
マイクが見つからない場合は相手(loopback)のみで続行する。
タイムスタンプは録音時刻ベースなので、要約・離席判定は時刻で行う。

実行: python -m meeting.run   （プロジェクトルートで）

コマンド:
  a : 離席を記録
  b : 復帰（離席中だけを要約）
  s : 直近5分を要約
  f : 会議全体を要約してファイル保存
  q : 終了（全体要約を保存）
"""
import datetime as dt
import json
import os
import threading

from . import audio, transcriber, llm

LOG_DIR = "data/meetings"


class MeetingSession:
    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        self.entries = []
        self.lock = threading.Lock()
        self.away_ts = None
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.jsonl_path = os.path.join(LOG_DIR, f"{ts}.jsonl")
        self.summary_path = os.path.join(LOG_DIR, f"{ts}_summary.md")
        self._jsonl = open(self.jsonl_path, "a", encoding="utf-8")

    def add_entry(self, entry):
        with self.lock:
            self.entries.append(entry)
        speaker = entry.get("speaker", "")
        line = f"[{entry['ts']}][{speaker}/{entry['lang']}] {entry['original']}"
        if entry["ja"]:
            line += f"\n        → {entry['ja']}"
        print(line)
        self._jsonl.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._jsonl.flush()

    def _snapshot(self, since_ts=None):
        """ts でソートしたコピーを返す。since_ts 指定時はそれ以降のみ。
        （確定順＝処理完了順なので、時刻順に並べ直して整合させる）"""
        with self.lock:
            items = list(self.entries)
        items.sort(key=lambda e: e["ts"])
        if since_ts is not None:
            items = [e for e in items if e["ts"] >= since_ts]
        return items

    def mark_away(self):
        with self.lock:
            self.away_ts = dt.datetime.now().strftime("%H:%M:%S")
        print(">>> 離席を記録しました。戻ったら b で要約します。")

    def summarize_away(self):
        if self.away_ts is None:
            print(">>> 離席が記録されていません（a で記録）")
            return
        window = self._snapshot(since_ts=self.away_ts)
        self.away_ts = None
        if not window:
            print(">>> 離席中の発言はありませんでした")
            return
        print(">>> 離席中の要約を生成中...\n")
        print(llm.summarize_log(window, "あなたが離席していた間"))

    def summarize_recent(self, minutes=5):
        cutoff = (dt.datetime.now() - dt.timedelta(minutes=minutes)).strftime("%H:%M:%S")
        window = self._snapshot(since_ts=cutoff)
        if not window:
            print(">>> 直近の発言はありません")
            return
        print(f">>> 直近{minutes}分の要約を生成中...\n")
        print(llm.summarize_log(window, f"直近{minutes}分"))

    def summarize_full(self):
        window = self._snapshot()
        if not window:
            print(">>> 記録がありません")
            return
        print(">>> 会議全体の要約を生成中...\n")
        summary = llm.summarize_log(window, "会議全体")
        with open(self.summary_path, "w", encoding="utf-8") as f:
            f.write(f"# 会議要約 {dt.datetime.now():%Y-%m-%d %H:%M}\n\n")
            f.write(summary + "\n")
        print(summary)
        print(f"\n>>> 要約を保存しました: {self.summary_path}")

    def close(self):
        self._jsonl.close()


def main():
    stop_event = threading.Event()
    session = MeetingSession()

    # 相手の声（ループバック）は必須、自分の声（マイク）は任意
    recorders = []
    recorders.append(("相手", audio.LoopbackRecorder()))
    try:
        recorders.append(("自分", audio.MicRecorder()))
    except RuntimeError as ex:
        print(f"[warn] マイクを初期化できません: {ex}")
        print("[warn] 相手(loopback)のみで続行します。"
              "デバイス一覧は  python -m meeting.audio")

    sources = [(label, rec.q) for label, rec in recorders]
    trans = transcriber.Transcriber(sources, session.add_entry, stop_event)

    trans.start()
    for _, rec in recorders:
        rec.start()
    print(
        "\n=== コマンド ===\n"
        " a : 離席を記録\n"
        " b : 復帰（離席中を要約）\n"
        " s : 直近5分を要約\n"
        " f : 会議全体を要約してファイル保存\n"
        " q : 終了（全体要約を保存）\n"
    )
    try:
        while True:
            cmd = input().strip().lower()
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
    except KeyboardInterrupt:
        pass
    finally:
        print("\n>>> 終了処理中...")
        stop_event.set()
        for _, rec in recorders:
            rec.stop()
        trans.join(timeout=10)
        session.summarize_full()
        session.close()
        print(">>> 終了しました")


if __name__ == "__main__":
    main()
