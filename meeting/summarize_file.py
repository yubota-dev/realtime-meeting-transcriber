"""保存済みの .jsonl ログから要約を再生成する。

使い方:
  python -m meeting.summarize_file                          # 最新のログを要約
  python -m meeting.summarize_file data/meetings/20260614_100000.jsonl
"""
import json
import os
import sys
import glob

from . import llm

LOG_DIR = "data/meetings"


def load_entries(path: str) -> list:
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(LOG_DIR, "*.jsonl")))
        if not files:
            print("ログファイルが見つかりません。")
            sys.exit(1)
        path = files[-1]

    print(f"ログ読み込み: {path}")
    entries = load_entries(path)
    if not entries:
        print("エントリが0件です。")
        return

    print(f"{len(entries)} 件の発言 → 要約生成中...\n")
    summary = llm.summarize_log(entries, "会議全体")
    print(summary)

    summary_path = path.replace(".jsonl", "_summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"# 会議要約（再生成）\n\n{summary}\n")
    print(f"\n>>> 保存しました: {summary_path}")


if __name__ == "__main__":
    main()
