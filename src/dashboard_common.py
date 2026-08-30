"""Shared data access, styling, and formatting helpers for every dashboard page.

All functions in this module that existed in the original single-file
dashboard.py (db, load_tracking, save_tracking, load_leads, money, clean_text,
confluence_page_id_from_url, run_permit_refresh) are unchanged logic-wise --
only moved here so every page can share one data layer.
"""

from __future__ import annotations

import html
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"
STATE_DIR = PROJECT_ROOT / "state"
DB_PATH = STATE_DIR / "dashboard.db"
CSV_PATH = OUTPUT_DIR / "chapronet_permit_leads.csv"
TOP_CSV_PATH = OUTPUT_DIR / "chapronet_top_leads.csv"
SAVED_SEARCHES_PATH = STATE_DIR / "saved_searches.json"

STATE_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Design tokens -- single source of truth for the color palette.
# ---------------------------------------------------------------------------
COLORS = {
    "navy": "#0B1220",
    "navy_soft": "#111C33",
    "navy_border": "#22314F",
    "blue": "#2563EB",
    "blue_dark": "#1D4ED8",
    "blue_soft": "#DBEAFE",
    "green": "#16A34A",
    "green_soft": "#DCFCE7",
    "amber": "#D97706",
    "amber_soft": "#FEF3C7",
    "red": "#DC2626",
    "red_soft": "#FEE2E2",
    "slate": "#64748B",
    "slate_soft": "#F1F5F9",
    "border": "#E2E8F0",
    "card": "#FFFFFF",
    "bg": "#F8FAFC",
    "ink": "#0F172A",
}

PAGE_ICONS = {
    "Dashboard": "🏠",
    "Permit Search": "🔍",
    "New Permits": "🆕",
    "Map View": "🗺️",
    "Leads": "🎯",
    "Saved Permits": "⭐",
    "Contractors": "👷",
    "Analytics": "📊",
    "Settings": "⚙️",
}

# Populated once by the entrypoint (dashboard.py) right after creating the
# st.Page objects, so any page can call switch_page("Permit Search") without
# needing to import the entrypoint (which would create a circular import).
PAGE_REGISTRY: dict[str, Any] = {}


def register_pages(pages: dict[str, Any]) -> None:
    PAGE_REGISTRY.update(pages)


def switch_page(title: str) -> None:
    target = PAGE_REGISTRY.get(title)
    if target is None:
        st.error(f"Unknown page: {title}")
        return
    st.switch_page(target)


