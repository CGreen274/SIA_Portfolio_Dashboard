"""
FINN3021 — Evaluation Period Dashboard
=======================================
Fixed period: 9 March 2026 → 20 April 2026
Run:   python dashboard/eval_app.py
Open:  http://127.0.0.1:8051
"""

import os
import sys
import pathlib
from datetime import date

# Ensure project root is importable
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, html, dcc

# Import shared logic from the main dashboard
from dashboard.app import (
    compute_all,
    build_dashboard_content,
    build_layout as _main_build_layout,
    kpi_card,
    INCEPTION,
    BENCHMARK,
    CHART_CONFIG,
)

# ── Evaluation period dates ───────────────────────────────────────
EVAL_START = date(2026, 3, 9)
EVAL_END = date(2026, 4, 20)

# ── Dash app (separate instance, different port) ─────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY],
    title="FINN3021 — Evaluation Period Report",
    suppress_callback_exceptions=True,
)
server = app.server


def build_layout():
    return dbc.Container([
        # Header
        dbc.Row(dbc.Col(html.Div([
            html.H2("FINN3021 — Evaluation Period Report",
                     className="mb-0", style={"fontWeight": "800"}),
            html.P(
                f"Fixed window: {EVAL_START.strftime('%d %B %Y')} → "
                f"{EVAL_END.strftime('%d %B %Y')}  ·  "
                f"100% equity (conviction-weighted)  ·  Benchmark: {BENCHMARK}",
                className="text-muted mb-0", style={"fontSize": "0.85rem"}),
        ]), width=12), className="my-3"),

        # Refresh button
        dbc.Row([
            dbc.Col(dbc.Button("↻  Refresh data", id="eval-refresh-btn",
                               color="info", size="sm", className="me-2"),
                    width="auto"),
            dbc.Col(html.Span(id="eval-last-update", className="text-muted",
                              style={"fontSize": "0.8rem"}), width="auto"),
        ], className="mb-3", align="center"),

        html.Div(id="eval-dashboard-content"),

        html.Hr(),
        html.P(
            f"Evaluation period: {EVAL_START} → {EVAL_END}  ·  "
            "Data: yfinance · Not investment advice",
            className="text-muted text-center", style={"fontSize": "0.7rem"}),
    ], fluid=True, style={"backgroundColor": "white", "minHeight": "100vh",
                           "padding": "20px 30px"})


app.layout = build_layout


@callback(
    Output("eval-dashboard-content", "children"),
    Output("eval-last-update", "children"),
    Input("eval-refresh-btn", "n_clicks"),
)
def refresh_eval(_):
    """Compute metrics for the fixed evaluation window and render."""
    d = compute_all(end_date=EVAL_END)
    content, last_date = build_dashboard_content(d)
    return content, f"Showing {EVAL_START} → {EVAL_END}  ·  Computed: {last_date}"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8051))
    app.run(debug=False, host="0.0.0.0", port=port)
