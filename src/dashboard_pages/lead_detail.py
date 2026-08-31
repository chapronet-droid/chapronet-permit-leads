"""Shared permit detail panel: AI Intelligence, Company Research, Sales
Tracking, Jobber Actions, Confluence Actions.

This is the same logic that used to live inline in dashboard.py's "Lead
Details" section -- unchanged behavior, restyled into cards, and reused by
every page that lets a user drill into one permit (Permit Search, Leads,
Saved Permits, New Permits).
"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import streamlit as st

from jobber_integration import JobberClient, JobberError
from confluence_integration import ConfluenceClient, ConfluenceError
from ai_intelligence import AIIntelligenceClient, AIIntelligenceError
from company_research import (
    CompanyResearchClient,
    CompanyResearchError,
    extract_company_candidates,
)
from outreach import OutreachClient, OutreachError

from dashboard_common import (
    PROJECT_ROOT,
    clean_text,
    money,
    save_tracking,
    confluence_page_id_from_url,
    priority_badge,
    crm_status_badge,
    compute_lead_tags,
    render_tags_html,
    lead_status_badge,
    ai_lead_score,
    match_experience,
    build_mailto_link,
    LEAD_STAGES,
)

CONTACT_TYPES = ["Owner", "General Contractor", "Developer", "Property Manager", "Other"]


def render_lead_detail_panel(row: pd.Series, permit_no: str) -> None:
    left, right = st.columns([1.3, 1])

    with left:
        with st.container(border=True):
            st.markdown(f"### {row.get('address', 'Unknown address')}")
            badges = (
                f'<span class="badge badge-blue">Base Score {int(row.get("lead_score", 0) or 0)}/100</span> '
                f'{priority_badge(row.get("priority", ""))} '
                f'{lead_status_badge(row)} '
                f'{crm_status_badge(row.get("status", ""))}'
            )
            st.markdown(badges, unsafe_allow_html=True)
            st.markdown(render_tags_html(compute_lead_tags(row)), unsafe_allow_html=True)
            st.write("")
            st.write(f"**Permit:** {permit_no}")
            st.write(f"**Type:** {row.get('permit_type', '')}")
            st.write(f"**Reported project cost:** {money(row.get('reported_cost'))}")
            st.write(f"**Recommended services:** {row.get('recommended_services', '')}")
            st.write(f"**Permit contacts:** {row.get('permit_contacts', '') or 'Not published'}")
            st.write("**Work description**")
            st.info(str(row.get("work_description", "") or "No description published."))

            links = st.columns(4)
            link_data = [
                ("City Permit", row.get("source_url", "")),
                ("Google Maps", row.get("google_maps_url", "")),
                ("Owner Research", row.get("owner_research_url", "")),
                ("GC Research", row.get("gc_research_url", "")),
            ]
            for col, (label, url) in zip(links, link_data):
                if url:
                    col.link_button(label, str(url), use_container_width=True)

        with st.container(border=True):
            st.markdown("#### 🤖 AI Opportunity Intelligence")
            stored_ai = clean_text(row.get("ai_analysis_json", ""))
            ai_result = None
            if stored_ai:
                try:
                    ai_result = json.loads(stored_ai)
                except Exception:
                    ai_result = None

            if ai_result:
                ai1, ai2, ai3 = st.columns(3)
                ai1.metric("AI opportunity score", f"{ai_result.get('opportunity_score', 0)}/100")
                ai2.metric(
                    "Estimated ChaproNet revenue",
                    f"${int(ai_result.get('estimated_revenue_low', 0)):,}–${int(ai_result.get('estimated_revenue_high', 0)):,}",
                )
                ai3.metric("Confidence", f"{ai_result.get('confidence', 0)}%")

                st.write(f"**Building type:** {ai_result.get('building_type', 'Unknown')}")
                st.write(f"**Construction stage:** {ai_result.get('construction_stage', 'Unknown')}")
                st.write(f"**Best first contact:** {ai_result.get('best_first_contact', 'Research needed')}")
                st.write(f"**Best contact type:** {ai_result.get('best_contact_type', 'Other')}")
                st.write(f"**Sales angle:** {ai_result.get('sales_angle', '')}")

                services = ai_result.get("recommended_services") or []
                if services:
                    st.write("**Recommended Services**")
                    st.markdown(render_tags_html([(s, "blue") for s in services]), unsafe_allow_html=True)

                next_actions = ai_result.get("next_actions") or []
                if next_actions:
                    st.write("**Next actions**")
                    st.markdown("\n".join(f"{i+1}. {action}" for i, action in enumerate(next_actions)))

                risks = ai_result.get("risks") or []
                if risks:
                    with st.expander("Risks and assumptions"):
                        st.markdown("\n".join(f"- {risk}" for risk in risks))

                if st.button(
                    "Regenerate AI analysis",
                    key=f"regenerate-ai-{permit_no}",
                    use_container_width=True,
                ):
                    save_tracking(permit_no, {"ai_analysis_json": "", "ai_updated_at": ""})
                    st.rerun()
            else:
                st.caption(
                    "AI analysis uses the permit details already in the dashboard. "
                    "It does not replace a site survey or final engineering estimate."
                )
                if st.button(
                    "Generate AI analysis",
                    key=f"generate-ai-{permit_no}",
                    type="primary",
                    use_container_width=True,
                ):
                    try:
                        ai_client = AIIntelligenceClient(PROJECT_ROOT)
                        with st.spinner("Analyzing this permit opportunity..."):
                            ai_result = ai_client.analyze_lead(
                                permit_number=permit_no,
                                address=clean_text(row.get("address", "")),
                                permit_type=clean_text(row.get("permit_type", "")),
                                description=clean_text(row.get("work_description", "")),
                                reported_cost=row.get("reported_cost"),
                                existing_score=row.get("lead_score"),
                                recommended_services=clean_text(row.get("recommended_services", "")),
                                permit_contacts=clean_text(row.get("permit_contacts", "")),
                            )
                        save_tracking(
                            permit_no,
                            {
                                "ai_analysis_json": json.dumps(ai_result),
                                "ai_updated_at": datetime.now().isoformat(timespec="seconds"),
                            },
                        )
                        st.success("AI opportunity analysis created.")
                        st.rerun()
                    except AIIntelligenceError as exc:
                        st.error(f"AI analysis error: {exc}")
                    except Exception as exc:
                        st.error(f"Unexpected AI error: {exc}")

        with st.container(border=True):
            st.markdown("#### 🏢 Company Research")
            st.caption(
                "Uses live web search the first time, then saves the company profile "
                "locally for faster reuse. Refresh research when the saved profile becomes stale."
            )

            company_candidates = extract_company_candidates(
                clean_text(row.get("permit_contacts", ""))
            )
            role_options = list(company_candidates.keys())
            if "Company / owner" not in role_options:
                role_options.append("Company / owner")
            if not role_options:
                role_options = ["Company / owner"]

            selected_research_role = st.selectbox(
                "Company role",
                role_options,
                key=f"research-role-{permit_no}",
            )
            default_company_name = company_candidates.get(
                selected_research_role,
                clean_text(row.get("company", "")),
            )
            research_company_name = st.text_input(
                "Company name",
                value=default_company_name,
                key=f"research-company-{permit_no}-{selected_research_role}",
                placeholder="Example: Ryan Companies US, Inc.",
            )

            company_research_result = None
            research_client = None
            try:
                research_client = CompanyResearchClient(PROJECT_ROOT)
                if research_company_name.strip():
                    company_research_result = research_client.get_cached(
                        research_company_name,
                        selected_research_role,
                    )
            except Exception as exc:
                st.warning(f"Company research setup: {exc}")

            research_col1, research_col2 = st.columns(2)
            run_research = research_col1.button(
                "Research company",
                key=f"research-company-button-{permit_no}-{selected_research_role}",
                type="primary",
                use_container_width=True,
                disabled=not research_company_name.strip(),
            )
            refresh_research = research_col2.button(
                "Refresh live research",
                key=f"refresh-company-button-{permit_no}-{selected_research_role}",
                use_container_width=True,
                disabled=not research_company_name.strip(),
            )

            if run_research or refresh_research:
                try:
                    research_client = research_client or CompanyResearchClient(PROJECT_ROOT)
                    with st.spinner("Searching public company and project sources..."):
                        company_research_result = research_client.research_company(
                            company_name=research_company_name,
                            role=selected_research_role,
                            address=clean_text(row.get("address", "")),
                            permit_number=permit_no,
                            permit_type=clean_text(row.get("permit_type", "")),
                            work_description=clean_text(row.get("work_description", "")),
                            force_refresh=refresh_research,
                        )
                    st.success(
                        "Company research refreshed from live sources."
                        if refresh_research
                        else "Company research completed."
                    )
                except CompanyResearchError as exc:
                    st.error(f"Company research error: {exc}")
                except Exception as exc:
                    st.error(f"Unexpected company research error: {exc}")

            if company_research_result:
                source_label = (
                    "Saved local profile"
                    if company_research_result.get("_from_cache")
                    else "Fresh live research"
                )
                if company_research_result.get("_is_stale"):
                    source_label += " • stale"
                st.caption(
                    f"{source_label} • Last researched: "
                    f"{company_research_result.get('_researched_at', 'Unknown')}"
                )

                r1, r2 = st.columns(2)
                r1.metric(
                    "Identity confidence",
                    f"{company_research_result.get('identity_confidence', 0)}%",
                )
                r2.metric(
                    "Chicago presence",
                    company_research_result.get("chicago_presence", "Unknown"),
                )

                st.write(
                    f"**Company:** {company_research_result.get('company_name', research_company_name)}"
                )
                st.write(
                    f"**Industry:** {company_research_result.get('industry', '') or 'Not confirmed'}"
                )
                st.write(
                    f"**Headquarters:** {company_research_result.get('headquarters', '') or 'Not confirmed'}"
                )
                st.write(
                    f"**Founded:** {company_research_result.get('founded', '') or 'Not confirmed'}"
                )
                st.write(
                    f"**Employees:** {company_research_result.get('employee_range', '') or 'Not confirmed'}"
                )
                st.write(
                    f"**Estimated revenue:** {company_research_result.get('revenue_range', '') or 'Not confirmed'}"
                )

                website = clean_text(company_research_result.get("website", ""))
                phone_number = clean_text(company_research_result.get("phone", ""))
                email_address = clean_text(company_research_result.get("email", ""))
                links_row = st.columns(2)
                if website:
                    links_row[0].link_button(
                        "Open company website",
                        website,
                        use_container_width=True,
                    )
                if phone_number:
                    links_row[1].write(f"**Public phone:** {phone_number}")
                if email_address:
                    st.write(f"**Public email:** {email_address}")

                summary = clean_text(company_research_result.get("summary", ""))
                if summary:
                    st.write("**Company profile**")
                    st.info(summary)

                decision_roles = company_research_result.get("decision_maker_roles") or []
                if decision_roles:
                    st.write("**Likely decision-maker roles**")
                    st.markdown("\n".join(f"- {item}" for item in decision_roles))

                projects = company_research_result.get("recent_projects") or []
                if projects:
                    with st.expander("Recent or relevant projects"):
                        st.markdown("\n".join(f"- {item}" for item in projects))

                strategy = clean_text(company_research_result.get("sales_strategy", ""))
                if strategy:
                    st.write("**ChaproNet sales strategy**")
                    st.success(strategy)

                actions = company_research_result.get("recommended_next_actions") or []
                if actions:
                    st.write("**Recommended next actions**")
                    st.markdown(
                        "\n".join(f"{i + 1}. {item}" for i, item in enumerate(actions))
                    )

                sources = company_research_result.get("sources") or []
                if sources:
                    with st.expander("Research sources"):
                        for source in sources:
                            if isinstance(source, dict) and source.get("url"):
                                st.markdown(
                                    f"- [{source.get('title', source['url'])}]({source['url']})"
                                )

                warnings = company_research_result.get("warnings") or []
                if warnings:
                    with st.expander("Identity warnings and limitations"):
                        st.markdown("\n".join(f"- {item}" for item in warnings))

    with right:
        with st.container(border=True):
            st.markdown("#### 📋 Sales Tracking & Contact Info")
            status_options = list(LEAD_STAGES)
            current_status = str(row.get("status", "New Lead") or "New Lead")
            if current_status not in status_options:
                status_options.insert(0, current_status)

            ai_suggested_contact_type = ""
            if stored_ai:
                try:
                    ai_suggested_contact_type = (json.loads(stored_ai) or {}).get("best_contact_type", "")
                except Exception:
                    ai_suggested_contact_type = ""
            contact_type_options = list(CONTACT_TYPES)
            saved_contact_type = clean_text(row.get("best_contact_type", "")) or ai_suggested_contact_type or "Other"
            if saved_contact_type not in contact_type_options:
                saved_contact_type = "Other"

            with st.form(f"tracking-{permit_no}"):
                status = st.selectbox("Status", status_options, index=status_options.index(current_status))

                st.markdown("**Contact Information**")
                st.caption("Only enter information you've actually confirmed -- fields left blank are shown as \"Not found\" everywhere else in the dashboard.")
                contact_name = st.text_input("Contact Name", value=clean_text(row.get("contact_name", "")), placeholder="Not found")
                company = st.text_input("Company", value=clean_text(row.get("company", "")), placeholder="Not found")
                contact_role = st.text_input("Role", value=clean_text(row.get("contact_role", "")), placeholder="Not found")
                phone = st.text_input("Phone", value=clean_text(row.get("phone", "")), placeholder="Not found")
                email = st.text_input("Email", value=clean_text(row.get("email", "")), placeholder="Not found")
                contact_website = st.text_input("Website", value=clean_text(row.get("contact_website", "")), placeholder="Not found")
                best_contact_type = st.selectbox(
                    "Best person to contact",
                    contact_type_options,
                    index=contact_type_options.index(saved_contact_type),
                    help="Defaults to the AI's suggestion once this permit has been analyzed; override anytime.",
                )

                st.markdown("**Follow-Up**")
                fc1, fc2 = st.columns(2)
                last_contact_date = fc1.text_input(
                    "Last contact date (YYYY-MM-DD)",
                    value=clean_text(row.get("last_contact_date", "")),
                )
                next_follow_up = fc2.text_input(
                    "Next follow-up (YYYY-MM-DD)",
                    value=clean_text(row.get("next_follow_up", ""))
                )
                assigned_to = st.text_input("Assigned to", value=clean_text(row.get("assigned_to", "")))
                notes = st.text_area("Notes", value=clean_text(row.get("notes", "")), height=100)
                saved = st.form_submit_button("Save lead updates", use_container_width=True, type="primary")
            if saved:
                save_tracking(
                    permit_no,
                    {
                        "status": status,
                        "assigned_to": assigned_to,
                        "company": company,
                        "phone": phone,
                        "email": email,
                        "contact_name": contact_name,
                        "contact_role": contact_role,
                        "contact_website": contact_website,
                        "best_contact_type": best_contact_type,
                        "last_contact_date": last_contact_date,
                        "next_follow_up": next_follow_up,
                        "notes": notes,
                    },
                )
                st.success("Lead tracking saved locally.")
                st.rerun()

        with st.container(border=True):
            st.markdown("#### ✉️ Outreach Email")
            if not ai_result:
                st.caption(
                    "Tip: run AI Opportunity Intelligence above first for a sharper, more "
                    "relevant email (it feeds recommended services and building type in). "
                    "You can still generate one without it."
                )
            else:
                preview_match = match_experience(
                    building_type=ai_result.get("building_type", "Unknown"),
                    recommended_services=ai_result.get("recommended_services") or [],
                    permit_type=clean_text(row.get("permit_type", "")),
                )
                if preview_match:
                    st.caption(
                        f"📎 Will reference your **{preview_match['building_type']}** "
                        f"**{preview_match['project_type'].lower()}** experience from ChaproNet Experience."
                    )
                else:
                    st.caption("No closely matching past project found in Experience -- the email will speak generally.")

            draft_subject = clean_text(row.get("outreach_email_subject", ""))
            draft_body = clean_text(row.get("outreach_email_body", ""))
            draft_status = clean_text(row.get("outreach_email_status", ""))
            has_draft = bool(draft_body)

            if has_draft:
                status_label = {
                    "approved": "✅ Approved for sending",
                    "sent": "📨 Sent",
                }.get(draft_status, "📝 Draft (not yet approved)")
                st.caption(status_label)

            gen_col, regen_col = st.columns(2)
            generate_clicked = gen_col.button(
                "✨ Generate Outreach Email" if not has_draft else "✨ Generate New Version",
                key=f"generate-email-{permit_no}",
                type="primary" if not has_draft else "secondary",
                use_container_width=True,
            )
            regenerate_note = ""
            if has_draft:
                regenerate_note = regen_col.text_input(
                    "What should change? (optional)",
                    key=f"regen-note-{permit_no}",
                    placeholder="e.g. shorter, more casual, mention Wi-Fi",
                    label_visibility="collapsed",
                )

            if generate_clicked:
                try:
                    outreach_client = OutreachClient(PROJECT_ROOT)
                    services_for_email = (ai_result or {}).get("recommended_services") or []
                    building_type_for_email = (ai_result or {}).get("building_type", "Unknown")
                    experience_match = match_experience(
                        building_type=building_type_for_email,
                        recommended_services=services_for_email,
                        permit_type=clean_text(row.get("permit_type", "")),
                    )
                    with st.spinner("Writing a personalized outreach email..."):
                        email = outreach_client.generate_email(
                            permit_number=permit_no,
                            address=clean_text(row.get("address", "")),
                            permit_type=clean_text(row.get("permit_type", "")),
                            description=clean_text(row.get("work_description", "")),
                            building_type=building_type_for_email,
                            recommended_services=services_for_email,
                            best_contact_type=clean_text(row.get("best_contact_type", "")) or (ai_result or {}).get("best_contact_type", "Other"),
                            contact_name=clean_text(row.get("contact_name", "")),
                            contact_company=clean_text(row.get("company", "")),
                            matched_experience=experience_match,
                            regenerate_note=regenerate_note,
                        )
                    updates = {
                        "outreach_email_subject": email["subject"],
                        "outreach_email_body": email["body"],
                        "outreach_email_status": "draft",
                        "outreach_email_updated_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    if str(row.get("status", "New Lead") or "New Lead") in ("New Lead", "New", "Qualified"):
                        updates["status"] = "Email Drafted"
                    save_tracking(permit_no, updates)
                    if experience_match:
                        st.success(
                            f"Outreach email generated, referencing your {experience_match['building_type']} "
                            f"{experience_match['project_type'].lower()} experience. Review it below before approving."
                        )
                    else:
                        st.success(
                            "Outreach email generated. No closely matching past project was found in Experience, "
                            "so it speaks generally about ChaproNet's experience. Review it below before approving."
                        )
                    st.rerun()
                except OutreachError as exc:
                    st.error(f"Outreach email error: {exc}")
                except Exception as exc:
                    st.error(f"Unexpected outreach error: {exc}")

            if has_draft:
                with st.form(f"email-editor-{permit_no}"):
                    edited_subject = st.text_input("Subject", value=draft_subject)
                    edited_body = st.text_area("Body", value=draft_body, height=220)
                    save_col, approve_col = st.columns(2)
                    save_edits = save_col.form_submit_button("💾 Save Edits", use_container_width=True)
                    approve = approve_col.form_submit_button(
                        "✅ Approve for Sending", use_container_width=True, type="primary"
                    )
                if save_edits or approve:
                    save_tracking(
                        permit_no,
                        {
                            "outreach_email_subject": edited_subject,
                            "outreach_email_body": edited_body,
                            "outreach_email_status": "approved" if approve else "draft",
                            "outreach_email_updated_at": datetime.now().isoformat(timespec="seconds"),
                        },
                    )
                    st.success("Approved -- ready to send when you are." if approve else "Draft saved.")
                    st.rerun()

                st.caption("Copy-ready version:")
                st.code(f"Subject: {draft_subject}\n\n{draft_body}", language=None)

                if draft_status in ("approved", "sent"):
                    st.divider()
                    recipient_email = clean_text(row.get("email", ""))
                    if not recipient_email:
                        st.warning(
                            "Add the contact's email under Contact Information above before sending."
                        )
                    else:
                        send_col, confirm_col = st.columns(2)
                        send_col.link_button(
                            "📧 Open in Email Client",
                            build_mailto_link(recipient_email, draft_subject, draft_body),
                            use_container_width=True,
                            type="primary",
                        )
                        if draft_status == "sent":
                            sent_at = clean_text(row.get("outreach_email_sent_at", ""))
                            confirm_col.success(f"✅ Marked sent{' on ' + sent_at.split('T')[0] if sent_at else ''}")
                        else:
                            if confirm_col.button(
                                "✅ I sent this email",
                                key=f"mark-sent-{permit_no}",
                                use_container_width=True,
                            ):
                                today = datetime.now().strftime("%Y-%m-%d")
                                sent_updates = {
                                    "outreach_email_status": "sent",
                                    "outreach_email_sent_at": datetime.now().isoformat(timespec="seconds"),
                                    "last_contact_date": today,
                                }
                                if str(row.get("status", "New Lead") or "New Lead") in (
                                    "New Lead", "New", "Qualified", "Email Drafted",
                                ):
                                    sent_updates["status"] = "Contacted"
                                save_tracking(permit_no, sent_updates)
                                st.success("Marked as sent and moved to Contacted.")
                                st.rerun()
                    st.caption(
                        "Opening in your email client does not send anything by itself -- this app "
                        "never sends email on its own. Click \"I sent this email\" only after you've "
                        "actually hit send yourself."
                    )
                else:
                    st.caption(
                        "This email is never sent automatically. Approve it above to unlock sending "
                        "it from your own email client."
                    )

        with st.container(border=True):
            st.markdown("#### 🔧 Jobber Actions")
            try:
                jobber = JobberClient(PROJECT_ROOT)
                if not jobber.is_connected():
                    st.warning("Connect Jobber before creating a CRM lead.")
                    if st.button("Start Jobber connection", key=f"connect-{permit_no}", use_container_width=True):
                        auth_url = jobber.start_oauth()
                        st.link_button("Authorize ChaproNet Lead Intelligence", auth_url, use_container_width=True)
                    if st.button("Finish connection after approval", key=f"finish-{permit_no}", use_container_width=True):
                        jobber.finish_oauth()
                        st.success("Jobber connected.")
                        st.rerun()
                else:
                    existing_jobber = clean_text(row.get("jobber_url", ""))
                    existing_request_id = clean_text(row.get("jobber_request_id", ""))
                    if existing_request_id:
                        st.success("This permit has a recorded Jobber request.")
                        if existing_jobber:
                            st.link_button("Open Jobber", existing_jobber, use_container_width=True)
                        st.caption(
                            "Deleting a request inside Jobber does not automatically clear "
                            "the dashboard's local record."
                        )
                        if st.button(
                            "Clear this permit's Jobber record",
                            key=f"clear-jobber-{permit_no}",
                            use_container_width=True,
                        ):
                            save_tracking(
                                permit_no,
                                {
                                    "jobber_url": "",
                                    "jobber_client_id": "",
                                    "jobber_request_id": "",
                                },
                            )
                            st.success("Local Jobber record cleared for this permit.")
                            st.rerun()
                    else:
                        confirm = st.checkbox(
                            "I reviewed this permit and want to create a Jobber client and request.",
                            key=f"confirm-jobber-{permit_no}",
                        )
                        if st.button(
                            "Push lead to Jobber",
                            key=f"push-jobber-{permit_no}",
                            type="primary",
                            use_container_width=True,
                            disabled=not confirm,
                        ):
                            with st.spinner("Creating the client and request in Jobber..."):
                                result = jobber.create_permit_lead(
                                    permit_number=permit_no,
                                    address=str(row.get("address", "") or ""),
                                    company=str(company or row.get("company", "") or ""),
                                    phone=str(phone or row.get("phone", "") or ""),
                                    email=str(email or row.get("email", "") or ""),
                                    description=str(row.get("work_description", "") or ""),
                                    permit_type=str(row.get("permit_type", "") or ""),
                                    reported_cost=row.get("reported_cost"),
                                    lead_score=row.get("lead_score"),
                                    recommended_services=str(row.get("recommended_services", "") or ""),
                                    source_url=str(row.get("source_url", "") or ""),
                                )
                            save_tracking(
                                permit_no,
                                {
                                    "status": "Ready to Contact",
                                    "company": company,
                                    "phone": phone,
                                    "email": email,
                                    "notes": notes,
                                    "jobber_url": result.get("jobber_url", ""),
                                    "jobber_client_id": result.get("client_id", ""),
                                    "jobber_request_id": result.get("request_id", ""),
                                },
                            )
                            st.success("Jobber client and request created.")
                            if result.get("jobber_url"):
                                st.link_button("Open in Jobber", result["jobber_url"], use_container_width=True)
                            st.rerun()
            except JobberError as exc:
                st.error(f"Jobber error: {exc}")
                with st.expander("Technical details"):
                    st.code(exc.details or "No additional details.")
            except Exception as exc:
                st.error(f"Jobber setup error: {exc}")

        with st.container(border=True):
            st.markdown("#### 📘 Confluence Actions")
            existing_confluence = clean_text(row.get("confluence_url", ""))
            if existing_confluence:
                st.success("This permit has a Confluence research page.")
                st.link_button(
                    "Open Confluence Page",
                    existing_confluence,
                    use_container_width=True,
                )
                c_upd, c_clear = st.columns(2)
                if c_upd.button(
                    "Refresh Confluence Page",
                    key=f"refresh-confluence-{permit_no}",
                    use_container_width=True,
                ):
                    try:
                        confluence = ConfluenceClient(PROJECT_ROOT)
                        page_id = confluence_page_id_from_url(existing_confluence)
                        if not page_id:
                            raise ConfluenceError("Could not determine the Confluence page ID.")
                        result = confluence.update_lead_page(
                            page_id=page_id,
                            permit_number=permit_no,
                            address=clean_text(row.get("address", "")),
                            issue_date=clean_text(row.get("issue_date", "")),
                            permit_type=clean_text(row.get("permit_type", "")),
                            description=clean_text(row.get("work_description", "")),
                            reported_cost=row.get("reported_cost"),
                            lead_score=row.get("lead_score"),
                            priority=clean_text(row.get("priority", "")),
                            recommended_services=clean_text(row.get("recommended_services", "")),
                            permit_contacts=clean_text(row.get("permit_contacts", "")),
                            company=clean_text(company),
                            phone=clean_text(phone),
                            email=clean_text(email),
                            next_follow_up=clean_text(next_follow_up),
                            notes=clean_text(notes),
                            source_url=clean_text(row.get("source_url", "")),
                            maps_url=clean_text(row.get("google_maps_url", "")),
                            owner_url=clean_text(row.get("owner_research_url", "")),
                            gc_url=clean_text(row.get("gc_research_url", "")),
                            jobber_url=clean_text(row.get("jobber_url", "")),
                        )
                        save_tracking(permit_no, {"confluence_url": result["url"]})
                        st.success("Confluence page refreshed.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not refresh Confluence page: {exc}")

                if c_clear.button(
                    "Clear Local Record",
                    key=f"clear-confluence-{permit_no}",
                    use_container_width=True,
                ):
                    save_tracking(permit_no, {"confluence_url": ""})
                    st.success("Local Confluence record cleared.")
                    st.rerun()
            else:
                try:
                    confluence = ConfluenceClient(PROJECT_ROOT)
                    confluence.test_connection()
                    create_page = st.checkbox(
                        "I reviewed this permit and want to create a Confluence lead page.",
                        key=f"confirm-confluence-{permit_no}",
                    )
                    if st.button(
                        "Create Confluence Page",
                        key=f"create-confluence-{permit_no}",
                        type="primary",
                        use_container_width=True,
                        disabled=not create_page,
                    ):
                        with st.spinner("Creating the Confluence lead page..."):
                            result = confluence.create_lead_page(
                                permit_number=permit_no,
                                address=clean_text(row.get("address", "")),
                                issue_date=clean_text(row.get("issue_date", "")),
                                permit_type=clean_text(row.get("permit_type", "")),
                                description=clean_text(row.get("work_description", "")),
                                reported_cost=row.get("reported_cost"),
                                lead_score=row.get("lead_score"),
                                priority=clean_text(row.get("priority", "")),
                                recommended_services=clean_text(row.get("recommended_services", "")),
                                permit_contacts=clean_text(row.get("permit_contacts", "")),
                                company=clean_text(company),
                                phone=clean_text(phone),
                                email=clean_text(email),
                                next_follow_up=clean_text(next_follow_up),
                                notes=clean_text(notes),
                                source_url=clean_text(row.get("source_url", "")),
                                maps_url=clean_text(row.get("google_maps_url", "")),
                                owner_url=clean_text(row.get("owner_research_url", "")),
                                gc_url=clean_text(row.get("gc_research_url", "")),
                                jobber_url=clean_text(row.get("jobber_url", "")),
                            )
                        save_tracking(
                            permit_no,
                            {"confluence_url": result["url"]},
                        )
                        st.success("Confluence lead page created.")
                        st.link_button(
                            "Open Confluence Page",
                            result["url"],
                            use_container_width=True,
                        )
                        st.rerun()
                except ConfluenceError as exc:
                    st.warning("Confluence setup is incomplete.")
                    with st.expander("Setup details"):
                        st.code(str(exc))
                except Exception as exc:
                    st.error(f"Confluence error: {exc}")


def render_lead_picker_and_detail(filtered: pd.DataFrame, key_prefix: str) -> None:
    """Selectbox + detail panel, reusable across pages. `key_prefix` keeps
    widget keys unique when multiple pages embed this in the same session.
    """
    if not len(filtered):
        return
    st.markdown("### Permit Detail")
    options: dict[str, int] = {}
    for idx, row in filtered.iterrows():
        label = f"{int(row.get('lead_score', 0) or 0):02d} • {row.get('address', 'Unknown address')} • {row.get('permit_number', '')}"
        options[label] = idx

    preselect_key = f"{key_prefix}-preselect"
    default_index = 0
    wanted_permit = st.session_state.pop(preselect_key, None)
    if wanted_permit:
        for i, (label, idx) in enumerate(options.items()):
            if str(filtered.loc[idx].get("permit_number", "")) == str(wanted_permit):
                default_index = i
                break

    selected_label = st.selectbox(
        "Select a permit",
        list(options.keys()),
        index=default_index,
        key=f"{key_prefix}-select-lead",
    )
    row = filtered.loc[options[selected_label]]
    permit_no = str(row.get("permit_number", ""))
    render_lead_detail_panel(row, permit_no)
