import json
import tempfile
import unittest
from pathlib import Path

from meeting.benchmark_asr import error_rate, normalize_text
from meeting.summarize_file import load_entries


class TestNormalization(unittest.TestCase):
    def test_nfkc_punctuation_space_and_number_order(self):
        self.assertEqual(normalize_text("ＡＰＩ、 二十 件。", "ja"), "api20件")

    def test_english_wer(self):
        score = error_rate("Hello, world!", "hello word", "en")
        self.assertEqual(score["metric"], "WER")
        self.assertEqual(score["errors"], 1)
        self.assertEqual(score["reference_units"], 2)

    def test_chinese_traditional_and_number_normalization(self):
        self.assertEqual(normalize_text("會議二十項。", "zh"), "会议20项")


class TestLogReplay(unittest.TestCase):
    def test_translation_update_is_applied(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "meeting.jsonl"
            records = [
                {"type": "session_start", "mode": "concurrent"},
                {"type": "transcript", "event_id": "e1", "original": "hello",
                 "lang": "en", "pass": "realtime"},
                {"type": "translation", "event_id": "e1", "ja": "こんにちは"},
            ]
            path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in records),
                            encoding="utf-8")
            entries = load_entries(path)
        self.assertEqual(entries[0]["ja"], "こんにちは")


if __name__ == "__main__":
    unittest.main()
