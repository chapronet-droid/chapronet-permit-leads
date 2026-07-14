from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from openai import OpenAI


class CompanyResearchError(RuntimeError):
    pass


def clean_company_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def extract_company_candidates(permit_contacts: str) -> dict[str, str]:
    """Best-effort parsing of labeled company names from Chicago permit contacts."""
    text = clean_company_name(permit_contacts)
    if not text:
        return {}

    labels = [
        ("Owner", r"(?:OWNER OCCUPIED|OWNER)"),
        ("General Contractor", r"(?:CONTRACTOR-GENERAL|GENERAL CONTRACTOR|CONTRACTOR)"),
        ("Electrical Contractor", r"(?:CONTRACTOR-ELECTRICAL|ELECTRICAL CONTRACTOR)"),
        ("Architect", r"ARCHITECT"),
        ("Expediter", r"EXPEDITOR"),
    ]
    label_pattern = "|".join(f"(?P<L{i}>{pattern})" for i, (_, pattern) in enumerate(labels))
    matches = list(re.finditer(rf"(?:^|\|\s*)({label_pattern})\s*:\s*", text, flags=re.I))
    results: dict[str, str] = {}

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[start:end].strip(" |,;")
        matched_label = ""
        for i, (friendly, _) in enumerate(labels):
            if match.groupdict().get(f"L{i}"):
                matched_label = friendly
                break
        if matched_label and value:
            results[matched_label] = value

    return results


