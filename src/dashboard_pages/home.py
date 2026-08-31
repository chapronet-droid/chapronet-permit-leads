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
    ai_lead_score,
    clean_text,
    switch_page,
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

    st.markdown("#### AI Outreach Pipeline")
    ai_scores = df.apply(ai_lead_score, axis=1)
    status = df.get("status", pd.Series(dtype=str)).fillna("")
    follow_up_due = 0
    if "next_follow_up" in df.columns:
        follow_up_dates = pd.to_datetime(df["next_follow_up"], errors="coerce")
        follow_up_due = int((follow_up_dates.notna() & (follow_up_dates <= today)).sum())
    emails_sent = int((df.get("outreach_email_status", pd.Series(dtype=str)).fillna("") == "sent").sum())

    st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
    ocols = st.columns(8)
    kpi_card(ocols[0], "🆕", "New Leads", f"{int((status == 'New Lead').sum()):,}", "blue")
    kpi_card(ocols[1], "🔥", "High-Priority Leads", f"{int((ai_scores >= 80).sum()):,}", "red")
    kpi_card(ocols[2], "🟢", "Good Leads", f"{int(((ai_scores >= 60) & (ai_scores < 80)).sum()):,}", "green")
    kpi_card(ocols[3], "✉️", "Emails Sent", f"{emails_sent:,}", "blue")
    kpi_card(ocols[4], "⏰", "Follow-Ups Due", f"{follow_up_due:,}", "amber")
    kpi_card(ocols[5], "📅", "Meetings Scheduled", f"{int((status == 'Meeting Scheduled').sum()):,}", "blue")
    kpi_card(ocols[6], "📋", "Estimates Requested", f"{int((status == 'Estimate Requested').sum()):,}", "amber")
    kpi_card(ocols[7], "🏆", "Won Leads", f"{int((status == 'Won').sum()):,}", "green")
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption(
        "\"Emails Sent\" counts emails you've confirmed sending (via \"I sent this email\" after "
        "opening in your mail client). \"High-Priority\"/\"Good Leads\" only count permits that "
        "have been AI-analyzed; see Settings to batch-analyze the rest."
    )

    if "next_follow_up" in df.columns:
        follow_up_dates = pd.to_datetime(df["next_follow_up"], errors="coerce")
        due = df[follow_up_dates.notna() & (follow_up_dates <= today)].copy()
        due["_follow_up_date"] = follow_up_dates[due.index]
        due = due.sort_values("_follow_up_date")
        if not due.empty:
            with st.container(border=True):
                st.markdown("#### ⏰ Follow-Ups Due")
                for _, row in due.head(10).iterrows():
                    overdue_days = (today - row["_follow_up_date"]).days
                    when = "Due today" if overdue_days == 0 else f"{overdue_days} day{'s' if overdue_days != 1 else ''} overdue"
                    contact = clean_text(row.get("contact_name", "")) or clean_text(row.get("company", "")) or "No contact name on file"
                    fcol1, fcol2 = st.columns([5, 1])
                    fcol1.markdown(
                        f"**{row.get('address', 'Unknown address')}** — {contact}  \n"
                        f"<span class='muted' style='font-size:0.85rem;'>{when} • {clean_text(row.get('status',''))}</span>",
                        unsafe_allow_html=True,
                    )
                    if fcol2.button("Open →", key=f"followup-{row.get('permit_number','')}", use_container_width=True):
                        st.session_state["permit-search-preselect"] = str(row.get("permit_number", ""))
                        switch_page("Permit Search")
                if len(due) > 10:
                    st.caption(f"+ {len(due) - 10} more due -- see Saved Permits for the full list.")

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
