"""
Screening logic — exactly as committed in the project brief.

Formulas (do not change without amending the report methodology):
  FCF             = oancf - capx
  EBITDA          = oibdp (latest annual)
  Net debt        = (dlc + dltt) - che
  ROIC            = ebit * (1 - tax_rate) / (total_debt + book_equity - cash)
                    5-year arithmetic mean
  FCF growth (5y) = (FCF_t / FCF_{t-5})^(1/5) - 1   (CAGR)
  FCF/EV (5y avg) = mean_{t=0..4}( FCF_t / EV_t )   (historical multiples)
  EV_t            = market_cap_t + net_debt_t  at FYE_t
  Piotroski       = standard 9-factor (profitability 4 + leverage/liquidity 3 + efficiency 2)

Tier 1 knockouts: all must hold →
  * FCF_t > 0 for each t in the last 5 FYs
  * latest net_debt / EBITDA < 4
  * GICS sector not in {40 Financials, 60 Real Estate}

Tier 2 composite (Tier 1 survivors only) →
  score = 0.50 * piotroski_norm + 0.30 * roic_5y_norm + 0.20 * fcf_growth_5y_norm
  (each term min-max scaled within sleeve)

Rank by 5y-avg FCF/EV within the top-quintile of the composite — within each
sleeve (DM ex-US vs EM). Take top 15 DM + top 5 EM (≥1 SA if available).
"""
from __future__ import annotations
import pandas as pd
import numpy as np

from . import constants as C


# ---------- Per-firm-year metrics from raw Compustat columns ----------
def add_fcf(funda: pd.DataFrame) -> pd.DataFrame:
    out = funda.copy()
    out["fcf"] = out["oancf"] - out["capx"]
    return out


def add_ebitda(funda: pd.DataFrame) -> pd.DataFrame:
    out = funda.copy()
    out["ebitda"] = out["oibdp"]
    return out


def add_net_debt(funda: pd.DataFrame) -> pd.DataFrame:
    out = funda.copy()
    out["net_debt"] = (out["dlc"].fillna(0) + out["dltt"].fillna(0)) - out["che"].fillna(0)
    return out


def add_roic(funda: pd.DataFrame) -> pd.DataFrame:
    """
    ROIC = EBIT * (1 - tax_rate) / (total_debt + book_equity - cash)
    tax_rate proxied by txt / pi (income tax / pretax income), clipped [0, 0.5]
    """
    out = funda.copy()
    tax_rate = (out["txt"] / out["pi"]).clip(lower=0.0, upper=0.5).fillna(0.25)
    out["tax_rate"] = tax_rate
    nopat = out["ebit"] * (1 - tax_rate)
    invested = (
        out["dlc"].fillna(0) + out["dltt"].fillna(0)
        + out["ceq"].fillna(0)
        - out["che"].fillna(0)
    )
    out["roic"] = nopat / invested.where(invested > 0)  # avoid div by 0 / negative IC
    return out


# ---------- Tier 1 hard knockouts ----------
def tier1_knockouts(panel: pd.DataFrame, company: pd.DataFrame) -> pd.DataFrame:
    """
    panel: firm-year fundamentals (must include fcf, ebitda, net_debt, fyear, gvkey).
    company: firm-level static (must include gvkey, gsector, fic).
    Returns the subset of firms passing Tier 1, with latest-year metrics attached.
    """
    # Sector exclusion
    keep_firms = company.loc[
        ~company["gsector"].astype(str).isin(C.EXCLUDED_GSECTOR),
        ["gvkey", "gsector", "fic"],
    ].drop_duplicates("gvkey")

    p = panel.merge(keep_firms, on="gvkey", how="inner")

    # Require exactly N_YEARS_FUNDA distinct FYs per firm, all with FCF>0
    fy_counts = p.groupby("gvkey")["fyear"].nunique()
    ok_history = fy_counts[fy_counts >= C.FCF_HISTORY_YEARS].index

    p = p[p["gvkey"].isin(ok_history)].copy()

    # keep only the last N_YEARS_FUNDA per firm
    p = p.sort_values(["gvkey", "fyear"]).groupby("gvkey").tail(C.N_YEARS_FUNDA)

    fcf_pos_all_years = (
        p.groupby("gvkey")["fcf"].apply(lambda s: (s > 0).all())
    )
    firms_fcf_ok = fcf_pos_all_years[fcf_pos_all_years].index

    # Leverage gate on LATEST year only
    latest = p.sort_values("fyear").groupby("gvkey").tail(1).set_index("gvkey")
    lev = latest["net_debt"] / latest["ebitda"].where(latest["ebitda"] > 0)
    latest["net_debt_ebitda"] = lev
    firms_lev_ok = latest[lev < C.LEVERAGE_MAX].index

    survivors = set(firms_fcf_ok) & set(firms_lev_ok)
    print(
        f"[tier1] sector OK: {keep_firms['gvkey'].nunique():,} | "
        f"5y FCF history: {len(ok_history):,} | "
        f"5y FCF>0: {len(firms_fcf_ok):,} | "
        f"leverage<{C.LEVERAGE_MAX}x: {len(firms_lev_ok):,} | "
        f"SURVIVORS: {len(survivors):,}"
    )
    return p[p["gvkey"].isin(survivors)].copy()


