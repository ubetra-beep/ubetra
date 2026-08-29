"""HTTP smoke checks against a running UBETRA (http://127.0.0.1:8000).

Used by GitHub Actions. MFA must be off and public registration on.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
API = BASE + "/api"


def req(method: str, path: str, data=None, token: str | None = None, prefix: str = API):
    body = None if data is None else json.dumps(data).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        prefix + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return {"status": resp.status}
            if resp.headers.get_content_type() == "application/json":
                return json.loads(raw)
            return {"status": resp.status, "bytes": len(raw)}
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(), file=sys.stderr)
        raise


def wait_healthy(tries: int = 60) -> None:
    last = None
    for _ in range(tries):
        try:
            payload = req("GET", "/health")
            if payload.get("status") == "ok":
                return
            last = payload
        except Exception as exc:
            last = exc
        time.sleep(1)
    raise SystemExit(f"server did not become healthy: {last}")


def main() -> None:
    wait_healthy()
    print("health ok")

    home = req("GET", "/", prefix=BASE)
    assert home.get("bytes", 0) > 100, home
    print("index ok")

    js = req("GET", "/assets/app.js", prefix=BASE)
    assert js.get("bytes", 0) > 1000, js
    print("app.js ok")

    updates = req("GET", "/app/updates")
    assert "local_version" in updates and "asset_version" in updates, updates
    print("updates", updates.get("local_version"), updates.get("asset_version"))

    dom = req(
        "POST",
        "/auth/register",
        {"username": "cidom", "email": "ci-dom@example.com", "password": "secret12"},
    )
    assert dom.get("access_token"), dom
    print("register dom ok")

    dyn = req(
        "POST",
        "/dynamics",
        {"name": "CI dynamic", "role": "dominant"},
        token=dom["access_token"],
    )
    assert dyn.get("invite_code") and dyn.get("id"), dyn
    print("dynamic", dyn["invite_code"])

    req(
        "POST",
        "/onboarding/features",
        {"enabled_optional": ["org_tracking", "chastity", "tasks", "scene_workshop"]},
        token=dom["access_token"],
    )
    print("features ok")

    sub = req(
        "POST",
        "/auth/register",
        {"username": "cisub", "email": "ci-sub@example.com", "password": "secret12"},
    )
    joined = req(
        "POST",
        "/dynamics/join",
        {"invite_code": dyn["invite_code"], "role": "submissive"},
        token=sub["access_token"],
    )
    assert len(joined.get("partners") or []) >= 2, joined
    print("partners", len(joined["partners"]))

    interests = req("GET", f"/dynamics/{dyn['id']}/interests", token=dom["access_token"])
    cats = interests.get("categories") or []
    assert cats and cats[0].get("interests"), interests
    print("kink catalog", len(cats), "categories")

    print("ci smoke passed")


if __name__ == "__main__":
    main()
