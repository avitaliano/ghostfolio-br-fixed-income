import json
import re
import unittest
from pathlib import Path

from br_fixed_income.ghostfolio_seed import ghostfolio_symbol, seed_sql
from br_fixed_income.tesouro.data import parse_csv

FIXTURE = Path(__file__).parent / "fixtures" / "sample.csv"
BASE_URL = "http://br-fixed-income:8000"


class SeedSqlTest(unittest.TestCase):
    def setUp(self):
        self.index = parse_csv(FIXTURE.read_bytes())
        self.sql = seed_sql(self.index, BASE_URL)

    def test_symbol_has_ghostfolio_manual_prefix(self):
        bond = self.index.find("tesouro-ipca-2035")
        self.assertEqual(ghostfolio_symbol(bond), "GF_TESOURO-IPCA-2035")

    def test_runs_in_one_transaction(self):
        self.assertTrue(self.sql.startswith("BEGIN;\n"))
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))

    def test_only_currently_quoted_bonds_by_default(self):
        # Selic 2025 matured (last price 2025-02-28); the other five are on the latest date.
        self.assertEqual(self.sql.count('INSERT INTO "SymbolProfile"'), 5)
        self.assertNotIn("GF_TESOURO-SELIC-2025", self.sql)
        everything = seed_sql(self.index, BASE_URL, include_matured=True)
        self.assertEqual(everything.count('INSERT INTO "SymbolProfile"'), 6)

    def test_profile_fields_and_scraper(self):
        row = re.search(r"\('GF_TESOURO-IPCA-2035'.*?\)\nON CONFLICT", self.sql, re.S).group(0)
        self.assertIn("'Tesouro IPCA+ 2035'", row)
        self.assertIn("'BRL'", row)
        self.assertIn("'FIXED_INCOME'", row)
        self.assertIn("'BOND'", row)
        scraper = json.loads(re.search(r"'(\{\"url\".*?\})'::jsonb", row).group(1))
        self.assertEqual(scraper, {
            "url": "http://br-fixed-income:8000/tesouro/price/tesouro-ipca-2035",
            "selector": "$.price",
            "locale": "en-US",
            "mode": "lazy",
        })

    def test_upsert_keeps_existing_ids(self):
        # Existing activities reference SymbolProfile.id, so a re-run must update, never replace.
        self.assertIn('ON CONFLICT ("dataSource", symbol) DO UPDATE SET', self.sql)
        self.assertNotIn('"id" = EXCLUDED', self.sql)
        self.assertIn('ON CONFLICT ("dataSource", symbol, date) DO UPDATE SET "marketPrice"', self.sql)

    def test_market_data_history(self):
        self.assertIn("('GF_TESOURO-IPCA-2035', '2026-10-23', 3526.0)", self.sql)
        self.assertIn("('GF_TESOURO-IPCA-2035', '2026-10-24', 3530.12)", self.sql)

    def test_quotes_are_escaped(self):
        from br_fixed_income.ghostfolio_seed import sql_text
        self.assertEqual(sql_text("O'Brien"), "'O''Brien'")
