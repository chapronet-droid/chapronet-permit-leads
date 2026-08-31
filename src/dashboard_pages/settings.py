"""Settings: integration status, data refresh, and maintenance tools.

This is the same "Controls" + "Integration status" + "Repair local Jobber
status" logic that used to live in the sidebar of the single-page dashboard
-- moved here so the sidebar is pure navigation, matching the new layout.
"""

from __future__ import annotations

import json
from datetime import datetime

import streamlit as st

from jobber_integration import JobberClient
from confluence_integration import ConfluenceClient
from ai_intelligence import AIIntelligenceClient, AIIntelligenceError
from company_research import CompanyResearchClient

from dashboard_common import (
    PROJECT_ROOT,
    CSV_PATH,
    DB_PATH,
    db,
    page_header,
    run_permit_refresh,
    load_leads,
    save_tracking,
    clean_text,
    ai_lead_score,
)


def render() -> None:
    page_header("Settings", "Data refresh, integration health, and maintenance tools.")

    with st.container(border=True):
        st.markdown("#### Data Controls")
        c1, c2 = st.columns(2)
        if c1.button("↻ Refresh dashboard data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        if c2.button("▶ Run permit update now", use_container_width=True, type="primary"):
            with st.spinner("Pulling the latest Chicago permits..."):
                ok, message = run_permit_refresh()
            st.session_state["permit_update_result"] = (ok, message)
            st.cache_data.clear()
            st.rerun()

        permit_update_result = st.session_state.pop("permit_update_result", None)
        if permit_update_result:
            update_ok, update_message = permit_update_result
            if update_ok:
                st.success("Permit report updated.")
                with st.expander("Run details"):
                    st.code(update_message)
            else:
                st.error("Permit update failed.")
                st.code(update_message)
        st.caption(
            f"Data source: {CSV_PATH.name} • Local tracking database: {DB_PATH.name} • "
            f"Last page load: {datetime.now().strftime('%Y-%m-%d %I:%M %p')}"
        )

    with st.container(border=True):
        st.markdown("#### Integration Status")
        st.write("✅ Chicago permit report")
        st.write("✅ Local lead tracking")
        try:
            jobber_status = JobberClient(PROJECT_ROOT)
            if jobber_status.is_connected():
                acct = jobber_status.get_account()
                st.write(f"✅ Jobber connected: {acct.get('name', 'Account')}")
            else:
                st.write("🟡 Jobber not connected to this dashboard")
                if st.button("Connect Jobber", use_container_width=True):
                    url = jobber_status.start_oauth()
                    st.link_button("Open Jobber authorization", url, use_container_width=True)
        except Exception as exc:
            st.write("🔴 Jobber configuration needs attention")
            st.caption(str(exc))
        try:
            confluence_status = ConfluenceClient(PROJECT_ROOT)
            site = confluence_status.test_connection()
            st.write(f"✅ Confluence connected: {site}")
        except Exception as exc:
            st.write("🟡 Confluence not connected")
            st.caption(str(exc))
        try:
            ai_status = AIIntelligenceClient(PROJECT_ROOT)
            st.write(f"✅ AI intelligence ready: {ai_status.model}")
        except Exception as exc:
            st.write("🟡 AI intelligence not configured")
            st.caption(str(exc))
        try:
            research_status = CompanyResearchClient(PROJECT_ROOT)
            st.write(f"✅ Live company research ready: {research_status.model}")
        except Exception as exc:
            st.write("🟡 Company research not configured")
            st.caption(str(exc))

    with st.container(border=True):
        st.markdown("#### AI Lead Analysis")
        df = load_leads()
        unanalyzed = df[df.apply(ai_lead_score, axis=1).isna()] if not df.empty else df
        st.write(f"**{len(unanalyzed):,}** of **{len(df):,}** permits have not been AI-analyzed yet.")
        st.caption(
            "Analyzing a permit makes one OpenAI call and caches the result (Lead Score, "
            "recommended services, best contact type) so it's never re-analyzed automatically. "
            "This can take a while and uses your OpenAI quota."
        )
        confirm_batch = st.checkbox(
            f"I understand this will make up to {len(unanalyzed):,} OpenAI API calls.",
            key="confirm-batch-ai",
            disabled=unanalyzed.empty,
        )
        if st.button(
            "🤖 Analyze all unanalyzed permits",
            use_container_width=True,
            type="primary",
            disabled=unanalyzed.empty or not confirm_batch,
        ):
            try:
                ai_client = AIIntelligenceClient(PROJECT_ROOT)
            except Exception as exc:
                st.error(f"AI intelligence is not configured: {exc}")
            else:
                progress = st.progress(0.0, text="Starting...")
                succeeded, failed = 0, 0
                total = len(unanalyzed)
                for i, (_, row) in enumerate(unanalyzed.iterrows(), start=1):
                    permit_no = str(row.get("permit_number", ""))
                    try:
                        result = ai_client.analyze_lead(
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
                                "ai_analysis_json": json.dumps(result),
                                "ai_updated_at": datetime.now().isoformat(timespec="seconds"),
                            },
                        )
                        succeeded += 1
                    except AIIntelligenceError:
                        failed += 1
                    except Exception:
                        failed += 1
                    progress.progress(i / total, text=f"Analyzed {i} of {total} ({succeeded} ok, {failed} failed)")
                st.cache_data.clear()
                st.success(f"Batch analysis complete: {succeeded} analyzed, {failed} failed.")
                st.rerun()

    with st.container(border=True):
        with st.expander("Repair local Jobber status"):
            st.caption(
                "Use this only if the dashboard says every permit was pushed but "
                "the records are not present in Jobber."
            )
            confirm_reset = st.checkbox(
                "Clear all locally recorded Jobber push flags",
                key="confirm-clear-jobber-flags",
            )
            if st.button(
                "Clear incorrect Jobber flags",
                disabled=not confirm_reset,
                use_container_width=True,
            ):
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE lead_tracking
                        SET jobber_url='',
                            jobber_client_id='',
                            jobber_request_id='',
                            updated_at=?
                        """,
                        (datetime.now().isoformat(timespec="seconds"),),
                    )
                    conn.commit()
                st.success("Local Jobber flags cleared. No Jobber records were deleted.")
                st.rerun()
