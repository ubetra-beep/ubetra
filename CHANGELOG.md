# Changelog

All notable changes to UBETRA are documented here.
Versioning follows SemVer while the app is in **beta (`0.x`)**. `1.0.0` will be tagged when the maintainer declares it ready.

## [0.87] — 2026-08-05

### Added
- Prior orgasm CSV import: preview rows (and errors) before confirm; success message after import

### Changed
- Artebu orgasm CSV partners: JustJim → Robot_Boy
- Service worker cache `ubetra-v87`

## [0.86] — 2026-08-05

### Added
- Clear chat from Chat ⋯ menu (anyone by default; Settings → Privacy can limit to keyholder)
- Images-off chat still shows an **Open in vault** link for each photo
- Vault image deletions are always logged in chat; any partner can delete

### Fixed
- Chat typing bar / UBETRA top bar staying visible (chat scrolls inside the message list only)

### Changed
- Service worker cache `ubetra-v86`

## [0.85] — 2026-08-05

### Added
- Multiple AI connections (text / adult / images) with Batch test probes (text, NSFW text, image, NSFW image)
- Advanced AI routing: assign services per tool; red labels + recommendations when unassigned
- Circled (!) badges on AI tools that need configuration (tap for fix summary)

### Changed
- Service worker cache `ubetra-v85`

## [0.84] — 2026-08-05

### Added
- Chastity timeline: **Eventual Release** on active terms (`?` by default; Dom can share planned end → “release in N days”)
- Historical CSV: `event` column with **lock** and **unlock** rows (pauses with tags), matching Artebu-style history
- Sleep unlock tag / break type; Hygiene label no longer says “(emergency)”

### Changed
- Unlock reasons are tags (same chips on the timeline; no separate reason vs tags fields)
- Service worker cache `ubetra-v84`

## [0.83] — 2026-08-05

### Added
- Forgotten password: email one-time code **and** reset link; Settings → Change password
- AI providers: OpenRouter, LM Studio, OpenAI-compatible (with base URL) + stronger adult-content help text
- Sleep tracking (default off; either partner can enable): manual log + Google / Garmin OAuth sync; Apple via iOS HealthKit bridge
- Playtime → Monthly manga (default off): script / hybrid / full panel modes with provider warnings; one comic per month

### Changed
- Service worker cache `ubetra-v83`
- Optional features can opt out of default-on (`sleep_tracking`, `manga_comics`)

## [0.82] — 2026-08-05

### Changed
- Bottom nav uses 3 equal columns (Tracking / Playtime / Chat) — no left cluster
- Tasks & acts moved from Tracking to Playtime; Sub “Request a task” is on Playtime (removed from Chat menu)
- Chat typing indicator shows once (bubble only)
- Service worker cache `ubetra-v82`

## [0.81] — 2026-08-05

### Fixed
- Chat typing indicator: partner “three dots” now appears as a chat bubble (and above the composer), with a longer presence TTL and faster polling

### Changed
- Service worker cache `ubetra-v81`

## [0.80] — 2026-08-04

### Added
- Color themes (Midnight, Ember, Forest, Slate) in Settings → Appearance; stored on-device
- Task make-up flow: Sub requests, Dom grants/denies, optional Domme assist note
- Dom pause / edit / bulk actions for recurring tasks; task category tags (Domestic · Health / Hygiene · Sensual · Sexual)
- Goals: optional tag filter on “Tasks completed” requirements

### Changed
- Top bar uses safe-area inset; Settings is an accent hamburger; Log out lives under Settings → Account
- Install app hidden when already running as PWA or native Capacitor app
- Tasks Tracking: expandable Open / Missed timelines; calendar card and Google Tasks UI hidden
- Overdue bucketing uses `next_due_at || due_at`; daily series not shown as due for tomorrow
- Service worker cache `ubetra-v80`

### Fixed
- Core Knowledge populate-from-interview 500 (missing imports + None-safe strips)

## [0.79] — 2026-08-04

### Added
- In-app **Android Chrome / Edge setup tips** after enabling Notify this device
- Capacitor Android APK scaffold (`mobile/`) with native FCM registration, `ubetra_chat` + `ubetra_calls` channels (DND bypass ready for calling)
- Server support for native FCM tokens (`POST /api/push/native`) via Firebase service-account env

### Changed
- Web Push sends with `Urgency: high`; service worker uses `requireInteraction` and louder vibration
- Service worker cache `ubetra-v79`

## [0.78] — 2026-08-04

### Fixed
- Chat hub now has its own Application features hamburger (settings stay on ⋯)
- Context library: Visible to partner toggle on create/edit (matched journals)
- Turning off “Notify this device” no longer disables push / wipes subscriptions on every other phone
- Push re-syncs on app resume and when FCM rotates the subscription (`pushsubscriptionchange`)
- Domme journal review can optionally post a note to Chat
- Log cards: tags/metadata only when expanded; clearer orgasm spacing

### Changed
- Service worker served with `Cache-Control: no-cache`; cache `ubetra-v78`
- `.env.example` documents `UBETRA_VAPID_CONTACT`

## [0.77] — 2026-08-01

### Added
- Journal gets its own page (Tracking → Journal) with a private/shared toggle, an AI-context hamburger (choose journals/stories/scenes/agreements/tracking), Assist with AI, and a Dom-only "Domme review"
- Scene builder has the same AI-context hamburger so the keyholder controls what feeds each generated scene
- In-app camera capture (getUserMedia) for Chat and the Image vault — falls back to the OS camera picker if unavailable
- Chat settings menu: Sub can "Request a task" without leaving the conversation (removed from Playtime)
- Tracking and Playtime hubs share a header with an "Application features" hamburger; Tracking has a collapsed Setup/Dynamic section for ground rules, interview, kink list, knowledge, context library, and gear
- Log cards redesigned: collapsed by default (name, relative time, colored accent stripe, type pill), a kebab menu for Edit/Delete, and primary vs. secondary tag chips

### Changed
- Context library files and journal entries support a partner-visibility toggle; hidden entries show as "Private entry" to the other partner but still count for their own AI context
- `renderFeatureSettings` renamed to "Application features"; a Sub can now submit a settings-change request from that page instead of only the hamburger
- Signing in with a dynamic now opens Tracking directly instead of the Dynamic overview

### Changed
- Service worker cache `ubetra-v77`

## [0.76] — 2026-07-31

### Changed
- Chastity: no enrollment approval — feature on means Subs can track; Dom can force-disable a Sub or turn off the module
- Chastity tags are empty by default and shared; custom tags become permanent presets
- Chat/vault: Take photo camera capture; images encrypt with the shared chat key when Encrypted chat is on
- New browsers default blurred photos to hold-to-view (existing installs keep their mode)
- Context library: server file uploads + journaling replace Google Drive links; subject tags (stories / journals / scenes) and Use for AI
- Playtime scenes can be saved into the context library

### Added
- Orgasm/play prior-history CSV template + import (with example default tags)

### Changed
- Service worker cache `ubetra-v76`

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
