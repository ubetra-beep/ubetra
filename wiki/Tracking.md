# Tracking

Route: `/#/dynamic/{id}/track`

Hub for history, chastity, orgasm logging, feelings, sleep, cycle, punishment, journaling, and the image vault.

![Tracking hub — Dom](images/11-tracking-hub.png)

![Tracking hub — Sub](images/35-sub-tracking.png)

Collapsed **Setup / Dynamic** holds ground rules, interview, kink survey, knowledge, context/journal libraries, gear, and **Application features**.

---

## History

Route: `/#/dynamic/{id}/history`

Reports and dashboards (weekly, orgasm, chastity stats, **Days in chastity**). Demo data includes ~3 months of synthetic history plus recent wiki seed events.

![History](images/23-history.png)

### Days in chastity

Route: `/#/dynamic/{id}/history/chastity-days`

Calendar of full / partial / free lock days. When a night of sleep is tied to that morning:

- Ring color: **red** under 6.6h · **yellow** 6.6–7.2h · **green** over 7.2h  
- **Solid** ring = slept locked · **dotted** = slept unlocked  
- Dots under the day: **red** denied / milking / partial-milking · **blue** ruined orgasm · **green** full orgasm  

![Days in chastity](images/39-chastity-days.png)

---

## Chastity

Route: `/#/dynamic/{id}/chastity`

Lock/unlock, temporary breaks (Hygiene, Sleep, …), timers, goals, **Eventual Release**. Import prior lock/unlock CSV from Prior lockup history. Unlock reasons are tags on the timeline.

![Chastity](images/13-chastity.png)

---

## Sex & orgasm tracking

Route: `/#/dynamic/{id}/tracking`

Counts, tags, calendars. Dom configures fields/metrics. **Prior orgasm / play history** supports CSV import with a **preview before confirm** and a success message after import.

![Orgasm tracking](images/14-orgasm-tracking.png)

---

## Feelings

Route: `/#/dynamic/{id}/feelings`

Wheel check-ins (before/after play, end of day). Dom can set soft vs hard prompts.

![Feelings](images/15-feelings.png)

---

## Sleep tracking

Route: `/#/dynamic/{id}/sleep`

**Off by default** — enable under Application features. Nights are collapsible log-cards (one line each). Sessions within **6 hours awake** are one night; hours are sleep time only.

On Android, **Health Connect** reads sleep from apps on the phone (Samsung Health, Fitbit, Pixel Watch, …). Cycle permission is **not** required. Manual logging always works in the browser. Garmin/Apple remain optional extras.

![Sleep](images/29-sleep.png)

---

## Cycle tracking

Route: `/#/dynamic/{id}/cycle`

**Off by default.** Period flow and symptoms for you; your partner can see the log. Health Connect can import menstruation days on Android.

![Cycle](images/38-cycle.png)

---

## Punishment

Route: `/#/dynamic/{id}/punishment`

Sub confesses; Dom assigns or resolves. Pending items can surface in the return inbox.

![Punishment — Dom](images/16-punishment.png)

![Punishment — Sub](images/36-sub-punishment.png)

---

## Tasks & acts

Managed from **Playtime** (`/#/dynamic/{id}/tasks`). Open/missed timelines, make-up requests, Dom bulk controls. See [Playtime](Playtime).

![Tasks](images/17-tasks.png)

---

## Image vault

Route: `/#/dynamic/{id}/vault`

Private images from chat. Any partner can delete; deletions are logged in chat. Chat **Images off** still shows vault links.

![Vault](images/24-vault.png)

---

## Journal

Route: `/#/dynamic/{id}/journal`

Private writing with **Use for AI** and **Visible to partner** toggles. Domme review can summarize an entry (needs LLM).

![Journal](images/28-journal.png)

---

## Log cards

Tracking history cards collapse by default (name, relative time, type pill, tag accent). Tap to expand; ⋮ for Edit / Delete.
