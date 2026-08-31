
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

try:
    import streamlit as st
except ImportError:
    st = None


# Single source of truth for ChaproNet's service catalog. The AI's
# recommended_services always come from this exact list, and ChaproNet
# Experience records (dashboard_pages/experience.py) draw services_performed
# from the same list, so work-experience matching can compare them as exact
# strings instead of guessing at fuzzy text similarity.
CHAPRONET_SERVICES = [
    "CCTV / surveillance",
    "Access control",
    "Video intercoms",
    "Structured cabling",
    "Cat5e/Cat6 data cabling",
    "Commercial Wi-Fi",
    "Networking",
    "PoE infrastructure",
    "Audio/visual systems",
    "TV/display installation",
]


class AIIntelligenceError(RuntimeError):
    pass


class AIIntelligenceClient:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        load_dotenv(self.project_root / ".env", override=False)

        def get_setting(name: str, default: str = "") -> str:
            if st is not None:
                try:
                    value = st.secrets.get(name)
                    if value:
                        return str(value)
                except Exception:
                    pass
            return os.getenv(name, default)

        self.api_key = get_setting("OPENAI_API_KEY").strip()
        self.model = get_setting("OPENAI_MODEL", "gpt-4.1-mini").strip()

        if not self.api_key:
            raise AIIntelligenceError(
                "OPENAI_API_KEY is missing from .env. Add a project API key before using AI analysis."
            )

        self.client = OpenAI(api_key=self.api_key)

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0.0

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
                raise AIIntelligenceError("The AI response did not contain valid JSON.")
            data = json.loads(match.group(0))

        if not isinstance(data, dict):
            raise AIIntelligenceError("The AI response was not a JSON object.")
        return data

    CONTACT_TYPES = ("Owner", "General Contractor", "Developer", "Property Manager", "Other")

    @staticmethod
    def _validate(data: dict[str, Any]) -> dict[str, Any]:
        required = {
            "opportunity_score": 0,
            "confidence": 0,
            "building_type": "Unknown",
            "construction_stage": "Unknown",
            "best_first_contact": "Research needed",
            "best_contact_type": "Other",
            "sales_angle": "",
            "estimated_revenue_low": 0,
            "estimated_revenue_high": 0,
            "recommended_services": [],
            "next_actions": [],
            "risks": [],
        }
        result = {**required, **data}

        for field in ["opportunity_score", "confidence"]:
            try:
                result[field] = max(0, min(100, int(result[field])))
            except Exception:
                result[field] = 0

        for field in ["estimated_revenue_low", "estimated_revenue_high"]:
            try:
                result[field] = max(0, int(float(result[field])))
            except Exception:
                result[field] = 0

        if result["estimated_revenue_high"] < result["estimated_revenue_low"]:
            result["estimated_revenue_low"], result["estimated_revenue_high"] = (
                result["estimated_revenue_high"],
                result["estimated_revenue_low"],
            )

        for field in ["recommended_services", "next_actions", "risks"]:
            value = result.get(field)
            if not isinstance(value, list):
                value = [str(value)] if value else []
            result[field] = [str(item).strip() for item in value if str(item).strip()][:8]

        if str(result.get("best_contact_type")) not in AIIntelligenceClient.CONTACT_TYPES:
            result["best_contact_type"] = "Other"

        return result

    def analyze_lead(
        self,
        *,
        permit_number: str,
        address: str,
        permit_type: str,
        description: str,
        reported_cost: Any,
        existing_score: Any,
        recommended_services: str,
        permit_contacts: str,
    ) -> dict[str, Any]:
        construction_cost = self._number(reported_cost)
        services_list = "\n".join(f"- {service}" for service in CHAPRONET_SERVICES)

        instructions = f"""
You are a commercial low-voltage sales engineer for ChaproNet, a Chicago security
and technology integrator. Analyze public building-permit information and produce
a conservative sales-opportunity assessment (the "Lead Score" for this permit).

ChaproNet's services -- only recommend from this exact list, and only the ones
that plausibly apply to this specific permit's description and building type:
{services_list}

Weight the opportunity_score higher for project types most likely to need this
work: commercial renovations, new construction, restaurants, retail, offices,
multifamily/apartment buildings, and hospitality. Weight it lower for projects
unlikely to need low-voltage systems (e.g. pure roofing, tuckpointing, signage-only,
minor residential repairs) even if the dollar value is high.

Based on the permit_contacts text (which may label OWNER, CONTRACTOR, ARCHITECT,
EXPEDITOR, etc.), classify best_contact_type as exactly one of: Owner,
General Contractor, Developer, Property Manager, Other. This is a role
classification only -- never invent a specific person's name, phone, or email.

Do not invent owner names, contractor names, contact details, building size, or
equipment quantities when they are not provided. Distinguish facts from
assumptions. Revenue estimates are preliminary sales ranges, not quotations.

Return only one valid JSON object with these exact fields:
opportunity_score: integer 0-100 (this is the Lead Score)
confidence: integer 0-100
building_type: string
construction_stage: string
best_first_contact: string (a short description, e.g. "General Contractor listed on the permit")
best_contact_type: one of Owner, General Contractor, Developer, Property Manager, Other
sales_angle: string
estimated_revenue_low: integer
estimated_revenue_high: integer
recommended_services: array of strings, each exactly one of the ChaproNet services listed above
next_actions: array of concise strings
risks: array of concise strings
"""

        lead_input = {
            "permit_number": permit_number,
            "address": address,
            "permit_type": permit_type,
            "description": description,
            "reported_construction_cost": construction_cost,
            "existing_rule_score": self._number(existing_score),
            "existing_recommended_services": recommended_services,
            "published_permit_contacts": permit_contacts,
        }

        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=json.dumps(
                    lead_input,
                    ensure_ascii=False,
                    default=lambda value: value.item()
                    if hasattr(value, "item")
                    else str(value),
                ),
                max_output_tokens=1200,
                store=False,
            )
        except Exception as exc:
            raise AIIntelligenceError(str(exc)) from exc

        output_text = getattr(response, "output_text", "") or ""
        return self._validate(self._extract_json(output_text))