# ---------------------------------------------------------------------------
# Data layer (unchanged from the original dashboard.py)
# ---------------------------------------------------------------------------
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
    script_path = PROJECT_ROOT / "src" / "permit_leads.py"
    if not script_path.exists():
        return False, "src/permit_leads.py was not found."
    try:
        completed = subprocess.run(
            [sys.executable, str(script_path), "--config", str(PROJECT_ROOT / "config.yaml")],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        return completed.returncode == 0, output[-6000:]
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Saved searches (new, additive -- local JSON file, same pattern as the
# app's other local state files like seen_permits.json).
# ---------------------------------------------------------------------------
def load_saved_searches() -> dict[str, dict[str, Any]]:
    if not SAVED_SEARCHES_PATH.exists():
        return {}
    try:
        return json.loads(SAVED_SEARCHES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_search(name: str, criteria: dict[str, Any]) -> None:
    searches = load_saved_searches()
    searches[name] = criteria
    SAVED_SEARCHES_PATH.write_text(json.dumps(searches, indent=2, default=str), encoding="utf-8")


def delete_saved_search(name: str) -> None:
    searches = load_saved_searches()
    searches.pop(name, None)
    SAVED_SEARCHES_PATH.write_text(json.dumps(searches, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Global styling
# ---------------------------------------------------------------------------
def inject_global_css() -> None:
    st.markdown(
        f"""
        <style>
          .block-container {{padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1400px;}}

          /* ---- Sidebar: dark navy SaaS nav ---- */
          [data-testid="stSidebar"] {{
            background-color: {COLORS['navy']};
            border-right: 1px solid {COLORS['navy_border']};
          }}
          [data-testid="stSidebar"] * {{
            color: #E2E8F0 !important;
          }}
          [data-testid="stSidebar"] [data-testid="stSidebarNav"] {{
            padding-top: 0.5rem;
          }}
          [data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {{
            border-radius: 8px;
            margin: 2px 8px;
            transition: background-color 0.15s ease;
          }}
          [data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {{
            background-color: {COLORS['navy_soft']};
          }}
          [data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {{
            background-color: {COLORS['blue']};
          }}
          [data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] * {{
            color: #FFFFFF !important;
            font-weight: 600;
          }}
          [data-testid="stSidebar"] hr {{
            border-color: {COLORS['navy_border']};
          }}
          [data-testid="stSidebar"] .stButton button {{
            background-color: {COLORS['navy_soft']};
            border: 1px solid {COLORS['navy_border']};
            color: #E2E8F0 !important;
          }}
          [data-testid="stSidebar"] .stButton button:hover {{
            border-color: {COLORS['blue']};
            color: #FFFFFF !important;
          }}
          [data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea {{
            color: {COLORS['ink']} !important;
          }}

          /* ---- Sidebar brand header ---- */
          .brand-block {{
            display:flex; align-items:center; gap:0.6rem;
            padding: 0.25rem 0 1rem 0; margin-bottom: 0.5rem;
            border-bottom: 1px solid {COLORS['navy_border']};
          }}
          .brand-block .brand-mark {{
            font-size: 1.6rem; line-height: 1;
          }}
          .brand-block .brand-name {{
            font-weight: 700; font-size: 1.05rem; color: #FFFFFF;
          }}
          .brand-block .brand-sub {{
            font-size: 0.72rem; color: #94A3B8;
          }}

          /* ---- Page header ---- */
          .page-header {{
            display:flex; align-items:center; gap:0.6rem; margin-bottom: 0.15rem;
          }}
          .page-header .page-icon {{ font-size: 1.7rem; }}
          .page-header h1 {{ margin: 0; font-size: 1.75rem; font-weight: 700; color: {COLORS['ink']}; }}
          .page-subtitle {{ color: {COLORS['slate']}; margin-bottom: 1.25rem; font-size: 0.95rem; }}

          /* ---- KPI cards ---- */
          .kpi-row {{ display:flex; gap:0.9rem; flex-wrap:wrap; margin-bottom: 1.5rem; }}
          .kpi-card {{
            flex: 1 1 150px; background: {COLORS['card']};
            border: 1px solid {COLORS['border']}; border-radius: 14px;
            padding: 1rem 1.1rem; box-shadow: 0 1px 2px rgba(15,23,42,0.04);
            border-top: 3px solid var(--accent, {COLORS['blue']});
            transition: box-shadow 0.15s ease, transform 0.15s ease;
          }}
          .kpi-card:hover {{
            box-shadow: 0 6px 16px rgba(15,23,42,0.08);
            transform: translateY(-1px);
          }}
          .kpi-icon {{
            font-size: 1.3rem; margin-bottom: 0.35rem; display:inline-block;
          }}
          .kpi-value {{
            font-size: 1.6rem; font-weight: 700; color: {COLORS['ink']}; line-height:1.1;
          }}
          .kpi-label {{
            font-size: 0.8rem; color: {COLORS['slate']}; margin-top: 0.2rem;
          }}

          /* ---- Generic content card (native bordered st.container) ---- */
          [data-testid="stVerticalBlockBorderWrapper"] {{
            border-radius: 14px !important;
          }}
          div[data-testid="stVerticalBlockBorderWrapper"] > div {{
            border-radius: 14px !important;
          }}
          [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{
            box-shadow: 0 1px 2px rgba(15,23,42,0.04);
          }}
          .app-card h3, .app-card h4 {{ margin-top:0; }}

          /* ---- Badges ---- */
          .badge {{
            display:inline-block; padding:0.18rem 0.6rem; border-radius:999px;
            font-size: 0.76rem; font-weight:600; letter-spacing:0.01em;
            border:1px solid transparent; white-space: nowrap;
          }}
          .badge-blue {{ background:{COLORS['blue_soft']}; color:{COLORS['blue_dark']}; }}
          .badge-green {{ background:{COLORS['green_soft']}; color:{COLORS['green']}; }}
          .badge-amber {{ background:{COLORS['amber_soft']}; color:{COLORS['amber']}; }}
          .badge-red {{ background:{COLORS['red_soft']}; color:{COLORS['red']}; }}
          .badge-slate {{ background:{COLORS['slate_soft']}; color:{COLORS['slate']}; }}

          .tag-row {{ display:flex; flex-wrap:wrap; gap:0.35rem; margin: 0.4rem 0 0.2rem 0; }}

          .muted {{ color:{COLORS['slate']}; }}

          /* ---- Dataframe polish ---- */
          [data-testid="stDataFrame"] {{
            border: 1px solid {COLORS['border']}; border-radius: 12px; overflow:hidden;
          }}

          /* ---- Buttons ---- */
          .stButton button, .stFormSubmitButton button, .stLinkButton a {{
            border-radius: 8px !important;
          }}
          .stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] {{
            background-color: {COLORS['blue']} !important;
            border-color: {COLORS['blue']} !important;
          }}
          .stButton button[kind="primary"]:hover, .stFormSubmitButton button[kind="primary"]:hover {{
            background-color: {COLORS['blue_dark']} !important;
          }}

          /* ---- Empty state ---- */
          .empty-state {{
            text-align:center; padding: 3rem 1rem; color:{COLORS['slate']};
            border: 1px dashed {COLORS['border']}; border-radius: 14px; background: {COLORS['card']};
          }}
          .empty-state .empty-icon {{ font-size: 2.2rem; margin-bottom: 0.5rem; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_brand() -> None:
    st.markdown(
        """
        <div class="brand-block">
          <div class="brand-mark">📡</div>
          <div>
            <div class="brand-name">ChaproNet</div>
            <div class="brand-sub">Lead Intelligence</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = "") -> None:
    icon = PAGE_ICONS.get(title, "📄")
    st.markdown(
        f"""
        <div class="page-header"><span class="page-icon">{icon}</span><h1>{html.escape(title)}</h1></div>
        """,
        unsafe_allow_html=True,
    )
    if subtitle:
        st.markdown(f'<div class="page-subtitle">{html.escape(subtitle)}</div>', unsafe_allow_html=True)


def empty_state(icon: str, title: str, detail: str = "") -> None:
    st.markdown(
        f"""
        <div class="empty-state">
          <div class="empty-icon">{icon}</div>
          <div style="font-weight:600; color:{COLORS['ink']};">{html.escape(title)}</div>
          <div class="muted" style="margin-top:0.25rem;">{html.escape(detail)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Badges / tags
# ---------------------------------------------------------------------------
def _badge(label: str, color: str) -> str:
    return f'<span class="badge badge-{color}">{html.escape(str(label))}</span>'


def priority_badge(priority: str) -> str:
    priority = clean_text(priority) or "Research"
    mapping = {
        "Immediate": ("🔥 Immediate", "red"),
        "Hot": ("🔥 Hot", "amber"),
        "Warm": ("Warm", "amber"),
        "Research": ("Research", "slate"),
    }
    label, color = mapping.get(priority, (priority, "slate"))
    return _badge(label, color)


def crm_status_badge(status: str) -> str:
    status = clean_text(status) or "New"
    won_lost = {"Won": "green", "Lost": "red"}
    active = {"Contacted", "Follow-Up", "Site Visit", "Quote Sent", "Ready to Contact"}
    if status in won_lost:
        color = won_lost[status]
    elif status in active:
        color = "blue"
    elif status == "New":
        color = "slate"
    else:
        color = "amber"
    return _badge(status, color)


def permit_status_badge(permit_status: str) -> str:
    value = clean_text(permit_status) or "Unknown"
    mapping = {
        "ACTIVE": "green",
        "COMPLETE": "blue",
        "ISSUED": "green",
        "CANCELLED": "red",
        "DENIED": "red",
        "EXPIRED": "red",
        "PENDING": "amber",
    }
    color = mapping.get(value.upper(), "slate")
    return _badge(value, color)


def priority_emoji_label(priority: str) -> str:
    """Text-safe colored label for st.dataframe, which does not render pandas
    Styler background colors in this Streamlit version -- verified empirically.
    """
    priority = clean_text(priority) or "Research"
    mapping = {
        "Immediate": "🔴 Immediate",
        "Hot": "🟠 Hot",
        "Warm": "🟡 Warm",
        "Research": "⚪ Research",
    }
    return mapping.get(priority, priority)


def permit_status_emoji_label(permit_status: str) -> str:
    value = clean_text(permit_status) or "Unknown"
    mapping = {
        "ACTIVE": "🟢 ACTIVE",
        "COMPLETE": "🔵 COMPLETE",
        "ISSUED": "🟢 ISSUED",
        "CANCELLED": "🔴 CANCELLED",
        "DENIED": "🔴 DENIED",
        "EXPIRED": "🔴 EXPIRED",
        "PENDING": "🟡 PENDING",
    }
    return mapping.get(value.upper(), f"⚪ {value}")


def crm_status_emoji_label(status: str) -> str:
    status = clean_text(status) or "New"
    won_lost = {"Won": "🟢", "Lost": "🔴"}
    active = {"Contacted", "Follow-Up", "Site Visit", "Quote Sent", "Ready to Contact"}
    if status in won_lost:
        dot = won_lost[status]
    elif status in active:
        dot = "🔵"
    elif status == "New":
        dot = "⚪"
    else:
        dot = "🟡"
    return f"{dot} {status}"


def compute_lead_tags(row: pd.Series) -> list[tuple[str, str]]:
    """Return a list of (label, color) tags describing why a permit is a good lead.

    Purely derived from data already present on the row -- no new inputs required.
    """
    tags: list[tuple[str, str]] = []
    priority = clean_text(row.get("priority", ""))
    if priority in {"Hot", "Immediate"}:
        tags.append(("🔥 Hot Lead", "red" if priority == "Immediate" else "amber"))

    try:
        cost = float(row.get("reported_cost") or 0)
    except Exception:
        cost = 0.0
    if cost >= 500_000:
        tags.append(("High Project Value", "green"))

    issue_date = row.get("issue_date")
    try:
        if pd.notna(issue_date) and (pd.Timestamp.now().normalize() - pd.Timestamp(issue_date).normalize()).days <= 7:
            tags.append(("Recently Issued", "blue"))
    except Exception:
        pass

    contacts = clean_text(row.get("permit_contacts", "")).upper()
    company = clean_text(row.get("company", ""))
    if "CONTRACTOR" not in contacts and not company:
        tags.append(("No Contractor Listed", "slate"))

    permit_type = clean_text(row.get("permit_type", "")).upper()
    work_type = clean_text(row.get("work_type", "")).upper()
    combined_type = f"{permit_type} {work_type}"
    if "COMMERCIAL" in combined_type or "COMM" in combined_type:
        tags.append(("Commercial Project", "blue"))
    if "NEW CONSTRUCTION" in combined_type:
        tags.append(("New Construction", "green"))
    if "RENOVATION" in combined_type or "ALTERATION" in combined_type:
        tags.append(("Renovation", "amber"))

    return tags


def render_tags_html(tags: list[tuple[str, str]]) -> str:
    if not tags:
        return ""
    spans = "".join(_badge(label, color) for label, color in tags)
    return f'<div class="tag-row">{spans}</div>'


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------
def kpi_card(column, icon: str, label: str, value: str, accent: str = "blue") -> None:
    accent_hex = COLORS.get(accent, COLORS["blue"])
    with column:
        st.markdown(
            f"""
            <div class="kpi-card" style="--accent: {accent_hex};">
              <div class="kpi-icon">{icon}</div>
              <div class="kpi-value">{html.escape(str(value))}</div>
              <div class="kpi-label">{html.escape(label)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Contractor / owner extraction re-export (kept here so pages have one
# import surface; the parsing logic itself still lives in company_research.py).
# ---------------------------------------------------------------------------
from company_research import extract_company_candidates  # noqa: E402


def build_contractor_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Explode each permit's labeled contacts into one row per (company, role)."""
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        candidates = extract_company_candidates(clean_text(row.get("permit_contacts", "")))
        for role, name in candidates.items():
            name = clean_text(name)
            if not name:
                continue
            records.append(
                {
                    "company_name": name,
                    "role": role,
                    "permit_number": row.get("permit_number", ""),
                    "address": row.get("address", ""),
                    "reported_cost": row.get("reported_cost", 0) or 0,
                    "lead_score": row.get("lead_score", 0) or 0,
                }
            )
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Simple pagination helper shared by table-driven pages
# ---------------------------------------------------------------------------
def paginate(df: pd.DataFrame, state_key: str, page_size: int = 15) -> tuple[pd.DataFrame, int, int]:
    total_rows = len(df)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    page = st.session_state.get(state_key, 1)
    page = max(1, min(page, total_pages))
    st.session_state[state_key] = page

    cols = st.columns([1, 1, 3, 1, 1])
    if cols[0].button("« First", key=f"{state_key}-first", disabled=page <= 1, use_container_width=True):
        st.session_state[state_key] = 1
        st.rerun()
    if cols[1].button("‹ Prev", key=f"{state_key}-prev", disabled=page <= 1, use_container_width=True):
        st.session_state[state_key] = page - 1
        st.rerun()
    cols[2].markdown(
        f"<div style='text-align:center; padding-top:0.4rem;' class='muted'>Page {page} of {total_pages} • {total_rows:,} results</div>",
        unsafe_allow_html=True,
    )
    if cols[3].button("Next ›", key=f"{state_key}-next", disabled=page >= total_pages, use_container_width=True):
        st.session_state[state_key] = page + 1
        st.rerun()
    if cols[4].button("Last »", key=f"{state_key}-last", disabled=page >= total_pages, use_container_width=True):
        st.session_state[state_key] = total_pages
        st.rerun()

    start = (page - 1) * page_size
    end = start + page_size
    return df.iloc[start:end], page, total_pages
