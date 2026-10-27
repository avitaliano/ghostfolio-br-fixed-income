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

Without cloning, swap `build: .` for `image: ghcr.io/avitaliano/ghostfolio-br-fixed-income:<version>`
in `compose.yaml`.

## Add a bond to Ghostfolio

1. Find the bond: `docker exec ghostfolio curl -s http://br-fixed-income:8000/tesouro/bonds`.
   Each entry has the bond's `name`, exactly as on the Tesouro Direto site (e.g. `Tesouro IPCA+ 2035`),
   and its `priceUrl`.
2. **Admin Control → Market Data → + → Add Manually**: data source `MANUAL`, a symbol of your choice
   (e.g. `TD-IPCA-2035`), currency `BRL`. Then open the asset and set **Name** to the `name` from step 1,
   **Asset Class** `Fixed Income` and **Asset Sub Class** `Bond`.
3. **Scraper Configuration** on that asset:

   | Field | Value |
   |---|---|
   | URL | `http://br-fixed-income:8000` + the `priceUrl`, e.g. `http://br-fixed-income:8000/tesouro/price/tesouro-ipca/2035-05-15` |
   | Selector | `$.price` |
   | Locale | `en-US` |
   | Mode | `lazy` |

   Click **Test** (it shows today's price), then **Save**. Ghostfolio records the price daily from now on.
4. **History, once:** fetch it and paste the output into the asset's **Historical Data** box.
   ```sh
   docker exec ghostfolio curl -s http://br-fixed-income:8000/tesouro/history/tesouro-ipca/2035-05-15
   ```
   Add `?from=2024-01-01` to limit it to the period you held the bond.
5. Add your buy activities against that asset as usual (quantity = number of títulos, fractions allowed).

## API

| Path | Returns |
|---|---|
| `GET /health` | `200 {"status":"ok","dataDate":…}`; `503` if no data yet or the data is older than `MAX_AGE_DAYS` |
| `GET /tesouro/bonds` | every bond in the dataset (including matured ones) with `name`, `maturity`, `latestDate`, `price`, `priceUrl` |
| `GET /tesouro/price/<slug>/<YYYY-MM-DD>` | `{"symbol","name","date","price"}`, the latest price |
| `GET /tesouro/history/<slug>/<YYYY-MM-DD>[?from=YYYY-MM-DD]` | `date;marketPrice` lines, Ghostfolio's import format |

The slug is the bond type (`tesouro-selic`, `tesouro-ipca`, `tesouro-ipca-com-juros-semestrais`,
`tesouro-prefixado`, `tesouro-prefixado-com-juros-semestrais`, `tesouro-renda-aposentadoria-extra`,
`tesouro-educa`, `tesouro-igpm-com-juros-semestrais`). The date is the maturity date in the dataset.

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
4. No Ghostfolio, crie um ativo MANUAL (BRL, Renda Fixa/Título) com *Scraper Configuration*: URL
   `http://br-fixed-income:8000/tesouro/price/<slug>/<vencimento>`, seletor `$.price`, locale `en-US`.
5. Cole o histórico de `/tesouro/history/<slug>/<vencimento>` em *Historical Data*.

O preço é o PU de venda (bruto, sem IR/IOF/custódia), da base oficial do Tesouro Transparente.

## License

MIT
