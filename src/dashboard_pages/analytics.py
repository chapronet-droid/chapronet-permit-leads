"""Analytics: aggregate charts built from the same permit data used everywhere
else -- no new backend, just different views of it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard_common import load_leads, money, page_header, empty_state, LEAD_STAGES


def render() -> None:
    page_header("Analytics", "Trends across every tracked permit.")

    df = load_leads()
    if df.empty:
        empty_state("📭", "No permit data yet", "Run a permit update from Settings first.")
        return

    with st.container(border=True):
        st.markdown("#### CRM Pipeline")
        st.caption("Every lead, grouped by stage in funnel order -- not sorted by value, so it reads left-to-right as the actual pipeline.")
        counts = df["status"].value_counts()
        values = df.groupby("status")["reported_cost"].sum().fillna(0)
        ordered_stages = [s for s in LEAD_STAGES if s in counts.index] + [
            s for s in counts.index if s not in LEAD_STAGES
        ]
        funnel = pd.DataFrame(
            {"Leads": [int(counts.get(s, 0)) for s in ordered_stages]},
            index=ordered_stages,
        )
        st.bar_chart(funnel)
        table = pd.DataFrame({
            "Stage": ordered_stages,
            "Leads": [int(counts.get(s, 0)) for s in ordered_stages],
            "Reported Value": [money(values.get(s, 0)) for s in ordered_stages],
        })
        st.dataframe(table, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.markdown("#### Priority Distribution")
            if "priority" in df.columns:
                st.bar_chart(df["priority"].value_counts())

    with col2:
        with st.container(border=True):
            st.markdown("#### Project Value by Permit Type")
            if "permit_type" in df.columns:
                by_type = (
                    df.groupby("permit_type")["reported_cost"].sum().fillna(0).sort_values(ascending=False).head(10)
                )
                st.bar_chart(by_type)

        with st.container(border=True):
            st.markdown("#### Permits Issued Over Time")
            if "issue_date" in df.columns:
                by_week = (
                    df.dropna(subset=["issue_date"])
                    .set_index("issue_date")
                    .resample("W")["permit_number"]
                    .count()
                )
                st.line_chart(by_week)
