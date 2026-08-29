# Changelog

All notable changes to UBETRA are documented here.
Versioning follows SemVer while the app is in **beta (`0.x`)**. `1.0.0` will be tagged when the maintainer declares it ready.

## [1.09] — 2026-08-29

### Added
- Labeled **Chat with Assistant** on Tracking, Playtime, Chat, chastity, orgasm log, and tasks, plus full-page `/assistant/chat`
- Seeded confirm-to-apply cards on **What can assistant do?** (no model wait)
- Agent **permissions** (ask / session / always / deny) for Assistant mutations
- **Changes from chat** log after each Apply
- Coaching subjects: goal coach, feature audit, orgasm/chastity review, tease, punishment, service
- Apply types: standing target create, gift goal edit, optional feature toggle, punishment task
- Per-screen [context maps](wiki/Context-maps.md): catalog of all areas, live packs only for the current key
- Partner Chat and Assistant **clear-all → 7-day trash**, then permanent delete; Recover in Chat ⋯ / Privacy / Assistant Chat tools
### Changed
- Assistant bubble is labeled, **draggable**, and hide/show from the bubble ×, edge tab, hub ☰, Chat ⋯, or Settings
- Assistant chat sends indexed packs instead of a full context dump on every follow-up turn
- Service worker cache `ubetra-v141`
- Chat hub uses the Assistant bubble only (no large banner); composer sits flush above the nav
- Punishment Recent is collapsed; rows are yellow (pending), blue (task/goal assigned), pink (remind tomorrow), pale grey (covered)
- Assistant bubble turns teal on screens it can coach; tap opens a page-context chat instead of the full subject list
- Clear-all is available to both partners (legacy keyholder-only checkbox no longer blocks it)
### Fixed
- Running image no longer hides the only Assistant entry behind a missing LLM key
- `currentRoute is not defined` blocked sending Assistant chat from most screens

## [1.08] — 2026-08-28

### Added
- **Assistant Domme** keyholder chat bubble with indexed subjects, page context, and confirm-to-apply suggestions
- Triggers for confessions, task drought, orgasm balance, lockup trend, inbox, journals, and gift-goal progress
- Standing weighted **Goals & balance** targets (current vs previous window vs target)
- Interview **table** when AI is off or no key is configured
- Manual act-type catalog when generate is unavailable
### Changed
- AI-only controls hide (instead of dim) when AI is off
- Playtime hub still offers Tasks, Instructor, and games without an LLM key
- Service worker cache `ubetra-v138`
### Fixed
- Interview complete no longer requires an LLM summary in no-AI mode

## [1.07] — 2026-08-17

