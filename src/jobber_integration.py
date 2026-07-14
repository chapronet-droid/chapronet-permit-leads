from __future__ import annotations

import json
import os
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

try:
    import streamlit as st
except ImportError:
    st = None


AUTH_URL = "https://api.getjobber.com/api/oauth/authorize"
TOKEN_URL = "https://api.getjobber.com/api/oauth/token"
GRAPHQL_URL = "https://api.getjobber.com/api/graphql"


class JobberError(RuntimeError):
    def __init__(self, message: str, details: str = ""):
        super().__init__(message)
        self.details = details


@dataclass
class CallbackResult:
    code: str = ""
    state: str = ""
    error: str = ""


class JobberClient:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.state_dir = self.project_root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.token_path = self.state_dir / "jobber_tokens.json"
        self.oauth_state_path = self.state_dir / "jobber_oauth_state.json"
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

        self.client_id = get_setting("JOBBER_CLIENT_ID")
        self.client_secret = get_setting("JOBBER_CLIENT_SECRET")
        self.redirect_uri = get_setting(
            "JOBBER_REDIRECT_URI",
            "http://localhost:8000/callback",
        )
        self.api_version = get_setting(
            "JOBBER_API_VERSION",
            "2025-04-16",
        ).strip()
        self.refresh_token = get_setting("JOBBER_REFRESH_TOKEN")

        def _read_tokens(self) -> dict[str, Any]:
         if not self.token_path.exists():
            if self.refresh_token:
                return {"refresh_token": self.refresh_token}
            return {}

        try:
            tokens = json.loads(
                self.token_path.read_text(encoding="utf-8")
            )

            if not tokens.get("refresh_token") and self.refresh_token:
                tokens["refresh_token"] = self.refresh_token

            return tokens

        except Exception as exc:
            raise JobberError(
                "Could not read saved Jobber tokens.",
                str(exc),
            ) from exc

    def _save_tokens(self, data: dict[str, Any]) -> None:
        current = self._read_tokens()
        current.update(data)
        current["saved_at"] = int(time.time())
        self.token_path.write_text(json.dumps(current, indent=2), encoding="utf-8")

    def is_connected(self) -> bool:
        tokens = self._read_tokens()
        return bool(tokens.get("access_token") or tokens.get("refresh_token"))

    def start_oauth(self) -> str:
        # Clear any stale callback file from a previous run
        stale_callback = self.state_dir / "jobber_callback.json"
        if stale_callback.exists():
            stale_callback.unlink()

        state = secrets.token_urlsafe(32)
        self.oauth_state_path.write_text(
            json.dumps({"state": state, "created_at": int(time.time())}),
            encoding="utf-8",
        )
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        url = f"{AUTH_URL}?{urlencode(params)}"
        self._start_callback_server()
        webbrowser.open(url)
        return url

    def _start_callback_server(self) -> None:
        parsed = urlparse(self.redirect_uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8000
        expected_path = parsed.path or "/callback"
        result_file = self.state_dir / "jobber_callback.json"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner_self):
                parsed_req = urlparse(inner_self.path)
                if parsed_req.path != expected_path:
                    inner_self.send_response(404)
                    inner_self.end_headers()
                    return
                query = parse_qs(parsed_req.query)
                payload = {
                    "code": query.get("code", [""])[0],
                    "state": query.get("state", [""])[0],
                    "error": query.get("error", [""])[0],
                }
                result_file.write_text(json.dumps(payload), encoding="utf-8")
                body = (
                    "<html><body style='font-family:Arial;padding:40px'>"
                    "<h2>Jobber authorization received</h2>"
                    "<p>Return to the ChaproNet dashboard and click "
                    "<b>Finish connection after approval</b>.</p>"
                    "</body></html>"
                ).encode("utf-8")
                inner_self.send_response(200)
                inner_self.send_header("Content-Type", "text/html")
                inner_self.send_header("Content-Length", str(len(body)))
                inner_self.end_headers()
                inner_self.wfile.write(body)

            def log_message(inner_self, format, *args):
                return

        def serve():
            try:
                server = HTTPServer((host, port), Handler)
                server.timeout = 180
                start = time.time()
                while time.time() - start < 180 and not result_file.exists():
                    server.handle_request()
                server.server_close()
            except OSError:
                # Another callback server may already be waiting.
                pass

        threading.Thread(target=serve, daemon=True).start()

    def finish_oauth(self) -> None:
        callback_path = self.state_dir / "jobber_callback.json"
        if not callback_path.exists():
            raise JobberError(
                "No authorization callback was received yet.",
                "Click Start Jobber connection, approve access in Jobber, then return here.",
            )
        callback = json.loads(callback_path.read_text(encoding="utf-8"))
        expected = json.loads(self.oauth_state_path.read_text(encoding="utf-8"))

        if callback.get("error"):
            raise JobberError("Jobber authorization was denied.", callback["error"])
        if not callback.get("code"):
            raise JobberError("The callback did not contain an authorization code.")
        if callback.get("state") != expected.get("state"):
            raise JobberError("OAuth state verification failed. Start the connection again.")

        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "authorization_code",
                "code": callback["code"],
                "redirect_uri": self.redirect_uri,
            },
            timeout=30,
        )
        if not response.ok:
            raise JobberError(
                "Jobber token exchange failed.",
                f"HTTP {response.status_code}: {response.text}",
            )
        self._save_tokens(response.json())
        callback_path.unlink(missing_ok=True)
        self.oauth_state_path.unlink(missing_ok=True)

    def _refresh(self) -> str:
        tokens = self._read_tokens()
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise JobberError("No Jobber refresh token is saved. Reconnect Jobber.")
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        if not response.ok:
            raise JobberError(
                "Jobber token refresh failed. Reconnect the app.",
                f"HTTP {response.status_code}: {response.text}",
            )
        payload = response.json()
        self._save_tokens(payload)
        return payload["access_token"]

    def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        tokens = self._read_tokens()
        access_token = tokens.get("access_token")
        if not access_token:
            access_token = self._refresh()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-JOBBER-GRAPHQL-VERSION": self.api_version,
        }
        response = requests.post(
            GRAPHQL_URL,
            headers=headers,
            json={"query": query, "variables": variables or {}},
            timeout=45,
        )
        if response.status_code == 401:
            access_token = self._refresh()
            headers["Authorization"] = f"Bearer {access_token}"
            response = requests.post(
                GRAPHQL_URL,
                headers=headers,
                json={"query": query, "variables": variables or {}},
                timeout=45,
            )
        if not response.ok:
            raise JobberError(
                "Jobber API request failed.",
                f"HTTP {response.status_code}: {response.text}",
            )
        payload = response.json()
        if payload.get("errors"):
            raise JobberError(
                "Jobber rejected the GraphQL operation.",
                json.dumps(payload["errors"], indent=2),
            )
        return payload.get("data", {})

    def get_account(self) -> dict[str, Any]:
        data = self._graphql("query AccountName { account { id name } }")
        return data.get("account") or {}

    def schema_diagnostics(self) -> dict[str, Any]:
        """Return relevant input fields without exposing credentials or tokens."""
        query = """
        query ChaproNetSchemaDiagnostics {
          clientInput: __type(name: "ClientCreateInput") {
            inputFields { name }
          }
          requestInput: __type(name: "RequestCreateInput") {
            inputFields { name }
          }
          jobInput: __type(name: "JobCreateInput") {
            inputFields { name }
          }
          invoiceInput: __type(name: "InvoiceCreateInput") {
            inputFields { name }
          }
        }
        """
        return self._graphql(query)