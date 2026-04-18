"""
Committed screening parameters — FINN3021 Summative.
Change here, not in the notebook.
"""
from datetime import date

SCREEN_ASOF = date(2026, 3, 9)

# ISO-2 country codes — MSCI classification as of Mar 2026
DM_EX_US = {
    "GB", "JP", "CA", "AU", "DE", "FR", "CH", "NL",
    "SE", "ES", "IT", "DK", "HK", "SG", "BE", "NO",
    "FI", "IL", "IE", "AT", "PT", "NZ",
}

EM = {
    "CN", "IN", "KR", "TW", "BR", "ZA", "MX", "SA",
    "AE", "QA", "KW", "TH", "MY", "ID", "PH", "PL",
    "HU", "CZ", "GR", "TR", "CL", "PE", "CO", "EG",
}

SA_CODES = {"ZA"}  # South Africa — for satellite sleeve tagging
UNIVERSE = DM_EX_US | EM

# GICS sector codes to exclude (Compustat uses 2-digit gsector)
EXCLUDED_GSECTOR = {
    "40",  # Financials
    "60",  # Real Estate
}

# Tier 1 hard knockouts
LEVERAGE_MAX = 4.0           # net debt / EBITDA < 4x
FCF_HISTORY_YEARS = 5        # positive FCF in each of last 5 FYs

# Tier 2 quality composite weights (must sum to 1.0)
COMPOSITE_WEIGHTS = {
    "piotroski": 0.50,
    "roic_5y_avg": 0.30,
    "fcf_growth_5y": 0.20,
}

# Top-quintile cut on composite score → rank by FCF/EV within
QUINTILE_CUT = 0.80          # keep top 20% of composite (within sleeve)
RANK_WITHIN_SLEEVES = True   # DM and EM ranked separately

# Final allocation
N_DM = 15
N_EM = 5
N_SA_MIN = 1                 # at least 1 SA name if screen allows

# Point-in-time discipline
# Compustat Global annual filings lag fiscal year-end.
# We only admit a firm-year if the assumed filing date ≤ SCREEN_ASOF.
# This is the conservative proxy when rdq is missing on g_funda.
ASSUMED_FILING_LAG_MONTHS = 4

# Fundamentals window — latest FY + 4 prior = 5-year history
N_YEARS_FUNDA = 5

# Data QA thresholds
QA_MAX_ROIC = 3.0            # flag ROIC > 300%
QA_MIN_ROIC = -3.0
QA_MAX_LEVERAGE = 50.0       # debug absurd leverage values