### Added
- Playtime **Instructor**: local-files Fap Instructor (HUD controls, task mode, warmup / I'm ready) using redgifs playlists
- Keyholder-locked Instructor config, assign-as-task, live pause / red light / lock
- Shared media tree bind-mount (`UBETRA_REDGIFS_HOST`, default `/home/james/vault/redgifs`); each subdirectory is a playlist
- Instructor: Domme can view the sub's camera split above the media, stream their own camera to the sub, switch cameras, and record sub / domme / both (off by default)
### Changed
- Web play / server Chromium is gone. https links open in the phone browser
- In-app **Wiki** lives under Settings → Help (not Playtime)
- Docker image no longer ships Playwright, Xvfb, Pulse, or jellyfin-ffmpeg
- Service worker cache `ubetra-v137`
- Password reset also pushes a code/link to registered devices (primary when SMTP is off)
- Instructor overlay uses the controlling partner's name; Domme controls sit in a collapsible left sidebar
- Beat meter keeps a steady scroll speed and changes density with stroke speed
### Fixed
- Instructor metronome now unlocks audio on Start so ticks are audible
- Instructor no longer opens itself when the app launches; it only starts from Playtime (or a task)
- Sub camera stays off until the Domme turns it on (wakes the sub with a call-priority push; tap opens the Android app)
- Instructor media stays blank until the sub taps Warm up or I'm ready
- Domme Exit can end the sub's game or leave them playing; End now actually closes the sub overlay
- Beat meter stays synced to the metronome, fills the right side at slow speeds, pulses on the hit, and fades on the left
- Metronome pitch rises with stroke speed
### Removed
- Remote browser WebSocket encoder and kiosk streaming

## [1.06] — 2026-08-17

### Added
- Tasks & acts → **Build training regimen**: a conversational keyholder assistant that reviews existing task tags, offers extra tags, then drafts selectable daily and weekly task lists to assign
- Training regimen: due-by time of day on each idea (and a group default); assigned recurring tasks are no longer due “now”
- **Completed on** on the task popup (sub and keyholder), with On time / Now shortcuts so overdue work can still log as finished on time
- Wiki troubleshooting maps: **Workflows**, **Feature map**, and **AI context** (flowcharts; mermaid in the in-app wiki)

### Changed
- Tapping the **UBETRA** title reloads the app (clears cached JS/CSS) instead of opening the old dynamic overview menu
- Training regimen assistant history is collapsed at the bottom as **Assistant history**
- Tapping a missed task opens the same task popup as a task link, instead of jumping to Request make-up
- Training regimen: skip the opening tag interview; extra tags live in a Help generate submenu. Recommended tasks start collapsed — check to accept, expand to edit
- Training regimen groups are titled Daily/Weekly (plus tag), not after a task; existing assigned tasks and current drafts are sent to the assistant so it does not re-suggest them; **Generate more ideas** appends extra tasks
- Health / Hygiene regimen ideas include physical workouts as well as hygiene

## [1.05] — 2026-08-16

### Fixed
- Due times and other logged times follow the user’s timezone (stored IANA zone + UTC `Z` on the API), so 7:00 AM local no longer shows as 2:00 PM
- Subs can complete overdue tasks (logged as late) instead of being locked out
- Web play: Android black screen when H.264 fails or falls back to JPEG; phone drags now scroll to the bottom of long pages (FapInstructor start button)
- Ending a video call hangs up both sides (faster poll + connection-loss hangup)
- In-call text chat works with end-to-end encryption on
- In-call Web play button; self camera can be dragged; smart censor only blurs what the sub sees

### Added
- Task create/edit due-by presets (1 hour, 8 hours, 24 hours, 3 days, 1 week, 2 weeks, or pick a time)
- Keyholder inbox for “task completed late” with punishment task, goals adjustment, or close
- Push to the sub when a task is added or becomes available, due-soon (configurable lead time), and Remind me in X (repeat until due)
- Android `ubetra_tasks` notification channel (separate sound from chat/calls)
- Settings → Playtime: task notifications and smart censor (off / auto / on-device / CUDA preference)

## [1.04] — 2026-08-16

### Fixed
- Feelings check-ins no longer spam the “While you were away” popup on every return

### Added
- Settings → Feelings notifications: after-play wheel prompt, return overlay, end-of-day reminder, and soft/hard mode

## [1.03] — 2026-08-15

### Fixed
- Tasks open into a detail sheet (complete, edit, delete) instead of dumping you in All lists
- Sub requests show as “Robot_boy requested” (the requester’s name)
- Task due and completed times use local time, not UTC
- Future-due tasks appear in Open and can be completed; only past-due tasks stay locked for the sub

### Added
- Keyholder can edit or delete any task; sub can request an edit or removal
- Completed tasks keep a local timestamp
- Settings → Playtime → Auto punish: missed tasks bump a goal by tag, or alert the keyholder if that tag has no rule
- Task AI assist prompts (sexualize, more fun, more degrading, ritual, specific, softer)
- Settings → AI: one “what to share with AI” list, plus a non-AI mode (AI controls stay visible but grey)
- Journal now includes the context library in collapsed sections with counts

## [1.02] — 2026-08-14

### Fixed
- Android app now declares Camera and Microphone, so the OS can prompt instead of failing silently on photos, clips, and video calls
- In-app camera and recorder let you pick front / rear (PWA and Android)

### Added
- Keyholder can force a camera session, choose the sub’s front or rear camera, and control flashlight (with brightness on Android 13+)
- Settings → This device → Permissions: Allow buttons plus how-tos (notifications, DND, battery, dedicated phone)
- Android APK `0.86` (install this build for camera prompts and flashlight)

## [1.01] — 2026-08-14

### Changed
- Kiosk remote desktop is now H.264 (NVIDIA NVENC when the host GPU is available, otherwise fast CPU encode) instead of JPEG screenshots, so phones and PC stay in sync
- Service worker cache `ubetra-v116`

### Fixed
- Android kiosk black screen from stale JPEG packet parsing
- PC kiosk going white / lagging on the old screenshot stream

## [1.00] — 2026-08-14

### Fixed
- Kiosk stream lag: smaller frames, drop stale JPEGs, stop screenshot fallback from fighting the live picture
- Audio/video sync: sound is delayed to the picture instead of playing ahead

## [0.99] — 2026-08-14

### Fixed
- Kiosk sound: Chromium was running in headless-shell (no audio). It now runs a real browser on a virtual display and taps page/Web Audio so games like FapInstructor can play on the phone

## [0.98] — 2026-08-14

### Fixed
- Kiosk sound (PCM alignment + capture Chromium output so YouTube/other sites can play on the phone)
- Phone swipe scrolls the page instead of selecting text
- PC mouse clicks links and buttons

### Added
- Viewport follows whoever is driving; **My screen** forces a fit; tap/click takes over
- Keyholder **Block sub** button in the kiosk bar

## [0.97] — 2026-08-14

### Fixed
- Kiosk page now matches the phone window instead of a 1280×720 desktop box, so taps land on the right controls
- Server browser presents as the phone’s Chrome (touch, size, timezone) and keeps cookies so captchas are less frequent after the first solve

## [0.96] — 2026-08-14

### Fixed
- Open in kiosk black screen (PWA and Android): overlay crashed before connecting, so Back/Close did nothing
- Server browser now sends a screenshot if live frames do not arrive

## [0.95] — 2026-08-14

### Added
- In-app kiosk uses a server-side Chromium browser streamed to phones (host speakers stay muted)

## [0.94] — 2026-08-14

### Added
- Video calls, in-app camera capture, and vault video clips

## [0.93] — 2026-08-14

### Added
- Settings **!** badge when GitHub has a newer `VERSION` than this server, with a link to the repo and changelog
- Android APK users get a **!** and a one-time download popup when a newer APK is on the server
- In-app kiosk browser: GitHub wiki (rendered in-app), chat link previews, and a browse log for the keyholder / assistant
- Playtime **Web play**: add timed web sessions (e.g. FapInstructor) and assign them as tasks

### Changed
- Service worker cache `ubetra-v108`

## [0.92] — 2026-08-13

### Changed
- While you were away: tapping an item (including Punishment needed) closes the overlay and opens it; **Remind me tomorrow** snoozes pending confessions
- Confession detail is a short choice: assign a task (task creator + optional assistant ideas) or add/edit a goal
- Task creation moved from the Playtime hub into **Tasks & acts**; optional due-by date; at least one category tag required; Punishment tag is preselected from a confession
- Goals live under Playtime → Tasks & acts (Goals tab)
- Service worker cache `ubetra-v106`

## [0.91] — 2026-08-13

### Added
- Punishment confessions: set a new chastity goal (type, requirements, start now/rolling) or assign a task — both work even when there are no existing goals

### Changed
- Service worker cache `ubetra-v103`

## [0.90] — 2026-08-13

### Fixed
- Punishment confessions with no active chastity goals were stuck: the Domme could see pending items but could not assign, close, or snooze them
- Confession detail now always offers a task, assistant ideas, remind-tomorrow, and “I've got it covered”, even when there are no goals

### Changed
- Service worker cache `ubetra-v102`

## [0.89] — 2026-08-13

### Added
- **Cycle tracking** (opt-in, partner-enableable): manual flow/symptoms log; partner can view; Health Connect menstruation import on Android
- **Health Connect** (Android APK): on-device sleep and cycle sync from Samsung Health, Fitbit, Pixel Watch, and other apps that write to Health Connect — not Google Fit cloud OAuth
- Sleep history window: sync from the dynamic’s first log (not a hardcoded 14 days); “past data” / history permission for older nights
- Days in chastity calendar: sleep rings (hours + locked/unlocked) and sex-tag dots (denied/milking, ruined, full orgasm)
- Chat **bubble color** per person (applies immediately; saved on the membership)
- Edit and delete your own chat messages (image delete also removes the vault copy)
- Style-aware PWA / home-screen **bird icons** (violet, sage, midnight, ember, cream); asked on install and in Appearance
- In-app **Android APK** download (`/apk/ubetra.apk`, Settings card); persistent signing keystore on the server
- Capacitor plugin `@ubetra/health-connect` and APK **0.85** (sleep-only vs cycle-only permission requests)

### Changed
- Sleep page: collapsible log-cards like tracking; sessions within 6 hours awake are one night (hours summed, gaps omitted)
- Health Connect sleep sync no longer requires Cycle / Menstruation permission
- Sleep list loads a much longer history so nights can be grouped
- Vault delete of a chat-sourced image also deletes the chat message (and sibling vault copies)
- Docker Compose bind-mounts `mobile/dist` so the published APK is served from the container
- Service worker cache `ubetra-v101`

### Fixed
- Chat bubble color swatches now paint live (not only after Save); tints are strong enough to see
- Sleep sync failing when cycle tracking / menstruation wasn’t granted
- APK sideload / Play Protect notes and DownloadManager handling in the WebView

## [0.88] — 2026-08-05

### Fixed
- Manga panel ↔ comic SQLAlchemy relationship (app would not start)

### Changed
- Wiki refreshed with seeded WikiDom/WikiSub demo data, new screenshots, and a Features & Settings guide
- Service worker cache `ubetra-v88`

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
