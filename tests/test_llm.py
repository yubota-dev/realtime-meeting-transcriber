import json
import time
import unittest
from unittest.mock import patch

from meeting import llm


ENTRIES = [
    {"type": "transcript", "event_id": "e1", "original": "APIを採用する",
     "speaker": "相手", "ts": "10:00:00", "low_confidence": False},
    {"type": "transcript", "event_id": "e2", "original": "期限は金曜",
     "speaker": "自分", "ts": "10:00:10", "low_confidence": True},
]


class TestStructuredSummary(unittest.TestCase):
    def test_cafe_context_is_detected_without_user_mode(self):
        self.assertEqual(
            llm.detect_conversation_context("I'll have a tall latte, please."),
            "cafe",
        )
        self.assertIsNone(
            llm.detect_conversation_context("That is a tall building."),
        )

    def test_translate_text_uses_requested_target_language(self):
        response = json.dumps({"translation": "Good morning"})
        with patch.object(llm, "_generate", return_value=response) as generate:
            translated = llm.translate_text(
                "おはよう", "ja", "en", model="llama3-ja:latest",
            )
        self.assertEqual(translated, "Good morning")
        self.assertIn("英語", generate.call_args.args[0])
        self.assertIn("英語", generate.call_args.args[1])
        self.assertEqual(generate.call_args.kwargs["schema"], llm.TRANSLATION_SCHEMA)

    def test_translate_text_removes_model_preamble_and_quotes(self):
        with patch.object(
            llm, "_generate", return_value='Here is the translation: "Good morning"',
        ):
            translated = llm.translate_text("おはよう", "ja", "en")
        self.assertEqual(translated, "Good morning")

    def test_translategemma_uses_dedicated_prompt_without_json_schema(self):
        with patch.object(llm, "_generate", return_value="Good morning") as generate:
            translated = llm.translate_text(
                "おはよう", "ja", "en", model="translategemma:4b",
                context=["前の発言です。"],
            )
        self.assertEqual(translated, "Good morning")
        prompt = generate.call_args.args[0]
        self.assertIn("professional Japanese (ja) to English (en) translator", prompt)
        self.assertNotIn("前の発言です。", prompt)
        self.assertNotIn("schema", generate.call_args.kwargs)

    def test_translategemma_includes_domain_but_not_previous_utterance(self):
        with patch.object(llm, "_generate", return_value="店内ですか、お持ち帰りですか？") as generate:
            translated = llm.translate_text(
                "For here or to go?", "en", "ja", model="translategemma:4b",
                context=["This previous sentence must not appear."],
                domain_context="A cafe customer-service conversation.",
            )
        self.assertEqual(translated, "店内ですか、お持ち帰りですか？")
        prompt = generate.call_args.args[0]
        self.assertIn("A cafe customer-service conversation.", prompt)
        self.assertLess(prompt.index("Domain guidance:"), prompt.index("Please translate"))
        self.assertIn("a tall latte", prompt)
        self.assertNotIn("This previous sentence must not appear.", prompt)

    def test_clean_translation_output_collapses_multiline_response(self):
        raw = "First sentence.\n\nSecond sentence."
        self.assertEqual(
            llm._clean_translation_output(raw),
            "First sentence. Second sentence.",
        )

    def test_invalid_evidence_is_removed(self):
        data = {
            "decisions": [
                {"text": "APIを採用", "evidence_event_ids": ["e1"]},
                {"text": "存在しない決定", "evidence_event_ids": ["missing"]},
            ],
            "todos": [{"text": "金曜まで", "evidence_event_ids": ["e2"]}],
            "questions": [], "unresolved": [],
        }
        result = llm.validate_summary(data, ENTRIES)
        self.assertEqual([x["text"] for x in result["decisions"]], ["APIを採用"])
        self.assertTrue(result["todos"][0]["contains_low_confidence_evidence"])

    def test_extract_uses_schema_and_verified_markdown(self):
        response = json.dumps({
            "decisions": [{"text": "APIを採用", "evidence_event_ids": ["e1"]}],
            "todos": [], "questions": [], "unresolved": [],
        })
        with patch.object(llm, "_generate", return_value=response) as generate:
            summary = llm.extract_summary(ENTRIES, "会議")
        self.assertEqual(summary["decisions"][0]["evidence_event_ids"], ["e1"])
        self.assertEqual(generate.call_args.kwargs["schema"], llm.SUMMARY_SCHEMA)
        markdown = llm.summary_to_markdown(summary, "会議")
        self.assertIn("根拠: e1", markdown)

    def test_translation_worker_drains_after_stop(self):
        results = []
        worker = llm.TranslationWorker(lambda event_id, fields: results.append((event_id, fields)))
        with patch.object(llm, "translate_text", return_value="訳文"):
            worker.start()
            worker.submit({"type": "transcript", "event_id": "e1", "lang": "en",
                           "original": "hello"})
            worker.stop()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(worker.ready.is_set())
        self.assertEqual(results[0][1]["ja"], "訳文")
        self.assertEqual(results[0][1]["translation_language"], "ja")

    def test_translation_worker_translates_ja_to_en(self):
        results = []
        worker = llm.TranslationWorker(
            lambda event_id, fields: results.append((event_id, fields)),
            target_language="en",
        )
        with patch.object(llm, "translate_text", return_value="Good morning") as translate:
            worker.start()
            worker.submit({"type": "transcript", "event_id": "e1", "lang": "ja",
                           "original": "おはよう"})
            worker.stop()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0][1]["en"], "Good morning")
        self.assertEqual(results[0][1]["translation_language"], "en")
        translate.assert_called_once_with("おはよう", "ja", "en", model=worker.model)

    def test_translation_worker_coalesces_fragments_until_sentence_end(self):
        results = []
        worker = llm.TranslationWorker(
            lambda event_id, fields: results.append((event_id, fields)),
            target_language="en",
        )
        with patch.object(llm, "translate_text", return_value="The meeting will be held.") as translate:
            worker.start()
            worker.submit({"type": "transcript", "event_id": "e1", "lang": "ja",
                           "speaker": "相手", "original": "来週の定例会議は、",
                           "capture_time": 1.0, "low_confidence": False})
            worker.submit({"type": "transcript", "event_id": "e2", "lang": "ja",
                           "speaker": "相手", "original": "開催すると連絡がありました。",
                           "capture_time": 3.0, "low_confidence": True})
            worker.stop()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        translate.assert_called_once_with(
            "来週の定例会議は、開催すると連絡がありました。", "ja", "en",
            model=worker.model,
        )
        self.assertEqual(results[0][0], "e2")
        self.assertEqual(results[0][1]["source_event_ids"], ["e1", "e2"])
        self.assertTrue(results[0][1]["translation_low_confidence"])

    def test_translation_worker_keeps_automatically_detected_cafe_context(self):
        worker = llm.TranslationWorker(lambda *_: None, target_language="ja")
        first = {"event_id": "e1", "lang": "en", "speaker": "相手",
                 "original": "A tall latte, please."}
        second = {"event_id": "e2", "lang": "en", "speaker": "相手",
                  "original": "For here or to go?"}
        with patch.object(llm, "translate_text", return_value="訳文") as translate:
            worker.pending["相手"] = {"entries": [first], "updated_at": 0}
            worker._translate_pending("相手")
            worker.pending["相手"] = {"entries": [second], "updated_at": 0}
            worker._translate_pending("相手")
        self.assertEqual(worker.detected_context, "cafe")
        self.assertEqual(
            translate.call_args_list[-1].kwargs["domain_context"],
            llm.CAFE_DOMAIN_CONTEXT,
        )

    def test_translation_worker_skips_target_language(self):
        worker = llm.TranslationWorker(lambda *_: None, target_language="en")
        worker.submit({"type": "transcript", "event_id": "e1", "lang": "en",
                       "original": "hello"})
        self.assertTrue(worker.q.empty())

    def test_english_ellipsis_is_sentence_end(self):
        self.assertTrue(llm.TranslationWorker._sentence_complete("Thank you."))
        self.assertTrue(llm.TranslationWorker._sentence_complete("people in..."))
        self.assertTrue(llm.TranslationWorker._sentence_complete("Wait…"))


if __name__ == "__main__":
    unittest.main()
