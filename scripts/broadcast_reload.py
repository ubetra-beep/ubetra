#!/usr/bin/env python3
"""Push kind=reload to every account (run inside the ubetra container after deploy)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/app/backend")
os.chdir("/app")

from app.database import SessionLocal  # noqa: E402
from app.services.push import broadcast_app_reload  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        result = broadcast_app_reload(
            db,
            title="UBETRA update",
            body="Refreshing to load the latest version…",
        )
        print(f"reload broadcast: users={result['users']} devices={result['devices']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
