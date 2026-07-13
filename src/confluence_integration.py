
from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv


class ConfluenceError(RuntimeError):
    pass


class ConfluenceClient:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        load_dotenv(self.project_root / ".env", override=False)

        self.site_url = os.getenv("CONFLUENCE_SITE_URL", "").strip().rstrip("/")
        self.email = os.getenv("CONFLUENCE_EMAIL", "").strip()
        self.api_token = os.getenv("CONFLUENCE_API_TOKEN", "").strip()
        self.space_id = os.getenv("CONFLUENCE_SPACE_ID", "").strip()
        self.space_key = os.getenv("CONFLUENCE_SPACE_KEY", "MFS").strip()
        self.parent_page_id = os.getenv("CONFLUENCE_PARENT_PAGE_ID", "").strip()

        missing = [
            name for name, value in {
                "CONFLUENCE_SITE_URL": self.site_url,
                "CONFLUENCE_EMAIL": self.email,
                "CONFLUENCE_API_TOKEN": self.api_token,
                "CONFLUENCE_PARENT_PAGE_ID": self.parent_page_id,
            }.items() if not value
        ]
        if missing:
            raise ConfluenceError(
                "Add these values to .env:\n" + "\n".join(missing)
            )

        self.session = requests.Session()
        self.session.auth = (self.email, self.api_token)
        self.session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )

    @property
    def api_base(self) -> str:
        return f"{self.site_url}/wiki/api/v2"

    def resolve_space_id(self) -> str:
        if self.space_id:
            return self.space_id
        if not self.space_key:
            raise ConfluenceError(
                "Add CONFLUENCE_SPACE_ID or CONFLUENCE_SPACE_KEY to .env."
            )
        response = self.session.get(
            f"{self.api_base}/spaces",
            params={"keys": self.space_key, "limit": 25},
            timeout=30,
        )
        if response.status_code == 401:
            raise ConfluenceError(
                "Confluence rejected the email/API token."
            )
        if response.status_code == 403:
            raise ConfluenceError(
                "The Atlassian account cannot access the requested Confluence space."
            )
        if not response.ok:
            raise ConfluenceError(
                f"Could not resolve Confluence space key {self.space_key}: "
                f"HTTP {response.status_code} — {response.text[:500]}"
            )
        results = response.json().get("results") or []
        exact = [
            item for item in results
            if str(item.get("key", "")).upper() == self.space_key.upper()
        ]
        if not exact:
            raise ConfluenceError(
                f"No Confluence space was found for key {self.space_key}."
            )
        self.space_id = str(exact[0]["id"])
        return self.space_id

    def test_connection(self) -> str:
        space_id = self.resolve_space_id()
        response = self.session.get(
            f"{self.api_base}/spaces/{space_id}",
            timeout=30,
        )
        if response.status_code == 401:
            raise ConfluenceError(
                "Confluence rejected the email/API token. Create a valid Atlassian API token."
            )
        if response.status_code == 403:
            raise ConfluenceError(
                "The Atlassian account cannot access this Confluence space."
            )
        if not response.ok:
            raise ConfluenceError(
                f"Confluence connection failed: HTTP {response.status_code} — {response.text[:500]}"
            )
        data = response.json()
        return data.get("name") or f"Space {self.space_id}"

    @staticmethod
    def _safe(value: Any) -> str:
        if value is None:
            return ""
        return html.escape(str(value), quote=True)

    @staticmethod
    def _money(value: Any) -> str:
        try:
            return f"${float(value):,.0f}"
        except Exception:
            return "Not published"

    def _link(self, label: str, url: str) -> str:
        if not url:
            return ""
        return f'<a href="{self._safe(url)}">{self._safe(label)}</a>'


    @staticmethod
    def _estimate_opportunity(reported_cost: Any, services: str, permit_type: str) -> tuple[int, int]:
        try:
            construction_cost = max(float(reported_cost or 0), 0)
        except Exception:
            construction_cost = 0

        service_count = max(
            1,
            len([s for s in str(services or "").replace("|", ",").split(",") if s.strip()])
        )
        permit_text = str(permit_type or "").lower()

        base_pct = 0.012
        if any(word in permit_text for word in ["new construction", "renovation", "alteration"]):
            base_pct = 0.018
        if any(word in permit_text for word in ["express", "repair"]):
            base_pct = 0.009

        low = max(2500, int(construction_cost * base_pct))
        low += max(0, service_count - 1) * 1500
        high = max(low + 2500, int(low * 1.9))
        return low, high

    @staticmethod
    def _service_scope(services: str, description: str) -> list[str]:
        text = f"{services} {description}".lower()
        scope = []
        rules = [
            ("CCTV / video surveillance", ["cctv", "camera", "surveillance", "security"]),
            ("Access control", ["access control", "door", "entry", "egress", "lock"]),
            ("Video intercom", ["intercom", "buzzer", "entry"]),
            ("Structured cabling", ["cabling", "cat6", "data", "network", "telecom"]),
            ("Wi-Fi / network infrastructure", ["wifi", "wi-fi", "network", "restaurant", "office"]),
            ("Audio / video", ["audio", "speaker", "video", "restaurant", "assembly"]),
        ]
        for label, words in rules:
            if any(word in text for word in words):
                scope.append(label)
        if not scope:
            scope = ["CCTV / video surveillance", "Structured cabling", "Network infrastructure"]
        return scope[:6]

    def get_page(self, page_id: str) -> dict[str, Any]:
        response = self.session.get(
            f"{self.api_base}/pages/{page_id}",
            params={"body-format": "storage"},
            timeout=30,
        )
        if not response.ok:
            raise ConfluenceError(
                f"Could not read Confluence page {page_id}: "
                f"HTTP {response.status_code} — {response.text[:500]}"
            )
        return response.json()

    def update_lead_page(self, page_id: str, **lead: Any) -> dict[str, str]:
        current = self.get_page(page_id)
        current_version = int(((current.get("version") or {}).get("number") or 1))
        title_address = lead.get("address") or lead.get("permit_number") or "Unknown"
        title = f"Permit Lead – {title_address} – {lead.get('permit_number', '')}".strip()

        payload = {
            "id": str(page_id),
            "status": "current",
            "title": title[:250],
            "body": {
                "representation": "storage",
                "value": self.build_storage_body(**lead),
            },
            "version": {
                "number": current_version + 1,
                "message": "Updated from ChaproNet Lead Intelligence dashboard",
            },
        }

        response = self.session.put(
            f"{self.api_base}/pages/{page_id}",
            json=payload,
            timeout=45,
        )
        if not response.ok:
            raise ConfluenceError(
                f"Page update failed: HTTP {response.status_code} — {response.text[:1000]}"
            )
        data = response.json()
        webui = ((data.get("_links") or {}).get("webui") or "")
        url = urljoin(f"{self.site_url}/wiki/", webui.lstrip("/"))
        if not webui:
            url = f"{self.site_url}/wiki/pages/viewpage.action?pageId={page_id}"
        return {"id": str(page_id), "url": url, "title": data.get("title", title)}

    def build_storage_body(self, **lead: Any) -> str:
        links = [
            self._link("Chicago permit source", lead.get("source_url", "")),
            self._link("Google Maps", lead.get("maps_url", "")),
            self._link("Owner research", lead.get("owner_url", "")),
            self._link("General contractor research", lead.get("gc_url", "")),
            self._link("Open Jobber", lead.get("jobber_url", "")),
        ]
        links = [x for x in links if x]

        services = self._service_scope(
            str(lead.get("recommended_services", "")),
            str(lead.get("description", "")),
        )
        low, high = self._estimate_opportunity(
            lead.get("reported_cost"),
            lead.get("recommended_services", ""),
            lead.get("permit_type", ""),
        )

        service_items = "".join(f"<li>{self._safe(item)}</li>" for item in services)
        link_items = "".join(f"<li>{link}</li>" for link in links)

        return f"""
        <h1>Permit Opportunity Summary</h1>
        <p><strong>Address:</strong> {self._safe(lead.get("address"))}</p>
        <p><strong>Permit number:</strong> {self._safe(lead.get("permit_number"))}</p>
        <p><strong>Issue date:</strong> {self._safe(lead.get("issue_date"))}</p>
        <p><strong>Permit type:</strong> {self._safe(lead.get("permit_type"))}</p>

        <h2>Opportunity Assessment</h2>
        <table>
          <tbody>
            <tr><th>Lead score</th><td>{self._safe(lead.get("lead_score"))}/100</td></tr>
            <tr><th>Priority</th><td>{self._safe(lead.get("priority"))}</td></tr>
            <tr><th>Reported construction cost</th><td>{self._money(lead.get("reported_cost"))}</td></tr>
            <tr><th>Estimated ChaproNet opportunity</th><td>${low:,.0f}–${high:,.0f}</td></tr>
            <tr><th>Recommended services</th><td>{self._safe(lead.get("recommended_services"))}</td></tr>
          </tbody>
        </table>

        <h2>Recommended Preliminary Scope</h2>
        <ul>{service_items}</ul>
        <p><em>This is a preliminary sales-engineering estimate. Confirm quantities and final scope through a site survey.</em></p>

        <h2>Permit Description</h2>
        <p>{self._safe(lead.get("description"))}</p>

        <h2>Published Contacts</h2>
        <p><strong>Permit contacts:</strong> {self._safe(lead.get("permit_contacts")) or "Not published"}</p>
        <p><strong>Company / owner:</strong> {self._safe(lead.get("company")) or "Research needed"}</p>
        <p><strong>Phone:</strong> {self._safe(lead.get("phone")) or "Research needed"}</p>
        <p><strong>Email:</strong> {self._safe(lead.get("email")) or "Research needed"}</p>

        <h2>Sales Strategy</h2>
        <ol>
          <li>Identify the owner, developer, general contractor, architect, and electrical contractor.</li>
          <li>Determine which party controls low-voltage procurement.</li>
          <li>Lead with a commercial site survey and budgetary design consultation.</li>
          <li>Position CCTV, access control, intercom, Wi-Fi, networking, and cabling as one integrated package.</li>
          <li>Create the quote and follow-up sequence in Jobber.</li>
        </ol>

        <h2>Sales Follow-Up</h2>
        <p><strong>Next follow-up:</strong> {self._safe(lead.get("next_follow_up")) or "Not scheduled"}</p>
        <p><strong>Notes:</strong> {self._safe(lead.get("notes")) or "No notes yet"}</p>

        <h2>Research Links</h2>
        <ul>{link_items}</ul>

        <h2>Qualification Checklist</h2>
        <ul>
          <li>Owner or developer confirmed</li>
          <li>General contractor confirmed</li>
          <li>Decision maker identified</li>
          <li>Phone and email verified</li>
          <li>Site survey requested</li>
          <li>Budget range discussed</li>
          <li>Jobber request created</li>
          <li>Proposal follow-up scheduled</li>
        </ul>

        <h2>Document Control</h2>
        <p>Source system: ChaproNet Lead Intelligence</p>
        <p>Permit source: City of Chicago public permit data</p>
        """
    @staticmethod
    def extract_page_id(url: str) -> str:
        text = str(url or "")
        match = re.search(r"/pages/(\d+)", text)
        if match:
            return match.group(1)
        match = re.search(r"[?&]pageId=(\d+)", text)
        return match.group(1) if match else ""

    def create_lead_page(self, **lead: Any) -> dict[str, str]:
        title_address = lead.get("address") or lead.get("permit_number") or "Unknown"
        title = f"Permit Lead – {title_address} – {lead.get('permit_number', '')}".strip()
        payload = {
            "spaceId": self.resolve_space_id(),
            "status": "current",
            "title": title[:250],
            "parentId": self.parent_page_id,
            "body": {
                "representation": "storage",
                "value": self.build_storage_body(**lead),
            },
        }

        response = self.session.post(
            f"{self.api_base}/pages",
            json=payload,
            timeout=45,
        )
        if response.status_code == 401:
            raise ConfluenceError("Confluence rejected the email/API token.")
        if response.status_code == 403:
            raise ConfluenceError(
                "The account does not have permission to create pages under the selected parent."
            )
        if not response.ok:
            raise ConfluenceError(
                f"Page creation failed: HTTP {response.status_code} — {response.text[:1000]}"
            )

        data = response.json()
        page_id = str(data.get("id", ""))
        webui = ((data.get("_links") or {}).get("webui") or "")
        url = urljoin(f"{self.site_url}/wiki/", webui.lstrip("/"))
        if not webui and page_id:
            url = f"{self.site_url}/wiki/pages/viewpage.action?pageId={page_id}"
        return {"id": page_id, "url": url, "title": data.get("title", title)}
