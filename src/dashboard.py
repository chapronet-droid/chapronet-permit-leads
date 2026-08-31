"""ChaproNet Lead Intelligence -- multipage app entrypoint.

This file only wires up page navigation and global styling. Every page's
actual logic lives in dashboard_pages/*.py, and all shared data-access /
formatting / styling helpers live in dashboard_common.py.
"""

from __future__ import annotations

import streamlit as st

from dashboard_common import inject_global_css, render_sidebar_brand, register_pages
from dashboard_pages import (
    home,
    permit_search,
    new_permits,
    map_view,
    leads,
    saved_permits,
    contractors,
    analytics,
    experience,
    settings,
)

st.set_page_config(
    page_title="ChaproNet Lead Intelligence",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_global_css()

pages = {
    "Dashboard": st.Page(home.render, title="Dashboard", icon="🏠", url_path="dashboard", default=True),
    "Permit Search": st.Page(permit_search.render, title="Permit Search", icon="🔍", url_path="permit-search"),
    "New Permits": st.Page(new_permits.render, title="New Permits", icon="🆕", url_path="new-permits"),
    "Map View": st.Page(map_view.render, title="Map View", icon="🗺️", url_path="map-view"),
    "Leads": st.Page(leads.render, title="Leads", icon="🎯", url_path="leads"),
    "Saved Permits": st.Page(saved_permits.render, title="Saved Permits", icon="⭐", url_path="saved-permits"),
    "Contractors": st.Page(contractors.render, title="Contractors", icon="👷", url_path="contractors"),
    "Analytics": st.Page(analytics.render, title="Analytics", icon="📊", url_path="analytics"),
    "Experience": st.Page(experience.render, title="Experience", icon="🗂️", url_path="experience"),
    "Settings": st.Page(settings.render, title="Settings", icon="⚙️", url_path="settings"),
}
register_pages(pages)

with st.sidebar:
    render_sidebar_brand()

current_page = st.navigation(list(pages.values()))
current_page.run()