class CompanyResearchClient:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.state_dir = self.project_root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "company_research.db"

        load_dotenv(self.project_root / ".env", override=False)
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv(
            "OPENAI_RESEARCH_MODEL",
            os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        ).strip()
        self.cache_days = int(os.getenv("COMPANY_RESEARCH_CACHE_DAYS", "30") or 30)

        if not self.api_key:
            raise CompanyResearchError(
                "OPENAI_API_KEY is missing from .env."
            )

        self.client = OpenAI(api_key=self.api_key)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS company_research (
                    cache_key TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    location_context TEXT DEFAULT '',
                    result_json TEXT NOT NULL,
                    researched_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _cache_key(company_name: str, role: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")
        role_key = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-")
        return f"{role_key}:{normalized}"

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        value = (text or "").strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*", "", value)
            value = re.sub(r"\s*```$", "", value)

        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", value, re.DOTALL)
            if not match:
                raise CompanyResearchError(
                    "The research response did not contain valid JSON."
                )
            data = json.loads(match.group(0))

        if not isinstance(data, dict):
            raise CompanyResearchError("The research response was not a JSON object.")
        return data

    @staticmethod
    def _validate(data: dict[str, Any], company_name: str, role: str) -> dict[str, Any]:
        defaults = {
            "company_name": company_name,
            "role": role,
            "identity_confidence": 0,
            "website": "",
            "phone": "",
            "email": "",
            "headquarters": "",
            "chicago_presence": "Unknown",
            "industry": "",
            "founded": "",
            "employee_range": "",
            "revenue_range": "",
            "summary": "",
            "decision_maker_roles": [],
            "recent_projects": [],
            "sales_strategy": "",
            "recommended_next_actions": [],
            "sources": [],
            "warnings": [],
        }
        result = {**defaults, **data}
        result["company_name"] = clean_company_name(result.get("company_name")) or company_name
        result["role"] = clean_company_name(result.get("role")) or role

        try:
            result["identity_confidence"] = max(
                0, min(100, int(result.get("identity_confidence", 0)))
            )
        except Exception:
            result["identity_confidence"] = 0

        for field in [
            "decision_maker_roles",
            "recent_projects",
            "recommended_next_actions",
            "sources",
            "warnings",
        ]:
            value = result.get(field)
            if not isinstance(value, list):
                value = [value] if value else []
            cleaned = []
            for item in value:
                if isinstance(item, dict):
                    cleaned.append(item)
                elif str(item).strip():
                    cleaned.append(str(item).strip())
            result[field] = cleaned[:10]

        valid_sources = []
        for source in result["sources"]:
            if isinstance(source, dict):
                title = clean_company_name(source.get("title"))
                url = clean_company_name(source.get("url"))
            else:
                title = ""
                url = clean_company_name(source)
            if url.startswith(("http://", "https://")):
                valid_sources.append(
                    {
                        "title": title or urlparse(url).netloc,
                        "url": url,
                    }
                )
        result["sources"] = valid_sources[:8]
        return result

    def get_cached(self, company_name: str, role: str) -> dict[str, Any] | None:
        key = self._cache_key(company_name, role)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT result_json, researched_at FROM company_research WHERE cache_key=?",
                (key,),
            ).fetchone()
        if not row:
            return None

        try:
            result = json.loads(row["result_json"])
            researched_at = datetime.fromisoformat(row["researched_at"])
        except Exception:
            return None

        if researched_at.tzinfo is None:
            researched_at = researched_at.replace(tzinfo=timezone.utc)

        result["_researched_at"] = researched_at.isoformat()
        result["_is_stale"] = (
            datetime.now(timezone.utc) - researched_at
            > timedelta(days=self.cache_days)
        )
        return result

    def save_cached(
        self,
        company_name: str,
        role: str,
        location_context: str,
        result: dict[str, Any],
    ) -> None:
        key = self._cache_key(company_name, role)
        researched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO company_research (
                    cache_key, company_name, role, location_context,
                    result_json, researched_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    company_name=excluded.company_name,
                    role=excluded.role,
                    location_context=excluded.location_context,
                    result_json=excluded.result_json,
                    researched_at=excluded.researched_at
                """,
                (
                    key,
                    company_name,
                    role,
                    location_context,
                    json.dumps(result, ensure_ascii=False),
                    researched_at,
                ),
            )
            conn.commit()

    def research_company(
        self,
        *,
        company_name: str,
        role: str,
        address: str = "",
        permit_number: str = "",
        permit_type: str = "",
        work_description: str = "",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        company_name = clean_company_name(company_name)
        role = clean_company_name(role) or "Company"

        if not company_name:
            raise CompanyResearchError("Enter a company name before researching.")

        if not force_refresh:
            cached = self.get_cached(company_name, role)
            if cached and not cached.get("_is_stale"):
                cached["_from_cache"] = True
                return cached

        instructions = """
You are a commercial construction sales researcher for ChaproNet, a Chicago
low-voltage, security, networking, access-control, intercom, CCTV, structured
cabling, Wi-Fi, and commercial A/V contractor.

Use live web search to identify and research the exact company supplied by the
user. Prefer official company websites, Illinois/Chicago government sources,
credible business publications, and reputable project announcements.

Important accuracy rules:
- Do not merge similarly named companies.
- If identity is uncertain, lower identity_confidence and explain the ambiguity.
- Do not invent phone numbers, emails, executives, revenue, employee counts,
  project history, or office locations.
- Only include an email address if it is explicitly published on the
  company's own website or another credible source (e.g. a general
  info@/sales@/contact address, or a named contact's business email
  listed publicly). Never guess or pattern-generate an email address
  (such as firstname.lastname@domain) that you did not actually find
  published. Leave email blank rather than guess.
- Revenue and employee counts may be ranges and should be labeled estimates.
- Only include public business contact information.
- Sources must be real URLs that support the profile.
- Return only one valid JSON object, with no markdown.

Return these exact fields:
company_name: string
role: string
identity_confidence: integer 0-100
website: string
phone: string
email: string
headquarters: string
chicago_presence: string
industry: string
founded: string
employee_range: string
revenue_range: string
summary: string
decision_maker_roles: array of strings
recent_projects: array of strings
sales_strategy: string
recommended_next_actions: array of strings
sources: array of objects with title and url
warnings: array of strings
"""

        research_input = {
            "company_name": company_name,
            "permit_role": role,
            "project_address": clean_company_name(address),
            "permit_number": clean_company_name(permit_number),
            "permit_type": clean_company_name(permit_type),
            "work_description": clean_company_name(work_description),
            "market": "Chicago, Illinois",
        }

        try:
            response = self.client.responses.create(
                model=self.model,
                tools=[
                    {
                        "type": "web_search",
                        "search_context_size": "medium",
                        "user_location": {
                            "type": "approximate",
                            "country": "US",
                            "city": "Chicago",
                            "region": "Illinois",
                        },
                    }
                ],
                tool_choice="required",
                instructions=instructions,
                input=json.dumps(
                    research_input,
                    ensure_ascii=False,
                    default=lambda value: value.item()
                    if hasattr(value, "item")
                    else str(value),
                ),
                max_output_tokens=2200,
                store=False,
            )
        except Exception as exc:
            raise CompanyResearchError(str(exc)) from exc

        result = self._validate(
            self._extract_json(getattr(response, "output_text", "") or ""),
            company_name,
            role,
        )
        self.save_cached(company_name, role, address, result)
        result["_researched_at"] = datetime.now(timezone.utc).isoformat()
        result["_from_cache"] = False
        result["_is_stale"] = False
        return result

    def clear_cached(self, company_name: str, role: str) -> None:
        key = self._cache_key(company_name, role)
        with self._connect() as conn:
            conn.execute("DELETE FROM company_research WHERE cache_key=?", (key,))
            conn.commit()
