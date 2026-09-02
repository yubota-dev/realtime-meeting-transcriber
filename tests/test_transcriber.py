import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from meeting import transcriber
from meeting.audio import AudioChunk


class TestLanguageAndConfidence(unittest.TestCase):
    def test_translate_mode_uses_shorter_english_segments(self):
        tr = transcriber.Transcriber.__new__(transcriber.Transcriber)
        tr.mode = "translate"
        tr.max_utter_sec = 8
        tr.english_translate_max_utter_sec = 4
        self.assertEqual(
            tr._max_utter_seconds(SimpleNamespace(language_lock="en")), 4,
        )
        self.assertEqual(
            tr._max_utter_seconds(SimpleNamespace(language_lock="ja")), 8,
        )

    def test_transcribe_passes_context_prompt_and_hotwords(self):
        tr = transcriber.Transcriber.__new__(transcriber.Transcriber)
        tr.initial_prompt = "Cafe conversation"
        tr.hotwords = "espresso for here or to go"
        tr.model = SimpleNamespace(transcribe=lambda *args, **kwargs: (
            [], SimpleNamespace(language="en", all_language_probs=[("en", 1.0)]),
        ))
        with patch.object(tr.model, "transcribe", wraps=tr.model.transcribe) as call:
            tr._transcribe(np.zeros(16000, dtype=np.float32), "en")
        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["initial_prompt"], "Cafe conversation")
        self.assertEqual(kwargs["hotwords"], "espresso for here or to go")

    def test_language_lock(self):
        lang, probs = transcriber.resolve_language(SimpleNamespace(), "en")
        self.assertEqual(lang, "en")
        self.assertEqual(probs, {"en": 1.0})

    def test_language_fallback_is_limited_to_supported_languages(self):
        info = SimpleNamespace(
            language="fr",
            all_language_probs=[("fr", 0.8), ("ja", 0.1), ("en", 0.07), ("zh", 0.03)],
        )
        lang, probs = transcriber.resolve_language(info)
        self.assertEqual(lang, "ja")
        self.assertEqual(set(probs), {"ja", "en", "zh"})

    def test_hallucination_phrase_and_repetition(self):
        self.assertTrue(transcriber.is_hallucination_candidate("ご視聴ありがとうございました"))
        self.assertTrue(transcriber.is_hallucination_candidate("test. test. test."))
        self.assertFalse(transcriber.is_hallucination_candidate("次回はAPI設計を確認します"))

    def test_vad_model_is_created_per_stream(self):
        models = [object(), object()]
        with patch.object(transcriber, "load_silero_vad", side_effect=models), \
                patch.object(transcriber, "VADIterator", side_effect=lambda m, **k: m):
            a = transcriber._StreamState("a", queue.Queue())
            b = transcriber._StreamState("b", queue.Queue())
        self.assertIs(a.vad, models[0])
        self.assertIs(b.vad, models[1])

    def test_stop_drains_queue_and_preserves_buffer_start_time(self):
        tr = transcriber.Transcriber.__new__(transcriber.Transcriber)
        threading.Thread.__init__(tr)
        tr.stop_event = threading.Event()
        tr.stop_event.set()
        q = queue.Queue()
        q.put(AudioChunk(100.0, np.zeros(1024, dtype=np.float32)))
        state = SimpleNamespace(
            q=q, pending_dropped_samples=0,
            buf=np.zeros(0, dtype=np.float32), buf_start=None, utter=[],
        )
        tr.streams = [state]
        seen = []
        tr._feed_vad = lambda st, window, wt: seen.append(wt)
        tr._emit_gap = lambda *args: None
        tr.run()
        self.assertTrue(q.empty())
        self.assertEqual(seen, [100.0, 100.0 + 512 / transcriber.SAMPLE_RATE])


if __name__ == "__main__":
    unittest.main()
