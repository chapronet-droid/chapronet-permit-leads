"""Saved Permits: permits the team has actually started working -- anything
with sales-tracking data recorded (status change, notes, assignment, or
contact info) in the local lead_tracking database.
"""

from __future__ import annotations

import streamlit as st

from dashboard_common import load_leads, money, page_header, empty_state, paginate, crm_status_emoji_label, clean_text
from dashboard_pages.lead_detail import render_lead_picker_and_detail


def render() -> None:
    page_header("Saved Permits", "Permits your team has reviewed, assigned, or added notes to -- doubles as your contact list once names/phone/email are filled in.")

    df = load_leads()
    if df.empty:
        empty_state("📭", "No permit data yet", "Run a permit update from Settings first.")
        return

    def _has_activity(row) -> bool:
        if (clean_text(row.get("status", "New Lead")) or "New Lead") not in ("New Lead", "New"):
            return True
        for field in [
            "assigned_to", "notes", "company", "phone", "email",
            "contact_name", "outreach_email_body",
        ]:
            if clean_text(row.get(field, "")):
                return True
        return False

    saved = df[df.apply(_has_activity, axis=1)].sort_values("issue_date", ascending=False)

    if saved.empty:
        empty_state(
            "⭐",
            "No saved permits yet",
            "Update a permit's status, notes, or contact info from Permit Search or Leads to save it here.",
        )
        return

    show_cols = [
        c for c in [
            "address", "status", "contact_name", "best_contact_type", "phone", "email",
            "assigned_to", "last_contact_date", "next_follow_up", "reported_cost",
        ] if c in saved.columns
    ]
    page_df, _, _ = paginate(saved, "sp_page", page_size=15)
    table = page_df[show_cols].copy()
    for col in ["contact_name", "best_contact_type", "phone", "email"]:
        if col in table:
            table[col] = table[col].apply(clean_text).replace("", "Not found")
    if "reported_cost" in table:
        table["reported_cost"] = table["reported_cost"].map(money)
    if "status" in table:
        table["status"] = table["status"].map(crm_status_emoji_label)
    table = table.rename(columns={
        "address": "Address", "status": "Status", "contact_name": "Contact Name",
        "best_contact_type": "Contact Type", "phone": "Phone", "email": "Email",
        "assigned_to": "Assigned To", "last_contact_date": "Last Contact",
        "next_follow_up": "Next Follow-Up", "reported_cost": "Project Value",
    })
    st.dataframe(table, use_container_width=True, hide_index=True, height=420)

    with st.container(border=True):
        render_lead_picker_and_detail(saved, key_prefix="saved-permits")
