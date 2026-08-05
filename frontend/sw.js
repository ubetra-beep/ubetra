const CACHE = "ubetra-v85";
const ASSETS = [
  "/",
  "/assets/styles.css",
  "/assets/app.js",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

/** FCM can rotate push endpoints; ask open clients to re-POST /push/subscribe. */
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil(
    (async () => {
      const list = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      list.forEach((client) => {
        try {
          client.postMessage({ type: "ubetra-push-resync" });
        } catch {
          /* ignore */
        }
      });
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET" || request.url.includes("/api/")) {
    return;
  }
  // Network-first for app shell so nav/UI fixes apply without a stuck History tab.
  event.respondWith(
    fetch(request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy));
        return response;
      })
      .catch(() => caches.match(request))
  );
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : "New message" };
  }
  const title = payload.title || "UBETRA";
  const body = payload.body || "New chat message";
  const url = payload.url || "/";
  const tag = payload.tag || "ubetra-chat";
  const dynamicId = payload.dynamic_id || "";
  const kind = payload.kind || "chat";

  event.waitUntil(
    (async () => {
      const list = await self.clients.matchAll({ type: "window", includeUncontrolled: true });

      // Ask open tabs whether this chat is already on-screen (skip OS banner if so).
      // Never suppress call rings — those must always surface.
      let suppressBanner = false;
      if (kind !== "call" && dynamicId && String(tag).startsWith("ubetra-chat")) {
        const checks = await Promise.all(
          list.map(
            (client) =>
              new Promise((resolve) => {
                const channel = new MessageChannel();
                const timer = setTimeout(() => resolve(false), 400);
                channel.port1.onmessage = (ev) => {
                  clearTimeout(timer);
                  resolve(!!ev.data?.suppress);
                };
                try {
                  client.postMessage(
                    { type: "ubetra-push-should-suppress", dynamicId, tag },
                    [channel.port2]
                  );
                } catch {
                  clearTimeout(timer);
                  resolve(false);
                }
              })
          )
        );
        suppressBanner = checks.some(Boolean);
      }

      const tasks = [];
      if (!suppressBanner) {
        tasks.push(
          self.registration.showNotification(title, {
            body,
            tag,
            data: { url, dynamicId, kind },
            renotify: true,
            // Keep banner until dismissed — helps Android not bury chat alerts.
            requireInteraction: true,
            silent: false,
            icon: "/icons/icon-192.png",
            badge: "/icons/icon-192.png",
            vibrate: kind === "call" ? [300, 120, 300, 120, 300] : [180, 80, 180],
          })
        );
      }
      list.forEach((client) => {
        client.postMessage({
          type: "ubetra-chat-push",
          dynamicId,
          url,
          kind,
        });
      });
      await Promise.all(tasks);
    })()
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/#/home";
  const href = new URL(target, self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ("focus" in client) {
          client.postMessage({ type: "ubetra-navigate", url: target });
          return client.focus();
        }
      }
      return self.clients.openWindow(href);
    })
  );
});
