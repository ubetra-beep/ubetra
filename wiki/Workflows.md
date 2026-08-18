# Workflows

Troubleshooting maps of how UBETRA actually runs. Open Settings → Help → Wiki → **Workflows**. Related: [Feature map](Feature-map) (how modules talk) and [AI context](AI-context) (what the model is allowed to see).

If a screen “does nothing,” start at the **spine**, then jump to the module flowchart.

---

## App spine

```mermaid
flowchart TD
  A[Create account] --> B[Create or join a dynamic]
  B --> C{Interview plus LLM key?}
  C -->|needed for Playtime AI| D[Complete interview]
  C -->|optional| E[Three hubs]
  D --> E
  E --> T[Tracking]
  E --> P[Playtime]
  E --> H[Chat]
  E --> S[Settings and Application features]
  S --> F[Optional modules on or off]
  F --> T
  F --> P
```

Core that cannot be turned off: Ground rules, Interview, Kink list, Core knowledge, History.

---

## Onboarding and first dynamic

```mermaid
flowchart TD
  R[Register / login] --> D{Have a dynamic?}
  D -->|no| C[Create dynamic as keyholder]
  D -->|invite code| J[Join as submissive]
  C --> I[Invite partner]
  J --> I
  I --> K{Need AI?}
  K -->|yes| L[Settings: AI connection]
  K -->|no| N[Hubs]
  L --> SPTI[Optional SPTI paste]
  SPTI --> SV[Kink survey]
  SV --> IV[Dynamic interview]
  IV --> CK[Submit Core knowledge]
  CK --> N
```

Stuck? Interview not finishing blocks Playtime scene builder, training regimen, and acts. SPTI is optional.

---

## Settings change as submissive

```mermaid
flowchart TD
  Sub[Sub changes a Dom-controlled setting] --> Req[Chat: settings request]
  Req --> Dom{Keyholder}
  Dom -->|Approve| Apply[Setting applies]
  Dom -->|Deny| Keep[Old value stays]
```

Dom-controlled examples: feature toggles, chat retain/clear/logs, feelings prompt mode, assistant tone, extra instructions, task push, smart censor. Sleep / cycle / manga can be enabled by either partner.

---

## Tasks: assign → due → complete

```mermaid
flowchart TD
  Create[Keyholder creates or assigns a task] --> Open[Open timeline]
  Create --> Recur{Recurring?}
  Recur -->|daily/weekly with no due time| Now[Due is now - often immediately overdue]
  Recur -->|due-by time of day| Due[next_due_at at that clock time]
  Open --> Due
  Now --> Missed[Missed / Overdue]
  Due --> Check{Clock vs due}
  Check -->|still upcoming| Open
  Check -->|past due| Missed
  Open --> Comp[Mark complete + Completed on]
  Missed --> Comp
  Missed --> MU[Request make-up]
  MU --> Grant{Keyholder grants?}
  Grant -->|yes| Comp
  Grant -->|deny| Missed
  Comp --> OnTime{Completed on at or before due?}
  OnTime -->|yes| Done[One-time: completed / Recurring: next occurrence]
  OnTime -->|no| Late[Late: inbox plus optional punish / goals]
  Late --> Done
```

Training regimen assigns recurring lists with a **due-by time of day**. A blank time falls back to 8:00 PM. Tapping the task row (or a `?task=` link) opens the same task popup with **Completed on**. Request make-up is its own button.

---

## Auto-punish vs make-up vs late complete

Three separate consequence paths can fire on the same overdue task:

```mermaid
flowchart LR
  Overdue[Overdue incomplete task] --> AP[Auto-punish rules if configured]
  Overdue --> MU[Make-up request / grant]
  Overdue --> Late[Sub marks complete late]
  Late --> Inbox[Keyholder inbox: punish / goals / ack]
```

If two of these fire, it is not a crash — it is overlapping design. Check Goals auto-punish settings, Missed make-up status, and inbox `task_completed_late`.

---

## Chastity

```mermaid
flowchart TD
  En[Chastity feature on] --> Lock[Lock up]
  Lock --> Active[Active lockup]
  Active --> Break[Hygiene / sleep break]
  Break --> Active
  Active --> ER[Eventual Release timer]
  ER --> Unlock[Unlock / end lockup]
  Active --> Unlock
  Unlock --> Feel{Feelings after-play prompt?}
  Feel -->|on| Wheel[Feelings check-in]
  Unlock --> ChatLog[System event in Chat if logs on]
```

Sub deleting a break log is a Dom-controlled setting.

---

## Sex / orgasm tracking and feelings

```mermaid
flowchart TD
  Log[Log play / orgasm] --> Hist[History calendar]
  Log --> Feel[Optional feelings check-in]
  Hist --> Hub[Tracking hub subtitles]
  Feel --> Wheel[Feelings wheel]
  Day[End of day reminder if on] --> Wheel
  Return[Return overlay if on] --> Wheel
  Wheel --> Store[Feeling check-in stored]
```

Hard feelings mode can insist on a check-in before continuing some play flows.

---

## Punishment confession

```mermaid
flowchart TD
  Con[Sub confesses] --> Rep[Punishment report]
  Rep --> Dom[Keyholder sees it]
  Dom --> Task[Assign punishment task]
  Dom --> Close[Mark covered / close]
  Task --> Lists[Tasks timeline]
```

Punishment tag is preselected when assigning from a confession.

---

## Chat, encryption, and activity logs

```mermaid
flowchart TD
  Send[Send text / image] --> E2E{Encrypted chat on?}
  E2E -->|yes| Cipher[Ciphertext on server]
  E2E -->|no| Plain[Plaintext on server]
  Cipher --> Devices[Each device uses shared key]
  Event[Lockup, tracking, task, settings] --> Sys{Show activity log in chat?}
  Sys -->|on| Feed[System line in Chat]
  Sys -->|off| Silent[Not posted]
  Clear[Clear chat] --> Who{Only keyholder can clear?}
  Who -->|yes| DomOnly[Dom only]
  Who -->|no| Anyone[Either partner]
```

Chat **messages are not sent to the AI**. Turning logs on does not add chat to model context.

---

## Playtime AI scene / spin / manga

```mermaid
flowchart TD
  Need[Interview done + AI on + Playtime feature on] --> Scene[Scene builder]
  Need --> Spin[Spin the wheel]
  Need --> Manga[Monthly manga if enabled]
  Scene --> Ctx[build_dynamic_context]
  Spin --> Ctx
  Manga --> Ctx
  Ctx --> LLM[Routed tool: playtime / spin_wheel / manga_*]
  LLM --> Out[Draft / outcome / panels]
```

If the assistant “knows too much” or “knows too little,” see [AI context](AI-context) rather than the scene form.

---

## Interview → Core knowledge

```mermaid
flowchart LR
  Chat[Interview chat] --> Sum[LLM summary]
  Sum --> CK[Populate Core knowledge]
  CK --> AI[Later AI calls use submitted CK of the requester]
```

Partner Core knowledge is **not** injected as readable text for the other person’s AI calls (only “submitted”).

---

## How to use these while debugging

1. Name the hub and feature toggle (Application features).
2. Check interview + AI key if it is a Playtime/LLM screen.
3. Follow the module chart until the last box that still works.
4. If the complaint is “AI invented X” or “AI ignored our agreement,” open [AI context](AI-context).
5. If two features both reacted (inbox + auto-punish + make-up), use the overlap chart above.

Design smells and fix-or-remove options: [Feature map](Feature-map).
