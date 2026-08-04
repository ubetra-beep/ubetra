# Chat

Route: `/#/chat/{id}`

Partner messaging for the active dynamic.

![Chat — Dom](images/19-chat.png)

![Chat — Sub](images/33-sub-chat.png)

---

## Basics

- Text messages and image attachments (`+`)
- **Logs on/off** — system activity posts (tasks, tracking, chastity…)
- **Images on/off** — show or hide image messages
- **☰** — Application features for this hub (e.g. Image vault)
- **⋯** — quick chat privacy settings (blur, retain, encryption, push); Subs also find **Request a task** here
- The attach sheet's **Take photo** opens an in-app camera (device camera via the browser) and sends the capture directly; **Choose from library** still opens the file picker.

---

## Requesting a task (Sub)

Subs can open the **⋯** settings menu in Chat and choose **Request a task** to submit a task idea straight to the Dom's task list for approval — no need to leave the conversation. A toast confirms the request was sent.

---

## Encrypted chat (shared key)

From **v0.75**, encryption uses a **server-shared key** for the dynamic (same idea as the shared AI key):

1. Turn on **Encrypted chat (shared key)** in Settings → Privacy (or Chat ☰) and Save once.
2. Every other signed-in device opens Chat and syncs the key automatically.

No redeem codes are required for new phones. Anyone with access to your server database can decrypt — that is the intentional tradeoff for multi-device simplicity.

Legacy one-time share codes remain under Advanced for unusual migrations.

---

## Images

- Optional blur by default  
- Dom can **lock** an image until the Sub requests unlock  
- Vault copies can be kept privately  

---

## Push notifications

1. Open the app over the **same HTTPS origin** you installed the PWA from (not a LAN `http://` URL).  
2. Enable chat push for the dynamic (Chat ⋯ or Settings → Privacy).  
3. On **each phone**, enable **Notify this device** and accept the browser/OS permission prompt.  
4. Fully close the PWA and have your partner send a test message.

### Android Chrome / Edge (PWA) setup

Settings → Privacy → **Android Chrome / Edge setup tips**, or:

1. Install via **⋮ → Install app** (not “Add to Home screen”).
2. Android Settings → Apps → **Chrome** or **Edge** → Notifications → **Allowed**.
3. Same path → Battery → **Unrestricted**.
4. Samsung / Xiaomi: add Chrome/Edge to **Never sleeping apps** / allow Autostart.
5. Confirm Google Play Services is present.
6. Re-open UBETRA once after a server update so the service worker re-syncs.

PWAs still cannot bypass **Do Not Disturb**. For that (and future calling), install the [Android APK](../mobile/README.md).

### Android APK (recommended for phones)

See [`mobile/README.md`](../mobile/README.md): Capacitor shell + native FCM, with a `ubetra_calls` channel that can ignore DND after you grant Notification Policy access.

Banners are suppressed when that same chat is already open and visible; messages still refresh in-app.

---

## Retention

Choose **keep forever** or a **server cache duration** (default 30 days) so offline phones can sync, then auto-delete. Encrypted bodies stay as ciphertext on the server while retained.
