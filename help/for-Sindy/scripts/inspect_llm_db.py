#!/usr/bin/env python3
"""Print account vs shared LLM fields. Never prints full API keys."""
from __future__ import annotations

import os
import sqlite3
import sys


def mask(key: str | None) -> str:
    raw = (key or "").strip()
    if not raw:
        return "(empty)"
    if len(raw) <= 8:
        return "••••"
    return f"••••{raw[-4:]}"


def main() -> int:
    db_path = os.environ.get("UBETRA_DB", "/app/backend/data/ubetra.db")
    if not os.path.isfile(db_path):
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    print(f"db: {db_path}\n")
    print("=== users (account LLM) ===")
    users = con.execute(
        """
        SELECT id, username, email,
               llm_provider, llm_model, llm_api_key, llm_base_url
        FROM users
        ORDER BY username
        """
    ).fetchall()
    if not users:
        print("(no users)")
    for u in users:
        key = u["llm_api_key"] or ""
        print(
            f"- {u['username'] or '(no name)'}  email={u['email'] or ''}\n"
            f"    provider={u['llm_provider'] or '(unset)'}  model={u['llm_model'] or '(unset)'}\n"
            f"    api_key_set={'yes' if key.strip() else 'no'}  hint={mask(key)}\n"
            f"    base_url={((u['llm_base_url'] or '').strip() or '(default)')}"
        )

    print("\n=== dynamics (shared LLM) ===")
    # Column names differ slightly across older DBs; probe pragmas.
    cols = {r[1] for r in con.execute("PRAGMA table_info(dynamics)").fetchall()}
    need = {
        "id",
        "name",
        "shared_llm_provider",
        "shared_llm_model",
        "shared_llm_api_key",
    }
    if not need.issubset(cols):
        print(f"Missing expected columns on dynamics: {sorted(need - cols)}")
        return 1

    has_base = "shared_llm_base_url" in cols
    sql = """
        SELECT id, name, shared_llm_provider, shared_llm_model, shared_llm_api_key
        {base}
        FROM dynamics
        ORDER BY name
    """.format(base=", shared_llm_base_url" if has_base else "")
    for d in con.execute(sql).fetchall():
        key = d["shared_llm_api_key"] or ""
        base = ""
        if has_base:
            base = (d["shared_llm_base_url"] or "").strip()
        print(
            f"- {d['name'] or '(unnamed)'}  id={d['id']}\n"
            f"    shared_provider={d['shared_llm_provider'] or '(unset)'}  "
            f"shared_model={d['shared_llm_model'] or '(unset)'}\n"
            f"    shared_api_key_set={'yes' if key.strip() else 'no'}  hint={mask(key)}\n"
            f"    shared_base_url={(base or '(empty)')}"
        )

    print("\n=== memberships (who is in which dynamic) ===")
    try:
        rows = con.execute(
            """
            SELECT m.dynamic_id, m.role, m.display_name, u.username
            FROM memberships m
            JOIN users u ON u.id = m.user_id
            ORDER BY m.dynamic_id, m.role
            """
        ).fetchall()
    except sqlite3.Error as exc:
        print(f"(skip memberships: {exc})")
        return 0
    for r in rows:
        print(
            f"- dynamic={r['dynamic_id'][:8]}…  role={r['role']}  "
            f"user={r['username']}  display={r['display_name'] or ''}"
        )

    print(
        "\nHint: Test with ?dynamic_id=… uses that dynamic's shared key when set "
        "(or shared_provider+shared_base_url). Account key alone is not enough if "
        "shared is only half-configured."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
