"""Analytics: aggregate charts built from the same permit data used everywhere
else -- no new backend, just different views of it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard_common import load_leads, money, page_header, empty_state


def render() -> None:
    page_header("Analytics", "Trends across every tracked permit.")

    df = load_leads()
    if df.empty:
        empty_state("📭", "No permit data yet", "Run a permit update from Settings first.")
        return

    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.markdown("#### Pipeline by Status")
            pipeline_status = (
                df.groupby("status", dropna=False)
                .agg(leads=("permit_number", "count"), reported_value=("reported_cost", "sum"))
                .reset_index()
                .sort_values("reported_value", ascending=False)
            )
            pipeline_status["reported_value"] = pipeline_status["reported_value"].fillna(0)
            st.bar_chart(pipeline_status.set_index("status")["leads"])
            display_pipeline = pipeline_status.copy()
            display_pipeline["reported_value"] = display_pipeline["reported_value"].map(money)
            display_pipeline = display_pipeline.rename(columns={"status": "Status", "leads": "Leads", "reported_value": "Reported Value"})
            st.dataframe(display_pipeline, use_container_width=True, hide_index=True)

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
