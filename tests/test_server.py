import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from br_fixed_income.server import State, make_server
from br_fixed_income.tesouro.data import parse_csv

FIXTURE = Path(__file__).parent / "fixtures" / "sample.csv"


class ServerTest(unittest.TestCase):
    def start(self, state, today=date(2026, 10, 27)):
        server = make_server(state, 0, max_age_days=5, today=lambda: today)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as response:
                return response.status, response.headers.get_content_type(), response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get_content_type(), error.read().decode()

    def loaded(self):
        return State(index=parse_csv(FIXTURE.read_bytes()), fetched_at=1.0)

    def test_price(self):
        self.start(self.loaded())
        status, kind, body = self.get("/tesouro/price/tesouro-ipca/2035-05-15")
        self.assertEqual((status, kind), (200, "application/json"))
        self.assertEqual(json.loads(body), {
            "symbol": "tesouro-ipca/2035-05-15", "name": "Tesouro IPCA+ 2035",
            "date": "2026-10-24", "price": 3530.12,
        })

    def test_price_errors(self):
        self.start(self.loaded())
        self.assertEqual(self.get("/tesouro/price/tesouro-ipca/2099-01-01")[0], 404)
        self.assertEqual(self.get("/tesouro/price/tesouro-ipca/2035-13-40")[0], 400)
        self.assertEqual(self.get("/tesouro/price/Tesouro-IPCA/2035-05-15")[0], 404)
        self.assertEqual(self.get("/tesouro/price/tesouro-ipca/2035-05-15/")[0], 404)
        status, kind, _ = self.get("/nope")
        self.assertEqual((status, kind), (404, "application/json"))

    def test_history(self):
        self.start(self.loaded())
        status, kind, body = self.get("/tesouro/history/tesouro-ipca/2035-05-15")
        self.assertEqual((status, kind), (200, "text/plain"))
        self.assertEqual(body, "date;marketPrice\n2026-10-23;3526.0\n2026-10-24;3530.12\n")
        _, _, body = self.get("/tesouro/history/tesouro-ipca/2035-05-15?from=2026-10-24")
        self.assertEqual(body, "date;marketPrice\n2026-10-24;3530.12\n")
        self.assertEqual(self.get("/tesouro/history/tesouro-ipca/2035-05-15?from=bad")[0], 400)

    def test_bonds(self):
        self.start(self.loaded())
        status, _, body = self.get("/tesouro/bonds")
        bonds = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(bonds), 6)
        self.assertIn({"slug": "tesouro-ipca", "name": "Tesouro IPCA+ 2035", "maturity": "2035-05-15",
                       "latestDate": "2026-10-24", "price": 3530.12,
                       "priceUrl": "/tesouro/price/tesouro-ipca/2035-05-15"}, bonds)

    def test_health_ok_and_stale(self):
        self.start(self.loaded())
        status, _, body = self.get("/health")
        self.assertEqual((status, json.loads(body)["status"]), (200, "ok"))
        self.start(self.loaded(), today=date(2026, 11, 10))
        self.assertEqual(json.loads(self.get("/health")[2])["status"], "stale")
        self.assertEqual(self.get("/health")[0], 503)

    def test_no_data_yet(self):
        self.start(State(last_error="HTTPError: 429"))
        status, _, body = self.get("/health")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["lastError"], "HTTPError: 429")
        self.assertEqual(self.get("/tesouro/price/tesouro-ipca/2035-05-15")[0], 503)
        self.assertEqual(self.get("/tesouro/bonds")[0], 503)
