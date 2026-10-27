import json
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path

from br_fixed_income.tesouro import source


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://x", code, "err", headers, None)


class FakeGet:
    """Returns CKAN JSON for the package URL; plays `csv_results` for the CSV URL."""

    def __init__(self, csv_results, ckan_ok=True):
        self.csv_results = list(csv_results)
        self.ckan_ok = ckan_ok
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if url == source.CKAN_PACKAGE_URL:
            if not self.ckan_ok:
                raise urllib.error.URLError("down")
            return json.dumps({"result": {"resources": [
                {"format": "PDF", "url": "http://x/taxa.pdf"},
                {"format": "CSV", "url": "http://x/fresh.csv"},
            ]}}).encode()
        result = self.csv_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class SourceTest(unittest.TestCase):
    def test_resolves_csv_url_from_ckan(self):
        self.assertEqual(source.resolve_csv_url(FakeGet([])), "http://x/fresh.csv")

    def test_falls_back_when_ckan_down(self):
        self.assertEqual(source.resolve_csv_url(FakeGet([], ckan_ok=False)), source.FALLBACK_CSV_URL)

    def test_retry_delay_honours_retry_after_but_not_below_backoff(self):
        self.assertEqual(source.retry_delay(http_error(429, "30"), 0), 60)
        self.assertEqual(source.retry_delay(http_error(429, "600"), 0), 600)
        self.assertEqual(source.retry_delay(http_error(503), 3), 480)
        self.assertEqual(source.retry_delay(http_error(429, "99999"), 0), 1800)
        self.assertEqual(source.retry_delay(http_error(429, "Wed, 21 Oct 2026 07:28:00 GMT"), 1), 120)

    def test_download_retries_then_succeeds(self):
        sleeps = []
        get = FakeGet([http_error(429, "30"), TimeoutError(), b"csv"])
        self.assertEqual(source.download(get, sleeps.append), b"csv")
        self.assertEqual(sleeps, [60, 120])

    def test_download_gives_up(self):
        get = FakeGet([http_error(429)] * 3)
        with self.assertRaises(urllib.error.HTTPError):
            source.download(get, lambda s: None, attempts=3)

    def test_cache_roundtrip_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            self.assertIsNone(source.load_cache(path))
            source.save_cache(path, b"abc")
            raw, mtime = source.load_cache(path)
            self.assertEqual(raw, b"abc")
            self.assertGreater(mtime, 0)
            self.assertFalse(path.with_suffix(".tmp").exists())
