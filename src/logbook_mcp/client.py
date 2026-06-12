"""Thin async wrapper around the signalk-logbook plugin's REST API."""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_date(date: str) -> None:
    """Reject anything that isn't YYYY-MM-DD shaped (format check only) before interpolating into a URL."""
    if not _DATE_RE.match(date):
        raise ValueError(f"invalid date: {date!r}")


class LogbookClient:
    """Async client for signalk-logbook on a SignalK server.

    ``base_url`` is the SignalK server root (e.g. http://naturalaspi.local:3000);
    plugin routes live under /plugins/signalk-logbook. Writes require a SignalK
    access token, sent as ``Authorization: Bearer {token}``.
    """

    def __init__(self, base_url: str, token: str | None = None,
                 timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        # signalk-server's admin gate accepts the Authorization header, but
        # the logbook plugin reads the author from the JAUTHENTICATION
        # cookie — send the token both ways.
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        cookies = {"JAUTHENTICATION": token} if token else {}
        # One timeout for all phases, including the post-write PUT; a slow Pi
        # can exceed 5 s and read as a false "could not confirm" — raise it
        # via LOGBOOK_TIMEOUT rather than living with the default.
        self._http = httpx.AsyncClient(timeout=timeout, headers=headers, cookies=cookies)

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

    async def get_dates(self) -> list[str]:
        """All YYYY-MM-DD days that have a log file. 404 -> no logs yet -> []."""
        resp = await self._http.get(f"{self._api}/logs")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json()

    async def post_entry(self, text: str, category: str | None = None) -> None:
        """Create an entry; the plugin enriches it server-side from live SignalK.

        ``ago: 0`` is always included — the plugin calls ``buffer.get(req.body.ago)``
        whenever its state buffer is non-empty, and omitting the field causes an
        HTTP 500 once the buffer has been populated.

        ``category`` is sent only when given; the plugin defaults to
        "navigation". The plugin copies it unvalidated, so values outside its
        schema enum (e.g. "drill") write fine — validation is our job.

        POST returns a bare 201 with no body — callers re-fetch the day to see
        the created entry.
        """
        body: dict = {"text": text, "ago": 0}
        if category is not None:
            body["category"] = category
        resp = await self._http.post(f"{self._api}/logs", json=body)
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
        except httpx.TransportError:
            return None
        if resp.status_code != 200:
            return None
        value = resp.json().get("value") or {}
        if value.get("latitude") is None or value.get("longitude") is None:
            return None
        return {"latitude": value["latitude"], "longitude": value["longitude"]}

    async def aclose(self) -> None:
        await self._http.aclose()
