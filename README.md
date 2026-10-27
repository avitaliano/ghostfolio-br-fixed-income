# ghostfolio-br-fixed-income

Free, self-hosted prices for **Brazilian fixed income** in [Ghostfolio](https://ghostfol.io).

**Phase 1: Tesouro Direto.** It downloads the official Tesouro Transparente open dataset once a day
and serves each bond's latest price as JSON for Ghostfolio's built-in scraper, plus its full price
history for a one-time import.

- **No paid API.** The data is the government's open dataset.
- **No Ghostfolio token.** Ghostfolio pulls from this service; this service never logs in to Ghostfolio.
- **Small.** One container, Python standard library only, no dependencies.

Planned: CDB / LCI / LCA and other CDI-, IPCA- or Selic-indexed bonds, valued from the Banco Central's public series.

## Quick start

Run it next to Ghostfolio, on the same Docker network:

```sh
git clone https://github.com/avitaliano/ghostfolio-br-fixed-income
cd ghostfolio-br-fixed-income
# Find your Ghostfolio network:
docker inspect ghostfolio -f '{{json .NetworkSettings.Networks}}'
GHOSTFOLIO_NETWORK=<that network> docker compose up -d --build
docker exec ghostfolio curl -s http://br-fixed-income:8000/health
```

The first start downloads about 15 MB; `/health` returns `"status": "ok"` once the data is loaded.
If the government site is rate-limiting (HTTP 429), the service keeps retrying every hour until the
first download succeeds; `/health` shows the last error meanwhile.

Without cloning, replace the `build: .` and `image: …` lines in `compose.yaml` with
`image: ghcr.io/avitaliano/ghostfolio-br-fixed-income:<version>`.

## Option 1: seed every bond into Ghostfolio (search by name)

One command creates every currently quoted Tesouro Direto bond in Ghostfolio as a global MANUAL
asset: name as on the Tesouro Direto site, BRL, Fixed Income / Bond, **full price history**, and the
scraper URL already set, so prices keep updating. After that, **Add Activity → search "Tesouro IPCA"**
finds them like any stock.

```sh
docker exec br-fixed-income python -m br_fixed_income.ghostfolio_seed \
  | docker exec -i ghostfolio-db psql -v ON_ERROR_STOP=1 -U ghostfolio ghostfolio
```

- Back up Ghostfolio's database first. This writes its `SymbolProfile` and `MarketData` tables directly,
  since Ghostfolio has no import path for asset profiles without activities. Written against Ghostfolio 3.93.
- Safe to re-run (e.g. when the Tesouro issues new bonds): rows are upserted, and existing assets keep
  their ids and your activities.
- Add `--all` to include matured bonds, and `--base-url` if Ghostfolio reaches the service under another name.
- Ghostfolio's search matches the **start** of the name: type `Tesouro IPCA`, not `IPCA`.
- Symbols are `GF_` + the name-derived symbol, e.g. `GF_TESOURO-IPCA-2035`.

## Option 2: add a single bond by hand

Every bond has a **symbol derived from its name on the Tesouro Direto site**: lowercase, drop the
`+`, spaces become `-`. `Tesouro IPCA+ 2035` → `tesouro-ipca-2035`, `Tesouro RendA+ Aposentadoria Extra 2065`
→ `tesouro-renda-aposentadoria-extra-2065`. Use it as the Ghostfolio symbol and the URL writes itself.
`/tesouro/bonds` lists every bond with its `symbol` and `priceUrl`.

1. **Admin Control → Market Data → + → Add Manually**: data source `MANUAL`, symbol e.g.
   `tesouro-ipca-2035`, currency `BRL`. Then open the asset and set **Name** `Tesouro IPCA+ 2035`,
   **Asset Class** `Fixed Income` and **Asset Sub Class** `Bond`.
2. **Scraper Configuration** on that asset:

   | Field | Value |
   |---|---|
   | URL | `http://br-fixed-income:8000/tesouro/price/<symbol>`, e.g. `http://br-fixed-income:8000/tesouro/price/tesouro-ipca-2035` |
   | Selector | `$.price` |
   | Locale | `en-US` |
   | Mode | `lazy` |

   Click **Test** (it shows today's price), then **Save**. Ghostfolio records the price daily from now on.
3. **History (optional):** for performance charts over time, paste the output into the asset's
   **Historical Data** box. Not needed if you only care about the current value.
   ```sh
   docker exec ghostfolio curl -s http://br-fixed-income:8000/tesouro/history/tesouro-ipca-2035
   ```
   Add `?from=2024-01-01` to limit it to the period you held the bond.
4. Add your buy activities against that asset as usual (quantity = number of títulos, fractions allowed).
   If you only track what you hold today, one Buy with your current quantity and average price is enough.

## API

| Path | Returns |
|---|---|
| `GET /health` | `200 {"status":"ok","dataDate":…}`; `503` if no data yet or the data is older than `MAX_AGE_DAYS` |
| `GET /tesouro/bonds` | every bond in the dataset (including matured ones) with `symbol`, `name`, `maturity`, `latestDate`, `price`, `priceUrl` |
| `GET /tesouro/price/<symbol>` | `{"symbol","name","date","price"}`, the latest price |
| `GET /tesouro/history/<symbol>[?from=YYYY-MM-DD]` | `date;marketPrice` lines, Ghostfolio's import format |

`<symbol>` is the name-derived symbol above. A few bonds that matured before 2014 share a name with
another maturity in the same year; for those, the name URL answers `409` with the alternatives, and the
long form `/tesouro/price/<type>/<maturity YYYY-MM-DD>` (e.g. `/tesouro/price/tesouro-ipca/2035-05-15`) works
for every bond.

## What the price means

- It's the **sell price** (`PU Venda Manha`): what you'd get selling one título that morning. That's
  the right value for net worth.
- It's **gross**: no income tax (IR), IOF or B3 custody fee is deducted.
- For **RendA+** and **Educa+**, the dataset dates each bond by its *last* payment. The service names
  them the way the site does: RendA+ 2065 has maturity `2084-12-15` in the URL.
- **Tesouro Reserva** is sold only through Banco do Brasil and isn't in the dataset, so it isn't covered.

## Data source and politeness

[Tesouro Transparente](https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto)
open data ("Taxas dos Títulos Ofertados pelo Tesouro Direto"). The download endpoint rate-limits
(HTTP 429), so the service downloads **once a day**, identifies itself in its User-Agent, honours
`Retry-After`, and backs off. The last good file is cached in the `/data` volume, so restarts and
outages keep serving prices.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `GHOSTFOLIO_NETWORK` | `ghostfolio_default` | Docker network shared with Ghostfolio (compose only) |
| `PORT` | `8000` | HTTP port inside the container |
| `FETCH_HOUR_UTC` | `13` | daily download time (the dataset updates around 10:20 UTC) |
| `MAX_AGE_DAYS` | `5` | `/health` reports `stale` beyond this (covers long weekends) |
| `CACHE_DIR` | `/data` | where the last good CSV is kept |

## Security

There's no authentication: serve it only on an internal Docker network, never on a public port or a
reverse proxy. It holds no secrets and no personal data, and needs outbound HTTPS to
`tesourotransparente.gov.br` only. The container runs as a non-root user on a read-only filesystem
with all capabilities dropped.

## Development

```sh
./test.sh discover -v      # unittest inside python:3.13 (no local Python needed)
```

## Início rápido (PT-BR)

1. `git clone` este repositório e entre na pasta.
2. `GHOSTFOLIO_NETWORK=<rede do seu Ghostfolio> docker compose up -d --build`
3. Veja os títulos: `docker exec ghostfolio curl -s http://br-fixed-income:8000/tesouro/bonds`
4. No Ghostfolio, crie um ativo MANUAL (BRL, Renda Fixa/Título) com símbolo derivado do nome do título
   (`Tesouro IPCA+ 2035` → `tesouro-ipca-2035`) e *Scraper Configuration*: URL
   `http://br-fixed-income:8000/tesouro/price/<símbolo>`, seletor `$.price`, locale `en-US`.
5. Opcional: cole o histórico de `/tesouro/history/<símbolo>` em *Historical Data*.

O preço é o PU de venda (bruto, sem IR/IOF/custódia), da base oficial do Tesouro Transparente.

## License

MIT
