import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from br_fixed_income.__main__ import (
    NO_DATA_RETRY_SECONDS,
    REFRESH_LOCK,
    load_from_cache,
    next_wait,
    read_config,
    refresh,
    seconds_until,
)
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

    def test_unwritable_cache_still_serves_download(self):
        state = State()
        unwritable = Path("/nonexistent-dir/prices.csv")
        refresh(state, unwritable, fetch=FIXTURE.read_bytes)
        self.assertEqual(state.index.data_date, date(2026, 10, 24))
        self.assertIsNone(state.last_error)

    def test_retries_hourly_until_first_data(self):
        now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(next_wait(State(), 13, now), NO_DATA_RETRY_SECONDS)
        loaded = State()
        refresh(loaded, self.cache, fetch=FIXTURE.read_bytes)
        self.assertEqual(next_wait(loaded, 13, now), 3600)
        self.assertEqual(next_wait(loaded, 11, now), 23 * 3600)
        self.assertEqual(NO_DATA_RETRY_SECONDS, 3600)

    def test_schema_change_flags_parse_error_until_fixed(self):
        state = State()
        refresh(state, self.cache, fetch=lambda: b"Renamed;Columns\n1;2\n")
        self.assertIn("missing columns", state.parse_error)
        refresh(state, self.cache, fetch=FIXTURE.read_bytes)
        self.assertIsNone(state.parse_error)

    def test_network_error_is_not_a_parse_error(self):
        state = State()

        def failing():
            raise TimeoutError("slow")

        refresh(state, self.cache, fetch=failing)
        self.assertIsNone(state.parse_error)

    def test_overlapping_refresh_is_skipped(self):
        calls = []
        with REFRESH_LOCK:
            refresh(State(), self.cache, fetch=lambda: calls.append(1) or FIXTURE.read_bytes())
        self.assertEqual(calls, [])

    def test_read_config_defaults(self):
        config = read_config({})
        self.assertEqual((config.port, config.hour_utc, config.max_age_days), (8000, 13, 5))
        self.assertEqual(config.cache_path, Path("/data/precotaxatesourodireto.csv"))

    def test_read_config_rejects_bad_values(self):
        for env in ({"FETCH_HOUR_UTC": "24"}, {"FETCH_HOUR_UTC": "x"}, {"PORT": "0"},
                    {"PORT": "70000"}, {"MAX_AGE_DAYS": "0"}):
            with self.subTest(env=env), self.assertRaises(SystemExit):
                read_config(env)

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
