import base64
from pathlib import Path

import httpx

from jva_fence.client import AuthError, JvaClient
from jva_fence.parser import apply_mode_html

FIXTURES = Path(__file__).resolve().parents[1] / "src" / "jva_fence" / "fixtures"
OK_HTML = FIXTURES.joinpath("status_ok.html").read_text(encoding="utf-8")
VOLTAGE_HTML = FIXTURES.joinpath("voltage.htm").read_text(encoding="utf-8")


def _auth_user(request: httpx.Request) -> str:
    header = request.headers["authorization"]
    encoded = header.split(" ", 1)[1]
    return base64.b64decode(encoded).decode()


def test_status_uses_basic_auth_and_posts_the_zone_form():
    seen: list[httpx.Request] = []
    current = {"html": OK_HTML}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert _auth_user(request) == "installer:s3cret"
        if request.method == "GET" and request.url.path == "/":
            return httpx.Response(200, text=current["html"])
        if request.method == "POST" and request.url.path == "/index.htm":
            body = request.content.decode()
            assert "z1mode=0" in body
            assert "z1amode=1" in body
            current["html"] = apply_mode_html(OK_HTML, "1", "disarmed")
            return httpx.Response(200, text=current["html"])
        return httpx.Response(404, text="missing")

    client = JvaClient(
        "http://192.168.0.12",
        "installer",
        "s3cret",
        transport=httpx.MockTransport(handler),
    )
    page = client.fetch_page()
    assert page.zone("1").return_voltage_kv == 4.2
    updated = client.set_zone_mode("1", "disarmed")
    assert updated.zone("1").mode == "disarmed"
    assert updated.zone("1a").mode == "armed"
    posts = [request for request in seen if request.method == "POST"]
    assert len(posts) == 1
    assert posts[0].url.path == "/index.htm"
    client.close()


def test_bad_password_is_an_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="401 Unauthorized: Password required")

    client = JvaClient("192.168.0.12", "nope", "wrong", transport=httpx.MockTransport(handler))
    try:
        client.fetch_page()
        raise AssertionError("expected AuthError")
    except AuthError as exc:
        assert "Authentication failed" in str(exc)
    finally:
        client.close()


def test_probe_reports_html_pages_and_a_json_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status.json":
            return httpx.Response(200, json={"zones": []}, headers={"content-type": "application/json"})
        if request.url.path == "/voltage.htm":
            return httpx.Response(200, text=VOLTAGE_HTML, headers={"content-type": "text/html"})
        return httpx.Response(404, text="404: File not found", headers={"content-type": "text/plain"})

    client = JvaClient("http://192.168.0.12/", "user", "pw", transport=httpx.MockTransport(handler))
    report = client.probe_api(["http://192.168.0.12/voltage.htm", "http://192.168.0.12/manual.pdf"])
    kinds = {item["url"]: item["kind"] for item in report["checked"]}
    assert report["api_found"] is True
    assert kinds["http://192.168.0.12/status.json"] == "json"
    assert kinds["http://192.168.0.12/voltage.htm"] == "html"
    assert "http://192.168.0.12/manual.pdf" not in kinds
    client.close()


def test_live_layout_follows_the_visible_zone_page_and_the_refresh_counter():
    frame = (FIXTURES / "zone1.htm").read_text(encoding="utf-8")
    shell = """
    <html><head><title>Voltages</title></head><body>
    <form method="post" action="/user/voltages.htm">
      <table>
        <tr class="vPage"><td>Zone 1</td><td>2 Zone</td>
          <td><iframe src="/user/zone1.htm"></iframe></td></tr>
        <tr><td>Zone 1a</td><td></td></tr>
      </table>
    </form>
    <form class="hid" method="post" action="/user/voltages.htm">
      <iframe src="/user/zone2.htm"></iframe>
    </form>
    </body></html>
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/":
            return httpx.Response(200, text=shell)
        if request.url.path == "/user/zone1.htm":
            return httpx.Response(200, text=frame)
        if request.url.path == "/user/zone2.htm":
            raise AssertionError("hidden zone page should not be read")
        return httpx.Response(404, text="missing")

    client = JvaClient("http://192.168.0.12", "user", "pw", transport=httpx.MockTransport(handler))
    page = client.fetch_page()
    assert page.zone("1").return_voltage_kv == 4.1
    assert page.zone("1").voltage_state == "ok"
    assert page.zone("1a").return_voltage_kv == 9.2
    assert page.zone("2") is None
    client.fetch_page()
    assert any(url.endswith("/user/zone1.htm?r=4456") for url in seen)
    assert not any("/user/zone2.htm" in url for url in seen)
    client.close()


def test_onclick_fallback_when_there_is_no_form():
    html = """
    <html><body><table><tr>
      <td>Zone 1</td>
      <td style="background:green">Return 5.0 kV</td>
      <td>
        <input type="radio" name="z" value="0" checked
          onclick="window.location='arm.htm?zone=1&state=0'"> Disarmed
        <input type="radio" name="z" value="1"
          onclick="window.location='arm.htm?zone=1&state=1'"> Armed
      </td>
    </tr></table></body></html>
    """
    armed = html.replace('value="0" checked', 'value="0"').replace(
        'value="1"', 'value="1" checked', 1
    )
    seen: list[str] = []
    armed_sent = {"done": False}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path != "/":
            armed_sent["done"] = True
            return httpx.Response(200, text=armed)
        if armed_sent["done"]:
            return httpx.Response(200, text=armed)
        return httpx.Response(200, text=html)

    client = JvaClient("http://192.168.0.12", "user", "pw", transport=httpx.MockTransport(handler))
    page = client.set_zone_mode("1", "armed")
    assert page.zone("1").mode == "armed"
    assert any(url.endswith("/arm.htm?zone=1&state=1") for url in seen)
    client.close()


def test_setup_is_read_with_get_and_never_saved():
    setup_html = FIXTURES.joinpath("setup.htm").read_text(encoding="utf-8")
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method != "GET":
            return httpx.Response(500, text="setup must not be submitted")
        if request.url.path == "/admin/index.htm":
            return httpx.Response(200, text=setup_html)
        return httpx.Response(404, text="missing")

    client = JvaClient("http://192.168.0.12", "user", "pw", transport=httpx.MockTransport(handler))
    setup = client.fetch_setup()
    assert setup.firmware == "1.00"
    assert setup.mac == "AA:BB:CC:DD:EE:FF"
    assert seen == [("GET", "/admin/index.htm")]
    client.close()
