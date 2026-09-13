#!/usr/bin/env python3
"""Find exactly one recipient-specific verification message without printing its body."""

import json
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen


def main() -> int:
    arguments = sys.argv[1:]
    wait_seconds = 0
    if len(arguments) == 3 and arguments[0] == "--wait-seconds":
        try:
            wait_seconds = int(arguments[1])
        except ValueError:
            wait_seconds = -1
        arguments = arguments[2:]
    if len(arguments) != 1 or not arguments[0] or wait_seconds < 0 or wait_seconds > 300:
        print("usage: mailpit-find-verification.py [--wait-seconds 0..300] <test-email>", file=sys.stderr)
        return 2
    query = urlencode({"query": f"to:{arguments[0]}", "limit": "10"})
    url = f"http://127.0.0.1:8025/api/v1/search?{query}"
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            with urlopen(url, timeout=5) as response:  # noqa: S310 -- fixed loopback origin
                payload = json.load(response)
        except OSError:
            print("Could not reach the loopback Mailpit API.", file=sys.stderr)
            return 1
        messages = payload.get("messages", payload.get("Messages", []))
        matches = [message for message in messages if message.get("Subject", message.get("subject")) == "Email verification"]
        if len(matches) == 1:
            message_id = matches[0].get("ID", matches[0].get("id"))
            if not isinstance(message_id, str) or not message_id:
                print("Mailpit returned a verification message without an ID.", file=sys.stderr)
                return 1
            print("Verification message found in loopback Mailpit UI; message ID:", message_id)
            print("Open http://127.0.0.1:8025 and inspect only that message ID.")
            return 0
        if time.monotonic() >= deadline:
            print("Expected exactly one verification message for that recipient before timeout.", file=sys.stderr)
            return 1
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
