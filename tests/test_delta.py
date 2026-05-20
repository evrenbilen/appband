import unittest

from netmon.delta import DeltaTracker


class DeltaTrackerTest(unittest.TestCase):
    def setUp(self):
        # 100 MB/sec threshold for "discontinuity"
        self.t = DeltaTracker(max_delta_per_sec=100 * 1024 * 1024)

    def test_first_observation_returns_none(self):
        self.assertIsNone(self.t.update("k", value=1000, now=10))

    def test_second_observation_returns_delta(self):
        self.t.update("k", value=1000, now=10)
        self.assertEqual(self.t.update("k", value=1500, now=15), 500)

    def test_negative_delta_treated_as_reset(self):
        self.t.update("k", value=1000, now=10)
        self.assertIsNone(self.t.update("k", value=200, now=11))
        self.assertEqual(self.t.update("k", value=400, now=12), 200)

    def test_huge_delta_treated_as_discontinuity(self):
        self.t.update("k", value=1000, now=10)
        self.assertIsNone(self.t.update("k", value=1000 + 1024**3, now=11))

    def test_independent_keys(self):
        self.t.update("a", value=100, now=1)
        self.t.update("b", value=500, now=1)
        self.assertEqual(self.t.update("a", value=300, now=2), 200)
        self.assertEqual(self.t.update("b", value=900, now=2), 400)

    def test_evict_after_n_misses(self):
        self.t.update("k", value=100, now=1)
        self.t.evict_missing(present_keys={"other"}, max_misses=2)
        self.assertIn("k", self.t._state)  # 1 miss
        self.t.evict_missing(present_keys={"other"}, max_misses=2)
        self.assertNotIn("k", self.t._state)  # 2 misses


if __name__ == "__main__":
    unittest.main()
