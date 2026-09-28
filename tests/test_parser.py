from pathlib import Path

from dataclasses import asdict

from jva_fence.parser import apply_mode_html, parse_page, parse_setup

FIXTURES = Path(__file__).resolve().parents[1] / "src" / "jva_fence" / "fixtures"


def test_ok_page_matches_the_controller_screenshot():
    page = parse_page(FIXTURES.joinpath("status_ok.html").read_text(encoding="utf-8"))
    assert page.title == "JVA Electric Fence WebServer Control"
    assert [zone.zone_id for zone in page.zones] == ["1", "1a"]

    zone1, zone1a = page.zones
    assert zone1.mode == "armed"
    assert zone1.return_voltage_kv == 4.2
    assert zone1.voltage_state == "ok"
    assert zone1.mode_values == {"disarmed": "0", "armed": "1", "low_power": "2"}
    assert zone1.form_method == "POST"
    assert zone1.form_fields["z1mode"] == "1"
    assert zone1.form_fields["z1amode"] == "1"
    assert all(alarm.active is False for alarm in zone1.alarms)
    assert [alarm.name for alarm in zone1.alarms] == [
        "Fence Alarm",
        "AC Failed",
        "Low Battery",
        "Tamper",
        "Fault",
        "Gate",
    ]

    assert zone1a.return_voltage_kv == 9.0
    assert zone1a.voltage_state == "ok"
    assert zone1a.mode == "armed"
    assert page.has_clear_alarms is True
    assert any(link.text == "Voltaje" for link in page.links)


def test_alarm_page_marks_red_voltage_as_error_and_reads_spanish_labels():
    page = parse_page((FIXTURES / "status_alarm.html").read_text(encoding="utf-8"))
    zone1 = page.zone("1")
    zone1a = page.zone("1a")
    assert zone1 is not None and zone1a is not None
    assert zone1.return_voltage_kv == 0.8
    assert zone1.voltage_state == "error"
    fence = next(alarm for alarm in zone1.alarms if alarm.name == "Fence Alarm")
    ac = next(alarm for alarm in zone1.alarms if alarm.name == "AC Failed")
    assert fence.active is True
    assert ac.active is False
    assert zone1a.mode == "disarmed"
    assert zone1a.return_voltage_kv == 9.0
    assert zone1a.voltage_state == "ok"
    assert zone1a.mode_values["armed"] == "on"
    assert zone1.form_method == "GET"


def test_zone_frame_uses_green_class_and_ignores_hidden_return():
    html = (FIXTURES / "zone1.htm").read_text(encoding="utf-8")
    page = parse_page(html, "http://192.168.0.12/user/zone1.htm?r=4368")
    zone1 = page.zone("1")
    zone1a = page.zone("1a")
    assert zone1 is not None and zone1a is not None
    assert zone1.return_voltage_kv == 4.1
    assert zone1.voltage_state == "ok"
    assert zone1.reading == "4.1 kV"
    assert zone1.mode == "armed"
    assert zone1.field_name == "Power[1]"
    assert zone1.form_action.endswith("/user/zone1.htm")
    assert all(alarm.active is False for alarm in zone1.alarms)
    assert zone1a.return_voltage_kv == 9.2
    assert zone1a.voltage_state == "ok"
    assert zone1a.mode == "armed"


def test_refresh_counter_steps_to_the_next_zone_url():
    from jva_fence.parser import next_refresh_url

    html = '<META HTTP-EQUIV="REFRESH"CONTENT="15;/user/zone1.htm?r=4420">'
    assert next_refresh_url(html, "http://192.168.0.12/user/zone1.htm?r=4418") == (
        "http://192.168.0.12/user/zone1.htm?r=4420"
    )


def test_setup_page_reads_firmware_and_network_and_drops_passwords():
    html = (FIXTURES / "setup.htm").read_text(encoding="utf-8")
    setup = parse_setup(html)
    assert setup.firmware == "1.00"
    assert setup.mac == "AA:BB:CC:DD:EE:FF"
    assert setup.ip == "192.168.1.50"
    assert setup.dhcp == "off"
    assert setup.subnet == "255.255.255.0"
    assert setup.gateway == "192.168.1.1"
    assert setup.dns == "8.8.8.8"
    assert setup.site_name == "Example Site"
    dumped = " ".join(str(value) for value in asdict(setup).values())
    assert "example-admin-pw" not in dumped
    assert "example-user-pw" not in dumped


def test_apply_mode_html_checks_only_the_requested_zone():
    html = FIXTURES.joinpath("status_ok.html").read_text(encoding="utf-8")
    updated = apply_mode_html(html, "1", "disarmed")
    page = parse_page(updated)
    assert page.zone("1").mode == "disarmed"
    assert page.zone("1a").mode == "armed"
    assert page.zone("1").form_fields["z1mode"] == "0"
    assert page.zone("1").form_fields["z1amode"] == "1"
