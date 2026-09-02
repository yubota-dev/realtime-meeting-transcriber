import json
import unittest
from unittest.mock import MagicMock, patch

from meeting import llm


def _load_helpers():
    """音声デバイス依存をimportせずに、voice_chatの純粋関数だけを取り出す。"""
    import re
    src = open("meeting/voice_chat.py", encoding="utf-8").read()
    body = src[src.index("SENTENCE_END"):src.index("class VoiceChat")]
    ns = {"re": re}
    exec(body, ns)
    return ns


HELPERS = _load_helpers()


class TestSentenceStreaming(unittest.TestCase):
    def test_japanese_sentence_is_emitted_before_the_rest_arrives(self):
        done, rest = HELPERS["_split_sentences"]("こんにちは。今日は")
        self.assertEqual(done, ["こんにちは。"])
        self.assertEqual(rest, "今日は")

    def test_english_sentence_boundary(self):
        done, rest = HELPERS["_split_sentences"]("Hello there! How are")
        self.assertEqual(done, ["Hello there!"])
        self.assertEqual(rest.strip(), "How are")

    def test_multiple_sentences_in_one_chunk(self):
        done, rest = HELPERS["_split_sentences"]("はい。わかりました。では")
        self.assertEqual(done, ["はい。", "わかりました。"])
        self.assertEqual(rest, "では")

    def test_symbol_only_fragment_is_not_spoken(self):
        self.assertFalse(HELPERS["_speakable"]("---"))
        self.assertTrue(HELPERS["_speakable"]("はい"))


class _Response:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)


class TestChatStream(unittest.TestCase):
    def test_pieces_are_yielded_until_done(self):
        lines = [
            json.dumps({"message": {"content": "こん"}}),
            "",
            json.dumps({"message": {"content": "にちは。"}}),
            json.dumps({"message": {"content": ""}, "done": True}),
            json.dumps({"message": {"content": "無視される"}}),
        ]
        with patch("meeting.llm.requests.post", return_value=_Response(lines)):
            self.assertEqual(
                list(llm.chat_stream([{"role": "user", "content": "やあ"}])),
                ["こん", "にちは。"],
            )

    def test_system_prompt_is_prepended(self):
        post = MagicMock(return_value=_Response([json.dumps({"done": True})]))
        with patch("meeting.llm.requests.post", post):
            list(llm.chat_stream([{"role": "user", "content": "x"}], system="S"))
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "S"})
        self.assertTrue(payload["stream"])

    def test_error_payload_raises(self):
        lines = [json.dumps({"error": "model not found"})]
        with patch("meeting.llm.requests.post", return_value=_Response(lines)):
            with self.assertRaises(RuntimeError):
                list(llm.chat_stream([{"role": "user", "content": "x"}]))


if __name__ == "__main__":
    unittest.main()
