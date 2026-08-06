# Features & Settings

This page is the map of **what UBETRA can do** and **where you configure it**. Screenshots use the WikiDom / WikiSub demo.

![Settings — Dom](images/20-settings.png)

![Settings (scrolled)](images/21-settings-lower.png)

---

## Three hubs (bottom nav)

| Hub | Purpose | Typical use |
|-----|---------|-------------|
| **Tracking** | Day-to-day logs and status | History, chastity, orgasm/play log, feelings, sleep, punishment, journal, vault; Setup / Dynamic at the bottom |
| **Playtime** | Games, AI scenes, tasks | Scene builder, spin the wheel, tasks & acts, monthly manga (opt-in) |
| **Chat** | Conversation + activity feed | Messages, photos, system logs (lockups, tracking, settings approvals) |

Each hub’s **☰** opens **Application features** for that area (same toggles as Settings → Features).

---

## Application features (optional modules)

**Always on (core):** Ground rules · Dynamic interview · Kink list · Core knowledge · History

| Feature | Default | How partners use it |
|---------|---------|---------------------|
| Sex & orgasm tracking | On | Log orgasms / no-orgasm play with tags; Dom configures fields/metrics; CSV prior-history import with preview |
| Chastity tracking | On | Lock/unlock, hygiene & sleep breaks, Eventual Release, historical CSV |
| Feelings | On | Wheel check-ins before/after play or end of day |
| Punishment | On | Sub confesses; Dom assigns / resolves |
| Tasks & acts | On | Dom creates tasks; Sub requests tasks; make-up flow; acts after interview |
| Image vault | On | Private copies of chat photos; anyone can delete (logged); images-off chat still links here |
| Journal | On | Private writing; **Use for AI** + **Visible to partner** per entry |
| Playtime / scene workshop | On | AI scenes and spin game (needs LLM key + interview) |
| SPTI profile | On | Paste personality results for AI context |
| Context library | On | Files/links tagged for AI |
| Gear | On | Toys / outfits inventory |
| Sleep tracking | **Off** | Manual log + Google / Garmin / Apple HealthKit; either partner can enable |
| Monthly manga | **Off** | One comic/month; either partner can enable |

Dom-controlled for most toggles; sleep/manga are partner-enableable.

---

## Settings sections (how to utilize)

### Account
Change username, email, password; log out. Dom may rename the Sub’s username for the dynamic.

### Appearance
Device theme (Midnight, Ember, Forest, Slate) — local to this browser/app.

### Dynamics
Pick the active dynamic, create another, or copy invite context.

### AI & assistant
- Add **named AI connections** (Gemini, OpenAI, OpenRouter, LM Studio, OpenAI-compatible).
- **Batch test** probes text / NSFW text / image / NSFW image.
- **Advanced AI routing** assigns a connection per tool; red labels mean “needs a service.”
- Dom sets assistant **tone** and extra instructions (Sub requests changes).

Use this when Playtime scenes, journal assist, Domme review, or acts need a model that allows adult content.

### Chat & privacy
| Setting | Default idea | Utilize when… |
|---------|--------------|----------------|
| Encrypted chat (shared key) | Off until you turn on | You want ciphertext at rest; every signed-in device syncs the key |
| Keep forever / server cache hours | Timed cache (~30d) | Multi-device sync vs auto-delete |
| Show activity log in chat | On | You want lockups, tracking, tasks mirrored into Chat |
| Only keyholder can clear chat | **Off** (anyone can clear) | Raise the bar so only Dom clears history |
| Blur shared images | Device preference | Quick privacy on shared screens |
| Push for this dynamic / this device | On when configured | Partner messages while the app is closed |

Chat **⋯** mirrors many of these for quick changes. **Clear chat…** deletes messages and posts a log line.

### Features
Same as Application features above — hide modules you do not use.

### Chastity policy
e.g. whether the Sub may delete temporary unlock log entries.

### Backup
Export / import JSON. Treat exports as **secret**.

---

## Dom-controlled vs request flow

When a Sub changes a Dom-controlled setting, Chat shows a **settings request** for the Dom to approve or deny. Examples: retain history, system events, clear-chat policy, feature toggles, feelings prompt mode, assistant tone.

![Settings — Sub](images/34-sub-settings.png)

---

## Suggested setup order

1. Create/join dynamic ([Onboarding](Onboarding)).
2. Enable the modules you actually use (Features).
3. Both partners: Core knowledge + interview ([Dynamics](Dynamics)).
4. Dom: ground rules; chastity settings; task list.
5. Chat privacy (encryption / logs / clear policy) and push on each phone.
6. Add an AI connection if you want Playtime / journal assist.

See also [Roles & Permissions](Roles-and-Permissions) and [Self-Hosting](Self-Hosting).
