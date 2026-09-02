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
    """append-only JSONLを復元し、translation updateを元eventへ反映する。"""
    entries = []
    by_id = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("type") == "translation":
                target = by_id.get(record.get("event_id"))
                if target:
                    target.update({k: v for k, v in record.items()
                                   if k not in ("type", "event_id")})
                continue
            if record.get("type") not in (None, "transcript"):
                continue
            record.setdefault("type", "transcript")
            record.setdefault("event_id", f"legacy-{len(entries) + 1:06d}")
            entries.append(record)
            by_id[record["event_id"]] = record
    accuracy = [e for e in entries if e.get("pass") == "accuracy"]
    return accuracy or [e for e in entries if e.get("type") == "transcript"]


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
    try:
        data, summary = llm.summarize_with_data(entries, "会議全体")
    except Exception as ex:
        print(f"要約失敗: {ex}")
        return
    print(summary)

    summary_path = path.replace(".jsonl", "_summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary + "\n")
    json_path = path.replace(".jsonl", "_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n>>> 保存しました: {summary_path}")


if __name__ == "__main__":
    main()
