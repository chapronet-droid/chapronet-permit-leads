"""Dashboard: top-level KPI summary and a quick look at the hottest leads."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard_common import (
    load_leads,
    money,
    page_header,
    kpi_card,
    empty_state,
    priority_badge,
    render_tags_html,
    compute_lead_tags,
)


def render() -> None:
    page_header("Dashboard", "A live snapshot of every Chicago permit ChaproNet is tracking.")

    df = load_leads()
    if df.empty:
        empty_state(
            "📭",
            "No permit data yet",
            "Run a permit update from Settings to pull the latest Chicago permits.",
        )
        return

    today = pd.Timestamp.now().normalize()
    week_cutoff = today - pd.Timedelta(days=7)

    total_permits = len(df)
    new_today = int((df["issue_date"].dt.normalize() == today).sum()) if "issue_date" in df else 0
    new_this_week = int((df["issue_date"] >= week_cutoff).sum()) if "issue_date" in df else 0
    est_value = float(df.get("reported_cost", pd.Series(dtype=float)).fillna(0).sum())
    high_value = int((df.get("reported_cost", pd.Series(dtype=float)).fillna(0) >= 500_000).sum())
    potential_leads = int((df.get("lead_score", pd.Series(dtype=float)).fillna(0) >= 35).sum())

    st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
    cols = st.columns(6)
    kpi_card(cols[0], "📄", "Total Permits", f"{total_permits:,}", "blue")
    kpi_card(cols[1], "🆕", "New Permits Today", f"{new_today:,}", "green")
    kpi_card(cols[2], "📅", "New This Week", f"{new_this_week:,}", "blue")
    kpi_card(cols[3], "💰", "Est. Project Value", money(est_value), "green")
    kpi_card(cols[4], "⭐", "High-Value Projects", f"{high_value:,}", "amber")
    kpi_card(cols[5], "🎯", "Potential Leads", f"{potential_leads:,}", "red")
    st.markdown("</div>", unsafe_allow_html=True)

    left, right = st.columns([1.6, 1])
    with left:
        with st.container(border=True):
            st.markdown("#### 🔥 Hottest Leads Right Now")
            top = df.sort_values("lead_score", ascending=False).head(8)
            if top.empty:
                st.caption("No scored leads yet.")
            for _, row in top.iterrows():
                cost = money(row.get("reported_cost"))
                st.markdown(
                    f"""
                    <div style="padding:0.6rem 0; border-bottom:1px solid #E2E8F0;">
                      <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div style="font-weight:600;">{row.get('address', 'Unknown address')}</div>
                        <div>{priority_badge(row.get('priority', ''))}</div>
                      </div>
                      <div class="muted" style="font-size:0.85rem;">
                        {row.get('permit_type', '')} • {cost} • Score {int(row.get('lead_score', 0) or 0)}/100
                      </div>
                      {render_tags_html(compute_lead_tags(row))}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with right:
        with st.container(border=True):
            st.markdown("#### Pipeline by Status")
            if "status" in df.columns:
                counts = df["status"].value_counts()
                st.bar_chart(counts)

        with st.container(border=True):
            st.markdown("#### Priority Mix")
            if "priority" in df.columns:
                priority_counts = df["priority"].value_counts()
                for label in ["Immediate", "Hot", "Warm", "Research"]:
                    if label in priority_counts.index:
                        st.markdown(
                            f"{priority_badge(label)} &nbsp; {priority_counts[label]} permits",
                            unsafe_allow_html=True,
                        )
