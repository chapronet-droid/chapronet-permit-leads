"""Permit Search: the full filter panel + sortable, paginated results table."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard_common import (
    load_leads,
    money,
    clean_text,
    page_header,
    empty_state,
    paginate,
    load_saved_searches,
    save_search,
    delete_saved_search,
    priority_emoji_label,
    permit_status_emoji_label,
    crm_status_emoji_label,
)
from dashboard_pages.lead_detail import render_lead_picker_and_detail

DEFAULTS = {
    "ps_address": "",
    "ps_zip": "",
    "ps_neighborhood": [],
    "ps_permit_type": [],
    "ps_contractor": "",
    "ps_owner": "",
    "ps_date_from": None,
    "ps_date_to": None,
    "ps_cost_min": 0,
    "ps_cost_max": 0,
    "ps_permit_status": [],
}


def _reset_filters() -> None:
    for key in DEFAULTS:
        st.session_state.pop(key, None)
    st.session_state.pop("permit_search_criteria", None)


def _apply_criteria(df: pd.DataFrame, criteria: dict) -> pd.DataFrame:
    out = df.copy()
    if criteria.get("address"):
        out = out[out["address"].astype(str).str.contains(criteria["address"], case=False, na=False)]
    if criteria.get("zip") and "zip_code" in out.columns:
        out = out[out["zip_code"].astype(str).str.contains(criteria["zip"], case=False, na=False)]
    if criteria.get("neighborhood") and "community_area" in out.columns:
        out = out[out["community_area"].astype(str).isin(criteria["neighborhood"])]
    if criteria.get("permit_type") and "permit_type" in out.columns:
        out = out[out["permit_type"].isin(criteria["permit_type"])]
    if criteria.get("contractor") and "permit_contacts" in out.columns:
        needle = criteria["contractor"]
        out = out[out["permit_contacts"].astype(str).str.contains(needle, case=False, na=False)]
    if criteria.get("owner") and "permit_contacts" in out.columns:
        needle = criteria["owner"]
        out = out[out["permit_contacts"].astype(str).str.contains(needle, case=False, na=False)]
    if criteria.get("date_from") and "issue_date" in out.columns:
        out = out[out["issue_date"] >= pd.Timestamp(criteria["date_from"])]
    if criteria.get("date_to") and "issue_date" in out.columns:
        out = out[out["issue_date"] <= pd.Timestamp(criteria["date_to"])]
    if criteria.get("cost_min") and "reported_cost" in out.columns:
        out = out[out["reported_cost"].fillna(0) >= criteria["cost_min"]]
    if criteria.get("cost_max") and "reported_cost" in out.columns:
        out = out[out["reported_cost"].fillna(0) <= criteria["cost_max"]]
    if criteria.get("permit_status") and "permit_status" in out.columns:
        out = out[out["permit_status"].isin(criteria["permit_status"])]
    return out


def render() -> None:
    page_header("Permit Search", "Filter every tracked Chicago permit by address, contractor, cost, status, and more.")

    df = load_leads()
    if df.empty:
        empty_state("📭", "No permit data yet", "Run a permit update from Settings first.")
        return

    saved = load_saved_searches()
    if saved:
        with st.container(border=True):
            load_col, del_col = st.columns([3, 1])
            chosen = load_col.selectbox("Load a saved search", ["—"] + list(saved.keys()), key="ps_load_saved")
            if chosen != "—":
                if load_col.button("Apply saved search", key="ps_apply_saved"):
                    criteria = saved[chosen]
                    st.session_state["permit_search_criteria"] = criteria
                    st.rerun()
                if del_col.button("Delete", key="ps_delete_saved", use_container_width=True):
                    delete_saved_search(chosen)
                    st.rerun()

    with st.container(border=True):
        with st.form("permit_search_filters"):
            r1c1, r1c2, r1c3 = st.columns(3)
            address = r1c1.text_input("Address", key="ps_address")
            zip_code = r1c2.text_input("ZIP Code", key="ps_zip")
            neighborhood_options = sorted(df["community_area"].dropna().astype(str).unique().tolist()) if "community_area" in df else []
            neighborhood = r1c3.multiselect("Neighborhood (Community Area)", neighborhood_options, key="ps_neighborhood")

            r2c1, r2c2, r2c3 = st.columns(3)
            permit_type_options = sorted(df["permit_type"].dropna().astype(str).unique().tolist()) if "permit_type" in df else []
            permit_type = r2c1.multiselect("Permit Type", permit_type_options, key="ps_permit_type")
            contractor = r2c2.text_input("Contractor", key="ps_contractor", placeholder="Search contractor name")
            owner = r2c3.text_input("Owner", key="ps_owner", placeholder="Search owner name")

            r3c1, r3c2, r3c3, r3c4 = st.columns(4)
            date_from = r3c1.date_input("Date Issued From", value=None, key="ps_date_from")
            date_to = r3c2.date_input("Date Issued To", value=None, key="ps_date_to")
            cost_min = r3c3.number_input("Min Project Cost ($)", min_value=0, step=10_000, key="ps_cost_min")
            cost_max = r3c4.number_input("Max Project Cost ($) — 0 = no limit", min_value=0, step=10_000, key="ps_cost_max")

            status_options = sorted(df["permit_status"].dropna().astype(str).unique().tolist()) if "permit_status" in df else []
            permit_status = st.multiselect("Permit Status", status_options, key="ps_permit_status")

            submitted = st.form_submit_button("🔍 Search", type="primary", use_container_width=False)

        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])
        if btn_col1.button("Reset Filters", use_container_width=True):
            _reset_filters()
            st.rerun()
        save_name = btn_col3.text_input("Save current search as", key="ps_save_name", label_visibility="collapsed", placeholder="Name this search…")
        if btn_col2.button("💾 Save Search", use_container_width=True, disabled=not save_name.strip()):
            save_search(save_name.strip(), st.session_state.get("permit_search_criteria", {}))
            st.success(f"Saved search '{save_name.strip()}'.")
            st.rerun()

    if submitted:
        st.session_state["permit_search_criteria"] = {
            "address": address,
            "zip": zip_code,
            "neighborhood": neighborhood,
            "permit_type": permit_type,
            "contractor": contractor,
            "owner": owner,
            "date_from": date_from,
            "date_to": date_to,
            "cost_min": cost_min,
            "cost_max": cost_max,
            "permit_status": permit_status,
        }

    criteria = st.session_state.get("permit_search_criteria", {})
    filtered = _apply_criteria(df, criteria) if criteria else df

    st.markdown(f"#### Results <span class='muted' style='font-weight:400;'>({len(filtered):,} permits)</span>", unsafe_allow_html=True)

    if filtered.empty:
        empty_state("🔍", "No permits match these filters", "Try widening your search or click Reset Filters.")
        return

    show_cols = [
        c for c in [
            "permit_number", "address", "permit_type", "work_description",
            "issue_date", "reported_cost", "company", "permit_status", "priority", "status",
        ] if c in filtered.columns
    ]
    table_source = filtered.sort_values("lead_score", ascending=False)
    page_df, page, total_pages = paginate(table_source, "ps_page", page_size=15)

    table = page_df[show_cols].copy()
    if "issue_date" in table:
        table["issue_date"] = table["issue_date"].dt.strftime("%Y-%m-%d")
    if "reported_cost" in table:
        table["reported_cost"] = table["reported_cost"].map(money)
    if "priority" in table:
        table["priority"] = table["priority"].map(priority_emoji_label)
    if "permit_status" in table:
        table["permit_status"] = table["permit_status"].map(permit_status_emoji_label)
    if "status" in table:
        table["status"] = table["status"].map(crm_status_emoji_label)
    table = table.rename(columns={
        "permit_number": "Permit Number", "address": "Address", "permit_type": "Permit Type",
        "work_description": "Description", "issue_date": "Issue Date", "reported_cost": "Project Value",
        "company": "Contractor", "permit_status": "Permit Status", "priority": "Priority", "status": "Status",
    })

    st.dataframe(table, use_container_width=True, hide_index=True, height=460)

    with st.container(border=True):
        render_lead_picker_and_detail(table_source, key_prefix="permit-search")
