"""
Data quality checks. Every pipeline stage passes through a `stage_report`
that logs row counts, missingness, sector/country distribution, and
flags absurd values.

These are defensive: the goal is to catch silent errors (wrong units,
stale country tables, a country disappearing, etc.) before they shape
the final 20-name portfolio.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import numpy as np

from . import constants as C


@dataclass
class StageReport:
    stage: str
    n_rows: int
    n_firms: int
    countries: dict = field(default_factory=dict)
    sectors: dict = field(default_factory=dict)
    missingness: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)

    def show(self) -> None:
        print(f"\n=== {self.stage} ===")
        print(f"  rows:  {self.n_rows:,}")
        print(f"  firms: {self.n_firms:,}")
        if self.countries:
            top = sorted(self.countries.items(), key=lambda kv: -kv[1])[:8]
            print("  top countries: " + ", ".join(f"{k}={v}" for k, v in top))
        if self.sectors:
            print("  sectors: " + ", ".join(f"{k}={v}" for k, v in sorted(self.sectors.items())))
        if self.missingness:
            worst = sorted(self.missingness.items(), key=lambda kv: -kv[1])[:6]
            if any(v > 0 for _, v in worst):
                print("  missing (top): " + ", ".join(f"{k}={v:.1%}" for k, v in worst))
        if self.flags:
            for f in self.flags:
                print(f"  ⚠ {f}")


def report(
    df: pd.DataFrame,
    stage: str,
    firm_col: str = "gvkey",
    country_col: str | None = "fic",
    sector_col: str | None = "gsector",
    check_cols: list[str] | None = None,
) -> StageReport:
    rep = StageReport(
        stage=stage,
        n_rows=len(df),
        n_firms=df[firm_col].nunique() if firm_col in df.columns else 0,
    )
    if country_col and country_col in df.columns:
        rep.countries = df[country_col].value_counts().to_dict()
    if sector_col and sector_col in df.columns:
        rep.sectors = df[sector_col].astype(str).value_counts().to_dict()
    if check_cols:
        rep.missingness = {c: df[c].isna().mean() for c in check_cols if c in df.columns}

    if "roic" in df.columns:
        bad = df["roic"].dropna()
        absurd = ((bad > C.QA_MAX_ROIC) | (bad < C.QA_MIN_ROIC)).sum()
        if absurd:
            rep.flags.append(f"{absurd} rows with ROIC outside [{C.QA_MIN_ROIC}, {C.QA_MAX_ROIC}]")
    if "net_debt_ebitda" in df.columns:
        bad = df["net_debt_ebitda"].dropna()
        absurd = (bad.abs() > C.QA_MAX_LEVERAGE).sum()
        if absurd:
            rep.flags.append(f"{absurd} rows with |net_debt/EBITDA| > {C.QA_MAX_LEVERAGE}")

    rep.show()
    return rep


def check_point_in_time(
    df: pd.DataFrame,
    asof: Any,
    date_col: str = "effective_date",
) -> None:
    """Hard assert: no row is dated after the point-in-time cutoff."""
    asof_ts = pd.Timestamp(asof)
    if date_col not in df.columns:
        raise KeyError(f"{date_col} not in dataframe; cannot assert point-in-time discipline")
    latest = pd.to_datetime(df[date_col]).max()
    if latest > asof_ts:
        leaks = (pd.to_datetime(df[date_col]) > asof_ts).sum()
        raise AssertionError(
            f"POINT-IN-TIME VIOLATION: {leaks} rows with {date_col} > {asof_ts.date()} (latest={latest})"
        )
    print(f"[point-in-time OK] latest {date_col} = {latest.date()} ≤ {asof_ts.date()}")


def freshness_by_country(df: pd.DataFrame, date_col: str = "datadate") -> pd.DataFrame:
    """Newest fundamentals date per country — catches stale coverage."""
    return (
        df.groupby("fic")[date_col]
        .max()
        .sort_values()
        .to_frame("latest_datadate")
    )
