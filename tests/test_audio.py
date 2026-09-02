import queue
import unittest

import numpy as np

from meeting.audio import AudioChunk, _put_audio_latest, _put_drop_oldest, _put_latest


class TestBoundedQueue(unittest.TestCase):
    def test_full_queue_drops_backlog_and_keeps_latest(self):
        q = queue.Queue(maxsize=2)
        q.put([1, 2])
        q.put([3])
        dropped = _put_latest(q, [9], len)
        self.assertEqual(dropped, 3)
        self.assertEqual(q.get_nowait(), [9])

    def test_callback_path_drops_only_oldest(self):
        q = queue.Queue(maxsize=2)
        q.put([1, 2])
        q.put([3])
        dropped = _put_drop_oldest(q, [9], len)
        self.assertEqual(dropped, 2)
        self.assertEqual(q.get_nowait(), [3])
        self.assertEqual(q.get_nowait(), [9])

    def test_audio_drop_is_attached_to_latest_chunk(self):
        q = queue.Queue(maxsize=2)
        q.put(AudioChunk(1.0, np.zeros(10), 3))
        q.put(AudioChunk(2.0, np.zeros(5), 0))
        dropped = _put_audio_latest(q, AudioChunk(3.0, np.zeros(4), 2))
        latest = q.get_nowait()
        self.assertEqual(dropped, 18)
        self.assertEqual(latest.dropped_samples, 20)


if __name__ == "__main__":
    unittest.main()
