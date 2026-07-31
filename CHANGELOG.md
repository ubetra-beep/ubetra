# Changelog

All notable changes to UBETRA are documented here.
Versioning follows SemVer while the app is in **beta (`0.x`)**. `1.0.0` will be tagged when the maintainer declares it ready.

## [0.75] — 2026-07-31

### Changed
- Chat encryption key is **server-shared** per dynamic (same pattern as the shared AI key) — turn it on once; every signed-in device syncs automatically
- Settings copy: “Encrypted chat (shared key)” (honest: the server can decrypt; no more redeem codes required for new phones)

### Fixed
- Multi-device encrypted chat no longer depends on one-time share/redeem codes

## [0.74] — 2026-07-31

### Fixed
- Web Push chat notifications failed silently (VAPID PEM passed incorrectly to pywebpush; library incompatible with current cryptography)
- Push TTL was `0`, so Android/FCM could drop messages when the device was briefly unreachable
- Failed push sends no longer wipe valid subscriptions (only real stale endpoints are removed)

### Changed
- Upgrade `pywebpush` to 2.3.0; write VAPID private key to a PEM file for signing
- Skip OS notification banners when that chat is already open and visible (in-app refresh still runs)
- Service worker cache `ubetra-v74`

## [0.1.1] — 2026-07-31

### Changed
- Chat server cache default is **30 days** (was 24 hours when history was off), so offline devices and extra logged-in phones can sync
- New dynamics default to timed server cache (30 days) instead of forever; “keep forever” remains available
- E2E: do not mint a second encryption key on a new device (redeem from a working device instead)

## [0.1.0] — 2026-07-31

### Added
- Initial public beta release for self-hosting
- FastAPI backend + static PWA frontend (no frontend build step)
- Dynamics, chat (optional E2E), tracking, chastity, tasks, AI assistant
- Native Python run scripts and Docker Compose
- Shared AI key per dynamic, Dom/sub settings policy, Ko-fi support link in-app
