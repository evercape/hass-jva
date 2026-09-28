[![GitHub Release][releases-shield]][releases]
[![License][license-shield]][license]
[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]

# JVA Electric Fence

Home Assistant custom integration for a [JVA](https://jvasecurity.com/) PAE212 electric fence controller with the built-in web server.

It signs in with the same username and password as the controller web page, reads return voltage and alarm lamps, and arms or disarms Zone 1 and Zone 1a. Setup is done in the Home Assistant UI. There is no YAML configuration.

The controller's own page is the interface. This integration speaks HTTP to that page. It does not use JVA Perimeter Patrol, WinPcap, or a private packet protocol.

## Features

- Config flow for host, username, password, and polling interval
- Default poll of 15 seconds, matching the controller page, changeable later without re-entering the password
- A switch per zone. On sends Armed. Off sends Disarmed
- Return voltage in kV, plus a fault sensor when the return cell is red
- Alarm lamps for fence, AC, battery, tamper, fault, and gate
- Read-only diagnostics: firmware, MAC address, IP address, DHCP, subnet, gateway, and DNS
- The setup page is only read. Save is never pressed, and passwords on that page are not imported
- One log name, `custom_components.jva_electric_fence`, so a single filter shows the whole integration

## Installation

Home Assistant must be able to open the controller's web page. The host running Home Assistant needs a route to that address, usually the same LAN.

### HACS

This integration is not in the default HACS catalog. Add it as a custom repository.

1. Open HACS, then the three-dot menu, then **Custom repositories**.
2. Add `https://github.com/evercape/hass-jva` and choose **Integration**.
3. Search for **JVA Electric Fence** and download it.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add Integration** and search for **JVA Electric Fence**.

HACS installs the release archive `jva_electric_fence.zip`. Download the latest release rather than copying the repository by hand if you want updates.

### Manual

Copy `custom_components/jva_electric_fence` into your Home Assistant `config/custom_components/` directory, then restart.

```text
custom_components/jva_electric_fence
├── __init__.py
├── binary_sensor.py
├── config_flow.py
├── const.py
├── coordinator.py
├── entity.py
├── log.py
├── manifest.json
├── sensor.py
├── strings.json
├── switch.py
├── translations/en.json
└── bundled/jva_fence/
```

## Configuration

**Settings → Devices & services → Add Integration → JVA Electric Fence.**

| Field | Meaning |
| --- | --- |
| Host | Address you already use in a browser, for example `http://192.168.1.50` |
| Username | Web login. The manual's default user is `Admin` |
| Password | Web login. Stored by Home Assistant in the config entry, not in YAML |
| Polling interval | Seconds between reads. Default 15, minimum 5, maximum 3600 |

The device name is the site name from the setup page. Firmware is shown as the software version. The **Visit** link opens the controller.

Change the poll interval from the integration's **Configure** button.

If the controller later rejects the password, Home Assistant starts a re-auth prompt. Update the password there. The host and username stay as they were.

## Entities

Each zone that has arm and disarm controls gets:

| Entity | States |
| --- | --- |
| Switch | On = Armed or Low power. Off = Disarmed. The `mode` attribute is `armed`, `low_power`, or `disarmed` |
| Return voltage | Kilovolts. Unknown when the page has no visible reading, which is normal just after disarm |
| Voltage fault | On when the return cell is red, including "Coms Fail" |
| Fence, AC, battery, tamper, fault, gate | On when that lamp is red |

Diagnostic sensors, disabled from the main view and listed on the device page: firmware, MAC address, IP address, DHCP, subnet mask, default gateway, primary DNS.

Low power still counts as on, because the energiser is running. Turning the switch off from low power sends Disarmed. Turning it on sends full Armed.

Voltage often stays blank for a few seconds after arming. The next poll fills it in. The controller also keeps a hidden duplicate of the voltage. That cell is ignored.

## Logging

All messages use the logger `custom_components.jva_electric_fence`. In **Settings → System → Logs**, search for `jva_electric_fence`.

Info shows startup, the first reading, arm and disarm, and shutdown. Debug adds one line per poll. The password is never logged.

Add this to `configuration.yaml` and restart:

```yaml
logger:
  default: info
  logs:
    custom_components.jva_electric_fence: debug
```

To turn it on without a restart, in **Developer tools → Actions** choose **Logger: Set logger level**, switch to YAML, and run:

```yaml
action: logger.set_level
data:
  custom_components.jva_electric_fence: debug
```

That lasts until Home Assistant restarts. Reload the integration if you want the startup banner after enabling the logger.

```text
READY site=Example Site firmware=1.00 mac=AA:BB:CC:DD:EE:FF ip=192.168.1.50 zone=1 mode=armed return=4.1kV state=ok alarms=clear zone=1a mode=armed return=9.0kV state=ok alarms=clear
SET zone=1 mode=disarmed
SET zone=1 mode=disarmed result=disarmed return=none state=ok
```

| Prefix | Level | Meaning |
| --- | --- | --- |
| startup banner | info | Version, host, and poll interval |
| `READY` | info | First successful read |
| `POLL` | debug | Later reads |
| `SET` | info | Arm or disarm, then the result |
| `AUTH` | warning | Login rejected |
| `SETUP` | warning | Setup page could not be read; last diagnostics kept |
| `STOP` | info | Integration unloaded |

## Safety

Turning a switch on or off commands the live energiser. Home Assistant will do that as soon as you toggle the switch or an automation calls it. Confirm the host is the controller you intend to operate.

## Troubleshooting

- **Cannot connect.** From the Home Assistant host, open the same URL you entered. A machine that can browse the controller is not enough if Home Assistant runs somewhere else.
- **Invalid username or password.** Use the web login, not a guess from the manual. The password is case-sensitive.
- **No arm controls found.** The signed-in page did not contain Zone 1 or Zone 1a power controls. Check that the energiser type on the controller is the 2-zone page this integration reads.
- **Voltage missing while disarmed.** The visible return cell is often empty until the zone is armed again. A red "Coms Fail" is reported as a voltage fault, not as a kilovolt value.
- **Logs are empty.** Set the logger as above, then reload the integration. Use **Show raw logs**.

When you open an issue, include the integration version and the `jva_electric_fence` log lines. Do not include the password or a packet capture of the login.

## Development

The repository also contains a small local console and the parser tests. Those are for development. Home Assistant installs only `custom_components/jva_electric_fence`.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
uvicorn jva_fence.web:app --host 127.0.0.1 --port 8091
```

The console listens on `127.0.0.1:8091`. Put the controller login in `.env` if you want the saved-credentials button. `.env` is not committed. `jva-fence disarm` does not send a command unless you also pass `--yes`.

## Credits

The controller page and the [PAE212 manual](https://www.pakton.com.au/PAE212_Assets/jva_manual.pdf) are the reference for zones, alarm lamps, and the setup fields. Logging follows the single-logger approach used by [Irrigation Unlimited](https://github.com/rgc99/irrigation_unlimited).

[releases-shield]: https://img.shields.io/github/release/evercape/hass-jva.svg?style=for-the-badge
[releases]: https://github.com/evercape/hass-jva/releases
[license-shield]: https://img.shields.io/github/license/evercape/hass-jva.svg?style=for-the-badge
[license]: https://github.com/evercape/hass-jva/blob/main/LICENSE
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-Martin%20%40evercape-blue.svg?style=for-the-badge
