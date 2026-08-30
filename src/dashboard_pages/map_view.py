"""Map View: permit locations on a map with a synced side panel.

Streamlit's built-in map can't fire a "user clicked this pin" event back to
Python, so location selection is driven by a dropdown next to the map --
selecting a permit there shows its info in the side panel and is the
practical equivalent of clicking its pin.
"""

from __future__ import annotations

import streamlit as st

from dashboard_common import (
    load_leads,
    money,
    page_header,
    empty_state,
    priority_badge,
    crm_status_badge,
    render_tags_html,
    compute_lead_tags,
    switch_page,
)


def render() -> None:
    page_header("Map View", "Geographic view of tracked permits across Chicago.")

    df = load_leads()
    if df.empty or not {"latitude", "longitude"}.issubset(df.columns):
        empty_state("🗺️", "No mappable permits", "Latitude/longitude are not included in the current report.")
        return

    map_df = df.dropna(subset=["latitude", "longitude"]).copy()
    if map_df.empty:
        empty_state("🗺️", "No mappable permits", "The current permits do not include usable latitude/longitude values.")
        return

    map_col, panel_col = st.columns([2, 1])

    with panel_col:
        with st.container(border=True):
            st.markdown("#### Select a Permit")
            options = {
                f"{row.get('address', 'Unknown')} • Score {int(row.get('lead_score', 0) or 0)}": idx
                for idx, row in map_df.iterrows()
            }
            selected_label = st.selectbox("Location", list(options.keys()), key="map_select")
            row = map_df.loc[options[selected_label]]

        with st.container(border=True):
            st.markdown(f"### {row.get('address', 'Unknown address')}")
            st.markdown(
                f'{priority_badge(row.get("priority",""))} {crm_status_badge(row.get("status",""))} '
                f'<span class="badge badge-blue">Score {int(row.get("lead_score", 0) or 0)}/100</span>',
                unsafe_allow_html=True,
            )
            st.markdown(render_tags_html(compute_lead_tags(row)), unsafe_allow_html=True)
            st.write(f"**Permit:** {row.get('permit_number', '')}")
            st.write(f"**Type:** {row.get('permit_type', '')}")
            st.write(f"**Project value:** {money(row.get('reported_cost'))}")
            st.caption(str(row.get("work_description", "") or "No description published."))
            if row.get("source_url"):
                st.link_button("Open City Permit", str(row["source_url"]), use_container_width=True)
            if st.button("View full detail in Permit Search →", use_container_width=True, type="primary"):
                st.session_state["permit-search-preselect"] = str(row.get("permit_number", ""))
                switch_page("Permit Search")

    with map_col:
        with st.container(border=True):
            display_df = map_df.rename(columns={"latitude": "lat", "longitude": "lon"}).copy()
            # Highlight the selected permit distinctly from the rest of the pins.
            display_df["color"] = "#2563EB"
            display_df["size"] = 40
            display_df.loc[row.name, "color"] = "#DC2626"
            display_df.loc[row.name, "size"] = 140
            st.map(display_df[["lat", "lon", "color", "size"]], color="color", size="size")
            st.caption(f"Showing {len(map_df):,} mapped permits • the selected one is highlighted in red.")
