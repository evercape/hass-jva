"""HTTP client for the JVA web controller.

Authentication is HTTP Basic, which is the browser username/password
prompt. The device answers every path with the same 401 until credentials
are sent, so linked pages and any hidden API can only be checked after login.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse
from bs4 import BeautifulSoup

import httpx

from jva_fence.models import PageParse, SetupInfo, ZoneStatus
from jva_fence.parser import next_refresh_url, parse_page, parse_setup, visible_frame_urls

_ASSET_EXTENSIONS = {
    ".png",
    ".gif",
    ".jpg",
    ".jpeg",
    ".css",
    ".js",
    ".ico",
    ".pdf",
    ".svg",
}
_API_CANDIDATES = (
    "/",
    "/index.html",
    "/index.htm",
    "/api",
    "/api/status",
    "/status.json",
    "/status.xml",
    "/json",
    "/voltage",
    "/voltage.html",
    "/voltage.htm",
    "/cgi-bin/",
)
_ONCLICK_URL = re.compile(
    r"""(?:location(?:\.href)?|window\.location)\s*=\s*['"]([^'"]+)['"]""",
    re.I,
)


class JvaError(Exception):
    """Base error for controller access."""


class AuthError(JvaError):
    """Username or password was rejected."""


class ControllerError(JvaError):
    """The controller could not be read or commanded."""


class JvaClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        timeout: float = 8.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = normalize_host(host)
        self.username = username
        self.last_html: str | None = None
        self.excerpt = ""
        self.next_frame_urls: dict[str, str] = {}
        self._client = httpx.Client(
            auth=httpx.BasicAuth(username, password),
            timeout=timeout,
            follow_redirects=True,
            max_redirects=4,
            trust_env=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_page(self) -> PageParse:
        html, final_url = self.fetch_html(self.base_url)
        self.last_html = html
        page = parse_page(html, final_url)
        texts = [BeautifulSoup(html, "html.parser").get_text("\n", strip=True)]
        fetched: list[str] = []
        for frame_url in visible_frame_urls(html, final_url):
            target = self.next_frame_urls.get(_frame_key(frame_url), frame_url)
            frame_html, frame_final = self.fetch_html(target)
            fetched.append(frame_final)
            upcoming = next_refresh_url(frame_html, frame_final)
            if upcoming:
                self.next_frame_urls[_frame_key(frame_url)] = upcoming
            frame_page = parse_page(frame_html, frame_final)
            page = _merge_pages(page, frame_page)
            texts.append(BeautifulSoup(frame_html, "html.parser").get_text("\n", strip=True))
        page.frames = fetched
        self.last_html = html
        self.excerpt = "\n".join(texts)[:1500]
        return page

    def fetch_setup(self) -> SetupInfo:
        """GET the setup page and return firmware, MAC, and network fields.

        The setup form has Save buttons. This method never posts it.
        """
        previous = self.last_html
        try:
            html, _final = self.fetch_html(urljoin(self.base_url, "admin/index.htm"))
            return parse_setup(html)
        finally:
            self.last_html = previous

    def fetch_html(self, url: str) -> tuple[str, str]:
        try:
            response = self._client.get(url)
        except httpx.TimeoutException as exc:
            raise ControllerError(f"Controller at {url} did not respond in time.") from exc
        except httpx.HTTPError as exc:
            raise ControllerError(f"Could not reach the controller: {exc}") from exc
        self._raise_for_status(response)
        self.last_html = response.text
        return response.text, str(response.url)

    def set_zone_mode(self, zone_id: str, mode: str) -> PageParse:
        page = self.fetch_page()
        zone = page.zone(zone_id)
        if zone is None:
            raise ControllerError(f"Zone {zone_id} was not on the controller page.")
        if mode not in zone.mode_values:
            raise ControllerError(f"Zone {zone.name} has no {mode} control.")
        onclick_url = _onclick_target(zone.mode_onclicks.get(mode, ""), page_url=self.base_url)
        try:
            if zone.field_name and zone.form_action:
                payload = dict(zone.form_fields)
                payload[zone.field_name] = zone.mode_values[mode]
                response = self._submit(zone.form_method or "GET", zone.form_action, payload)
            elif onclick_url:
                response = self._client.get(onclick_url)
            else:
                raise ControllerError(f"Zone {zone.name} has no form control to submit.")
        except httpx.TimeoutException as exc:
            raise ControllerError("The controller did not respond to the zone command.") from exc
        except httpx.HTTPError as exc:
            raise ControllerError(f"The zone command failed: {exc}") from exc
        self._raise_for_status(response)
        self.last_html = response.text
        return self.fetch_page()

    def clear_alarms(self) -> PageParse:
        page = self.fetch_page()
        if not page.has_clear_alarms or not page.clear_form_action:
            raise ControllerError("The controller page has no Clear Alarms control.")
        payload = dict(page.clear_form_fields)
        if page.clear_alarms_name:
            payload[page.clear_alarms_name] = page.clear_alarms_value or "Clear Alarms"
        try:
            response = self._submit(
                page.clear_form_method or "POST",
                page.clear_form_action,
                payload,
            )
        except httpx.HTTPError as exc:
            raise ControllerError(f"Clear Alarms failed: {exc}") from exc
        self._raise_for_status(response)
        self.last_html = response.text
        return self.fetch_page()

    def probe_api(self, extra_urls: list[str] | None = None) -> dict[str, Any]:
        """Check likely API paths and same-host links after authentication."""
        origin = self.base_url
        urls = [urljoin(origin, path) for path in _API_CANDIDATES]
        for extra in extra_urls or []:
            if _same_host(origin, extra):
                urls.append(extra)
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for url in urls:
            cleaned = url.split("#", 1)[0]
            if cleaned in seen or _is_asset(cleaned):
                continue
            seen.add(cleaned)
            results.append(self._describe(cleaned))
            if len(results) >= 30:
                break
        structured = [item for item in results if item["kind"] in {"json", "xml"}]
        return {
            "api_found": bool(structured),
            "summary": (
                "A structured response was found behind login."
                if structured
                else "No JSON or XML API turned up. Status is the HTML page."
            ),
            "checked": results,
        }

    def _submit(self, method: str, url: str, payload: dict[str, str]) -> httpx.Response:
        # Keep Power[1] brackets literal. This firmware matches the field name as written.
        body = urlencode(payload, safe="[]")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if method.upper() == "POST":
            return self._client.post(url, content=body, headers=headers)
        return self._client.get(url, params=payload)

    def _describe(self, url: str) -> dict[str, Any]:
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            return {"url": url, "status": None, "kind": "error", "detail": str(exc)}
        content_type = response.headers.get("content-type", "")
        kind = _kind_of(response.status_code, content_type, response.text[:500])
        return {
            "url": url,
            "status": response.status_code,
            "content_type": content_type.split(";")[0],
            "kind": kind,
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise AuthError("Authentication failed. Check the username and password.")
        if response.status_code >= 400:
            raise ControllerError(
                f"Controller returned HTTP {response.status_code} for {response.url}."
            )


def normalize_host(host: str) -> str:
    value = host.strip()
    if not value:
        raise ControllerError("Controller host is required.")
    if "://" not in value:
        value = f"http://{value}"
    parsed = urlparse(value)
    if not parsed.hostname:
        raise ControllerError(f"Controller host {host!r} is not a valid URL.")
    return value.rstrip("/") + "/"


def _onclick_target(onclick: str, page_url: str) -> str | None:
    match = _ONCLICK_URL.search(onclick)
    if not match:
        return None
    return urljoin(page_url, match.group(1))


def _same_host(origin: str, url: str) -> bool:
    left = urlparse(origin)
    right = urlparse(url)
    return (right.hostname or "").lower() == (left.hostname or "").lower()


def _is_asset(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in _ASSET_EXTENSIONS)


def _frame_key(url: str) -> str:
    return urlparse(url).path


def _merge_pages(base: PageParse, extra: PageParse) -> PageParse:
    incoming = {zone.zone_id: zone for zone in extra.zones}
    merged: list[ZoneStatus] = []
    seen: set[str] = set()
    for zone in base.zones:
        replacement = incoming.get(zone.zone_id)
        if replacement is not None and _prefer_frame(replacement, zone):
            merged.append(replacement)
        else:
            merged.append(zone)
        seen.add(zone.zone_id)
    for zone in extra.zones:
        if zone.zone_id not in seen:
            merged.append(zone)
    base.zones = merged
    return base


def _prefer_frame(frame_zone: ZoneStatus, shell_zone: ZoneStatus) -> bool:
    if frame_zone.return_voltage_kv is not None or frame_zone.reading:
        return True
    if frame_zone.mode_values and not shell_zone.mode_values:
        return True
    return False


def _kind_of(status: int, content_type: str, sample: str) -> str:
    if status == 401:
        return "unauthorized"
    lowered = content_type.lower()
    text = sample.lstrip()
    folded = text.lower()
    if "json" in lowered or text.startswith("{") or text.startswith("["):
        return "json"
    if "xml" in lowered or text.startswith("<?xml"):
        return "xml"
    if "html" in lowered or "<html" in folded or "<!doctype html" in folded:
        return "html"
    return "other"
