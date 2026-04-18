"""
Data access layer. Three backends, unified interface:
  - Postgres  (wrds package) → preferred for bulk pulls
  - REST      (wrds-api.wharton.upenn.edu) → fallback
  - yfinance  → prices only, gap-fill post-WRDS-lag period

Caching: every pull is written to data/cache/<name>.parquet.
Re-runs read from cache unless force_refresh=True.
"""
from __future__ import annotations
import os
from pathlib import Path
from datetime import date
from typing import Iterable

import pandas as pd
import requests

_ROOT = Path(__file__).resolve().parent.parent
CACHE = _ROOT / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

REST_BASE = "https://wrds-api.wharton.upenn.edu/data"


class WRDSClient:
    """
    Thin wrapper. `self.db` holds a wrds.Connection (Postgres) if available,
    otherwise falls back to REST via `self.token`.
    """

    def __init__(self, username: str | None = None, token: str | None = None):
        self.username = username or os.getenv("WRDS_USERNAME")
        self.token = token or os.getenv("WRDS_API_TOKEN")
        self.db = None
        self._connect_postgres()

    def _connect_postgres(self) -> None:
        try:
            import wrds
            self.db = wrds.Connection(wrds_username=self.username)
            print(f"[wrds] Postgres connected as {self.username}")
        except Exception as e:
            print(f"[wrds] Postgres unavailable ({e}); will use REST fallback")
            self.db = None

    # ---------- unified query ----------
    def sql(self, query: str, cache_name: str, force_refresh: bool = False) -> pd.DataFrame:
        """Run SQL via Postgres; cache to parquet."""
        path = CACHE / f"{cache_name}.parquet"
        if path.exists() and not force_refresh:
            print(f"[cache hit] {cache_name}")
            return pd.read_parquet(path)

        if self.db is None:
            raise RuntimeError(
                "Postgres not connected. Either fix wrds auth or use rest_get()."
            )
        print(f"[sql] {cache_name}")
        df = self.db.raw_sql(query)
        df.to_parquet(path, index=False)
        return df

    def rest_get(
        self,
        endpoint: str,
        params: dict | None = None,
        cache_name: str | None = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """GET /data/<endpoint>/ with Authorization: Token <...>."""
        if cache_name:
            path = CACHE / f"{cache_name}.parquet"
            if path.exists() and not force_refresh:
                print(f"[cache hit] {cache_name}")
                return pd.read_parquet(path)

        if not self.token:
            raise RuntimeError("WRDS_API_TOKEN missing in env")

        url = f"{REST_BASE}/{endpoint.strip('/')}/"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Token {self.token}",
        }
        rows: list[dict] = []
        next_url: str | None = url
        call_params = params
        while next_url:
            r = requests.get(next_url, headers=headers, params=call_params, timeout=60)
            r.raise_for_status()
            payload = r.json()
            if isinstance(payload, dict) and "results" in payload:
                rows.extend(payload["results"])
                next_url = payload.get("next")
                call_params = None  # next already has the params baked in
            else:
                rows.extend(payload if isinstance(payload, list) else [payload])
                next_url = None

        df = pd.DataFrame(rows)
        if cache_name:
            df.to_parquet(CACHE / f"{cache_name}.parquet", index=False)
        return df


# ---------- yfinance helpers (prices only, post-WRDS-lag gap fill) ----------
def yf_prices(tickers: Iterable[str], start: str, end: str) -> pd.DataFrame:
    """
    Daily close prices via yfinance. Returns wide DataFrame indexed by date.
    Use only when WRDS price coverage has a gap (e.g. most-recent weeks).
    """
    import yfinance as yf
    data = yf.download(
        list(tickers),
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
    )
    if isinstance(data.columns, pd.MultiIndex):
        closes = data.xs("Close", level=1, axis=1)
    else:
        closes = data[["Close"]].rename(columns={"Close": list(tickers)[0]})
    return closes


def stamp() -> str:
    """Timestamp for provenance logs."""
    return pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
