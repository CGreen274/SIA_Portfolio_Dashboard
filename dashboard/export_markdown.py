#!/usr/bin/env python3
"""
Export a comprehensive Markdown snapshot of the portfolio.

Usage:
    python dashboard/export_markdown.py              # live (up to today)
    python dashboard/export_markdown.py --eval       # evaluation window only

The output file is written to data/outputs/portfolio_report.md
(or portfolio_report_eval.md for --eval).  Upload that file to Claude
or any LLM for analysis — no live data or URLs needed.
"""

import argparse
import pathlib
import sys
from datetime import date
from textwrap import dedent

import numpy as np
import pandas as pd
import yfinance as yf

# Ensure project root is importable
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.app import (
    BENCHMARK,
    INCEPTION,
    NOTIONAL,
    RISK_FREE_ANNUAL,
    HORIZON_YRS,
    compute_all,
    load_fundamentals,
    load_snapshot,
)

EVAL_END = date(2026, 4, 20)
OUT_DIR = ROOT / "data" / "outputs"


def _df_to_md(df: pd.DataFrame) -> str:
    """Convert a DataFrame to a Markdown table string."""
    cols = df.columns.tolist()
    lines = ["| " + " | ".join(str(c) for c in cols) + " |"]
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def build_report(end_date=None) -> str:
    """Run compute_all and render a full Markdown report."""
    label = f"Evaluation Period ({INCEPTION} → {end_date})" if end_date else f"Live (inception {INCEPTION} → today)"
    print(f"Computing metrics for: {label} ...")
    d = compute_all(end_date=end_date)

    pos = d["pos_pnl"]
    total_ret = d["port_return"].iloc[-1]
    bench_ret = d["bench_return"].iloc[-1]
    active_ret = total_ret - bench_ret
    first_date = d["prices"].index[0].strftime("%Y-%m-%d")
    last_date = d["prices"].index[-1].strftime("%Y-%m-%d")
    days = (d["prices"].index[-1] - d["prices"].index[0]).days

    # ── Holdings table ────────────────────────────────────────
    htbl = pos[["name", "ticker", "country", "sector",
                "inception_px", "current_px", "pnl", "return_pct",
                "weight_now"]].copy()
    htbl.columns = ["Name", "Ticker", "Country", "Sector",
                    "Entry Px", "Current Px", "P&L ($)", "Return %", "Weight %"]
    for c in ["Entry Px", "Current Px"]:
        htbl[c] = htbl[c].round(2)
    htbl["P&L ($)"] = htbl["P&L ($)"].round(0).astype(int)
    htbl["Return %"] = htbl["Return %"].round(2)
    htbl["Weight %"] = htbl["Weight %"].round(2)
    htbl = htbl.sort_values("Return %", ascending=False)

    # ── Country & sector breakdowns ───────────────────────────
    ctry = pos.groupby("country_name")["current_value"].sum()
    ctry_pct = (ctry / ctry.sum() * 100).round(1).sort_values(ascending=False)
    ctry_df = pd.DataFrame({"Country": ctry_pct.index, "Weight %": ctry_pct.values})

    sec = pos.groupby("sector")["current_value"].sum()
    sec_pct = (sec / sec.sum() * 100).round(1).sort_values(ascending=False)
    sec_df = pd.DataFrame({"Sector": sec_pct.index, "Weight %": sec_pct.values})

    # ── Risk metrics ──────────────────────────────────────────
    risk_md = _df_to_md(d["risk_df"])

    # ── FX attribution ────────────────────────────────────────
    fx = d["fx_df"].sort_values("usd_ret", ascending=False)
    fx_md = _df_to_md(fx)

    # ── Correlation summary ───────────────────────────────────
    corr = d["corr"]
    avg_corr = corr.where(~np.eye(len(corr), dtype=bool)).stack().mean()
    # Top 5 most and least correlated pairs
    pairs = corr.where(np.triu(np.ones_like(corr, dtype=bool), k=1)).stack()
    top5 = pairs.nlargest(5)
    bot5 = pairs.nsmallest(5)

    # ── Dividends / Total Shareholder Yield ───────────────────
    def _safe_yield(info):
        raw_fwd = info.get("dividendYield")
        fwd = raw_fwd / 100 if raw_fwd is not None else None
        raw_trail = info.get("trailingAnnualDividendYield")
        if raw_trail is not None and raw_trail > 0:
            ccy = (info.get("currency") or "")
            is_minor = len(ccy) == 3 and ccy[-1].islower()
            trail = raw_trail * 100 if is_minor else raw_trail
        else:
            trail = fwd
        return trail, fwd

    def _buyback_yield(ticker_obj, info):
        try:
            cf = ticker_obj.cashflow
            mktcap = info.get("marketCap")
            if cf is None or cf.empty or not mktcap or mktcap <= 0:
                return None
            repurchase = 0
            if "Repurchase Of Capital Stock" in cf.index:
                v = cf.loc["Repurchase Of Capital Stock"].dropna()
                if len(v) > 0:
                    repurchase = float(v.iloc[0])
            issuance = 0
            if "Issuance Of Capital Stock" in cf.index:
                v = cf.loc["Issuance Of Capital Stock"].dropna()
                if len(v) > 0:
                    issuance = float(v.iloc[0])
            net_buyback = -(repurchase + issuance)
            return net_buyback / mktcap
        except Exception:
            return None

    print("Fetching dividend & buyback data ...")
    div_rows = []
    for _, h in pos.iterrows():
        try:
            tk = yf.Ticker(h["ticker"])
            info = tk.info
            trail_y, fwd_y = _safe_yield(info)
            bb_y = _buyback_yield(tk, info)
        except Exception:
            trail_y = fwd_y = bb_y = None
        fwd_pct = round(fwd_y * 100, 2) if fwd_y else None
        bb_pct = round(bb_y * 100, 2) if bb_y is not None else None
        total_sh = round((fwd_pct or 0) + (bb_pct or 0), 2)
        div_rows.append({
            "Name": h["name"], "Ticker": h["ticker"],
            "Fwd Yield %": fwd_pct, "Buyback Yield %": bb_pct,
            "Total SH Yield %": total_sh,
        })
    div_df = pd.DataFrame(div_rows)
    total_eq = pos["current_value"].sum()
    wt = pos["current_value"].values / total_eq
    port_div = np.nansum([(r.get("Fwd Yield %") or 0) * w for r, w in zip(div_rows, wt)])
    port_bb = np.nansum([(r.get("Buyback Yield %") or 0) * w for r, w in zip(div_rows, wt)])
    port_tsy = port_div + port_bb

    # ── Fundamentals ──────────────────────────────────────────
    try:
        fundas = load_fundamentals()
        fund_md = _df_to_md(fundas.reset_index().round(3))
    except Exception:
        fund_md = "_Not available._"

    # ── CAPM line ─────────────────────────────────────────────
    reg = d["reg"]

    # ── 10-year projection ────────────────────────────────────
    price_ann = (1 + total_ret) ** (365 / max(days, 1)) - 1
    total_ret_ann = price_ann + port_tsy / 100
    proj = []
    for y in range(0, HORIZON_YRS + 1):
        proj.append({
            "Year": y,
            "Price-Only NAV": f"${NOTIONAL * (1 + price_ann) ** y:,.0f}",
            "With TSY Reinvested": f"${NOTIONAL * (1 + total_ret_ann) ** y:,.0f}",
        })
    proj_df = pd.DataFrame(proj)

    # ── Daily return time-series (first & last 5 days) ────────
    pr = d["port_return"]
    br = d["bench_return"]
    ts_rows = []
    for dt in pr.index:
        ts_rows.append({
            "Date": dt.strftime("%Y-%m-%d"),
            "Port Cum %": round(pr.loc[dt] * 100, 2),
            "Bench Cum %": round(br.loc[dt] * 100, 2),
        })
    ts_df = pd.DataFrame(ts_rows)

    # ── Assemble Markdown ─────────────────────────────────────
    md = dedent(f"""\
    # FINN3021 — Portfolio Report
    **{label}**
    Generated: {date.today()}

    ---

    ## Overview
    | Parameter | Value |
    | --- | --- |
    | Inception | {INCEPTION} |
    | Report End | {last_date} |
    | Calendar Days | {days} |
    | Notional | ${NOTIONAL:,} |
    | Allocation | 100% Equity (conviction-weighted, 3 tiers) |
    | Holdings | {len(pos)} stocks across {pos['country'].nunique()} countries |
    | Benchmark | {BENCHMARK} (iShares MSCI ACWI ex-US) |
    | Risk-Free Rate | {RISK_FREE_ANNUAL:.1%} (US 1-yr T-Bill) |

    ## Summary
    | Metric | Value |
    | --- | --- |
    | Portfolio Value | ${d['port_value'].iloc[-1]:,.0f} |
    | Total Return | {total_ret:+.2%} |
    | Benchmark Return | {bench_ret:+.2%} |
    | Active Return | {active_ret:+.2%} |

    ---

    ## Holdings (sorted by return)
    {_df_to_md(htbl)}

    ---

    ## Country Exposure
    {_df_to_md(ctry_df)}

    ## Sector Exposure
    {_df_to_md(sec_df)}

    ---

    ## Risk Metrics (Portfolio vs Benchmark)
    {risk_md}

    ---

    ## CAPM Regression
    | Parameter | Value |
    | --- | --- |
    | Alpha (annualised) | {d['alpha_ann']:.2%} |
    | Beta | {d['beta']:.3f} |
    | R² | {d['r2']:.3f} |
    | Regression equation | r_port = {reg.intercept:.6f} + {reg.slope:.4f} × r_bench |

    ---

    """)

    # ── FF5 section ───────────────────────────────────────────
    ff5 = d.get("ff5")
    if ff5:
        factors = ["const", "MKT-RF", "SMB", "HML", "RMW", "CMA"]
        nice = {"const": "Alpha (daily)", "MKT-RF": "Market", "SMB": "Size (Small-Big)",
                "HML": "Value (High-Low)", "RMW": "Profitability (Robust-Weak)",
                "CMA": "Investment (Cons.-Agg.)"}
        ff_rows = []
        for f in factors:
            coeff = ff5["params"].get(f, 0)
            t = ff5["tvalues"].get(f, 0)
            p = ff5["pvalues"].get(f, 1)
            sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
            ff_rows.append({
                "Factor": nice.get(f, f),
                "Coefficient": round(coeff, 6) if f == "const" else round(coeff, 4),
                "t-stat": round(t, 2),
                "p-value": round(p, 4),
                "Sig.": sig,
            })
        ff_df = pd.DataFrame(ff_rows)
        md += dedent(f"""\
    ## Fama-French 5-Factor Decomposition
    **Model:** r_port − Rf = α + β₁(MKT−RF) + β₂(SMB) + β₃(HML) + β₄(RMW) + β₅(CMA) + ε

    | Summary | Value |
    | --- | --- |
    | R² | {ff5['rsquared']:.3f} |
    | Adj. R² | {ff5['rsquared_adj']:.3f} |
    | Alpha (annualised) | {ff5['alpha_ann']:.2%} |
    | Observations | {ff5['nobs']} |

    ### Factor Loadings
    {_df_to_md(ff_df)}

    **Significance:** \\*\\*\\* p<0.01, \\*\\* p<0.05, \\* p<0.10

    **Factor proxies (ETF-based):** MKT-RF = ACWX − Rf · SMB = SCZ − EFA · HML = EFV − EFG · RMW = IQLT − ACWX · CMA = EFAV − ACWX

    ---

    """)
    else:
        md += "## Fama-French 5-Factor Decomposition\n_Factor data unavailable for this period._\n\n---\n\n"

    md += dedent(f"""\
    ## FX / Return Attribution
    {fx_md}

    ---

    ## Correlation
    - **Average pairwise correlation:** {avg_corr:.3f}

    **Most correlated pairs:**
    """)

    for (a, b), v in top5.items():
        md += f"- {a} / {b}: {v:.3f}\n"

    md += "\n**Least correlated pairs:**\n"
    for (a, b), v in bot5.items():
        md += f"- {a} / {b}: {v:.3f}\n"

    md += dedent(f"""
    ---

    ## Full Correlation Matrix
    {_df_to_md(corr.round(2))}

    ---

    ## Total Shareholder Yield
    | Metric | Value |
    | --- | --- |
    | Weighted Dividend Yield | {port_div:.2f}% |
    | Weighted Buyback Yield | {port_bb:+.2f}% |
    | Total Shareholder Yield | {port_tsy:.2f}% |

    ### Per-Holding Yields
    {_df_to_md(div_df)}

    ---

    ## 10-Year Projection (price-only vs total shareholder return)
    - Price-only annualised return: {price_ann:.2%}
    - With TSY reinvested: {total_ret_ann:.2%}

    {_df_to_md(proj_df)}

    ---

    ## Screen Fundamentals
    {fund_md}

    ---

    ## Daily Cumulative Return Series
    {_df_to_md(ts_df)}

    ---
    _End of report._
    """)

    return md


def main():
    parser = argparse.ArgumentParser(description="Export portfolio report to Markdown")
    parser.add_argument("--eval", action="store_true",
                        help="Lock to evaluation window (inception → 20 Apr 2026)")
    args = parser.parse_args()

    end_date = EVAL_END if args.eval else None
    suffix = "_eval" if args.eval else ""
    out_path = OUT_DIR / f"portfolio_report{suffix}.md"

    md = build_report(end_date=end_date)
    out_path.write_text(md, encoding="utf-8")
    print(f"\n✅ Report written to {out_path}  ({len(md):,} chars)")


if __name__ == "__main__":
    main()
