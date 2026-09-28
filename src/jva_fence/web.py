"""Local test console for the JVA controller.

Run this on 127.0.0.1:8091. gtowntrails already uses ports 3000 and 4000.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jva_fence.client import AuthError, JvaClient, JvaError
from jva_fence.parser import apply_mode_html, parse_page

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "status_ok.html"
STATIC = ROOT / "static"
DATA = Path("data")

load_dotenv()

app = FastAPI(title="JVA Electric Fence Local Console")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def do_not_cache_api(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class SessionBody(BaseModel):
    mode: str
    host: str | None = None
    username: str | None = None
    password: str | None = None
    use_env: bool = False


class ModeBody(BaseModel):
    mode: str = Field(pattern="^(armed|disarmed|low_power)$")


class ConsoleState:
    def __init__(self) -> None:
        self.kind: str | None = None
        self.client: JvaClient | None = None
        self.demo_html: str | None = None
        self.host: str | None = None
        self.username: str | None = None

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
        self.kind = None
        self.demo_html = None
        self.host = None
        self.username = None


STATE = ConsoleState()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config() -> dict[str, object]:
    username = os.getenv("JVA_USERNAME", "")
    password = os.getenv("JVA_PASSWORD", "")
    return {
        "host": os.getenv("JVA_HOST", "http://192.168.0.12"),
        "username": username,
        "has_env_credentials": bool(username and password),
        "listen": "127.0.0.1:8091",
    }


@app.post("/api/session")
def open_session(body: SessionBody) -> dict[str, object]:
    STATE.close()
    if body.mode == "demo":
        STATE.kind = "demo"
        STATE.demo_html = FIXTURE.read_text(encoding="utf-8")
        STATE.host = "demo"
        return _status_payload()
    if body.mode != "live":
        raise HTTPException(status_code=400, detail="Mode must be demo or live.")
    host, username, password = _live_credentials(body)
    client = JvaClient(host, username, password)
    STATE.kind = "live"
    STATE.client = client
    STATE.host = client.base_url
    STATE.username = username
    try:
        payload = _status_payload()
    except JvaError:
        STATE.close()
        raise
    payload["api_probe"] = client.probe_api()
    return payload


@app.delete("/api/session")
def close_session() -> dict[str, bool]:
    STATE.close()
    return {"connected": False}


@app.get("/api/status")
def status() -> dict[str, object]:
    _require()
    return _status_payload()


@app.post("/api/zones/{zone_id}/mode")
def set_mode(zone_id: str, body: ModeBody) -> dict[str, object]:
    _require()
    if STATE.kind == "demo":
        assert STATE.demo_html is not None
        try:
            STATE.demo_html = apply_mode_html(STATE.demo_html, zone_id, body.mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _status_payload()
    assert STATE.client is not None
    page = STATE.client.set_zone_mode(zone_id, body.mode)
    if STATE.client.last_html:
        _save_html(STATE.client.last_html)
    return _status_payload(page)


@app.post("/api/alarms/clear")
def clear_alarms() -> dict[str, object]:
    _require()
    if STATE.kind == "demo":
        return _status_payload()
    assert STATE.client is not None
    page = STATE.client.clear_alarms()
    if STATE.client.last_html:
        _save_html(STATE.client.last_html)
    return _status_payload(page)


@app.get("/api/investigate")
def investigate() -> dict[str, object]:
    _require()
    if STATE.kind == "demo" or STATE.client is None:
        return {
            "api_found": False,
            "summary": "Demo mode uses a saved HTML sample. Connect live to probe the controller.",
            "checked": [],
        }
    page = parse_page(STATE.client.last_html or "", STATE.client.base_url)
    extra = [link.url for link in page.links]
    return STATE.client.probe_api(extra)


@app.exception_handler(AuthError)
def auth_error(_: object, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(JvaError)
def jva_error(_: object, exc: JvaError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


def _live_credentials(body: SessionBody) -> tuple[str, str, str]:
    if body.use_env:
        host = os.getenv("JVA_HOST", "")
        username = os.getenv("JVA_USERNAME", "")
        password = os.getenv("JVA_PASSWORD", "")
    else:
        host = body.host or ""
        username = body.username or ""
        password = body.password or ""
    if not host or not username or not password:
        raise HTTPException(
            status_code=400,
            detail="Host, username, and password are required to connect to the controller.",
        )
    return host, username, password


def _require() -> None:
    if STATE.kind is None:
        raise HTTPException(status_code=409, detail="Not connected.")


def _status_payload(page=None) -> dict[str, object]:
    next_frames: list[str] = []
    if STATE.kind == "demo":
        html = STATE.demo_html or ""
        page = parse_page(html, "http://192.168.0.12/")
        excerpt = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)[:1500]
    else:
        if STATE.client is None:
            raise HTTPException(status_code=409, detail="Not connected.")
        if page is None:
            page = STATE.client.fetch_page()
        if STATE.client.last_html:
            _save_html(STATE.client.last_html)
        excerpt = STATE.client.excerpt
        next_frames = list(STATE.client.next_frame_urls.values())
    return {
        "connected": True,
        "source": STATE.kind,
        "host": STATE.host,
        "username": STATE.username,
        "page": page.to_public_dict(),
        "excerpt": excerpt,
        "refreshed_at": datetime.now().strftime("%H:%M:%S"),
        "next_frames": next_frames,
    }


def _save_html(html: str) -> None:
    DATA.mkdir(exist_ok=True)
    (DATA / "last_page.html").write_text(html, encoding="utf-8")
