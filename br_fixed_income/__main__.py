"""Entry point: load cache, keep data fresh daily, serve HTTP."""

import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from br_fixed_income import __version__
from br_fixed_income.server import State, make_server
from br_fixed_income.tesouro.data import parse_csv
from br_fixed_income.tesouro.source import download, load_cache, save_cache

REFRESH_IF_OLDER_THAN_SECONDS = 20 * 3600
NO_DATA_RETRY_SECONDS = 3600  # until the first successful download, don't wait for the daily run
REFRESH_LOCK = threading.Lock()  # the startup refresh and the daily one must not overlap


@dataclass(frozen=True)
class Config:
    port: int
    cache_path: Path
    hour_utc: int
    max_age_days: int


def env_int(env: dict, name: str, default: int, low: int, high: int) -> int:
    text = env.get(name, str(default))
    try:
        value = int(text)
    except ValueError:
        value = None
    if value is None or not low <= value <= high:
        sys.exit(f"{name} must be an integer from {low} to {high}, got {text!r}")
    return value


def read_config(env: dict) -> Config:
    return Config(
        port=env_int(env, "PORT", 8000, 1, 65535),
        cache_path=Path(env.get("CACHE_DIR", "/data")) / "precotaxatesourodireto.csv",
        hour_utc=env_int(env, "FETCH_HOUR_UTC", 13, 0, 23),
        max_age_days=env_int(env, "MAX_AGE_DAYS", 5, 1, 365),
    )


def log(message: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {message}", flush=True)


def refresh(state: State, cache_path: Path, fetch=download) -> None:
    if not REFRESH_LOCK.acquire(blocking=False):
        log("refresh already running; skipped")
        return
    try:
        refresh_locked(state, cache_path, fetch)
    finally:
        REFRESH_LOCK.release()


def refresh_locked(state: State, cache_path: Path, fetch) -> None:
    try:
        raw = fetch()
    except Exception as error:  # network trouble: keep serving the previous data
        state.last_error = f"{type(error).__name__}: {error}"
        log(f"refresh failed: {state.last_error}")
        return
    try:
        index = parse_csv(raw)  # parse before caching: never replace good data with bad
    except ValueError as error:  # the file changed format: keep serving, but alarm
        state.last_error = state.parse_error = f"{type(error).__name__}: {error}"
        log(f"refresh failed, source format changed: {state.parse_error}")
        return
    state.index, state.fetched_at = index, time.time()
    state.last_error = state.parse_error = None
    log(f"refreshed: {len(index.bonds)} bonds, data date {index.data_date}")
    try:
        save_cache(cache_path, raw)
    except OSError as error:  # serving works without a cache; only restarts lose it
        log(f"cache not saved: {type(error).__name__}: {error}")


def load_from_cache(state: State, cache_path: Path) -> float | None:
    cached = load_cache(cache_path)
    if cached is None:
        return None
    raw, mtime = cached
    try:
        state.index, state.fetched_at = parse_csv(raw), mtime
    except ValueError as error:
        log(f"ignoring unreadable cache: {error}")
        return None
    return time.time() - mtime


def seconds_until(hour_utc: int, now: datetime) -> float:
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def next_wait(state: State, hour_utc: int, now: datetime) -> float:
    if state.index is None:
        return NO_DATA_RETRY_SECONDS
    return seconds_until(hour_utc, now)


def run_daily(state: State, cache_path: Path, hour_utc: int) -> None:
    while True:
        time.sleep(next_wait(state, hour_utc, datetime.now(timezone.utc)))
        refresh(state, cache_path)


def main() -> None:
    config = read_config(dict(os.environ))

    state = State()
    age = load_from_cache(state, config.cache_path)
    if age is None or age > REFRESH_IF_OLDER_THAN_SECONDS:
        threading.Thread(target=refresh, args=(state, config.cache_path), daemon=True).start()
    threading.Thread(
        target=run_daily, args=(state, config.cache_path, config.hour_utc), daemon=True
    ).start()

    server = make_server(state, config.port, config.max_age_days)
    log(f"ghostfolio-br-fixed-income {__version__} listening on :{config.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
