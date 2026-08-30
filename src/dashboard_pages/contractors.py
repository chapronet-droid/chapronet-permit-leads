"""Contractors: companies aggregated from permit contact fields, cross-
referenced with any cached Company Research profile.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from dashboard_common import (
    load_leads,
    money,
    page_header,
    empty_state,
    build_contractor_rows,
    paginate,
    STATE_DIR,
)


def _cached_research_lookup() -> dict[str, dict]:
    db_path = STATE_DIR / "company_research.db"
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT company_name, result_json FROM company_research").fetchall()
        conn.close()
    except Exception:
        return {}
    import json
    lookup = {}
    for name, result_json in rows:
        try:
            lookup[str(name).strip().lower()] = json.loads(result_json)
        except Exception:
            continue
    return lookup


def render() -> None:
    page_header("Contractors", "Owners, contractors, and architects seen across tracked permits.")

    df = load_leads()
    if df.empty:
        empty_state("📭", "No permit data yet", "Run a permit update from Settings first.")
        return

    exploded = build_contractor_rows(df)
    if exploded.empty:
        empty_state("👷", "No contractor data found", "Permit contact fields didn't contain any labeled company names.")
        return

    role_filter = st.multiselect(
        "Role", sorted(exploded["role"].unique().tolist()), default=sorted(exploded["role"].unique().tolist())
    )
    exploded = exploded[exploded["role"].isin(role_filter)] if role_filter else exploded

    grouped = (
        exploded.groupby("company_name")
        .agg(
            permits=("permit_number", "nunique"),
            total_value=("reported_cost", "sum"),
            max_score=("lead_score", "max"),
            roles=("role", lambda s: ", ".join(sorted(set(s)))),
        )
        .reset_index()
        .sort_values("total_value", ascending=False)
    )

    research_lookup = _cached_research_lookup()

    def _lookup_field(name: str, field: str) -> str:
        profile = research_lookup.get(str(name).strip().lower())
        return profile.get(field, "") if profile else ""

    grouped["industry"] = grouped["company_name"].map(lambda n: _lookup_field(n, "industry"))
    grouped["phone"] = grouped["company_name"].map(lambda n: _lookup_field(n, "phone"))

    k1, k2, k3 = st.columns(3)
    k1.metric("Unique companies", f"{len(grouped):,}")
    k2.metric("With researched profile", f"{int((grouped['industry'] != '').sum()):,}")
    k3.metric("Total tracked value", money(grouped["total_value"].sum()))

    page_df, _, _ = paginate(grouped, "contractors_page", page_size=20)
    display = page_df.copy()
    display["total_value"] = display["total_value"].map(money)
    display = display.rename(columns={
        "company_name": "Company", "permits": "Permits", "total_value": "Total Value",
        "max_score": "Top Lead Score", "roles": "Roles Seen", "industry": "Industry (researched)",
        "phone": "Public Phone (researched)",
    })
    st.dataframe(display, use_container_width=True, hide_index=True, height=460)
    st.caption("Industry and phone are populated only for companies already looked up in Company Research (on any permit's detail page).")
