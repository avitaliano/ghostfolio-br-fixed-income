"""Print SQL that seeds Ghostfolio with every Tesouro Direto bond as a MANUAL asset.

Each bond gets a global asset profile (findable by name in Ghostfolio's search box), its full price
history, and a scraper configuration pointing at this service, so prices keep updating by themselves.
Re-running is safe: profiles and prices are upserted, existing ids (and the activities using them)
are kept.

    docker exec br-fixed-income python -m br_fixed_income.ghostfolio_seed \\
      | docker exec -i ghostfolio-db psql -v ON_ERROR_STOP=1 -U ghostfolio ghostfolio

This writes Ghostfolio's tables directly (there's no API for it without an admin token), so it
depends on Ghostfolio's schema; it was written against Ghostfolio 3.93.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from br_fixed_income.tesouro.data import Bond, Index, parse_csv

MARKET_DATA_ROWS_PER_STATEMENT = 1000
COMMENT = "Tesouro Direto, seeded by ghostfolio-br-fixed-income"


def sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def ghostfolio_symbol(bond: Bond) -> str:
    # Ghostfolio requires MANUAL symbols to start with "GF_".
    return "GF_" + bond.name_slug.upper()


def price_path(bond: Bond, index: Index) -> str:
    if len(index.by_name[bond.name_slug]) == 1:
        return f"/tesouro/price/{bond.name_slug}"
    return f"/tesouro/price/{bond.slug}/{bond.maturity.isoformat()}"


def profile_sql(bond: Bond, index: Index, base_url: str) -> str:
    scraper = json.dumps({
        "url": base_url.rstrip("/") + price_path(bond, index),
        "selector": "$.price",
        "locale": "en-US",
        "mode": "lazy",
    })
    values = ", ".join([
        sql_text(ghostfolio_symbol(bond)),
        "gen_random_uuid()::text",
        "'MANUAL'",
        sql_text(bond.name),
        "'BRL'",
        "'FIXED_INCOME'",
        "'BOND'",
        sql_text(scraper) + "::jsonb",
        sql_text(COMMENT),
        "NOW()",
    ])
    return (
        'INSERT INTO "SymbolProfile" (symbol, id, "dataSource", name, currency, "assetClass", '
        '"assetSubClass", "scraperConfiguration", comment, "updatedAt")\n'
        f"VALUES ({values})\n"
        'ON CONFLICT ("dataSource", symbol) DO UPDATE SET name = EXCLUDED.name, '
        'currency = EXCLUDED.currency, "assetClass" = EXCLUDED."assetClass", '
        '"assetSubClass" = EXCLUDED."assetSubClass", '
        '"scraperConfiguration" = EXCLUDED."scraperConfiguration", '
        'comment = EXCLUDED.comment, "updatedAt" = NOW();\n'
    )


def market_data_sql(bond: Bond) -> str:
    symbol = sql_text(ghostfolio_symbol(bond))
    rows = [f"({symbol}, '{day.isoformat()}', {price})" for day, price in bond.prices]
    statements = []
    for start in range(0, len(rows), MARKET_DATA_ROWS_PER_STATEMENT):
        chunk = ",\n".join(rows[start:start + MARKET_DATA_ROWS_PER_STATEMENT])
        statements.append(
            'INSERT INTO "MarketData" (id, "dataSource", symbol, date, "marketPrice", state)\n'
            "SELECT gen_random_uuid()::text, 'MANUAL', v.symbol, v.day::timestamp, v.price, 'CLOSE'\n"
            f"FROM (VALUES\n{chunk}\n) AS v(symbol, day, price)\n"
            'ON CONFLICT ("dataSource", symbol, date) DO UPDATE SET "marketPrice" = EXCLUDED."marketPrice";\n'
        )
    return "".join(statements)


def seed_sql(index: Index, base_url: str, include_matured: bool = False) -> str:
    bonds = [b for b in index.all() if include_matured or b.latest[0] == index.data_date]
    parts = ["BEGIN;\n"]
    for bond in bonds:
        parts.append(f"-- {bond.name}\n")
        parts.append(profile_sql(bond, index, base_url))
        parts.append(market_data_sql(bond))
    parts.append("COMMIT;\n")
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://br-fixed-income:8000",
                        help="how Ghostfolio reaches this service (default: %(default)s)")
    parser.add_argument("--all", action="store_true", help="also seed matured bonds")
    args = parser.parse_args()

    cache_path = Path(os.environ.get("CACHE_DIR", "/data")) / "precotaxatesourodireto.csv"
    if not cache_path.exists():
        sys.exit(f"no cached data at {cache_path}; wait for /health to report ok")
    index = parse_csv(cache_path.read_bytes())
    sys.stdout.write(seed_sql(index, args.base_url, include_matured=args.all))


if __name__ == "__main__":
    main()
