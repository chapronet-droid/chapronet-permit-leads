"""New Permits: permits issued within a recent, adjustable window."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard_common import load_leads, money, page_header, empty_state, paginate, priority_emoji_label, crm_status_emoji_label
from dashboard_pages.lead_detail import render_lead_picker_and_detail


def render() -> None:
    page_header("New Permits", "Recently issued permits, sorted with the newest first.")

    df = load_leads()
    if df.empty or "issue_date" not in df.columns:
        empty_state("📭", "No permit data yet", "Run a permit update from Settings first.")
        return

    window = st.radio(
        "Show permits issued in the last…",
        ["2 days", "7 days", "14 days", "30 days"],
        horizontal=True,
        key="np_window",
    )
    days = {"2 days": 2, "7 days": 7, "14 days": 14, "30 days": 30}[window]
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
    recent = df[df["issue_date"] >= cutoff].sort_values("issue_date", ascending=False)

    st.markdown(
        f"<div class='muted' style='margin-bottom:0.75rem;'>{len(recent):,} permits issued since {cutoff.strftime('%Y-%m-%d')}</div>",
        unsafe_allow_html=True,
    )

    if recent.empty:
        empty_state("🆕", "No new permits in this window", "Try a longer window or run a permit update.")
        return

    show_cols = [c for c in ["issue_date", "address", "permit_type", "reported_cost", "lead_score", "priority", "status"] if c in recent.columns]
    page_df, _, _ = paginate(recent, "np_page", page_size=15)
    table = page_df[show_cols].copy()
    table["issue_date"] = table["issue_date"].dt.strftime("%Y-%m-%d")
    if "reported_cost" in table:
        table["reported_cost"] = table["reported_cost"].map(money)
    if "priority" in table:
        table["priority"] = table["priority"].map(priority_emoji_label)
    if "status" in table:
        table["status"] = table["status"].map(crm_status_emoji_label)
    table = table.rename(columns={
        "issue_date": "Issue Date", "address": "Address", "permit_type": "Permit Type",
        "reported_cost": "Project Value", "lead_score": "Lead Score", "priority": "Priority", "status": "Status",
    })
    st.dataframe(table, use_container_width=True, hide_index=True, height=440)

    with st.container(border=True):
        render_lead_picker_and_detail(recent, key_prefix="new-permits")
