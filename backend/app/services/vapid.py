from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ..config import DATA_DIR, settings

_VAPID_PATH = DATA_DIR / "vapid.json"
_VAPID_PEM_PATH = DATA_DIR / "vapid_private.pem"
_keys: dict[str, str] | None = None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _generate_vapid_keys() -> dict[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_numbers = private_key.public_key().public_numbers()
    x = public_numbers.x.to_bytes(32, "big")
    y = public_numbers.y.to_bytes(32, "big")
    public_raw = b"\x04" + x + y
    return {
        "private_key": private_pem,
        "public_key": _b64url(public_raw),
        "contact": settings.vapid_contact,
    }


def _write_pem_file(private_pem: str) -> None:
    """pywebpush only accepts PEM via filesystem path (or a Vapid object).

    Passing the PEM string uses Vapid.from_string(), which expects raw/DER
    material and raises ASN.1 errors — so pushes never leave the server.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _VAPID_PEM_PATH.write_text(private_pem, encoding="utf-8")


def ensure_vapid_keys() -> dict[str, str]:
    global _keys
    if _keys is not None:
        return _keys

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _VAPID_PATH.exists():
        _keys = json.loads(_VAPID_PATH.read_text(encoding="utf-8"))
        # Prefer configured contact over legacy localhost placeholder.
        contact = (_keys.get("contact") or "").strip()
        if not contact or contact.endswith("@localhost") or contact == "mailto:ubetra@localhost":
            _keys["contact"] = settings.vapid_contact
            _VAPID_PATH.write_text(json.dumps(_keys, indent=2), encoding="utf-8")
        _write_pem_file(_keys["private_key"])
        return _keys

    _keys = _generate_vapid_keys()
    _VAPID_PATH.write_text(json.dumps(_keys, indent=2), encoding="utf-8")
    _write_pem_file(_keys["private_key"])
    return _keys


def vapid_public_key() -> str:
    return ensure_vapid_keys()["public_key"]


def vapid_private_key() -> str:
    """Return path to the VAPID private key PEM file (for pywebpush)."""
    ensure_vapid_keys()
    return str(_VAPID_PEM_PATH)


def vapid_contact() -> str:
    return ensure_vapid_keys().get("contact") or settings.vapid_contact


def is_configured() -> bool:
    try:
        ensure_vapid_keys()
        return True
    except Exception:
        return False
