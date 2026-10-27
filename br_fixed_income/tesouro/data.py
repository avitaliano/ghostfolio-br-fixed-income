"""Parse the Tesouro Transparente price CSV into an in-memory index."""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

PRICE_COLUMN = "PU Venda Manha"
REQUIRED_COLUMNS = ("Tipo Titulo", "Data Vencimento", "Data Base", PRICE_COLUMN)

# Renda+ and Educa+ are dated in the CSV by their last payment; the product name uses the first.
NAME_YEAR_OFFSETS = {"tesouro-renda-aposentadoria-extra": -19, "tesouro-educa": -4}
# CSV "Tipo Titulo" -> exact spelling on tesourodireto.com.br, only where they differ.
SITE_TYPE_NAMES = {"Tesouro Renda+ Aposentadoria Extra": "Tesouro RendA+ Aposentadoria Extra"}


def slugify(bond_type: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", bond_type).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def display_name(bond_type: str, maturity: date) -> str:
    """Name as shown on the Tesouro Direto site, e.g. 'Tesouro IPCA+ 2035'."""
    year = maturity.year + NAME_YEAR_OFFSETS.get(slugify(bond_type), 0)
    return f"{SITE_TYPE_NAMES.get(bond_type, bond_type)} {year}"


def parse_number(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    if "," in text:  # Brazilian format: 1.234,56
        text = text.replace(".", "").replace(",", ".")
    return float(text)


def parse_date(text: str) -> date:
    return datetime.strptime(text.strip(), "%d/%m/%Y").date()


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


@dataclass(frozen=True)
class Bond:
    slug: str
    name: str
    maturity: date
    prices: tuple[tuple[date, float], ...]  # sorted by date, one entry per date

    @property
    def latest(self) -> tuple[date, float]:
        return self.prices[-1]


class Index:
    def __init__(self, bonds: dict[tuple[str, date], Bond]):
        self.bonds = bonds
        self.data_date = max((b.latest[0] for b in bonds.values()), default=None)

    def get(self, slug: str, maturity: date) -> Bond | None:
        return self.bonds.get((slug, maturity))

    def all(self) -> list[Bond]:
        return [self.bonds[key] for key in sorted(self.bonds)]


def parse_csv(raw: bytes) -> Index:
    reader = csv.DictReader(io.StringIO(decode(raw)), delimiter=";")
    reader.fieldnames = [name.strip() for name in reader.fieldnames or []]
    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise ValueError(f"CSV is missing columns: {missing}")

    series: dict[tuple[str, date], dict[date, float]] = {}
    names: dict[tuple[str, date], str] = {}
    for row in reader:
        try:
            price = parse_number(row[PRICE_COLUMN] or "")
            if not price or price <= 0:
                continue
            name = row["Tipo Titulo"].strip()
            key = (slugify(name), parse_date(row["Data Vencimento"]))
            base_date = parse_date(row["Data Base"])
        except (ValueError, AttributeError):
            continue  # malformed row: skip, don't fail the whole file
        series.setdefault(key, {})[base_date] = price
        names[key] = name

    if not series:
        raise ValueError("CSV has no usable rows")
    return Index(
        {
            key: Bond(key[0], display_name(names[key], key[1]), key[1], tuple(sorted(days.items())))
            for key, days in series.items()
        }
    )
