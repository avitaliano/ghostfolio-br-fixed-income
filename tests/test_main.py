import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from br_fixed_income.__main__ import load_from_cache, refresh, seconds_until
from br_fixed_income.server import State

FIXTURE = Path(__file__).parent / "fixtures" / "sample.csv"


class MainTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "prices.csv"

    def test_refresh_success_updates_state_and_cache(self):
        state = State(last_error="old")
        refresh(state, self.cache, fetch=FIXTURE.read_bytes)
        self.assertEqual(state.index.data_date, date(2026, 10, 24))
        self.assertIsNone(state.last_error)
        self.assertEqual(self.cache.read_bytes(), FIXTURE.read_bytes())

    def test_bad_csv_keeps_previous_index_and_cache(self):
        state = State()
        refresh(state, self.cache, fetch=FIXTURE.read_bytes)
        good = state.index
        refresh(state, self.cache, fetch=lambda: b"Renamed;Columns\n1;2\n")
        self.assertIs(state.index, good)
        self.assertIn("missing columns", state.last_error)
        self.assertEqual(self.cache.read_bytes(), FIXTURE.read_bytes())

    def test_download_failure_recorded_not_raised(self):
        state = State()

        def failing():
            raise TimeoutError("slow")

        refresh(state, self.cache, fetch=failing)
        self.assertIsNone(state.index)
        self.assertEqual(state.last_error, "TimeoutError: slow")

    def test_load_from_cache(self):
        state = State()
        self.assertIsNone(load_from_cache(state, self.cache))
        self.cache.write_bytes(FIXTURE.read_bytes())
        age = load_from_cache(state, self.cache)
        self.assertLess(age, 60)
        self.assertEqual(state.index.data_date, date(2026, 10, 24))

    def test_corrupt_cache_ignored(self):
        self.cache.write_bytes(b"garbage")
        state = State()
        self.assertIsNone(load_from_cache(state, self.cache))
        self.assertIsNone(state.index)

    def test_seconds_until(self):
        now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(seconds_until(13, now), 3600)
        self.assertEqual(seconds_until(12, now), 86400)
        self.assertEqual(seconds_until(11, now), 23 * 3600)
