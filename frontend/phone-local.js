/* Phone-only and server-offline behaviour. Talks to UbetraLocalStore when the Android app is present. */
(function () {
  var STORAGE_KEY = "ubetra_phone_events_v1";
  var caps = {
    serverReachable: true,
    serverConfigured: true,
    localLoggerReady: false,
    phoneOnly: false,
    choiceMade: false,
    serverUrl: "",
    lastSyncAt: "",
    pendingCount: 0,
    mode: "server",
  };
  var localSession = false;
  var statusCache = null;
  var statusAt = 0;

  function plugin() {
    try {
      if (!window.Capacitor || !window.Capacitor.Plugins) return null;
      return window.Capacitor.Plugins.UbetraLocalStore || null;
    } catch (err) {
      return null;
    }
  }

  function nativeApp() {
    try {
      return !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
    } catch (err) {
      return false;
    }
  }

  function readEvents() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      var parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      return [];
    }
  }

  function writeEvents(rows) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(rows));
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function uuid() {
    return "local-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }

  function applyCaps(next) {
    caps.serverUrl = next.serverUrl || "";
    caps.phoneOnly = !!next.phoneOnly;
    caps.choiceMade = !!next.choiceMade;
    caps.serverConfigured = !!next.serverConfigured;
    caps.serverReachable = next.serverReachable !== false;
    caps.localLoggerReady = next.localLoggerReady !== false;
    caps.lastSyncAt = next.lastSyncAt || "";
    caps.pendingCount = Number(next.pendingCount) || 0;
    if (!caps.serverConfigured) caps.mode = "phone";
    else if (!caps.serverReachable) caps.mode = "offline";
    else caps.mode = "server";
    document.body.classList.toggle("phone-server-off", serverFeaturesGrey());
    paint();
  }

  function serverFeaturesGrey() {
    return caps.mode === "phone" || caps.mode === "offline";
  }

  function bannerText() {
    if (caps.mode === "phone") return "Phone-only. Logging stays on this device.";
    if (caps.mode === "offline") {
      var extra = caps.pendingCount ? " " + caps.pendingCount + " waiting to send." : "";
      return "Server offline — logging on this phone." + extra;
    }
    return "";
  }

  function paint() {
    var text = bannerText();
    var banner = document.getElementById("phone-mode-banner");
    if (!text) {
      if (banner) banner.remove();
    } else if (!banner) {
      banner = document.createElement("div");
      banner.id = "phone-mode-banner";
      banner.className = "phone-mode-banner";
      banner.textContent = text;
      var top = document.getElementById("top-bar");
      if (top && top.parentNode) top.parentNode.insertBefore(banner, top);
      else document.body.insertBefore(banner, document.body.firstChild);
    } else {
      banner.textContent = text;
    }
    if (!serverFeaturesGrey()) return;
    var titles = {
      "Privacy & security": 1,
      "Assistant domme": 1,
      "LLM API Configuration": 1,
      "Google Tasks": 1,
      "Smart censor": 1,
      "Auto punish": 1,
      "Tasks & notifications": 1,
      "Feelings notifications": 1,
      "Account email": 1,
      "Change password": 1,
      "Backup & restore": 1,
      "Your dynamics": 1,
      "Start or join a dynamic": 1,
      "Application features": 1,
      "Chastity policy": 1,
    };
    var cards = document.querySelectorAll(".card");
    for (var i = 0; i < cards.length; i++) {
      var heading = cards[i].querySelector("h2, h3");
      var name = heading ? heading.textContent.trim() : "";
      if (titles[name]) cards[i].classList.add("server-only-card");
    }
  }

  function pathOnly(path) {
    return String(path || "").split("?")[0];
  }

  function dynamicId(path) {
    var match = pathOnly(path).match(/^\/dynamics\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function localCapable(path, options) {
    var p = pathOnly(path);
    var method = ((options && options.method) || "GET").toUpperCase();
    if (method === "GET" && (
      p === "/auth/me" ||
      p === "/dynamics" ||
      /\/dynamics\/[^/]+$/.test(p) ||
      /\/chastity\/overview$/.test(p) ||
      /\/chastity$/.test(p) ||
      /\/tracking$/.test(p) ||
      /\/tracking\/stats$/.test(p) ||
      /\/watch\/summary$/.test(p) ||
      /\/sleep$/.test(p) ||
      /\/cycle$/.test(p) ||
      /\/interests$/.test(p) ||
      /\/tasks$/.test(p) ||
      /\/inbox$/.test(p)
    )) return true;
    if (method === "POST" && /\/tracking$/.test(p)) return true;
    if (method === "POST" && /\/chastity\/start$/.test(p)) return true;
    if (method === "POST" && /\/chastity\/[^/]+\/break$/.test(p)) return true;
    if (method === "PATCH" && /\/chastity\/[^/]+\/end$/.test(p)) return true;
    if (method === "PATCH" && /\/break\/[^/]+\/finish$/.test(p)) return true;
    return false;
  }

  function shouldServeLocal(path, options) {
    if (!serverFeaturesGrey() && !localSession) return false;
    return localCapable(path, options);
  }

  function canFallback(path, options) {
    return localCapable(path, options);
  }

  function parseBody(options) {
    if (!options || !options.body) return {};
    try {
      return JSON.parse(options.body);
    } catch (err) {
      return {};
    }
  }

  function browserLogOrgasm(body) {
    var rows = readEvents();
    var event = {
      client_event_id: body.client_event_id || uuid(),
      kind: "orgasm",
      action: body.event_type === "no_orgasm" ? "log_play" : "log_full",
      updated_at: nowIso(),
      sync_state: "pending",
      body: body,
    };
    rows.push(event);
    writeEvents(rows);
    caps.pendingCount = rows.filter(function (row) { return row.sync_state !== "synced"; }).length;
    caps.localLoggerReady = true;
    return {
      id: event.client_event_id,
      client_event_id: event.client_event_id,
      for_membership_id: body.for_membership_id || "local-self",
      for_display_name: "You",
      event_type: body.event_type || "orgasm",
      notes: body.notes || "",
      tags: body.tags || [],
      orgasms: body.orgasms || [],
      occurred_at: body.occurred_at || event.updated_at,
      logged_by_display_name: "You",
      updated_at: event.updated_at,
      pending: true,
    };
  }

  function browserStatus() {
    var rows = readEvents();
    var entries = [];
    rows.forEach(function (row) {
      if (row.kind === "orgasm") entries.push(browserLogOrgasmShape(row));
    });
    return {
      localLoggerReady: true,
      overview: {
        summary_label: "Phone log",
        any_enabled: true,
        partners: [{
          membership_id: "local-self",
          name: "You",
          chastity_enabled: true,
          state: "unlocked",
          current_duration_label: null,
        }],
      },
      lockups: [],
      entries: entries,
      stats: { recent_orgasm_label: entries.length ? "Logged on this phone" : "", partners: [], cumulative_30d: [] },
      summary: null,
      sleep: null,
      cycle: null,
      dynamic: localDynamic("local"),
      user: localUser(),
      pendingCount: rows.length,
    };
  }

  function browserLogOrgasmShape(row) {
    var body = row.body || {};
    return {
      id: row.client_event_id,
      client_event_id: row.client_event_id,
      for_membership_id: body.for_membership_id || "local-self",
      event_type: body.event_type || "orgasm",
      notes: body.notes || "",
      tags: body.tags || [],
      orgasms: body.orgasms || [],
      occurred_at: body.occurred_at || row.updated_at,
      logged_by_display_name: "You",
      for_display_name: "You",
      updated_at: row.updated_at,
    };
  }

  function localDynamic(id) {
    return {
      id: id || "local",
      name: id === "local" ? "This phone" : "UBETRA",
      enabled_features: ["chastity", "org_tracking"],
      partners: [{
        id: "local-self",
        display_name: "You",
        is_you: true,
        role: "submissive",
        chastity_enabled: true,
      }],
    };
  }

  function localUser() {
    return { id: "local-user", username: "You", onboarding_completed: true, email: "" };
  }

  async function loadStatus(force) {
    var plug = plugin();
    if (!plug || !plug.getStatus) {
      statusCache = browserStatus();
      statusAt = Date.now();
      return statusCache;
    }
    if (!force && statusCache && Date.now() - statusAt < 1500) return statusCache;
    statusCache = await plug.getStatus();
    statusAt = Date.now();
    return statusCache;
  }

  async function serveLocal(path, options) {
    var p = pathOnly(path);
    var method = ((options && options.method) || "GET").toUpperCase();
    var body = parseBody(options);
    var plug = plugin();
    if (method === "POST" && /\/tracking$/.test(p)) {
      body.client_event_id = body.client_event_id || uuid();
      body.updated_at = body.updated_at || nowIso();
      var created = plug && plug.logOrgasm
        ? await plug.logOrgasm({ payload: JSON.stringify(body) })
        : browserLogOrgasm(body);
      statusCache = null;
      caps.localLoggerReady = true;
      caps.pendingCount += 1;
      paint();
      return created;
    }
    if (method !== "GET" && /chastity/.test(p)) {
      var action = "start";
      if (/\/end$/.test(p)) action = "end";
      else if (/\/break$/.test(p)) action = body.break_type && String(body.break_type).indexOf("sleep") >= 0 ? "sleep_break" : "hygiene_break";
      else if (/\/finish$/.test(p)) action = "relock";
      body.action = action;
      body.client_event_id = body.client_event_id || uuid();
      if (plug && plug.chastityAction) {
        var next = await plug.chastityAction({ payload: JSON.stringify(body) });
        statusCache = next;
        return action === "start" || action === "end" ? (next.lockups && next.lockups[0]) || next : next;
      }
      throw needsServer();
    }
    var status = await loadStatus(false);
    if (p === "/auth/me") return status.user || localUser();
    if (p === "/dynamics") return [status.dynamic || localDynamic("local")];
    if (/\/dynamics\/[^/]+$/.test(p)) return status.dynamic || localDynamic(dynamicId(p));
    if (/\/chastity\/overview$/.test(p)) return status.overview;
    if (/\/chastity$/.test(p)) return status.lockups || [];
    if (/\/tracking\/stats$/.test(p)) return status.stats || { partners: [], cumulative_30d: [] };
    if (/\/tracking$/.test(p)) return status.entries || [];
    if (/\/watch\/summary$/.test(p)) return status.summary;
    if (/\/sleep$/.test(p)) return status.sleep || [];
    if (/\/cycle$/.test(p)) return status.cycle || { people: [] };
    if (/\/interests$/.test(p)) return { interests: [] };
    if (/\/tasks$/.test(p)) return [];
    if (/\/inbox$/.test(p)) return { items: [] };
    throw needsServer();
  }

  function needsServer() {
    var err = new Error("Needs self-host server");
    err.status = 503;
    return err;
  }

  function blockedRoute(parts) {
    if (!serverFeaturesGrey()) return false;
    var head = parts[0] || "";
    var facet = parts[2] || "";
    if (head === "chat") return true;
    var blocked = {
      assistant: 1,
      vault: 1,
      video: 1,
      instructor: 1,
      acts: 1,
      gear: 1,
      feelings: 1,
      knowledge: 1,
      interview: 1,
      "check-in": 1,
      context: 1,
      kiosk: 1,
    };
    if (head === "dynamic" && blocked[facet]) return true;
    if ((facet === "sleep" || facet === "cycle") && !hasBodyCache(facet === "sleep" ? "sleep" : "cycle")) return true;
    return false;
  }

  function hasBodyCache(kind) {
    if (!statusCache) return false;
    if (kind === "sleep") return !!(statusCache.sleep && (statusCache.sleep.nights || statusCache.sleep.length));
    if (kind === "cycle") return !!(statusCache.cycle && statusCache.cycle.people && statusCache.cycle.people.length);
    return false;
  }

  function renderNeedsServer() {
    var view = document.getElementById("view");
    if (!view) return;
    view.innerHTML = "";
    var card = document.createElement("div");
    card.className = "card stack";
    card.innerHTML = "<h1>Needs self-host server</h1><p class=\"muted\">This part stays off until a server URL is saved and the phone can reach it. Today, Log, and chastity on this phone still work.</p>";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "primary-btn";
    button.textContent = "Server settings";
    button.addEventListener("click", function () {
      if (window.location.hash.indexOf("#/settings") !== 0) window.location.hash = "#/settings";
    });
    card.appendChild(button);
    view.appendChild(card);
  }

  async function refresh() {
    var plug = plugin();
    if (plug && plug.getServerConfig) {
      var config = await plug.getServerConfig();
      if (config.serverConfigured && plug.probeServer) {
        try {
          var probe = await plug.probeServer();
          config.serverReachable = !!(probe && probe.reachable);
        } catch (err) {
          config.serverReachable = false;
        }
      }
      applyCaps(config);
      if (caps.localLoggerReady) await loadStatus(true);
      return caps;
    }
    if (!nativeApp()) {
      caps.serverConfigured = true;
      caps.choiceMade = true;
      caps.phoneOnly = false;
      try {
        var health = await fetch("/api/health", { cache: "no-store" });
        caps.serverReachable = health.ok;
      } catch (err) {
        caps.serverReachable = false;
        caps.localLoggerReady = true;
      }
      caps.mode = caps.serverReachable ? "server" : "offline";
      document.body.classList.toggle("phone-server-off", serverFeaturesGrey());
      paint();
      return caps;
    }
    caps.serverConfigured = false;
    caps.serverReachable = false;
    caps.phoneOnly = true;
    caps.localLoggerReady = true;
    caps.mode = "phone";
    document.body.classList.toggle("phone-server-off", true);
    paint();
    return caps;
  }

  async function prepare(state) {
    await refresh();
    if (caps.mode === "phone" || (caps.mode === "offline" && (!state.token || state.token === "local"))) {
      installOfflineSession(state);
      localSession = true;
    }
  }

  function usingLocalSession() {
    return localSession;
  }

  function installOfflineSession(state) {
    var dynamic = (statusCache && statusCache.dynamic) || localDynamic(state.activeDynamicId || "local");
    var user = (statusCache && statusCache.user) || localUser();
    if (!state.token || caps.mode === "phone") state.token = state.token || "local";
    state.user = state.user || user;
    if (state.user && state.user.onboarding_completed == null) state.user.onboarding_completed = true;
    if (!state.dynamics || !state.dynamics.length) state.dynamics = [dynamic];
    state.currentDynamic = state.currentDynamic || dynamic;
    state.activeDynamicId = state.activeDynamicId || dynamic.id || "local";
    localSession = caps.mode !== "server";
    return state;
  }

  async function keepSessionOffline() {
    await refresh();
    return caps.mode === "offline" || caps.mode === "phone";
  }

  function noteSession(state) {
    var plug = plugin();
    if (!plug || !plug.setSession || !state || !state.token || state.token === "local") return;
    var dynamic = state.currentDynamic || (state.dynamics && state.dynamics[0]) || null;
    var you = "";
    if (dynamic && dynamic.partners) {
      for (var i = 0; i < dynamic.partners.length; i++) {
        if (dynamic.partners[i].is_you) you = dynamic.partners[i].id;
      }
    }
    var origin = "";
    try { origin = window.location.origin || ""; } catch (err) { origin = ""; }
    plug.setSession({
      token: state.token,
      dynamicId: state.activeDynamicId || (dynamic && dynamic.id) || "",
      membershipId: you,
      apiBase: origin,
      dynamicJson: dynamic ? JSON.stringify(dynamic) : "",
      userJson: state.user ? JSON.stringify(state.user) : "",
    }).catch(function () {});
  }

  function markUnreachable() {
    caps.serverReachable = false;
    if (caps.serverConfigured) caps.mode = "offline";
    caps.localLoggerReady = true;
    document.body.classList.toggle("phone-server-off", true);
    paint();
  }

  function markReachable() {
    if (!caps.serverConfigured && caps.mode === "phone") return;
    caps.serverReachable = true;
    caps.serverConfigured = true;
    caps.mode = "server";
    localSession = false;
    document.body.classList.remove("phone-server-off");
    var banner = document.getElementById("phone-mode-banner");
    if (banner) banner.remove();
  }

  async function onForeground() {
    await refresh();
    var plug = plugin();
    if (plug && plug.syncNow && caps.serverConfigured && caps.serverReachable) {
      try { await plug.syncNow(); } catch (err) { /* pending rows stay */ }
      statusCache = null;
      await loadStatus(true);
    }
  }

  window.UbetraPhone = {
    caps: caps,
    refresh: refresh,
    prepare: prepare,
    usingLocalSession: usingLocalSession,
    installOfflineSession: installOfflineSession,
    keepSessionOffline: keepSessionOffline,
    shouldServeLocal: shouldServeLocal,
    canFallback: canFallback,
    serveLocal: serveLocal,
    serverFeaturesGrey: serverFeaturesGrey,
    blockedRoute: blockedRoute,
    renderNeedsServer: renderNeedsServer,
    hasBodyCache: hasBodyCache,
    noteSession: noteSession,
    markUnreachable: markUnreachable,
    markReachable: markReachable,
    onForeground: onForeground,
    paint: paint,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { refresh(); });
  } else {
    refresh();
  }
})();
