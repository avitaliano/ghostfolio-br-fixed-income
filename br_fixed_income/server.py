"""HTTP API over the current price index."""

import json
import re
import socketserver
from dataclasses import dataclass
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from br_fixed_income.tesouro.data import Bond, Index

BOND_ROUTE = re.compile(r"^/tesouro/(price|history)/([a-z0-9-]+)/(\d{4}-\d{2}-\d{2})$")


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # Skip HTTPServer.server_bind's socket.getfqdn(): a reverse DNS lookup that delays
        # listening by ~5 s when DNS is unavailable.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


@dataclass
class State:
    index: Index | None = None
    fetched_at: float | None = None
    last_error: str | None = None


def bond_json(bond: Bond) -> dict:
    latest_date, price = bond.latest
    maturity = bond.maturity.isoformat()
    return {
        "slug": bond.slug,
        "name": bond.name,
        "maturity": maturity,
        "latestDate": latest_date.isoformat(),
        "price": price,
        "priceUrl": f"/tesouro/price/{bond.slug}/{maturity}",
    }


def make_server(state: State, port: int, max_age_days: int, today=date.today) -> Server:
    class Handler(BaseHTTPRequestHandler):
        server_version = "br-fixed-income"

        def send(self, status: int, body, content_type="application/json"):
            text = json.dumps(body) if content_type == "application/json" else body
            data = text.encode()
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def error(self, status: int, message: str):
            self.send(status, {"error": message})

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == "/health":
                return self.health()
            index = state.index
            if url.path == "/tesouro/bonds":
                if index is None:
                    return self.error(503, "no data yet")
                return self.send(200, [bond_json(b) for b in index.all()])
            match = BOND_ROUTE.match(url.path)
            if not match:
                return self.error(404, "not found")
            if index is None:
                return self.error(503, "no data yet")
            kind, slug, maturity_text = match.groups()
            try:
                maturity = date.fromisoformat(maturity_text)
            except ValueError:
                return self.error(400, "maturity must be YYYY-MM-DD")
            bond = index.get(slug, maturity)
            if bond is None:
                return self.error(404, f"unknown bond {slug}/{maturity_text}; see /tesouro/bonds")
            if kind == "price":
                latest_date, price = bond.latest
                return self.send(200, {
                    "symbol": f"{slug}/{maturity_text}",
                    "name": bond.name,
                    "date": latest_date.isoformat(),
                    "price": price,
                })
            return self.history(bond, parse_qs(url.query).get("from", [None])[0])

        def history(self, bond: Bond, from_text: str | None):
            try:
                start = date.fromisoformat(from_text) if from_text else date.min
            except ValueError:
                return self.error(400, "from must be YYYY-MM-DD")
            lines = [f"{day.isoformat()};{price}" for day, price in bond.prices if day >= start]
            self.send(200, "\n".join(["date;marketPrice", *lines]) + "\n", "text/plain")

        def health(self):
            index = state.index
            body = {
                "status": "ok",
                "dataDate": None,
                "fetchedAt": state.fetched_at,
                "bonds": 0,
                "lastError": state.last_error,
            }
            if index is None:
                body["status"] = "no data"
                return self.send(503, body)
            body.update(dataDate=index.data_date.isoformat(), bonds=len(index.bonds))
            if (today() - index.data_date).days > max_age_days:
                body["status"] = "stale"
                return self.send(503, body)
            self.send(200, body)

    return Server(("0.0.0.0", port), Handler)
