"""One-time migration from users.json to the configured MySQL database."""

from __future__ import annotations

import json
from pathlib import Path

import game


def main() -> None:
    if not game.MYSQL_ENABLED:
        raise SystemExit("Set MYSQL_HOST, MYSQL_USER and MYSQL_DATABASE first.")

    source = Path(__file__).with_name("users.json")
    if not source.exists():
        raise SystemExit(f"Account file not found: {source}")

    payload = json.loads(source.read_text(encoding="utf-8"))
    users = payload.get("users")
    if not isinstance(users, dict):
        raise SystemExit("Invalid users.json format.")

    for key, account in users.items():
        account.setdefault("friends", [])
        account.setdefault("friendRequests", [])

    game.ensure_mysql_schema()
    game.ACCOUNTS = users
    game.save_accounts()
    print(f"Migrated {len(users)} accounts to MySQL.")


if __name__ == "__main__":
    main()
