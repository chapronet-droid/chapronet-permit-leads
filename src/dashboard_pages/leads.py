"""Leads: permits qualified as sales opportunities, ranked by lead score."""

from __future__ import annotations

import streamlit as st

from dashboard_common import (
    load_leads, money, page_header, empty_state, paginate, priority_badge,
    render_tags_html, compute_lead_tags, lead_status_badge, ai_lead_score,
)
from dashboard_pages.lead_detail import render_lead_picker_and_detail


def render() -> None:
    page_header("Leads", "Qualified sales opportunities, ranked by ChaproNet lead score.")

    df = load_leads()
    if df.empty:
        empty_state("📭", "No permit data yet", "Run a permit update from Settings first.")
        return

    sort_col, slider_col = st.columns([1, 2])
    sort_by = sort_col.radio("Rank by", ["Base Score", "AI Lead Score"], horizontal=True, key="leads_sort_by")
    min_score = slider_col.slider("Minimum base lead score", 0, 100, 55, key="leads_min_score")
    qualified = df[df.get("lead_score", 0).fillna(0) >= min_score].copy()
    if sort_by == "AI Lead Score":
        qualified["_sort_score"] = qualified.apply(ai_lead_score, axis=1).fillna(-1)
        qualified = qualified.sort_values("_sort_score", ascending=False)
    else:
        qualified = qualified.sort_values("lead_score", ascending=False)

    k1, k2, k3 = st.columns(3)
    k1.metric("Qualified leads", f"{len(qualified):,}")
    k2.metric("Est. pipeline value", money(qualified.get("reported_cost", 0).fillna(0).sum()))
    k3.metric("Avg. lead score", f"{qualified['lead_score'].mean():.0f}" if len(qualified) else "0")

    if qualified.empty:
        empty_state("🎯", "No leads at this score threshold", "Lower the minimum lead score to see more opportunities.")
        return

    with st.container(border=True):
        page_df, _, _ = paginate(qualified, "leads_page", page_size=10)
        for _, row in page_df.iterrows():
            st.markdown(
                f"""
                <div style="padding:0.75rem 0; border-bottom:1px solid #E2E8F0;">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div style="font-weight:600; font-size:1.02rem;">{row.get('address', 'Unknown address')}</div>
                    <div>{priority_badge(row.get('priority',''))} <span class="badge badge-blue">Score {int(row.get('lead_score', 0) or 0)}/100</span> {lead_status_badge(row)}</div>
                  </div>
                  <div class="muted" style="font-size:0.85rem; margin-top:0.15rem;">
                    {row.get('permit_type', '')} • {money(row.get('reported_cost'))} • Permit {row.get('permit_number','')}
                  </div>
                  {render_tags_html(compute_lead_tags(row))}
                </div>
                """,
                unsafe_allow_html=True,
            )

    with st.container(border=True):
        render_lead_picker_and_detail(qualified, key_prefix="leads")
