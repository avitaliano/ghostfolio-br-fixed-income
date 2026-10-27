"""Download the official CSV politely and cache it on disk."""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from br_fixed_income import __version__

DATASET_ID = "df56aa42-484a-4a59-8184-7676580c81e3"
CKAN_PACKAGE_URL = (
    "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=" + DATASET_ID
)
FALLBACK_CSV_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/" + DATASET_ID
    + "/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)
USER_AGENT = (
    f"ghostfolio-br-fixed-income/{__version__} "
    "(+https://github.com/avitaliano/ghostfolio-br-fixed-income)"
)
TIMEOUT_SECONDS = 120
BASE_DELAY_SECONDS = 60
MAX_DELAY_SECONDS = 1800
RETRYABLE = (urllib.error.URLError, TimeoutError, ConnectionError)  # HTTPError is a URLError


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def resolve_csv_url(get=http_get) -> str:
    try:
        package = json.loads(get(CKAN_PACKAGE_URL))
        for resource in package["result"]["resources"]:
            if resource.get("format", "").upper() == "CSV":
                return resource["url"]
    except (*RETRYABLE, ValueError, KeyError, TypeError):
        pass
    return FALLBACK_CSV_URL


def retry_delay(error: Exception, attempt: int) -> float:
    backoff = BASE_DELAY_SECONDS * 2**attempt
    headers = getattr(error, "headers", None)
    retry_after = headers.get("Retry-After", "") if headers else ""
    if retry_after.isdigit():
        backoff = max(backoff, int(retry_after))
    return min(backoff, MAX_DELAY_SECONDS)


def download(get=http_get, sleep=time.sleep, attempts: int = 6) -> bytes:
    url = resolve_csv_url(get)
    for attempt in range(attempts):
        try:
            return get(url)
        except RETRYABLE as error:
            if attempt == attempts - 1:
                raise
            delay = retry_delay(error, attempt)
            print(f"download failed ({error}); retrying in {delay:.0f}s", flush=True)
            sleep(delay)
    raise RuntimeError("unreachable")


def save_cache(path: Path, raw: bytes) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)


def load_cache(path: Path) -> tuple[bytes, float] | None:
    try:
        return path.read_bytes(), path.stat().st_mtime
    except FileNotFoundError:
        return None
