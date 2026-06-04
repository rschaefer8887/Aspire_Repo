"""Aspire External API client (token auth + GET/POST)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DEFAULT_API_BASE = "https://cloud-api.youraspire.com"


def api_base() -> str:
    return os.environ.get("ASPIRE_API_BASE", DEFAULT_API_BASE).strip().rstrip("/")


def inventory_location_id() -> int:
    raw = os.environ.get("ASPIRE_INVENTORY_LOCATION_ID", "1").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"ASPIRE_INVENTORY_LOCATION_ID must be an integer, got {raw!r}"
        ) from exc
    if value < 1:
        raise ValueError(f"ASPIRE_INVENTORY_LOCATION_ID must be >= 1, got {value}")
    return value


def require_credentials() -> tuple[str, str]:
    client_id = os.environ.get("ASPIRE_CLIENT_ID", "").strip()
    secret = os.environ.get("ASPIRE_SECRET", "").strip()
    if not client_id or not secret:
        print(
            "Set ASPIRE_CLIENT_ID and ASPIRE_SECRET in .env (see .env.example).",
            file=sys.stderr,
        )
        sys.exit(1)
    return client_id, secret


class AspireClient:
    def __init__(self, client_id: str, secret: str, *, base_url: str | None = None) -> None:
        self.base_url = (base_url or api_base()).rstrip("/")
        self.client_id = client_id
        self.secret = secret
        self._token: str | None = None
        self._refresh_token: str | None = None

    def authenticate(self) -> str:
        url = f"{self.base_url}/Authorization"
        payload = {"ClientId": self.client_id, "Secret": self.secret}
        r = requests.post(url, json=payload, timeout=60)
        self._raise_for_response(r, "Authorization")
        data = r.json()
        token = data.get("Token")
        if not token:
            raise RuntimeError("Authorization returned no Token")
        self._token = str(token)
        self._refresh_token = data.get("RefreshToken")
        return self._token

    def _refresh(self) -> str:
        if not self._refresh_token:
            return self.authenticate()
        url = f"{self.base_url}/Authorization/RefreshToken"
        r = requests.post(
            url, json={"RefreshToken": self._refresh_token}, timeout=60
        )
        if r.status_code >= 400:
            return self.authenticate()
        data = r.json()
        token = data.get("Token")
        if not token:
            return self.authenticate()
        self._token = str(token)
        if data.get("RefreshToken"):
            self._refresh_token = data.get("RefreshToken")
        return self._token

    @property
    def token(self) -> str:
        if not self._token:
            return self.authenticate()
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> Any:
        path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{path}"
        r = requests.get(url, headers=self._headers(), params=params, timeout=timeout)
        if r.status_code == 401:
            self._refresh()
            r = requests.get(url, headers=self._headers(), params=params, timeout=timeout)
        self._raise_for_response(r, f"GET {path}")
        if not r.content:
            return []
        return r.json()

    def post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        timeout: int = 120,
    ) -> Any:
        path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{path}"
        r = requests.post(url, headers=self._headers(), json=body, timeout=timeout)
        if r.status_code == 401:
            self._refresh()
            r = requests.post(url, headers=self._headers(), json=body, timeout=timeout)
        self._raise_for_response(r, f"POST {path}")
        if not r.content:
            return {}
        return r.json()

    def fetch_all(
        self,
        path: str,
        *,
        extra_params: dict[str, Any] | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        """Page through OData list endpoints until a short page is returned."""
        params: dict[str, Any] = dict(extra_params or {})
        all_rows: list[dict[str, Any]] = []
        page = 1
        while True:
            params["$limit"] = str(page_size)
            params["$pageNumber"] = str(page)
            chunk = self.get(path, params=params)
            if not isinstance(chunk, list):
                if isinstance(chunk, dict):
                    for key in ("value", "data", "items"):
                        if isinstance(chunk.get(key), list):
                            chunk = chunk[key]
                            break
                    else:
                        raise RuntimeError(
                            f"Unexpected response shape from {path}: {type(chunk)}"
                        )
                else:
                    raise RuntimeError(f"Unexpected response from {path}: {type(chunk)}")
            if not chunk:
                break
            for row in chunk:
                if isinstance(row, dict):
                    all_rows.append(row)
            if len(chunk) < page_size:
                break
            page += 1
        return all_rows

    @staticmethod
    def _raise_for_response(r: requests.Response, label: str) -> None:
        if r.status_code < 400:
            return
        detail = r.text[:2000] if r.text else r.reason
        raise RuntimeError(f"{label} failed: HTTP {r.status_code} — {detail}")
