"""AI-generated outreach emails for ChaproNet sales leads.

Phase 1: generates a personalized email from permit facts + AI lead analysis.
Phase 2 will pass a matched prior-experience record in via `matched_experience`
so the email can reference real, non-fabricated past work.
"""

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


class OutreachError(RuntimeError):
    pass


class OutreachClient:
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
            raise OutreachError(
                "OPENAI_API_KEY is missing from .env. Add a project API key before generating emails."
            )

        self.client = OpenAI(api_key=self.api_key)

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
                raise OutreachError("The AI response did not contain valid JSON.")
            data = json.loads(match.group(0))
        if not isinstance(data, dict):
            raise OutreachError("The AI response was not a JSON object.")
        return data

    def generate_email(
        self,
        *,
        permit_number: str,
        address: str,
        permit_type: str,
        description: str,
        building_type: str,
        recommended_services: list[str],
        best_contact_type: str,
        contact_name: str = "",
        contact_company: str = "",
        matched_experience: dict[str, Any] | None = None,
        regenerate_note: str = "",
    ) -> dict[str, str]:
        """Return {"subject": str, "body": str}. Never invents a recipient's
        name -- if contact_name is blank, the email opens with a generic,
        professional greeting instead of guessing a name.
        """
        instructions = """
You are writing a short, personal-sounding cold outreach email on behalf of
ChaproNet, a Chicago-based commercial low-voltage, security, and technology
integrator. The recipient is connected to a specific building permit -- write
as if you noticed their project through normal business awareness, not as if
you scraped, monitored, or are tracking permit records. Never mention permits,
public records, or that this address was found through a database.

Rules:
- 80-150 words total (subject line does not count toward this).
- Reference the project naturally (e.g. the type of build-out, the neighborhood
  or building type) without sounding like a form letter.
- Only mention services from the "relevant services" list provided -- do not
  list every ChaproNet capability.
- If a matched_experience example is provided, reference it briefly and
  specifically (e.g. "we recently completed similar camera and access control
  work on a multifamily building in Chicago") -- do NOT invent details beyond
  what is given. If no matched_experience is provided, speak only generally
  about ChaproNet's Chicago low-voltage/security experience without claiming
  a specific past project.
- If contact_name is blank, open with a professional generic greeting (e.g.
  "Hi there," or address the company) -- never invent a person's name.
- Sound like it was personally written by a real salesperson, not a mail merge.
- End with a low-pressure call to action asking for a 10-15 minute call or a
  brief site walkthrough -- not a hard sell.
- Do not use exclamation points more than once. Do not sound like spam.

Return only one valid JSON object with these exact fields:
subject: string, concise and specific (not clickbait)
body: string, the full email body (no subject line inside it), plain text
  with a simple sign-off "Best," followed by "ChaproNet" on its own line
"""

        payload = {
            "permit_number": permit_number,
            "address": address,
            "permit_type": permit_type,
            "description": description,
            "building_type": building_type,
            "relevant_services": recommended_services,
            "best_contact_type": best_contact_type,
            "contact_name": contact_name,
            "contact_company": contact_company,
            "matched_experience": matched_experience,
        }
        if regenerate_note:
            payload["regeneration_instructions"] = regenerate_note

        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=json.dumps(payload, ensure_ascii=False, default=str),
                max_output_tokens=700,
                store=False,
            )
        except Exception as exc:
            raise OutreachError(str(exc)) from exc

        data = self._extract_json(getattr(response, "output_text", "") or "")
        subject = str(data.get("subject", "")).strip() or f"Quick question about {address}"
        body = str(data.get("body", "")).strip()
        if not body:
            raise OutreachError("The AI response did not include an email body.")
        return {"subject": subject, "body": body}