# ---------- Tier 2 composite metrics ----------
def piotroski(panel5: pd.DataFrame) -> pd.Series:
    """
    Standard 9-factor Piotroski F-score on the LATEST two fiscal years per firm.
    Requires columns: ni, oancf, at, dltt, act, lct, csho, sale, cogs.
    Deltas use latest FY vs prior FY.
    """
    p = panel5.sort_values(["gvkey", "fyear"])
    scores = {}
    for gv, g in p.groupby("gvkey"):
        if len(g) < 2:
            continue
        t = g.iloc[-1]
        tm1 = g.iloc[-2]
        s = 0
        # Profitability (4)
        s += int(t["ni"] > 0)
        s += int(t["oancf"] > 0)
        s += int((t["ni"] / t["at"]) > (tm1["ni"] / tm1["at"])) if tm1["at"] else 0  # ΔROA
        s += int(t["oancf"] > t["ni"])  # accruals quality
        # Leverage / liquidity / source of funds (3)
        s += int((t["dltt"] / t["at"]) < (tm1["dltt"] / tm1["at"])) if tm1["at"] else 0  # Δleverage (lower is +1)
        s += int((t["act"] / t["lct"]) > (tm1["act"] / tm1["lct"])) if tm1["lct"] else 0  # Δcurrent ratio
        s += int(t["csho"] <= tm1["csho"])  # no share issuance
        # Efficiency (2)
        gm_t = (t["sale"] - t["cogs"]) / t["sale"] if t["sale"] else 0
        gm_tm1 = (tm1["sale"] - tm1["cogs"]) / tm1["sale"] if tm1["sale"] else 0
        s += int(gm_t > gm_tm1)  # Δgross margin
        s += int((t["sale"] / t["at"]) > (tm1["sale"] / tm1["at"])) if tm1["at"] else 0  # Δasset turnover
        scores[gv] = s
    return pd.Series(scores, name="piotroski")


def roic_5y_avg(panel5: pd.DataFrame) -> pd.Series:
    return panel5.groupby("gvkey")["roic"].mean().rename("roic_5y_avg")


def fcf_growth_5y(panel5: pd.DataFrame) -> pd.Series:
    """CAGR over the 5-year window. Requires FCF_t and FCF_{t-4} both > 0 (Tier 1 guarantees)."""
    def cagr(s: pd.Series) -> float:
        s = s.sort_index()
        if len(s) < C.N_YEARS_FUNDA or s.iloc[0] <= 0 or s.iloc[-1] <= 0:
            return np.nan
        return (s.iloc[-1] / s.iloc[0]) ** (1 / (C.N_YEARS_FUNDA - 1)) - 1

    return (
        panel5.set_index("fyear")
        .groupby("gvkey")["fcf"]
        .apply(cagr)
        .rename("fcf_growth_5y")
    )


def fcf_ev_5y_avg(panel5: pd.DataFrame, ev_by_year: pd.DataFrame) -> pd.Series:
    """
    5-year mean of historical FCF_t / EV_t ratios.
    ev_by_year: long DF with columns [gvkey, fyear, ev].
    """
    merged = panel5.merge(ev_by_year, on=["gvkey", "fyear"], how="left")
    merged["fcf_ev"] = merged["fcf"] / merged["ev"].where(merged["ev"] > 0)
    return merged.groupby("gvkey")["fcf_ev"].mean().rename("fcf_ev_5y_avg")


# ---------- Composite score + final ranking ----------
def minmax(s: pd.Series) -> pd.Series:
    lo, hi = s.min(), s.max()
    if hi == lo:
        return pd.Series(0.5, index=s.index)
    return (s - lo) / (hi - lo)


def composite_score(metrics: pd.DataFrame) -> pd.Series:
    """metrics has columns: piotroski, roic_5y_avg, fcf_growth_5y (per firm)."""
    norm = pd.DataFrame({
        "piotroski": minmax(metrics["piotroski"]),
        "roic_5y_avg": minmax(metrics["roic_5y_avg"]),
        "fcf_growth_5y": minmax(metrics["fcf_growth_5y"]),
    })
    return (
        norm["piotroski"] * C.COMPOSITE_WEIGHTS["piotroski"]
        + norm["roic_5y_avg"] * C.COMPOSITE_WEIGHTS["roic_5y_avg"]
        + norm["fcf_growth_5y"] * C.COMPOSITE_WEIGHTS["fcf_growth_5y"]
    ).rename("composite")


def sleeve_of(fic: str) -> str:
    if fic in C.DM_EX_US:
        return "DM"
    if fic in C.EM:
        return "EM"
    return "OTHER"


def rank_and_select(firm_metrics: pd.DataFrame) -> pd.DataFrame:
    """
    firm_metrics must include:
      gvkey, fic, piotroski, roic_5y_avg, fcf_growth_5y, fcf_ev_5y_avg
    Returns selected portfolio with sleeve tag and rank columns.
    """
    df = firm_metrics.copy()
    df["sleeve"] = df["fic"].map(sleeve_of)
    df = df[df["sleeve"].isin(["DM", "EM"])].copy()

    selected_frames = []
    for sleeve, sub in df.groupby("sleeve"):
        sub = sub.copy()
        sub["composite"] = composite_score(
            sub.set_index("gvkey")[["piotroski", "roic_5y_avg", "fcf_growth_5y"]]
        ).reindex(sub["gvkey"]).values

        cutoff = sub["composite"].quantile(C.QUINTILE_CUT)
        top = sub[sub["composite"] >= cutoff].copy()
        top["rank_fcf_ev"] = top["fcf_ev_5y_avg"].rank(ascending=False)
        top = top.sort_values("rank_fcf_ev")
        n = C.N_DM if sleeve == "DM" else C.N_EM
        picked = top.head(n).copy()
        picked["sleeve"] = sleeve
        selected_frames.append(picked)

    out = pd.concat(selected_frames, ignore_index=True)
    out["is_sa"] = out["fic"].isin(C.SA_CODES)
    return out
