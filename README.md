# SIA Portfolio — FINN3021 Summative

Ex-ante equity screener built in Python/Jupyter for the Durham FINN3021 Security Investment Analysis summative (report due 27 April 2026).

## Quick start

```bash
cd ~/Documents/SIA_Portfolio
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — set WRDS_USERNAME (required for Postgres)
# set WRDS_API_TOKEN (only if you need REST fallback)

# first-time WRDS Postgres auth: creates ~/.pgpass
python -c "import wrds; wrds.Connection()"

jupyter notebook notebooks/01_screen.ipynb
```

## What's here

```
SIA_Portfolio/
├── src/
│   ├── constants.py      committed screen thresholds + country lists
│   ├── wrds_client.py    Postgres + REST + yfinance access layer, with parquet caching
│   ├── qa.py             data-quality checks run at every pipeline stage
│   └── screen.py         Tier 1/2 logic, metric formulas, final ranking
├── notebooks/
│   └── 01_screen.ipynb   main deliverable — run top to bottom
├── data/
│   ├── cache/            raw WRDS pulls cached as parquet (gitignored)
│   └── outputs/          final portfolio + diagnostics (gitignored)
└── .env.example          template — copy to .env and fill in
```

## Screening methodology (committed — do not tweak to chase outputs)

**As-of date** — 9 March 2026. Point-in-time: a firm-year is admitted only if `datadate + 4 months ≤ 2026-03-09` (conservative filing-lag proxy for Compustat Global where `rdq` is often missing on annuals).

**Universe** — MSCI DM ex-US + EM country lists (see `constants.py`). GICS Financials (40) and Real Estate (60) excluded.

**Tier 1 — all must hold**:
1. FCF > 0 in each of last 5 fiscal years, `FCF = oancf − capx`
2. Latest `net_debt / EBITDA < 4×`, where `net_debt = (dlc + dltt) − che`, `EBITDA = oibdp`
3. Sector filter (above)

**Tier 2 composite (Tier 1 survivors only)** — min-max scaled within each sleeve:
- 0.50 · Piotroski F-score (standard 9-factor, latest FY vs prior FY)
- 0.30 · 5-year arithmetic mean of ROIC, where ROIC = `EBIT × (1 − tax_rate) / (total_debt + book_equity − cash)` and `tax_rate = clip(txt/pi, 0, 0.5)`
- 0.20 · 5-year FCF CAGR = `(FCF_t / FCF_{t-4})^(1/4) − 1`

**Ranking within top quintile of composite** — 5-year mean of `FCF_t / EV_t` (historical multiples), where `EV_t = market_cap at FYE_t + net_debt_t`.

**Selection** — top 15 DM ex-US + top 5 EM, ranked within each sleeve. ≥1 SA name if screen produces one.

## Principles

- **Ex-ante discipline.** The point-in-time cutoff is asserted by `qa.check_point_in_time`. If the screen produces names that look weird, diagnose the *data*, never the thresholds.
- **Transparency.** Every threshold is a named constant in `constants.py`. Every formula is in a documented function in `screen.py`. The notebook is the audit trail.
- **Reproducibility.** All WRDS pulls are cached to `data/cache/*.parquet`. Timestamp and row counts logged at every stage via `qa.report`.

## Known methodological caveats (mention in report)

1. **Survivorship** — Compustat Global includes delisted firms, but firms that failed before 2021 are absent from the 5-year history by construction. Impact likely small (selecting for 5y positive FCF already filters fragile firms).
2. **Filing lag proxy** — using `datadate + 4 months` when `rdq` missing is conservative; some firms file faster, some slower. Does not leak post-cutoff data but may exclude a few FY2025 filings that landed earlier than 4 months.
3. **Currency** — Compustat Global reports in local currency. All metrics used are ratios (Piotroski, ROIC, FCF growth, FCF/EV) so currency cancels firm-by-firm. No FX conversion applied.
4. **GICS coverage** — Financials/REIT exclusion based on `gsector` only; firms with missing GICS are kept and flagged in QA.

## AI appendix

Per the Department Generative AI Policy, prompts and responses used to build this pipeline must be included as an appendix to the report. Keep a log of prompt exchanges alongside the commits.
