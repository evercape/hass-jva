"""Parse the JVA web controller HTML.

The controller on the local network has no documented API. Status and
arm/disarm controls are read from the same HTML page the browser shows.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from jva_fence.models import AlarmFlag, LinkInfo, PageParse, SetupInfo, ZoneStatus

ALARM_NAMES = (
    "Fence Alarm",
    "AC Failed",
    "Low Battery",
    "Tamper",
    "Fault",
    "Gate",
)

_ZONE_RE = re.compile(r"\b(?:Zone|Zona)\s+([0-9]+[A-Za-z]?)\b", re.I)
_POWER_RE = re.compile(r"Power\[([0-9]+[A-Za-z]?)\]", re.I)
_REFRESH_RE = re.compile(
    r"""http-equiv\s*=\s*["']refresh["']\s*content\s*=\s*["']([^"']+)["']""",
    re.I,
)
_KV_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*kV", re.I)
_RETURN_RE = re.compile(r"return|retorno", re.I)
_MODE_WORDS = (
    ("low_power", ("low power", "low-power", "baja potencia", "low")),
    ("disarmed", ("disarmed", "desarmado", "disarm")),
    ("armed", ("armed", "armado", "arm")),
)
_NAMED_COLORS = {
    "red": "error",
    "lime": "ok",
    "green": "ok",
    "lawngreen": "ok",
    "lightgreen": "ok",
    "darkgreen": "ok",
    "forestgreen": "ok",
    "orange": "error",
    "orangered": "error",
    "yellow": "error",
    "gold": "error",
    "tomato": "error",
    "crimson": "error",
    "firebrick": "error",
    "gray": "idle",
    "grey": "idle",
    "silver": "idle",
    "white": "idle",
    "whitesmoke": "idle",
    "gainsboro": "idle",
    "lightgray": "idle",
    "lightgrey": "idle",
    "darkgray": "idle",
    "transparent": "idle",
    "buttonface": "idle",
}


def parse_page(html: str, page_url: str = "http://192.168.0.12/") -> PageParse:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    zones = _parse_zones(soup, page_url)
    links = _parse_links(soup, page_url)
    field_names = _form_field_names(soup)
    clear = _find_clear_alarms(soup, page_url)
    return PageParse(
        title=title,
        zones=zones,
        links=links,
        form_field_names=field_names,
        has_clear_alarms=clear is not None,
        clear_alarms_name=None if clear is None else clear["name"],
        clear_alarms_value=None if clear is None else clear["value"],
        clear_form_method=None if clear is None else clear["method"],
        clear_form_action=None if clear is None else clear["action"],
        clear_form_fields={} if clear is None else clear["fields"],
    )


def apply_mode_html(html: str, zone_id: str, mode: str) -> str:
    """Rewrite checked radios. Used by the local demo, not the live controller."""
    page = parse_page(html)
    zone = page.zone(zone_id)
    if zone is None:
        raise ValueError(f"Unknown zone {zone_id}")
    if mode not in zone.mode_values or not zone.field_name:
        raise ValueError(f"Zone {zone_id} has no {mode} control")
    soup = BeautifulSoup(html, "html.parser")
    wanted = zone.mode_values[mode]
    for inp in soup.find_all("input"):
        if (inp.get("type") or "").lower() != "radio":
            continue
        if inp.get("name") != zone.field_name:
            continue
        if inp.get("value") == wanted:
            inp["checked"] = "checked"
        elif inp.has_attr("checked"):
            del inp["checked"]
    return str(soup)


def visible_frame_urls(html: str, page_url: str) -> list[str]:
    """Iframe addresses that are actually shown. Hidden energiser slots are skipped."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for iframe in soup.find_all("iframe"):
        if not isinstance(iframe, Tag) or _is_hidden(iframe):
            continue
        src = iframe.get("src")
        if not src:
            continue
        urls.append(urljoin(page_url, src))
    return urls


def next_refresh_url(html: str, page_url: str) -> str | None:
    """The PAE212 zone page reloads itself. The r value in that URL steps by 2."""
    match = _REFRESH_RE.search(html)
    if not match:
        return None
    content = match.group(1).strip()
    parts = [part.strip() for part in content.split(";") if part.strip()]
    target = parts[-1] if parts else ""
    if not target or target.isdigit():
        return None
    return urljoin(page_url, target)


def _parse_zones(soup: BeautifulSoup, page_url: str) -> list[ZoneStatus]:
    found: dict[str, tuple[int, ZoneStatus]] = {}
    for tr in soup.find_all("tr"):
        if not isinstance(tr, Tag) or _is_hidden(tr):
            continue
        zone_id = _zone_id_from_row(tr)
        if not zone_id:
            continue
        nested = len(tr.find_all("tr"))
        zone = _zone_from_row(tr, zone_id, page_url)
        previous = found.get(zone_id)
        if previous is None or nested < previous[0] or (
            nested == previous[0] and zone.return_voltage_kv is not None
        ):
            found[zone_id] = (nested, zone)
    return [item[1] for item in found.values()]


def _zone_id_from_row(tr: Tag) -> str | None:
    for inp in tr.find_all("input"):
        match = _POWER_RE.search(inp.get("name") or "")
        if match:
            return match.group(1).lower()
    return _zone_id_from(tr.get_text(" ", strip=True))


def _zone_id_from(text: str) -> str | None:
    match = _ZONE_RE.search(text)
    if not match:
        return None
    return match.group(1).lower()


def _zone_from_row(tr: Tag, zone_id: str, page_url: str) -> ZoneStatus:
    voltage_kv, voltage_state, reading = _return_voltage(tr)
    mode, field_name, mode_values, form_method, form_action, form_fields, mode_onclicks = (
        _mode_controls(tr, page_url)
    )
    prefix = "Zona" if re.search(r"\bZona\b", tr.get_text(" ", strip=True), re.I) else "Zone"
    return ZoneStatus(
        zone_id=zone_id,
        name=f"{prefix} {zone_id}",
        mode=mode,
        return_voltage_kv=voltage_kv,
        voltage_state=voltage_state,
        reading=reading,
        alarms=_alarms(tr),
        field_name=field_name,
        mode_values=mode_values,
        form_method=form_method,
        form_action=form_action,
        form_fields=form_fields,
        mode_onclicks=mode_onclicks,
    )


def _return_voltage(tr: Tag) -> tuple[float | None, str, str | None]:
    candidates: list[tuple[float | None, str, str]] = []
    for cell in tr.find_all("td"):
        if not isinstance(cell, Tag) or _cell_hidden(cell):
            continue
        context = cell.get_text(" ", strip=True)
        if not _RETURN_RE.search(context):
            continue
        match = _KV_RE.search(context)
        value = float(match.group(1).replace(",", ".")) if match else None
        reading = match.group(0) if match else _RETURN_RE.sub("", context).strip(" :-")
        candidates.append((value, _element_state(cell), reading))
    if not candidates:
        return None, "unknown", None
    value, state, reading = candidates[0]
    if reading and re.search(r"coms?\s*fail", reading, re.I):
        state = "error"
    return value, state, reading or None


def _mode_controls(
    tr: Tag, page_url: str
) -> tuple[str, str | None, dict[str, str], str | None, str | None, dict[str, str], dict[str, str]]:
    mode = "unknown"
    field_name: str | None = None
    mode_values: dict[str, str] = {}
    mode_onclicks: dict[str, str] = {}
    form: Tag | None = None
    for inp in tr.find_all("input"):
        if (inp.get("type") or "").lower() != "radio":
            continue
        label = _radio_label(inp)
        mapped = _mode_from_label(label)
        if mapped is None:
            continue
        name = inp.get("name")
        value = inp.get("value", "on")
        if name:
            field_name = name
            mode_values[mapped] = value
        if inp.has_attr("checked"):
            mode = mapped
        if inp.get("onclick"):
            mode_onclicks[mapped] = inp["onclick"]
        parent_form = inp.find_parent("form")
        if isinstance(parent_form, Tag):
            form = parent_form
    if mode == "unknown" and len(mode_values) == 1:
        mode = next(iter(mode_values))
    method = None
    action = None
    fields: dict[str, str] = {}
    if form is not None:
        method = (form.get("method") or "GET").upper()
        action = urljoin(page_url, form.get("action") or page_url)
        fields = _successful_fields(form)
    return mode, field_name, mode_values, method, action, fields, mode_onclicks


def _radio_label(inp: Tag) -> str:
    chunks: list[str] = []
    for sib in inp.next_siblings:
        if isinstance(sib, Tag) and sib.name == "input":
            break
        text = sib.get_text(" ", strip=True) if isinstance(sib, Tag) else str(sib).strip()
        if text:
            chunks.append(text)
        if len(" ".join(chunks)) > 40:
            break
    label = " ".join(chunks).strip()
    if label:
        return label
    parent = inp.parent if isinstance(inp.parent, Tag) else None
    if parent is not None and parent.name == "label":
        return parent.get_text(" ", strip=True)
    return ""


def _mode_from_label(label: str) -> str | None:
    text = label.lower()
    for mode, words in _MODE_WORDS:
        if any(word in text for word in words):
            return mode
    return None


def _alarms(tr: Tag) -> list[AlarmFlag]:
    flags: list[AlarmFlag] = []
    for name in ALARM_NAMES:
        match = _find_alarm_element(tr, name)
        if match is None:
            continue
        state = _element_state(match)
        if state == "error":
            active: bool | None = True
        elif state == "idle":
            active = False
        elif state == "ok":
            active = False
        else:
            active = None
        flags.append(AlarmFlag(name=name, active=active))
    return flags


def _find_alarm_element(tr: Tag, name: str) -> Tag | None:
    needle = name.lower()
    for el in tr.find_all(["input", "button", "td", "span", "div", "a"]):
        if el.name == "input":
            label = (el.get("value") or "").strip()
        else:
            label = el.get_text(" ", strip=True)
        if label.lower() == needle or label.lower().startswith(needle):
            if len(label) > len(name) + 20:
                continue
            return el
    return None


def _cell_hidden(el: Tag) -> bool:
    tokens = {part.upper() for part in (el.get("class") or [])}
    return bool(tokens & {"HID", "NON"}) or _is_hidden(el)


def _is_hidden(tag: Tag) -> bool:
    current: Tag | None = tag
    while isinstance(current, Tag):
        classes = {part.lower() for part in (current.get("class") or [])}
        if "hid" in classes or "hidden" in classes:
            return True
        style = (current.get("style") or "").replace(" ", "").lower()
        if "display:none" in style:
            return True
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return False


def _element_state(el: Tag) -> str:
    current: Tag | None = el
    for _ in range(6):
        if current is None or not isinstance(current, Tag):
            break
        state = classify_background(
            current.get("style") or "",
            current.get("bgcolor"),
            " ".join(current.get("class") or []),
        )
        if state != "unknown":
            return state
        if current.name == "tr":
            break
        parent = current.parent if isinstance(current.parent, Tag) else None
        current = parent
    return "unknown"


def classify_background(style: str, bgcolor: str | None, class_name: str) -> str:
    tokens = {part.upper() for part in class_name.split()}
    if "GRN" in tokens:
        return "ok"
    if "RED" in tokens:
        return "error"
    if tokens & {"GRY", "GREY", "GRAY"}:
        return "idle"
    blob = f"{style} {bgcolor or ''} {class_name}".lower()
    if any(token in blob for token in ("alarm", "fault", "error", "danger")):
        if "no-alarm" not in blob and "inactive" not in blob:
            return "error"
    color = _extract_color(style, bgcolor)
    if color is None:
        return "unknown"
    named = _NAMED_COLORS.get(color.lower())
    if named:
        return named
    rgb = _parse_rgb(color)
    if rgb is None:
        return "unknown"
    return _rgb_state(*rgb)


def _extract_color(style: str, bgcolor: str | None) -> str | None:
    match = re.search(r"background(?:-color)?\s*:\s*([^;]+)", style, re.I)
    raw = match.group(1).strip() if match else (bgcolor or "").strip()
    if not raw or "url(" in raw.lower():
        return None
    token = raw.split()[0].strip()
    return token or None


def _parse_rgb(color: str) -> tuple[int, int, int] | None:
    rgb = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", color, re.I)
    if rgb:
        return int(rgb.group(1)), int(rgb.group(2)), int(rgb.group(3))
    if not color.startswith("#"):
        return None
    hex_color = color[1:]
    if len(hex_color) == 3:
        hex_color = "".join(ch * 2 for ch in hex_color)
    if len(hex_color) != 6 or re.fullmatch(r"[0-9a-fA-F]{6}", hex_color) is None:
        return None
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def _rgb_state(red: int, green: int, blue: int) -> str:
    if abs(red - green) < 28 and abs(green - blue) < 28 and red > 170:
        return "idle"
    if red > 160 and red > green + 35 and red > blue + 35:
        return "error"
    if red > 180 and green > 130 and blue < 110:
        return "error"
    if green > 110 and green > red + 25 and green >= blue:
        return "ok"
    return "unknown"


def _successful_fields(form: Tag) -> dict[str, str]:
    fields: dict[str, str] = {}
    for control in form.find_all(["input", "select", "textarea"]):
        name = control.get("name")
        if not name or not isinstance(control, Tag):
            continue
        if control.name == "select":
            option = control.find("option", selected=True) or control.find("option")
            if isinstance(option, Tag):
                fields[name] = option.get("value", option.get_text(strip=True))
            continue
        if control.name == "textarea":
            fields[name] = control.get_text()
            continue
        input_type = (control.get("type") or "text").lower()
        if input_type in {"submit", "button", "image", "reset", "file"}:
            continue
        if input_type in {"radio", "checkbox"}:
            if control.has_attr("checked"):
                fields[name] = control.get("value", "on")
            continue
        fields[name] = control.get("value", "")
    return fields


def _form_field_names(soup: BeautifulSoup) -> list[str]:
    names: list[str] = []
    for control in soup.find_all(["input", "select", "textarea"]):
        name = control.get("name")
        if name and name not in names:
            names.append(name)
    return names


def _find_clear_alarms(soup: BeautifulSoup, page_url: str) -> dict[str, object] | None:
    for control in soup.find_all(["input", "button"]):
        if not isinstance(control, Tag):
            continue
        label = (control.get("value") or control.get_text(" ", strip=True)).strip()
        if "clear" not in label.lower() or "alarm" not in label.lower():
            continue
        form = control.find_parent("form")
        if not isinstance(form, Tag):
            continue
        return {
            "name": control.get("name") or "clear_alarms",
            "value": control.get("value") or label,
            "method": (form.get("method") or "GET").upper(),
            "action": urljoin(page_url, form.get("action") or page_url),
            "fields": _successful_fields(form),
        }
    return None


_SETUP_FIELDS = {
    "firmware version": "firmware",
    "mac address": "mac",
    "ip address": "ip",
    "dhcp": "dhcp",
    "sub net mask": "subnet",
    "subnet mask": "subnet",
    "default gateway": "gateway",
    "primary dns": "dns",
    "site name": "site_name",
}
_TITLE_SITE_RE = re.compile(r"JVA Embedded:\s*(.+?)\s*-", re.I)


def parse_setup(html: str) -> SetupInfo:
    """Read firmware, MAC, and network fields. Never returns login secrets."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = [cell for cell in row.find_all("td", recursive=False) if isinstance(cell, Tag)]
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True).lower()
        field = _SETUP_FIELDS.get(label)
        if field is None:
            continue
        value = _setup_cell_value(cells[1])
        if field == "dhcp":
            value = _normalize_dhcp(value)
        elif field == "mac" and value:
            value = value.strip().upper()
        if value:
            found[field] = value
    site_name = found.get("site_name")
    if not site_name:
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        match = _TITLE_SITE_RE.search(title)
        if match:
            site_name = match.group(1).strip()
    return SetupInfo(
        firmware=found.get("firmware"),
        mac=found.get("mac"),
        ip=found.get("ip"),
        dhcp=found.get("dhcp"),
        subnet=found.get("subnet"),
        gateway=found.get("gateway"),
        dns=found.get("dns"),
        site_name=site_name,
    )


def _setup_cell_value(cell: Tag) -> str | None:
    radios = [
        el
        for el in cell.find_all("input")
        if isinstance(el, Tag) and (el.get("type") or "").lower() == "radio"
    ]
    if radios:
        chosen = next((el for el in radios if el.has_attr("checked")), None)
        if chosen is None:
            return None
        return _radio_label(chosen).strip() or chosen.get("value")
    for field in cell.find_all("input"):
        if not isinstance(field, Tag):
            continue
        kind = (field.get("type") or "text").lower()
        if kind in {"submit", "button", "radio", "checkbox", "password", "hidden"}:
            continue
        name = (field.get("name") or "").lower()
        if "pass" in name:
            continue
        return field.get("value")
    text = cell.get_text(" ", strip=True)
    return text or None


def _normalize_dhcp(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().lower()
    if text in {"1", "on", "yes"}:
        return "on"
    if text in {"0", "off", "no"}:
        return "off"
    return text


def _parse_links(soup: BeautifulSoup, page_url: str) -> list[LinkInfo]:
    links: list[LinkInfo] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        url = urljoin(page_url, href)
        if url in seen:
            continue
        seen.add(url)
        links.append(LinkInfo(text=anchor.get_text(" ", strip=True) or url, url=url))
    return links
