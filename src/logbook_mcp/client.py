"""Thin async wrapper around the signalk-logbook plugin's REST API."""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_date(date: str) -> None:
    """Reject anything that isn't YYYY-MM-DD before interpolating into a URL."""
    if not _DATE_RE.match(date):
        raise ValueError(f"invalid date: {date!r}")


class LogbookClient:
    """Async client for signalk-logbook on a SignalK server.

    ``base_url`` is the SignalK server root (e.g. http://naturalaspi.local:3000);
    plugin routes live under /plugins/signalk-logbook. Writes require a SignalK
    access token, sent as ``Authorization: Bearer {token}``.
    """

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.AsyncClient(timeout=5.0, headers=headers)

    @property
    def _api(self) -> str:
        return f"{self.base_url}/plugins/signalk-logbook"

    async def get_entries(self, date: str) -> list[dict]:
        """Entries for a YYYY-MM-DD day. A 404 means no log that day -> []."""
        validate_date(date)
        resp = await self._http.get(f"{self._api}/logs/{date}")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json()

    async def post_entry(self, text: str) -> None:
        """Create an entry; the plugin enriches it server-side from live SignalK.

        POST returns a bare 201 with no body — callers re-fetch the day to see
        the created entry.
        """
        resp = await self._http.post(f"{self._api}/logs", json={"text": text})
        resp.raise_for_status()

    async def put_entry(self, date: str, datetime_key: str, entry: dict) -> None:
        """Replace an entry identified by its datetime key."""
        validate_date(date)
        url = f"{self._api}/logs/{date}/{quote(datetime_key, safe='')}"
        resp = await self._http.put(url, json=entry)
        resp.raise_for_status()

    async def get_position(self) -> dict | None:
        """Current GPS fix from SignalK, or None if unavailable.

        Absence (404, no fix, unreachable) is a normal result here, not an
        error — callers fall back to LOGBOOK_TZ.
        """
        url = f"{self.base_url}/signalk/v1/api/vessels/self/navigation/position"
        try:
            resp = await self._http.get(url)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        value = resp.json().get("value") or {}
        if value.get("latitude") is None or value.get("longitude") is None:
            return None
        return {"latitude": value["latitude"], "longitude": value["longitude"]}

    async def aclose(self) -> None:
        await self._http.aclose()
