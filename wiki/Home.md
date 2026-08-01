# UBETRA Wiki

**UBETRA** is a self-hosted Progressive Web App for consensual adult D/s relationship dynamics. Couples (or “dynamics”) plan, track, chat, and optionally use AI assist — on hardware they control.

This wiki covers features and day-to-day workflows. Screenshots were captured from a local demo with test accounts **WikiDom** (Dominant) and **WikiSub** (Submissive).

> **Adult content:** Features include chastity, orgasm tracking, kink lists, punishments, and acts of submission. Descriptions are matter-of-fact, not graphic.

---

## Quick links

| Page | What it covers |
|------|----------------|
| [Getting Started](Getting-Started) | Install, first login, PWA |
| [Onboarding](Onboarding) | Create/join dynamic, AI key, SPTI, kink survey |
| [Dynamics](Dynamics) | Overview, ground rules, interview, knowledge, gear (now under Tracking → Setup) |
| [Tracking](Tracking) | History, chastity, orgasm log, feelings, punishment, tasks, journal, vault |
| [Chat](Chat) | Messaging, encryption, push, images |
| [Playtime](Playtime) | Assistant, scene builder, spin game |
| [Settings](Settings) | Account, privacy, AI, features, backup |
| [Roles & Permissions](Roles-and-Permissions) | Dom vs Sub, approvals |
| [Self-Hosting](Self-Hosting) | Docker/native config, HTTPS, env vars |

---

## Mental model

1. You create an **account** (email + username + password).
2. You create or join a **dynamic** (shared space for one Dom/Sub partnership).
3. Bottom nav switches between **Tracking**, **Playtime**, and **Chat**. [Dynamics](Dynamics) content (ground rules, interviews, knowledge, gear) lives inside the Tracking hub's collapsed **Setup / Dynamic** section rather than its own tab.
4. **Settings** is global; many couple preferences live on the dynamic.
5. Some settings are **Dom-controlled** — a Sub submits a change request instead of applying it directly, including **Application features**.

![Sign in](images/00-login.png)

---

## Version

Docs match app **v0.77** (Tracking/Playtime hub redesign, private journals with AI context controls, in-app camera, redesigned log cards). See the [CHANGELOG](https://github.com/ubetra-beep/ubetra/blob/main/CHANGELOG.md) on GitHub.
