import unittest
from datetime import date
from pathlib import Path

from br_fixed_income.tesouro.data import display_name, parse_csv, slugify

FIXTURE = Path(__file__).parent / "fixtures" / "sample.csv"


class DisplayNameTest(unittest.TestCase):
    def test_site_names(self):
        self.assertEqual(display_name("Tesouro IPCA+", date(2035, 5, 15)), "Tesouro IPCA+ 2035")
        self.assertEqual(
            display_name("Tesouro IPCA+ com Juros Semestrais", date(2040, 8, 15)),
            "Tesouro IPCA+ com Juros Semestrais 2040",
        )
        self.assertEqual(display_name("Tesouro Selic", date(2031, 3, 1)), "Tesouro Selic 2031")

    def test_renda_and_educa_named_by_first_payment_year(self):
        # The site spells it "RendA+"; the CSV says "Renda+".
        self.assertEqual(
            display_name("Tesouro Renda+ Aposentadoria Extra", date(2084, 12, 15)),
            "Tesouro RendA+ Aposentadoria Extra 2065",
        )
        self.assertEqual(display_name("Tesouro Educa+", date(2034, 12, 15)), "Tesouro Educa+ 2030")


class SlugifyTest(unittest.TestCase):
    def test_slugs(self):
        self.assertEqual(slugify("Tesouro IPCA+"), "tesouro-ipca")
        self.assertEqual(
            slugify("Tesouro IPCA+ com Juros Semestrais"),
            "tesouro-ipca-com-juros-semestrais",
        )
        self.assertEqual(slugify(" Tesouro Educa+ "), "tesouro-educa")
        self.assertEqual(slugify("Título Ç"), "titulo-c")


class ParseCsvTest(unittest.TestCase):
    def setUp(self):
        self.index = parse_csv(FIXTURE.read_bytes())

    def test_latest_sell_price(self):
        bond = self.index.get("tesouro-ipca", date(2035, 5, 15))
        self.assertEqual(bond.latest, (date(2026, 10, 24), 3530.12))
        self.assertEqual(bond.name, "Tesouro IPCA+ 2035")

    def test_names_for_all_bonds(self):
        names = {b.name for b in self.index.all()}
        self.assertEqual(names, {
            "Tesouro IPCA+ 2035", "Tesouro IPCA+ com Juros Semestrais 2040",
            "Tesouro Selic 2031", "Tesouro Selic 2025",
            "Tesouro RendA+ Aposentadoria Extra 2065", "Tesouro Educa+ 2030",
        })

    def test_duplicate_date_keeps_last_row(self):
        bond = self.index.get("tesouro-ipca", date(2035, 5, 15))
        self.assertEqual(bond.prices[0], (date(2026, 10, 23), 3526.00))
        self.assertEqual(len(bond.prices), 2)

    def test_matured_bond_kept_with_last_date(self):
        bond = self.index.get("tesouro-selic", date(2025, 3, 1))
        self.assertEqual(bond.latest, (date(2025, 2, 28), 16123.40))

    def test_zero_and_malformed_rows_skipped(self):
        self.assertIsNone(self.index.get("tesouro-prefixado", date(2031, 1, 1)))

    def test_data_date_is_newest_base_date(self):
        self.assertEqual(self.index.data_date, date(2026, 10, 24))

    def test_all_sorted(self):
        keys = [(b.slug, b.maturity) for b in self.index.all()]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), 6)

    def test_bom_and_latin1(self):
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertIsNotNone(parse_csv(b"\xef\xbb\xbf" + text.encode()).data_date)
        latin = text.replace("Tesouro Selic", "Tesouro Selíc").encode("latin-1")
        self.assertIsNotNone(parse_csv(latin).get("tesouro-selic", date(2031, 3, 1)))

    def test_header_whitespace_tolerated(self):
        text = FIXTURE.read_text().replace("PU Venda Manha", " PU Venda Manha ")
        self.assertIsNotNone(parse_csv(text.encode()).data_date)

    def test_missing_column_raises(self):
        text = FIXTURE.read_text().replace("PU Venda Manha", "PU Venda")
        with self.assertRaises(ValueError):
            parse_csv(text.encode())

    def test_no_usable_rows_raises(self):
        header = FIXTURE.read_text().splitlines()[0]
        with self.assertRaises(ValueError):
            parse_csv((header + "\n").encode())
