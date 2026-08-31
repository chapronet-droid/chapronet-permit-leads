"""ChaproNet Experience: a hand-maintained record of real past projects.

This is the "Never invent experience" database from the outreach spec --
every record here is entered by ChaproNet staff. The AI never writes to
this table; it only reads from it (via dashboard_common.match_experience)
to decide whether a specific past project is relevant enough to reference
in an outreach email.
"""

from __future__ import annotations

import streamlit as st

from dashboard_common import (
    page_header,
    empty_state,
    load_experience,
    save_experience_record,
    delete_experience_record,
    clean_text,
    CHAPRONET_SERVICES,
)


def render() -> None:
    page_header(
        "Experience",
        "Real past ChaproNet projects. Outreach emails only ever reference what's recorded here -- nothing is invented.",
    )

    records = load_experience()

    edit_options = {"➕ Add a new project": None}
    for _, row in records.iterrows():
        label = f"✏️ Edit #{int(row['id'])} — {clean_text(row.get('building_type','')) or 'Untitled'} ({clean_text(row.get('project_type','')) or 'no type'})"
        edit_options[label] = int(row["id"])

    with st.container(border=True):
        chosen_label = st.selectbox("Add a new record, or edit an existing one", list(edit_options.keys()), key="exp_mode")
        editing_id = edit_options[chosen_label]
        editing_row = records[records["id"] == editing_id].iloc[0] if editing_id is not None else None

        def _val(field: str, default: str = "") -> str:
            return clean_text(editing_row.get(field, default)) if editing_row is not None else default

        with st.form("experience_form", clear_on_submit=(editing_id is None)):
            c1, c2 = st.columns(2)
            project_type = c1.text_input("Project Type", value=_val("project_type"), placeholder="e.g. Renovation, New Construction, Tenant Buildout")
            building_type = c2.text_input("Building Type", value=_val("building_type"), placeholder="e.g. Multifamily/Apartment, Office, Restaurant, Retail")

            default_services = [s for s in _val("services_performed").split(",") if s.strip()] if editing_row is not None else []
            services_performed = st.multiselect("Services Performed", CHAPRONET_SERVICES, default=default_services)

            c3, c4, c5 = st.columns(3)
            num_cameras = c3.text_input("Number of Cameras", value=_val("num_cameras"), placeholder="e.g. 24")
            num_doors = c4.text_input("Number of Doors", value=_val("num_doors"), placeholder="e.g. 8")
            num_data_drops = c5.text_input("Number of Data Drops", value=_val("num_data_drops"), placeholder="e.g. 120")

            networking_scope = st.text_area("Networking Scope", value=_val("networking_scope"), placeholder="e.g. Full building Cat6 backbone, core switch, 3 wiring closets", height=80)
            av_scope = st.text_area("AV Scope", value=_val("av_scope"), placeholder="e.g. Conference room displays and ceiling speakers in 4 rooms", height=80)
            approx_project_size = st.text_input("Approximate Project Size", value=_val("approx_project_size"), placeholder="e.g. 60 units, or 40,000 sqft")
            description = st.text_area("Short Project Description", value=_val("description"), placeholder="A couple of sentences describing the actual work performed.", height=100)

            submit_label = "💾 Update Record" if editing_id is not None else "💾 Save Experience Record"
            submitted = st.form_submit_button(submit_label, type="primary", use_container_width=True)

        if submitted:
            if not building_type.strip() and not project_type.strip():
                st.error("Enter at least a Project Type or Building Type so this record can be matched later.")
            else:
                save_experience_record(
                    {
                        "project_type": project_type,
                        "building_type": building_type,
                        "services_performed": ", ".join(services_performed),
                        "num_cameras": num_cameras,
                        "num_doors": num_doors,
                        "num_data_drops": num_data_drops,
                        "networking_scope": networking_scope,
                        "av_scope": av_scope,
                        "approx_project_size": approx_project_size,
                        "description": description,
                    },
                    record_id=editing_id,
                )
                st.success("Experience record updated." if editing_id is not None else "Experience record saved.")
                st.rerun()

    st.markdown("#### Recorded Projects")
    if records.empty:
        empty_state(
            "🗂️",
            "No past projects recorded yet",
            "Add ChaproNet's real project history above so outreach emails can reference it.",
        )
        return

    for _, row in records.iterrows():
        with st.container(border=True):
            title = clean_text(row.get("building_type", "")) or "Untitled project"
            subtitle = clean_text(row.get("project_type", ""))
            head_col, del_col = st.columns([5, 1])
            head_col.markdown(f"**{title}**" + (f" — {subtitle}" if subtitle else ""))
            if del_col.button("🗑️ Delete", key=f"delete-exp-{row['id']}", use_container_width=True):
                delete_experience_record(int(row["id"]))
                st.rerun()

            services = clean_text(row.get("services_performed", ""))
            if services:
                st.markdown(
                    "".join(f'<span class="badge badge-blue">{s.strip()}</span> ' for s in services.split(",") if s.strip()),
                    unsafe_allow_html=True,
                )
            meta = []
            for label, field in [
                ("Cameras", "num_cameras"), ("Doors", "num_doors"), ("Data drops", "num_data_drops"),
                ("Size", "approx_project_size"),
            ]:
                value = clean_text(row.get(field, ""))
                if value:
                    meta.append(f"{label}: {value}")
            if meta:
                st.caption(" • ".join(meta))
            if clean_text(row.get("networking_scope", "")):
                st.write(f"**Networking:** {clean_text(row.get('networking_scope',''))}")
            if clean_text(row.get("av_scope", "")):
                st.write(f"**AV:** {clean_text(row.get('av_scope',''))}")
            description = clean_text(row.get("description", ""))
            if description:
                st.info(description)
