
from __future__ import annotations

import os
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"
STATE_DIR = PROJECT_ROOT / "state"
DB_PATH = STATE_DIR / "dashboard.db"
CSV_PATH = OUTPUT_DIR / "chapronet_permit_leads.csv"
TOP_CSV_PATH = OUTPUT_DIR / "chapronet_top_leads.csv"
RUN_SCRIPT = PROJECT_ROOT / "run_daily.bat"

STATE_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="ChaproNet Lead Intelligence",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.25rem; padding-bottom: 2rem;}
      [data-testid="stMetricValue"] {font-size: 1.7rem;}
      .status-pill {
        display:inline-block; padding:0.2rem 0.55rem; border-radius:999px;
        background:#eef2ff; border:1px solid #c7d2fe; font-size:0.82rem;
      }
      .muted {color:#64748b;}
      .lead-card {
        border:1px solid #e2e8f0; border-radius:12px; padding:1rem;
        background:white; margin-bottom:0.75rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lead_tracking (
            permit_number TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'New',
            assigned_to TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            company TEXT DEFAULT '',
            next_follow_up TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            jobber_url TEXT DEFAULT '',
            jobber_client_id TEXT DEFAULT '',
            jobber_request_id TEXT DEFAULT '',
            confluence_url TEXT DEFAULT '',
            ai_analysis_json TEXT DEFAULT '',
            ai_updated_at TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    # Lightweight migrations for existing dashboard databases.
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(lead_tracking)").fetchall()
    }
    for column in [
        "jobber_client_id",
        "jobber_request_id",
        "ai_analysis_json",
        "ai_updated_at",
    ]:
        if column not in existing_columns:
            conn.execute(
                f"ALTER TABLE lead_tracking ADD COLUMN {column} TEXT DEFAULT ''"
            )
    conn.commit()
    return conn

def load_tracking() -> pd.DataFrame:
    with db() as conn:
        rows = conn.execute("SELECT * FROM lead_tracking").fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM lead_tracking LIMIT 0").description]
    return pd.DataFrame(rows, columns=cols)

def save_tracking(permit_number: str, values: dict[str, Any]) -> None:
    permitted = {
        "status", "assigned_to", "phone", "email", "company",
        "next_follow_up", "notes", "jobber_url", "jobber_client_id",
        "jobber_request_id", "confluence_url", "ai_analysis_json", "ai_updated_at"
    }
    clean = {k: str(v or "") for k, v in values.items() if k in permitted}
    fields = ["permit_number"] + list(clean.keys()) + ["updated_at"]
    params = [permit_number] + list(clean.values()) + [datetime.now().isoformat(timespec="seconds")]
    placeholders = ",".join("?" for _ in fields)
    updates = ",".join(f"{f}=excluded.{f}" for f in fields if f != "permit_number")
    with db() as conn:
        conn.execute(
            f"INSERT INTO lead_tracking ({','.join(fields)}) VALUES ({placeholders}) "
            f"ON CONFLICT(permit_number) DO UPDATE SET {updates}",
            params,
        )
        conn.commit()

def load_leads() -> pd.DataFrame:
    path = CSV_PATH if CSV_PATH.exists() else TOP_CSV_PATH
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for col in ["reported_cost", "lead_score", "latitude", "longitude"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "issue_date" in df.columns:
        df["issue_date"] = pd.to_datetime(df["issue_date"], errors="coerce")
    if "permit_number" not in df.columns:
        df["permit_number"] = df.index.astype(str)

    tracking = load_tracking()
    if not tracking.empty:
        df = df.merge(tracking, on="permit_number", how="left", suffixes=("", "_tracked"))
        for col in [
            "status", "assigned_to", "phone", "email", "company",
            "next_follow_up", "notes", "jobber_url", "jobber_client_id",
            "jobber_request_id", "confluence_url", "ai_analysis_json", "ai_updated_at"
        ]:
            tracked = f"{col}_tracked"
            if tracked in df.columns:
                base = df[col] if col in df.columns else ""
                df[col] = df[tracked].where(df[tracked].fillna("") != "", base)
                df.drop(columns=[tracked], inplace=True)
    if "status" not in df.columns:
        df["status"] = "New"
    df["status"] = df["status"].replace("", "New").fillna("New")
    return df

def money(v: Any) -> str:
    try:
        if pd.isna(v):
            return "$0"
        return f"${float(v):,.0f}"
    except Exception:
        return "$0"

def clean_text(v: Any) -> str:
    """Convert database/CSV values to text without turning NaN into 'nan'."""
    try:
        if v is None or pd.isna(v):
            return ""
    except Exception:
        pass
    text = str(v).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text

def confluence_page_id_from_url(url: str) -> str:
    """Extract a Confluence page ID from modern or legacy Confluence URLs."""
    text = clean_text(url)
    match = re.search(r"/pages/(\d+)", text)
    if match:
        return match.group(1)
    match = re.search(r"[?&]pageId=(\d+)", text)
    return match.group(1) if match else ""

def run_permit_refresh() -> tuple[bool, str]:
    if not RUN_SCRIPT.exists():
        return False, "run_daily.bat was not found."
    try:
        completed = subprocess.run(
            ["cmd.exe", "/c", str(RUN_SCRIPT)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        return completed.returncode == 0, output[-6000:]
    except Exception as exc:
        return False, str(exc)

st.title("ChaproNet Lead Intelligence")
st.caption("Local dashboard • Chicago permits • Jobber • Confluence • AI opportunity intelligence • Live company research")

with st.sidebar:
    st.header("Controls")
    if st.button("↻ Refresh dashboard data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if st.button("▶ Run permit update now", use_container_width=True):
        with st.spinner("Pulling the latest Chicago permits..."):
            ok, message = run_permit_refresh()
        if ok:
            st.success("Permit report updated.")
            st.cache_data.clear()
            with st.expander("Run details"):
                st.code(message)
        else:
            st.error("Permit update failed.")
            st.code(message)

    st.divider()
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

    st.divider()
    st.subheader("Integration status")
    st.write("✅ Chicago permit report")
    st.write("✅ Local lead tracking")
    try:
        jobber_sidebar = JobberClient(PROJECT_ROOT)
        if jobber_sidebar.is_connected():
            acct = jobber_sidebar.get_account()
            st.write(f"✅ Jobber connected: {acct.get('name', 'Account')}")
        else:
            st.write("🟡 Jobber not connected to this dashboard")
            if st.button("Connect Jobber", use_container_width=True):
                url = jobber_sidebar.start_oauth()
                st.link_button("Open Jobber authorization", url, use_container_width=True)
    except Exception as exc:
        st.write("🔴 Jobber configuration needs attention")
        st.caption(str(exc))
    try:
        confluence_sidebar = ConfluenceClient(PROJECT_ROOT)
        site = confluence_sidebar.test_connection()
        st.write(f"✅ Confluence connected: {site}")
    except Exception as exc:
        st.write("🟡 Confluence not connected")
        st.caption(str(exc))
    try:
        ai_sidebar = AIIntelligenceClient(PROJECT_ROOT)
        st.write(f"✅ AI intelligence ready: {ai_sidebar.model}")
    except Exception as exc:
        st.write("🟡 AI intelligence not configured")
        st.caption(str(exc))
    try:
        research_sidebar = CompanyResearchClient(PROJECT_ROOT)
        st.write(f"✅ Live company research ready: {research_sidebar.model}")
    except Exception as exc:
        st.write("🟡 Company research not configured")
        st.caption(str(exc))

df = load_leads()

if df.empty:
    st.warning(
        "No permit CSV was found yet. Run `run_daily.bat` first, then reopen or refresh this dashboard."
    )
    st.code(str(CSV_PATH))
    st.stop()

# Filters
with st.sidebar:
    st.divider()
    st.subheader("Filters")
    score_min = int(df["lead_score"].min()) if "lead_score" in df and df["lead_score"].notna().any() else 0
    score_max = int(df["lead_score"].max()) if "lead_score" in df and df["lead_score"].notna().any() else 100
    min_score = st.slider("Minimum lead score", 0, max(100, score_max), min(35, max(100, score_max)))
    statuses = sorted(df["status"].dropna().astype(str).unique().tolist())
    selected_statuses = st.multiselect("Status", statuses, default=statuses)
    search = st.text_input("Search address, permit, contact or description")
    only_new = st.checkbox("Issued in the last 2 days", value=False)

filtered = df.copy()
if "lead_score" in filtered:
    filtered = filtered[filtered["lead_score"].fillna(0) >= min_score]
if selected_statuses:
    filtered = filtered[filtered["status"].isin(selected_statuses)]
if only_new and "issue_date" in filtered:
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=2)
    filtered = filtered[filtered["issue_date"] >= cutoff]
if search:
    searchable_cols = [
        c for c in [
            "address", "permit_number", "permit_contacts", "work_description",
            "permit_type", "company", "contact_1_name", "contact_2_name"
        ] if c in filtered.columns
    ]
    haystack = filtered[searchable_cols].astype(str).agg(" | ".join, axis=1)
    filtered = filtered[haystack.str.contains(search, case=False, na=False)]

# KPIs
total = len(filtered)
high_priority = int((filtered.get("lead_score", pd.Series(dtype=float)).fillna(0) >= 70).sum())
pipeline = float(filtered.get("reported_cost", pd.Series(dtype=float)).fillna(0).sum())
new_count = int((filtered["status"] == "New").sum()) if "status" in filtered else total

c1, c2, c3, c4 = st.columns(4)
c1.metric("Qualified leads", f"{total:,}")
c2.metric("High priority", f"{high_priority:,}")
c3.metric("Reported project value", money(pipeline))
c4.metric("New / unworked", f"{new_count:,}")

tab1, tab2, tab3 = st.tabs(["Lead Queue", "Map", "Pipeline"])

with tab1:
    st.subheader("Lead Queue")
    show_cols = [
        c for c in [
            "lead_score", "priority", "issue_date", "address", "permit_type",
            "reported_cost", "recommended_services", "permit_contacts", "status"
        ] if c in filtered.columns
    ]
    table = filtered[show_cols].copy()
    if "issue_date" in table:
        table["issue_date"] = table["issue_date"].dt.strftime("%Y-%m-%d")
    if "reported_cost" in table:
        table["reported_cost"] = table["reported_cost"].map(money)
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        height=420,
    )

    st.subheader("Lead Details")
    if len(filtered):
        options = {}
        for idx, row in filtered.iterrows():
            label = f"{int(row.get('lead_score', 0) or 0):02d} • {row.get('address', 'Unknown address')} • {row.get('permit_number', '')}"
            options[label] = idx
        selected_label = st.selectbox("Select a lead", list(options.keys()))
        row = filtered.loc[options[selected_label]]
        permit_no = str(row.get("permit_number", ""))

        left, right = st.columns([1.3, 1])
        with left:
            st.markdown(f"### {row.get('address', 'Unknown address')}")
            st.markdown(
                f"<span class='status-pill'>Score {int(row.get('lead_score', 0) or 0)}/100</span>",
                unsafe_allow_html=True,
            )
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

            st.divider()
            st.markdown("### AI Opportunity Intelligence")
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
                st.write(f"**Sales angle:** {ai_result.get('sales_angle', '')}")

                services = ai_result.get("recommended_services") or []
                if services:
                    st.write("**Recommended systems**")
                    st.markdown("\n".join(f"- {service}" for service in services))

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

            st.divider()
            st.markdown("### Company Research")
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
            st.markdown("### Sales Tracking")
            status_options = [
                "New", "Researching", "Ready to Contact", "Contacted",
                "Follow-Up", "Site Visit", "Quote Sent", "Won", "Lost"
            ]
            current_status = str(row.get("status", "New") or "New")
            if current_status not in status_options:
                status_options.insert(0, current_status)
            with st.form(f"tracking-{permit_no}"):
                status = st.selectbox("Status", status_options, index=status_options.index(current_status))
                assigned_to = st.text_input("Assigned to", value=clean_text(row.get("assigned_to", "")))
                company = st.text_input("Company / owner", value=clean_text(row.get("company", "")))
                phone = st.text_input("Phone", value=clean_text(row.get("phone", "")))
                email = st.text_input("Email", value=clean_text(row.get("email", "")))
                next_follow_up = st.text_input(
                    "Next follow-up (YYYY-MM-DD)",
                    value=clean_text(row.get("next_follow_up", ""))
                )
                notes = st.text_area("Notes", value=clean_text(row.get("notes", "")), height=120)
                saved = st.form_submit_button("Save lead updates", use_container_width=True)
            if saved:
                save_tracking(
                    permit_no,
                    {
                        "status": status,
                        "assigned_to": assigned_to,
                        "company": company,
                        "phone": phone,
                        "email": email,
                        "next_follow_up": next_follow_up,
                        "notes": notes,
                    },
                )
                st.success("Lead tracking saved locally.")
                st.rerun()

            st.divider()
            st.markdown("### Jobber Actions")
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

            st.divider()
            st.markdown("### Confluence Actions")
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

with tab2:
    st.subheader("Permit Map")
    if {"latitude", "longitude"}.issubset(filtered.columns):
        map_df = filtered.dropna(subset=["latitude", "longitude"]).copy()
        if len(map_df):
            map_df = map_df.rename(columns={"latitude": "lat", "longitude": "lon"})
            st.map(map_df[["lat", "lon"]], use_container_width=True)
            st.caption(f"Showing {len(map_df):,} mapped permits.")
        else:
            st.info("The current permits do not include usable latitude/longitude values.")
    else:
        st.info("Latitude and longitude are not included in the current report.")

with tab3:
    st.subheader("Pipeline by Status")
    pipeline_status = (
        filtered.groupby("status", dropna=False)
        .agg(leads=("permit_number", "count"), reported_value=("reported_cost", "sum"))
        .reset_index()
        .sort_values("reported_value", ascending=False)
    )
    pipeline_status["reported_value"] = pipeline_status["reported_value"].fillna(0)
    st.bar_chart(pipeline_status.set_index("status")["leads"])
    display_pipeline = pipeline_status.copy()
    display_pipeline["reported_value"] = display_pipeline["reported_value"].map(money)
    st.dataframe(display_pipeline, use_container_width=True, hide_index=True)

st.divider()
st.caption(
    f"Data source: {CSV_PATH.name} • Local tracking database: {DB_PATH.name} • "
    f"Last dashboard load: {datetime.now().strftime('%Y-%m-%d %I:%M %p')}"
)
