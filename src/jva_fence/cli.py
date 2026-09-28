"""Command line access to a JVA controller. Reads JVA_HOST, JVA_USERNAME, and JVA_PASSWORD."""

from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from jva_fence.client import JvaClient, JvaError


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Read or command a JVA fence controller")
    parser.add_argument("command", choices=["status", "investigate", "arm", "disarm", "low-power"])
    parser.add_argument("--zone", help="Zone id, for example 1 or 1a")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required before arm, disarm, or low-power. Those commands change the live fence.",
    )
    args = parser.parse_args(argv)
    host = os.getenv("JVA_HOST", "")
    username = os.getenv("JVA_USERNAME", "")
    password = os.getenv("JVA_PASSWORD", "")
    if not host or not username or not password:
        print("Set JVA_HOST, JVA_USERNAME, and JVA_PASSWORD in .env.", file=sys.stderr)
        return 2
    if args.command in {"arm", "disarm", "low-power"}:
        if not args.zone:
            print("Pass --zone for arm, disarm, or low-power.", file=sys.stderr)
            return 2
        if not args.yes:
            print(
                "That command changes the live fence. Re-run with --yes once you mean to send it.",
                file=sys.stderr,
            )
            return 2
    client = JvaClient(host, username, password)
    try:
        if args.command == "status":
            print(json.dumps(client.fetch_page().to_public_dict(), indent=2))
        elif args.command == "investigate":
            page = client.fetch_page()
            print(json.dumps(client.probe_api([link.url for link in page.links]), indent=2))
        else:
            mode = {"arm": "armed", "disarm": "disarmed", "low-power": "low_power"}[args.command]
            print(json.dumps(client.set_zone_mode(args.zone, mode).to_public_dict(), indent=2))
    except JvaError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
