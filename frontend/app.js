const API = "/api";
const TOKEN_KEY = "ubetra_token";

const state = {
  token: localStorage.getItem(TOKEN_KEY),
  user: null,
  dynamics: [],
  currentDynamic: null,
  interests: null,
  taskLists: [],
  activeDynamicId: null,
};

const NAV_TABS = [
  { id: "tracking", label: "Tracking", icon: "📈", enabled: true, requiresDynamic: true },
  { id: "workshop", label: "Playtime", icon: "✨", enabled: true, requiresDynamic: true },
  { id: "chat", label: "Chat", icon: "💬", enabled: true, requiresDynamic: true },
];

/** Facets shown on the Dynamic overview / Setup section. */
const FACET_SECTIONS = [
  {
    id: "essentials",
    title: "Essentials",
    items: [
      { id: "ground_rules", icon: "🛡", title: "Ground rules", subtitle: "Agreements and boundaries", core: true, route: "ground-rules" },
      { id: "interview", icon: "🎙", title: "Dynamic interview", subtitle: "Tell the AI what you want here", core: true, route: "interview", badge: "interview" },
      { id: "kink_list", icon: "📋", title: "Kink list", subtitle: "Want / if partner / not into", core: true, route: "survey", badge: "survey" },
    ],
  },
  {
    id: "knowledge",
    title: "Knowledge",
    items: [
      { id: "core_knowledge", icon: "🧠", title: "Core knowledge", subtitle: "Relationship context for AI", core: true, route: "knowledge" },
      { id: "spti", icon: "🧬", title: "SPTI profile", subtitle: "Personality test for AI", route: "knowledge/spti" },
      { id: "context_library", icon: "📎", title: "Context library", subtitle: "Stories, scenes, and files for AI", route: "context" },
      { id: "gear", icon: "🧰", title: "Gear", subtitle: "Vanilla toys, kinky stuff, outfits", route: "gear" },
    ],
  },
];

/** Facets shown on the Tracking bottom-nav hub. */
const TRACKING_FACETS = [
  { id: "history", icon: "📊", title: "History", subtitle: "Reports and logs", route: "history", core: true },
  { id: "chastity", icon: "🔒", title: "Chastity tracking", subtitle: "Lockup stats and current lock time", route: "chastity" },
  { id: "org_tracking", icon: "📈", title: "Sex & orgasm tracking", subtitle: "Counts and recent activity", route: "tracking" },
  { id: "feelings", icon: "💫", title: "Feelings tracking", subtitle: "Wheel check-ins before/after play", route: "feelings" },
  {
    id: "punishment",
    icon: "⚖",
    title: "Punishment",
    subtitle: "Confess or assign punishments",
    route: "punishment",
    core: true,
  },
  {
    id: "tasks",
    icon: "✅",
    title: "Tasks & acts",
    subtitle: "Task lists and acts of submission",
    route: "tasks",
    alsoEnabledBy: ["acts"],
  },
  { id: "journal", icon: "📓", title: "Journal", subtitle: "Private writing with optional AI assist", route: "journal" },
  { id: "image_vault", icon: "🖼", title: "Image vault", subtitle: "Encrypted private images from chat", route: "vault" },
];

const PLAYTIME_EXTRA_FACETS = [];

function allFacetItems() {
  return [
    ...FACET_SECTIONS.flatMap((section) => section.items),
    ...TRACKING_FACETS,
    ...PLAYTIME_EXTRA_FACETS,
  ];
}

const viewEl = document.getElementById("view");
const logoutBtn = document.getElementById("logout-btn");
const settingsBtn = document.getElementById("settings-btn");
const installPwaBtn = document.getElementById("install-pwa-btn");
const bottomNavEl = document.getElementById("bottom-nav");
const topBarEl = document.getElementById("top-bar");
const appBrandEl = document.getElementById("app-brand");
const domGoalMetersEl = document.getElementById("dom-goal-meters");

let goalHeaderState = { hidden: true, revealed: new Set(), timer: null };
let deferredPwaPrompt = null;

function isRunningAsPwa() {
  return (
    window.matchMedia("(display-mode: standalone)").matches
    || window.matchMedia("(display-mode: minimal-ui)").matches
    || window.navigator.standalone === true
  );
}

function updateInstallPwaButton() {
  if (!installPwaBtn) return;
  const show = !isRunningAsPwa() && !!state.token;
  installPwaBtn.classList.toggle("hidden", !show);
  installPwaBtn.textContent = "Install app";
  installPwaBtn.title = deferredPwaPrompt
    ? "Install as a standalone app (recommended)"
    : "Browser menu → Install app (not a home-screen shortcut)";
}

function setAuthVisible(visible) {
  logoutBtn.classList.toggle("hidden", !visible);
  settingsBtn.classList.toggle("hidden", !visible);
  if (topBarEl) topBarEl.classList.toggle("hidden", !visible);
  document.body.classList.toggle("auth-screen", !visible);
  updateInstallPwaButton();
  if (visible && appBrandEl) {
    appBrandEl.textContent = "UBETRA";
    appBrandEl.classList.add("brand-link");
    appBrandEl.setAttribute("role", "link");
    appBrandEl.tabIndex = 0;
    document.title = "UBETRA";
  } else if (!visible) {
    document.title = "Shared space";
    if (appBrandEl) {
      appBrandEl.classList.remove("brand-link");
      appBrandEl.removeAttribute("role");
      appBrandEl.tabIndex = -1;
    }
  }
}

function goHomeFromBrand() {
  if (!state.token) return;
  const id = getActiveDynamicId();
  if (id) navigate(`/dynamic/${id}`);
  else navigate("/home");
}

function formatGoalCountdown(iso) {
  if (!iso) return "";
  const ms = new Date(iso) - Date.now();
  if (ms <= 0) return "ready soon";
  const hours = Math.floor(ms / 3600000);
  const days = Math.floor(hours / 24);
  if (days >= 1) return `${days}d ${hours % 24}h`;
  const mins = Math.floor((ms % 3600000) / 60000);
  return `${hours}h ${mins}m`;
}

function formatGoalChipLabel(goal, { revealed }) {
  if (goal.ready) return revealed ? `${goal.title}: READY` : "• ready";
  const counts = (goal.requirements || []).filter((r) => r.unit === "count");
  const times = (goal.requirements || []).filter((r) => r.unit === "days");
  if (!revealed) {
    if (goal.countdown_at) return `• ${formatGoalCountdown(goal.countdown_at)}`;
    if (counts.length) {
      const r = counts[0];
      return `• ${r.current}/${r.target}`;
    }
    return "• …";
  }
  const bits = [`${goal.title}`];
  if (goal.countdown_at) bits.push(formatGoalCountdown(goal.countdown_at));
  counts.forEach((r) => bits.push(`${r.current}/${r.target} ${r.title.split(" ")[0].toLowerCase()}`));
  times.filter((r) => !r.met).forEach((r) => bits.push(`${r.current}/${r.target}d`));
  return bits.join(" · ");
}

async function refreshDomGoalHeader(dynamicId = getActiveDynamicId()) {
  if (!domGoalMetersEl) return;
  if (goalHeaderState.timer) {
    clearInterval(goalHeaderState.timer);
    goalHeaderState.timer = null;
  }
  if (!state.token || !dynamicId) {
    domGoalMetersEl.classList.add("hidden");
    domGoalMetersEl.replaceChildren();
    return;
  }
  const you = state.currentDynamic?.partners?.find((p) => p.is_you);
  if (you?.role !== "dominant") {
    domGoalMetersEl.classList.add("hidden");
    domGoalMetersEl.replaceChildren();
    return;
  }
  try {
    const data = await api(`/dynamics/${dynamicId}/chastity-goals`);
    if (!data.you_are_dominant || !(data.goals || []).length) {
      domGoalMetersEl.classList.add("hidden");
      domGoalMetersEl.replaceChildren();
      return;
    }
    goalHeaderState.hidden = data.header_hidden !== false;
    const paint = () => {
      domGoalMetersEl.classList.remove("hidden");
      domGoalMetersEl.replaceChildren();
      (data.goals || []).forEach((goal) => {
        const revealed = goalHeaderState.revealed.has(goal.id);
        const chip = el("button", {
          type: "button",
          className: `dom-goal-chip tone-${goal.tone || "primary"}${goal.ready ? " ready" : ""}${revealed ? " revealed" : ""}`,
          title: "Click to show/hide details (keyholder only)",
          onClick: () => {
            if (goalHeaderState.revealed.has(goal.id)) goalHeaderState.revealed.delete(goal.id);
            else goalHeaderState.revealed.add(goal.id);
            paint();
          },
        }, formatGoalChipLabel(goal, { revealed }));
        domGoalMetersEl.appendChild(chip);
      });
    };
    paint();
    goalHeaderState.timer = setInterval(paint, 60000);
  } catch {
    domGoalMetersEl.classList.add("hidden");
    domGoalMetersEl.replaceChildren();
  }
}

function setToken(token) {
  state.token = token;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
  setAuthVisible(!!token);
}

let mfaSession = { token: null, emailHint: null };

function navigateAfterAuth() {
  // Soft sex prompt later — don't hard-land on Settings after login.
  if (!state.user?.onboarding_completed) {
    navigate("/onboarding");
    return;
  }
  const last = getLastRoute();
  if (last) {
    navigate(last);
    return;
  }
  if (state.dynamics.length) {
    navigate(`/dynamic/${state.dynamics[0].id}/track`);
  } else {
    navigate("/home");
  }
}

const LAST_ROUTE_KEY = "ubetra_last_route";

function shouldRememberRoute(path) {
  const clean = String(path || "").split("?")[0];
  const parts = clean.replace(/^#/, "").split("/").filter(Boolean);
  if (!parts.length) return false;
  if (["settings", "login", "register", "onboarding"].includes(parts[0])) return false;
  return true;
}

function rememberRoute(path) {
  if (!shouldRememberRoute(path)) return;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  localStorage.setItem(LAST_ROUTE_KEY, normalized);
}

function getLastRoute() {
  const raw = localStorage.getItem(LAST_ROUTE_KEY) || "";
  if (!shouldRememberRoute(raw)) return null;
  return raw;
}

function providerHelpBtn(provider) {
  if (!provider?.policy_notes && !provider?.description) return null;
  const pop = el("div", { className: "help-popover hidden" }, [
    el("p", {}, provider.description || ""),
    provider.policy_notes ? el("p", {}, provider.policy_notes) : null,
    provider.key_url
      ? el("a", {
        href: provider.key_url,
        target: "_blank",
        rel: "noopener noreferrer",
      }, "Where to get an API key")
      : null,
  ]);
  const btn = el("button", { className: "help-btn", type: "button", title: "About this provider" }, "?");
  btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    pop.classList.toggle("hidden");
  });
  return el("span", { className: "help-wrap" }, [btn, pop]);
}

function onboardingStep(status) {
  if (!status.has_dynamic) return "dynamic";
  if (!status.shared_llm_configured && !status.api_skipped) return "api";
  if (!status.spti_completed && !status.spti_skipped) return "spti";
  if (!status.survey_submitted && !status.survey_skipped) return "survey";
  return "finish";
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`${API}${path}`, { ...options, headers });
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      if (!response.ok) {
        throw new Error(text || `Request failed (${response.status})`);
      }
      throw new Error("Server returned an invalid response. Try restarting the app.");
    }
  }
  if (!response.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg || item).join(", ")
          : data?.error || text || `Request failed (${response.status})`;
    const err = new Error(message);
    err.status = response.status;
    throw err;
  }
  return data;
}

function navigate(path) {
  rememberRoute(path);
  if (location.hash !== `#${path}`) location.hash = path;
  else renderRoute();
  updateBottomNav();
  const parts = String(path || "").split("?")[0].split("/").filter(Boolean);
  if (parts[0] === "dynamic" && parts[1]) {
    maybeShowInbox(parts[1]);
  }
}

const inboxCheckedDynamics = new Set();

async function maybeShowInbox(dynamicId) {
  if (!state.token || !dynamicId) return;
  try {
    const data = await api(`/dynamics/${dynamicId}/inbox`);
    if (!data?.items?.length) {
      inboxCheckedDynamics.add(dynamicId);
      return;
    }
    const hasPunishment = data.items.some((i) => String(i.kind || "").includes("punishment"));
    if (inboxCheckedDynamics.has(dynamicId) && !hasPunishment) return;
    inboxCheckedDynamics.add(dynamicId);
    showInboxOverlay(dynamicId, data.items);
  } catch {
    /* ignore */
  }
}

function showInboxOverlay(dynamicId, items) {
  const existing = document.getElementById("inbox-overlay");
  if (existing) existing.remove();

  const log = el("div", { className: "inbox-log" });
  items.forEach((item) => {
    const when = item.occurred_at
      ? formatLocalDateTime(item.occurred_at, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
      : "";
    const row = el("button", {
      type: "button",
      className: `inbox-log-item ${item.kind || ""}`,
    }, [
      el("div", { className: "inbox-log-title" }, item.title || "Update"),
      item.body ? el("div", { className: "inbox-log-body" }, item.body) : null,
      when ? el("div", { className: "inbox-log-when" }, when) : null,
    ]);
    row.addEventListener("click", () => {
      if (item.path) navigate(item.path.startsWith("/") ? item.path : `/${item.path}`);
    });
    log.appendChild(row);
  });

  const dismiss = async () => {
    try {
      await api(`/dynamics/${dynamicId}/inbox/ack`, { method: "POST" });
    } catch {
      /* still close */
    }
    overlay.remove();
  };

  const panel = el("div", { className: "inbox-panel" }, [
    el("h2", {}, "While you were away"),
    el("p", { className: "muted" }, "Activity and tasks that need your eye."),
    log,
    el("button", {
      className: "primary-btn",
      type: "button",
      onClick: () => { dismiss(); },
    }, "Got it"),
  ]);

  const overlay = el("div", { id: "inbox-overlay", className: "inbox-overlay" }, [panel]);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) dismiss();
  });
  document.body.appendChild(overlay);
}

function buildDueInControls() {
  const amount = el("input", {
    type: "number",
    min: "1",
    step: "1",
    placeholder: "Amount",
  });
  const unit = el("select");
  [
    ["", "No relative due"],
    ["minutes", "Minutes"],
    ["hours", "Hours"],
    ["days", "Days"],
    ["weeks", "Weeks"],
  ].forEach(([value, label]) => {
    unit.appendChild(el("option", { value }, label));
  });
  return {
    node: el("div", { className: "due-in-controls" }, [
      el("label", {}, ["Due in", amount]),
      el("label", {}, ["Unit", unit]),
    ]),
    getPayload() {
      const n = Number(amount.value);
      if (!Number.isFinite(n) || n < 1 || !unit.value) {
        return { due_in_amount: null, due_in_unit: null };
      }
      return { due_in_amount: Math.floor(n), due_in_unit: unit.value };
    },
  };
}

function buildAssigneeSelect(partners, { includeDefault = true } = {}) {
  const sel = el("select");
  if (includeDefault) {
    sel.appendChild(el("option", { value: "" }, "Unassigned (sub completes)"));
  }
  (partners || []).forEach((p) => {
    const label = p.is_you ? `${p.display_name} (you)` : p.display_name;
    sel.appendChild(el("option", { value: p.id }, label));
  });
  return sel;
}

function canCompleteTask(task, you) {
  if (!you || task.completed_at || task.hidden || task.approval_status !== "approved") return false;
  if (task.assigned_to_membership_id) return task.assigned_to_membership_id === you.id;
  if (task.is_private) return true;
  return you.role === "submissive";
}

function formatTaskDue(task) {
  const due = task.next_due_at || task.due_at;
  if (!due) return "";
  const d = new Date(due);
  const now = Date.now();
  const ms = d.getTime() - now;
  const abs = Math.abs(ms);
  const mins = Math.round(abs / 60000);
  let relative;
  if (mins < 60) relative = `${mins}m`;
  else if (mins < 60 * 48) relative = `${Math.round(mins / 60)}h`;
  else relative = `${Math.round(mins / (60 * 24))}d`;
  const when = d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  return ms < 0 ? `Overdue by ${relative} (${when})` : `Due in ${relative} (${when})`;
}

function parseRoute() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const [pathPart, queryPart] = hash.split("?");
  const parts = pathPart.split("/").filter(Boolean);
  const query = new URLSearchParams(queryPart || "");
  return { parts, raw: pathPart, query };
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === "className") node.className = value;
    else if (key === "checked" || key === "disabled" || key === "selected" || key === "open") node[key] = !!value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value !== null && value !== undefined) node.setAttribute(key, value);
  });
  (Array.isArray(children) ? children : [children]).forEach((child) => {
    if (child === null || child === undefined) return;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  });
  return node;
}

function showToast(message, { duration = 3200 } = {}) {
  const toast = el("div", { className: "ubetra-toast" }, message);
  document.body.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("visible"));
  setTimeout(() => {
    toast.classList.remove("visible");
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

const ORGASM_TYPE_PRESETS = [
  "Full Orgasm",
  "Ruined Orgasm",
  "Denied",
  "Milking",
  "Partial-Milking",
  "Dildo",
  "Handjob",
  "PiV",
  "Finger",
  "Oral",
  "Vibrator",
  "Masturbation",
  "Cheated",
  "Anal",
  "Prostate",
];
const PLAY_TYPE_PRESETS = [
  "Edging",
  "Massage",
  "Spanking",
  "Foot rub",
];
const PARTNER_CONTEXT_OPTIONS = [
  { id: "partner", label: "Partner" },
  { id: "solo", label: "Solo" },
];

/** Curated outcome tags only — do not pull historical/legacy tags into the picker. */
function trackingTagPresets(kind) {
  return kind === "play" ? [...PLAY_TYPE_PRESETS] : [...ORGASM_TYPE_PRESETS];
}

function formatTrackingEventType(eventType) {
  if (eventType === "orgasm" || eventType === "both") return "Orgasm";
  if (eventType === "no_orgasm" || eventType === "sex") return "No orgasm (play)";
  return eventType;
}

function buildPartnerSoloRadio(name = `ctx-${Date.now()}`) {
  const wrap = el("div", { className: "row wrap partner-context-radio" });
  const inputs = PARTNER_CONTEXT_OPTIONS.map((opt, idx) => {
    const input = el("input", {
      type: "radio",
      name,
      value: opt.id,
      ...(idx === 0 ? { checked: "true" } : {}),
    });
    wrap.appendChild(el("label", { className: "checkbox-label" }, [input, ` ${opt.label}`]));
    return input;
  });
  return {
    wrap,
    getValue() {
      const picked = inputs.find((i) => i.checked);
      return picked ? picked.value : "partner";
    },
  };
}

function buildSatisfactionSelect() {
  const satisfaction = el("select");
  satisfaction.appendChild(el("option", { value: "" }, "—"));
  for (let i = 1; i <= 5; i += 1) {
    satisfaction.appendChild(el("option", { value: String(i) }, `${i}`));
  }
  return satisfaction;
}

function buildPartnerOrgasmPanel(partner, {
  showContextRadio = false,
  open = true,
  collapsible = true,
  initial = null,
} = {}) {
  const satisfaction = buildSatisfactionSelect();
  if (initial?.satisfaction != null) satisfaction.value = String(initial.satisfaction);
  const edgingCount = el("input", {
    type: "number",
    min: "0",
    max: "100",
    value: String(initial?.edging_count ?? 0),
  });
  const orgasmEditor = buildOrgasmListEditor(trackingTagPresets("orgasm"), initial?.orgasms || null);
  const contextRadio = showContextRadio ? buildPartnerSoloRadio(`ctx-${partner.id}`) : null;
  if (contextRadio && initial?.orgasms?.length) {
    const flat = (initial.orgasms || []).flatMap((o) => (o.tags || []).map((t) => String(t).toLowerCase()));
    const preferSolo = flat.includes("solo");
    contextRadio.wrap.querySelectorAll('input[type="radio"]').forEach((input) => {
      input.checked = preferSolo ? input.value === "solo" : input.value === "partner";
    });
  }
  const bodyChildren = [];
  if (contextRadio) {
    bodyChildren.push(el("div", { className: "stack" }, [
      el("strong", {}, "With"),
      contextRadio.wrap,
    ]));
  }
  bodyChildren.push(el("label", {}, ["Satisfaction (1–5)", satisfaction]));
  bodyChildren.push(el("label", {}, ["Edging count", edgingCount]));
  bodyChildren.push(el("p", { className: "muted" }, "Add each orgasm with its own tags."));
  bodyChildren.push(orgasmEditor.wrap);
  bodyChildren.push(orgasmEditor.addButton);

  let wrap;
  if (collapsible) {
    wrap = el("details", {
      className: "card stack partner-orgasm-panel",
      ...(open ? { open: "true" } : {}),
    }, [
      el("summary", {}, partner.display_name),
      el("div", { className: "stack partner-orgasm-panel-body" }, bodyChildren),
    ]);
  } else {
    wrap = el("div", { className: "card stack partner-orgasm-panel" }, [
      el("strong", {}, partner.display_name),
      ...bodyChildren,
    ]);
  }

  return {
    partner,
    wrap,
    getPayload() {
      const orgasms = orgasmEditor.getOrgasms().map((o) => ({ tags: [...o.tags] }));
      if (contextRadio) {
        const ctx = contextRadio.getValue();
        orgasms.forEach((o) => {
          const lower = o.tags.map((t) => t.toLowerCase());
          if (!lower.includes(ctx)) o.tags.push(ctx);
        });
      }
      const payload = {
        for_membership_id: partner.id,
        orgasms,
      };
      if (satisfaction.value) payload.satisfaction = parseInt(satisfaction.value, 10);
      else payload.satisfaction = null;
      if (edgingCount.value !== "") payload.edging_count = parseInt(edgingCount.value, 10) || 0;
      else payload.edging_count = null;
      return payload;
    },
  };
}

function buildOrgasmListEditor(presets, initialOrgasms = null) {
  const wrap = el("div", { className: "stack orgasm-list-editor" });
  const rows = [];

  function removeRow(card) {
    if (rows.length <= 1) return;
    const idx = rows.findIndex((r) => r.card === card);
    if (idx >= 0) rows.splice(idx, 1);
    card.remove();
  }

  function addRow(selected = []) {
    const tagPicker = buildTagPicker(presets, selected);
    const card = el("div", { className: "card stack" }, [
      el("label", {}, ["Orgasm tags", tagPicker.row, tagPicker.custom]),
      el("button", {
        type: "button",
        className: "ghost-btn",
        onClick: () => removeRow(card),
      }, "Remove orgasm"),
    ]);
    rows.push({ card, tagPicker });
    wrap.appendChild(card);
  }

  if (Array.isArray(initialOrgasms) && initialOrgasms.length) {
    initialOrgasms.forEach((o) => addRow(o.tags || []));
  } else {
    addRow();
  }
  const addButton = el("button", {
    type: "button",
    className: "ghost-btn",
    onClick: () => addRow(),
  }, "+ Add orgasm");

  return {
    wrap,
    addButton,
    getOrgasms() {
      return rows.map((r) => ({ tags: r.tagPicker.getTags() })).filter((o) => o.tags.length);
    },
  };
}

function buildTrackingEntryEditCard(dynamicId, entry, partners, { onSaved, onCancel } = {}) {
  const error = el("div", { className: "error hidden" });
  const isOrgasm = entry.event_type === "orgasm" || entry.event_type === "both";
  const eventType = el("select");
  [
    ["orgasm", "Orgasm"],
    ["no_orgasm", "No orgasm (play)"],
  ].forEach(([value, label]) => {
    const opt = el("option", { value }, label);
    if ((isOrgasm && value === "orgasm") || (!isOrgasm && value === "no_orgasm")) opt.selected = true;
    eventType.appendChild(opt);
  });
  const sessionStart = el("input", {
    type: "datetime-local",
    value: entry.occurred_at ? toLocalDatetimeValue(entry.occurred_at) : toLocalDatetimeValue(),
  });
  const sessionEnd = el("input", {
    type: "datetime-local",
    value: entry.ended_at ? toLocalDatetimeValue(entry.ended_at) : "",
  });
  const locationInput = el("input", {
    type: "text",
    maxlength: "120",
    value: entry.location || "",
    placeholder: "e.g. home, hotel",
  });
  const initiatedBy = el("select");
  initiatedBy.appendChild(el("option", { value: "" }, "—"));
  (partners || []).forEach((p) => {
    const opt = el("option", { value: p.id }, p.display_name);
    if (p.id === entry.initiated_by_membership_id) opt.selected = true;
    initiatedBy.appendChild(opt);
  });
  const protection = el("select");
  [
    ["", "—"],
    ["protected", "Protected"],
    ["unprotected", "Unprotected"],
    ["n_a", "N/A"],
  ].forEach(([value, label]) => {
    const opt = el("option", { value }, label);
    if (value === (entry.protection || "")) opt.selected = true;
    protection.appendChild(opt);
  });
  const notes = el("textarea", {
    rows: "3",
    placeholder: "Optional notes",
  }, entry.notes_hidden ? "" : (entry.notes || ""));
  const notesPrivate = el("input", { type: "checkbox" });
  notesPrivate.checked = !!entry.notes_private;

  const partner = (partners || []).find((p) => p.id === entry.for_membership_id)
    || { id: entry.for_membership_id, display_name: entry.for_display_name };
  const orgasmPanel = buildPartnerOrgasmPanel(partner, {
    showContextRadio: true,
    open: true,
    collapsible: false,
    initial: {
      satisfaction: entry.satisfaction,
      edging_count: entry.edging_count,
      orgasms: entry.orgasms || [],
    },
  });
  const playTagPicker = buildTagPicker(trackingTagPresets("play"), entry.tags || []);
  const playFields = el("div", { className: "stack" }, [
    el("label", {}, ["Play tags (optional)", playTagPicker.row, playTagPicker.custom]),
  ]);
  const orgasmFields = el("div", { className: "stack" }, [orgasmPanel.wrap]);

  function refreshEditFields() {
    const orgasm = eventType.value === "orgasm";
    orgasmFields.classList.toggle("hidden", !orgasm);
    playFields.classList.toggle("hidden", orgasm);
  }
  eventType.addEventListener("change", refreshEditFields);
  refreshEditFields();

  const card = el("div", { className: "card stack tracking-entry-edit" }, [
    el("h3", {}, `Edit · ${entry.for_display_name}`),
    el("label", {}, ["Event", eventType]),
    el("label", {}, ["Session start", sessionStart]),
    el("label", {}, ["Session end (optional)", sessionEnd]),
    el("label", {}, ["Location", locationInput]),
    el("label", {}, ["Who initiated", initiatedBy]),
    el("label", {}, ["Protection", protection]),
    orgasmFields,
    playFields,
    el("label", { className: "stack" }, ["Notes", notes]),
    el("label", { className: "checkbox-label" }, [
      notesPrivate,
      " Private notes (logger, partner, and keyholder only)",
    ]),
    error,
    el("div", { className: "row wrap" }, [
      el("button", {
        className: "primary-btn",
        type: "button",
        onClick: async () => {
          error.classList.add("hidden");
          try {
            const payload = {
              event_type: eventType.value,
              occurred_at: datetimeLocalToIso(sessionStart.value) || entry.occurred_at,
              ended_at: sessionEnd.value ? datetimeLocalToIso(sessionEnd.value) : null,
              location: locationInput.value.trim(),
              initiated_by_membership_id: initiatedBy.value || null,
              protection: protection.value,
              notes: notes.value.trim(),
              notes_private: notesPrivate.checked,
            };
            if (eventType.value === "orgasm") {
              const part = orgasmPanel.getPayload();
              if (!part.orgasms.length) throw new Error("Add at least one orgasm with tags.");
              payload.orgasms = part.orgasms;
              payload.satisfaction = part.satisfaction ?? null;
              payload.edging_count = part.edging_count ?? null;
              payload.tags = [];
            } else {
              payload.orgasms = [];
              payload.tags = playTagPicker.getTags();
              payload.satisfaction = null;
              payload.edging_count = null;
            }
            await api(`/dynamics/${dynamicId}/tracking/${entry.id}`, {
              method: "PATCH",
              body: JSON.stringify(payload),
            });
            onSaved?.();
          } catch (err) {
            error.textContent = err.message;
            error.classList.remove("hidden");
          }
        },
      }, "Save changes"),
      el("button", {
        className: "ghost-btn",
        type: "button",
        onClick: () => onCancel?.(),
      }, "Cancel"),
    ]),
  ]);
  return card;
}

/** Fixed accent hex per curated preset tag; unknown tags get a stable hash-based hue. */
const TAG_ACCENT_COLORS = {
  "full orgasm": "#ef4444",
  "ruined orgasm": "#f97316",
  "denied": "#6366f1",
  "milking": "#ec4899",
  "partial-milking": "#db2777",
  "dildo": "#a855f7",
  "handjob": "#0ea5e9",
  "piv": "#e11d48",
  "finger": "#14b8a6",
  "oral": "#f59e0b",
  "vibrator": "#8b5cf6",
  "masturbation": "#22c55e",
  "cheated": "#dc2626",
  "anal": "#7c3aed",
  "prostate": "#0891b2",
  "edging": "#f97316",
  "massage": "#22c55e",
  "spanking": "#ef4444",
  "foot rub": "#0ea5e9",
};

function hashColorForTag(tag) {
  let hash = 0;
  for (let i = 0; i < tag.length; i += 1) {
    hash = (hash << 5) - hash + tag.charCodeAt(i);
    hash |= 0;
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 60%, 52%)`;
}

/** Up to 3 accent colors for a log card's left stripe, sorted alphabetically for stability. */
function tagAccentColors(tags) {
  const unique = [...new Set((tags || []).map((t) => (t || "").trim()).filter(Boolean))];
  const sorted = unique.sort((a, b) => a.localeCompare(b));
  return sorted
    .slice(0, 3)
    .map((tag) => TAG_ACCENT_COLORS[tag.toLowerCase()] || hashColorForTag(tag.toLowerCase()));
}

function tagAccentGradient(colors) {
  if (!colors.length) return "";
  if (colors.length === 1) return colors[0];
  const step = 100 / colors.length;
  const stops = colors.map(
    (c, i) => `${c} ${(i * step).toFixed(1)}%, ${c} ${((i + 1) * step).toFixed(1)}%`
  );
  return `linear-gradient(to bottom, ${stops.join(", ")})`;
}

/** Relative, second-free timestamp: "3m ago", "Today 4:15 PM", "Yesterday 9:02 AM", "Tue 8:00 PM", "Jan 5". */
function formatLogWhen(value) {
  const d = parseServerDate(value);
  if (!d) return "—";
  const now = new Date();
  const startOfDay = (dt) => new Date(dt.getFullYear(), dt.getMonth(), dt.getDate()).getTime();
  const diffMs = now - d;
  const timeStr = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (diffMs >= 0 && diffMs < 60 * 60 * 1000) {
    const mins = Math.max(1, Math.round(diffMs / 60000));
    return `${mins}m ago`;
  }
  if (startOfDay(d) === startOfDay(now)) return `Today ${timeStr}`;
  const yesterday = new Date(startOfDay(now));
  yesterday.setDate(yesterday.getDate() - 1);
  if (startOfDay(d) === yesterday.getTime()) return `Yesterday ${timeStr}`;
  if (diffMs >= 0 && diffMs < 7 * 24 * 60 * 60 * 1000) {
    return `${d.toLocaleDateString(undefined, { weekday: "short" })} ${timeStr}`;
  }
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${timeStr}`;
}

/** Close any open kebab menu when clicking elsewhere on the page. */
document.addEventListener("click", () => {
  document.querySelectorAll(".kebab-menu:not(.hidden)").forEach((menu) => menu.classList.add("hidden"));
});

function buildKebabMenu(actions) {
  const menu = el("div", { className: "kebab-menu hidden" });
  actions.forEach(({ label, onClick, danger }) => {
    menu.appendChild(
      el(
        "button",
        {
          type: "button",
          className: `kebab-menu-item ${danger ? "danger" : ""}`,
          onClick: (e) => {
            e.stopPropagation();
            menu.classList.add("hidden");
            onClick();
          },
        },
        label
      )
    );
  });
  const btn = el(
    "button",
    {
      type: "button",
      className: "kebab-menu-btn",
      title: "More actions",
      "aria-label": "More actions",
      onClick: (e) => {
        e.stopPropagation();
        document.querySelectorAll(".kebab-menu:not(.hidden)").forEach((m) => {
          if (m !== menu) m.classList.add("hidden");
        });
        menu.classList.toggle("hidden");
      },
    },
    "⋮"
  );
  return el("div", { className: "kebab-menu-wrap" }, [btn, menu]);
}

function renderTrackingEntrySummary(entry, { dynamicId, editable = false, onChanged } = {}) {
  let expanded = false;

  function buildCard(onEdit, onDelete) {
    const allTags = entry.orgasms?.length
      ? entry.orgasms.flatMap((o) => o.tags || [])
      : entry.tags || [];
    const accentColors = tagAccentColors(allTags);
    const accentGradient = tagAccentGradient(accentColors);

    const card = el("div", {
      className: `card log-card ${accentGradient ? "log-card-accent" : ""} ${expanded ? "log-card-expanded" : "log-card-collapsed"}`,
    });
    if (accentGradient) card.style.setProperty("--log-card-accent", accentGradient);

    const headerRow = el(
      "button",
      {
        type: "button",
        className: "log-card-toggle row wrap",
        onClick: () => {
          expanded = !expanded;
          renderView();
        },
      },
      [
        el("div", { className: "stack log-card-main" }, [
          el("strong", {}, entry.for_display_name),
          el("span", { className: "muted log-card-when" }, formatLogWhen(entry.occurred_at)),
        ]),
        el("span", { className: "pill" }, formatTrackingEventType(entry.event_type)),
      ]
    );

    const topRow = el("div", { className: "row log-card-top" }, [headerRow]);
    if (onEdit || onDelete) {
      topRow.appendChild(
        buildKebabMenu(
          [
            onEdit ? { label: "Edit", onClick: onEdit } : null,
            onDelete ? { label: "Delete", onClick: onDelete, danger: true } : null,
          ].filter(Boolean)
        )
      );
    }
    card.appendChild(topRow);

      if (entry.during_lockup) {
      const lockLabel = entry.during_own_lockup
        ? "During lockup"
        : `Partner locked: ${(entry.locked_partner_names || []).join(", ") || "yes"}`;
      card.appendChild(el("span", { className: "pill log-card-lockup" }, lockLabel));
    }

    if (!expanded) return card;

    if (allTags.length) {
      const chipsRow = el("div", { className: "tag-filter-row log-card-chips" });
      const sortedTags = [...allTags].sort((a, b) => a.localeCompare(b));
      sortedTags.forEach((tag, idx) => {
        chipsRow.appendChild(
          el("span", { className: `tag-chip active ${idx < 2 ? "primary" : "secondary"}` }, tag)
        );
      });
      card.appendChild(chipsRow);
    }

    const details = el("div", { className: "stack log-card-details" });
    const metaBits = [];
    if (entry.ended_at || entry.duration_minutes != null) {
      const range = [];
      range.push(formatLogWhen(entry.occurred_at));
      if (entry.ended_at) range.push(`→ ${formatLogWhen(entry.ended_at)}`);
      if (entry.duration_minutes != null) range.push(`${entry.duration_minutes}m`);
      metaBits.push(range.join(" "));
    }
    if (entry.location) metaBits.push(`📍 ${entry.location}`);
    if (entry.protection) metaBits.push(String(entry.protection).replace(/_/g, " "));
    if (entry.satisfaction != null) metaBits.push(`★ ${entry.satisfaction}/5`);
    if (entry.edging_count != null) metaBits.push(`${entry.edging_count} edges`);
    if (entry.initiated_by_display_name) metaBits.push(`↗ ${entry.initiated_by_display_name}`);
    if (metaBits.length) details.appendChild(el("p", { className: "muted" }, metaBits.join(" · ")));

    const notesText = entry.notes_hidden ? "Private notes hidden" : entry.notes || null;
    if (notesText) details.appendChild(el("p", { className: entry.notes_hidden ? "muted" : "" }, notesText));

    if (entry.orgasms?.length) {
      entry.orgasms.forEach((orgasm, idx) => {
        const oTags = (orgasm.tags || []).join(", ");
        details.appendChild(
          el(
            "p",
            { className: "muted log-card-orgasm" },
            `Orgasm ${idx + 1}${oTags ? ` · ${oTags}` : ""}`
          )
        );
      });
    }
    if (entry.session_id && entry.session_entry_count > 1 && dynamicId) {
      details.appendChild(
        el(
          "button",
          {
            className: "link-btn",
            type: "button",
            onClick: () => navigate(`/dynamic/${dynamicId}/history/sessions/${entry.session_id}`),
          },
          "View linked session →"
        )
      );
    }
    card.appendChild(details);
    return card;
  }

  const host = el("div", { className: editable && dynamicId ? "stack tracking-entry-host" : "" });

  function renderView() {
    if (!editable || !dynamicId) {
      host.replaceChildren(buildCard());
      return;
    }
    function showEdit() {
      const partners = state.currentDynamic?.partners || [];
      host.replaceChildren(
        buildTrackingEntryEditCard(dynamicId, entry, partners, {
          onSaved: () => onChanged?.(),
          onCancel: () => renderView(),
        })
      );
    }
    async function doDelete() {
      if (!confirm("Delete this entry?")) return;
      try {
        await api(`/dynamics/${dynamicId}/tracking/${entry.id}`, { method: "DELETE" });
        onChanged?.();
      } catch (err) {
        alert(err.message);
      }
    }
    host.replaceChildren(buildCard(showEdit, doDelete));
  }

  renderView();
  return host;
}

function buildTagPicker(presets, selected = []) {
  const selectedSet = new Set(selected.map((t) => t.toLowerCase()));
  const row = el("div", { className: "tag-filter-row tag-picker" });
  presets.forEach((tag) => {
    const btn = el("button", {
      type: "button",
      className: `tag-chip ${selectedSet.has(tag.toLowerCase()) ? "active" : ""}`,
    }, tag);
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const key = tag.toLowerCase();
      if (selectedSet.has(key)) {
        selectedSet.delete(key);
        btn.classList.remove("active");
      } else {
        selectedSet.add(key);
        btn.classList.add("active");
      }
    });
    row.appendChild(btn);
  });
  const custom = el("input", { placeholder: "Custom tags (comma-separated)" });
  return {
    row,
    custom,
    getTags() {
      const extra = custom.value.split(",").map((t) => t.trim()).filter(Boolean);
      return [...selectedSet, ...extra];
    },
  };
}

function parseServerDate(value) {
  if (value == null || value === "") return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === "number") {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const raw = String(value).trim();
  if (!raw) return null;
  // Already timezone-aware
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(raw)) {
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  // Date-only → UTC midnight
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const d = new Date(`${raw}T00:00:00Z`);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  // Server stores naive UTC — treat as UTC, not local
  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const d = new Date(/[zZ]$/.test(normalized) ? normalized : `${normalized}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatLocalDateTime(value, options) {
  const d = parseServerDate(value);
  if (!d) return "—";
  return options ? d.toLocaleString(undefined, options) : d.toLocaleString();
}

function toLocalDatetimeValue(date = new Date()) {
  const d = date instanceof Date ? date : parseServerDate(date);
  if (!d || Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  // datetime-local needs the user's wall-clock time (local timezone)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function datetimeLocalToIso(value) {
  if (!value) return null;
  // Parse datetime-local components as local wall time (never as UTC)
  const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!m) {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d.toISOString();
  }
  const d = new Date(
    Number(m[1]),
    Number(m[2]) - 1,
    Number(m[3]),
    Number(m[4]),
    Number(m[5]),
    Number(m[6] || 0),
  );
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function feelingsAtJustAfter(isoOrDate) {
  const d = parseServerDate(isoOrDate) || new Date();
  if (Number.isNaN(d.getTime())) return new Date(Date.now() + 60_000).toISOString();
  d.setTime(d.getTime() + 60_000);
  return d.toISOString();
}

function navigateToFeelingsAfterEvent(dynamicId, { at, from, orgEntryId, chastityLockupId, context } = {}) {
  const params = new URLSearchParams();
  params.set("at", feelingsAtJustAfter(at || new Date().toISOString()));
  if (from) params.set("from", from);
  if (orgEntryId) params.set("org_entry_id", orgEntryId);
  if (chastityLockupId) params.set("chastity_lockup_id", chastityLockupId);
  if (context) params.set("context", context);
  navigate(`/dynamic/${dynamicId}/feelings?${params.toString()}`);
}

function shiftLocalDatetime(minutesAgo) {
  return toLocalDatetimeValue(new Date(Date.now() - minutesAgo * 60 * 1000));
}

function buildTimeSelector({ label, defaultValue, shortcuts = true } = {}) {
  const input = el("input", {
    type: "datetime-local",
  });
  if (defaultValue) input.value = defaultValue;
  else if (defaultValue !== "") input.value = toLocalDatetimeValue();
  const wrap = el("label", { className: "stack time-selector" }, [
    label || "Time",
    input,
  ]);
  if (shortcuts) {
    const row = el("div", { className: "row wrap time-shortcuts" });
    [
      ["now", "Now", 0],
      ["15m", "15m ago", 15],
      ["30m", "30m ago", 30],
      ["1h", "1h ago", 60],
    ].forEach(([, text, mins]) => {
      row.appendChild(el("button", {
        type: "button",
        className: "ghost-btn time-shortcut-btn",
        onClick: (e) => {
          e.preventDefault();
          input.value = mins ? shiftLocalDatetime(mins) : toLocalDatetimeValue();
        },
      }, text));
    });
    wrap.appendChild(row);
  }
  return {
    wrap,
    input,
    getIso() {
      return datetimeLocalToIso(input.value);
    },
  };
}

function buildBreakTypePicker(settings, { selectedId, isDominant, allowUndecided = false } = {}) {
  const breakTypes = settings.break_types || [];
  const emergency = new Set(settings.emergency_break_types || []);
  const selected = { id: selectedId || "" };
  const customReason = el("input", {
    placeholder: "Describe the reason",
    className: "hidden",
  });
  const needsCustom = (id) => id === "authorized_other" || id === "emergency_other";
  const wrap = el("div", { className: "stack" });
  const groups = [
    { title: "Authorized", items: breakTypes.filter((t) => !emergency.has(t.id) && (allowUndecided || t.id !== "authorized_undecided")) },
    { title: "Emergency", items: breakTypes.filter((t) => emergency.has(t.id)) },
  ];
  if (!isDominant) {
    groups[0].items = [];
  } else if (allowUndecided) {
    const undecided = breakTypes.find((t) => t.id === "authorized_undecided");
    if (undecided && !groups[0].items.some((t) => t.id === undecided.id)) {
      groups[0].items.push(undecided);
    }
  }
  groups.forEach((group) => {
    if (!group.items.length) return;
    wrap.appendChild(el("p", { className: "muted" }, group.title));
    const row = el("div", { className: "tag-filter-row break-type-picker" });
    group.items.forEach((type) => {
      const btn = el("button", {
        type: "button",
        className: `tag-chip ${selected.id === type.id ? "active" : ""}`,
        onClick: (e) => {
          e.preventDefault();
          selected.id = type.id;
          row.querySelectorAll(".tag-chip").forEach((chip) => chip.classList.remove("active"));
          btn.classList.add("active");
          customReason.classList.toggle("hidden", !needsCustom(type.id));
        },
      }, type.label);
      row.appendChild(btn);
    });
    wrap.appendChild(row);
  });
  wrap.appendChild(customReason);
  return {
    wrap,
    getPayload() {
      if (!selected.id) return null;
      const reason = needsCustom(selected.id) ? customReason.value.trim() : "";
      if (needsCustom(selected.id) && !reason) return null;
      return { break_type: selected.id, break_reason: reason };
    },
  };
}

function openChastityFlow(flowHost, title, bodyNodes, onBack) {
  flowHost.classList.remove("hidden");
  flowHost.replaceChildren(
    el("div", { className: "card stack chastity-flow" }, [
      el("div", { className: "row wrap chastity-flow-header" }, [
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            flowHost.classList.add("hidden");
            flowHost.replaceChildren();
            if (onBack) onBack();
          },
        }, "← Back"),
        el("h2", {}, title),
      ]),
      ...(Array.isArray(bodyNodes) ? bodyNodes : [bodyNodes]),
    ])
  );
  flowHost.scrollIntoView({ behavior: "smooth", block: "start" });
}

function closeChastityFlow(flowHost) {
  flowHost.classList.add("hidden");
  flowHost.replaceChildren();
}

function chatKeyStorage(dynamicId) {
  return `ubetra_chat_key_${dynamicId}`;
}

function hasChatCryptoKey(dynamicId) {
  return !!(dynamicId && localStorage.getItem(chatKeyStorage(dynamicId)));
}

const VAULT_PLAIN_PREFIX = "ubetra:plain:";

function cryptoSubtleAvailable() {
  return !!(globalThis.crypto && globalThis.crypto.subtle);
}

function encryptionUnavailableError() {
  const err = new Error(
    "Encryption needs HTTPS or localhost (Web Crypto). Turn off E2E in Settings → Privacy, or open http://127.0.0.1:8000."
  );
  err.code = "ENCRYPTION_UNAVAILABLE";
  return err;
}

function e2eKeyMissingError() {
  const err = new Error(
    "No shared chat encryption key yet. Turn on Encrypted chat in Settings → Privacy (or Chat ☰) once — every signed-in device will pick it up automatically."
  );
  err.code = "E2E_KEY_MISSING";
  return err;
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function base64ToBytes(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function importChatKeyRaw(storedB64) {
  const raw = base64ToBytes(storedB64);
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function getChatCryptoKey(dynamicId) {
  if (!cryptoSubtleAvailable()) throw encryptionUnavailableError();
  const stored = localStorage.getItem(chatKeyStorage(dynamicId));
  if (!stored) return null;
  return importChatKeyRaw(stored);
}

/** Create a brand-new key and cache it locally (caller uploads to server). */
async function createChatCryptoKey(dynamicId) {
  if (!cryptoSubtleAvailable()) throw encryptionUnavailableError();
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const stored = bytesToBase64(bytes);
  localStorage.setItem(chatKeyStorage(dynamicId), stored);
  return { key: await importChatKeyRaw(stored), raw: stored };
}

async function fetchSharedChatKey(dynamicId) {
  try {
    const res = await api(`/dynamics/${dynamicId}/chat/key`);
    if (res?.key) {
      localStorage.setItem(chatKeyStorage(dynamicId), res.key);
      return res.key;
    }
  } catch (err) {
    if (err.status === 404 || err.status === 400) return null;
    throw err;
  }
  return null;
}

async function uploadSharedChatKey(dynamicId, keyB64) {
  try {
    await api(`/dynamics/${dynamicId}/chat/key`, {
      method: "PUT",
      body: JSON.stringify({ key: keyB64 }),
    });
    return true;
  } catch (err) {
    // Another device already set a different key — use theirs instead.
    if (err.status === 409) {
      const fetched = await fetchSharedChatKey(dynamicId);
      return !!fetched;
    }
    throw err;
  }
}

const syncedChatKeys = new Set();

async function ensureChatCryptoKey(dynamicId, { createIfMissing = false } = {}) {
  if (!cryptoSubtleAvailable()) throw encryptionUnavailableError();

  let stored = localStorage.getItem(chatKeyStorage(dynamicId));
  if (stored) {
    if (!syncedChatKeys.has(dynamicId)) {
      await uploadSharedChatKey(dynamicId, stored).catch(() => false);
      syncedChatKeys.add(dynamicId);
    }
    return importChatKeyRaw(localStorage.getItem(chatKeyStorage(dynamicId)) || stored);
  }

  stored = await fetchSharedChatKey(dynamicId);
  if (stored) {
    syncedChatKeys.add(dynamicId);
    return importChatKeyRaw(stored);
  }

  if (!createIfMissing) throw e2eKeyMissingError();

  const created = await createChatCryptoKey(dynamicId);
  await uploadSharedChatKey(dynamicId, created.raw);
  syncedChatKeys.add(dynamicId);
  return created.key;
}

async function encryptChatText(dynamicId, text) {
  await ensureChatCryptoKey(dynamicId, { createIfMissing: false });
  const key = await getChatCryptoKey(dynamicId);
  if (!key) throw e2eKeyMissingError();
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encoded = new TextEncoder().encode(text);
  const cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, encoded);
  const packed = new Uint8Array(iv.length + cipher.byteLength);
  packed.set(iv, 0);
  packed.set(new Uint8Array(cipher), iv.length);
  return bytesToBase64(packed);
}

async function decryptChatText(dynamicId, payload) {
  if (!cryptoSubtleAvailable()) {
    return "[Encryption unavailable — open Settings]";
  }
  let key = await getChatCryptoKey(dynamicId);
  if (!key) {
    try {
      await ensureChatCryptoKey(dynamicId, { createIfMissing: false });
      key = await getChatCryptoKey(dynamicId);
    } catch {
      /* leave key null */
    }
  }
  if (!key) return "[Waiting for shared encryption key…]";
  try {
    const packed = base64ToBytes(payload);
    const iv = packed.slice(0, 12);
    const data = packed.slice(12);
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, data);
    return new TextDecoder().decode(plain);
  } catch {
    return "[Unable to decrypt — shared key may not match this ciphertext.]";
  }
}

function isCryptoPlaceholder(text) {
  return (
    typeof text === "string" &&
    (text.startsWith("[Encryption unavailable") ||
      text.startsWith("[Set up E2E") ||
      text.startsWith("[No key on this device") ||
      text.startsWith("[Unable to decrypt"))
  );
}

function renderCryptoPlaceholder(dynamicId, text) {
  return el("span", { className: "chat-crypto-placeholder" }, [
    el("span", {}, text.replace(/\s*—\s*open Settings\]?$/i, "").replace(/^\[|\]$/g, "") + " — "),
    el(
      "button",
      {
        type: "button",
        className: "link-btn",
        onClick: () => navigate(`/settings?dynamic=${dynamicId}`),
      },
      "Open Settings"
    ),
  ]);
}

async function encryptVaultPayload(dynamicId, text) {
  try {
    return await encryptChatText(dynamicId, text);
  } catch {
    // Large images or missing crypto — still store so the vault is never empty.
    return VAULT_PLAIN_PREFIX + text;
  }
}

async function decryptVaultPayload(dynamicId, payload) {
  if (!payload) return null;
  if (payload.startsWith(VAULT_PLAIN_PREFIX)) {
    return payload.slice(VAULT_PLAIN_PREFIX.length);
  }
  try {
    const text = await decryptChatText(dynamicId, payload);
    if (isCryptoPlaceholder(text)) return null;
    return text;
  } catch {
    return null;
  }
}

function readImageFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function partnerContactStorage(dynamicId) {
  return `ubetra_partner_contact_${dynamicId}`;
}

function chatBlurStorage() {
  return "ubetra_chat_blur_images";
}

function chatBlurModeStorage() {
  return "ubetra_chat_blur_mode";
}

function chatBlurPrefsMigratedStorage() {
  return "ubetra_chat_blur_prefs_v1";
}

/**
 * Resolve blur mode. New browsers default to hold; existing installs that already
 * had chat prefs / a token keep session unless they already chose a mode.
 * @returns {"hold"|"timed5"|"session"}
 */
function getChatBlurMode() {
  const stored = localStorage.getItem(chatBlurModeStorage());
  if (stored === "hold" || stored === "timed5" || stored === "session") return stored;

  if (!localStorage.getItem(chatBlurPrefsMigratedStorage())) {
    const hadBlurPref = localStorage.getItem(chatBlurStorage()) != null;
    const hadToken = localStorage.getItem("ubetra_token") != null;
    if (hadBlurPref || hadToken) {
      localStorage.setItem(chatBlurModeStorage(), "session");
      localStorage.setItem(chatBlurPrefsMigratedStorage(), "1");
      return "session";
    }
    localStorage.setItem(chatBlurModeStorage(), "hold");
    localStorage.setItem(chatBlurPrefsMigratedStorage(), "1");
    return "hold";
  }
  return "session";
}

function setChatBlurMode(mode) {
  localStorage.setItem(chatBlurModeStorage(), mode);
}

/**
 * Attach reveal behavior for a blurred image.
 * @param {HTMLImageElement} img
 * @param {{ id: string, revealedSet: Set<string>, locked?: boolean }} opts
 */
function attachBlurReveal(img, { id, revealedSet, locked = false }) {
  if (locked) {
    img.classList.add("blurred");
    img.classList.add("chat-image-protected");
    img.setAttribute("draggable", "false");
    img.style.cursor = "default";
    img.title = "Locked — permission required";
    img.addEventListener("contextmenu", (e) => e.preventDefault());
    img.addEventListener("dragstart", (e) => e.preventDefault());
    return;
  }
  const mode = getChatBlurMode();
  img.style.cursor = "pointer";
  img.setAttribute("draggable", "false");
  img.classList.add("chat-image-protected");
  img.addEventListener("contextmenu", (e) => e.preventDefault());
  img.addEventListener("dragstart", (e) => e.preventDefault());
  if (mode === "hold") {
    img.title = "Press and hold to unblur";
    let holdTimer = null;
    let holding = false;
    const show = () => img.classList.remove("blurred");
    const hide = () => {
      if (!revealedSet.has(id)) img.classList.add("blurred");
    };
    const clearHold = () => {
      if (holdTimer) {
        clearTimeout(holdTimer);
        holdTimer = null;
      }
      if (holding) {
        holding = false;
        hide();
      }
    };
    img.addEventListener("pointerdown", (e) => {
      if (e.button != null && e.button !== 0) return;
      e.preventDefault();
      try {
        img.setPointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
      holdTimer = setTimeout(() => {
        holding = true;
        show();
      }, 320);
    });
    img.addEventListener("pointerup", clearHold);
    img.addEventListener("pointerleave", clearHold);
    img.addEventListener("pointercancel", clearHold);
    img.addEventListener("lostpointercapture", clearHold);
  } else if (mode === "timed5") {
    img.title = "Tap to unblur for 5 seconds";
    img.addEventListener("click", (e) => {
      e.preventDefault();
      img.classList.remove("blurred");
      setTimeout(() => {
        if (!revealedSet.has(id)) img.classList.add("blurred");
      }, 5000);
    });
  } else {
    img.title = "Tap to unblur this session";
    img.addEventListener("click", (e) => {
      e.preventDefault();
      revealedSet.add(id);
      img.classList.remove("blurred");
    });
  }
}

function loadPartnerContact(dynamicId) {
  try {
    return JSON.parse(localStorage.getItem(partnerContactStorage(dynamicId)) || "{}");
  } catch {
    return {};
  }
}

function savePartnerContact(dynamicId, contact) {
  localStorage.setItem(partnerContactStorage(dynamicId), JSON.stringify(contact));
}

function buildShareLinks(dynamicId, code, hint) {
  const origin = window.location.origin;
  // App uses hash routing — path /settings is not a FastAPI route
  const settingsUrl = `${origin}/#/settings?redeem=${encodeURIComponent(code)}&dynamic=${encodeURIComponent(dynamicId)}`;
  const message = `UBETRA chat key — open this link and redeem the code in Privacy & security:\n${settingsUrl}\n\nCode: ${code}\n${hint}`;
  return { settingsUrl, message };
}

async function shareChatKeySecure(dynamicId, key) {
  const result = await api(`/dynamics/${dynamicId}/chat/key-share`, {
    method: "POST",
    body: JSON.stringify({ key }),
  });
  return result;
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
  return output;
}

async function getPushRegistration() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;
  return navigator.serviceWorker.ready;
}

async function subscribeChatPush() {
  if (isNativeApp()) {
    return subscribeNativePush();
  }
  if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    throw new Error(
      "Browsers only allow notifications on HTTPS (or localhost). Open this app over HTTPS — plain http:// LAN addresses cannot enable notifications."
    );
  }
  const reg = await getPushRegistration();
  if (!reg) throw new Error("Push notifications are not supported in this browser");
  const { public_key, configured } = await api("/push/public-key");
  if (!configured || !public_key) {
    throw new Error("Push is not configured on this server");
  }
  let permission = Notification.permission;
  if (permission === "default") {
    permission = await Notification.requestPermission();
  }
  if (permission !== "granted") {
    throw new Error("Notification permission denied — enable notifications for this site in browser settings");
  }
  let sub = await reg.pushManager.getSubscription();
  const expectedKey = urlBase64ToUint8Array(public_key);
  if (sub) {
    const existingKey = sub.options?.applicationServerKey;
    let keyMatches = true;
    if (existingKey) {
      const existing = existingKey instanceof ArrayBuffer
        ? new Uint8Array(existingKey)
        : new Uint8Array(existingKey);
      keyMatches =
        existing.byteLength === expectedKey.byteLength &&
        existing.every((b, i) => b === expectedKey[i]);
    }
    if (!keyMatches) {
      try {
        await api(`/push/subscribe?endpoint=${encodeURIComponent(sub.endpoint)}`, { method: "DELETE" });
      } catch {
        /* server may already lack this endpoint */
      }
      await sub.unsubscribe();
      sub = null;
    }
  }
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: expectedKey,
    });
  }
  const json = sub.toJSON();
  if (!json?.endpoint || !json?.keys?.p256dh || !json?.keys?.auth) {
    throw new Error("Browser returned an incomplete push subscription — try again");
  }
  await api("/push/subscribe", {
    method: "POST",
    body: JSON.stringify({
      endpoint: json.endpoint,
      keys: json.keys,
      expiration_time: json.expirationTime || null,
    }),
  });
  await api("/push/settings", {
    method: "PUT",
    body: JSON.stringify({ push_enabled: true }),
  });
  return sub;
}

async function unsubscribeChatPush() {
  if (isNativeApp()) {
    await unsubscribeNativePush();
    return;
  }
  const reg = await getPushRegistration();
  if (!reg) return;
  const sub = await reg.pushManager.getSubscription();
  if (sub) {
    await api(`/push/subscribe?endpoint=${encodeURIComponent(sub.endpoint)}`, { method: "DELETE" });
    await sub.unsubscribe();
  }
  // Do not flip global push_enabled / wipe other devices — only this endpoint was removed.
}

async function ensureChatPushEnabled() {
  if (!state.token) return false;
  try {
    const status = await api("/push/status");
    if (isNativeApp()) {
      if (!status.native_configured) return false;
    } else if (!status.configured) {
      return false;
    }
    if (typeof Notification !== "undefined" && Notification.permission === "denied") return false;
    // Re-subscribe even if push_enabled was previously false (e.g. old multi-device wipe),
    // so opening this device can restore notifications.
    await subscribeChatPush();
    return true;
  } catch {
    return false;
  }
}

function isNativeApp() {
  try {
    return !!(window.Capacitor && typeof window.Capacitor.isNativePlatform === "function" && window.Capacitor.isNativePlatform());
  } catch {
    return false;
  }
}

function isAndroidBrowser() {
  return /Android/i.test(navigator.userAgent || "");
}

/** Step-by-step Chrome / Edge Android settings so banners arrive while the PWA is closed. */
function openAndroidPushSetupGuide() {
  const backdrop = el("div", { className: "modal-backdrop" });
  const card = el("div", { className: "card stack modal-card push-setup-guide" }, [
    el("h3", {}, "Android notification setup"),
    el(
      "p",
      { className: "muted" },
      "Browsers often delay PWA push until you open the app. Do these once per phone:"
    ),
    el("ol", { className: "push-setup-list" }, [
      el("li", {}, "Install via Chrome/Edge ⋮ → Install app (not “Add to Home screen”)."),
      el("li", {}, "Android Settings → Apps → Chrome (or Edge) → Notifications → Allowed."),
      el("li", {}, "Same path → Battery → Unrestricted (or “Don’t optimize”)."),
      el("li", {}, "Samsung/Xiaomi: also allow the app in “Never sleeping apps” / Autostart."),
      el("li", {}, "Confirm Google Play Services is installed and up to date."),
      el("li", {}, "In UBETRA: Settings → Privacy → Notify this device → Allow."),
      el("li", {}, "Fully close the PWA, then send a test message from your partner."),
    ]),
    el(
      "p",
      { className: "muted" },
      "For reliable rings while Do Not Disturb is on, install the Android APK (see mobile/README) — PWAs cannot bypass DND."
    ),
    el("button", {
      type: "button",
      className: "primary-btn",
      onClick: () => backdrop.remove(),
    }, "Got it"),
  ]);
  backdrop.appendChild(card);
  backdrop.addEventListener("click", (ev) => {
    if (ev.target === backdrop) backdrop.remove();
  });
  document.body.appendChild(backdrop);
}

async function subscribeNativePush() {
  const PushNotifications = window.Capacitor?.Plugins?.PushNotifications;
  if (!PushNotifications) {
    throw new Error("Native push plugin is not available in this build");
  }
  let perm = await PushNotifications.checkPermissions();
  if (perm.receive !== "granted") {
    perm = await PushNotifications.requestPermissions();
  }
  if (perm.receive !== "granted") {
    throw new Error("Notification permission denied — enable notifications for UBETRA in Android settings");
  }
  await PushNotifications.register();
  const token = await new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("Timed out waiting for FCM token")), 20000);
    PushNotifications.addListener("registration", (ev) => {
      clearTimeout(t);
      resolve(ev.value);
    });
    PushNotifications.addListener("registrationError", (err) => {
      clearTimeout(t);
      reject(new Error(err?.error || "FCM registration failed"));
    });
  });
  await api("/push/native", {
    method: "POST",
    body: JSON.stringify({
      token,
      platform: "android",
      app_id: "ubetra-android",
    }),
  });
  await api("/push/settings", {
    method: "PUT",
    body: JSON.stringify({ push_enabled: true }),
  });
  return token;
}

async function unsubscribeNativePush() {
  const status = await api("/push/status").catch(() => null);
  // Best-effort: remove all native tokens for this user from server; plugin has no deleteToken on all platforms.
  await api("/push/native", { method: "DELETE" }).catch(() => {});
  return status;
}

function formatRole(role) {
  return role === "dominant" ? "Dominant" : "Submissive";
}

/** Prefer Dom & Sub display names over placeholder titles like "Our dynamic". */
function formatDynamicTitle(dynamic) {
  const partners = dynamic?.partners || [];
  const dom = partners.find((p) => p.role === "dominant");
  const sub = partners.find((p) => p.role === "submissive");
  if (dom?.display_name && sub?.display_name) {
    return `${dom.display_name} & ${sub.display_name}`;
  }
  const raw = (dynamic?.name || "").trim();
  if (raw && raw.toLowerCase() !== "our dynamic") return raw;
  if (dom?.display_name) return `${dom.display_name}'s dynamic`;
  if (sub?.display_name) return `${sub.display_name}'s dynamic`;
  const any = partners[0]?.display_name;
  return any ? `${any}'s dynamic` : raw || "Dynamic";
}

function getActiveDynamicId() {
  const { parts } = parseRoute();
  if (parts[0] === "dynamic" && parts[1]) return parts[1];
  if (parts[0] === "dashboard" && parts[1]) return parts[1];
  if (parts[0] === "chat" && parts[1]) return parts[1];
  return state.activeDynamicId || state.dynamics[0]?.id || null;
}

function facetBadge(facet, dynamic) {
  const you = dynamic?.partners?.find((p) => p.is_you);
  if (!you || !facet.badge) return null;
  if (facet.badge === "interview") {
    return you.interview_completed ? { text: "Done", ok: true } : { text: "Needed", ok: false };
  }
  if (facet.badge === "survey") {
    return you.survey_submitted ? { text: "Done", ok: true } : { text: "Needed", ok: false };
  }
  return null;
}

function updateBottomNav() {
  const { parts } = parseRoute();
  const authPages = ["login", "register", "onboarding"];
  const hide = !state.token || authPages.includes(parts[0]) || parts[0] === "settings";
  bottomNavEl.classList.toggle("hidden", hide);
  if (hide) return;

  const dynamicId = getActiveDynamicId();
  const enabledFeatures = state.currentDynamic?.enabled_features || [];
  const playtimeOn =
    !enabledFeatures.length || enabledFeatures.includes("scene_workshop");
  const trackingRoutes = new Set([
    "track", "tracking", "chastity", "feelings", "tasks", "acts", "punishment",
    "history", "vault", "journal", "ground-rules", "interview", "survey",
    "knowledge", "context", "gear", "features", "overlap",
  ]);
  const playtimeRoutes = new Set(["assistant"]);
  const activeTab =
    parts[0] === "chat" ? "chat"
    : parts[0] === "dynamic" && playtimeRoutes.has(parts[2]) ? "workshop"
    : "tracking";

  bottomNavEl.replaceChildren(
    ...NAV_TABS.map((tab) => {
      const featureOff = tab.id === "workshop" && dynamicId && !playtimeOn;
      const disabled = !tab.enabled || (tab.requiresDynamic && !dynamicId) || featureOff;
      const btn = el("button", {
        className: `nav-tab ${activeTab === tab.id ? "active" : ""} ${disabled ? "disabled" : ""}`,
        type: "button",
        title: featureOff ? "Playtime is turned off in Application features" : "",
        onClick: () => {
          if (disabled) return;
          if (tab.id === "tracking" && dynamicId) navigate(`/dynamic/${dynamicId}/track`);
          if (tab.id === "workshop" && dynamicId) navigate(`/dynamic/${dynamicId}/assistant`);
          if (tab.id === "chat" && dynamicId) navigate(`/chat/${dynamicId}`);
        },
      }, [
        el("span", { className: "nav-icon" }, tab.icon),
        tab.label,
      ]);
      return btn;
    })
  );
}

/** Hub title row with Application features hamburger. */
function buildHubHeader(dynamicId, title, { subtitle = "", sectionFilter = "all" } = {}) {
  const ham = el("button", {
    type: "button",
    className: "hub-features-btn",
    title: "Application features",
    "aria-label": "Application features",
  }, "☰");
  ham.addEventListener("click", () => openAppFeaturesPanel(dynamicId, sectionFilter));
  return el("div", { className: "hub-header row" }, [
    el("div", { className: "stack hub-header-copy" }, [
      el("h1", {}, title),
      subtitle ? el("p", { className: "muted" }, subtitle) : null,
    ]),
    ham,
  ]);
}

function openAppFeaturesPanel(dynamicId, sectionFilter = "all") {
  const backdrop = el("div", { className: "modal-backdrop app-features-backdrop" });
  const error = el("p", { className: "error hidden" });
  const status = el("p", { className: "muted" });
  const body = el("div", { className: "card stack modal-card app-features-panel" }, [
    el("h3", {}, "Application features"),
    el("p", { className: "muted" }, "Turn optional tools on or off for this dynamic."),
    status,
    error,
  ]);
  backdrop.appendChild(body);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) backdrop.remove();
  });
  document.body.appendChild(backdrop);

  Promise.all([
    api(`/dynamics/${dynamicId}/features`),
    api(`/dynamics/${dynamicId}/policy`).catch(() => null),
    loadDynamic(dynamicId),
  ])
    .then(([features, policy]) => {
      const youAreDominant = policy?.you_are_dominant === true;
      const checks = {};
      const list = el("div", { className: "stack" });
      const optional = (features.optional || []).filter((f) => {
        if (sectionFilter === "all") return true;
        if (sectionFilter === "tracking") return f.section === "tracking" || f.section === "knowledge";
        if (sectionFilter === "playtime") return f.section === "playtime";
        if (sectionFilter === "chat") return f.id === "image_vault";
        return true;
      });
      if (!optional.length) {
        list.appendChild(el("p", { className: "muted" }, "No optional features for this menu."));
      }
      optional.forEach((feature) => {
        const box = el("input", { type: "checkbox" });
        box.checked = feature.enabled;
        checks[feature.id] = box;
        list.appendChild(el("label", { className: "checkbox-label" }, [box, ` ${feature.title}`]));
      });
      body.appendChild(list);
      body.appendChild(el("div", { className: "row wrap" }, [
        el("button", {
          type: "button",
          className: "primary-btn",
          onClick: async () => {
            error.classList.add("hidden");
            try {
              if (youAreDominant) {
                const enabled_optional = [];
                Object.entries(checks).forEach(([id, box]) => {
                  if (!box.checked) return;
                  enabled_optional.push(id);
                  const meta = features.optional.find((f) => f.id === id);
                  if (meta?.paired_with) enabled_optional.push(meta.paired_with);
                });
                (features.optional || []).forEach((f) => {
                  if (optional.some((o) => o.id === f.id)) return;
                  if (f.enabled) {
                    enabled_optional.push(f.id);
                    if (f.paired_with) enabled_optional.push(f.paired_with);
                  }
                });
                const updated = await api(`/dynamics/${dynamicId}/features`, {
                  method: "PUT",
                  body: JSON.stringify({ enabled_optional: [...new Set(enabled_optional)] }),
                });
                if (state.currentDynamic?.id === dynamicId) {
                  state.currentDynamic.enabled_features = updated.enabled;
                }
                status.textContent = "Saved.";
                updateBottomNav();
                setTimeout(() => backdrop.remove(), 400);
              } else {
                const dirty = [];
                optional.forEach((feature) => {
                  const box = checks[feature.id];
                  if (!box || box.checked === feature.enabled) return;
                  dirty.push({
                    settingKey: `features.${feature.id}`,
                    settingLabel: `Feature: ${feature.title}`,
                    requestedValue: box.checked,
                  });
                });
                if (!dirty.length) {
                  status.textContent = "No changes.";
                  return;
                }
                for (const d of dirty) {
                  await postSettingsChangeRequest({
                    dynamicId,
                    settingKey: d.settingKey,
                    settingLabel: d.settingLabel,
                    requestedValue: d.requestedValue,
                    note: "From Application features menu",
                  });
                }
                status.textContent = "Request sent to keyholder.";
                setTimeout(() => backdrop.remove(), 700);
              }
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, youAreDominant ? "Save" : "Submit settings change"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => backdrop.remove(),
        }, "Close"),
      ]));
    })
    .catch((err) => {
      error.textContent = err.message;
      error.classList.remove("hidden");
    });
}

function isFacetEnabled(facet, enabledFeatures) {
  if (facet.core) return true;
  if (!enabledFeatures || !enabledFeatures.length) return true;
  if (enabledFeatures.includes(facet.id)) return true;
  if (Array.isArray(facet.alsoEnabledBy)) {
    return facet.alsoEnabledBy.some((id) => enabledFeatures.includes(id));
  }
  return false;
}

function navigateFacet(dynamicId, facet) {
  if (!facet.route) return;
  navigate(`/dynamic/${dynamicId}/${facet.route}`);
}

function renderFacetRow(facet, dynamicId, dynamic) {
  const badge = facetBadge(facet, dynamic);
  const row = el("button", {
    className: "facet-row",
    type: "button",
    onClick: () => navigateFacet(dynamicId, facet),
  }, [
    el("span", { className: "facet-icon" }, facet.icon),
    el("span", { className: "facet-copy" }, [
      el("span", { className: "facet-title" }, facet.title),
      el("span", { className: "facet-subtitle" }, facet.subtitle),
    ]),
    el("span", { className: "facet-chevron" }, badge
      ? el("span", { className: `pill ${badge.ok ? "ok" : "pending"}` }, badge.text)
      : "›"),
  ]);
  return row;
}

function setViewContent(node) {
  const { parts } = parseRoute();
  if (parts[0] !== "chat") {
    viewEl.classList.remove("chat-view");
    if (typeof window.__ubetraStopChatLive === "function") {
      window.__ubetraStopChatLive();
      window.__ubetraStopChatLive = null;
    }
  }
  viewEl.replaceChildren(node);
  updateBottomNav();
}

async function bootstrap() {
  setAuthVisible(!!state.token);
  if (!logoutBtn || !settingsBtn || !viewEl || !bottomNavEl) {
    console.error("UBETRA: required DOM elements missing");
    return;
  }
  logoutBtn.addEventListener("click", () => {
    setToken(null);
    state.user = null;
    state.dynamics = [];
    inboxCheckedDynamics.clear();
    navigate("/login");
  });
  settingsBtn.addEventListener("click", () => navigate("/settings"));
  if (installPwaBtn) {
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      deferredPwaPrompt = e;
      updateInstallPwaButton();
    });
    window.addEventListener("appinstalled", () => {
      deferredPwaPrompt = null;
      updateInstallPwaButton();
    });
    installPwaBtn.addEventListener("click", async () => {
      if (deferredPwaPrompt) {
        deferredPwaPrompt.prompt();
        await deferredPwaPrompt.userChoice;
        deferredPwaPrompt = null;
        updateInstallPwaButton();
        return;
      }
      alert(
        "To install as a real app (no browser bar):\n\n"
        + "• Chrome: menu ⋮ → Install app (or Install page as app)\n"
        + "• Edge: menu ⋯ → Add to phone → Install\n\n"
        + "Avoid “Add to Home screen” / shortcut — that keeps the address bar.\n"
        + "After installing, delete any old shortcut and open the new app icon.\n\n"
        + "Note: Edge on Android may show a “Tap to copy URL” banner; that is browser UI and cannot be turned off by the site."
      );
    });
    updateInstallPwaButton();
  }
  if (appBrandEl) {
    appBrandEl.addEventListener("click", () => goHomeFromBrand());
    appBrandEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        goHomeFromBrand();
      }
    });
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
    navigator.serviceWorker.addEventListener("message", (event) => {
      if (event.data?.type === "ubetra-push-should-suppress") {
        const port = event.ports?.[0];
        if (!port) return;
        const dynId = event.data.dynamicId || "";
        const { parts } = parseRoute();
        const onThisChat = parts[0] === "chat" && !!dynId && parts[1] === dynId;
        const visible =
          document.visibilityState === "visible" &&
          (typeof document.hasFocus !== "function" || document.hasFocus());
        port.postMessage({ suppress: onThisChat && visible });
        return;
      }
      if (event.data?.type === "ubetra-push-resync") {
        ensureChatPushEnabled().catch(() => {});
        return;
      }
      if (event.data?.type === "ubetra-navigate" && event.data.url) {
        let path = event.data.url;
        if (path.startsWith("/#")) path = path.slice(2);
        else if (path.startsWith("#")) path = path.slice(1);
        navigate(path.startsWith("/") ? path : `/${path}`);
      }
      if (event.data?.type === "ubetra-chat-push") {
        window.dispatchEvent(
          new CustomEvent("ubetra-chat-push", {
            detail: {
              dynamicId: event.data.dynamicId,
              url: event.data.url,
            },
          })
        );
      }
    });
    // Re-sync FCM subscription when returning to the PWA (Android often rotates endpoints).
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible" || !state.token) return;
      if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
      ensureChatPushEnabled().catch(() => {});
    });
  }

  window.addEventListener("hashchange", renderRoute);

  // Render login immediately so buttons work while token validation runs
  if (!state.token) {
    navigate("/login");
  } else {
    renderRoute();
  }

  if (state.token) {
    try {
      state.user = await api("/auth/me");
      state.dynamics = await api("/dynamics");
      navigateAfterAuth();
      return;
    } catch {
      setToken(null);
      state.user = null;
      state.dynamics = [];
      navigate("/login");
    }
  }
}

function renderLogin() {
  setAuthVisible(false);
  const error = el("div", { className: "error hidden" });
  const form = el("form", { className: "stack auth-card" }, [
    el("h1", {}, "Sign in"),
    el("p", { className: "muted" }, "Use the email address for your account."),
    el("label", {}, ["Email", el("input", { name: "email", type: "email", required: "true", autocomplete: "email" })]),
    el("label", {}, ["Password", el("input", { name: "password", type: "password", required: "true", autocomplete: "current-password" })]),
    error,
    el("button", { className: "primary-btn", type: "submit" }, "Continue"),
  ]);
  const registerLink = el("button", {
    className: "ghost-btn",
    type: "button",
    onClick: () => navigate("/register"),
  }, "Create account");
  const claimLink = el("button", {
    className: "ghost-btn",
    type: "button",
    onClick: () => renderClaimEmail(),
  }, "Add email to existing account");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.classList.add("hidden");
    const data = new FormData(form);
    try {
      const result = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: data.get("email"),
          password: data.get("password"),
        }),
      });
      if (result.mfa_required) {
        mfaSession = { token: result.mfa_token, emailHint: result.email_hint };
        renderMfaVerify();
        return;
      }
      setToken(result.access_token);
      state.user = await api("/auth/me");
      state.dynamics = await api("/dynamics");
      navigateAfterAuth();
    } catch (err) {
      error.textContent = err.message;
      error.classList.remove("hidden");
    }
  });

  api("/auth/config").then((cfg) => {
    if (cfg.allow_public_register) form.appendChild(registerLink);
    if (cfg.mfa_required) form.appendChild(claimLink);
  }).catch(() => {
    form.appendChild(registerLink);
    form.appendChild(claimLink);
  });

  viewEl.replaceChildren(el("div", { className: "auth-splash" }, [form]));
}

function renderClaimEmail() {
  setAuthVisible(false);
  const error = el("div", { className: "error hidden" });
  const form = el("form", { className: "stack auth-card" }, [
    el("h1", {}, "Add email"),
    el("p", { className: "muted" }, "Existing accounts need an email to sign in. Enter your current username and password, then add an email."),
    el("label", {}, ["Username", el("input", { name: "username", required: "true", autocomplete: "username" })]),
    el("label", {}, ["Password", el("input", { name: "password", type: "password", required: "true", autocomplete: "current-password" })]),
    el("label", {}, ["Email", el("input", { name: "email", type: "email", required: "true", autocomplete: "email" })]),
    error,
    el("button", { className: "primary-btn", type: "submit" }, "Continue"),
    el("button", { className: "ghost-btn", type: "button", onClick: () => navigate("/login") }, "Back"),
  ]);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.classList.add("hidden");
    const data = new FormData(form);
    try {
      const result = await api("/auth/claim-email", {
        method: "POST",
        body: JSON.stringify({
          username: data.get("username"),
          password: data.get("password"),
          email: data.get("email"),
        }),
      });
      if (result.mfa_required) {
        mfaSession = { token: result.mfa_token, emailHint: result.email_hint };
        renderMfaVerify();
        return;
      }
      setToken(result.access_token);
      state.user = await api("/auth/me");
      state.dynamics = await api("/dynamics");
      navigateAfterAuth();
    } catch (err) {
      error.textContent = err.message;
      error.classList.remove("hidden");
    }
  });
  viewEl.replaceChildren(el("div", { className: "auth-splash" }, [form]));
}

function renderMfaVerify() {
  setAuthVisible(false);
  const error = el("div", { className: "error hidden" });
  const hint = mfaSession.emailHint
    ? `We sent a one-time code to ${mfaSession.emailHint}.`
    : "We sent a one-time code to your email.";
  const form = el("form", { className: "stack auth-card" }, [
    el("h1", {}, "Check your email"),
    el("p", { className: "muted" }, hint),
    el("label", {}, ["Code", el("input", {
      name: "code",
      required: "true",
      inputmode: "numeric",
      autocomplete: "one-time-code",
      placeholder: "6-digit code",
    })]),
    error,
    el("button", { className: "primary-btn", type: "submit" }, "Verify"),
    el("button", {
      className: "ghost-btn",
      type: "button",
      onClick: async () => {
        error.classList.add("hidden");
        try {
          const result = await api("/auth/mfa/resend", {
            method: "POST",
            body: JSON.stringify({ mfa_token: mfaSession.token }),
          });
          mfaSession = { token: result.mfa_token, emailHint: result.email_hint || mfaSession.emailHint };
          error.className = "muted";
          error.textContent = "Code sent again.";
          error.classList.remove("hidden");
        } catch (err) {
          error.className = "error";
          error.textContent = err.message;
          error.classList.remove("hidden");
        }
      },
    }, "Resend code"),
    el("button", {
      className: "ghost-btn",
      type: "button",
      onClick: () => navigate("/login"),
    }, "Back"),
  ]);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.className = "error hidden";
    const data = new FormData(form);
    try {
      const result = await api("/auth/mfa/verify", {
        method: "POST",
        body: JSON.stringify({
          mfa_token: mfaSession.token,
          code: String(data.get("code") || "").trim(),
        }),
      });
      mfaSession = { token: null, emailHint: null };
      setToken(result.access_token);
      state.user = await api("/auth/me");
      state.dynamics = await api("/dynamics");
      navigateAfterAuth();
    } catch (err) {
      error.className = "error";
      error.textContent = err.message;
      error.classList.remove("hidden");
    }
  });

  viewEl.replaceChildren(el("div", { className: "auth-splash" }, [form]));
}

function renderRegister() {
  setAuthVisible(false);
  const error = el("div", { className: "error hidden" });
  const form = el("form", { className: "stack auth-card" }, [
    el("h1", {}, "Create account"),
    el("p", { className: "muted" }, "Email is for sign-in. Username is your name in the dynamic (your keyholder can change a sub’s username later)."),
    el("label", {}, ["Email", el("input", { name: "email", type: "email", required: "true", autocomplete: "email" })]),
    el("label", {}, ["Username", el("input", { name: "username", required: "true", autocomplete: "username" })]),
    el("label", {}, ["Password", el("input", { name: "password", type: "password", required: "true", autocomplete: "new-password" })]),
    error,
    el("button", { className: "primary-btn", type: "submit" }, "Continue"),
    el("button", { className: "ghost-btn", type: "button", onClick: () => navigate("/login") }, "Back to sign in"),
  ]);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.classList.add("hidden");
    const data = new FormData(form);
    try {
      const result = await api("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          username: data.get("username"),
          email: data.get("email"),
          password: data.get("password"),
        }),
      });
      if (result.mfa_required) {
        mfaSession = { token: result.mfa_token, emailHint: result.email_hint };
        renderMfaVerify();
        return;
      }
      setToken(result.access_token);
      state.user = await api("/auth/me");
      state.dynamics = [];
      navigate("/onboarding");
    } catch (err) {
      error.textContent = err.message;
      error.classList.remove("hidden");
    }
  });

  viewEl.replaceChildren(el("div", { className: "auth-splash" }, [form]));
}

function renderOnboarding() {
  viewEl.replaceChildren(el("p", { className: "muted" }, "Loading setup..."));
  Promise.all([
    api("/onboarding/status"),
    api("/settings/llm/providers"),
  ])
    .then(async ([status, providers]) => {
      const step = onboardingStep(status);
      const error = el("div", { className: "error hidden" });
      const stack = el("div", { className: "stack onboarding" }, [
        el("h1", {}, "Welcome to UBETRA"),
        el("p", { className: "muted" }, "A short setup so the assistant can tailor suggestions to your dynamic."),
        error,
      ]);

      const steps = ["dynamic", "api", "spti", "survey", "finish"];
      const stepLabels = ["Dynamic", "AI key", "SPTI", "Kinks", "Done"];
      const stepper = el("div", { className: "onboarding-steps" });
      steps.forEach((id, idx) => {
        const active = id === step;
        const done = steps.indexOf(step) > idx;
        stepper.appendChild(el("span", {
          className: `onboarding-step ${active ? "active" : ""} ${done ? "done" : ""}`,
        }, stepLabels[idx]));
      });
      stack.appendChild(stepper);

      const panel = el("div", { className: "card stack" });
      stack.appendChild(panel);

      if (step === "dynamic") {
        panel.appendChild(el("h2", {}, "Start or join a dynamic"));
        panel.appendChild(el("p", { className: "muted" }, "Create a new relationship space or join your partner with their invite code."));
        const createCard = el("div", { className: "stack" }, [
          el("h3", {}, "Start a new dynamic"),
          el("label", {}, ["Name", el("input", { id: "ob-dynamic-name", placeholder: "Leave blank — becomes Dom & Sub names", value: "" })]),
          el("label", {}, [
            "Your role",
            el("select", { id: "ob-create-role" }, [
              el("option", { value: "dominant" }, "Dominant"),
              el("option", { value: "submissive" }, "Submissive"),
            ]),
          ]),
          el("button", {
            className: "primary-btn",
            type: "button",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api("/dynamics", {
                  method: "POST",
                  body: JSON.stringify({
                    name: document.getElementById("ob-dynamic-name").value.trim() || "Our dynamic",
                    role: document.getElementById("ob-create-role").value,
                  }),
                });
                state.dynamics = await api("/dynamics");
                renderOnboarding();
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Create dynamic"),
        ]);
        const joinCard = el("div", { className: "stack" }, [
          el("h3", {}, "Join an existing dynamic"),
          el("label", {}, ["Invite code", el("input", { id: "ob-invite-code", placeholder: "ABC12345" })]),
          el("label", {}, [
            "Your role",
            el("select", { id: "ob-join-role" }, [
              el("option", { value: "submissive" }, "Submissive"),
              el("option", { value: "dominant" }, "Dominant"),
            ]),
          ]),
          el("button", {
            className: "primary-btn",
            type: "button",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api("/dynamics/join", {
                  method: "POST",
                  body: JSON.stringify({
                    invite_code: document.getElementById("ob-invite-code").value,
                    role: document.getElementById("ob-join-role").value,
                  }),
                });
                state.dynamics = await api("/dynamics");
                renderOnboarding();
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Join dynamic"),
        ]);
        panel.appendChild(createCard);
        panel.appendChild(joinCard);
      }

      if (step === "api") {
        const providerMap = Object.fromEntries(providers.filter((p) => p.id !== "server").map((p) => [p.id, p]));
        const providerSelect = el("select");
        providers.filter((p) => p.id !== "server").forEach((provider) => {
          providerSelect.appendChild(el("option", { value: provider.id }, provider.label));
        });
        const modelSelect = el("select");
        const modelCustom = el("input", { placeholder: "Model name" });
        const apiKeyInput = el("input", { type: "password", placeholder: "Paste API key", autocomplete: "off" });
        const description = el("p", { className: "muted" });
        const providerRow = el("div", { className: "row wrap" }, [
          el("label", { className: "grow" }, ["AI provider", providerSelect]),
        ]);

        function refreshProviderUi() {
          const selected = providerMap[providerSelect.value];
          description.textContent = selected?.description || "";
          providerRow.replaceChildren(
            el("label", { className: "grow" }, ["AI provider", providerSelect]),
            providerHelpBtn(selected),
          );
          modelSelect.replaceChildren();
          (selected?.models || []).forEach((model) => {
            modelSelect.appendChild(el("option", { value: model }, model));
          });
          if (selected?.default_model) modelCustom.value = selected.default_model;
        }
        providerSelect.addEventListener("change", refreshProviderUi);
        modelSelect.addEventListener("change", () => { modelCustom.value = modelSelect.value; });
        refreshProviderUi();

        panel.appendChild(el("h2", {}, "AI provider setup"));
        panel.appendChild(el("p", { className: "muted" }, "This key is shared for your dynamic — both partners use it for the assistant. If your partner already configured one, you would have skipped this step."));
        panel.appendChild(providerRow);
        panel.appendChild(description);
        panel.appendChild(el("label", {}, ["Model", modelSelect]));
        panel.appendChild(el("label", {}, ["Custom model (optional)", modelCustom]));
        panel.appendChild(el("label", {}, ["API key", apiKeyInput]));
        panel.appendChild(el("div", { className: "row wrap" }, [
          el("button", {
            className: "primary-btn",
            type: "button",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api(`/dynamics/${status.dynamic_id}/shared-llm`, {
                  method: "PUT",
                  body: JSON.stringify({
                    provider: providerSelect.value,
                    model: modelCustom.value || modelSelect.value,
                    api_key: apiKeyInput.value.trim(),
                  }),
                });
                renderOnboarding();
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Save shared API key"),
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api("/onboarding/skip-api", { method: "POST" });
                renderOnboarding();
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Fill out later"),
        ]));
      }

      if (step === "spti") {
        const results = el("textarea", {
          placeholder: "Paste your SPTI results here after completing the test…",
          rows: 8,
        });
        panel.appendChild(el("h2", {}, "SPTI personality test"));
        panel.appendChild(el("p", { className: "muted" }, "The Sexual Personality Type Inventory helps the assistant understand your preferences, boundaries, and communication style. Results are stored privately and used as context for scene ideas — never shown to your partner verbatim."));
        panel.appendChild(el("a", {
          className: "primary-btn inline-link",
          href: "https://spti-test.com/",
          target: "_blank",
          rel: "noopener noreferrer",
        }, "Take the test at spti-test.com (48 questions)"));
        panel.appendChild(el("label", {}, ["Paste results", results]));
        panel.appendChild(el("div", { className: "row wrap" }, [
          el("button", {
            className: "primary-btn",
            type: "button",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api("/onboarding/spti", {
                  method: "PUT",
                  body: JSON.stringify({ results: results.value, skipped: false }),
                });
                renderOnboarding();
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Save results"),
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: async () => {
              await api("/onboarding/spti", {
                method: "PUT",
                body: JSON.stringify({ skipped: true }),
              });
              renderOnboarding();
            },
          }, "Skip for now"),
        ]));
      }

      if (step === "survey") {
        panel.appendChild(el("h2", {}, "Kink survey"));
        panel.appendChild(el("p", { className: "muted" }, "Rate interests with the color key below. You can refine answers anytime from your dynamic menu."));
        panel.appendChild(el("div", { className: "interest-key" }, [
          el("span", { className: "key-item want" }, "Want to do"),
          el("span", { className: "key-item if" }, "If they want"),
          el("span", { className: "key-item not" }, "Not interested"),
          el("span", { className: "key-item none" }, "No answer"),
        ]));
        panel.appendChild(el("div", { className: "row wrap" }, [
          el("button", {
            className: "primary-btn",
            type: "button",
            onClick: () => navigate(`/dynamic/${status.dynamic_id}/survey?onboarding=1`),
          }, "Open kink survey"),
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api("/onboarding/skip-survey", { method: "POST" });
                renderOnboarding();
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Fill out later"),
        ]));
        panel.appendChild(el("p", { className: "muted" }, "Submit the survey when you're done to continue, or skip and fill it in later."));
      }

      if (step === "finish") {
        panel.appendChild(el("h2", {}, "You're all set"));
        panel.appendChild(el("p", { className: "muted" }, "Your dynamic is ready. Invite your partner if you haven't yet — they'll get their own onboarding flow."));
        if (status.invite_code) {
          panel.appendChild(el("div", { className: "card" }, [
            el("p", {}, "Share this invite code with your partner:"),
            el("h3", {}, status.invite_code),
          ]));
        }
        panel.appendChild(el("button", {
          className: "primary-btn",
          type: "button",
          onClick: async () => {
            error.classList.add("hidden");
            try {
              await api("/onboarding/complete", { method: "POST" });
              state.user = await api("/auth/me");
              navigate(`/dynamic/${status.dynamic_id}`);
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Go to dynamic"));
      }

      viewEl.replaceChildren(stack);
      updateBottomNav();
    })
    .catch((err) => viewEl.replaceChildren(el("p", { className: "error" }, err.message)));
}

const HISTORY_REPORTS = [
  { id: "weekly", title: "Weekly activity", subtitle: "Orgasm comparison, weekly trends, and averages", needsChastity: false, yearBased: false },
  { id: "chastity-days", title: "Days in chastity", subtitle: "Calendar of full, partial, and free days", needsChastity: true, yearBased: true },
  { id: "orgasms", title: "Orgasm report", subtitle: "Charts, averages, monthly trends, and intervals", needsChastity: false, yearBased: true },
  { id: "chastity-stats", title: "Chastity statistics", subtitle: "Sessions, durations, locked %, monthly charts", needsChastity: true, yearBased: true },
  { id: "sessions", title: "Linked sessions", subtitle: "Entries within 1 hour grouped together", needsChastity: false, yearBased: false },
  { id: "org-log", title: "Orgasm & sex log", subtitle: "View, edit, and delete logged entries", needsChastity: false, yearBased: false },
  { id: "chastity-log", title: "Chastity lockup log", subtitle: "Lockup periods with edit controls", needsChastity: true, yearBased: false },
];

function historyReportShell(dynamicId, title, bodyNodes, { onBack } = {}) {
  const stack = el("div", { className: "stack" }, [
    el("div", { className: "row wrap" }, [
      el("button", {
        className: "ghost-btn",
        type: "button",
        onClick: () => (onBack ? onBack() : navigate(`/dynamic/${dynamicId}/history`)),
      }, "← History"),
      el("h1", {}, title),
    ]),
    ...(Array.isArray(bodyNodes) ? bodyNodes : [bodyNodes]),
    el("button", {
      className: "ghost-btn",
      onClick: () => navigate(`/dynamic/${dynamicId}`),
    }, "Back to dynamic"),
  ]);
  setViewContent(stack);
  return stack;
}

function buildYearPicker(year, onChange) {
  const select = el("select");
  const current = new Date().getFullYear();
  for (let y = current; y >= current - 5; y -= 1) {
    const opt = el("option", { value: String(y) }, String(y));
    if (y === year) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener("change", () => onChange(parseInt(select.value, 10)));
  return el("label", {}, ["Year", select]);
}

function buildDaysPicker(days, onChange) {
  const select = el("select");
  [[30, "30 days"], [90, "90 days"], [180, "6 months"], [365, "1 year"]].forEach(([value, label]) => {
    const opt = el("option", { value: String(value) }, label);
    if (value === days) opt.selected = true;
    select.appendChild(opt);
  });
  select.addEventListener("change", () => onChange(parseInt(select.value, 10)));
  return el("label", {}, ["Period", select]);
}

function renderChastityCalendar(days) {
  const byMonth = {};
  days.forEach((d) => {
    const key = d.date.slice(0, 7);
    if (!byMonth[key]) byMonth[key] = [];
    byMonth[key].push(d);
  });
  const wrap = el("div", { className: "chastity-calendar-wrap" });
  Object.keys(byMonth).sort().forEach((monthKey) => {
    const monthEl = el("div", { className: "chastity-month card stack" }, [
      el("h3", {}, new Date(`${monthKey}-01T12:00:00`).toLocaleString(undefined, { month: "long", year: "numeric" })),
    ]);
    const grid = el("div", { className: "chastity-day-grid" });
    byMonth[monthKey].forEach((day) => {
      grid.appendChild(el("span", {
        className: `chastity-day-cell ${day.status}`,
        title: `${day.date} · ${day.status}`,
      }, String(new Date(`${day.date}T12:00:00`).getDate())));
    });
    monthEl.appendChild(grid);
    wrap.appendChild(monthEl);
  });
  wrap.appendChild(el("p", { className: "muted" }, "Bright = full calendar day locked (breaks ≤20m) · Outlined = partial (2h+) · Dim = free · Whole days = rolling 24h streaks"));
  return wrap;
}

function renderStatsTable(rows) {
  const table = el("table", { className: "stats-table" });
  const tbody = el("tbody");
  rows.forEach(([label, value]) => {
    tbody.appendChild(el("tr", {}, [
      el("td", {}, label),
      el("td", {}, String(value ?? "—")),
    ]));
  });
  table.appendChild(tbody);
  return table;
}

/** Horizontal compare bars: [{label, value, tone?}] */
function renderCompareBars(items, { unit = "" } = {}) {
  const max = Math.max(1, ...items.map((i) => Number(i.value) || 0));
  const wrap = el("div", { className: "compare-list" });
  items.forEach((item, idx) => {
    const value = Number(item.value) || 0;
    const width = Math.round((value / max) * 100);
    wrap.appendChild(el("div", { className: "compare-row" }, [
      el("span", { className: "compare-label" }, item.label),
      el("div", { className: "compare-bar-wrap" }, [
        el("div", {
          className: `compare-bar ${item.tone || (idx % 2 === 0 ? "org" : "alt")}`,
          style: `width:${Math.max(width, value > 0 ? 4 : 0)}%`,
        }),
      ]),
      el("span", { className: "compare-value" }, `${value}${unit}`),
    ]));
  });
  return wrap;
}

/** Metric tiles: [{label, value, hint?}] */
function renderMetricTiles(items) {
  const grid = el("div", { className: "metric-tile-grid" });
  items.forEach((item) => {
    grid.appendChild(el("div", { className: "metric-tile" }, [
      el("div", { className: "metric-tile-value" }, String(item.value ?? "—")),
      el("div", { className: "metric-tile-label" }, item.label),
      item.hint ? el("div", { className: "metric-tile-hint" }, item.hint) : null,
    ].filter(Boolean)));
  });
  return grid;
}

/**
 * Vertical bar chart.
 * series: [{label, values: number[], titles?: string[]}]
 * partnerLabels: string[] matching values index
 */
function renderHistoryBarChart(buckets, { valueKey, partnerIds, partnerNames, maxHint } = {}) {
  const chart = el("div", { className: "history-chart tall" });
  const getVal = (bucket, pid) => {
    if (typeof valueKey === "function") return valueKey(bucket, pid) || 0;
    const map = bucket[valueKey] || {};
    return map[pid] || 0;
  };
  const maxVal = Math.max(
    1,
    maxHint || 0,
    ...buckets.flatMap((b) => partnerIds.map((pid) => Number(getVal(b, pid)) || 0)),
  );
  buckets.forEach((bucket) => {
    const col = el("div", { className: "history-week" });
    col.appendChild(el("span", { className: "history-week-label" }, bucket.label));
    const bars = el("div", { className: "history-week-bars" });
    partnerIds.forEach((pid, idx) => {
      const count = Number(getVal(bucket, pid)) || 0;
      const height = Math.round((count / maxVal) * 100);
      bars.appendChild(el("div", {
        className: `history-week-bar p${idx}`,
        style: `height:${Math.max(height, count > 0 ? 6 : 2)}%`,
        title: `${partnerNames[idx] || "Partner"}: ${count}`,
      }));
    });
    col.appendChild(bars);
    chart.appendChild(col);
  });
  return chart;
}

function renderPartnerLegend(partners) {
  const row = el("div", { className: "history-legend" });
  partners.forEach((p, idx) => {
    row.appendChild(el("span", { className: `history-legend-item p${idx}` }, p.name || p));
  });
  return row;
}

function renderHistoryHub(dynamicId) {
  const id = dynamicId || getActiveDynamicId();
  if (!id) {
    renderHome();
    return;
  }
  state.activeDynamicId = id;
  setViewContent(el("p", { className: "muted" }, "Loading history..."));
  Promise.all([
    loadDynamic(id),
    api(`/dynamics/${id}/chastity/overview`).catch(() => ({ any_enabled: false })),
  ]).then(([, chastityOverview]) => {
    const stack = el("div", { className: "stack" }, [
      el("h1", {}, "History"),
      el("p", { className: "muted" }, "Reports, charts, and logs — pick one to open."),
    ]);
    const list = el("div", { className: "facet-list" });
    HISTORY_REPORTS.forEach((report) => {
      if (report.needsChastity && !chastityOverview.any_enabled) return;
      list.appendChild(el("button", {
        className: "facet-row",
        type: "button",
        onClick: () => navigate(`/dynamic/${id}/history/${report.id}`),
      }, [
        el("span", { className: "facet-icon" }, "📊"),
        el("span", { className: "facet-text" }, [
          el("span", { className: "facet-title" }, report.title),
          el("span", { className: "facet-subtitle" }, report.subtitle),
        ]),
      ]));
    });
    stack.appendChild(list);
    stack.appendChild(el("button", {
      className: "ghost-btn",
      onClick: () => navigate(`/dynamic/${id}`),
    }, "Back to dynamic"));
    setViewContent(stack);
  }).catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderHistoryReport(dynamicId, reportId) {
  const id = dynamicId || getActiveDynamicId();
  if (!id) {
    renderHome();
    return;
  }
  const report = HISTORY_REPORTS.find((r) => r.id === reportId);
  if (!report) {
    navigate(`/dynamic/${id}/history`);
    return;
  }
  state.activeDynamicId = id;
  let year = new Date().getFullYear();
  let days = report.id === "chastity-log" ? 365 : 90;
  let selectedTags = [];

  function paintWeekly() {
    const tagQuery = selectedTags.length ? `&tags=${encodeURIComponent(selectedTags.join(","))}` : "";
    api(`/dynamics/${id}/history/reports/weekly?days=${days}${tagQuery}`)
      .then((data) => {
        const partnerIds = data.partners.map((p) => p.membership_id);
        const partnerNames = data.partners.map((p) => p.name);
        const buckets = data.weekly_buckets.slice(-12);
        const nodes = [
          buildDaysPicker(days, (v) => { days = v; paintWeekly(); }),
          el("p", { className: "muted" }, data.comparison_label),
          renderPartnerLegend(data.partners),
        ];

        const compare = el("div", { className: "card stack" }, [
          el("h2", {}, "Orgasm totals"),
          renderCompareBars(data.partners.map((p) => ({ label: p.name, value: p.orgasm_count }))),
        ]);
        nodes.push(compare);

        nodes.push(el("div", { className: "card stack" }, [
          el("h2", {}, "Averages this period"),
          renderMetricTiles(data.partners.flatMap((p) => {
            const weeks = Math.max(1, days / 7);
            return [
              { label: `${p.name} / week`, value: (p.orgasm_count / weeks).toFixed(1), hint: "orgasms" },
              { label: `${p.name} duration`, value: p.avg_duration_minutes != null ? `${p.avg_duration_minutes}m` : "—", hint: "avg session" },
              { label: `${p.name} play`, value: p.play_count, hint: "no-O sessions" },
            ];
          })),
        ]));

        nodes.push(el("div", { className: "card stack" }, [
          el("h2", {}, "Weekly orgasms"),
          renderHistoryBarChart(buckets, {
            valueKey: "orgasms_by_partner",
            partnerIds,
            partnerNames,
          }),
          el("p", { className: "muted" }, "Bars = orgasm count per partner each week"),
        ]));

        nodes.push(el("div", { className: "card stack" }, [
          el("h2", {}, "Weekly play sessions"),
          renderHistoryBarChart(buckets, {
            valueKey: "play_by_partner",
            partnerIds,
            partnerNames,
          }),
        ]));

        nodes.push(el("div", { className: "card stack" }, [
          el("h2", {}, "Weekly ruined / denial tags"),
          renderHistoryBarChart(buckets, {
            valueKey: "ruined_by_partner",
            partnerIds,
            partnerNames,
          }),
        ]));

        nodes.push(el("div", { className: "card stack" }, [
          el("h2", {}, "Average session duration (min)"),
          renderHistoryBarChart(buckets, {
            valueKey: (bucket, pid) => bucket.avg_duration_by_partner?.[pid] || 0,
            partnerIds,
            partnerNames,
          }),
        ]));

        if (data.chastity_any_enabled) {
          nodes.push(el("div", { className: "card stack" }, [
            el("h2", {}, "Weekly chastity % locked"),
            renderHistoryBarChart(buckets, {
              valueKey: "chastity_locked_pct_by_partner",
              partnerIds,
              partnerNames,
              maxHint: 100,
            }),
            el("p", { className: "muted" }, "Height = percent of the week locked (sub only)"),
          ]));
        }

        historyReportShell(id, report.title, nodes);
      })
      .catch((err) => historyReportShell(id, report.title, el("p", { className: "error" }, err.message)));
  }

  function paintChastityDays() {
    api(`/dynamics/${id}/history/reports/chastity-days?year=${year}`)
      .then((data) => {
        const nodes = [buildYearPicker(year, (y) => { year = y; paintChastityDays(); })];
        if (!data.partners.length) {
          nodes.push(el("p", { className: "muted" }, "Chastity not enabled."));
        }
        data.partners.forEach((partner) => {
          nodes.push(el("div", { className: "card stack" }, [
            el("h2", {}, partner.name),
            renderMetricTiles([
              { label: "Rolling whole days", value: partner.whole_days },
              { label: "Partial days", value: partner.partial_days },
              { label: "Free days", value: partner.free_days },
            ]),
            renderChastityCalendar(partner.days),
          ]));
        });
        historyReportShell(id, report.title, nodes);
      })
      .catch((err) => historyReportShell(id, report.title, el("p", { className: "error" }, err.message)));
  }

  function paintOrgasms() {
    const tagQuery = selectedTags.length ? `&tags=${encodeURIComponent(selectedTags.join(","))}` : "";
    Promise.all([
      api(`/dynamics/${id}/history/reports/orgasms?year=${year}${tagQuery}`),
      api(`/dynamics/${id}/tracking-prefs`).catch(() => ({ metrics: [] })),
    ])
      .then(([data, prefs]) => {
        const metricOn = Object.fromEntries((prefs.metrics || []).map((m) => [m.id, m.enabled]));
        const show = (key, fallback = true) => (key in metricOn ? metricOn[key] : fallback);
        const nodes = [
          buildYearPicker(year, (y) => { year = y; paintOrgasms(); }),
          el("p", { className: "muted" }, data.note),
          renderPartnerLegend(data.partners),
        ];

        if (show("total_orgasms") || show("ruined_count") || show("play_days")) {
          const compareCard = el("div", { className: "card stack" }, [el("h2", {}, "Year totals")]);
          if (show("total_orgasms")) {
            compareCard.appendChild(el("h3", { className: "chart-subhead" }, "Orgasms"));
            compareCard.appendChild(renderCompareBars(data.partners.map((p) => ({ label: p.name, value: p.total_orgasms }))));
          }
          if (show("ruined_count")) {
            compareCard.appendChild(el("h3", { className: "chart-subhead" }, "Ruined / denial"));
            compareCard.appendChild(renderCompareBars(data.partners.map((p) => ({ label: p.name, value: p.ruined_orgasms, tone: "warn" }))));
          }
          if (show("play_days")) {
            compareCard.appendChild(el("h3", { className: "chart-subhead" }, "Play days"));
            compareCard.appendChild(renderCompareBars(data.partners.map((p) => ({ label: p.name, value: p.play_days, tone: "alt" }))));
          }
          nodes.push(compareCard);
        }

        if (show("avg_rates") || show("avg_duration") || show("avg_satisfaction") || show("avg_edging")) {
          const tiles = [];
          data.partners.forEach((p) => {
            if (show("avg_rates")) {
              tiles.push({ label: `${p.name} / week`, value: p.avg_orgasms_per_week ?? "—", hint: "avg orgasms" });
              tiles.push({ label: `${p.name} / month`, value: p.avg_orgasms_per_month ?? "—", hint: "avg orgasms" });
              tiles.push({ label: `${p.name} ruin / mo`, value: p.avg_ruined_per_month ?? "—", hint: "avg ruined" });
            }
            if (show("avg_duration")) {
              tiles.push({
                label: `${p.name} duration`,
                value: p.avg_duration_minutes != null ? `${p.avg_duration_minutes}m` : "—",
                hint: "avg session",
              });
            }
            if (show("avg_satisfaction")) {
              tiles.push({ label: `${p.name} satisfaction`, value: p.avg_satisfaction ?? "—", hint: "1–5 avg" });
            }
            if (show("avg_edging")) {
              tiles.push({ label: `${p.name} edging`, value: p.avg_edging_count ?? "—", hint: "avg count" });
            }
          });
          nodes.push(el("div", { className: "card stack" }, [
            el("h2", {}, "Averages"),
            renderMetricTiles(tiles),
          ]));
        }

        if (show("monthly_charts") && data.partners.some((p) => (p.monthly || []).length)) {
          const months = data.partners[0]?.monthly || [];
          const partnerIds = data.partners.map((p) => p.membership_id);
          const partnerNames = data.partners.map((p) => p.name);
          const monthBuckets = months.map((m, idx) => {
            const orgasms_by_partner = {};
            const ruined_by_partner = {};
            const play_by_partner = {};
            const duration_by_partner = {};
            data.partners.forEach((p) => {
              const row = (p.monthly || [])[idx] || {};
              orgasms_by_partner[p.membership_id] = row.orgasms || 0;
              ruined_by_partner[p.membership_id] = row.ruined || 0;
              play_by_partner[p.membership_id] = row.play_sessions || 0;
              duration_by_partner[p.membership_id] = row.avg_duration_minutes || 0;
            });
            return {
              label: m.label,
              orgasms_by_partner,
              ruined_by_partner,
              play_by_partner,
              duration_by_partner,
            };
          });
          nodes.push(el("div", { className: "card stack" }, [
            el("h2", {}, "Monthly orgasms"),
            renderHistoryBarChart(monthBuckets, {
              valueKey: "orgasms_by_partner",
              partnerIds,
              partnerNames,
            }),
          ]));
          nodes.push(el("div", { className: "card stack" }, [
            el("h2", {}, "Monthly ruined tags"),
            renderHistoryBarChart(monthBuckets, {
              valueKey: "ruined_by_partner",
              partnerIds,
              partnerNames,
            }),
          ]));
          nodes.push(el("div", { className: "card stack" }, [
            el("h2", {}, "Monthly play sessions"),
            renderHistoryBarChart(monthBuckets, {
              valueKey: "play_by_partner",
              partnerIds,
              partnerNames,
            }),
          ]));
          nodes.push(el("div", { className: "card stack" }, [
            el("h2", {}, "Monthly avg duration (min)"),
            renderHistoryBarChart(monthBuckets, {
              valueKey: (bucket, pid) => bucket.duration_by_partner?.[pid] || 0,
              partnerIds,
              partnerNames,
            }),
          ]));
        }

        data.partners.forEach((p) => {
          const rows = [];
          if (show("days_with_without")) {
            rows.push(["Days with orgasms", p.days_with_orgasms]);
            rows.push(["Days without orgasms", p.days_without_orgasms]);
          }
          if (show("total_orgasms")) rows.push(["Total orgasms", p.total_orgasms]);
          if (show("lockup_context")) {
            rows.push(["Orgasms during lockup", p.orgasms_during_lockup]);
            rows.push(["Orgasms while self locked", p.orgasms_during_own_lockup]);
            rows.push(["Orgasms while partner locked", p.orgasms_while_partner_locked]);
          }
          if (show("full_orgasm_days")) rows.push(["Full orgasm days", p.full_orgasm_days]);
          if (show("play_days")) rows.push(["Play days (no O)", p.play_days]);
          if (show("ruined_count")) rows.push(["Ruined / denial count", p.ruined_orgasms]);
          if (show("avg_duration")) {
            rows.push(["Avg session duration", p.avg_duration_minutes != null ? `${p.avg_duration_minutes}m` : "—"]);
          }
          if (show("avg_rates")) {
            rows.push(["Avg orgasms / week", p.avg_orgasms_per_week]);
            rows.push(["Avg orgasms / month", p.avg_orgasms_per_month]);
            rows.push(["Avg ruined / month", p.avg_ruined_per_month]);
            rows.push(["Avg play days / month", p.avg_play_days_per_month]);
          }
          if (show("avg_satisfaction")) rows.push(["Avg satisfaction", p.avg_satisfaction]);
          if (show("avg_edging")) rows.push(["Avg edging count", p.avg_edging_count]);
          if (show("intervals_full")) {
            rows.push(["Max days between full O", p.max_days_between_full]);
            rows.push(["Min days between full O", p.min_days_between_full]);
            rows.push(["Avg days between full O", p.avg_days_between_full]);
          }
          if (show("intervals_any")) {
            rows.push(["Max days between any O", p.max_days_between_any]);
            rows.push(["Avg days between any O", p.avg_days_between_any]);
          }
          nodes.push(el("div", { className: "card stack" }, [
            el("h2", {}, p.name),
            rows.length
              ? renderStatsTable(rows)
              : el("p", { className: "muted" }, "All orgasm metrics are hidden in Settings."),
          ]));
        });
        historyReportShell(id, report.title, nodes);
      })
      .catch((err) => historyReportShell(id, report.title, el("p", { className: "error" }, err.message)));
  }

  function paintChastityStats() {
    api(`/dynamics/${id}/history/reports/chastity-stats?year=${year}`)
      .then((data) => {
        const nodes = [buildYearPicker(year, (y) => { year = y; paintChastityStats(); })];
        if (!data.partners.length) {
          nodes.push(el("p", { className: "muted" }, "Chastity not enabled."));
        }
        data.partners.forEach((p) => {
          nodes.push(el("div", { className: "card stack" }, [
            el("h2", {}, `${p.name} · ${data.year}`),
            renderMetricTiles([
              { label: "Sessions", value: p.sessions_count },
              { label: "% locked", value: `${p.percent_locked}%` },
              { label: "Avg locked", value: p.avg_locked_label },
              { label: "Avg session", value: p.avg_session_days != null ? `${p.avg_session_days}d` : "—", hint: "days" },
            ]),
            renderCompareBars([
              { label: "Locked", value: p.percent_locked, tone: "org" },
              { label: "Unlocked", value: p.percent_unlocked, tone: "alt" },
            ], { unit: "%" }),
            renderStatsTable([
              ["Max locked", p.max_locked_label],
              ["Min locked", p.min_locked_label],
              ["Cumulative locked", p.cumulative_locked_label],
              ["Cumulative unlocked", p.cumulative_unlocked_label],
            ]),
          ]));
          if ((p.monthly || []).length) {
            nodes.push(el("div", { className: "card stack" }, [
              el("h2", {}, `${p.name} · monthly % locked`),
              renderHistoryBarChart(
                p.monthly.map((m) => ({
                  label: m.label,
                  orgasms_by_partner: { [p.membership_id]: m.percent_locked },
                })),
                {
                  valueKey: "orgasms_by_partner",
                  partnerIds: [p.membership_id],
                  partnerNames: [p.name],
                  maxHint: 100,
                },
              ),
            ]));
          }
        });
        historyReportShell(id, report.title, nodes);
      })
      .catch((err) => historyReportShell(id, report.title, el("p", { className: "error" }, err.message)));
  }

  function paintSessions() {
    api(`/dynamics/${id}/history/reports/sessions?days=${days}`)
      .then((data) => {
        const list = el("div", { className: "stack" });
        if (!data.sessions.length) {
          list.appendChild(el("p", { className: "muted" }, "No linked sessions in this period."));
        }
        data.sessions.forEach((session) => {
          const subtitle = [
            `${session.orgasm_count} orgasms`,
            session.during_lockup ? `during lockup (${(session.locked_partner_names || []).join(", ") || "yes"})` : null,
          ].filter(Boolean).join(" · ");
          list.appendChild(el("button", {
            className: "facet-row",
            type: "button",
            onClick: () => navigate(`/dynamic/${id}/history/sessions/${session.session_id}`),
          }, [
            el("span", { className: "facet-icon" }, "🔗"),
            el("span", { className: "facet-text" }, [
              el("span", { className: "facet-title" }, `${formatLocalDateTime(session.started_at)} · ${session.entry_count} entries`),
              el("span", { className: "facet-subtitle" }, subtitle || "No orgasms logged"),
            ]),
          ]));
        });
        historyReportShell(id, report.title, [
          buildDaysPicker(days, (v) => { days = v; paintSessions(); }),
          el("p", { className: "muted" }, "Entries that overlap or fall within 1 hour of each other are grouped as one session."),
          list,
        ]);
      })
      .catch((err) => historyReportShell(id, report.title, el("p", { className: "error" }, err.message)));
  }

  function paintOrgLog() {
    const tagQuery = selectedTags.length ? `&tags=${encodeURIComponent(selectedTags.join(","))}` : "";
    api(`/dynamics/${id}/history/reports/org-log?days=${days}${tagQuery}`)
      .then((dashboard) => {
        const tagRow = el("div", { className: "tag-filter-row" });
        tagRow.appendChild(el("span", { className: "muted" }, "Tags:"));
        if (!dashboard.available_tags.length) {
          tagRow.appendChild(el("span", { className: "muted" }, " none"));
        } else {
          dashboard.available_tags.forEach((tag) => {
            const active = selectedTags.includes(tag);
            tagRow.appendChild(el("button", {
              className: `tag-chip ${active ? "active" : ""}`,
              type: "button",
              onClick: () => {
                if (active) selectedTags = selectedTags.filter((t) => t !== tag);
                else selectedTags = [...selectedTags, tag];
                paintOrgLog();
              },
            }, tag));
          });
        }
        const list = el("div", { className: "stack" });
        if (!dashboard.org_entries.length) {
          list.appendChild(el("p", { className: "muted" }, "No entries in this period."));
        }
        dashboard.org_entries.forEach((entry) => {
          list.appendChild(renderTrackingEntrySummary(entry, {
            dynamicId: id,
            editable: true,
            onChanged: () => paintOrgLog(),
          }));
        });
        historyReportShell(id, report.title, [
          buildDaysPicker(days, (v) => { days = v; paintOrgLog(); }),
          tagRow,
          list,
          el("button", {
            className: "link-btn",
            type: "button",
            onClick: () => navigate(`/dynamic/${id}/tracking`),
          }, "Log new event →"),
        ]);
      })
      .catch((err) => historyReportShell(id, report.title, el("p", { className: "error" }, err.message)));
  }

  function paintChastityLog() {
    api(`/dynamics/${id}/history/reports/chastity-log?days=${days}`)
      .then((dashboard) => {
        const list = el("div", { className: "stack" });
        if (!dashboard.chastity_lockups.length) {
          list.appendChild(el("p", { className: "muted" }, "No lockups in this period."));
        }
        dashboard.chastity_lockups.forEach((lockup) => {
          const card = el("div", { className: "card stack" }, [
            el("div", { className: "row" }, [
              el("strong", {}, lockup.for_display_name),
              el("span", { className: "pill" }, lockup.status),
            ]),
            el("p", { className: "muted" }, `${formatLocalDateTime(lockup.started_at)} · ${lockup.locked_duration_label} locked`),
          ]);
          if (lockup.breaks?.length) {
            lockup.breaks.forEach((brk) => {
              card.appendChild(el("p", { className: "muted" }, `Break: ${brk.break_reason} · ${formatLocalDateTime(brk.started_at)}`));
            });
          }
          if (lockup.status === "ended" && dashboard.you_are_dominant) {
            card.appendChild(el("button", {
              className: "ghost-btn",
              onClick: async () => {
                const started = prompt("Started (ISO)", lockup.started_at);
                if (started === null) return;
                const ended = prompt("Ended (ISO)", lockup.ended_at || "");
                await api(`/dynamics/${id}/chastity/${lockup.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({ started_at: started, ended_at: ended || null }),
                });
                paintChastityLog();
              },
            }, "Edit"));
          }
          list.appendChild(card);
        });
        historyReportShell(id, report.title, [
          buildDaysPicker(days, (v) => { days = v; paintChastityLog(); }),
          list,
          el("button", {
            className: "link-btn",
            type: "button",
            onClick: () => navigate(`/dynamic/${id}/chastity`),
          }, "Chastity tracking →"),
        ]);
      })
      .catch((err) => historyReportShell(id, report.title, el("p", { className: "error" }, err.message)));
  }

  setViewContent(el("p", { className: "muted" }, "Loading report..."));
  if (reportId === "weekly") paintWeekly();
  else if (reportId === "chastity-days") paintChastityDays();
  else if (reportId === "orgasms") paintOrgasms();
  else if (reportId === "chastity-stats") paintChastityStats();
  else if (reportId === "sessions") paintSessions();
  else if (reportId === "org-log") paintOrgLog();
  else if (reportId === "chastity-log") paintChastityLog();
  else navigate(`/dynamic/${id}/history`);
}

function renderHistorySession(dynamicId, sessionId) {
  const id = dynamicId || getActiveDynamicId();
  if (!id) {
    renderHome();
    return;
  }
  state.activeDynamicId = id;
  setViewContent(el("p", { className: "muted" }, "Loading session..."));
  api(`/dynamics/${id}/history/reports/sessions?days=365`)
    .then((data) => {
      const session = data.sessions.find((s) => s.session_id === sessionId);
      if (!session) {
        setViewContent(el("p", { className: "error" }, "Session not found."));
        return;
      }
      const nodes = [
        el("p", { className: "muted" }, `${formatLocalDateTime(session.started_at)} – ${formatLocalDateTime(session.ended_at)}`),
        el("p", {}, `${session.entry_count} linked entries · ${session.orgasm_count} orgasms`),
      ];
      if (session.during_lockup) {
        nodes.push(el("p", { className: "muted" }, `During lockup: ${(session.locked_partner_names || []).join(", ") || "yes"}`));
      }
      const list = el("div", { className: "stack" });
      session.entries.forEach((entry) => list.appendChild(renderTrackingEntrySummary(entry, { dynamicId: id })));
      nodes.push(list);
      historyReportShell(id, "Linked session", nodes, {
        onBack: () => navigate(`/dynamic/${id}/history/sessions`),
      });
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderDashboard(dynamicId) {
  renderHistoryHub(dynamicId);
}


function renderHome() {
  const stack = el("div", { className: "stack" }, [
    el("h1", {}, `Hi, ${state.user?.username || "there"}`),
    el("p", { className: "muted" }, "Create a dynamic or join your partner with an invite code."),
  ]);

  const createCard = el("div", { className: "card stack" }, [
    el("h2", {}, "Start a dynamic"),
    el("label", {}, ["Name", el("input", { id: "dynamic-name", placeholder: "Leave blank — becomes Dom & Sub names", value: "" })]),
    el("label", {}, [
      "Your role",
      el(
        "select",
        { id: "create-role" },
        [
          el("option", { value: "dominant" }, "Dominant"),
          el("option", { value: "submissive" }, "Submissive"),
        ]
      ),
    ]),
    el("button", {
      className: "primary-btn",
      onClick: async () => {
        const dynamic = await api("/dynamics", {
          method: "POST",
          body: JSON.stringify({
            name: document.getElementById("dynamic-name").value.trim() || "Our dynamic",
            role: document.getElementById("create-role").value,
          }),
        });
        state.dynamics = await api("/dynamics");
        navigate(`/dynamic/${dynamic.id}`);
      },
    }, "Create"),
  ]);

  const joinCard = el("div", { className: "card stack" }, [
    el("h2", {}, "Join a dynamic"),
    el("label", {}, ["Invite code", el("input", { id: "invite-code", placeholder: "ABC12345" })]),
    el("label", {}, [
      "Your role",
      el(
        "select",
        { id: "join-role" },
        [
          el("option", { value: "submissive" }, "Submissive"),
          el("option", { value: "dominant" }, "Dominant"),
        ]
      ),
    ]),
    el("button", {
      className: "primary-btn",
      onClick: async () => {
        const dynamic = await api("/dynamics/join", {
          method: "POST",
          body: JSON.stringify({
            invite_code: document.getElementById("invite-code").value,
            role: document.getElementById("join-role").value,
          }),
        });
        state.dynamics = await api("/dynamics");
        navigate(`/dynamic/${dynamic.id}`);
      },
    }, "Join"),
  ]);

  stack.appendChild(createCard);
  stack.appendChild(joinCard);

  viewEl.replaceChildren(stack);
  updateBottomNav();
}

function formatDurationMs(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return "0 minutes";
  const totalMin = Math.round(ms / 60000);
  const days = Math.floor(totalMin / (60 * 24));
  const hours = Math.floor((totalMin % (60 * 24)) / 60);
  const mins = totalMin % 60;
  const parts = [];
  if (days) parts.push(`${days} day${days === 1 ? "" : "s"}`);
  if (hours) parts.push(`${hours} hour${hours === 1 ? "" : "s"}`);
  if (mins && days === 0) parts.push(`${mins} minute${mins === 1 ? "" : "s"}`);
  if (!parts.length) parts.push("under a minute");
  return parts.join(" ");
}

function formatPeriodMd(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "??/??";
  return `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}`;
}

function periodDayCount(startAt, endAt) {
  const start = new Date(startAt).getTime();
  const end = new Date(endAt).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return 1;
  return Math.max(1, Math.ceil((end - start) / 86400000));
}

const CHASTITY_TERM_UNLOCK_SPLIT_MS = 18 * 60 * 60 * 1000;

function unlockedDurationMs(ev) {
  if (ev.kind !== "temp_unlock") return 0;
  const start = new Date(ev.startValue || ev.at).getTime();
  const end = new Date(ev.endValue || ev.endAt || Date.now()).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 0;
  return end - start;
}

function chastityEndTitle(lockup) {
  const kind = lockup?.ended_kind || "";
  if (kind === "released_orgasm" || kind === "released_timer") return "Released!";
  if (kind === "historical") return "Unlocked";
  return "Unlocked";
}

function buildChastityTimelineEvents(lockups) {
  const events = [];
  (lockups || []).forEach((lockup) => {
    events.push({
      id: "lock-" + lockup.id,
      kind: "lockup",
      lockupId: lockup.id,
      at: lockup.started_at,
      endAt: lockup.started_at,
      startValue: lockup.started_at,
      endValue: lockup.ended_at || "",
      title: "Locked up",
      detail: lockup.device_notes || (lockup.record_type === "historical" ? "Historical lockup" : ""),
      tags: lockup.tags || [],
      noteKey: "device_notes",
      endedKind: lockup.ended_kind || "",
    });
    (lockup.breaks || []).forEach((brk) => {
      const endOk = !brk.ended_at || new Date(brk.ended_at) > new Date(brk.started_at);
      if (!endOk) return;
      const unlockedMs = brk.ended_at
        ? new Date(brk.ended_at) - new Date(brk.started_at)
        : Date.now() - new Date(brk.started_at);
      events.push({
        id: "break-" + brk.id,
        kind: "temp_unlock",
        lockupId: lockup.id,
        breakId: brk.id,
        at: brk.started_at,
        endAt: brk.ended_at || new Date().toISOString(),
        startValue: brk.started_at,
        endValue: brk.ended_at || "",
        title: brk.break_reason || "Temporary unlock",
        detail: brk.note || "",
        tags: brk.tags || [],
        unlockedLabel: formatDurationMs(unlockedMs) + " unlocked",
        open: !brk.ended_at,
        noteKey: "note",
      });
    });
    if (lockup.ended_at) {
      const title = chastityEndTitle(lockup);
      events.push({
        id: "release-" + lockup.id,
        kind: title === "Released!" ? "release" : "unlocked",
        lockupId: lockup.id,
        at: lockup.ended_at,
        endAt: lockup.ended_at,
        startValue: lockup.started_at,
        endValue: lockup.ended_at,
        title,
        detail: lockup.release_notes || "",
        tags: lockup.tags || [],
        noteKey: "release_notes",
        endedKind: lockup.ended_kind || "",
      });
    }
  });
  return events.sort((a, b) => new Date(b.at) - new Date(a.at));
}

/** Split timeline into terms: after Released!, or after unlocks longer than 18h. */
function buildChastityTerms(lockups) {
  const chrono = buildChastityTimelineEvents(lockups)
    .slice()
    .sort((a, b) => {
      const dt = new Date(a.at) - new Date(b.at);
      if (dt !== 0) return dt;
      const order = { lockup: 0, temp_unlock: 1, unlocked: 2, release: 3 };
      return (order[a.kind] ?? 9) - (order[b.kind] ?? 9);
    });

  const terms = [];
  let current = [];
  let resumeAfter = null; // ms — next events at/after this belong in a new term

  function flush() {
    if (current.length) terms.push(current);
    current = [];
  }

  chrono.forEach((ev) => {
    const evAt = new Date(ev.at).getTime();

    // New term when locking up after a Released!
    if (ev.kind === "lockup" && current.some((e) => e.kind === "release")) {
      flush();
      resumeAfter = null;
    }

    // New term when locking up after ordinary unlock with >18h gap
    if (ev.kind === "lockup" && current.length) {
      const prevEnd = [...current].reverse().find((e) => e.kind === "unlocked" || e.kind === "release");
      if (prevEnd && prevEnd.kind === "unlocked") {
        const gap = evAt - new Date(prevEnd.at).getTime();
        if (gap > CHASTITY_TERM_UNLOCK_SPLIT_MS) {
          flush();
          resumeAfter = null;
        }
      }
    }

    // New term for events after a long temp unlock ends
    if (resumeAfter != null && evAt >= resumeAfter) {
      const isLongUnlockRow =
        ev.kind === "temp_unlock" && unlockedDurationMs(ev) > CHASTITY_TERM_UNLOCK_SPLIT_MS;
      if (!isLongUnlockRow) {
        flush();
        current.push({
          id: "relock-" + resumeAfter,
          kind: "lockup",
          lockupId: ev.lockupId,
          at: new Date(resumeAfter).toISOString(),
          endAt: new Date(resumeAfter).toISOString(),
          startValue: new Date(resumeAfter).toISOString(),
          endValue: "",
          title: "Locked up",
          detail: "Locked back up after long unlock",
          tags: [],
          noteKey: "device_notes",
          synthetic: true,
        });
        resumeAfter = null;
      }
    }

    current.push(ev);

    if (ev.kind === "temp_unlock" && unlockedDurationMs(ev) > CHASTITY_TERM_UNLOCK_SPLIT_MS) {
      const end = new Date(ev.endValue || ev.endAt).getTime();
      if (Number.isFinite(end)) resumeAfter = end;
    }
  });
  flush();
  return terms.reverse();
}

function chastityTermLabelFromEvents(events, { isNewest = false } = {}) {
  if (!events.length) return { range: "??/?? - ??/??", daysLabel: "0 days" };
  const firstLock = events.find((e) => e.kind === "lockup") || events[0];
  const releaseEv = events.find((e) => e.kind === "release");
  const last = events[events.length - 1];
  const start = formatPeriodMd(firstLock.at);
  let endPart = "Current";
  let endAt = new Date().toISOString();

  if (releaseEv) {
    endPart = formatPeriodMd(releaseEv.at);
    endAt = releaseEv.at;
  } else if (
    last.kind === "temp_unlock" &&
    unlockedDurationMs(last) > CHASTITY_TERM_UNLOCK_SPLIT_MS
  ) {
    // Term closed when the long unlock began
    endPart = formatPeriodMd(last.at);
    endAt = last.at;
  } else if (!isNewest) {
    const endEv =
      [...events].reverse().find((e) => e.kind === "unlocked" || e.kind === "release") || last;
    endPart = formatPeriodMd(endEv.endValue || endEv.endAt || endEv.at);
    endAt = endEv.endValue || endEv.endAt || endEv.at;
  }

  const days = periodDayCount(firstLock.at, endAt);
  return {
    range: `${start} - ${endPart}`,
    daysLabel: `${days} day${days === 1 ? "" : "s"}`,
  };
}

function renderChastityTimeline(lockups, partnerName, opts = {}) {
  const {
    dynamicId,
    canEdit = false,
    subCanDeleteBreaks = true,
    youAreDominant = false,
    tagPresets = [],
    onSaved = null,
  } = opts;
  const periods = buildChastityTerms(lockups);
  const body = el("div", { className: "chastity-timeline hidden" });
  const toggle = el("button", {
    type: "button",
    className: "ghost-btn chastity-timeline-toggle",
  }, "Show timeline");
  const editHost = el("div", { className: "chastity-timeline-edit-host" });

  function closeEdit() {
    editHost.replaceChildren();
  }

  function openEdit(event) {
    let startLabel = "Lockup started";
    let endLabel = "Ended at";
    if (event.kind === "temp_unlock") {
      startLabel = "unlocked @";
      endLabel = "locked back up @";
    } else if (event.kind === "lockup") {
      startLabel = "Locked up @";
      endLabel = "Ended @";
    } else if (event.kind === "release" || event.kind === "unlocked") {
      startLabel = "Locked up @";
      endLabel = event.title === "Released!" ? "Released! @" : "Unlocked @";
    }
    const startTime = buildTimeSelector({
      label: startLabel,
      defaultValue: event.startValue ? toLocalDatetimeValue(event.startValue) : toLocalDatetimeValue(),
      shortcuts: false,
    });
    const endTime = buildTimeSelector({
      label: endLabel,
      defaultValue: event.endValue ? toLocalDatetimeValue(event.endValue) : "",
      shortcuts: false,
    });
    if (!event.endValue) endTime.input.value = "";
    const notes = el("textarea", {
      rows: "3",
      placeholder: "Notes",
    });
    notes.value = event.detail || "";
    const tagPicker = buildTagPicker(tagPresets, event.tags || []);
    const flowError = el("p", { className: "error hidden" });
    const notesDetails = el("details", { className: "chastity-edit-notes" }, [
      el("summary", {}, event.detail ? "Notes (tap to edit)" : "Notes (rarely used)"),
      el("label", { className: "stack" }, [notes]),
    ]);
    if (event.detail) notesDetails.open = true;

    const canDeleteEntry =
      event.kind !== "temp_unlock" || youAreDominant || subCanDeleteBreaks;

    const actions = el("div", { className: "row chastity-timeline-edit-actions" }, [
      el("button", {
        type: "button",
        className: "primary-btn",
        onClick: async () => {
          flowError.classList.add("hidden");
          const startIso = startTime.getIso();
          const endIso = endTime.input.value ? endTime.getIso() : null;
          if (!startIso) {
            flowError.textContent = "Start time is required.";
            flowError.classList.remove("hidden");
            return;
          }
          if (endIso && new Date(endIso) <= new Date(startIso)) {
            flowError.textContent = "End must be after start.";
            flowError.classList.remove("hidden");
            return;
          }
          try {
            if (event.kind === "temp_unlock") {
              await api("/dynamics/" + dynamicId + "/chastity/" + event.lockupId + "/break/" + event.breakId, {
                method: "PATCH",
                body: JSON.stringify({
                  started_at: startIso,
                  ended_at: endIso,
                  clear_ended_at: !endIso,
                  note: notes.value.trim(),
                  tags: tagPicker.getTags(),
                }),
              });
            } else {
              const body = {
                started_at: startIso,
                tags: tagPicker.getTags(),
              };
              if (event.kind === "lockup") {
                body.device_notes = notes.value.trim();
                if (endIso) {
                  body.ended_at = endIso;
                  if (!event.endedKind) body.ended_kind = "unlocked";
                } else {
                  body.clear_ended_at = true;
                }
              } else {
                body.release_notes = notes.value.trim();
                body.ended_at = endIso || startIso;
                if (event.endedKind) body.ended_kind = event.endedKind;
              }
              await api("/dynamics/" + dynamicId + "/chastity/" + event.lockupId, {
                method: "PATCH",
                body: JSON.stringify(body),
              });
            }
            closeEdit();
            if (typeof onSaved === "function") onSaved();
          } catch (err) {
            flowError.textContent = err.message;
            flowError.classList.remove("hidden");
          }
        },
      }, "Save"),
    ]);

    if (canDeleteEntry) {
      actions.appendChild(el("button", {
        type: "button",
        className: "ghost-btn danger-btn",
        onClick: async () => {
          const what = event.kind === "temp_unlock"
            ? "this temporary unlock"
            : "this entire lock period";
          if (!confirm("Delete " + what + "?")) return;
          flowError.classList.add("hidden");
          try {
            if (event.kind === "temp_unlock") {
              await api(
                "/dynamics/" + dynamicId + "/chastity/" + event.lockupId + "/break/" + event.breakId,
                { method: "DELETE" }
              );
            } else {
              await api("/dynamics/" + dynamicId + "/chastity/" + event.lockupId, { method: "DELETE" });
            }
            closeEdit();
            if (typeof onSaved === "function") onSaved();
          } catch (err) {
            flowError.textContent = err.message;
            flowError.classList.remove("hidden");
          }
        },
      }, "Delete"));
    }

    editHost.replaceChildren(
      el("div", { className: "card stack chastity-timeline-edit" }, [
        el("div", { className: "row" }, [
          el("h3", {}, "Edit · " + event.title),
          el("button", {
            type: "button",
            className: "ghost-btn",
            onClick: () => closeEdit(),
          }, "Cancel"),
        ]),
        startTime.wrap,
        endTime.wrap,
        el("label", { className: "stack" }, ["Tags", tagPicker.row, tagPicker.custom]),
        notesDetails,
        flowError,
        actions,
      ])
    );
    editHost.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderPeriodEvents(termEvents) {
    // Terms store oldest→newest; timeline shows newest first
    const events = termEvents.slice().reverse();
    if (!events.length) {
      return el("p", { className: "muted" }, "No events in this period.");
    }
    const list = el("div", { className: "chastity-timeline-list" });
    events.forEach((event, index) => {
      const tagRow = el("div", { className: "tag-filter-row" });
      (event.tags || []).forEach((t) => tagRow.appendChild(el("span", { className: "tag-chip active" }, t)));
      const detail = el("div", { className: "chastity-timeline-detail hidden" }, [
        event.detail ? el("p", {}, event.detail) : el("p", { className: "muted" }, "No notes."),
        (event.tags || []).length ? tagRow : null,
        el("p", { className: "muted" }, formatLocalDateTime(event.at)),
      ]);
      const header = el("div", { className: "chastity-timeline-header" }, [
        el("button", {
          type: "button",
          className: "chastity-timeline-title-btn",
          onClick: () => detail.classList.toggle("hidden"),
        }, event.title),
      ]);
      if (canEdit && dynamicId && !event.synthetic) {
        header.appendChild(
          el("button", {
            type: "button",
            className: "chastity-timeline-edit-btn",
            title: "Edit log",
            onClick: (e) => {
              e.preventDefault();
              e.stopPropagation();
              openEdit(event);
            },
          }, "\u270e")
        );
      }
      list.appendChild(
        el("div", { className: "chastity-timeline-item kind-" + event.kind }, [
          el("button", {
            type: "button",
            className: "chastity-timeline-dot kind-" + event.kind,
            title: event.title,
            onClick: () => detail.classList.toggle("hidden"),
          }),
          el("div", { className: "chastity-timeline-main" }, [
            header,
            event.unlockedLabel
              ? el("p", { className: "chastity-timeline-sub" }, event.unlockedLabel)
              : null,
            el("p", { className: "muted chastity-timeline-when" }, formatLocalDateTime(event.at)),
            detail,
          ]),
        ])
      );

      const older = events[index + 1];
      if (older) {
        const gapMs = new Date(event.at) - new Date(older.endAt || older.at);
        if (gapMs > 60 * 1000) {
          list.appendChild(el("div", { className: "chastity-timeline-gap" }, formatDurationMs(gapMs) + " locked"));
        }
      }
    });
    return list;
  }

  if (!periods.length) {
    body.appendChild(el("p", { className: "muted" }, "No lockup periods yet."));
  } else {
    const periodsHost = el("div", { className: "chastity-timeline-periods" });
    periods.forEach((termEvents, idx) => {
      const label = chastityTermLabelFromEvents(termEvents, { isNewest: idx === 0 });
      const openByDefault =
        idx === 0 ||
        termEvents.some((e) => e.open) ||
        termEvents.some((e) => e.kind === "lockup" && !e.endValue && !e.synthetic);
      periodsHost.appendChild(
        el("details", { className: "chastity-timeline-period", open: openByDefault }, [
          el("summary", { className: "chastity-timeline-period-summary" }, [
            el("span", { className: "chastity-timeline-period-range" }, label.range),
            el("span", { className: "chastity-timeline-period-days" }, label.daysLabel),
          ]),
          renderPeriodEvents(termEvents),
        ])
      );
    });
    body.appendChild(periodsHost);
  }

  let open = false;
  toggle.addEventListener("click", () => {
    open = !open;
    body.classList.toggle("hidden", !open);
    toggle.textContent = open ? "Hide timeline" : "Show timeline";
  });

  return el("div", { className: "card stack chastity-timeline-card" }, [
    el("div", { className: "row" }, [
      el("h2", {}, partnerName + " timeline"),
      toggle,
    ]),
    el("p", { className: "muted" }, "A new expandable term starts after Released! or after more than 18 hours unlocked. Short unlocks stay in the same term."),
    editHost,
    body,
  ]);
}

function renderTrackingEventsCalendar(dynamicId, partners) {
  const rangeState = { value: "month" };
  const typeState = { chastity: true, orgasms: true, feelings: true };
  const userState = new Set((partners || []).map((p) => p.id));

  const host = el("div", { className: "card stack tracking-cal-card" }, [
    el("h2", {}, "Calendar"),
    el("p", { className: "muted" }, "Tap a dot for that day’s event. Month keeps days light; last 7 days shows more per day."),
  ]);
  const filters = el("div", { className: "stack tracking-cal-filters" });
  const gridHost = el("div", { className: "tracking-cal-grid-host" });
  const detailHost = el("div", { className: "tracking-cal-detail muted" }, "Select a day or event.");
  host.appendChild(filters);
  host.appendChild(gridHost);
  host.appendChild(detailHost);

  function selectedTypes() {
    return Object.entries(typeState).filter(([, on]) => on).map(([k]) => k).join(",");
  }

  async function reload() {
    gridHost.replaceChildren(el("p", { className: "muted" }, "Loading…"));
    const users = [...userState].join(",");
    try {
      const data = await api(
        `/dynamics/${dynamicId}/tracking-calendar?range=${rangeState.value}&types=${encodeURIComponent(selectedTypes())}&users=${encodeURIComponent(users)}`
      );
      paint(data);
    } catch (err) {
      gridHost.replaceChildren(el("p", { className: "error" }, err.message));
    }
  }

  function paint(data) {
    const grid = el("div", {
      className: `tracking-cal-grid range-${data.range}`,
    });
    if (data.range === "month") {
      const start = new Date(`${data.start}T12:00:00`);
      const pad = (start.getDay() + 6) % 7; // Monday-first
      for (let i = 0; i < pad; i += 1) {
        grid.appendChild(el("div", { className: "tracking-cal-cell empty" }));
      }
    }
    data.days.forEach((day) => {
      const cell = el("button", {
        type: "button",
        className: `tracking-cal-cell ${day.events.length ? "has-events" : ""}`,
      });
      const dayNum = Number(day.date.slice(-2));
      cell.appendChild(el("span", { className: "tracking-cal-daynum" }, String(dayNum)));
      if (data.range === "7d") {
        cell.appendChild(el("span", { className: "tracking-cal-weekday" }, day.weekday));
      }
      const dots = el("div", { className: "tracking-cal-dots" });
      day.visible_events.forEach((ev) => {
        const dot = el("button", {
          type: "button",
          className: `tracking-cal-dot kind-${ev.kind} group-${ev.type_group}`,
          title: ev.title,
          onClick: (e) => {
            e.stopPropagation();
            showEvent(ev);
          },
        });
        dots.appendChild(dot);
      });
      if (day.overflow > 0) {
        dots.appendChild(el("span", { className: "tracking-cal-overflow" }, `+${day.overflow}`));
      }
      cell.appendChild(dots);
      cell.addEventListener("click", () => showDay(day));
      grid.appendChild(cell);
    });
    gridHost.replaceChildren(grid);
  }

  function showDay(day) {
    if (!day.events.length) {
      detailHost.replaceChildren(el("p", { className: "muted" }, `${day.date}: no events`));
      return;
    }
    const list = el("div", { className: "stack" }, [
      el("strong", {}, day.date),
    ]);
    day.events.forEach((ev) => {
      list.appendChild(
        el("button", {
          type: "button",
          className: "tracking-cal-event-row",
          onClick: () => {
            if (ev.path) navigate(ev.path);
          },
        }, [
          el("span", { className: `tracking-cal-dot kind-${ev.kind}` }),
          el("span", {}, `${ev.title}${ev.detail ? ` — ${ev.detail}` : ""}`),
        ])
      );
    });
    detailHost.replaceChildren(list);
  }

  function showEvent(ev) {
    detailHost.replaceChildren(
      el("div", { className: "stack" }, [
        el("strong", {}, ev.title),
        ev.detail ? el("p", {}, ev.detail) : null,
        el("p", { className: "muted" }, formatLocalDateTime(ev.at)),
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => navigate(ev.path || `/dynamic/${dynamicId}/track`),
        }, "Open"),
      ])
    );
  }

  const rangeRow = el("div", { className: "row wrap" });
  [["month", "This month"], ["7d", "Last 7 days"]].forEach(([value, label]) => {
    rangeRow.appendChild(
      el("button", {
        type: "button",
        className: value === rangeState.value ? "primary-btn" : "ghost-btn",
        onClick: () => {
          rangeState.value = value;
          Array.from(rangeRow.children).forEach((btn) => {
            btn.className = btn.textContent === label ? "primary-btn" : "ghost-btn";
          });
          reload();
        },
      }, label)
    );
  });
  filters.appendChild(el("label", {}, ["Range", rangeRow]));

  const typeRow = el("div", { className: "row wrap tracking-cal-type-row" });
  [
    ["chastity", "Chastity"],
    ["orgasms", "Orgasms"],
    ["feelings", "Feelings"],
  ].forEach(([key, label]) => {
    const box = el("input", { type: "checkbox" });
    box.checked = typeState[key];
    box.addEventListener("change", () => {
      typeState[key] = box.checked;
      reload();
    });
    typeRow.appendChild(el("label", { className: "checkbox-label" }, [box, ` ${label}`]));
  });
  filters.appendChild(el("div", {}, [el("span", { className: "muted" }, "Event types"), typeRow]));

  if ((partners || []).length) {
    const userRow = el("div", { className: "row wrap tracking-cal-type-row" });
    partners.forEach((p) => {
      const box = el("input", { type: "checkbox" });
      box.checked = true;
      box.addEventListener("change", () => {
        if (box.checked) userState.add(p.id);
        else userState.delete(p.id);
        reload();
      });
      userRow.appendChild(el("label", { className: "checkbox-label" }, [box, ` ${p.display_name}`]));
    });
    filters.appendChild(el("div", {}, [el("span", { className: "muted" }, "People"), userRow]));
  }

  reload();
  return host;
}

function renderTrackingHub(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading tracking…"));
  loadDynamic(dynamicId)
    .then(async () => {
      const dynamic = state.currentDynamic;
      let trackingLabel = "";
      let chastityLabel = "";
      let tasksLabel = "";
      let actsLabel = "";
      try {
        const menuSummaries = await api(`/dynamics/${dynamicId}/menu-summaries`);
        trackingLabel = menuSummaries.org_tracking || "";
        chastityLabel = menuSummaries.chastity || "";
        tasksLabel = menuSummaries.tasks || "";
        actsLabel = menuSummaries.acts || "";
      } catch {
        /* ignore */
      }
      const enabledFeatures = dynamic.enabled_features || [];
      const stack = el("div", { className: "stack" }, [
        buildHubHeader(dynamicId, "Tracking", {
          subtitle: "History, lockups, play, feelings, and tasks for this dynamic.",
          sectionFilter: "tracking",
        }),
      ]);
      const list = el("div", { className: "facet-list" });
      TRACKING_FACETS.forEach((facet) => {
        if (!isFacetEnabled(facet, enabledFeatures)) return;
        const rowFacet = { ...facet };
        if (facet.id === "org_tracking" && trackingLabel) rowFacet.subtitle = trackingLabel;
        if (facet.id === "chastity" && chastityLabel) rowFacet.subtitle = chastityLabel;
        if (facet.id === "tasks") {
          const bits = [tasksLabel, actsLabel].filter(Boolean);
          if (bits.length) rowFacet.subtitle = bits.join(" · ");
        }
        list.appendChild(renderFacetRow(rowFacet, dynamicId, dynamic));
      });
      if (!list.childNodes.length) {
        stack.appendChild(
          el("div", { className: "stack" }, [
            el("p", { className: "muted" }, "No tracking features enabled."),
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => navigate(`/dynamic/${dynamicId}/features`),
            }, "Application features"),
          ])
        );
      } else {
        stack.appendChild(list);
      }

      const setupItems = FACET_SECTIONS.flatMap((section) => section.items).filter((facet) =>
        isFacetEnabled(facet, enabledFeatures)
      );
      const setupList = el("div", { className: "facet-list" });
      setupItems.forEach((facet) => setupList.appendChild(renderFacetRow(facet, dynamicId, dynamic)));
      stack.appendChild(
        el("details", { className: "hub-setup-details" }, [
          el("summary", {}, "Setup / Dynamic"),
          setupList,
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: () => navigate(`/dynamic/${dynamicId}/features`),
          }, "Application features"),
        ])
      );
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderTasksActsSwitcher(dynamicId, active) {
  return el("div", { className: "row wrap feelings-when-row" }, [
    el(
      "button",
      {
        type: "button",
        className: active === "tasks" ? "primary-btn" : "ghost-btn",
        onClick: () => navigate(`/dynamic/${dynamicId}/tasks`),
      },
      "Task lists"
    ),
    el(
      "button",
      {
        type: "button",
        className: active === "acts" ? "primary-btn" : "ghost-btn",
        onClick: () => navigate(`/dynamic/${dynamicId}/acts`),
      },
      "Acts of submission"
    ),
  ]);
}

async function loadDynamic(dynamicId) {
  state.activeDynamicId = dynamicId;
  state.currentDynamic = await api(`/dynamics/${dynamicId}`);
  state.interests = await api(`/dynamics/${dynamicId}/interests`);
  state.taskLists = await api(`/dynamics/${dynamicId}/tasks`);
  refreshDomGoalHeader(dynamicId);
}

function renderDynamicOverview(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading dynamic..."));
  loadDynamic(dynamicId)
    .then(async () => {
      const dynamic = state.currentDynamic;
      const you = dynamic.partners.find((p) => p.is_you);
      const partner = dynamic.partners.find((p) => !p.is_you);
      let groundRulesLabel = "Agreements and boundaries";
      try {
        const agreements = await api(`/dynamics/${dynamicId}/agreements`);
        if (agreements.pending_count) {
          groundRulesLabel = `${agreements.approved_count} approved · ${agreements.pending_count} pending`;
        } else if (agreements.approved_count) {
          groundRulesLabel = `${agreements.approved_count} agreement${agreements.approved_count === 1 ? "" : "s"}`;
        } else {
          groundRulesLabel = "No agreements yet";
        }
      } catch {
        /* keep default */
      }

      const stack = el("div", { className: "stack" }, [
        el("h1", {}, formatDynamicTitle(dynamic)),
        el("p", { className: "muted" }, `You are the ${formatRole(you?.role || "dominant")}.`),
      ]);

      if (partner) {
        stack.appendChild(
          el("div", { className: "card stack" }, [
            el("div", { className: "row" }, [
              el("strong", {}, partner.display_name),
              el("span", { className: "pill" }, formatRole(partner.role)),
            ]),
            el("div", { className: "row" }, [
              el("span", {}, "Their interview"),
              el(
                "span",
                { className: `pill ${partner.interview_completed ? "ok" : "pending"}` },
                partner.interview_completed ? "Done" : "Not yet"
              ),
            ]),
          ])
        );
      } else {
        stack.appendChild(
          el("div", { className: "card" }, [
            el("p", {}, "Share this invite code with your partner:"),
            el("h2", {}, dynamic.invite_code),
          ])
        );
      }

      const enabledFeatures = dynamic.enabled_features || [];
      const youPartner = dynamic.partners?.find((p) => p.is_you);
      FACET_SECTIONS.forEach((section) => {
        const visible = section.items.filter((facet) => isFacetEnabled(facet, enabledFeatures));
        if (!visible.length) return;
        const facetList = el("div", { className: "facet-list" });
        visible.forEach((facet) => {
          const rowFacet = { ...facet };
          if (facet.id === "ground_rules") {
            rowFacet.subtitle = groundRulesLabel;
          }
          facetList.appendChild(renderFacetRow(rowFacet, dynamicId, dynamic));
        });

        const storageKey = `ubetra_facet_collapse_${dynamicId}_${section.id}`;
        let collapsed = localStorage.getItem(storageKey) === "1";
        if (section.id === "essentials" && localStorage.getItem(storageKey) == null) {
          // Default collapsed once each essentials item looks filled.
          const interviewDone = !!youPartner?.interview_completed;
          const surveyDone = !!youPartner?.survey_submitted;
          const rulesDone = !/No agreements yet/i.test(groundRulesLabel || "");
          collapsed = interviewDone && surveyDone && rulesDone;
        }
        if (collapsed) facetList.classList.add("hidden");

        const titleBtn = el(
          "button",
          {
            className: "facet-section-title facet-section-toggle",
            type: "button",
            onClick: () => {
              const next = !facetList.classList.contains("hidden");
              facetList.classList.toggle("hidden", next);
              localStorage.setItem(storageKey, next ? "1" : "0");
              titleBtn.textContent = `${section.title}${next ? " ▸" : " ▾"}`;
            },
          },
          `${section.title}${collapsed ? " ▸" : " ▾"}`
        );
        stack.appendChild(el("div", { className: "facet-section" }, [titleBtn, facetList]));
      });
      stack.appendChild(
        el("button", {
          className: "ghost-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}/features`),
        }, "Application features")
      );
      stack.appendChild(
        el("button", {
          className: "ghost-btn",
          onClick: () => navigate("/settings"),
        }, "Switch dynamic")
      );
      setViewContent(stack);
    })
    .catch((err) => {
      setViewContent(el("p", { className: "error" }, err.message));
    });
}

function interestLabel(interest, role) {
  if (role === "submissive" && interest.submissive_display_override) {
    return interest.submissive_display_override;
  }
  return interest.display_copy;
}

function interestCompletionStats(interests, responses) {
  const total = interests?.length || 0;
  if (!total) return { total: 0, answered: 0, percent: 0 };
  const answered = interests.filter((i) => Object.prototype.hasOwnProperty.call(responses, i.id)).length;
  return { total, answered, percent: Math.round((answered / total) * 100) };
}

function categoryCompletionStats(category, responses) {
  return interestCompletionStats(category?.interests || [], responses);
}

function surveyCompletionStats(bundle, responses) {
  const interests = (bundle.categories || []).flatMap((c) => c.interests || []);
  return interestCompletionStats(interests, responses);
}

function createPieChart(percent, { size = 24, title } = {}) {
  const p = Math.max(0, Math.min(100, Number(percent) || 0));
  const ring = Math.max(3, Math.round(size * 0.18));
  const innerSize = size - ring * 2;
  const pie = el("span", {
    className: "pie-chart",
    title: title || `${p}% complete`,
    "aria-hidden": "true",
  });
  pie.style.width = `${size}px`;
  pie.style.height = `${size}px`;
  pie.style.background = `conic-gradient(var(--accent) ${p * 3.6}deg, var(--border) 0deg)`;
  const inner = el("span", { className: "pie-chart-inner" });
  inner.style.width = `${innerSize}px`;
  inner.style.height = `${innerSize}px`;
  pie.appendChild(inner);
  return pie;
}

function updatePieChart(pie, percent, title) {
  const p = Math.max(0, Math.min(100, Number(percent) || 0));
  pie.style.background = `conic-gradient(var(--accent) ${p * 3.6}deg, var(--border) 0deg)`;
  if (title) pie.title = title;
}

async function saveInterestShareIfDominant(dynamicId, role, shareKinksChecked) {
  if (role !== "dominant") return;
  await api(`/dynamics/${dynamicId}/interests/share`, {
    method: "PUT",
    body: JSON.stringify({ share_kinks: !!shareKinksChecked }),
  });
}

function renderSurvey(dynamicId) {
  viewEl.replaceChildren(el("p", { className: "muted" }, "Loading survey..."));
  const { query } = parseRoute();
  const fromOnboarding = query.get("onboarding") === "1";
  loadDynamic(dynamicId)
    .then(async () => {
      const dynamic = state.currentDynamic;
      const you = dynamic.partners.find((p) => p.is_you);
      const isDominant = you?.role === "dominant";
      const bundle = state.interests;
      const localResponses = { ...bundle.your_responses };
      let activeCategory = bundle.categories[0]?.id;
      let sptiReady = you?.spti_completed;
      if (!sptiReady) {
        try {
          const ob = await api("/onboarding/status");
          sptiReady = ob.spti_completed;
        } catch {
          sptiReady = false;
        }
      }

      const shareKinks = el("input", { type: "checkbox" });
      shareKinks.checked = !!bundle.your_share_kinks;

      const titlePie = createPieChart(0, { size: 22 });
      const stack = el("div", { className: "stack" }, [
        el("div", { className: "title-row" }, [
          titlePie,
          el("h1", {}, "Kink list"),
        ]),
        el("p", { className: "muted" }, "Mark what you want, what you'd do for your partner, what you're not into, or leave unanswered."),
        el("button", {
          className: "link-btn",
          type: "button",
          onClick: () => navigate(`/dynamic/${dynamicId}/overlap`),
        }, "Shared kinks →"),
        isDominant
          ? el("div", { className: "card stack" }, [
            el("label", { className: "checkbox-label" }, [
              shareKinks,
              "Share my kink list with my partner",
            ]),
            el("p", { className: "muted" }, "Off by default. Your answers still guide the AI — they stay private from your partner until you opt in."),
          ])
          : null,
        el("div", { className: "interest-key" }, [
          el("span", { className: "key-item want" }, "Want to do"),
          el("span", { className: "key-item if" }, "If they want"),
          el("span", { className: "key-item not" }, "Not interested"),
          el("span", { className: "key-item none" }, "No answer"),
        ]),
      ]);

      const tabs = el("div", { className: "tabs" });
      const list = el("div", { className: "stack" });

      function paintTabs() {
        tabs.replaceChildren(
          ...bundle.categories.map((cat) => {
            const stats = categoryCompletionStats(cat, localResponses);
            return el("button", {
              className: `tab tab-pie ${cat.id === activeCategory ? "active" : ""}`,
              type: "button",
              title: `${stats.answered}/${stats.total} answered`,
              onClick: () => {
                activeCategory = cat.id;
                paintTabs();
                paintInterests();
              },
            }, [
              createPieChart(stats.percent, { size: 20, title: `${stats.percent}%` }),
              el("span", { className: "tab-label" }, cat.name),
            ]);
          })
        );
      }

      function refreshProgress() {
        const overall = surveyCompletionStats(bundle, localResponses);
        updatePieChart(
          titlePie,
          overall.percent,
          `${overall.percent}% complete (${overall.answered}/${overall.total})`
        );
        paintTabs();
      }

      function paintInterests() {
        const category = bundle.categories.find((c) => c.id === activeCategory);
        if (!category) return;
        list.replaceChildren(
          el("p", { className: "muted" }, category.description || ""),
          ...category.interests.map((interest) => {
            const value = localResponses[interest.id];
            const examplesBox = el("p", { className: "muted hidden examples-box" });
            const header = el("div", { className: "row wrap" }, [
              el("strong", {}, interestLabel(interest, you?.role)),
              sptiReady
                ? el("button", {
                  className: "help-btn",
                  type: "button",
                  title: "Get tailored examples",
                  onClick: async () => {
                    examplesBox.textContent = "Loading examples…";
                    examplesBox.classList.remove("hidden");
                    try {
                      const result = await api(`/dynamics/${dynamicId}/interests/${interest.id}/examples`);
                      examplesBox.replaceChildren(
                        ...(result.examples.length
                          ? result.examples.map((ex) => el("p", {}, ex))
                          : [el("p", {}, "No examples returned.")])
                      );
                    } catch (err) {
                      examplesBox.textContent = err.message;
                    }
                  },
                }, "?")
                : null,
            ]);
            const ratingClass = (key) => {
              if (value !== key) return "";
              if (key === "want") return "active-want";
              if (key === "if_partner") return "active-if";
              if (key === "not_into") return "active-not";
              return "active-none";
            };
            const item = el("div", { className: "card interest-item" }, [
              header,
              interest.description ? el("p", { className: "muted" }, interest.description) : null,
              examplesBox,
              el("div", { className: "interest-actions interest-rating" }, [
                ["want", "Want"],
                ["if_partner", "If they want"],
                ["not_into", "Not into"],
                ["no_answer", "No answer"],
              ].map(([key, label]) =>
                el("button", {
                  className: `rating-box ${ratingClass(key)}`,
                  type: "button",
                  onClick: () => {
                    if (value === key) delete localResponses[interest.id];
                    else localResponses[interest.id] = key;
                    paintInterests();
                    refreshProgress();
                  },
                }, label)
              )),
            ]);
            return item;
          })
        );
      }

      refreshProgress();
      paintInterests();

      const error = el("div", { className: "error hidden" });
      const bottom = el("div", { className: "bottom-bar stack" }, [
        error,
        el("button", {
          className: "ghost-btn",
          onClick: async () => {
            try {
              await api(`/dynamics/${dynamicId}/interests`, {
                method: "PUT",
                body: JSON.stringify({ responses: localResponses }),
              });
              await saveInterestShareIfDominant(dynamicId, you?.role, shareKinks.checked);
              navigate(`/dynamic/${dynamicId}`);
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Save draft"),
        el("button", {
          className: "primary-btn",
          onClick: async () => {
            try {
              await api(`/dynamics/${dynamicId}/interests`, {
                method: "PUT",
                body: JSON.stringify({ responses: localResponses }),
              });
              await saveInterestShareIfDominant(dynamicId, you?.role, shareKinks.checked);
              await api(`/dynamics/${dynamicId}/interests/submit`, { method: "POST" });
              if (fromOnboarding) {
                renderOnboarding();
              } else if (isDominant && shareKinks.checked) {
                navigate(`/dynamic/${dynamicId}/overlap`);
              } else {
                navigate(`/dynamic/${dynamicId}`);
              }
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Submit survey"),
      ]);

      stack.appendChild(tabs);
      stack.appendChild(list);
      stack.appendChild(bottom);
      viewEl.replaceChildren(stack);
    })
    .catch((err) => {
      viewEl.replaceChildren(el("p", { className: "error" }, err.message));
    });
}

function renderOverlap(dynamicId) {
  viewEl.replaceChildren(el("p", { className: "muted" }, "Loading overlap..."));
  Promise.all([
    loadDynamic(dynamicId),
    api(`/dynamics/${dynamicId}/interests`),
  ])
    .then(([, bundle]) => {
      state.interests = bundle;
      const you = state.currentDynamic?.partners?.find((p) => p.is_you);
      const isDominant = you?.role === "dominant";
      const shareKinks = el("input", { type: "checkbox" });
      shareKinks.checked = !!bundle.your_share_kinks;
      const status = el("p", { className: "muted" });
      const error = el("div", { className: "error hidden" });

      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Shared kinks"),
        el("p", { className: "muted" }, "Overlap is optional. By default, kink lists stay private and only feed the AI."),
        el("button", {
          className: "link-btn",
          type: "button",
          onClick: () => navigate(`/dynamic/${dynamicId}/survey`),
        }, "← Back to kink list"),
      ]);

      if (isDominant) {
        stack.appendChild(el("div", { className: "card stack" }, [
          el("label", { className: "checkbox-label" }, [
            shareKinks,
            "Share my kink list with my partner",
          ]),
          el("button", {
            className: "primary-btn",
            type: "button",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                const updated = await api(`/dynamics/${dynamicId}/interests/share`, {
                  method: "PUT",
                  body: JSON.stringify({ share_kinks: shareKinks.checked }),
                });
                state.interests = updated;
                status.textContent = updated.your_share_kinks
                  ? "Sharing on — overlap appears once both partners submit their kink lists."
                  : "Sharing off — lists stay private to the AI.";
                renderOverlap(dynamicId);
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Save sharing preference"),
          status,
          error,
        ]));
      } else {
        stack.appendChild(el("div", { className: "card" }, [
          el("p", {}, "Your dominant decides whether kink lists are shared. Your answers stay private to the AI."),
        ]));
      }

      if (!isDominant) {
        if (!bundle.sharing_enabled) {
          stack.appendChild(el("div", { className: "card" }, "Your dominant has not enabled shared kinks yet. Your answers stay private to the AI."));
        } else if (!bundle.your_submission.submitted) {
          stack.appendChild(el("div", { className: "card" }, "Submit your kink list to see overlap."));
        } else if (!bundle.partner_submission.submitted) {
          stack.appendChild(el("div", { className: "card" }, "Your dominant has not submitted their kink list yet."));
        } else if (!bundle.overlap_details.length) {
          stack.appendChild(el("div", { className: "card" }, "No shared matches yet."));
        } else {
          stack.appendChild(el("p", { className: "muted" }, "Matches where both of you marked Want or If partner wants."));
          bundle.overlap_details.forEach((item) => {
            stack.appendChild(
              el("div", { className: "card" }, [
                el("strong", {}, item.display_copy),
                item.description ? el("p", { className: "muted" }, item.description) : null,
              ])
            );
          });
        }
      } else if (!bundle.your_share_kinks) {
        stack.appendChild(el("div", { className: "card" }, "Sharing is off. Turn it on above to compare kink lists with your partner."));
      } else if (!bundle.partner_submission.submitted) {
        stack.appendChild(el("div", { className: "card" }, "Your partner has not submitted their kink list yet."));
      } else if (!bundle.your_submission.submitted) {
        stack.appendChild(el("div", { className: "card" }, "Submit your survey to see overlap."));
      } else if (!bundle.overlap_details.length) {
        stack.appendChild(el("div", { className: "card" }, "No shared matches yet. Try updating your surveys."));
      } else {
        stack.appendChild(el("p", { className: "muted" }, "Matches where both of you marked Want or If partner wants."));
        bundle.overlap_details.forEach((item) => {
          stack.appendChild(
            el("div", { className: "card" }, [
              el("strong", {}, item.display_copy),
              item.description ? el("p", { className: "muted" }, item.description) : null,
            ])
          );
        });
      }

      viewEl.replaceChildren(stack);
    })
    .catch((err) => viewEl.replaceChildren(el("p", { className: "error" }, err.message)));
}

function renderTasks(dynamicId) {
  viewEl.replaceChildren(el("p", { className: "muted" }, "Loading tasks..."));
  Promise.all([
    loadDynamic(dynamicId),
    api(`/dynamics/${dynamicId}/tasks/calendar`),
    api(`/dynamics/${dynamicId}/tags`).catch(() => ({ presets: [] })),
    api("/google/status").catch(() => ({ configured: false, connected: false })),
  ])
    .then(([, calendar, tagData, googleStatus]) => {
      const dynamic = state.currentDynamic;
      const you = dynamic.partners.find((p) => p.is_you);
      const error = el("div", { className: "error hidden" });
      const syncStatus = el("p", { className: "muted" });
      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Tasks & acts"),
        renderTasksActsSwitcher(dynamicId, "tasks"),
        el("p", { className: "muted" }, "Track overdue and open work. Create and assign new tasks from Playtime."),
        error,
      ]);

      const googleCard = el("div", { className: "card stack" }, [
        el("h2", {}, "Google Tasks"),
        el("p", { className: "muted" }, "Sync approved tasks to vanilla Google Tasks using G-rated code words. Completing a Google task marks it done here."),
      ]);
      if (!googleStatus.configured) {
        googleCard.appendChild(el("p", { className: "muted" }, "Add UBETRA_GOOGLE_CLIENT_ID and UBETRA_GOOGLE_CLIENT_SECRET in .env to enable."));
      } else if (!googleStatus.connected) {
        googleCard.appendChild(el("p", { className: "muted" }, "Connect Google in Settings (submissive account recommended)."));
        googleCard.appendChild(el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => navigate("/settings"),
        }, "Open Settings"));
      } else {
        googleCard.appendChild(el("p", { className: "muted" }, `Connected · list ${googleStatus.list_id || "@default"}`));
        googleCard.appendChild(el("button", {
          className: "primary-btn",
          type: "button",
          onClick: async () => {
            error.classList.add("hidden");
            syncStatus.textContent = "Syncing…";
            try {
              const result = await api(`/google/dynamics/${dynamicId}/sync`, { method: "POST" });
              syncStatus.textContent = `Pushed ${result.pushed}, completed from Google ${result.completed_from_google}.`;
              if (result.errors?.length) {
                error.textContent = result.errors.join(" ");
                error.classList.remove("hidden");
              }
              if (result.completed_from_google || result.pushed) renderTasks(dynamicId);
            } catch (err) {
              syncStatus.textContent = "";
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Sync with Google Tasks"));
        googleCard.appendChild(syncStatus);
      }
      stack.appendChild(googleCard);

      const calCard = el("div", { className: "card stack" }, [el("h2", {}, "Task calendar (repeating)")]);
      if (!calendar.items.length) {
        calCard.appendChild(el("p", { className: "muted" }, "No scheduled or repeating tasks yet."));
      } else {
        const cal = el("div", { className: "task-calendar" });
        calendar.items.slice(0, 40).forEach((item) => {
          const row = el("div", { className: "task-cal-row" }, [
            el("span", { className: "task-cal-date" }, new Date(item.due_at).toLocaleDateString()),
            el("span", { className: "task-cal-body" }, item.content),
            el("span", { className: "pill" }, item.recurrence !== "none" ? item.recurrence : "once"),
          ]);
          if (item.tags?.length) {
            const tags = el("div", { className: "tag-filter-row" });
            item.tags.forEach((t) => tags.appendChild(el("span", { className: "tag-chip active" }, t)));
            row.appendChild(tags);
          }
          if (item.approval_status === "pending") {
            row.appendChild(el("span", { className: "pill pending" }, "pending approval"));
          }
          cal.appendChild(row);
        });
        calCard.appendChild(cal);
      }
      stack.appendChild(calCard);

      stack.appendChild(el("div", { className: "card stack" }, [
        el("h2", {}, "Create tasks in Playtime"),
        el("p", { className: "muted" }, "Task creation lives under Playtime. This screen is for tracking overdue, pending, and completed work."),
        el("button", {
          className: "primary-btn",
          type: "button",
          onClick: () => navigate(`/dynamic/${dynamicId}/assistant`),
        }, "Open Playtime"),
      ]));

      const now = Date.now();
      const missed = [];
      const pending = [];
      const open = [];
      (state.taskLists || []).forEach((list) => {
        (list.tasks || []).forEach((task) => {
          const row = { list, task };
          if (task.approval_status === "pending") pending.push(row);
          else if (!task.completed_at && task.due_at && new Date(task.due_at).getTime() < now) missed.push(row);
          else if (!task.completed_at) open.push(row);
        });
      });

      function paintTaskBucket(title, rows, emptyText) {
        const card = el("div", { className: "card stack" }, [el("h2", {}, title)]);
        if (!rows.length) {
          card.appendChild(el("p", { className: "muted" }, emptyText));
          return card;
        }
        rows.slice(0, 30).forEach(({ list, task }) => {
          const meta = [];
          if (task.approval_status === "pending") meta.push("pending");
          if (task.due_at) meta.push(formatTaskDue(task) || new Date(task.due_at).toLocaleString());
          if (task.assigned_to_display_name) meta.push(`for ${task.assigned_to_display_name}`);
          const row = el("div", { className: "task-item" }, [
            el("p", {}, task.content),
            meta.length ? el("p", { className: "muted" }, `${list.title} · ${meta.join(" · ")}`) : el("p", { className: "muted" }, list.title),
          ]);
          const actions = el("div", { className: "row" });
          if (canCompleteTask(task, you)) {
            actions.appendChild(el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                await api(`/tasks/${list.id}/items/${task.id}/complete`, { method: "PATCH" });
                renderTasks(dynamicId);
              },
            }, "Mark complete"));
          }
          if (you?.role === "dominant" && task.approval_status === "pending") {
            actions.appendChild(el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                await api(`/tasks/${list.id}/items/${task.id}/approval?approved=true`, { method: "PATCH" });
                renderTasks(dynamicId);
              },
            }, "Approve"));
          }
          if (actions.childNodes.length) row.appendChild(actions);
          card.appendChild(row);
        });
        return card;
      }

      stack.appendChild(paintTaskBucket("Missed / overdue", missed, "No overdue tasks."));
      stack.appendChild(paintTaskBucket("Pending approval", pending, "Nothing waiting on approval."));
      stack.appendChild(paintTaskBucket("Open tasks", open, "No open tasks."));

      if (!state.taskLists.length) {
        stack.appendChild(el("div", { className: "card" }, "No task lists yet — create one in Playtime."));
      } else {
        state.taskLists.forEach((list) => {
          const card = el("div", { className: "card stack" }, [
            el("div", { className: "row" }, [
              el("h2", {}, list.title),
              el("span", { className: "pill" }, list.status),
            ]),
          ]);
          list.tasks.forEach((task) => {
            const meta = [];
            if (task.source) meta.push(task.source);
            if (task.recurrence && task.recurrence !== "none") meta.push(task.recurrence);
            if (task.approval_status === "pending") meta.push("pending");
            if (task.is_private) meta.push("private");
            if (task.assigned_to_display_name) meta.push(`for ${task.assigned_to_display_name}`);
            const dueLabel = formatTaskDue(task);
            if (dueLabel) meta.push(dueLabel);
            const row = el("div", { className: `task-item ${task.completed_at ? "done" : ""}` }, [
              el("p", {}, `${task.position + 1}. ${task.content}`),
              task.public_code_word
                ? el("p", { className: "muted" }, `Google code word: ${task.public_code_word}${task.google_synced ? " · synced" : ""}`)
                : null,
              meta.length ? el("p", { className: "muted" }, meta.join(" · ")) : null,
            ]);
            if (task.tags?.length) {
              const tags = el("div", { className: "tag-filter-row" });
              task.tags.forEach((t) => tags.appendChild(el("span", { className: "tag-chip active" }, t)));
              row.appendChild(tags);
            }
            const actions = el("div", { className: "row" });
            if (canCompleteTask(task, you)) {
              actions.appendChild(
                el("button", {
                  className: "primary-btn",
                  onClick: async () => {
                    await api(`/tasks/${list.id}/items/${task.id}/complete`, { method: "PATCH" });
                    renderTasks(dynamicId);
                  },
                }, "Mark complete")
              );
            }
            if (you?.role === "dominant" && task.approval_status === "pending") {
              actions.appendChild(
                el("button", {
                  className: "primary-btn",
                  onClick: async () => {
                    await api(`/tasks/${list.id}/items/${task.id}/approval?approved=true`, { method: "PATCH" });
                    renderTasks(dynamicId);
                  },
                }, "Approve")
              );
              actions.appendChild(
                el("button", {
                  className: "ghost-btn",
                  onClick: async () => {
                    await api(`/tasks/${list.id}/items/${task.id}/approval?approved=false`, { method: "PATCH" });
                    renderTasks(dynamicId);
                  },
                }, "Reject")
              );
            }
            if (you?.role === "dominant" || (task.is_private && you)) {
              actions.appendChild(
                el("button", {
                  className: "ghost-btn",
                  onClick: async () => {
                    if (!confirm("Remove this task?")) return;
                    await api(`/tasks/${list.id}/items/${task.id}`, { method: "DELETE" });
                    renderTasks(dynamicId);
                  },
                }, "Remove")
              );
            }
            if (actions.childNodes.length) row.appendChild(actions);
            card.appendChild(row);
          });
          stack.appendChild(card);
        });
      }

      stack.appendChild(
        el("button", {
          className: "ghost-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}/track`),
        }, "Back to tracking")
      );
      viewEl.replaceChildren(stack);
      updateBottomNav();
    })
    .catch((err) => viewEl.replaceChildren(el("p", { className: "error" }, err.message)));
}

function knowledgeFields() {
  return [
    ["relationship_context", "Relationship context", "How would you describe your dynamic right now?"],
    ["distance", "Distance & logistics", "Schedules, travel, privacy constraints..."],
    ["space", "Play space", "Bedroom, hotel, shared home, dungeon setup..."],
    ["budget", "Budget & resources", "Toys, outfits, time, money..."],
    ["about_you", "About you", "Background, experience level, what you need from a partner..."],
    ["desires", "Desires & fantasies", "What you want more of, what you're curious to explore..."],
  ];
}

function renderKnowledgeHub(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading…"));
  Promise.all([
    api(`/dynamics/${dynamicId}/core-knowledge/me`),
    api(`/dynamics/${dynamicId}/spti/me`),
    loadDynamic(dynamicId),
  ])
    .then(([knowledge, spti]) => {
      const sptiLabel = spti.completed
        ? "Results saved"
        : spti.skipped
          ? "Skipped — add anytime"
          : "Not completed yet";
      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Knowledge & profile"),
        el("p", { className: "muted" }, "Private context for the assistant. Your partner never sees these answers."),
      ]);
      stack.appendChild(
        el("button", {
          className: "facet-row",
          type: "button",
          onClick: () => navigate(`/dynamic/${dynamicId}/knowledge/core`),
        }, [
          el("span", { className: "facet-icon" }, "🧠"),
          el("span", { className: "facet-copy" }, [
            el("span", { className: "facet-title" }, "Core knowledge"),
            el("span", { className: "facet-subtitle" }, "Relationship, logistics, desires"),
          ]),
          el("span", { className: "facet-chevron" }, el("span", {
            className: `pill ${knowledge.submitted ? "ok" : "pending"}`,
          }, knowledge.submitted ? "Submitted" : "Draft")),
        ])
      );
      stack.appendChild(
        el("button", {
          className: "facet-row",
          type: "button",
          onClick: () => navigate(`/dynamic/${dynamicId}/knowledge/spti`),
        }, [
          el("span", { className: "facet-icon" }, "🧬"),
          el("span", { className: "facet-copy" }, [
            el("span", { className: "facet-title" }, "SPTI profile"),
            el("span", { className: "facet-subtitle" }, "Sexual Personality Type Inventory"),
          ]),
          el("span", { className: "facet-chevron" }, el("span", {
            className: `pill ${spti.completed ? "ok" : "pending"}`,
          }, sptiLabel)),
        ])
      );
      const enabledFeatures = state.currentDynamic?.enabled_features || [];
      if (isFacetEnabled({ id: "context_library" }, enabledFeatures)) {
        stack.appendChild(
          el("button", {
            className: "facet-row",
            type: "button",
            onClick: () => navigate(`/dynamic/${dynamicId}/context`),
          }, [
            el("span", { className: "facet-icon" }, "📎"),
            el("span", { className: "facet-copy" }, [
              el("span", { className: "facet-title" }, "Context library"),
              el("span", { className: "facet-subtitle" }, "Stories, scenes, and files for AI"),
            ]),
            el("span", { className: "facet-chevron" }, "›"),
          ])
        );
      }
      if (isFacetEnabled({ id: "gear" }, enabledFeatures)) {
        stack.appendChild(
          el("button", {
            className: "facet-row",
            type: "button",
            onClick: () => navigate(`/dynamic/${dynamicId}/gear`),
          }, [
            el("span", { className: "facet-icon" }, "🧰"),
            el("span", { className: "facet-copy" }, [
              el("span", { className: "facet-title" }, "Gear"),
              el("span", { className: "facet-subtitle" }, "Vanilla toys, kinky stuff, outfits"),
            ]),
            el("span", { className: "facet-chevron" }, "›"),
          ])
        );
      }
      stack.appendChild(
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => navigate(`/dynamic/${dynamicId}`),
        }, "Back to dynamic")
      );
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderSptiProfile(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading SPTI…"));
  api(`/dynamics/${dynamicId}/spti/me`)
    .then((spti) => {
      const error = el("div", { className: "error hidden" });
      const status = el("p", { className: "muted" });
      const results = el("textarea", {
        rows: 10,
        placeholder: "Paste your SPTI results from spti-test.com…",
      });
      results.value = spti.skipped ? "" : (spti.results || "");

      function refreshStatus() {
        if (spti.completed) {
          status.textContent = spti.completed_at
            ? `Saved ${new Date(spti.completed_at).toLocaleString()}`
            : "Results saved";
        } else if (spti.skipped) {
          status.textContent = "You skipped SPTI earlier. Paste results when ready.";
        } else {
          status.textContent = "Not saved yet";
        }
      }
      refreshStatus();

      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "SPTI profile"),
        el("p", { className: "muted" }, "Results are private — only you and the AI see them. They help tailor scene ideas, kink examples, and tone. Your partner only sees whether you've completed SPTI."),
        status,
        el("a", {
          className: "primary-btn inline-link",
          href: "https://spti-test.com/",
          target: "_blank",
          rel: "noopener noreferrer",
        }, "Take the test at spti-test.com"),
        el("label", {}, ["Paste results", results]),
        error,
        el("div", { className: "row wrap" }, [
          el("button", {
            className: "primary-btn",
            type: "button",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                const updated = await api(`/dynamics/${dynamicId}/spti/me`, {
                  method: "PUT",
                  body: JSON.stringify({ results: results.value, skipped: false }),
                });
                Object.assign(spti, updated);
                refreshStatus();
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Save results"),
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: async () => {
              if (!confirm("Mark SPTI as skipped? You can add results later.")) return;
              error.classList.add("hidden");
              try {
                const updated = await api(`/dynamics/${dynamicId}/spti/me`, {
                  method: "PUT",
                  body: JSON.stringify({ skipped: true }),
                });
                Object.assign(spti, updated);
                results.value = "";
                refreshStatus();
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Clear / skip for now"),
        ]),
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => navigate(`/dynamic/${dynamicId}/knowledge`),
        }, "Back to knowledge"),
      ]);
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderCoreKnowledge(dynamicId) {
  viewEl.replaceChildren(el("p", { className: "muted" }, "Loading core knowledge..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/core-knowledge/me`),
    loadDynamic(dynamicId),
  ])
    .then(([knowledge]) => {
      const inputs = {};
      const error = el("div", { className: "error hidden" });
      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Core knowledge"),
        el("p", { className: "muted" }, "Private — only you and the AI see your answers. Your partner never sees your core knowledge."),
        el("span", { className: `pill ${knowledge.submitted ? "ok" : "pending"}` }, knowledge.submitted ? "Submitted" : "Draft"),
      ]);

      const populateStatus = el("p", { className: "muted" });
      if (knowledge.interview_completed) {
        stack.appendChild(
          el("div", { className: "card stack" }, [
            el("p", { className: "muted" }, "Your dynamic interview can pre-fill these fields. Review and edit before submitting to the AI."),
            populateStatus,
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                populateStatus.textContent = "Filling from interview…";
                try {
                  const overwrite = confirm(
                    "Replace existing field content with a fresh extract from your interview?\n\nOK = replace all fields\nCancel = only fill empty fields"
                  );
                  const updated = await api(
                    `/dynamics/${dynamicId}/core-knowledge/me/from-interview?overwrite=${overwrite}`,
                    { method: "POST" }
                  );
                  knowledgeFields().forEach(([key]) => {
                    inputs[key].value = updated[key] || "";
                  });
                  populateStatus.textContent = overwrite
                    ? "Re-populated all fields from your interview."
                    : "Filled empty fields from your interview.";
                } catch (err) {
                  populateStatus.textContent = "";
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Re-populate from interview"),
          ])
        );
      } else {
        stack.appendChild(
          el("p", { className: "muted" }, "Complete your dynamic interview first to auto-fill or re-populate from it.")
        );
      }

      knowledgeFields().forEach(([key, label, placeholder]) => {
        inputs[key] = el("textarea", { placeholder });
        inputs[key].value = knowledge[key] || "";
        stack.appendChild(el("label", {}, [label, inputs[key]]));
      });

      const saveBody = () => {
        const body = {};
        knowledgeFields().forEach(([key]) => {
          body[key] = inputs[key].value;
        });
        return body;
      };

      const bottom = el("div", { className: "bottom-bar stack" }, [
        error,
        el("button", {
          className: "ghost-btn",
          onClick: async () => {
            try {
              await api(`/dynamics/${dynamicId}/core-knowledge/me`, {
                method: "PUT",
                body: JSON.stringify(saveBody()),
              });
              navigate(`/dynamic/${dynamicId}/knowledge`);
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Save draft"),
        el("button", {
          className: "primary-btn",
          onClick: async () => {
            try {
              await api(`/dynamics/${dynamicId}/core-knowledge/me`, {
                method: "PUT",
                body: JSON.stringify(saveBody()),
              });
              await api(`/dynamics/${dynamicId}/core-knowledge/me/submit`, { method: "POST" });
              navigate(`/dynamic/${dynamicId}/assistant`);
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Submit to AI"),
        el("button", {
          className: "ghost-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}/knowledge`),
        }, "Back"),
      ]);
      stack.appendChild(bottom);
      viewEl.replaceChildren(stack);
    })
    .catch((err) => viewEl.replaceChildren(el("p", { className: "error" }, err.message)));
}

function renderAssistant(dynamicId) {
  viewEl.replaceChildren(el("p", { className: "muted" }, "Loading Playtime..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/assistant/status`),
    loadDynamic(dynamicId),
  ])
    .then(([status]) => {
      const stack = el("div", { className: "stack" }, [
        buildHubHeader(dynamicId, "Playtime", {
          subtitle: "Tools for the domme / keyholder.",
          sectionFilter: "playtime",
        }),
        el("p", { className: "muted" }, `Provider: ${status.llm_provider} · Model: ${status.llm_model}`),
      ]);

      if (!status.your_interview_completed) {
        stack.appendChild(
          el("div", { className: "card stack" }, [
            el("p", {}, "Complete your dynamic interview first."),
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => navigate(`/dynamic/${dynamicId}/interview`),
            }, "Start interview"),
          ])
        );
      } else if (!status.llm_configured) {
        stack.appendChild(
          el("div", { className: "card stack" }, [
            el("p", {}, "AI is not configured yet."),
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => navigate("/settings"),
            }, "Open settings"),
          ])
        );
      } else {
        stack.appendChild(
          el("button", {
            className: "choice-btn playtime-option",
            type: "button",
            onClick: () => navigate(`/dynamic/${dynamicId}/assistant/scene`),
          }, [
            el("strong", {}, "Scene builder"),
            el("span", { className: "muted" }, "Effort → lean → subjects → full scene"),
          ])
        );
        stack.appendChild(
          el("button", {
            className: "choice-btn playtime-option",
            type: "button",
            onClick: () => navigate(`/dynamic/${dynamicId}/assistant/games`),
          }, [
            el("strong", {}, "Games"),
            el("span", { className: "muted" }, "Spin the wheel and other release games"),
          ])
        );
      }

      const enabledFeatures = state.currentDynamic?.enabled_features || [];
      PLAYTIME_EXTRA_FACETS.forEach((facet) => {
        if (!isFacetEnabled(facet, enabledFeatures)) return;
        stack.appendChild(renderFacetRow(facet, dynamicId, state.currentDynamic));
      });

      const dynamic = state.currentDynamic;
      const you = dynamic?.partners?.find((p) => p.is_you);
      const taskError = el("div", { className: "error hidden" });
      if (you?.role === "dominant") {
        const title = el("input", { placeholder: "List title (e.g. Tonight)" });
        const tasksBox = el("textarea", { rows: "4", placeholder: "One task per line" });
        const recurrence = el("select");
        [["none", "One-time"], ["daily", "Daily"], ["weekly", "Weekly"]].forEach(([v, l]) => {
          recurrence.appendChild(el("option", { value: v }, l));
        });
        const assignee = buildAssigneeSelect(dynamic.partners);
        stack.appendChild(el("div", { className: "card stack" }, [
          el("h2", {}, "Create tasks"),
          el("p", { className: "muted" }, "Keep it light — tracking overdue work stays under Tracking → Tasks."),
          title,
          tasksBox,
          el("label", {}, ["Recurrence", recurrence]),
          el("label", {}, ["Assign to", assignee]),
          taskError,
          el("button", {
            className: "primary-btn",
            type: "button",
            onClick: async () => {
              taskError.classList.add("hidden");
              const lines = tasksBox.value.split("\n").map((l) => l.trim()).filter(Boolean);
              if (!title.value.trim() || !lines.length) {
                taskError.textContent = "Add a title and at least one task.";
                taskError.classList.remove("hidden");
                return;
              }
              try {
                await api(`/dynamics/${dynamicId}/tasks`, {
                  method: "POST",
                  body: JSON.stringify({
                    title: title.value.trim(),
                    assigned_to_membership_id: assignee.value || null,
                    tasks: lines.map((content, index) => ({
                      content,
                      visibility: index === 0 ? "visible" : "after_prior",
                      recurrence: recurrence.value,
                    })),
                  }),
                });
                title.value = "";
                tasksBox.value = "";
                taskError.classList.add("hidden");
                const ok = el("p", { className: "muted" }, "Created. Open Tracking → Tasks to follow progress.");
                taskError.replaceWith(ok);
              } catch (err) {
                taskError.textContent = err.message;
                taskError.classList.remove("hidden");
              }
            },
          }, "Create task list"),
        ]));
      }

      stack.appendChild(
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => navigate(`/dynamic/${dynamicId}/track`),
        }, "Back to Tracking")
      );
      viewEl.replaceChildren(stack);
      updateBottomNav();
    })
    .catch((err) => viewEl.replaceChildren(el("p", { className: "error" }, err.message)));
}

function renderPlaytimeGames(dynamicId) {
  viewEl.replaceChildren(el("p", { className: "muted" }, "Loading games…"));
  Promise.all([
    loadDynamic(dynamicId),
    api(`/dynamics/${dynamicId}/playtime/spin/game`).catch(() => ({ status: "none", can_spin_post_orgasm: false })),
  ])
    .then(([_, game]) => {
      const you = state.currentDynamic?.partners?.find((p) => p.is_you);
      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Games"),
        el("p", { className: "muted" }, "When he's almost earned release or a full orgasm."),
      ]);
      if (game.can_spin_post_orgasm || game.status === "awaiting_post_spin") {
        stack.appendChild(
          el("div", { className: "card stack" }, [
            el("h2", {}, "Post-orgasm wheel waiting"),
            el("p", { className: "muted" }, "Open the current game and spin for post-orgasm task(s)."),
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => navigate(`/dynamic/${dynamicId}/assistant/games/spin?post=1`),
            }, "Spin now"),
          ])
        );
      }
      if (you?.role === "dominant" || you?.role === "submissive") {
        stack.appendChild(
          el("button", {
            className: "choice-btn playtime-option",
            type: "button",
            onClick: () =>
              navigate(
                game.status === "awaiting_post_spin"
                  ? `/dynamic/${dynamicId}/assistant/games/spin?post=1`
                  : `/dynamic/${dynamicId}/assistant/games/spin`
              ),
          }, [
            el("strong", {}, "Spin the wheel"),
            el(
              "span",
              { className: "muted" },
              game.status === "awaiting_post_spin"
                ? "Continue the current post-orgasm spin"
                : you?.role === "dominant"
                ? "Dice → outcomes → fate (secrets stay keyholder-only)"
                : "Shared outcomes only — secrets stay with the keyholder"
            ),
          ])
        );
      }
      stack.appendChild(
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => navigate(`/dynamic/${dynamicId}/assistant`),
        }, "Back to Playtime")
      );
      viewEl.replaceChildren(stack);
      updateBottomNav();
    })
    .catch((err) => viewEl.replaceChildren(el("p", { className: "error" }, err.message)));
}

function renderSpinTheWheel(dynamicId) {
  viewEl.replaceChildren(el("p", { className: "muted" }, "Loading Spin the wheel..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/assistant/status`),
    loadDynamic(dynamicId),
  ])
    .then(async ([status]) => {
      const partners = state.currentDynamic?.partners || [];
      const dominant = partners.find((p) => p.role === "dominant");
      const submissive = partners.find((p) => p.role === "submissive");
      const error = el("div", { className: "error hidden" });
      const body = el("div", { className: "stack" });
      const storageKey = `ubetra_spin_game_${dynamicId}`;

      const flow = {
        step: "pick",
        faces: 6,
        dice: null,
        value: null,
        multiplierUsed: false,
        options: [],
        selected: {},
        expanded: {},
        landed: null,
        postTasks: [],
        selectedTasks: {},
        postTaskCount: 1,
        postUseWheel: true,
        postSpinner: "either",
        postResults: [],
        serverGame: null,
        daysSince: null,
        verifiedWait: null,
        waitDirection: null,
        waitChoices: [],
        nextWaitDays: null,
        busy: false,
        inPlay: false,
        startedAt: null,
        ruinsRequired: 0,
        ruinsDone: 0,
        midgameOrgasms: [],
        orgasmShouldHaveBeenGranted: null,
        dominant_name: dominant?.display_name || "the keyholder",
        submissive_name: submissive?.display_name || "he",
      };

      function persist() {
        if (!flow.inPlay) return;
        const payload = {
          inPlay: true,
          startedAt: flow.startedAt,
          faces: flow.faces,
          dice: flow.dice,
          value: flow.value,
          multiplierUsed: flow.multiplierUsed,
          selected: flow.selected,
          step: flow.step,
          landedId: flow.landed?.id || null,
          ruinsRequired: flow.ruinsRequired,
          ruinsDone: flow.ruinsDone,
          verifiedWait: flow.verifiedWait,
          waitDirection: flow.waitDirection,
          waitChoices: flow.waitChoices,
          nextWaitDays: flow.nextWaitDays,
          selectedTasks: flow.selectedTasks,
        };
        localStorage.setItem(storageKey, JSON.stringify(payload));
      }

      function clearPersist() {
        localStorage.removeItem(storageKey);
        flow.inPlay = false;
        flow.startedAt = null;
      }

      function loadPersist() {
        try {
          const raw = localStorage.getItem(storageKey);
          if (!raw) return null;
          return JSON.parse(raw);
        } catch {
          return null;
        }
      }

      function markInPlay() {
        if (!flow.inPlay) {
          flow.inPlay = true;
          flow.startedAt = flow.startedAt || new Date().toISOString();
        }
        persist();
      }

      function setBusy(busy) {
        flow.busy = busy;
        paint();
      }

      function showError(message) {
        error.textContent = message;
        error.classList.remove("hidden");
      }

      function clearError() {
        error.classList.add("hidden");
        error.textContent = "";
      }

      function rollDie(faces) {
        return 1 + Math.floor(Math.random() * faces);
      }

      function applyMultiplier(value) {
        return Math.max(1, Math.ceil(Number(value) * 1.2));
      }

      function failCopy(behavior) {
        if (behavior === "lock_up") return "On fail: lock back up and serve the wait — no re-spin.";
        if (behavior === "ruins_session") {
          return "Run the ruins session (one at a time). Not a re-spin outcome.";
        }
        if (behavior === "retry_or_respin") {
          return "On fail: lock up and retry later, or re-spin for a different outcome.";
        }
        if (behavior === "continue_later") {
          return "If interrupted: lock up and finish the remaining count later.";
        }
        if (behavior === "none") return "";
        return "On fail: re-spin for a new outcome (same options).";
      }

      function subFacingText(option, value) {
        if (option.id === "full_orgasm") return "Full orgasm earned.";
        if (option.id === "multiplier") return "Multiplier — dice boosted, spinning again.";
        if (option.id === "ruins_secret" || !option.share_with_sub) {
          return `${option.title}: more ruins are required before you earn release/orgasm. (Exact count stays with the keyholder.)`;
        }
        const label = (option.value_label || "count").toLowerCase();
        return `${option.title}: ${value} ${label}.`;
      }

      function checkedOptions() {
        return flow.options.filter((opt) => {
          if (!flow.selected[opt.id]) return false;
          if (opt.id === "multiplier" && flow.multiplierUsed) return false;
          return true;
        });
      }

      function beginFullOrgasmPath() {
        flow.step = "full_loading";
        paint();
        loadPostOrgasmTasks();
      }

      async function loadOptions() {
        clearError();
        setBusy(true);
        try {
          const data = await api(`/dynamics/${dynamicId}/playtime/spin/suggestions`, {
            method: "POST",
            body: JSON.stringify({ faces: flow.faces }),
          });
          flow.dominant_name = data.dominant_name || flow.dominant_name;
          flow.submissive_name = data.submissive_name || flow.submissive_name;
          flow.daysSince = data.days_since_last_orgasm;
          flow.options = data.options || [];
          if (!Object.keys(flow.selected).length) {
            flow.options.forEach((opt) => {
              flow.selected[opt.id] = opt.source === "preset";
            });
          } else {
            flow.options.forEach((opt) => {
              if (flow.selected[opt.id] === undefined) {
                flow.selected[opt.id] = opt.source === "preset";
              }
            });
          }
        } catch (err) {
          showError(err.message);
        } finally {
          setBusy(false);
        }
      }

      async function checkMidgameOrgasm() {
        const saved = loadPersist();
        if (!saved?.inPlay || !saved.startedAt) return false;
        try {
          const data = await api(
            `/dynamics/${dynamicId}/playtime/spin/midgame?since=${encodeURIComponent(saved.startedAt)}`
          );
          if (data.days_since_last_orgasm != null) {
            flow.daysSince = data.days_since_last_orgasm;
          }
          if (data.full_orgasms?.length) {
            flow.midgameOrgasms = data.full_orgasms;
            flow.startedAt = saved.startedAt;
            flow.inPlay = true;
            flow.faces = saved.faces || flow.faces;
            flow.selected = saved.selected || flow.selected;
            flow.multiplierUsed = !!saved.multiplierUsed;
            flow.verifiedWait = data.days_since_last_orgasm ?? saved.verifiedWait ?? 7;
            flow.step = "midgame_orgasm";
            return true;
          }
        } catch {
          /* ignore — continue normal resume */
        }
        return false;
      }

      function resumeSaved() {
        const saved = loadPersist();
        if (!saved?.inPlay) return false;
        flow.inPlay = true;
        flow.startedAt = saved.startedAt;
        flow.faces = saved.faces || 6;
        flow.dice = saved.dice;
        flow.value = saved.value;
        flow.multiplierUsed = !!saved.multiplierUsed;
        flow.selected = saved.selected || {};
        flow.ruinsRequired = saved.ruinsRequired || 0;
        flow.ruinsDone = saved.ruinsDone || 0;
        flow.verifiedWait = saved.verifiedWait;
        flow.waitDirection = saved.waitDirection;
        flow.waitChoices = saved.waitChoices || [];
        flow.nextWaitDays = saved.nextWaitDays;
        flow.selectedTasks = saved.selectedTasks || {};
        if (saved.landedId && flow.options.length) {
          flow.landed = flow.options.find((o) => o.id === saved.landedId) || null;
        }
        // Prefer resuming ruins pause / active ruins session
        if (saved.step === "ruins_pause" || saved.step === "ruins_do" || saved.step === "ruins_ask") {
          flow.step = saved.step === "ruins_do" ? "ruins_do" : saved.step;
          if (saved.step === "ruins_ask") flow.step = "ruins_ask";
          return true;
        }
        if (saved.ruinsRequired > saved.ruinsDone && saved.ruinsRequired > 0) {
          flow.step = "ruins_pause";
          return true;
        }
        if (saved.step && saved.step !== "done" && saved.step !== "pick") {
          // Never resume a post-orgasm wheel from local storage alone — server must be awaiting.
          if (
            String(saved.step).startsWith("full_tasks") ||
            saved.step === "full_loading" ||
            saved.step === "full_wait_ask" ||
            saved.step === "full_wait_spin" ||
            saved.step === "full_wait_result" ||
            saved.step === "after_complete_ask"
          ) {
            return false;
          }
          flow.step = saved.step;
          return true;
        }
        return false;
      }

      function rollDice() {
        const chosen = checkedOptions();
        if (!chosen.length) {
          showError("Select at least one wheel option first.");
          return;
        }
        clearError();
        flow.dice = rollDie(flow.faces);
        flow.value = flow.dice;
        flow.landed = null;
        flow.step = "ready";
        markInPlay();
        paint();
      }

      function startRuinsSession(required) {
        flow.ruinsRequired = Number(required) || 1;
        flow.ruinsDone = 0;
        flow.step = "ruins_intro";
        markInPlay();
        paint();
      }

      function spinWheel() {
        const chosen = checkedOptions();
        if (!chosen.length) {
          showError("No options left on the wheel.");
          return;
        }
        if (flow.value == null) {
          showError("Roll the dice first — that number is assigned to whatever lands.");
          return;
        }
        clearError();
        const pick = chosen[Math.floor(Math.random() * chosen.length)];
        flow.landed = pick;
        markInPlay();

        if (pick.id === "multiplier") {
          const before = flow.value;
          flow.value = applyMultiplier(flow.value);
          flow.multiplierUsed = true;
          flow.selected.multiplier = false;
          flow.step = "multiplier";
          flow.multiplierBefore = before;
          persist();
          paint();
          return;
        }

        if (pick.id === "full_orgasm") {
          beginFullOrgasmPath();
          return;
        }

        if (pick.id === "ruins_secret") {
          startRuinsSession(flow.value);
          return;
        }

        flow.step = "result";
        persist();
        paint();
        if (pick.share_with_sub) {
          const label = pick.value_label || "value";
          announceShared(`Playtime outcome: ${pick.title} — ${flow.value} ${label.toLowerCase()}`);
        }
      }

      function respinAfterFail() {
        clearError();
        if (!checkedOptions().length) {
          showError("No options left on the wheel.");
          return;
        }
        flow.dice = rollDie(flow.faces);
        flow.value = flow.dice;
        flow.landed = null;
        markInPlay();
        spinWheel();
      }

      async function loadPostOrgasmTasks() {
        clearError();
        setBusy(true);
        try {
          await api(`/dynamics/${dynamicId}/playtime/spin/game/ensure`, { method: "POST" }).catch(() => null);
          const data = await api(`/dynamics/${dynamicId}/playtime/spin/post-orgasm-tasks`, {
            method: "POST",
          });
          flow.postTasks = data.tasks || [];
          flow.selectedTasks = {};
          flow.postTasks.forEach((task) => {
            // Preset services on by default; addons off until chosen.
            flow.selectedTasks[task.id] = task.kind !== "addon" && task.source === "preset";
          });
          if (data.days_since_last_orgasm != null) {
            flow.daysSince = data.days_since_last_orgasm;
          }
          flow.verifiedWait = flow.verifiedWait ?? (flow.daysSince != null ? flow.daysSince : 7);
          flow.postTaskCount = 1;
          flow.postUseWheel = true;
          flow.postSpinner = "either";
          flow.postResults = [];
          flow.step = "full_tasks_pool";
          persist();
        } catch (err) {
          showError(err.message);
          flow.step = "pick";
        } finally {
          setBusy(false);
        }
      }

      function selectedPool() {
        return flow.postTasks.filter((t) => flow.selectedTasks[t.id]);
      }

      async function submitPostOrgasmSetup() {
        clearError();
        const pool = selectedPool().map((t) => ({
          id: t.id,
          title: t.title,
          description: t.description || "",
        }));
        if (!pool.length) {
          showError("Select at least one task for the pool.");
          return;
        }
        const count = Math.max(1, Math.min(flow.postTaskCount || 1, pool.length));
        setBusy(true);
        try {
          let manual = [];
          if (!flow.postUseWheel) {
            manual = pool.slice(0, count);
          }
          const game = await api(`/dynamics/${dynamicId}/playtime/spin/post-orgasm/setup`, {
            method: "POST",
            body: JSON.stringify({
              task_pool: pool,
              task_count: count,
              use_wheel: !!flow.postUseWheel,
              spinner: flow.postSpinner || "either",
              manual_picks: manual,
            }),
          });
          flow.serverGame = game;
          flow.postResults = game.public?.post_orgasm?.results || manual;
          if (flow.postUseWheel) {
            const spinPath = `/dynamic/${dynamicId}/assistant/games/spin?post=1`;
            const pushUrl = `/#${spinPath}`;
            const link = `[[ubetra:${spinPath}|Spin the wheel]]`;
            if (flow.postSpinner === "sub") {
              await announceShared(`Post-orgasm wheel is ready — your turn to spin.\n${link}`, pushUrl);
            } else if (flow.postSpinner === "either") {
              await announceShared(`Post-orgasm wheel is ready — either of you can spin.\n${link}`, pushUrl);
            } else {
              await announceShared(`Post-orgasm wheel is ready (keyholder spinning).\n${link}`, pushUrl);
            }
            flow.step = "full_tasks_spin";
          } else {
            flow.step = "full_wait_ask";
          }
          persist();
        } catch (err) {
          showError(err.message);
        } finally {
          setBusy(false);
        }
      }

      async function spinPostOrgasmTask() {
        clearError();
        setBusy(true);
        try {
          const result = await api(`/dynamics/${dynamicId}/playtime/spin/post-orgasm/spin`, {
            method: "POST",
          });
          flow.postResults = result.results || [];
          // Stay on the wheel screen so all landed tasks are visible before continuing.
          persist();
        } catch (err) {
          showError(err.message);
          if (/no post-orgasm wheel waiting/i.test(err.message || "")) {
            // Stale UI vs server — offer escape via clear (button always shown for domme).
            const game = await api(`/dynamics/${dynamicId}/playtime/spin/game`).catch(() => null);
            if (!game?.can_spin_post_orgasm) {
              clearPersist();
            }
          }
        } finally {
          setBusy(false);
        }
      }

      async function clearCurrentGame() {
        clearError();
        setBusy(true);
        try {
          await api(`/dynamics/${dynamicId}/playtime/spin/game/clear`, { method: "POST" });
          clearPersist();
          flow.serverGame = null;
          flow.postResults = [];
          flow.postTasks = [];
          flow.selectedTasks = {};
          flow.postTaskCount = 1;
          flow.landed = null;
          flow.dice = null;
          flow.value = null;
          flow.multiplierUsed = false;
          flow.ruinsRequired = 0;
          flow.ruinsDone = 0;
          flow.waitChoices = [];
          flow.nextWaitDays = null;
          flow.waitDirection = null;
          flow.step = "pick";
          if (!flow.options.length) {
            await loadOptions();
          }
          clearError();
        } catch (err) {
          showError(err.message);
        } finally {
          setBusy(false);
        }
      }

      async function announceShared(text, pushUrl) {
        try {
          await api(`/dynamics/${dynamicId}/playtime/spin/announce`, {
            method: "POST",
            body: JSON.stringify({
              text,
              push_url: pushUrl || undefined,
            }),
          });
        } catch {
          /* optional */
        }
      }

      async function buildNextWait(direction) {
        clearError();
        setBusy(true);
        try {
          const data = await api(`/dynamics/${dynamicId}/playtime/spin/next-wait`, {
            method: "POST",
            body: JSON.stringify({
              verified_wait_days: Number(flow.verifiedWait) || 1,
              direction,
            }),
          });
          flow.waitDirection = direction;
          flow.waitChoices = data.day_choices || [];
          flow.step = "full_wait_spin";
          persist();
        } catch (err) {
          showError(err.message);
        } finally {
          setBusy(false);
        }
      }

      function paintOptionList() {
        const list = el("div", { className: "spin-option-list" });
        flow.options.forEach((opt) => {
          if (opt.id === "multiplier" && flow.multiplierUsed) return;
          const checked = !!flow.selected[opt.id];
          const open = !!flow.expanded[opt.id];
          const check = el("input", { type: "checkbox" });
          check.checked = checked;
          check.addEventListener("change", () => {
            flow.selected[opt.id] = check.checked;
            persist();
          });
          const toggle = el("button", {
            type: "button",
            className: "spin-expand-btn",
            onClick: () => {
              flow.expanded[opt.id] = !flow.expanded[opt.id];
              paint();
            },
          }, open ? "▾" : "▸");
          list.appendChild(
            el("div", { className: `spin-option-row ${open ? "open" : ""}` }, [
              el("label", { className: "checkbox-label spin-option-main" }, [
                check,
                opt.title + (opt.source === "llm" ? " · AI" : ""),
              ]),
              toggle,
            ])
          );
          if (open) {
            list.appendChild(
              el("div", { className: "spin-option-detail muted" }, [
                el("p", {}, opt.description || ""),
                opt.uses_dice
                  ? el("p", {}, `Dice supplies: ${opt.value_label || "count"}`)
                  : el("p", {}, "No dice value needed for this outcome."),
                el("p", {}, opt.share_with_sub ? "Shared with sub" : "Hidden count from sub"),
                failCopy(opt.fail_behavior) ? el("p", {}, failCopy(opt.fail_behavior)) : null,
              ])
            );
          }
        });
        return list;
      }

      async function fulfillSpin(kind, count, unit) {
        try {
          return await api(`/dynamics/${dynamicId}/playtime/spin/fulfill`, {
            method: "POST",
            body: JSON.stringify({
              kind,
              count: Number(count) || 1,
              unit: unit || "days",
            }),
          });
        } catch (err) {
          showError(err.message);
          throw err;
        }
      }

      function resetToPick() {
        clearPersist();
        flow.step = "pick";
        flow.dice = null;
        flow.value = null;
        flow.landed = null;
        flow.multiplierUsed = false;
        flow.postTasks = [];
        flow.selectedTasks = {};
        flow.postResults = [];
        flow.waitChoices = [];
        flow.nextWaitDays = null;
        flow.waitDirection = null;
        flow.ruinsRequired = 0;
        flow.ruinsDone = 0;
        flow.midgameOrgasms = [];
        flow.orgasmShouldHaveBeenGranted = null;
      }

      function paintResultActions(option) {
        const wrap = el("div", { className: "row wrap" });
        wrap.appendChild(
          el("button", {
            className: "primary-btn",
            type: "button",
            disabled: flow.busy,
            onClick: async () => {
              clearError();
              setBusy(true);
              try {
                if (option.id === "dom_orgasms_locked" && flow.value) {
                  await fulfillSpin("dom_orgasms", flow.value);
                } else if (option.id === "wait_days" && flow.value) {
                  await fulfillSpin("wait_lockup", flow.value, "days");
                } else if (option.id === "wait_weeks" && flow.value) {
                  await fulfillSpin("wait_lockup", flow.value, "weeks");
                }
                flow.step = "after_complete_ask";
                persist();
              } catch {
                /* error already shown */
              } finally {
                setBusy(false);
              }
            },
          }, "He completed it")
        );
        const behavior = option.fail_behavior;
        if (behavior === "lock_up" || behavior === "continue_later") {
          wrap.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => {
                flow.step = "paused";
                persist();
                paint();
              },
            }, "Lock up / continue later")
          );
        } else if (behavior === "retry_or_respin") {
          wrap.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => {
                flow.step = "paused";
                persist();
                paint();
              },
            }, "Lock up — retry later")
          );
          wrap.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => respinAfterFail(),
            }, "Re-spin for different outcome")
          );
        } else if (behavior !== "none" && behavior !== "ruins_session") {
          wrap.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => respinAfterFail(),
            }, "Failed — re-spin")
          );
        }
        return wrap;
      }

      function paint() {
        body.replaceChildren();
        body.appendChild(el("h1", {}, "Spin the wheel"));
        body.appendChild(
          el(
            "p",
            { className: "muted" },
            `${flow.submissive_name} has almost earned release or a full orgasm.`
          )
        );

        if (!status.your_interview_completed || !status.llm_configured) {
          body.appendChild(
            el("p", { className: "error" }, "Finish interview and AI setup in Playtime first.")
          );
          body.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => navigate(`/dynamic/${dynamicId}/assistant`),
            }, "Back to Playtime")
          );
          return;
        }

        if (flow.busy) {
          body.appendChild(el("p", { className: "muted" }, "Working…"));
        }

        if (flow.step === "sub_view") {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Shared playtime only"),
              el(
                "p",
                { className: "muted" },
                "Secret wheel setup stays with the keyholder. When a shared spin is ready (like post-orgasm tasks), it shows up here and in chat."
              ),
            ])
          );
        } else if (flow.step === "midgame_orgasm") {
          const when = flow.midgameOrgasms[0]?.occurred_at
            ? new Date(flow.midgameOrgasms[0].occurred_at).toLocaleString()
            : "recently";
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Full orgasm logged mid-game"),
              el(
                "p",
                {},
                `While this spin game was in play, a full orgasm for ${flow.submissive_name} was recorded (${when}).`
              ),
              el("p", { className: "muted" }, "Should that full orgasm have been granted?"),
            ])
          );
          body.appendChild(
            el("div", { className: "row wrap" }, [
              el("button", {
                className: "primary-btn",
                type: "button",
                onClick: () => {
                  flow.orgasmShouldHaveBeenGranted = true;
                  flow.verifiedWait = flow.daysSince != null ? flow.daysSince : 7;
                  flow.step = "full_wait_verify";
                  persist();
                  paint();
                },
              }, "Yes — it was granted"),
              el("button", {
                className: "ghost-btn",
                type: "button",
                onClick: () => {
                  flow.orgasmShouldHaveBeenGranted = false;
                  flow.verifiedWait = flow.daysSince != null ? flow.daysSince : 7;
                  flow.step = "full_wait_verify";
                  persist();
                  paint();
                },
              }, "No — it should not have been"),
            ])
          );
          body.appendChild(
            el("p", { className: "muted" }, "Next you'll set longer/shorter for the following wait.")
          );
        } else if (flow.step === "pick") {
          body.appendChild(el("h2", {}, "1. Choose wheel options"));
          body.appendChild(
            el("p", { className: "muted" }, "Select outcomes first. Expand a row for details. Dice comes after.")
          );
          const facesInput = el("input", {
            type: "number",
            min: "2",
            max: "20",
            value: String(flow.faces),
          });
          facesInput.addEventListener("change", () => {
            flow.faces = Math.max(2, Math.min(20, parseInt(facesInput.value, 10) || 6));
          });
          body.appendChild(el("label", {}, ["Dice faces (used when you roll)", facesInput]));
          body.appendChild(paintOptionList());
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              disabled: flow.busy,
              onClick: () => rollDice(),
            }, "2. Roll the dice")
          );
          body.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              disabled: flow.busy,
              onClick: () => loadOptions(),
            }, "Refresh AI extras")
          );
        } else if (flow.step === "ready") {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, `Dice: ${flow.value}`),
              el(
                "p",
                { className: "muted" },
                flow.dice !== flow.value
                  ? `Rolled ${flow.dice}, now ${flow.value} after multiplier.`
                  : `On a ${flow.faces}-sided die. This number is assigned to whatever lands.`
              ),
            ])
          );
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => spinWheel(),
            }, "3. Spin the wheel")
          );
          body.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => {
                flow.step = "pick";
                paint();
              },
            }, "Back to options")
          );
        } else if (flow.step === "multiplier") {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Multiplier!"),
              el("p", {}, `Dice boosted from ${flow.multiplierBefore} → ${flow.value}. Spin again.`),
            ])
          );
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => {
                flow.step = "ready";
                flow.landed = null;
                persist();
                paint();
              },
            }, "Spin again")
          );
        } else if (flow.step === "ruins_intro") {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Ruins before earned"),
              el("p", {}, `Secret count for you: ${flow.ruinsRequired} ruin(s).`),
              el(
                "p",
                { className: "muted" },
                "Tell him only that more ruins are required — do not share the number."
              ),
              el(
                "p",
                { className: "muted" },
                "Proceed with one ruin (in front of you, or have him ruin himself in front of you), then you'll be asked if he can handle another."
              ),
            ])
          );
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => {
                flow.step = "ruins_do";
                persist();
                paint();
              },
            }, "Start first ruin")
          );
        } else if (flow.step === "ruins_do") {
          const remaining = Math.max(0, flow.ruinsRequired - flow.ruinsDone);
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Ruin now"),
              el("p", {}, `Progress (secret): ${flow.ruinsDone} / ${flow.ruinsRequired}`),
              el("p", { className: "muted" }, `Remaining for you: ${remaining}`),
              el(
                "p",
                { className: "muted" },
                "Have him ruin once in front of you, or tell him to ruin himself in front of you."
              ),
            ])
          );
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => {
                flow.ruinsDone += 1;
                if (flow.ruinsDone >= flow.ruinsRequired) {
                  flow.step = "ruins_offer_orgasm";
                } else {
                  flow.step = "ruins_ask";
                }
                persist();
                paint();
              },
            }, "Ruin completed")
          );
        } else if (flow.step === "ruins_ask") {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Another ruin?"),
              el("p", {}, `Secret progress: ${flow.ruinsDone} / ${flow.ruinsRequired}`),
              el("p", { className: "muted" }, "Ask if he can handle another ruin."),
            ])
          );
          body.appendChild(
            el("div", { className: "row wrap" }, [
              el("button", {
                className: "primary-btn",
                type: "button",
                onClick: () => {
                  flow.step = "ruins_do";
                  persist();
                  paint();
                },
              }, "Yes — another ruin"),
              el("button", {
                className: "ghost-btn",
                type: "button",
                onClick: () => {
                  flow.step = "ruins_pause";
                  persist();
                  paint();
                },
              }, "No — lock up, finish later"),
            ])
          );
        } else if (flow.step === "ruins_pause") {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Locked up — ruins pending"),
              el(
                "p",
                {},
                `Secret progress saved: ${flow.ruinsDone} / ${flow.ruinsRequired}. Continue play later until the remaining ruins are provided.`
              ),
              el("p", { className: "muted" }, "This game stays in play and is tied to orgasm tracking."),
            ])
          );
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => {
                flow.step = "ruins_do";
                persist();
                paint();
              },
            }, "Resume ruins now")
          );
        } else if (flow.step === "ruins_offer_orgasm") {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Ruins complete"),
              el("p", {}, `Secret count met (${flow.ruinsRequired}).`),
              el("p", { className: "muted" }, "Ask if he wants his full orgasm now or later."),
            ])
          );
          body.appendChild(
            el("div", { className: "row wrap" }, [
              el("button", {
                className: "primary-btn",
                type: "button",
                onClick: () => beginFullOrgasmPath(),
              }, "Full orgasm now"),
              el("button", {
                className: "ghost-btn",
                type: "button",
                onClick: () => {
                  flow.step = "after_complete_ask";
                  persist();
                  paint();
                },
              }, "Later — end for now"),
            ])
          );
        } else if (flow.step === "result" && flow.landed) {
          const option = flow.landed;
          const value = flow.value;
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("p", { className: "muted" }, `Dice value ${value}`),
              el("h2", {}, option.title),
              el("p", {}, `${option.value_label || "Value"}: ${value}`),
              el("p", { className: "muted" }, option.description || ""),
              el("h3", {}, "What to tell him"),
              el("p", { className: "playtime-scene-body" }, subFacingText(option, value)),
              el("h3", {}, "If interrupted / fails"),
              el("p", { className: "muted" }, failCopy(option.fail_behavior) || "Handle as you see fit."),
            ])
          );
          body.appendChild(paintResultActions(option));
        } else if (flow.step === "paused") {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Paused"),
              el("p", {}, "Lock him up and continue this assignment later. Game stays in play."),
              flow.landed
                ? el("p", { className: "muted" }, `Active outcome: ${flow.landed.title} · ${flow.value}`)
                : null,
            ])
          );
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => {
                flow.step = "result";
                persist();
                paint();
              },
            }, "Resume outcome")
          );
        } else if (flow.step === "full_loading") {
          body.appendChild(el("h2", {}, "Full Orgasm!"));
          body.appendChild(el("p", { className: "muted" }, "Loading post-orgasm tasks…"));
        } else if (flow.step === "full_tasks_pool") {
          if (!flow.expandedTasks) flow.expandedTasks = {};
          if (!flow.addonsOpen) flow.addonsOpen = false;
          const services = flow.postTasks.filter((t) => t.kind !== "addon");
          const addons = flow.postTasks.filter((t) => t.kind === "addon");

          function taskRow(task) {
            const open = !!flow.expandedTasks[task.id];
            const check = el("input", { type: "checkbox" });
            check.checked = !!flow.selectedTasks[task.id];
            check.addEventListener("change", () => {
              flow.selectedTasks[task.id] = check.checked;
            });
            const toggle = el(
              "button",
              {
                className: "spin-expand-btn",
                type: "button",
                "aria-label": open ? "Hide details" : "Show details",
                onClick: () => {
                  flow.expandedTasks[task.id] = !flow.expandedTasks[task.id];
                  paint();
                },
              },
              open ? "▾" : "▸"
            );
            const rows = [
              el("div", { className: "spin-option-row" }, [
                el("label", { className: "checkbox-label spin-option-main" }, [
                  check,
                  task.title + (task.source === "llm" ? " · AI" : ""),
                ]),
                toggle,
              ]),
            ];
            if (open) {
              rows.push(
                el("div", { className: "spin-option-detail muted" }, [
                  el("p", {}, task.description || "No extra detail."),
                ])
              );
            }
            return rows;
          }

          body.appendChild(el("h2", {}, "Post-orgasm task pool"));
          body.appendChild(
            el("p", { className: "muted" }, "Check which services can land on the wheel. Expand for details.")
          );
          const taskList = el("div", { className: "spin-option-list" });
          services.forEach((task) => {
            taskRow(task).forEach((node) => taskList.appendChild(node));
          });
          body.appendChild(taskList);

          body.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => {
                flow.addonsOpen = !flow.addonsOpen;
                paint();
              },
            }, flow.addonsOpen ? "Hide add-ons ▾" : "Add-ons ▸")
          );
          if (flow.addonsOpen) {
            body.appendChild(
              el(
                "p",
                { className: "muted" },
                "Optional extras that can also land on the wheel (or be assigned with a service)."
              )
            );
            const addonList = el("div", { className: "spin-option-list" });
            addons.forEach((task) => {
              taskRow(task).forEach((node) => addonList.appendChild(node));
            });
            body.appendChild(addonList);
          }

          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => {
                if (!selectedPool().length) {
                  showError("Select at least one task.");
                  return;
                }
                clearError();
                flow.step = "full_tasks_count";
                paint();
              },
            }, "Next")
          );
        } else if (flow.step === "full_tasks_count") {
          const poolSize = selectedPool().length;
          body.appendChild(el("h2", {}, "One task or more?"));
          body.appendChild(
            el("p", { className: "muted" }, `Pool has ${poolSize} task(s). How many should be assigned?`)
          );
          body.appendChild(
            el("div", { className: "row wrap" }, [
              el("button", {
                className: `choice-btn ${flow.postTaskCount === 1 ? "active" : ""}`,
                type: "button",
                onClick: () => {
                  flow.postTaskCount = 1;
                  paint();
                },
              }, "Just one"),
              el("button", {
                className: `choice-btn ${flow.postTaskCount > 1 ? "active" : ""}`,
                type: "button",
                onClick: () => {
                  flow.postTaskCount = Math.min(2, poolSize);
                  paint();
                },
              }, "More than one"),
            ])
          );
          if (flow.postTaskCount > 1) {
            const countInput = el("input", {
              type: "number",
              min: "2",
              max: String(poolSize),
              value: String(Math.min(flow.postTaskCount, poolSize)),
            });
            countInput.addEventListener("change", () => {
              flow.postTaskCount = Math.max(2, Math.min(poolSize, parseInt(countInput.value, 10) || 2));
            });
            body.appendChild(el("label", {}, ["How many tasks?", countInput]));
          }
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => {
                flow.step = "full_tasks_method";
                paint();
              },
            }, "Next")
          );
        } else if (flow.step === "full_tasks_method") {
          body.appendChild(el("h2", {}, "How to choose?"));
          body.appendChild(
            el("p", { className: "muted" }, "Select randomly with a wheel spin, or pick yourself.")
          );
          body.appendChild(
            el("div", { className: "row wrap" }, [
              el("button", {
                className: "primary-btn",
                type: "button",
                onClick: () => {
                  flow.postUseWheel = true;
                  flow.step = "full_tasks_who";
                  paint();
                },
              }, "Wheel spin (random)"),
              el("button", {
                className: "ghost-btn",
                type: "button",
                onClick: async () => {
                  flow.postUseWheel = false;
                  await submitPostOrgasmSetup();
                },
              }, "I'll pick (no wheel)"),
            ])
          );
        } else if (flow.step === "full_tasks_who") {
          body.appendChild(el("h2", {}, "Who spins the post-orgasm wheel?"));
          body.appendChild(
            el("div", { className: "playtime-options" }, [
              el("button", {
                className: "choice-btn playtime-option",
                type: "button",
                onClick: async () => {
                  flow.postSpinner = "dom";
                  await submitPostOrgasmSetup();
                },
              }, [el("strong", {}, "Domme / keyholder"), el("span", { className: "muted" }, "You spin (you can always spin anyway)")]),
              el("button", {
                className: "choice-btn playtime-option",
                type: "button",
                onClick: async () => {
                  flow.postSpinner = "sub";
                  await submitPostOrgasmSetup();
                },
              }, [el("strong", {}, "Sub"), el("span", { className: "muted" }, "He spins — chat link + push nudge")]),
              el("button", {
                className: "choice-btn playtime-option",
                type: "button",
                onClick: async () => {
                  flow.postSpinner = "either";
                  await submitPostOrgasmSetup();
                },
              }, [el("strong", {}, "Either"), el("span", { className: "muted" }, "Whoever opens can spin — you can always spin")]),
            ])
          );
        } else if (flow.step === "full_tasks_spin") {
          const needed = flow.postTaskCount || 1;
          const done = flow.postResults.length;
          const spinner = flow.postSpinner || "either";
          const you = state.currentDynamic?.partners?.find((p) => p.is_you);
          const canSpin =
            you?.role === "dominant" ||
            spinner === "either" ||
            (spinner === "sub" && you?.role === "submissive");
          body.appendChild(el("h2", {}, "Post-orgasm wheel"));
          body.appendChild(
            el(
              "p",
              { className: "muted" },
              `Spun ${done} of ${needed}. Preferred spinner: ${spinner}. Keyholder can always spin.`
            )
          );
          if (flow.postResults.length) {
            body.appendChild(
              el("div", { className: "card stack" }, [
                el("h3", {}, "Landed so far"),
                ...flow.postResults.map((r) =>
                  el("div", { className: "stack" }, [
                    el("p", {}, r.title),
                    r.description
                      ? el("p", { className: "muted" }, r.description)
                      : null,
                  ])
                ),
              ])
            );
          }
          if (done < needed && canSpin) {
            body.appendChild(
              el("button", {
                className: "primary-btn",
                type: "button",
                disabled: flow.busy,
                onClick: () => spinPostOrgasmTask(),
              }, done ? "Spin again" : "Spin the wheel")
            );
          } else if (done < needed) {
            body.appendChild(
              el("p", { className: "muted" }, "Waiting for the chosen spinner. Shared tasks notify in chat.")
            );
            body.appendChild(
              el("button", {
                className: "ghost-btn",
                type: "button",
                onClick: async () => {
                  const game = await api(`/dynamics/${dynamicId}/playtime/spin/game`);
                  flow.serverGame = game;
                  flow.postResults = game.public?.post_orgasm?.results || [];
                  paint();
                },
              }, "Refresh")
            );
          } else {
            body.appendChild(
              el(
                "p",
                { className: "muted" },
                needed === 1
                  ? "Task is set. Continue when you’re ready for the next wait."
                  : `All ${needed} tasks are set. Continue when you’re ready for the next wait.`
              )
            );
            body.appendChild(
              el("button", {
                className: "primary-btn",
                type: "button",
                onClick: () => {
                  flow.step = "full_wait_ask";
                  paint();
                },
              }, "Continue to next wait")
            );
          }
        } else if (flow.step === "full_wait_ask") {
          body.appendChild(el("h2", {}, "Next orgasm wait?"));
          body.appendChild(
            el("p", { className: "muted" }, "Spin a wheel for the next wait period?")
          );
          body.appendChild(
            el("div", { className: "row wrap" }, [
              el("button", {
                className: "primary-btn",
                type: "button",
                onClick: () => {
                  flow.step = "full_wait_verify";
                  persist();
                  paint();
                },
              }, "Yes — set next wait"),
              el("button", {
                className: "ghost-btn",
                type: "button",
                onClick: () => {
                  flow.step = "after_complete_ask";
                  persist();
                  paint();
                },
              }, "No — finish"),
            ])
          );
        } else if (flow.step === "full_wait_verify") {
          body.appendChild(el("h2", {}, "Verify this wait"));
          if (flow.orgasmShouldHaveBeenGranted === true) {
            body.appendChild(
              el("p", { className: "muted" }, "Tracked mid-game orgasm was marked as granted.")
            );
          } else if (flow.orgasmShouldHaveBeenGranted === false) {
            body.appendChild(
              el(
                "p",
                { className: "muted" },
                "Tracked mid-game orgasm was marked as not properly granted — still set the next wait from the actual interval."
              )
            );
          }
          const appDays = flow.daysSince;
          body.appendChild(
            el(
              "p",
              { className: "muted" },
              appDays == null
                ? "No wait found in tracking yet — enter how many days this wait actually was."
                : `App shows about ${appDays} day(s) since last orgasm / lock start. Confirm or edit.`
            )
          );
          const waitInput = el("input", {
            type: "number",
            min: "1",
            max: "3650",
            value: String(flow.verifiedWait ?? appDays ?? 7),
          });
          body.appendChild(el("label", {}, ["Days waited for this orgasm", waitInput]));
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => {
                flow.verifiedWait = Math.max(1, parseInt(waitInput.value, 10) || 1);
                flow.step = "full_wait_direction";
                persist();
                paint();
              },
            }, "Next")
          );
        } else if (flow.step === "full_wait_direction") {
          body.appendChild(el("h2", {}, "Longer or shorter?"));
          body.appendChild(
            el(
              "p",
              { className: "muted" },
              `This wait was ${flow.verifiedWait} day(s). Longer = at least +1 day, up to 20% more. Shorter = about 50–90% of this wait.`
            )
          );
          body.appendChild(
            el("div", { className: "row wrap" }, [
              el("button", {
                className: "primary-btn",
                type: "button",
                disabled: flow.busy,
                onClick: () => buildNextWait("longer"),
              }, "Longer"),
              el("button", {
                className: "ghost-btn",
                type: "button",
                disabled: flow.busy,
                onClick: () => buildNextWait("shorter"),
              }, "Shorter"),
            ])
          );
        } else if (flow.step === "full_wait_spin") {
          body.appendChild(el("h2", {}, `Next wait wheel (${flow.waitDirection})`));
          body.appendChild(
            el(
              "p",
              { className: "muted" },
              `Choices: ${flow.waitChoices.join(", ")} days`
            )
          );
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => {
                flow.nextWaitDays =
                  flow.waitChoices[Math.floor(Math.random() * flow.waitChoices.length)];
                flow.step = "full_wait_result";
                persist();
                paint();
              },
            }, "Spin for next wait")
          );
        } else if (flow.step === "full_wait_result") {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Next wait set"),
              el("p", {}, `${flow.nextWaitDays} day(s) until the next earned orgasm window.`),
              el("p", { className: "muted" }, "Continue applies this to chastity lockup when one is active."),
            ])
          );
          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              disabled: flow.busy,
              onClick: async () => {
                clearError();
                setBusy(true);
                try {
                  if (flow.nextWaitDays) {
                    await fulfillSpin("wait_lockup", flow.nextWaitDays, "days");
                  }
                  flow.step = "after_complete_ask";
                  persist();
                } catch {
                  /* shown */
                } finally {
                  setBusy(false);
                }
              },
            }, "Continue")
          );
        } else if (flow.step === "after_complete_ask") {
          const landedTasks = flow.postResults?.length
            ? flow.postResults
            : (flow.postTasks || []).filter((t) => flow.selectedTasks[t.id]);
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Tasks complete"),
              landedTasks.length
                ? el("div", { className: "stack" }, [
                    el("p", { className: "muted" }, "Assigned:"),
                    ...landedTasks.map((t) => el("p", {}, t.title)),
                  ])
                : null,
              flow.nextWaitDays != null
                ? el("p", {}, `Next wait / lockup add: ${flow.nextWaitDays} day(s)`)
                : null,
              el(
                "p",
                {},
                "Did you grant a full orgasm, or should we spin the wheel again?"
              ),
            ])
          );
          body.appendChild(
            el("div", { className: "playtime-options" }, [
              el("button", {
                className: "choice-btn playtime-option",
                type: "button",
                disabled: flow.busy,
                onClick: async () => {
                  clearError();
                  setBusy(true);
                  try {
                    const fStatus = await api(`/dynamics/${dynamicId}/feelings/status`).catch(() => null);
                    if (fStatus?.hard_gate_active) {
                      const recent = await api(`/dynamics/${dynamicId}/feelings?limit=5`).catch(() => []);
                      const sixHoursAgo = Date.now() - 6 * 3600 * 1000;
                      const hasAfter = (recent || []).some(
                        (r) =>
                          r.for_membership_id &&
                          r.context === "after_play" &&
                          new Date(r.occurred_at).getTime() >= sixHoursAgo
                      );
                      if (!hasAfter) {
                        showError("Log after-play feelings on the Feelings wheel first.");
                        setBusy(false);
                        return;
                      }
                    }
                    await fulfillSpin("sub_full_orgasm", 1);
                    await api(`/dynamics/${dynamicId}/playtime/spin/game/clear`, {
                      method: "POST",
                    }).catch(() => null);
                    resetToPick();
                    if (!flow.options.length) await loadOptions();
                  } catch (err) {
                    showError(err.message);
                  } finally {
                    setBusy(false);
                  }
                },
              }, [
                el("strong", {}, "Granted a full orgasm"),
                el(
                  "span",
                  { className: "muted" },
                  "Logs it in sex & orgasm tracking · Game notifies chat"
                ),
              ]),
              el("button", {
                className: "choice-btn playtime-option",
                type: "button",
                disabled: flow.busy,
                onClick: async () => {
                  clearError();
                  setBusy(true);
                  try {
                    await announceShared("Spin again — another wheel round.");
                    await api(`/dynamics/${dynamicId}/playtime/spin/game/clear`, {
                      method: "POST",
                    }).catch(() => null);
                    resetToPick();
                    if (!flow.options.length) await loadOptions();
                  } catch {
                    /* shown */
                  } finally {
                    setBusy(false);
                  }
                },
              }, [
                el("strong", {}, "Spin the wheel again"),
                el(
                  "span",
                  { className: "muted" },
                  "Start a fresh spin without logging a full orgasm"
                ),
              ]),
            ])
          );
        } else if (flow.step === "done") {
          flow.step = "after_complete_ask";
          paint();
          return;
        }

        body.appendChild(error);
        const youNow = state.currentDynamic?.partners?.find((p) => p.is_you);
        if (youNow?.role === "dominant" && flow.step !== "pick") {
          body.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              disabled: flow.busy,
              onClick: () => {
                if (!window.confirm("Clear the current spin game and start from scratch?")) return;
                clearCurrentGame();
              },
            }, "Clear game & start over")
          );
        }
        body.appendChild(
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: () => navigate(`/dynamic/${dynamicId}/assistant/games`),
          }, "Back to Games")
        );
      }

      viewEl.replaceChildren(el("div", { className: "stack" }, [body]));
      updateBottomNav();

      (async () => {
        const you = state.currentDynamic?.partners?.find((p) => p.is_you);
        const wantPost = /[?&]post=1/.test(location.hash);

        // Shared / active post-orgasm wheel — jump straight into the current game.
        try {
          const game = await api(`/dynamics/${dynamicId}/playtime/spin/game`);
          flow.serverGame = game;
          const post = game.public?.post_orgasm || {};
          const awaiting =
            game.status === "awaiting_post_spin" && post.use_wheel;
          if (awaiting || game.can_spin_post_orgasm) {
            flow.postResults = post.results || [];
            flow.postTaskCount = post.task_count || 1;
            flow.postSpinner = post.spinner || "either";
            flow.postUseWheel = !!post.use_wheel;
            flow.step = "full_tasks_spin";
            paint();
            return;
          }
          // Stale local post-orgasm resume — drop it if server isn't waiting.
          const saved = loadPersist();
          if (saved?.step && String(saved.step).startsWith("full_")) {
            clearPersist();
          }
          if (wantPost && you?.role === "dominant") {
            // ?post=1 with nothing waiting — don't trap; fall through to pick.
          }
          // Submissive: never see secret wheel setup — only shared pending spins.
          if (you?.role === "submissive") {
            flow.step = "sub_view";
            paint();
            return;
          }
        } catch {
          /* continue */
        }

        if (!status.your_interview_completed || !status.llm_configured) {
          paint();
          return;
        }
        await loadOptions();
        const mid = await checkMidgameOrgasm();
        if (mid) {
          paint();
          return;
        }
        if (resumeSaved()) {
          if (flow.landed?.id && !flow.landed.title) {
            flow.landed = flow.options.find((o) => o.id === flow.landed.id) || flow.landed;
          }
          if (flow.landedId && !flow.landed) {
            const saved = loadPersist();
            flow.landed = flow.options.find((o) => o.id === saved?.landedId) || null;
          }
          paint();
          return;
        }
        flow.step = "pick";
        paint();
      })();
    })
    .catch((err) => viewEl.replaceChildren(el("p", { className: "error" }, err.message)));
}

function renderPlaytimeScene(dynamicId) {
  viewEl.replaceChildren(el("p", { className: "muted" }, "Loading scene builder..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/assistant/status`),
    loadDynamic(dynamicId),
  ])
    .then(([status]) => {
      const you = state.currentDynamic.partners.find((p) => p.is_you);
      const error = el("div", { className: "error hidden" });
      const body = el("div", { className: "stack" });

      const flow = {
        step: "effort",
        effort: null,
        lean: null,
        subjects: [],
        subject: null,
        scene: null,
        busy: false,
        contextFlags: { journals: true, stories: true, scenes: true, agreements: true, tracking: true },
      };
      const { toggleBtn: contextToggleBtn, menu: contextMenu } = buildContextFlagsMenu(flow.contextFlags);

      const EFFORT_OPTIONS = [
        { id: "low", title: "Low", subtitle: "Under 5 minutes" },
        { id: "med", title: "Medium", subtitle: "About 10–15 minutes" },
        { id: "high", title: "High", subtitle: "20+ minutes, or lots of prep" },
      ];
      const LEAN_OPTIONS = [
        { id: "sub", title: "Sub", subtitle: "Lean on the submissive's desires" },
        { id: "dom", title: "Dom / keyholder", subtitle: "Lean on the dominant's desires" },
        { id: "equal", title: "Equal", subtitle: "Balance both partners" },
      ];

      function setBusy(busy) {
        flow.busy = busy;
        paint();
      }

      function showError(message) {
        error.textContent = message;
        error.classList.remove("hidden");
      }

      function clearError() {
        error.classList.add("hidden");
        error.textContent = "";
      }

      async function loadSubjects(exclude = []) {
        clearError();
        setBusy(true);
        try {
          const result = await api(`/dynamics/${dynamicId}/playtime/subjects`, {
            method: "POST",
            body: JSON.stringify({
              effort: flow.effort,
              lean: flow.lean,
              exclude_subjects: exclude,
            }),
          });
          flow.subjects = result.subjects || [];
          flow.step = "subjects";
        } catch (err) {
          showError(err.message);
        } finally {
          setBusy(false);
        }
      }

      async function loadScene(note = "", avoidSummary = "") {
        clearError();
        setBusy(true);
        try {
          const result = await api(`/dynamics/${dynamicId}/playtime/scene`, {
            method: "POST",
            body: JSON.stringify({
              effort: flow.effort,
              lean: flow.lean,
              subject: flow.subject,
              note,
              avoid_summary: avoidSummary,
              context_flags: flow.contextFlags,
            }),
          });
          flow.scene = result;
          flow.step = "scene";
        } catch (err) {
          showError(err.message);
        } finally {
          setBusy(false);
        }
      }

      async function rateScene(rating) {
        clearError();
        setBusy(true);
        try {
          const result = await api(`/dynamics/${dynamicId}/playtime/feedback`, {
            method: "POST",
            body: JSON.stringify({
              effort: flow.effort,
              lean: flow.lean,
              subject: flow.subject,
              scene_title: flow.scene?.title || "",
              scene_summary: flow.scene?.summary || flow.scene?.body?.slice(0, 240) || "",
              rating,
            }),
          });
          flow.step = "done";
          flow.doneMessage = result.message || "Saved.";
        } catch (err) {
          showError(err.message);
        } finally {
          setBusy(false);
        }
      }

      async function rejectAndRetry(note) {
        clearError();
        setBusy(true);
        try {
          const result = await api(`/dynamics/${dynamicId}/playtime/feedback`, {
            method: "POST",
            body: JSON.stringify({
              effort: flow.effort,
              lean: flow.lean,
              subject: flow.subject,
              scene_title: flow.scene?.title || "",
              scene_summary: flow.scene?.summary || flow.scene?.body?.slice(0, 240) || "",
              reject: true,
              regenerate: true,
              note,
            }),
          });
          if (result.scene) {
            flow.scene = result.scene;
            flow.step = "scene";
          }
        } catch (err) {
          showError(err.message);
        } finally {
          setBusy(false);
        }
      }

      function optionButtons(options, selectedId, onPick) {
        const wrap = el("div", { className: "playtime-options" });
        options.forEach((opt) => {
          const btn = el("button", {
            type: "button",
            className: `choice-btn playtime-option ${selectedId === opt.id ? "active" : ""}`,
            disabled: flow.busy,
            onClick: () => onPick(opt.id),
          }, [
            el("strong", {}, opt.title),
            el("span", { className: "muted" }, opt.subtitle),
          ]);
          wrap.appendChild(btn);
        });
        return wrap;
      }

      function paint() {
        body.replaceChildren();
        body.appendChild(el("h1", {}, "Scene builder"));
        body.appendChild(
          el("p", { className: "muted" }, "Quick scene builder for the domme / keyholder.")
        );
        body.appendChild(el("div", { className: "row wrap" }, [contextToggleBtn]));
        body.appendChild(contextMenu);

        if (!status.your_interview_completed) {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("p", {}, "Complete your dynamic interview first."),
              el("button", {
                className: "primary-btn",
                type: "button",
                onClick: () => navigate(`/dynamic/${dynamicId}/interview`),
              }, "Start interview"),
            ])
          );
          body.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => navigate(`/dynamic/${dynamicId}/assistant`),
            }, "Back to Playtime")
          );
          return;
        }

        if (!status.llm_configured) {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("p", {}, "AI is not configured yet."),
              el("button", {
                className: "primary-btn",
                type: "button",
                onClick: () => navigate("/settings"),
              }, "Open settings"),
            ])
          );
          return;
        }

        if (flow.busy) {
          body.appendChild(el("p", { className: "muted" }, "Working with the assistant…"));
        }

        if (flow.step === "effort") {
          body.appendChild(el("h2", {}, "Level of effort"));
          body.appendChild(
            optionButtons(EFFORT_OPTIONS, flow.effort, (id) => {
              flow.effort = id;
              flow.step = "lean";
              paint();
            })
          );
        } else if (flow.step === "lean") {
          body.appendChild(el("h2", {}, "Whose desires should we lean on?"));
          body.appendChild(
            optionButtons(LEAN_OPTIONS, flow.lean, async (id) => {
              flow.lean = id;
              await loadSubjects();
            })
          );
          body.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              disabled: flow.busy,
              onClick: () => {
                flow.step = "effort";
                paint();
              },
            }, "Back")
          );
        } else if (flow.step === "subjects") {
          body.appendChild(el("h2", {}, "Pick a scene subject"));
          body.appendChild(
            el("p", { className: "muted" }, "Three options tailored to this dynamic and effort.")
          );
          const list = el("div", { className: "playtime-options" });
          flow.subjects.forEach((subject) => {
            list.appendChild(
              el("button", {
                type: "button",
                className: "choice-btn playtime-option",
                disabled: flow.busy,
                onClick: async () => {
                  flow.subject = subject.title;
                  await loadScene();
                },
              }, [
                el("strong", {}, subject.title),
                el("span", { className: "muted" }, subject.blurb || ""),
              ])
            );
          });
          body.appendChild(list);
          body.appendChild(
            el("div", { className: "row wrap" }, [
              el("button", {
                className: "ghost-btn",
                type: "button",
                disabled: flow.busy,
                onClick: () => {
                  flow.step = "lean";
                  paint();
                },
              }, "Back"),
              el("button", {
                className: "ghost-btn",
                type: "button",
                disabled: flow.busy,
                onClick: () => loadSubjects(flow.subjects.map((s) => s.title)),
              }, "Shuffle subjects"),
            ])
          );
        } else if (flow.step === "scene" && flow.scene) {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("p", { className: "muted" }, `${flow.scene.subject} · ${flow.effort} effort · lean ${flow.lean}`),
              el("h2", {}, flow.scene.title),
              flow.scene.summary ? el("p", { className: "muted" }, flow.scene.summary) : null,
              el("p", { className: "playtime-scene-body" }, flow.scene.body),
            ])
          );

          body.appendChild(el("h3", {}, "Use this scene?"));
          body.appendChild(el("p", { className: "muted" }, "Rate it after play, or ask for something different."));
          const ratings = el("div", { className: "row wrap playtime-ratings" });
          for (let star = 1; star <= 5; star += 1) {
            ratings.appendChild(
              el("button", {
                className: "choice-btn",
                type: "button",
                disabled: flow.busy,
                onClick: () => rateScene(star),
              }, `${star}★`)
            );
          }
          body.appendChild(ratings);

          body.appendChild(
            el("button", {
              className: "primary-btn",
              type: "button",
              disabled: flow.busy,
              onClick: async () => {
                clearError();
                setBusy(true);
                try {
                  const sceneText = [
                    flow.scene.title || "",
                    flow.scene.summary || "",
                    flow.scene.body || "",
                  ].filter(Boolean).join("\n\n");
                  await api(`/dynamics/${dynamicId}/context`, {
                    method: "POST",
                    body: JSON.stringify({
                      subject: "scenes",
                      title: flow.scene.title || flow.subject || "Playtime scene",
                      text_content: sceneText,
                      notes: `Playtime scene · ${flow.effort || ""} effort · lean ${flow.lean || ""}`.trim(),
                      use_for_ai: true,
                    }),
                  });
                  const ok = el("p", { className: "muted" }, "Saved to Knowledge library as a scene.");
                  body.insertBefore(ok, ratings);
                } catch (err) {
                  showError(err.message);
                } finally {
                  setBusy(false);
                }
              },
            }, "Save to library (scene)")
          );

          const rejectNote = el("textarea", {
            placeholder: "Optional note for a different scene (e.g. less intensity, more teasing)…",
          });
          body.appendChild(el("label", {}, ["Not into this scene", rejectNote]));
          body.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              disabled: flow.busy,
              onClick: () => rejectAndRetry(rejectNote.value.trim()),
            }, "Not into scene — try something different")
          );
          body.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              disabled: flow.busy,
              onClick: () => {
                flow.step = "subjects";
                flow.scene = null;
                paint();
              },
            }, "Pick a different subject")
          );
        } else if (flow.step === "done") {
          body.appendChild(
            el("div", { className: "card stack" }, [
              el("h2", {}, "Nice"),
              el("p", {}, flow.doneMessage || "Rating saved."),
              el("button", {
                className: "primary-btn",
                type: "button",
                onClick: () => {
                  flow.step = "effort";
                  flow.effort = null;
                  flow.lean = null;
                  flow.subjects = [];
                  flow.subject = null;
                  flow.scene = null;
                  flow.doneMessage = "";
                  paint();
                },
              }, "Build another scene"),
            ])
          );
        }

        if (you?.role === "submissive") {
          body.appendChild(
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => navigate(`/dynamic/${dynamicId}/acts`),
            }, status.active_act_id ? "View active act" : "Request act of submission")
          );
        }

        body.appendChild(error);
        body.appendChild(
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: () => navigate(`/dynamic/${dynamicId}/assistant`),
          }, "Back to Playtime")
        );
      }

      const stack = el("div", { className: "stack" }, [body]);
      viewEl.replaceChildren(stack);
      paint();
      updateBottomNav();
    })
    .catch((err) => viewEl.replaceChildren(el("p", { className: "error" }, err.message)));
}

function renderInterview(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading interview..."));
  Promise.all([api(`/dynamics/${dynamicId}/interview`), loadDynamic(dynamicId)])
    .then(([interview]) => {
      const chatLog = el("div", { className: "chat-log" });
      const error = el("div", { className: "error hidden" });
      const input = el("textarea", {
        placeholder: interview.completed
          ? "Add or adjust anything — the summary updates when you send"
          : "Type your answer...",
      });
      const sendBtn = el("button", { className: "primary-btn", type: "button" }, "Send");
      const completeBtn = el(
        "button",
        { className: "ghost-btn", type: "button" },
        interview.completed ? "Refresh summary" : "Mark interview complete"
      );

      function paintMessages(messages) {
        chatLog.replaceChildren(
          ...messages.map((msg) =>
            el("div", { className: `chat-bubble ${msg.role}` }, msg.content)
          )
        );
        chatLog.scrollTop = chatLog.scrollHeight;
      }

      paintMessages(interview.messages);

      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Dynamic interview"),
        el("p", { className: "muted" }, "Private Q&A so the AI learns what you want — and what to avoid — in this dynamic. You can always come back and add more."),
      ]);

      if (interview.completed) {
        stack.appendChild(
          el("div", { className: "card stack" }, [
            el("p", { className: "pill ok" }, "Interview complete"),
            el("p", {}, interview.summary || "Summary saved."),
            el("p", { className: "muted" }, "Keep chatting below anytime to adjust or add context."),
          ])
        );
      }

      stack.appendChild(el("div", { className: "card" }, [chatLog]));

      if (!interview.message_count) {
        stack.appendChild(
          el("button", {
            className: "primary-btn",
            onClick: async () => {
              try {
                await api(`/dynamics/${dynamicId}/interview/start`, { method: "POST" });
                renderInterview(dynamicId);
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Begin interview")
        );
      } else {
        stack.appendChild(input);
        stack.appendChild(sendBtn);
        sendBtn.addEventListener("click", async () => {
          if (!input.value.trim()) return;
          error.classList.add("hidden");
          sendBtn.disabled = true;
          completeBtn.disabled = true;
          try {
            const updated = await api(`/dynamics/${dynamicId}/interview/reply`, {
              method: "POST",
              body: JSON.stringify({ message: input.value.trim() }),
            });
            input.value = "";
            if (updated.completed !== interview.completed || updated.summary !== interview.summary) {
              renderInterview(dynamicId);
            } else {
              paintMessages(updated.messages);
            }
          } catch (err) {
            error.textContent = err.message;
            error.classList.remove("hidden");
          } finally {
            sendBtn.disabled = false;
            completeBtn.disabled = false;
          }
        });

        if (interview.can_mark_complete || interview.completed) {
          stack.appendChild(
            el("p", { className: "muted" }, interview.completed
              ? "Or regenerate the saved summary from the full conversation."
              : "Enough answers to finish? Mark complete when you're ready — the AI also finishes on its own when it has enough.")
          );
          stack.appendChild(completeBtn);
          completeBtn.addEventListener("click", async () => {
            error.classList.add("hidden");
            completeBtn.disabled = true;
            sendBtn.disabled = true;
            try {
              await api(`/dynamics/${dynamicId}/interview/complete`, { method: "POST" });
              renderInterview(dynamicId);
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            } finally {
              completeBtn.disabled = false;
              sendBtn.disabled = false;
            }
          });
        }
      }

      stack.appendChild(error);
      stack.appendChild(
        el("button", {
          className: "ghost-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}`),
        }, "Back to dynamic")
      );
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderContext(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading context library..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/context`),
    api(`/dynamics/${dynamicId}/context/categories`),
    loadDynamic(dynamicId),
  ])
    .then(([links, categories]) => {
      const error = el("div", { className: "error hidden" });
      const status = el("p", { className: "muted" });
      const title = el("input", { placeholder: "Title" });
      const textBody = el("textarea", {
        placeholder: "Paste text, or upload a file below (.txt, .md, .csv, .json, .html, .pdf, .docx)",
        rows: "5",
      });
      const subject = el("select");
      categories.forEach((cat) => {
        subject.appendChild(el("option", { value: cat.id }, cat.label));
      });
      const useForAi = el("input", { type: "checkbox", checked: true });
      const partnerVisible = el("input", { type: "checkbox", checked: true });
      const fileInput = el("input", {
        type: "file",
        accept: ".txt,.md,.csv,.json,.html,.htm,.pdf,.docx,text/plain,text/markdown,text/csv,application/json,text/html,application/pdf",
        className: "hidden",
      });

      const list = el("div", { className: "stack" });
      function paintLinks(items) {
        list.replaceChildren();
        if (!items.length) {
          list.appendChild(el("p", { className: "muted" }, "No files yet."));
          return;
        }
        items.forEach((link) => {
          const subLabel =
            categories.find((c) => c.id === (link.subject || link.category))?.label
            || link.subject
            || link.category;
          if (link.is_private_to_others) {
            list.appendChild(
              el("div", { className: "card stack" }, [
                el("div", { className: "row wrap" }, [
                  el("strong", {}, link.title || "Private file"),
                  el("span", { className: "pill" }, "🔒 Private"),
                ]),
                el("p", { className: "muted" }, "This file is private to its author."),
              ])
            );
            return;
          }
          const aiToggle = el("input", { type: "checkbox" });
          aiToggle.checked = link.use_for_ai !== false;
          aiToggle.addEventListener("change", async () => {
            try {
              await api(`/dynamics/${dynamicId}/context/${link.id}`, {
                method: "PATCH",
                body: JSON.stringify({ use_for_ai: aiToggle.checked }),
              });
              status.textContent = "Updated AI toggle.";
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
              aiToggle.checked = !aiToggle.checked;
            }
          });
          const visibleToggle = el("input", { type: "checkbox" });
          visibleToggle.checked = link.partner_visible !== false;
          visibleToggle.addEventListener("change", async () => {
            try {
              await api(`/dynamics/${dynamicId}/context/${link.id}`, {
                method: "PATCH",
                body: JSON.stringify({ partner_visible: visibleToggle.checked }),
              });
              status.textContent = "Updated partner visibility.";
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
              visibleToggle.checked = !visibleToggle.checked;
            }
          });
          list.appendChild(
            el("div", { className: "card stack" }, [
              el("div", { className: "row wrap" }, [
                el("strong", {}, link.title),
                el("span", { className: "pill" }, subLabel),
              ]),
              link.filename ? el("p", { className: "muted" }, link.filename) : null,
              link.text_preview ? el("p", { className: "muted" }, link.text_preview) : null,
              link.notes ? el("p", { className: "muted" }, link.notes) : null,
              el("label", { className: "checkbox-label" }, [aiToggle, " Use for AI"]),
              el("label", { className: "checkbox-label" }, [visibleToggle, " Visible to partner"]),
              el("button", {
                className: "ghost-btn",
                onClick: async () => {
                  await api(`/dynamics/${dynamicId}/context/${link.id}`, { method: "DELETE" });
                  renderContext(dynamicId);
                },
              }, "Remove"),
            ])
          );
        });
      }
      paintLinks(links);

      async function uploadFile(file) {
        if (!file) return;
        error.classList.add("hidden");
        const body = new FormData();
        body.append("file", file);
        body.append("subject", subject.value);
        body.append("title", title.value || file.name || "Upload");
        body.append("notes", "");
        body.append("use_for_ai", useForAi.checked ? "true" : "false");
        body.append("partner_visible", partnerVisible.checked ? "true" : "false");
        const token = state.token;
        const res = await fetch(`${API}/dynamics/${dynamicId}/context/upload`, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || data.message || "Upload failed");
        renderContext(dynamicId);
      }

      fileInput.addEventListener("change", async () => {
        try {
          await uploadFile(fileInput.files?.[0]);
        } catch (err) {
          error.textContent = err.message;
          error.classList.remove("hidden");
        } finally {
          fileInput.value = "";
        }
      });

      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Knowledge & context"),
        el("p", { className: "muted" }, "Upload text files for the assistant and toggle what is shared with AI. Subjects: stories, scenes, and other."),
        status,
        el("div", { className: "card stack" }, [
          el("h2", {}, "File library"),
          el("label", {}, ["Subject", subject]),
          el("label", {}, ["Title", title]),
          el("label", {}, ["Paste text (optional)", textBody]),
          el("label", { className: "checkbox-label" }, [useForAi, " Use for AI"]),
          el("label", { className: "checkbox-label" }, [partnerVisible, " Visible to partner"]),
          el("div", { className: "row wrap" }, [
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: () => fileInput.click(),
            }, "Upload file"),
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                try {
                  if (!title.value.trim() && !textBody.value.trim()) {
                    throw new Error("Add a title and paste text, or upload a file.");
                  }
                  await api(`/dynamics/${dynamicId}/context`, {
                    method: "POST",
                    body: JSON.stringify({
                      subject: subject.value,
                      title: title.value.trim() || "Pasted note",
                      text_content: textBody.value,
                      notes: "",
                      use_for_ai: useForAi.checked,
                      partner_visible: partnerVisible.checked,
                    }),
                  });
                  title.value = "";
                  textBody.value = "";
                  renderContext(dynamicId);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Save pasted text"),
          ]),
          fileInput,
        ]),
        list,
        error,
        el("button", {
          className: "ghost-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}`),
        }, "Back to dynamic"),
      ]);
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

/** Context flags used to scope what AI assist can see (journal assist / scene builder). */
const JOURNAL_CONTEXT_FLAG_LABELS = {
  journals: "My journal entries",
  stories: "Stories",
  scenes: "Scene inspiration",
  agreements: "Ground rules & agreements",
  tracking: "Tracking history",
};

function buildContextFlagsMenu(flags) {
  const checks = {};
  const menu = el("div", { className: "card stack context-flags-menu hidden" }, [
    el("strong", {}, "AI context"),
    el("p", { className: "muted" }, "Choose what this assist request can read."),
  ]);
  Object.entries(JOURNAL_CONTEXT_FLAG_LABELS).forEach(([key, label]) => {
    const box = el("input", { type: "checkbox" });
    box.checked = !!flags[key];
    box.addEventListener("change", () => {
      flags[key] = box.checked;
    });
    checks[key] = box;
    menu.appendChild(el("label", { className: "checkbox-label" }, [box, ` ${label}`]));
  });
  const toggleBtn = el("button", {
    type: "button",
    className: "ghost-btn hub-features-btn",
    title: "AI context",
    "aria-label": "AI context",
    onClick: () => menu.classList.toggle("hidden"),
  }, "☰ AI context");
  return { toggleBtn, menu, checks };
}

function renderJournal(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading journal..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/journal`).catch(() => []),
    loadDynamic(dynamicId),
  ])
    .then(([journals]) => {
      const dynamic = state.currentDynamic;
      const you = dynamic?.partners?.find((p) => p.is_you);
      const isDom = you?.role === "dominant";
      const error = el("div", { className: "error hidden" });
      const status = el("p", { className: "muted" });

      const jTitle = el("input", { placeholder: "Journal title" });
      const jBody = el("textarea", { placeholder: "Write freely…", rows: "6" });
      const jAi = el("input", { type: "checkbox", checked: true });
      const jVisible = el("input", { type: "checkbox", checked: true });
      const assistPrompt = el("input", { placeholder: "e.g. Expand this into a reflective entry" });

      const contextFlags = { journals: true, stories: false, scenes: false, agreements: false, tracking: false };
      const { toggleBtn: contextToggleBtn, menu: contextMenu } = buildContextFlagsMenu(contextFlags);

      const list = el("div", { className: "stack" });
      function paintJournals(items) {
        list.replaceChildren();
        if (!items.length) {
          list.appendChild(el("p", { className: "muted" }, "No journal entries yet."));
          return;
        }
        items.forEach((entry) => {
          const card = el("div", { className: "card stack" }, [
            el("div", { className: "row wrap" }, [
              el("strong", {}, entry.title || (entry.is_private_to_others ? "Private entry" : "Untitled")),
              el("span", { className: "muted" }, entry.author_display_name),
              entry.is_private_to_others ? el("span", { className: "pill" }, "🔒 Private") : null,
            ]),
          ]);
          if (entry.is_private_to_others) {
            card.appendChild(el("p", { className: "muted" }, "This entry is private to its author."));
            list.appendChild(card);
            return;
          }

          card.appendChild(el("p", {}, (entry.body || "").slice(0, 400) || "(empty)"));
          if (entry.llm_assisted) card.appendChild(el("p", { className: "muted" }, "AI-assisted"));

          const toggleAi = el("input", { type: "checkbox" });
          toggleAi.checked = entry.use_for_ai !== false;
          toggleAi.addEventListener("change", async () => {
            try {
              await api(`/dynamics/${dynamicId}/journal/${entry.id}`, {
                method: "PATCH",
                body: JSON.stringify({ use_for_ai: toggleAi.checked }),
              });
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
              toggleAi.checked = !toggleAi.checked;
            }
          });
          const toggleVisible = el("input", { type: "checkbox" });
          toggleVisible.checked = entry.partner_visible !== false;
          toggleVisible.addEventListener("change", async () => {
            try {
              await api(`/dynamics/${dynamicId}/journal/${entry.id}`, {
                method: "PATCH",
                body: JSON.stringify({ partner_visible: toggleVisible.checked }),
              });
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
              toggleVisible.checked = !toggleVisible.checked;
            }
          });
          card.appendChild(el("label", { className: "checkbox-label" }, [toggleAi, " Use for AI"]));
          card.appendChild(el("label", { className: "checkbox-label" }, [toggleVisible, " Visible to partner"]));

          const reviewOut = el("p", { className: "muted hidden" });
          const rowBtns = el("div", { className: "row wrap" }, [
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                try {
                  await api(`/dynamics/${dynamicId}/journal/${entry.id}`, { method: "DELETE" });
                  renderJournal(dynamicId);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Delete"),
          ]);
          if (isDom) {
            rowBtns.appendChild(el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                reviewOut.classList.add("hidden");
                try {
                  const postToChat = confirm(
                    "Also post a short note to Chat so your partner knows you reviewed?"
                  );
                  const res = await api(`/dynamics/${dynamicId}/journal/${entry.id}/domme-review`, {
                    method: "POST",
                    body: JSON.stringify({ post_system_event: postToChat }),
                  });
                  reviewOut.textContent = res.summary;
                  reviewOut.classList.remove("hidden");
                  if (postToChat) status.textContent = "Review noted in Chat.";
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Domme review"));
          }
          card.appendChild(rowBtns);
          card.appendChild(reviewOut);
          list.appendChild(card);
        });
      }
      paintJournals(journals || []);

      const stack = el("div", { className: "stack" }, [
        buildHubHeader(dynamicId, "Journal", {
          subtitle: "Private writing with optional AI assist.",
          sectionFilter: "tracking",
        }),
        status,
        el("div", { className: "card stack" }, [
          el("h2", {}, "New entry"),
          el("label", {}, ["Title", jTitle]),
          el("label", {}, ["Entry", jBody]),
          el("label", { className: "checkbox-label" }, [jAi, " Use for AI"]),
          el("label", { className: "checkbox-label" }, [jVisible, " Visible to partner"]),
          el("div", { className: "row wrap" }, [contextToggleBtn]),
          contextMenu,
          el("label", {}, ["Assist prompt (optional)", assistPrompt]),
          el("div", { className: "row wrap" }, [
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                try {
                  if (!assistPrompt.value.trim()) throw new Error("Enter an assist prompt first.");
                  const res = await api(`/dynamics/${dynamicId}/journal/assist`, {
                    method: "POST",
                    body: JSON.stringify({
                      prompt: assistPrompt.value.trim(),
                      draft: jBody.value,
                      context_flags: contextFlags,
                    }),
                  });
                  if (res.text) jBody.value = res.text;
                  status.textContent = "Assist filled the draft — edit and save when ready.";
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Assist with AI"),
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                try {
                  await api(`/dynamics/${dynamicId}/journal`, {
                    method: "POST",
                    body: JSON.stringify({
                      title: jTitle.value.trim() || "Journal entry",
                      body: jBody.value,
                      use_for_ai: jAi.checked,
                      partner_visible: jVisible.checked,
                      llm_assisted: !!assistPrompt.value.trim() && !!jBody.value.trim(),
                    }),
                  });
                  jTitle.value = "";
                  jBody.value = "";
                  assistPrompt.value = "";
                  renderJournal(dynamicId);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Save journal entry"),
          ]),
        ]),
        list,
        error,
        el("button", {
          className: "ghost-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}/track`),
        }, "Back to Tracking"),
      ]);
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderPunishment(dynamicId, reportId = null) {
  const id = dynamicId || getActiveDynamicId();
  if (!id) {
    renderHome();
    return;
  }
  state.activeDynamicId = id;
  if (reportId) {
    renderPunishmentDetail(id, reportId);
    return;
  }
  setViewContent(el("p", { className: "muted" }, "Loading punishment…"));

  Promise.all([
    api(`/dynamics/${id}/punishments`),
    loadDynamic(id),
  ])
    .then(([data]) => {
      const you = state.currentDynamic?.partners?.find((p) => p.is_you);
      const isDom = !!(data.you_are_dominant || you?.role === "dominant");
      const error = el("div", { className: "error hidden" });
      const status = el("div", { className: "muted" });

      if (!isDom) {
        const actionInput = el("textarea", {
          rows: "4",
          placeholder: "What did you do that deserves punishment?",
          maxlength: "2000",
        });
        const waiting = el("div", { className: "stack" }, [el("h2", {}, "Waiting on keyholder")]);
        const mine = (data.reports || []).filter((r) => r.status === "pending").slice(0, 8);
        if (!mine.length) waiting.appendChild(el("p", { className: "muted" }, "Nothing pending."));
        else {
          mine.forEach((r) => {
            waiting.appendChild(el("div", { className: "card stack" }, [
              el("span", { className: "pill" }, "pending"),
              el("p", {}, r.action_text),
              el("p", { className: "muted" }, r.created_at ? new Date(r.created_at).toLocaleString() : ""),
            ]));
          });
        }
        setViewContent(el("div", { className: "stack" }, [
          el("h1", {}, "Confess"),
          el("p", { className: "muted" }, "Tell your keyholder what happened. They choose the punishment."),
          el("div", { className: "card stack" }, [
            el("label", { className: "stack" }, ["What happened?", actionInput]),
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                const action = actionInput.value.trim();
                if (!action) {
                  error.textContent = "Describe what happened.";
                  error.classList.remove("hidden");
                  return;
                }
                try {
                  await api(`/dynamics/${id}/punishments/self-report`, {
                    method: "POST",
                    body: JSON.stringify({ action }),
                  });
                  status.textContent = "Submitted. Your keyholder has been notified.";
                  actionInput.value = "";
                  renderPunishment(id);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Submit confession"),
          ]),
          status,
          error,
          waiting,
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: () => navigate(`/dynamic/${id}/track`),
          }, "Back to tracking"),
        ]));
        return;
      }

      const open = data.open || data.pending || [];
      const list = el("div", { className: "stack" }, [
        el("h1", {}, "Punishment dashboard"),
        el("p", { className: "muted" }, "Confessions waiting for you. Assign goal increases, then choose a follow-up."),
      ]);
      if (!open.length) {
        list.appendChild(el("p", { className: "muted" }, "No open confessions."));
      } else {
        open.forEach((r) => {
          list.appendChild(el("button", {
            className: "facet-row",
            type: "button",
            onClick: () => navigate(`/dynamic/${id}/punishment/${r.id}`),
          }, [
            el("span", { className: "facet-icon" }, "⚖"),
            el("span", { className: "facet-text" }, [
              el("span", { className: "facet-title" }, r.reporter_name || "Partner"),
              el("span", { className: "facet-subtitle" }, `${r.status} · ${(r.action_text || "").slice(0, 80)}`),
            ]),
          ]));
        });
      }
      const recent = el("div", { className: "stack" }, [el("h2", {}, "Recent")]);
      (data.reports || []).slice(0, 10).forEach((r) => {
        recent.appendChild(el("button", {
          className: "facet-row",
          type: "button",
          onClick: () => navigate(`/dynamic/${id}/punishment/${r.id}`),
        }, [
          el("span", { className: "facet-icon" }, "·"),
          el("span", { className: "facet-text" }, [
            el("span", { className: "facet-title" }, `${r.reporter_name} · ${r.status}`),
            el("span", { className: "facet-subtitle" }, (r.action_text || "").slice(0, 100)),
          ]),
        ]));
      });
      setViewContent(el("div", { className: "stack" }, [
        list,
        recent,
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => navigate(`/dynamic/${id}/track`),
        }, "Back to tracking"),
      ]));
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderPunishmentDetail(dynamicId, reportId) {
  const id = dynamicId;
  setViewContent(el("p", { className: "muted" }, "Loading confession…"));
  Promise.all([
    api(`/dynamics/${id}/punishments/${reportId}`),
    loadDynamic(id),
  ])
    .then(([data]) => {
      const report = data.report;
      const isDom = !!data.you_are_dominant;
      const error = el("div", { className: "error hidden" });
      const status = el("div", { className: "muted" });
      const followHost = el("div", { className: "stack" });
      const ideasHost = el("div", { className: "stack" });

      const stack = el("div", { className: "stack" }, [
        el("div", { className: "row wrap" }, [
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: () => navigate(`/dynamic/${id}/punishment`),
          }, "← Dashboard"),
          el("h1", {}, "Confession"),
        ]),
        el("div", { className: "card stack" }, [
          el("div", { className: "row wrap" }, [
            el("strong", {}, report.reporter_name || "Partner"),
            el("span", { className: "pill" }, report.status),
          ]),
          el("p", {}, report.action_text),
          el("p", { className: "muted" }, report.created_at ? new Date(report.created_at).toLocaleString() : ""),
        ]),
      ]);

      if ((report.applied || []).length) {
        stack.appendChild(el("div", { className: "card stack" }, [
          el("h2", {}, "Assigned so far"),
          ...report.applied.map((a) => el("p", {}, `${a.goal_title}: ${a.requirement_title} +${a.added} → ${a.new_target}`)),
        ]));
      }

      if (!isDom) {
        stack.appendChild(el("p", { className: "muted" }, "Your keyholder will decide the punishment."));
        stack.appendChild(error);
        setViewContent(stack);
        return;
      }

      const bumpInputs = new Map();
      const goalsCard = el("div", { className: "card stack" }, [
        el("h2", {}, "Assign to active goals"),
        el("p", { className: "muted" }, "Increase requirement targets for this confession."),
      ]);
      const goals = data.options?.goals || [];
      if (!goals.length) {
        goalsCard.appendChild(el("p", { className: "muted" }, "No active goals. Create some on Chastity first."));
      } else {
        goals.forEach((goal) => {
          const block = el("div", { className: "stack" }, [el("h3", {}, goal.title)]);
          (goal.requirements || []).forEach((req) => {
            const input = el("input", {
              type: "number",
              min: "0",
              step: req.kind === "duration" ? "0.5" : "1",
              value: "0",
              style: "max-width:6rem",
            });
            bumpInputs.set(`${goal.id}|${req.type}`, input);
            const suggests = el("div", { className: "row wrap" });
            (req.suggested_adds || [1, 2, 3]).forEach((n) => {
              suggests.appendChild(el("button", {
                type: "button",
                className: "ghost-btn",
                onClick: () => { input.value = String(n); },
              }, `+${n}`));
            });
            const unit = req.unit === "days" ? "days" : req.unit || "";
            block.appendChild(el("div", { className: "card stack" }, [
              el("strong", {}, req.title),
              el("p", { className: "muted" }, `Target ${req.target}${unit ? ` ${unit}` : ""}${req.current != null ? ` · now ${req.current}` : ""}`),
              el("label", { className: "row wrap" }, ["Add", input, unit || ""]),
              suggests,
            ]));
          });
          goalsCard.appendChild(block);
        });
      }

      function collectAdjustments() {
        const adjustments = [];
        bumpInputs.forEach((input, key) => {
          const add = parseFloat(input.value || "0");
          if (!add || add <= 0) return;
          const [goalId, requirementType] = key.split("|");
          adjustments.push({ goal_id: goalId, requirement_type: requirementType, add });
        });
        return adjustments;
      }

      function showFollowUp() {
        followHost.replaceChildren(
          el("div", { className: "card stack" }, [
            el("h2", {}, "Next step"),
            el("p", { className: "muted" }, "Goal values are saved. What do you want to do next?"),
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                status.textContent = "Asking assistant…";
                try {
                  const result = await api(`/dynamics/${id}/punishments/${reportId}/ideas`, { method: "POST" });
                  status.textContent = "Ideas ready.";
                  renderIdeas(result.ideas || []);
                } catch (err) {
                  status.textContent = "";
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Ask the assistant for additional task or punishment ideas"),
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: async () => {
                try {
                  await api(`/dynamics/${id}/punishments/${reportId}/remind`, { method: "POST" });
                  status.textContent = "Reminder set for tomorrow.";
                  setTimeout(() => navigate(`/dynamic/${id}/punishment`), 700);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Remind me tomorrow about this"),
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: async () => {
                try {
                  await api(`/dynamics/${id}/punishments/${reportId}/covered`, { method: "POST" });
                  status.textContent = "Marked as covered.";
                  refreshDomGoalHeader(id);
                  setTimeout(() => navigate(`/dynamic/${id}/punishment`), 700);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "I've got it covered"),
          ]),
        );
      }

      function renderIdeas(ideas) {
        ideasHost.replaceChildren();
        if (!ideas?.length) {
          ideasHost.appendChild(el("p", { className: "muted" }, "No ideas returned."));
          return;
        }
        ideasHost.appendChild(el("h2", {}, "Assistant ideas"));
        ideas.forEach((idea) => {
          const card = el("div", { className: "card stack" }, [
            el("strong", {}, idea.title || "Idea"),
            el("p", {}, idea.summary || ""),
          ]);
          if (idea.task_suggestion) {
            card.appendChild(el("p", { className: "muted" }, `Task: ${idea.task_suggestion}`));
          }
          if (idea.goal_id && idea.requirement_type && Number(idea.add) > 0) {
            card.appendChild(el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: async () => {
                try {
                  await api(`/dynamics/${id}/punishments/${reportId}/apply-idea`, {
                    method: "POST",
                    body: JSON.stringify({ idea_id: idea.id }),
                  });
                  status.textContent = "Idea applied to goals.";
                  refreshDomGoalHeader(id);
                  renderPunishmentDetail(id, reportId);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, `Also add +${idea.add} ${idea.requirement_type}`));
          }
          ideasHost.appendChild(card);
        });
      }

      if (report.status === "pending") {
        stack.appendChild(goalsCard);
        stack.appendChild(el("button", {
          className: "primary-btn",
          type: "button",
          onClick: async () => {
            error.classList.add("hidden");
            const adjustments = collectAdjustments();
            if (!adjustments.length) {
              error.textContent = "Choose at least one amount to add.";
              error.classList.remove("hidden");
              return;
            }
            try {
              const result = await api(`/dynamics/${id}/punishments/${reportId}/assign`, {
                method: "POST",
                body: JSON.stringify({ adjustments }),
              });
              status.textContent = `Assigned: ${(result.applied || []).map((a) => `${a.requirement_title} +${a.added}`).join(", ")}`;
              refreshDomGoalHeader(id);
              bumpInputs.forEach((input) => { input.value = "0"; });
              showFollowUp();
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Submit punishment values"));
      }

      if (report.needs_follow_up || report.status === "assigned" || report.status === "ideas" || report.status === "remind") {
        showFollowUp();
        if ((report.ideas || []).length) renderIdeas(report.ideas);
      }

      stack.appendChild(followHost);
      stack.appendChild(ideasHost);
      stack.appendChild(status);
      stack.appendChild(error);
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderFeelings(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading feelings wheel…"));
  const query = (() => {
    const q = location.hash.split("?")[1] || "";
    return new URLSearchParams(q);
  })();
  const contextParam = query.get("context") || "ad_hoc";
  const atParam = query.get("at");
  const fromParam = query.get("from") || "";
  const orgEntryId = query.get("org_entry_id") || null;
  const chastityLockupId = query.get("chastity_lockup_id") || null;
  const initialAt = atParam ? parseServerDate(atParam) : new Date();
  const initialLocal = !initialAt || Number.isNaN(initialAt.getTime())
    ? toLocalDatetimeValue()
    : toLocalDatetimeValue(initialAt);

  Promise.all([
    api(`/dynamics/${dynamicId}/feelings/wheel`),
    api(`/dynamics/${dynamicId}/feelings?limit=40`),
    api(`/dynamics/${dynamicId}/feelings/status`),
    loadDynamic(dynamicId),
  ])
    .then(([wheel, history, statusInfo]) => {
      const dynamic = state.currentDynamic;
      const you = dynamic?.partners?.find((p) => p.is_you);
      const error = el("div", { className: "error hidden" });
      /** @type {Map<string, {id:string,label:string,path:string,level:number,description:string}>} */
      const selected = new Map();
      const pathById = new Map();
      const wheelHost = el("div", { className: "feelings-wheel-host" });
      const logEl = el("pre", { className: "feelings-term-log" });
      const detailTitle = el("h3", { className: "feelings-detail-title" }, "Feeling");
      const detailPath = el("p", { className: "feelings-detail-path muted" }, "");
      const detailBody = el(
        "p",
        { className: "feelings-detail-body" },
        "Click any wedge to read about it. Click again to select or unselect."
      );
      const detailPanel = el("div", { className: "feelings-detail-panel" }, [
        detailTitle,
        detailPath,
        detailBody,
      ]);
      detailPanel.hidden = true;
      const WHEEL_CX = 280;
      const WHEEL_CY = 280;
      let rotationDeg = -90;
      /** @type {null | {x:number,y:number,startAngle:number,startRot:number,moved:boolean,emotionId:string|null,pointerId:number}} */
      let pointerState = null;
      let context = ["ad_hoc", "before_play", "after_play", "end_of_day"].includes(contextParam)
        ? contextParam
        : "ad_hoc";
      if (fromParam === "orgasm" || fromParam === "play") context = "after_play";
      if (fromParam === "chastity") context = "ad_hoc";

      const cores = wheel.cores || [];
      cores.forEach((core) => {
        pathById.set(core.id, {
          id: core.id,
          label: core.label,
          path: core.label,
          level: 1,
          description: core.description || "",
        });
        (core.mids || []).forEach((mid) => {
          pathById.set(mid.id, {
            id: mid.id,
            label: mid.label,
            path: `${core.label} › ${mid.label}`,
            level: 2,
            description: mid.description || "",
          });
          (mid.outers || []).forEach((outer) => {
            pathById.set(outer.id, {
              id: outer.id,
              label: outer.label,
              path: `${core.label} › ${mid.label} › ${outer.label}`,
              level: 3,
              description: outer.description || "",
            });
          });
        });
      });

      const whenInput = el("input", { type: "datetime-local", value: initialLocal });
      const whenLabel = el("span", { className: "feelings-when-label" }, "Now");
      function syncWhenLabel() {
        const iso = datetimeLocalToIso(whenInput.value);
        const d = iso ? new Date(iso) : new Date();
        const isNow = Math.abs(Date.now() - d.getTime()) < 90_000;
        whenLabel.textContent = isNow ? "Now" : d.toLocaleString();
      }
      syncWhenLabel();
      whenInput.addEventListener("change", syncWhenLabel);

      const whenPanel = el("div", { className: "feelings-when stack" }, [
        el("div", { className: "row wrap feelings-when-row" }, [
          el("strong", {}, "When"),
          whenLabel,
          el(
            "button",
            {
              type: "button",
              className: "ghost-btn",
              onClick: () => {
                whenInput.value = toLocalDatetimeValue();
                syncWhenLabel();
              },
            },
            "Now"
          ),
        ]),
        whenInput,
      ]);

      let showFeelings = true;
      let showDesires = true;
      try {
        const saved = JSON.parse(localStorage.getItem("ubetra-feelings-wheel-layers") || "null");
        if (saved && typeof saved === "object") {
          if (typeof saved.feelings === "boolean") showFeelings = saved.feelings;
          if (typeof saved.desires === "boolean") showDesires = saved.desires;
        }
      } catch (_) {
        /* ignore */
      }
      function persistLayers() {
        try {
          localStorage.setItem(
            "ubetra-feelings-wheel-layers",
            JSON.stringify({ feelings: showFeelings, desires: showDesires })
          );
        } catch (_) {
          /* ignore */
        }
      }
      function coreKind(core) {
        return core.kind === "desire" ? "desire" : "feeling";
      }
      function visibleCores() {
        return cores.filter((c) => {
          const kind = coreKind(c);
          return kind === "desire" ? showDesires : showFeelings;
        });
      }

      let hornyTouched = false;
      const hornyValueEl = el("strong", { className: "feelings-horny-value" }, "—");
      const hornyInput = el("input", {
        type: "range",
        min: "0",
        max: "10",
        step: "1",
        value: "0",
        className: "feelings-horny-range",
      });
      const clearHornyBtn = el(
        "button",
        {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            hornyTouched = false;
            hornyInput.value = "0";
            hornyValueEl.textContent = "—";
            refreshLog();
          },
        },
        "Clear"
      );
      hornyInput.addEventListener("input", () => {
        hornyTouched = true;
        hornyValueEl.textContent = `${hornyInput.value}/10`;
        refreshLog();
      });
      const hornyPanel = el("div", { className: "card stack feelings-horny" }, [
        el("div", { className: "row wrap" }, [
          el("strong", {}, "Horny level"),
          hornyValueEl,
          clearHornyBtn,
        ]),
        el("p", { className: "muted" }, "0 = none · 10 = max. Can be logged alone."),
        hornyInput,
      ]);

      const showFeelingsCb = el("input", { type: "checkbox" });
      showFeelingsCb.checked = showFeelings;
      const showDesiresCb = el("input", { type: "checkbox" });
      showDesiresCb.checked = showDesires;
      const wheelLayers = el("div", { className: "row wrap feelings-wheel-layers" }, [
        el("span", { className: "muted" }, "On the wheel:"),
        el("label", { className: "checkbox-label" }, [showFeelingsCb, " Feelings"]),
        el("label", { className: "checkbox-label" }, [showDesiresCb, " Desires"]),
      ]);

      let eventBanner = null;
      if (fromParam || orgEntryId || chastityLockupId) {
        const fromLabel =
          fromParam === "orgasm"
            ? "orgasm / play event"
            : fromParam === "chastity"
              ? "chastity event"
              : fromParam === "play"
                ? "play event"
                : "linked event";
        eventBanner = el(
          "p",
          { className: "feelings-event-banner" },
          `Logging feelings for this ${fromLabel} — timestamp is set just after it.`
        );
      }

      function refreshLog() {
        const lines = [];
        if (hornyTouched) lines.push(`Horny: ${hornyInput.value}/10`);
        if (selected.size) {
          lines.push(
            ...[...selected.values()]
              .sort((a, b) => a.path.localeCompare(b.path))
              .map((s) => s.path)
          );
        }
        logEl.textContent = lines.length ? lines.join("\n") : "(nothing selected yet)";
      }

      function hideDetail() {
        detailPanel.classList.remove("visible");
        detailPanel.hidden = true;
      }

      function showDetail(id) {
        const meta = pathById.get(id);
        if (!meta) return;
        detailTitle.textContent = meta.label;
        detailPath.textContent = meta.path;
        detailBody.textContent =
          meta.description ||
          "No description yet for this feeling — still useful as a precise label.";
        detailPanel.hidden = false;
        detailPanel.classList.add("visible");
      }

      function syncHighlights() {
        const SELECTED_BLUE = "#3B82F6";
        wheelHost.querySelectorAll("[data-emotion-id]").forEach((node) => {
          const id = node.getAttribute("data-emotion-id");
          const on = selected.has(id);
          node.classList.toggle("selected", on);
          node.setAttribute("fill", on ? SELECTED_BLUE : node.getAttribute("data-base-fill") || "#888");
          node.setAttribute(
            "opacity",
            on ? "1" : node.getAttribute("data-base-opacity") || "1"
          );
        });
      }

      function toggleEmotion(id) {
        const meta = pathById.get(id);
        if (!meta) return;
        if (selected.has(id)) {
          selected.delete(id);
          hideDetail();
        } else {
          selected.set(id, meta);
          showDetail(id);
        }
        refreshLog();
        syncHighlights();
      }

      function applyRotation() {
        const g = wheelHost.querySelector(".feelings-wheel-rot");
        if (g) g.setAttribute("transform", `rotate(${rotationDeg} ${WHEEL_CX} ${WHEEL_CY})`);
      }

      function paintWheel() {
        wheelHost.replaceChildren();
        const size = 560;
        const pad = 20;
        const cx = WHEEL_CX;
        const cy = WHEEL_CY;
        const R_HUB = 52;
        const R_CORE = 118;
        const R_MID = 178;
        const R_OUTER = 248;
        const SELECTED_BLUE = "#3B82F6";

        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", `${-pad} ${-pad} ${size + pad * 2} ${size + pad * 2}`);
        svg.setAttribute("class", "feelings-wheel-svg");
        svg.setAttribute("width", "100%");
        svg.setAttribute("aria-label", "Feelings wheel");

        const rot = document.createElementNS("http://www.w3.org/2000/svg", "g");
        rot.setAttribute("class", "feelings-wheel-rot");
        rot.setAttribute("transform", `rotate(${rotationDeg} ${cx} ${cy})`);

        function polar(r, a) {
          return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
        }
        function arcPath(r0, r1, a0, a1) {
          const span = a1 - a0;
          const large = span > Math.PI ? 1 : 0;
          const [x0, y0] = polar(r1, a0);
          const [x1, y1] = polar(r1, a1);
          const [x2, y2] = polar(r0, a1);
          const [x3, y3] = polar(r0, a0);
          return `M ${x0} ${y0} A ${r1} ${r1} 0 ${large} 1 ${x1} ${y1} L ${x2} ${y2} A ${r0} ${r0} 0 ${large} 0 ${x3} ${y3} Z`;
        }
        /** Labels always read center → outer along the ray (no left-half flip). */
        function labelAt(r, a0, a1, text, className) {
          const mid = (a0 + a1) / 2;
          const [tx, ty] = polar(r, mid);
          const deg = (mid * 180) / Math.PI;
          const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
          t.setAttribute("x", String(tx));
          t.setAttribute("y", String(ty));
          t.setAttribute("text-anchor", "middle");
          t.setAttribute("dominant-baseline", "middle");
          t.setAttribute("class", className);
          t.setAttribute("transform", `rotate(${deg} ${tx} ${ty})`);
          t.textContent = text;
          return t;
        }
        function addSeg(id, fill, opacity, r0, r1, a0, a1) {
          const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
          path.setAttribute("d", arcPath(r0, r1, a0, a1));
          path.setAttribute("class", "feelings-wheel-seg");
          path.setAttribute("data-emotion-id", id);
          path.setAttribute("data-base-fill", fill);
          path.setAttribute("data-base-opacity", String(opacity));
          const isOn = selected.has(id);
          path.setAttribute("fill", isOn ? SELECTED_BLUE : fill);
          path.setAttribute("opacity", isOn ? "1" : String(opacity));
          if (isOn) path.classList.add("selected");
          rot.appendChild(path);
        }

        const ringCores = visibleCores();
        const n = Math.max(1, ringCores.length);
        const coreSpan = (Math.PI * 2) / n;
        ringCores.forEach((core, i) => {
          const c0 = i * coreSpan;
          const c1 = c0 + coreSpan;
          const color = core.color || "#888";
          addSeg(core.id, color, 1, R_HUB, R_CORE, c0, c1);
          rot.appendChild(
            labelAt((R_HUB + R_CORE) / 2, c0, c1, core.label, "feelings-wheel-label")
          );

          const mids = core.mids || [];
          const midSpan = coreSpan / Math.max(1, mids.length);
          mids.forEach((mid, j) => {
            const m0 = c0 + j * midSpan;
            const m1 = m0 + midSpan;
            addSeg(mid.id, color, 0.78, R_CORE + 1, R_MID, m0, m1);
            rot.appendChild(
              labelAt((R_CORE + R_MID) / 2, m0, m1, mid.label, "feelings-wheel-label-mid")
            );

            const outers = mid.outers || [];
            const outerSpan = midSpan / Math.max(1, outers.length);
            outers.forEach((outer, k) => {
              const o0 = m0 + k * outerSpan;
              const o1 = o0 + outerSpan;
              addSeg(outer.id, color, 0.55, R_MID + 1, R_OUTER, o0, o1);
              rot.appendChild(
                labelAt((R_MID + R_OUTER) / 2, o0, o1, outer.label, "feelings-wheel-label-sm")
              );
            });
          });
        });

        svg.appendChild(rot);

        const hub = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        hub.setAttribute("cx", String(cx));
        hub.setAttribute("cy", String(cy));
        hub.setAttribute("r", String(R_HUB - 2));
        hub.setAttribute("fill", "#141414");
        hub.setAttribute("stroke", "#333");
        hub.setAttribute("class", "feelings-wheel-hub-disk");
        svg.appendChild(hub);
        const hubText = document.createElementNS("http://www.w3.org/2000/svg", "text");
        hubText.setAttribute("x", String(cx));
        hubText.setAttribute("y", String(cy));
        hubText.setAttribute("text-anchor", "middle");
        hubText.setAttribute("dominant-baseline", "middle");
        hubText.setAttribute("class", "feelings-wheel-hub");
        hubText.textContent = "Feel";
        svg.appendChild(hubText);

        function pointerAngle(clientX, clientY) {
          const rect = svg.getBoundingClientRect();
          const x = clientX - (rect.left + rect.width / 2);
          const y = clientY - (rect.top + rect.height / 2);
          return (Math.atan2(y, x) * 180) / Math.PI;
        }

        function emotionFromEvent(e) {
          const node =
            e.target && e.target.closest
              ? e.target.closest("[data-emotion-id]")
              : null;
          return node ? node.getAttribute("data-emotion-id") : null;
        }

        svg.addEventListener("pointerdown", (e) => {
          if (e.button !== 0 && e.pointerType === "mouse") return;
          e.preventDefault();
          try {
            svg.setPointerCapture(e.pointerId);
          } catch (_) {
            /* ignore */
          }
          pointerState = {
            x: e.clientX,
            y: e.clientY,
            startAngle: pointerAngle(e.clientX, e.clientY),
            startRot: rotationDeg,
            moved: false,
            emotionId: emotionFromEvent(e),
            pointerId: e.pointerId,
          };
          svg.classList.add("dragging");
        });
        svg.addEventListener("pointermove", (e) => {
          if (!pointerState || pointerState.pointerId !== e.pointerId) return;
          const dx = e.clientX - pointerState.x;
          const dy = e.clientY - pointerState.y;
          // Pixel threshold — angular threshold broke mouse clicks near the hub
          if (!pointerState.moved && dx * dx + dy * dy > 64) {
            pointerState.moved = true;
          }
          if (pointerState.moved) {
            const ang = pointerAngle(e.clientX, e.clientY);
            rotationDeg = pointerState.startRot + (ang - pointerState.startAngle);
            applyRotation();
          }
        });
        function endPointer(e) {
          if (!pointerState || pointerState.pointerId !== e.pointerId) return;
          const wasDrag = pointerState.moved;
          const id = pointerState.emotionId;
          pointerState = null;
          svg.classList.remove("dragging");
          try {
            svg.releasePointerCapture(e.pointerId);
          } catch (_) {
            /* ignore */
          }
          if (!wasDrag && id) toggleEmotion(id);
        }
        svg.addEventListener("pointerup", endPointer);
        svg.addEventListener("pointercancel", endPointer);

        wheelHost.appendChild(svg);
      }

      const historyCard = el("div", { className: "card stack" }, [el("h2", {}, "Recent")]);
      if (!history.length) {
        historyCard.appendChild(el("p", { className: "muted" }, "No check-ins yet."));
      } else {
        history.forEach((row) => {
          const labels = (row.selections || [])
            .map((s) => s.path || s.label)
            .filter(Boolean)
            .join(", ");
          const horny =
            row.horny_level != null && row.horny_level !== undefined
              ? `Horny ${row.horny_level}/10`
              : "";
          const detail = [horny, labels].filter(Boolean).join(" · ") || "—";
          historyCard.appendChild(
            el("div", { className: "stack" }, [
              el(
                "strong",
                {},
                `${row.for_display_name} · ${row.context} · ${formatLocalDateTime(row.occurred_at)}`
              ),
              el("p", { className: "muted" }, detail),
            ])
          );
        });
      }

      const settingsCard = el("div", { className: "card stack" });
      if (you?.role === "dominant") {
        const mode = el("select");
        [
          ["soft", "Soft reminders"],
          ["hard", "Hard gates where it makes sense"],
        ].forEach(([v, l]) => {
          const o = el("option", { value: v }, l);
          if (v === (statusInfo.prompt_mode || "soft")) o.selected = true;
          mode.appendChild(o);
        });
        const eod = el("input", { type: "checkbox" });
        eod.checked = !!statusInfo.require_end_of_day;
        settingsCard.append(
          el("h2", {}, "Feelings prompts"),
          el("label", {}, ["Mode", mode]),
          el("label", { className: "checkbox-label" }, [eod, " Nudge for end-of-day check-in"]),
          el(
            "button",
            {
              className: "ghost-btn",
              type: "button",
              onClick: async () => {
                try {
                  await api(`/dynamics/${dynamicId}/feelings/settings`, {
                    method: "PUT",
                    body: JSON.stringify({
                      prompt_mode: mode.value,
                      require_end_of_day: eod.checked,
                    }),
                  });
                  renderFeelings(dynamicId);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            },
            "Save prompt settings"
          )
        );
      } else if (statusInfo.needs_end_of_day) {
        settingsCard.appendChild(
          el("p", { className: "muted" }, "Reminder: log end-of-day feelings when you can.")
        );
      }

      paintWheel();
      refreshLog();

      const wheelStage = el("div", { className: "feelings-stage" }, [
        el("div", { className: "feelings-wheel-wrap" }, [
          wheelHost,
          detailPanel,
          el("div", { className: "feelings-wheel-controls" }, [
            el(
              "button",
              {
                className: "ghost-btn",
                type: "button",
                onClick: () => {
                  rotationDeg -= 20;
                  applyRotation();
                },
              },
              "↺"
            ),
            el(
              "button",
              {
                className: "ghost-btn",
                type: "button",
                onClick: () => {
                  rotationDeg += 20;
                  applyRotation();
                },
              },
              "↻"
            ),
            el(
              "button",
              {
                className: "ghost-btn",
                type: "button",
                onClick: () => {
                  rotationDeg = -90;
                  applyRotation();
                },
              },
              "Reset"
            ),
          ]),
        ]),
      ]);
      const termCard = el("div", { className: "feelings-term" }, [
        el("div", { className: "feelings-term-bar" }, "to submit"),
        logEl,
      ]);
      function syncWheelVisibility() {
        showFeelings = !!showFeelingsCb.checked;
        showDesires = !!showDesiresCb.checked;
        persistLayers();
        const showWheel = showFeelings || showDesires;
        wheelStage.hidden = !showWheel;
        if (showWheel) paintWheel();
        else {
          wheelHost.replaceChildren();
          hideDetail();
        }
      }
      showFeelingsCb.addEventListener("change", syncWheelVisibility);
      showDesiresCb.addEventListener("change", syncWheelVisibility);
      syncWheelVisibility();

      setViewContent(
        el("div", { className: "stack feelings-page" }, [
          el("h1", {}, "Feelings & desires"),
          el(
            "p",
            { className: "muted feelings-hint" },
            "Set a horny level anytime. Turn Feelings / Desires on to pick wedges — drag to rotate, click to select."
          ),
          statusInfo.needs_end_of_day
            ? el("p", { className: "muted" }, "End-of-day check-in still needed today.")
            : null,
          eventBanner,
          whenPanel,
          hornyPanel,
          wheelLayers,
          wheelStage,
          termCard,
          error,
          el(
            "button",
            {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                if (!selected.size && !hornyTouched) {
                  error.textContent = "Select at least one feeling/desire or set a horny level.";
                  error.classList.remove("hidden");
                  return;
                }
                try {
                  await api(`/dynamics/${dynamicId}/feelings`, {
                    method: "POST",
                    body: JSON.stringify({
                      context,
                      emotion_ids: [...selected.keys()],
                      horny_level: hornyTouched ? Number(hornyInput.value) : null,
                      occurred_at: datetimeLocalToIso(whenInput.value) || new Date().toISOString(),
                      org_entry_id: orgEntryId,
                      chastity_lockup_id: chastityLockupId,
                    }),
                  });
                  renderFeelings(dynamicId);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            },
            "Submit"
          ),
          settingsCard.childNodes.length ? settingsCard : null,
          historyCard,
          el(
            "button",
            {
              className: "ghost-btn",
              type: "button",
              onClick: () => navigate(`/dynamic/${dynamicId}/track`),
            },
            "Back to tracking"
          ),
        ])
      );
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderCumulativeOrgasmChart(series, partners) {
  const wrap = el("div", { className: "cum-chart-wrap" });
  if (!series?.length || !partners?.length) {
    wrap.appendChild(el("p", { className: "muted" }, "No orgasm data in the last 30 days."));
    return wrap;
  }
  const w = 360;
  const h = 180;
  const pad = { t: 12, r: 12, b: 28, l: 28 };
  const maxY = Math.max(1, ...series.flatMap((pt) => Object.values(pt.by_partner || {})));
  const colors = ["var(--accent)", "#7eb8a8", "#c97b4a", "#8a9bb8"];
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "cum-line-chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Cumulative orgasms over 30 days");

  function xAt(i) {
    return pad.l + (i / Math.max(1, series.length - 1)) * (w - pad.l - pad.r);
  }
  function yAt(v) {
    return pad.t + (1 - v / maxY) * (h - pad.t - pad.b);
  }

  // baseline
  const base = document.createElementNS(svgNS, "line");
  base.setAttribute("x1", String(pad.l));
  base.setAttribute("x2", String(w - pad.r));
  base.setAttribute("y1", String(h - pad.b));
  base.setAttribute("y2", String(h - pad.b));
  base.setAttribute("class", "cum-axis");
  svg.appendChild(base);

  partners.forEach((partner, pIdx) => {
    const pts = series.map((pt, i) => {
      const v = Number(pt.by_partner?.[partner.membership_id] || 0);
      return `${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`;
    }).join(" ");
    const poly = document.createElementNS(svgNS, "polyline");
    poly.setAttribute("points", pts);
    poly.setAttribute("fill", "none");
    poly.setAttribute("stroke", colors[pIdx % colors.length]);
    poly.setAttribute("stroke-width", "2.5");
    poly.setAttribute("stroke-linejoin", "round");
    poly.setAttribute("stroke-linecap", "round");
    svg.appendChild(poly);
  });

  wrap.appendChild(svg);
  const legend = el("div", { className: "history-legend" });
  partners.forEach((p, idx) => {
    legend.appendChild(el("span", {
      className: `history-legend-item p${idx}`,
      style: `border-color: ${colors[idx % colors.length]}`,
    }, p.name));
  });
  wrap.appendChild(legend);
  return wrap;
}

function renderTracking(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading tracking..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/tracking/stats`),
    api(`/dynamics/${dynamicId}/tracking`),
    loadDynamic(dynamicId),
    api(`/dynamics/${dynamicId}/tags`).catch(() => ({ presets: [] })),
    api(`/dynamics/${dynamicId}/tracking-prefs`).catch(() => ({ fields: [], metrics: [] })),
  ])
    .then(([stats, entries, , tagData, prefs]) => {
      const dynamic = state.currentDynamic;
      const error = el("div", { className: "error hidden" });
      const fieldOn = Object.fromEntries((prefs.fields || []).map((f) => [f.id, f.enabled]));
      const metricOn = Object.fromEntries((prefs.metrics || []).map((m) => [m.id, m.enabled]));
      const on = (id, fallback = true) => (id in fieldOn ? fieldOn[id] : fallback);
      const metric = (id, fallback = true) => (id in metricOn ? metricOn[id] : fallback);

      const playPresets = trackingTagPresets("play");
      const partners = dynamic.partners || [];

      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Sex & orgasm tracking"),
        el("p", { className: "muted" }, stats.recent_orgasm_label || "No orgasms in the last 7 days"),
        el("p", { className: "muted" }, "Select who climaxed. Session times are shared; satisfaction, edging, and orgasm tags are per partner."),
      ]);

      if (metric("partner_chart_90d")) {
        stack.appendChild(el("div", { className: "card stack" }, [
          el("h2", {}, "Orgasm breakdown (30 days cumulative)"),
          renderCumulativeOrgasmChart(stats.cumulative_30d || [], stats.partners || []),
        ]));
      }

      const partnerChecks = partners.map((p, idx) => {
        const input = el("input", {
          type: "checkbox",
          ...(idx === 0 ? { checked: "true" } : {}),
        });
        return { partner: p, input };
      });
      const partnerSelectRow = el("div", { className: "stack" }, [
        el("strong", {}, "Log for"),
        el("div", { className: "row wrap" }, partnerChecks.map(({ partner, input }) =>
          el("label", { className: "checkbox-label" }, [input, ` ${partner.display_name}`])
        )),
      ]);

      const eventType = el("select");
      [
        ["orgasm", "Orgasm"],
        ["no_orgasm", "No orgasm (play)"],
      ].forEach(([value, label]) => {
        eventType.appendChild(el("option", { value }, label));
      });
      const sessionStart = el("input", { type: "datetime-local", value: toLocalDatetimeValue() });
      const sessionEnd = el("input", { type: "datetime-local" });
      const locationInput = el("input", { type: "text", maxlength: "120", placeholder: "e.g. home, hotel" });
      const initiatedBy = el("select");
      initiatedBy.appendChild(el("option", { value: "" }, "—"));
      partners.forEach((p) => {
        initiatedBy.appendChild(el("option", { value: p.id }, p.display_name));
      });
      const protection = el("select");
      [
        ["", "—"],
        ["protected", "Protected"],
        ["unprotected", "Unprotected"],
        ["n_a", "N/A"],
      ].forEach(([value, label]) => protection.appendChild(el("option", { value }, label)));
      const notes = el("textarea", { rows: "3", placeholder: "Optional notes" });
      const notesPrivate = el("input", { type: "checkbox" });
      const playTagPicker = buildTagPicker(playPresets);
      const playForPartner = el("select");
      partners.forEach((p) => {
        playForPartner.appendChild(el("option", { value: p.id }, p.display_name));
      });
      const playFields = el("div", { className: "stack hidden" }, [
        el("p", { className: "muted" }, "No orgasm (play) for the sub counts as a denial toward goals. Optional tags below are just notes."),
        el("label", {}, ["Partner", playForPartner]),
        el("label", {}, ["Play tags (optional)", playTagPicker.row, playTagPicker.custom]),
      ]);
      const orgasmPartnerHost = el("div", { className: "stack" });
      let partnerPanels = [];

      function selectedOrgasmPartners() {
        return partnerChecks.filter((c) => c.input.checked).map((c) => c.partner);
      }

      function rebuildPartnerPanels() {
        const selected = selectedOrgasmPartners();
        const multi = selected.length > 1;
        partnerPanels = selected.map((p) => buildPartnerOrgasmPanel(p, {
          showContextRadio: !multi,
          open: true,
          collapsible: multi,
        }));
        if (!partnerPanels.length) {
          orgasmPartnerHost.replaceChildren(
            el("p", { className: "muted" }, "Select at least one partner above.")
          );
          return;
        }
        orgasmPartnerHost.replaceChildren(...partnerPanels.map((panel) => panel.wrap));
      }

      function refreshTrackingFields() {
        const isOrgasm = eventType.value === "orgasm";
        partnerSelectRow.classList.toggle("hidden", !isOrgasm);
        orgasmPartnerHost.classList.toggle("hidden", !isOrgasm);
        playFields.classList.toggle("hidden", isOrgasm);
        if (!isOrgasm) {
          const sub = partners.find((p) => p.role === "submissive");
          if (sub) playForPartner.value = sub.id;
        } else {
          rebuildPartnerPanels();
        }
      }
      eventType.addEventListener("change", refreshTrackingFields);
      partnerChecks.forEach(({ input }) => input.addEventListener("change", () => {
        if (eventType.value === "orgasm") rebuildPartnerPanels();
      }));

      const formCard = el("div", { className: "card stack" }, [
        partnerSelectRow,
        el("label", {}, ["Event", eventType]),
        el("label", {}, ["Session start", sessionStart]),
      ]);
      if (on("session_end")) formCard.appendChild(el("label", {}, ["Session end (optional)", sessionEnd]));
      if (on("location")) formCard.appendChild(el("label", {}, ["Location", locationInput]));
      if (on("initiated_by")) formCard.appendChild(el("label", {}, ["Who initiated", initiatedBy]));
      if (on("protection")) formCard.appendChild(el("label", {}, ["Protection", protection]));
      formCard.appendChild(orgasmPartnerHost);
      formCard.appendChild(playFields);
      if (on("notes")) {
        formCard.appendChild(el("label", { className: "stack" }, ["Notes", notes]));
        if (on("notes_private", false)) {
          formCard.appendChild(el("label", { className: "checkbox-label" }, [
            notesPrivate,
            " Private notes (logger, partner, and keyholder only)",
          ]));
        }
      }
      formCard.appendChild(el("button", {
        className: "primary-btn",
        onClick: async () => {
          error.classList.add("hidden");
          try {
            const shared = {
              event_type: eventType.value,
              occurred_at: datetimeLocalToIso(sessionStart.value) || new Date().toISOString(),
            };
            if (on("session_end") && sessionEnd.value) shared.ended_at = datetimeLocalToIso(sessionEnd.value);
            if (on("location") && locationInput.value.trim()) shared.location = locationInput.value.trim();
            if (on("initiated_by") && initiatedBy.value) shared.initiated_by_membership_id = initiatedBy.value;
            if (on("protection") && protection.value) shared.protection = protection.value;
            if (on("notes")) {
              shared.notes = notes.value.trim();
              if (on("notes_private", false)) shared.notes_private = notesPrivate.checked;
            }

            let entry;
            if (eventType.value === "orgasm") {
              if (!partnerPanels.length) throw new Error("Select at least one partner.");
              const payloads = partnerPanels.map((panel) => panel.getPayload());
              for (const part of payloads) {
                if (!part.orgasms.length) {
                  const name = partners.find((p) => p.id === part.for_membership_id)?.display_name || "partner";
                  throw new Error(`Add at least one orgasm with tags for ${name}.`);
                }
              }
              const created = [];
              for (const part of payloads) {
                created.push(await api(`/dynamics/${dynamicId}/tracking`, {
                  method: "POST",
                  body: JSON.stringify({ ...shared, ...part }),
                }));
              }
              entry = created[0];
            } else {
              entry = await api(`/dynamics/${dynamicId}/tracking`, {
                method: "POST",
                body: JSON.stringify({
                  ...shared,
                  for_membership_id: playForPartner.value,
                  tags: playTagPicker.getTags(),
                }),
              });
            }
            navigateToFeelingsAfterEvent(dynamicId, {
              at: entry.occurred_at || shared.occurred_at,
              from: eventType.value === "orgasm" ? "orgasm" : "play",
              orgEntryId: entry.id,
              context: "after_play",
            });
          } catch (err) {
            if (/feelings/i.test(err.message || "")) {
              error.textContent = `${err.message} Opening Feelings wheel…`;
              error.classList.remove("hidden");
              setTimeout(
                () =>
                  navigateToFeelingsAfterEvent(dynamicId, {
                    from: "orgasm",
                    context: "before_play",
                  }),
                800
              );
              return;
            }
            error.textContent = err.message;
            error.classList.remove("hidden");
          }
        },
      }, "Log event"));

      const history = el("div", { className: "stack" });
      if (!entries.length) {
        history.appendChild(el("p", { className: "muted" }, "No entries yet."));
      } else {
        entries.slice(0, 20).forEach((entry) => {
          history.appendChild(renderTrackingEntrySummary(entry, {
            dynamicId,
            editable: true,
            onChanged: () => renderTracking(dynamicId),
          }));
        });
      }
      const logsSection = el("details", { className: "card stack tracking-logs-collapse" }, [
        el("summary", {}, `Logs (${Math.min(entries.length, 20)}${entries.length > 20 ? "+" : ""})`),
        el("p", { className: "muted" }, "Recent submissions — expand to view, edit, or delete."),
        history,
      ]);

      stack.appendChild(formCard);
      stack.appendChild(el("div", { className: "stack" }, [
        el("button", {
          type: "button",
          className: "link-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}/tracking/history`),
        }, "Prior orgasm / play history →"),
        el("p", { className: "muted" }, "Import past orgasms and play from CSV or other apps."),
      ]));
      stack.appendChild(logsSection);
      stack.appendChild(error);
      stack.appendChild(el("button", {
        className: "ghost-btn",
        onClick: () => navigate(`/dynamic/${dynamicId}/track`),
      }, "Back to tracking"));
      refreshTrackingFields();
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderOrgasmPriorHistory(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading prior history tools..."));
  Promise.all([
    loadDynamic(dynamicId),
  ])
    .then(() => {
      const dynamic = state.currentDynamic;
      const partners = dynamic.partners || [];
      const error = el("div", { className: "error hidden" });
      const status = el("p", { className: "muted" });

      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Prior orgasm / play history"),
        el("p", { className: "muted" }, "Import past tracking from before UBETRA. Template rows include example default tags (Full Orgasm, Handjob, Edging, etc.)."),
        error,
        status,
      ]);

      const csvCard = el("div", { className: "card stack" }, [
        el("h2", {}, "CSV import"),
        el("p", { className: "muted" }, "Columns: partner, event_type (orgasm|no_orgasm), occurred_at, ended_at, notes, tags, orgasm_tags. Use | in orgasm_tags to separate multiple orgasms."),
      ]);
      csvCard.appendChild(el("button", {
        type: "button",
        className: "ghost-btn",
        onClick: async () => {
          error.classList.add("hidden");
          try {
            const token = state.token;
            const res = await fetch(`${API}/dynamics/${dynamicId}/tracking/historical/csv-template`, {
              headers: token ? { Authorization: `Bearer ${token}` } : {},
            });
            if (!res.ok) throw new Error(await res.text() || "Could not download template");
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = el("a", { href: url, download: "ubetra-orgasm-history-template.csv" });
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            status.textContent = "Template downloaded.";
          } catch (err) {
            error.textContent = err.message;
            error.classList.remove("hidden");
          }
        },
      }, "Download CSV template"));

      const fileInput = el("input", {
        type: "file",
        accept: ".csv,text/csv",
        className: "hidden",
      });
      fileInput.addEventListener("change", async () => {
        const file = fileInput.files?.[0];
        if (!file) return;
        error.classList.add("hidden");
        status.textContent = "Importing…";
        try {
          const body = new FormData();
          body.append("file", file);
          const token = state.token;
          const res = await fetch(`${API}/dynamics/${dynamicId}/tracking/historical/import-csv`, {
            method: "POST",
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            body,
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.detail || data.message || "Import failed");
          const bits = [`Imported ${data.created || 0} entr${data.created === 1 ? "y" : "ies"}.`];
          if (data.error_count) bits.push(`${data.error_count} row error(s).`);
          status.textContent = bits.join(" ");
          if (data.errors?.length) {
            error.textContent = data.errors.join("\n");
            error.classList.remove("hidden");
          }
        } catch (err) {
          status.textContent = "";
          error.textContent = err.message;
          error.classList.remove("hidden");
        } finally {
          fileInput.value = "";
        }
      });
      csvCard.appendChild(fileInput);
      csvCard.appendChild(el("button", {
        type: "button",
        className: "primary-btn",
        onClick: () => fileInput.click(),
      }, "Upload CSV"));
      stack.appendChild(csvCard);

      const manualCard = el("div", { className: "card stack" }, [
        el("h2", {}, "Add one entry"),
        el("p", { className: "muted" }, "Log a single past orgasm or play session."),
      ]);
      const partnerSelect = el("select");
      partners.forEach((p) => partnerSelect.appendChild(el("option", { value: p.id }, p.display_name)));
      const eventType = el("select", {}, [
        el("option", { value: "orgasm" }, "Orgasm"),
        el("option", { value: "no_orgasm" }, "No orgasm (play)"),
      ]);
      const occurred = el("input", { type: "datetime-local" });
      const ended = el("input", { type: "datetime-local" });
      const notes = el("input", { placeholder: "Notes (optional)" });
      const orgasmTags = buildTagPicker(trackingTagPresets("orgasm"));
      const playTags = buildTagPicker(trackingTagPresets("play"));
      const orgasmWrap = el("label", { className: "stack" }, ["Orgasm tags", orgasmTags.row, orgasmTags.custom]);
      const playWrap = el("label", { className: "stack hidden" }, ["Play tags", playTags.row, playTags.custom]);
      eventType.addEventListener("change", () => {
        const isOrgasm = eventType.value === "orgasm";
        orgasmWrap.classList.toggle("hidden", !isOrgasm);
        playWrap.classList.toggle("hidden", isOrgasm);
      });
      manualCard.appendChild(el("label", {}, ["Partner", partnerSelect]));
      manualCard.appendChild(el("label", {}, ["Type", eventType]));
      manualCard.appendChild(el("label", {}, ["Occurred at", occurred]));
      manualCard.appendChild(el("label", {}, ["Ended at (optional)", ended]));
      manualCard.appendChild(el("label", {}, ["Notes", notes]));
      manualCard.appendChild(orgasmWrap);
      manualCard.appendChild(playWrap);
      manualCard.appendChild(el("button", {
        className: "primary-btn",
        onClick: async () => {
          if (!occurred.value) {
            error.textContent = "Occurred at is required.";
            error.classList.remove("hidden");
            return;
          }
          error.classList.add("hidden");
          try {
            const payload = {
              for_membership_id: partnerSelect.value,
              event_type: eventType.value,
              occurred_at: new Date(occurred.value).toISOString(),
              notes: notes.value,
            };
            if (ended.value) payload.ended_at = new Date(ended.value).toISOString();
            if (eventType.value === "orgasm") {
              const tags = orgasmTags.getTags();
              if (!tags.length) throw new Error("Add at least one orgasm tag.");
              payload.orgasms = [{ tags }];
            } else {
              payload.tags = playTags.getTags();
            }
            await api(`/dynamics/${dynamicId}/tracking`, {
              method: "POST",
              body: JSON.stringify(payload),
            });
            status.textContent = "Historical entry saved.";
            occurred.value = "";
            ended.value = "";
            notes.value = "";
          } catch (err) {
            error.textContent = err.message;
            error.classList.remove("hidden");
          }
        },
      }, "Add entry"));
      stack.appendChild(manualCard);

      stack.appendChild(el("button", {
        className: "ghost-btn",
        onClick: () => navigate(`/dynamic/${dynamicId}/tracking`),
      }, "Back to orgasm tracking"));
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function formatGoalStamp(iso) {
  if (!iso) return "—";
  try {
    return formatLocalDateTime(iso);
  } catch {
    return iso;
  }
}

function renderChastityGoalsCard(dynamicId, goalsData, { partners, onSaved }) {
  const catalog = goalsData.requirement_catalog || [];
  const kinds = goalsData.goal_kinds || [];
  const startModes = goalsData.start_modes || [
    { id: "rolling", title: "Rolling (from last full orgasm)", hint: "" },
    { id: "now", title: "Start now", hint: "" },
  ];
  const archiveReasons = goalsData.archive_reasons || [
    { id: "completed", title: "Completed / granted" },
    { id: "replaced", title: "Replaced by a new goal" },
  ];
  const softMax = goalsData.soft_max_requirements || 2;
  const config = JSON.parse(JSON.stringify(goalsData.config || { goals: [], header_hidden: true }));
  const progressById = Object.fromEntries(
    [...(goalsData.goals || []), ...(goalsData.archived_goals || [])].map((g) => [g.id, g])
  );
  const error = el("div", { className: "error hidden" });
  const host = el("details", { className: "card stack goals-collapse" }, [
    el("summary", {}, "Orgasm and Chastity goals"),
    el("p", { className: "muted" }, "Currently active goals drive header meters. Archive when finished or replaced; repeat to restart tracking from now. Rolling starts from the last full orgasm; Start now ignores prior events."),
  ]);

  const headerHidden = el("input", { type: "checkbox" });
  headerHidden.checked = config.header_hidden !== false;
  host.appendChild(el("label", { className: "checkbox-label" }, [
    headerHidden,
    " Start header meters collapsed (click chips to reveal)",
  ]));

  const summary = el("p", { className: "muted" });
  const activeHost = el("div", { className: "stack" });
  const archivedHost = el("div", { className: "stack" });

  function baselineFor(goal) {
    const mode = goal.start_mode === "now" ? "now" : "rolling";
    return goalsData.baselines?.[mode] || null;
  }

  function metricPreviewText(goal, reqType) {
    const base = baselineFor(goal);
    if (!base) return "";
    const m = (base.metrics || []).find((x) => x.type === reqType);
    if (!m) return "";
    const unit = m.unit === "days" ? "d" : "";
    return `Currently ${m.current}${unit} · since ${base.since_label}`;
  }

  function askArchiveReason() {
    const labels = archiveReasons.map((r, i) => `${i + 1}) ${r.title}`).join("\n");
    const answer = window.prompt(
      `Archive this goal — was it completed or replaced?\n\n${labels}\n\nEnter 1 or 2 (or completed / replaced):`,
      "1"
    );
    if (answer == null) return null;
    const t = String(answer).trim().toLowerCase();
    if (t === "1" || t.startsWith("complet")) return "completed";
    if (t === "2" || t.startsWith("replac")) return "replaced";
    if (archiveReasons.some((r) => r.id === t)) return t;
    return null;
  }

  function paintGoalCard(goal, { archived }) {
    const kindSelect = el("select");
    kinds.forEach((k) => {
      const opt = el("option", { value: k.id }, k.title);
      if (goal.kind === k.id) opt.selected = true;
      kindSelect.appendChild(opt);
    });
    kindSelect.addEventListener("change", () => { goal.kind = kindSelect.value; });
    kindSelect.disabled = archived;

    const title = el("input", { value: goal.title || "", placeholder: "Goal title" });
    title.addEventListener("change", () => { goal.title = title.value.trim(); });
    title.disabled = archived;

    const forSelect = el("select");
    forSelect.appendChild(el("option", { value: "" }, "Default sub"));
    partners.filter((p) => p.role === "submissive").forEach((p) => {
      const opt = el("option", { value: p.id }, p.display_name);
      if (goal.for_membership_id === p.id) opt.selected = true;
      forSelect.appendChild(opt);
    });
    forSelect.addEventListener("change", () => { goal.for_membership_id = forSelect.value || null; });
    forSelect.disabled = archived;

    const startSelect = el("select");
    startModes.forEach((m) => {
      const opt = el("option", { value: m.id }, m.title);
      if ((goal.start_mode || "rolling") === m.id) opt.selected = true;
      startSelect.appendChild(opt);
    });
    const startHint = el("p", { className: "muted" });
    function syncStartHint() {
      const mode = startModes.find((m) => m.id === (goal.start_mode || "rolling"));
      const base = baselineFor(goal);
      const bits = [];
      if (mode?.hint) bits.push(mode.hint);
      if (base?.since_label) {
        bits.push(
          goal.start_mode === "now"
            ? "Preview counts from now (prior events ignored)."
            : `Rolling baseline: ${base.since_label}${base.since ? ` (${formatGoalStamp(base.since)})` : ""}.`
        );
      }
      startHint.textContent = bits.join(" ");
    }
    startSelect.addEventListener("change", () => {
      goal.start_mode = startSelect.value;
      goal.resolve_reset = true;
      goal.reset_at = null;
      syncStartHint();
      paintGoals();
    });
    startSelect.disabled = archived;
    syncStartHint();

    const reqHost = el("div", { className: "stack" });
    const warn = el("p", { className: "goal-complex-warn hidden" }, "More than two requirements can make grants rare or ambiguous — keep the rule set intentional.");

    function paintReqs() {
      reqHost.replaceChildren();
      warn.classList.toggle("hidden", (goal.requirements || []).length <= softMax);
      (goal.requirements || []).forEach((req, reqIdx) => {
        const typeSelect = el("select");
        catalog.forEach((c) => {
          const opt = el("option", { value: c.id }, c.title);
          if (req.type === c.id) opt.selected = true;
          typeSelect.appendChild(opt);
        });
        const valueInput = el("input", { type: "number", min: "1", step: "1", value: String(req.value || 1) });
        const preview = el("p", { className: "muted goal-metric-preview" });
        function syncPreview() {
          preview.textContent = metricPreviewText(goal, req.type) || "";
          preview.classList.toggle("hidden", !preview.textContent);
        }
        typeSelect.addEventListener("change", () => {
          req.type = typeSelect.value;
          syncPreview();
        });
        valueInput.addEventListener("change", () => { req.value = Number(valueInput.value) || 1; });
        typeSelect.disabled = archived;
        valueInput.disabled = archived;
        syncPreview();
        reqHost.appendChild(el("div", { className: "stack" }, [
          el("div", { className: "row wrap" }, [
            typeSelect,
            valueInput,
            archived
              ? null
              : el("button", {
                type: "button",
                className: "ghost-btn",
                onClick: () => {
                  goal.requirements.splice(reqIdx, 1);
                  paintReqs();
                },
              }, "Remove"),
          ]),
          preview,
        ]));
      });
    }
    paintReqs();

    const progress = progressById[goal.id];
    const progressBits = progress
      ? (progress.requirements || []).map((r) => `${r.title}: ${r.current}/${r.target}${r.met ? " ✓" : ""}`).join(" · ")
      : "";
    const metaBits = [
      `Created ${formatGoalStamp(goal.created_at || progress?.created_at)}`,
      `Tracking since ${formatGoalStamp(goal.reset_at || progress?.reset_at)}`,
      `Start: ${(goal.start_mode || "rolling") === "now" ? "now" : "rolling"}`,
    ];
    if (Number(goal.repeat_count || progress?.repeat_count || 0) > 0) {
      metaBits.push(`Repeated ${goal.repeat_count || progress.repeat_count}×`);
    }
    if (archived && goal.archive_reason) {
      const reasonTitle = archiveReasons.find((r) => r.id === goal.archive_reason)?.title || goal.archive_reason;
      metaBits.push(`Archived as ${reasonTitle}`);
      if (goal.archived_at) metaBits.push(formatGoalStamp(goal.archived_at));
    }

    const actions = el("div", { className: "row wrap" });
    if (!archived) {
      actions.appendChild(el("button", {
        type: "button",
        className: "ghost-btn",
        onClick: () => {
          if (!goal.requirements) goal.requirements = [];
          goal.requirements.push({ type: catalog[0]?.id || "days_since_full_orgasm", value: 7 });
          paintReqs();
        },
      }, "+ Add requirement"));
      actions.appendChild(el("button", {
        type: "button",
        className: "ghost-btn",
        onClick: () => {
          goal.start_mode = "now";
          goal.resolve_reset = true;
          goal.reset_at = null;
          goal.active = true;
          goal.archived_at = null;
          goal.archive_reason = null;
          goal.repeat_count = Number(goal.repeat_count || 0) + 1;
          paintGoals();
        },
      }, "Repeat (reset to now)"));
      actions.appendChild(el("button", {
        type: "button",
        className: "ghost-btn",
        onClick: () => {
          const reason = askArchiveReason();
          if (!reason) return;
          goal.active = false;
          goal.archive_reason = reason;
          goal.archived_at = new Date().toISOString();
          paintGoals();
        },
      }, "Archive"));
    } else {
      actions.appendChild(el("button", {
        type: "button",
        className: "ghost-btn",
        onClick: () => {
          goal.active = true;
          goal.archive_reason = null;
          goal.archived_at = null;
          goal.start_mode = "now";
          goal.resolve_reset = true;
          goal.reset_at = null;
          goal.repeat_count = Number(goal.repeat_count || 0) + 1;
          paintGoals();
        },
      }, "Repeat as active (from now)"));
      actions.appendChild(el("button", {
        type: "button",
        className: "ghost-btn",
        onClick: () => {
          const idx = config.goals.indexOf(goal);
          if (idx >= 0) config.goals.splice(idx, 1);
          paintGoals();
        },
      }, "Delete permanently"));
    }

    return el("div", { className: `card stack${archived ? " goal-archived" : ""}` }, [
      el("label", {}, ["Goal type", kindSelect]),
      el("label", {}, ["Title", title]),
      el("label", {}, ["For", forSelect]),
      archived ? null : el("label", {}, ["Tracking start", startSelect]),
      archived ? null : startHint,
      el("strong", {}, "Requirements"),
      reqHost,
      archived ? null : warn,
      el("p", { className: "muted" }, metaBits.join(" · ")),
      progressBits ? el("p", {}, progressBits) : null,
      progress?.countdown_at && !archived
        ? el("p", { className: "muted" }, `Countdown: ${formatGoalCountdown(progress.countdown_at)}`)
        : null,
      progress?.ready && !archived ? el("p", { className: "pill ok" }, "Ready to grant") : null,
      actions,
    ]);
  }

  function paintGoals() {
    const active = (config.goals || []).filter((g) => g.active !== false);
    const archived = (config.goals || []).filter((g) => g.active === false);
    summary.textContent = `${active.length} currently active · ${archived.length} archived`;
    activeHost.replaceChildren(
      el("h3", {}, "Currently active"),
      active.length
        ? null
        : el("p", { className: "muted" }, "No active goals. Add one below."),
      ...active.map((g) => paintGoalCard(g, { archived: false }))
    );
    archivedHost.replaceChildren(
      el("h3", {}, "Archived"),
      archived.length
        ? null
        : el("p", { className: "muted" }, "No archived goals yet."),
      ...archived.map((g) => paintGoalCard(g, { archived: true }))
    );
  }
  paintGoals();

  host.appendChild(summary);
  host.appendChild(activeHost);
  host.appendChild(archivedHost);
  host.appendChild(el("button", {
    type: "button",
    className: "ghost-btn",
    onClick: () => {
      const startMode = "rolling";
      config.goals.push({
        id: `goal-${Date.now()}`,
        kind: "orgasm_grant",
        title: "Next orgasm / unlock",
        for_membership_id: null,
        requirements: [
          { type: "days_since_full_orgasm", value: 7 },
          { type: "tasks_completed", value: 3 },
        ],
        start_mode: startMode,
        reset_at: null,
        resolve_reset: true,
        created_at: null,
        active: true,
        archived_at: null,
        archive_reason: null,
        repeat_count: 0,
      });
      paintGoals();
    },
  }, "+ Add goal"));
  host.appendChild(error);
  host.appendChild(el("button", {
    type: "button",
    className: "primary-btn",
    onClick: async () => {
      error.classList.add("hidden");
      try {
        config.header_hidden = headerHidden.checked;
        await api(`/dynamics/${dynamicId}/chastity-goals`, {
          method: "PUT",
          body: JSON.stringify(config),
        });
        onSaved?.();
      } catch (err) {
        error.textContent = err.message;
        error.classList.remove("hidden");
      }
    },
  }, "Save goals"));
  return host;
}

function renderChastity(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading chastity tracking..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/chastity/overview`),
    api(`/dynamics/${dynamicId}/chastity/settings`),
    api(`/dynamics/${dynamicId}/chastity`),
    api(`/dynamics/${dynamicId}/chastity/limit-proposals`).catch(() => []),
    api(`/dynamics/${dynamicId}/chastity/tags`).catch(() => ({ presets: [] })),
    api(`/dynamics/${dynamicId}/chastity-goals`).catch(() => null),
    loadDynamic(dynamicId),
  ])
    .then(([overview, settings, lockups, limitProposals, tagData, goalsData]) => {
      const dynamic = state.currentDynamic;
      const you = dynamic.partners.find((p) => p.is_you);
      const error = el("div", { className: "error hidden" });
      const flowHost = el("div", { className: "chastity-flow-host hidden" });
      const chastityTagPresets = tagData.presets || [];
      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Chastity tracking"),
        el("p", { className: "muted" }, "Lockups are tracked for submissives with chastity available. Orgasm and lockup data can be shared with the assistant domme in Settings."),
        error,
        flowHost,
      ]);

      if (settings.you_are_dominant && goalsData) {
        stack.appendChild(renderChastityGoalsCard(dynamicId, goalsData, {
          partners: dynamic.partners || [],
          onSaved: () => {
            refreshDomGoalHeader(dynamicId);
            renderChastity(dynamicId);
          },
        }));
      }

      const subs = settings.submissives || [];
      const enrolled = overview.partners.filter((p) => p.chastity_enabled);

      function saveSubSettings(subId, enabled, maxHours) {
        return api(`/dynamics/${dynamicId}/chastity/settings`, {
          method: "PUT",
          body: JSON.stringify({
            membership_id: subId,
            chastity_enabled: enabled,
            chastity_max_lock_hours: maxHours,
          }),
        });
      }

      if (!overview.any_enabled) {
        const empty = el("div", { className: "card stack" }, [
          el("h2", {}, "No one available for chastity"),
          el("p", { className: "muted" }, "The keyholder can enable chastity for a submissive below or in Ground rules. To hide the whole module, turn off Chastity in Menu → Features."),
        ]);
        if (settings.you_are_dominant && subs.length) {
          subs.forEach((sub) => {
            empty.appendChild(el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                try {
                  await saveSubSettings(sub.membership_id, true, sub.chastity_max_lock_hours ?? 72);
                  renderChastity(dynamicId);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, `Enable chastity for ${sub.display_name}`));
          });
        }
        empty.appendChild(el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => navigate(`/dynamic/${dynamicId}/ground-rules`),
        }, "Open Ground rules"));
        stack.appendChild(empty);
        stack.appendChild(el("button", {
          className: "ghost-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}/track`),
        }, "Back to tracking"));
        setViewContent(stack);
        return;
      }

      stack.appendChild(el("p", { className: "muted" }, overview.summary_label));
      stack.appendChild(el("button", {
        type: "button",
        className: "link-btn",
        onClick: () => navigate(`/dynamic/${dynamicId}/ground-rules`),
      }, "Availability & lock time agreements →"));

      enrolled.forEach((partner) => {
        const hero = el("div", { className: `card lockup-hero ${partner.state === "locked" ? "locked" : ""}` });
        let heroText = "";
        if (partner.state === "locked") {
          heroText = `${partner.name} has been locked for ${partner.current_duration_label}`;
        } else if (partner.state === "on_break") {
          heroText = `${partner.name} is on a break for ${partner.break_duration_label}`;
        } else if (partner.free_duration_label) {
          heroText = `${partner.name} has been free for ${partner.free_duration_label}`;
        } else {
          heroText = `${partner.name} has not been locked up yet`;
        }
        hero.appendChild(el("p", { className: "lockup-hero-text" }, heroText));
        if (partner.state === "locked") {
          hero.appendChild(el("p", { className: "lockup-timer" }, partner.current_duration_label));
        } else if (partner.state === "on_break") {
          hero.appendChild(el("p", { className: "lockup-timer break" }, partner.break_duration_label));
        }
        if (partner.timer_overdue && partner.active_lockup_id && settings.you_are_dominant) {
          const timerBanner = el("div", { className: "chastity-timer-overdue stack" }, [
            el("p", {}, `${partner.name}'s lock timer is up.`),
            el("p", { className: "muted" }, "Extend the time, or confirm Released!"),
            el("div", { className: "row" }, [
              el("button", {
                type: "button",
                className: "primary-btn",
                onClick: async () => {
                  const raw = prompt("Extend by how many hours?", "24");
                  if (raw == null) return;
                  const hours = parseInt(raw, 10);
                  if (!hours || hours < 1) {
                    error.textContent = "Enter a positive number of hours.";
                    error.classList.remove("hidden");
                    return;
                  }
                  try {
                    await api(`/dynamics/${dynamicId}/chastity/${partner.active_lockup_id}/timer/extend`, {
                      method: "PATCH",
                      body: JSON.stringify({ hours }),
                    });
                    renderChastity(dynamicId);
                  } catch (err) {
                    error.textContent = err.message;
                    error.classList.remove("hidden");
                  }
                },
              }, "Extend"),
              el("button", {
                type: "button",
                className: "ghost-btn",
                onClick: async () => {
                  if (!confirm("Confirm Released! for this lock timer?")) return;
                  try {
                    await api(`/dynamics/${dynamicId}/chastity/${partner.active_lockup_id}/timer/release`, {
                      method: "PATCH",
                    });
                    renderChastity(dynamicId);
                  } catch (err) {
                    error.textContent = err.message;
                    error.classList.remove("hidden");
                  }
                },
              }, "Released!"),
            ]),
          ]);
          hero.appendChild(timerBanner);
        } else if (partner.timer_overdue) {
          hero.appendChild(el("p", { className: "chastity-timer-overdue-note" }, "Lock timer finished — waiting on keyholder."));
        }
        stack.appendChild(hero);

        stack.appendChild(el("div", { className: "card chastity-stats-grid" }, [
          el("div", { className: "chastity-stat" }, [
            el("span", { className: "chastity-stat-value" }, `${partner.percent_locked_all_time}%`),
            el("span", { className: "muted" }, "Locked (all time)"),
          ]),
          el("div", { className: "chastity-stat" }, [
            el("span", { className: "chastity-stat-value" }, partner.total_locked_label),
            el("span", { className: "muted" }, "Spent locked"),
          ]),
          el("div", { className: "chastity-stat wide" }, [
            el("span", { className: "muted" }, `Average lockup: ${partner.average_lockup_label || "—"} · Longest: ${partner.longest_lockup_label || "—"} · ${partner.lockup_count} periods`),
          ]),
        ]));

        const partnerLockupsForTimeline = lockups.filter((l) => l.for_membership_id === partner.membership_id);
        stack.appendChild(renderChastityTimeline(partnerLockupsForTimeline, partner.name, {
          dynamicId,
          canEdit: settings.you_are_dominant || you?.id === partner.membership_id,
          youAreDominant: !!settings.you_are_dominant,
          subCanDeleteBreaks: settings.sub_can_delete_breaks !== false,
          tagPresets: chastityTagPresets,
          onSaved: () => renderChastity(dynamicId),
        }));

        const actions = el("div", { className: "row chastity-actions" });
        const isDom = settings.you_are_dominant;
        const isLockedSub = you?.id === partner.membership_id;
        const activeLockup = lockups.find((l) => l.id === partner.active_lockup_id);
        const activeBreak = activeLockup?.breaks?.find((b) => b.id === partner.active_break_id);

        function showFlowError(flowError, message) {
          flowError.textContent = message;
          flowError.classList.remove("hidden");
        }

        function showFullReleaseFlow() {
          const releaseTime = buildTimeSelector({ label: "Release time" });
          const notes = el("textarea", { placeholder: "Optional note", rows: 3 });
          const releaseTags = buildTagPicker(chastityTagPresets);
          const flowError = el("p", { className: "error hidden" });
          openChastityFlow(flowHost, "Full release", [
            el("p", { className: "muted" }, `Ends the lockup. ${isLockedSub ? "You are" : `${partner.name} is`} allowed a full orgasm.`),
            releaseTime.wrap,
            el("label", { className: "stack" }, ["Note", notes]),
            el("label", { className: "stack" }, ["Tags", releaseTags.row, releaseTags.custom]),
            flowError,
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                flowError.classList.add("hidden");
                try {
                  const ended = await api(`/dynamics/${dynamicId}/chastity/${partner.active_lockup_id}/end`, {
                    method: "PATCH",
                    body: JSON.stringify({
                      release_notes: notes.value.trim(),
                      ended_at: releaseTime.getIso(),
                      tags: releaseTags.getTags(),
                      ended_kind: "released_orgasm",
                    }),
                  });
                  closeChastityFlow(flowHost);
                  navigateToFeelingsAfterEvent(dynamicId, {
                    at: ended.ended_at || releaseTime.getIso(),
                    from: "chastity",
                    chastityLockupId: partner.active_lockup_id,
                    context: "after_play",
                  });
                } catch (err) {
                  showFlowError(flowError, err.message);
                }
              },
            }, "Full release"),
          ], () => closeChastityFlow(flowHost));
        }

        function showTempUnlockFlow(completed) {
          const startTime = buildTimeSelector({
            label: "Unlock started",
            defaultValue: completed ? shiftLocalDatetime(15) : toLocalDatetimeValue(),
          });
          const endTime = completed
            ? buildTimeSelector({ label: "Locked back up", defaultValue: toLocalDatetimeValue() })
            : null;
          const breakPicker = buildBreakTypePicker(settings, { isDominant: isDom });
          const note = el("input", { placeholder: "Optional note" });
          const unlockTags = buildTagPicker(chastityTagPresets);
          const flowError = el("p", { className: "error hidden" });
          const nodes = [
            el("p", { className: "muted" }, completed
              ? "Log a temporary unlock that already ended."
              : "Log a temporary unlock starting now. Use Lock back up when the cage goes on again."),
            startTime.wrap,
          ];
          if (endTime) nodes.push(endTime.wrap);
          nodes.push(
            el("p", { className: "muted" }, "Reason for unlock"),
            breakPicker.wrap,
            el("label", { className: "stack" }, ["Note", note]),
            el("label", { className: "stack" }, ["Tags", unlockTags.row, unlockTags.custom]),
            flowError,
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                const picked = breakPicker.getPayload();
                if (!picked) {
                  showFlowError(flowError, "Pick a reason for the unlock.");
                  return;
                }
                error.classList.add("hidden");
                flowError.classList.add("hidden");
                try {
                  await api(`/dynamics/${dynamicId}/chastity/${partner.active_lockup_id}/break`, {
                    method: "POST",
                    body: JSON.stringify({
                      break_type: picked.break_type,
                      break_reason: picked.break_reason,
                      started_at: startTime.getIso(),
                      ended_at: endTime ? endTime.getIso() : null,
                      note: note.value.trim(),
                      tags: unlockTags.getTags(),
                    }),
                  });
                  closeChastityFlow(flowHost);
                  renderChastity(dynamicId);
                } catch (err) {
                  showFlowError(flowError, err.message);
                }
              },
            }, completed ? "Log temporary unlock" : "Unlock"),
          );
          if (!isDom && isLockedSub) {
            nodes.splice(nodes.length - 1, 0, el("p", { className: "muted" }, "Your keyholder will be notified."));
          }
          openChastityFlow(flowHost, completed ? "Temporary unlock (completed)" : "Temporary unlock", nodes, () => closeChastityFlow(flowHost));
        }

        function showUnlockDisambiguation() {
          const who = isLockedSub ? "I'm" : "they're";
          openChastityFlow(flowHost, "Unlock", [
            el("button", {
              className: "option-card",
              type: "button",
              onClick: () => showFullReleaseFlow(),
            }, [
              el("strong", {}, "Full release"),
              el("p", { className: "muted" }, "End the lockup — allowed a full orgasm."),
            ]),
            el("button", {
              className: "option-card",
              type: "button",
              onClick: () => showTempUnlockFlow(true),
            }, [
              el("strong", {}, `Temporary unlock but ${who} locked now`),
              el("p", { className: "muted" }, "Log unlock and lock-back-up times with a reason."),
            ]),
            el("button", {
              className: "option-card",
              type: "button",
              onClick: () => showTempUnlockFlow(false),
            }, [
              el("strong", {}, "Temporary unlock"),
              el("p", { className: "muted" }, "Starting now — lock back up later from this page."),
            ]),
          ], () => closeChastityFlow(flowHost));
        }

        function showLockBackUpFlow() {
          const isUndecided = activeBreak?.break_type === "authorized_undecided";
          const lockTime = buildTimeSelector({ label: "When did the lock go back on?" });
          const flowError = el("p", { className: "error hidden" });
          const nodes = [
            el("p", { className: "muted" }, "Resume the lockup after a temporary unlock."),
            lockTime.wrap,
          ];
          let finalPicker = null;
          if (isUndecided && isDom) {
            nodes.push(el("p", { className: "muted" }, "Finalize the unlock reason, or choose full release."));
            finalPicker = buildBreakTypePicker(settings, { isDominant: true });
            nodes.push(finalPicker.wrap);
            nodes.push(el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => showFullReleaseFlow(),
            }, "Full release instead"));
          }
          nodes.push(
            flowError,
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                flowError.classList.add("hidden");
                const body = { ended_at: lockTime.getIso() };
                if (finalPicker) {
                  const picked = finalPicker.getPayload();
                  if (!picked) {
                    showFlowError(flowError, "Pick how to finalize this unlock.");
                    return;
                  }
                  body.break_type = picked.break_type;
                  body.break_reason = picked.break_reason;
                }
                try {
                  await api(
                    `/dynamics/${dynamicId}/chastity/${partner.active_lockup_id}/break/${partner.active_break_id}/finish`,
                    { method: "PATCH", body: JSON.stringify(body) }
                  );
                  closeChastityFlow(flowHost);
                  renderChastity(dynamicId);
                } catch (err) {
                  showFlowError(flowError, err.message);
                }
              },
            }, "Lock back up"),
          );
          openChastityFlow(flowHost, "Lock back up", nodes, () => closeChastityFlow(flowHost));
        }

        function showStartLockupFlow() {
          const startTime = buildTimeSelector({ label: "Lockup started" });
          const note = el("input", { placeholder: "Optional note" });
          const lockTags = buildTagPicker(chastityTagPresets);
          const plannedEnd = isDom ? el("input", { type: "datetime-local" }) : null;
          const flowError = el("p", { className: "error hidden" });
          const nodes = [
            startTime.wrap,
            el("label", { className: "stack" }, ["Note", note]),
            el("label", { className: "stack" }, ["Tags", lockTags.row, lockTags.custom]),
          ];
          if (plannedEnd) {
            nodes.splice(1, 0, el("label", { className: "stack" }, ["Planned end (optional)", plannedEnd]));
          }
          nodes.push(
            flowError,
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                error.classList.add("hidden");
                flowError.classList.add("hidden");
                try {
                  const lockup = await api(`/dynamics/${dynamicId}/chastity/start`, {
                    method: "POST",
                    body: JSON.stringify({
                      for_membership_id: partner.membership_id,
                      device_notes: note.value.trim(),
                      started_at: startTime.getIso(),
                      planned_end_at: plannedEnd?.value ? datetimeLocalToIso(plannedEnd.value) : null,
                      tags: lockTags.getTags(),
                    }),
                  });
                  closeChastityFlow(flowHost);
                  navigateToFeelingsAfterEvent(dynamicId, {
                    at: lockup.started_at || startTime.getIso(),
                    from: "chastity",
                    chastityLockupId: lockup.id,
                    context: "ad_hoc",
                  });
                } catch (err) {
                  showFlowError(flowError, err.message);
                }
              },
            }, isLockedSub ? "Start my lockup" : `Lock up ${partner.name}`),
          );
          openChastityFlow(flowHost, isLockedSub ? "Start lockup" : `Lock up ${partner.name}`, nodes, () => closeChastityFlow(flowHost));
        }

        if (partner.state === "unlocked" && (isDom || isLockedSub)) {
          actions.appendChild(el("button", {
            className: "primary-btn",
            type: "button",
            onClick: () => showStartLockupFlow(),
          }, isLockedSub ? "Start my lockup" : `Lock up ${partner.name}`));
        }

        if (partner.state === "locked" && (isDom || isLockedSub)) {
          actions.appendChild(el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: () => showUnlockDisambiguation(),
          }, "Unlock"));
        }

        if (partner.state === "on_break" && (isDom || isLockedSub)) {
          actions.appendChild(el("button", {
            className: "primary-btn",
            type: "button",
            onClick: () => showLockBackUpFlow(),
          }, isLockedSub ? "Lock back up" : `Lock ${partner.name} back up`));
          if (isDom) {
            actions.appendChild(el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: () => showFullReleaseFlow(),
            }, "Full release"));
          }
        }
        if (actions.childNodes.length) stack.appendChild(actions);
      });

      const historicalCard = el("div", { className: "stack" }, [
        el("button", {
          type: "button",
          className: "link-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}/chastity/history`),
        }, "Prior lockup history →"),
        el("p", { className: "muted" }, "Import past lockups from other apps or log them manually."),
      ]);
      stack.appendChild(historicalCard);

      stack.appendChild(el("button", {
        className: "ghost-btn",
        onClick: () => navigate(`/dynamic/${dynamicId}/track`),
      }, "Back to tracking"));
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderChastityPriorHistory(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading prior lockup tools..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/chastity/overview`),
    api(`/dynamics/${dynamicId}/chastity/settings`),
    api(`/dynamics/${dynamicId}/chastity/tags`).catch(() => ({ presets: [] })),
    loadDynamic(dynamicId),
  ])
    .then(([overview, settings, tagData]) => {
      const error = el("div", { className: "error hidden" });
      const status = el("p", { className: "muted" });
      const enrolled = (overview.partners || []).filter((p) => p.chastity_enabled);
      const chastityTagPresets = tagData.presets || [];

      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Prior lockup history"),
        el("p", { className: "muted" }, "Log lockups from before UBETRA (or other apps). They appear as historical periods on the chastity timeline."),
        error,
        status,
      ]);

      const csvCard = el("div", { className: "card stack" }, [
        el("h2", {}, "CSV import"),
        el("p", { className: "muted" }, "Download a template with example rows, edit in Excel or Google Sheets, then upload. Columns: submissive, started_at, ended_at, note, tags."),
      ]);
      csvCard.appendChild(el("button", {
        type: "button",
        className: "ghost-btn",
        onClick: async () => {
          error.classList.add("hidden");
          try {
            const token = state.token;
            const res = await fetch(`${API}/dynamics/${dynamicId}/chastity/historical/csv-template`, {
              headers: token ? { Authorization: `Bearer ${token}` } : {},
            });
            if (!res.ok) throw new Error(await res.text() || "Could not download template");
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = el("a", { href: url, download: "ubetra-chastity-history-template.csv" });
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            status.textContent = "Template downloaded.";
          } catch (err) {
            error.textContent = err.message;
            error.classList.remove("hidden");
          }
        },
      }, "Download CSV template"));

      const fileInput = el("input", {
        type: "file",
        accept: ".csv,text/csv",
        className: "hidden",
      });
      fileInput.addEventListener("change", async () => {
        const file = fileInput.files?.[0];
        if (!file) return;
        error.classList.add("hidden");
        status.textContent = "Importing…";
        try {
          const body = new FormData();
          body.append("file", file);
          const token = state.token;
          const res = await fetch(`${API}/dynamics/${dynamicId}/chastity/historical/import-csv`, {
            method: "POST",
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            body,
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.detail || data.message || "Import failed");
          const bits = [`Imported ${data.created || 0} lockup(s).`];
          if (data.error_count) bits.push(`${data.error_count} row error(s).`);
          status.textContent = bits.join(" ");
          if (data.errors?.length) {
            error.textContent = data.errors.join("\n");
            error.classList.remove("hidden");
          }
        } catch (err) {
          status.textContent = "";
          error.textContent = err.message;
          error.classList.remove("hidden");
        } finally {
          fileInput.value = "";
        }
      });
      csvCard.appendChild(fileInput);
      csvCard.appendChild(el("button", {
        type: "button",
        className: "primary-btn",
        onClick: () => fileInput.click(),
      }, "Upload CSV"));
      stack.appendChild(csvCard);

      const manualCard = el("div", { className: "card stack" }, [
        el("h2", {}, "Add one lockup"),
        el("p", { className: "muted" }, "Enter a single past period manually."),
      ]);
      if (!enrolled.length) {
        manualCard.appendChild(el("p", { className: "muted" }, "Enable chastity for a submissive first."));
      } else {
        const histSub = el("select");
        enrolled.forEach((p) => histSub.appendChild(el("option", { value: p.membership_id }, p.name)));
        const startInput = el("input", { type: "datetime-local" });
        const endInput = el("input", { type: "datetime-local" });
        const noteInput = el("input", { placeholder: "Note (optional)" });
        const histTags = buildTagPicker(chastityTagPresets);
        manualCard.appendChild(el("label", {}, ["Submissive", histSub]));
        manualCard.appendChild(el("label", {}, ["Started", startInput]));
        manualCard.appendChild(el("label", {}, ["Ended", endInput]));
        manualCard.appendChild(el("label", {}, ["Note", noteInput]));
        manualCard.appendChild(el("label", { className: "stack" }, ["Tags", histTags.row, histTags.custom]));
        manualCard.appendChild(el("button", {
          className: "primary-btn",
          onClick: async () => {
            if (!startInput.value || !endInput.value) {
              error.textContent = "Start and end times are required.";
              error.classList.remove("hidden");
              return;
            }
            error.classList.add("hidden");
            try {
              await api(`/dynamics/${dynamicId}/chastity/historical`, {
                method: "POST",
                body: JSON.stringify({
                  for_membership_id: histSub.value,
                  started_at: new Date(startInput.value).toISOString(),
                  ended_at: new Date(endInput.value).toISOString(),
                  note: noteInput.value,
                  tags: histTags.getTags(),
                }),
              });
              status.textContent = "Historical lockup saved.";
              startInput.value = "";
              endInput.value = "";
              noteInput.value = "";
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Add historical lockup"));
      }
      stack.appendChild(manualCard);

      stack.appendChild(el("button", {
        className: "ghost-btn",
        onClick: () => navigate(`/dynamic/${dynamicId}/chastity`),
      }, "Back to chastity"));
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderChastityRulesPanel(dynamicId, settings, limitProposals, { onChanged, onError }) {
  const subs = settings.submissives || [];
  const wrap = el("div", { className: "stack" });

  const enrollCard = el("details", { className: "card stack", open: true }, [
    el("summary", {}, "Chastity availability"),
    el("p", { className: "muted" }, "When the Chastity feature is on, tracking is available for each submissive unless the keyholder turns it off here. To disable the whole module, use Menu → Features (submissives can request that via Dom-controlled settings)."),
  ]);

  function saveSubSettings(subId, enabled, maxHours) {
    return api(`/dynamics/${dynamicId}/chastity/settings`, {
      method: "PUT",
      body: JSON.stringify({
        membership_id: subId,
        chastity_enabled: enabled,
        chastity_max_lock_hours: maxHours,
      }),
    });
  }

  if (!subs.length) {
    enrollCard.appendChild(el("p", { className: "muted" }, "Add a submissive partner before configuring chastity."));
  } else if (settings.you_are_dominant) {
    subs.forEach((sub) => {
      const enabled = el("input", { type: "checkbox" });
      enabled.checked = sub.chastity_enabled;
      const maxSelect = el("select");
      (settings.max_lock_presets || []).forEach((preset) => {
        const value = preset.hours === null ? "null" : String(preset.hours);
        const option = el("option", { value }, preset.label);
        if (preset.hours === (sub.chastity_max_lock_hours ?? 72)) option.selected = true;
        maxSelect.appendChild(option);
      });
      const block = el("div", { className: "stack" }, [
        el("label", { className: "checkbox-label" }, [
          enabled,
          ` Chastity available for ${sub.display_name}`,
        ]),
        el("label", {}, ["Max lock time", maxSelect]),
        el("button", {
          className: "primary-btn",
          type: "button",
          onClick: async () => {
            try {
              const hours = maxSelect.value === "null" ? null : parseInt(maxSelect.value, 10);
              await saveSubSettings(sub.membership_id, enabled.checked, hours);
              onChanged?.();
            } catch (err) {
              onError?.(err.message);
            }
          },
        }, "Save"),
      ]);
      enrollCard.appendChild(block);
    });
  } else {
    const selfSub = subs.find((s) => s.membership_id === settings.you_membership_id);
    if (!selfSub) {
      enrollCard.appendChild(el("p", { className: "muted" }, "Chastity availability is controlled by your keyholder."));
    } else if (selfSub.chastity_enabled) {
      enrollCard.appendChild(el("p", { className: "muted" }, `Chastity is available for you. Max lock: ${selfSub.chastity_max_lock_hours == null ? "no limit" : `${selfSub.chastity_max_lock_hours}h`}.`));
    } else {
      enrollCard.appendChild(el("p", { className: "muted" }, "The keyholder has disabled chastity tracking for you. Ask them to re-enable it here, or to turn the Chastity feature off entirely in Menu → Features if you want the module hidden."));
    }
  }
  wrap.appendChild(enrollCard);

  const agreementsCard = el("details", { className: "card stack", open: true }, [
    el("summary", {}, "Lock time agreements"),
    el("p", { className: "muted" }, "Submissives can propose maximum lock durations. The keyholder approves or rejects."),
  ]);
  const pendingProposals = (limitProposals || []).filter((p) => p.status === "pending");
  if (!pendingProposals.length) {
    agreementsCard.appendChild(el("p", { className: "muted" }, "No pending limit proposals."));
  }
  pendingProposals.forEach((proposal) => {
    const row = el("div", { className: "stack" }, [
      el("strong", {}, `${proposal.for_display_name}: ${proposal.proposed_max_hours}h max`),
      el("p", { className: "muted" }, `Proposed by ${proposal.proposed_by_display_name}`),
      proposal.rationale ? el("p", {}, proposal.rationale) : null,
    ]);
    if (settings.you_are_dominant) {
      row.appendChild(el("div", { className: "row" }, [
        el("button", {
          className: "primary-btn",
          type: "button",
          onClick: async () => {
            await api(`/dynamics/${dynamicId}/chastity/limit-proposals/${proposal.id}/approve`, { method: "POST" });
            onChanged?.();
          },
        }, "Approve"),
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: async () => {
            await api(`/dynamics/${dynamicId}/chastity/limit-proposals/${proposal.id}/reject`, { method: "POST" });
            onChanged?.();
          },
        }, "Reject"),
      ]));
    }
    agreementsCard.appendChild(row);
  });
  if (!settings.you_are_dominant) {
    const selfSub = subs.find((s) => s.membership_id === settings.you_membership_id);
    if (selfSub?.chastity_enabled) {
      const propHours = el("select");
      (settings.max_lock_presets || []).forEach((preset) => {
        if (preset.hours == null) return;
        propHours.appendChild(el("option", { value: String(preset.hours) }, preset.label));
      });
      const propNote = el("input", { placeholder: "Why this limit? (optional)" });
      agreementsCard.appendChild(el("label", {}, ["Propose new max lock time", propHours]));
      agreementsCard.appendChild(el("label", {}, ["Rationale", propNote]));
      agreementsCard.appendChild(el("button", {
        className: "ghost-btn",
        type: "button",
        onClick: async () => {
          try {
            await api(`/dynamics/${dynamicId}/chastity/limit-proposals`, {
              method: "POST",
              body: JSON.stringify({
                for_membership_id: selfSub.membership_id,
                proposed_max_hours: parseInt(propHours.value, 10),
                rationale: propNote.value,
              }),
            });
            onChanged?.();
          } catch (err) {
            onError?.(err.message);
          }
        },
      }, "Submit proposal"));
    }
  }
  wrap.appendChild(agreementsCard);
  return wrap;
}

function renderGroundRules(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading agreements..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/agreements`),
    loadDynamic(dynamicId),
    api(`/dynamics/${dynamicId}/chastity/settings`).catch(() => null),
    api(`/dynamics/${dynamicId}/chastity/limit-proposals`).catch(() => []),
  ])
    .then(([bundle, , chastitySettings, limitProposals]) => {
      const error = el("div", { className: "error hidden" });
      const newTitle = el("input", { placeholder: "Title (e.g. Safewords, Limits, Protocol)" });
      const newContent = el("textarea", { placeholder: "Agreement text..." });

      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Ground rules"),
        el("p", { className: "muted" }, "Agreements, chastity availability, and lock-time limits. Anyone can propose agreements; only the keyholder approves. The keyholder can disable chastity for a submissive instantly."),
        el("p", { className: "muted" }, `${bundle.approved_count} approved · ${bundle.pending_count} pending`),
        error,
      ]);

      if (chastitySettings) {
        stack.appendChild(renderChastityRulesPanel(dynamicId, chastitySettings, limitProposals || [], {
          onChanged: () => renderGroundRules(dynamicId),
          onError: (msg) => {
            error.textContent = msg;
            error.classList.remove("hidden");
          },
        }));
      }

      const suggestStatus = el("p", { className: "muted" });
      stack.appendChild(el("button", {
        className: "ghost-btn",
        type: "button",
        onClick: async () => {
          suggestStatus.textContent = "Generating suggestions…";
          try {
            const result = await api(`/dynamics/${dynamicId}/agreements/suggest`, { method: "POST" });
            if (!result.ready) {
              suggestStatus.textContent = result.reason || "Not ready yet.";
              return;
            }
            if (!result.items.length) {
              suggestStatus.textContent = result.reason || "No suggestions returned.";
              return;
            }
            suggestStatus.textContent = `Generated ${result.items.length} suggestion(s) — review and add below.`;
            result.items.forEach((item) => {
              list.prepend(
                el("div", { className: "card stack suggested-agreement" }, [
                  el("strong", {}, item.title),
                  el("p", {}, item.content),
                  el("button", {
                    className: "ghost-btn",
                    type: "button",
                    onClick: () => {
                      newTitle.value = item.title;
                      newContent.value = item.content;
                      newTitle.scrollIntoView({ behavior: "smooth" });
                    },
                  }, "Use as new agreement"),
                ])
              );
            });
          } catch (err) {
            suggestStatus.textContent = err.message;
          }
        },
      }, "Suggested ground rules"));
      stack.appendChild(suggestStatus);

      const list = el("div", { className: "stack" });

      function paintList() {
        list.replaceChildren();
        if (!bundle.agreements.length) {
          list.appendChild(el("p", { className: "muted" }, "No agreements yet. Add your first one below."));
          return;
        }
        bundle.agreements.forEach((agreement) => {
          const card = el("div", { className: "card stack" }, [
            el("div", { className: "row" }, [
              el("strong", {}, agreement.title || "Agreement"),
              agreement.has_approved
                ? el("span", { className: "pill ok" }, "Approved")
                : el("span", { className: "pill pending" }, "Awaiting approval"),
            ]),
          ]);

          if (agreement.has_approved) {
            card.appendChild(el("p", {}, agreement.approved_content));
          }

          if (agreement.has_pending) {
            card.appendChild(
              el("div", { className: "stack" }, [
                el("span", { className: "pill pending" }, "Pending change"),
                el("p", { className: "muted" }, `Proposed by ${agreement.pending_by_display_name || "partner"}`),
                el("p", {}, agreement.pending_content),
              ])
            );
            if (bundle.you_are_dominant) {
              card.appendChild(
                el("div", { className: "row" }, [
                  el("button", {
                    className: "primary-btn",
                    onClick: async () => {
                      await api(`/dynamics/${dynamicId}/agreements/${agreement.id}/approve`, { method: "POST" });
                      renderGroundRules(dynamicId);
                    },
                  }, "Approve"),
                  el("button", {
                    className: "ghost-btn",
                    onClick: async () => {
                      await api(`/dynamics/${dynamicId}/agreements/${agreement.id}/reject`, { method: "POST" });
                      renderGroundRules(dynamicId);
                    },
                  }, "Reject"),
                ])
              );
            }
          }

          const editTitle = el("input", { value: agreement.title || "" });
          const editContent = el("textarea", {});
          editContent.value = agreement.has_pending
            ? agreement.pending_content
            : agreement.has_approved
              ? agreement.approved_content
              : "";

          card.appendChild(
            el("details", {}, [
              el("summary", {}, "Propose edit"),
              el("div", { className: "stack" }, [
                el("label", {}, ["Title", editTitle]),
                el("label", {}, ["Text", editContent]),
                el("button", {
                  className: "ghost-btn",
                  onClick: async () => {
                    await api(`/dynamics/${dynamicId}/agreements/${agreement.id}`, {
                      method: "PUT",
                      body: JSON.stringify({
                        title: editTitle.value,
                        content: editContent.value,
                        approve_now: false,
                      }),
                    });
                    renderGroundRules(dynamicId);
                  },
                }, "Submit edit for approval"),
                bundle.you_are_dominant
                  ? el("button", {
                    className: "primary-btn",
                    onClick: async () => {
                      await api(`/dynamics/${dynamicId}/agreements/${agreement.id}`, {
                        method: "PUT",
                        body: JSON.stringify({
                          title: editTitle.value,
                          content: editContent.value,
                          approve_now: true,
                        }),
                      });
                      renderGroundRules(dynamicId);
                    },
                  }, "Save and approve")
                  : null,
              ]),
            ])
          );

          if (bundle.you_are_dominant || !agreement.has_approved) {
            card.appendChild(
              el("button", {
                className: "ghost-btn",
                onClick: async () => {
                  if (!confirm("Remove this agreement?")) return;
                  await api(`/dynamics/${dynamicId}/agreements/${agreement.id}`, { method: "DELETE" });
                  renderGroundRules(dynamicId);
                },
              }, "Remove")
            );
          }

          list.appendChild(card);
        });
      }

      paintList();

      stack.appendChild(list);
      stack.appendChild(
        el("div", { className: "card stack" }, [
          el("h2", {}, "Add agreement"),
          el("label", {}, ["Title", newTitle]),
          el("label", {}, ["Text", newContent]),
          el("button", {
            className: "primary-btn",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api(`/dynamics/${dynamicId}/agreements`, {
                  method: "POST",
                  body: JSON.stringify({
                    title: newTitle.value,
                    content: newContent.value,
                    approve_now: false,
                  }),
                });
                newTitle.value = "";
                newContent.value = "";
                renderGroundRules(dynamicId);
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Submit for approval"),
          bundle.you_are_dominant
            ? el("button", {
              className: "ghost-btn",
              onClick: async () => {
                await api(`/dynamics/${dynamicId}/agreements`, {
                  method: "POST",
                  body: JSON.stringify({
                    title: newTitle.value,
                    content: newContent.value,
                    approve_now: true,
                  }),
                });
                newTitle.value = "";
                newContent.value = "";
                renderGroundRules(dynamicId);
              },
            }, "Add and approve now")
            : null,
        ])
      );

      stack.appendChild(error);
      stack.appendChild(
        el("button", {
          className: "ghost-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}`),
        }, "Back to dynamic")
      );
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderActs(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading acts..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/acts`),
    api(`/dynamics/${dynamicId}/acts/catalog`).catch(() => []),
    api(`/dynamics/${dynamicId}/assistant/status`),
    api(`/dynamics/${dynamicId}/core-knowledge/me/act-focus-options`).catch(() => []),
    loadDynamic(dynamicId),
  ])
    .then(([acts, catalog, status, focusOptions]) => {
      const you = state.currentDynamic.partners.find((p) => p.is_you);
      const active = acts.find((a) => a.status === "active");
      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Tasks & acts"),
        renderTasksActsSwitcher(dynamicId, "acts"),
        el("p", { className: "muted" }, "AI-generated acts based on your interviews. Pick a category that fits what you're willing to do."),
      ]);

      const error = el("div", { className: "error hidden" });
      const selectedFocus = new Set(focusOptions.map((o) => o.key));
      let selectedActType = catalog[0]?.id || "";

      if (catalog.length) {
        const catalogCard = el("div", { className: "card stack" }, [
          el("h2", {}, "Act types"),
          el("p", { className: "muted" }, "Categories generated from both partners' interviews."),
        ]);
        const typeRow = el("div", { className: "tag-filter-row break-type-picker" });
        catalog.forEach((cat) => {
          const btn = el("button", {
            type: "button",
            className: `tag-chip ${selectedActType === cat.id ? "active" : ""}`,
            onClick: (e) => {
              e.preventDefault();
              selectedActType = cat.id;
              typeRow.querySelectorAll(".tag-chip").forEach((chip) => chip.classList.remove("active"));
              btn.classList.add("active");
              desc.textContent = cat.description || "";
              examples.replaceChildren(
                ...(cat.example_acts || []).map((ex) => el("li", {}, ex))
              );
            },
          }, cat.title);
          typeRow.appendChild(btn);
        });
        const selectedCat = catalog.find((c) => c.id === selectedActType) || catalog[0];
        const desc = el("p", { className: "muted" }, selectedCat?.description || "");
        const examples = el("ul", { className: "muted" }, ...(selectedCat?.example_acts || []).map((ex) => el("li", {}, ex)));
        catalogCard.appendChild(typeRow);
        catalogCard.appendChild(desc);
        if (selectedCat?.example_acts?.length) catalogCard.appendChild(examples);
        if (you?.role === "dominant" && status.llm_configured) {
          catalogCard.appendChild(el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api(`/dynamics/${dynamicId}/acts/catalog/generate`, { method: "POST" });
                renderActs(dynamicId);
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Regenerate act types"));
        }
        stack.appendChild(catalogCard);
      } else if (status.your_interview_completed && status.partner_interview_completed && status.llm_configured) {
        stack.appendChild(el("div", { className: "card" }, [
          el("p", {}, "Both interviews are done. Generate act types from what you shared."),
          el("button", {
            className: "primary-btn",
            type: "button",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api(`/dynamics/${dynamicId}/acts/catalog/generate`, { method: "POST" });
                renderActs(dynamicId);
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Generate act types"),
        ]));
      }

      if (!status.your_interview_completed) {
        stack.appendChild(
          el("div", { className: "card" }, [
            el("p", {}, "Complete your dynamic interview before requesting acts."),
            el("button", {
              className: "primary-btn",
              onClick: () => navigate(`/dynamic/${dynamicId}/interview`),
            }, "Start interview"),
          ])
        );
      } else if (you?.role === "submissive" && !active && status.llm_configured) {
        const focusCard = el("div", { className: "card stack" }, [
          el("h2", {}, "Emphasize in this act"),
          el("p", { className: "muted" }, "Pick which parts of your core knowledge should shape the request."),
        ]);
        if (!focusOptions.length) {
          focusCard.appendChild(
            el("p", { className: "muted" }, "Submit core knowledge first."),
            el("button", {
              className: "ghost-btn",
              onClick: () => navigate(`/dynamic/${dynamicId}/knowledge/core`),
            }, "Fill out core knowledge")
          );
        } else {
          focusOptions.forEach((option) => {
            const checkbox = el("input", { type: "checkbox" });
            checkbox.checked = true;
            checkbox.addEventListener("change", () => {
              if (checkbox.checked) selectedFocus.add(option.key);
              else selectedFocus.delete(option.key);
            });
            focusCard.appendChild(
              el("label", { className: "row" }, [checkbox, option.label])
            );
          });
          focusCard.appendChild(
            el("button", {
              className: "primary-btn",
              onClick: async () => {
                error.classList.add("hidden");
                if (!selectedFocus.size) {
                  error.textContent = "Select at least one focus area.";
                  error.classList.remove("hidden");
                  return;
                }
                if (catalog.length && !selectedActType) {
                  error.textContent = "Choose an act type.";
                  error.classList.remove("hidden");
                  return;
                }
                try {
                  await api(`/dynamics/${dynamicId}/acts`, {
                    method: "POST",
                    body: JSON.stringify({
                      knowledge_focus: [...selectedFocus],
                      act_type_id: selectedActType,
                    }),
                  });
                  renderActs(dynamicId);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Request new act")
          );
        }
        stack.appendChild(focusCard);
      }

      if (!status.llm_configured) {
        stack.appendChild(el("div", { className: "card" }, "Configure your AI provider in Settings to enable acts."));
      }

      if (active) {
        if (active.act_type_title) {
          stack.appendChild(el("p", { className: "muted" }, `Type: ${active.act_type_title}`));
        }
        const card = el("div", { className: "card stack" }, [
          el("span", { className: "pill pending" }, "Active"),
          el("p", {}, active.hint_text),
        ]);
        if (you?.role === "submissive") {
          const response = el("textarea", { placeholder: "What did you do? How did it feel?" });
          const rating = el("input", { type: "number", min: "1", max: "5", placeholder: "Rating 1-5 (optional)" });
          card.appendChild(response);
          card.appendChild(rating);
          card.appendChild(
            el("button", {
              className: "primary-btn",
              onClick: async () => {
                try {
                  await api(`/acts/${active.id}/respond`, {
                    method: "PATCH",
                    body: JSON.stringify({
                      response_text: response.value,
                      rating: rating.value ? Number(rating.value) : null,
                    }),
                  });
                  renderActs(dynamicId);
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
              },
            }, "Mark complete")
          );
        }
        stack.appendChild(card);
      }

      const completed = acts.filter((a) => a.status === "completed" || a.status === "verified");
      completed.forEach((act) => {
        const card = el("div", { className: "card stack" }, [
          el("span", { className: `pill ${act.status === "verified" ? "ok" : "pending"}` }, act.status),
          el("p", {}, act.hint_text),
          act.sub_response_text ? el("p", { className: "muted" }, act.sub_response_text) : null,
        ]);
        if (you?.role === "dominant" && act.status === "completed") {
          const notes = el("textarea", { placeholder: "Optional feedback" });
          card.appendChild(notes);
          card.appendChild(
            el("div", { className: "row" }, [
              el("button", {
                className: "primary-btn",
                onClick: async () => {
                  await api(`/acts/${act.id}/verify`, {
                    method: "PATCH",
                    body: JSON.stringify({ approved: true, notes: notes.value }),
                  });
                  renderActs(dynamicId);
                },
              }, "Approve"),
              el("button", {
                className: "ghost-btn",
                onClick: async () => {
                  await api(`/acts/${act.id}/verify`, {
                    method: "PATCH",
                    body: JSON.stringify({ approved: false, notes: notes.value }),
                  });
                  renderActs(dynamicId);
                },
              }, "Needs work"),
            ])
          );
        }
        const convertRec = el("select");
        [["weekly", "Weekly"], ["daily", "Daily"], ["monthly", "Monthly"]].forEach(([v, l]) => {
          convertRec.appendChild(el("option", { value: v }, l));
        });
        card.appendChild(el("label", {}, ["Recurrence", convertRec]));
        card.appendChild(
          el("button", {
            className: "ghost-btn",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api(`/acts/${act.id}/convert-to-task`, {
                  method: "POST",
                  body: JSON.stringify({ recurrence: convertRec.value }),
                });
                navigate(`/dynamic/${dynamicId}/tasks`);
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Convert to repeating task")
        );
        stack.appendChild(card);
      });

      stack.appendChild(error);
      stack.appendChild(
        el("button", {
          className: "ghost-btn",
          onClick: () => navigate(`/dynamic/${dynamicId}/track`),
        }, "Back to tracking")
      );
      setViewContent(stack);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderFeatureSettings(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading features..."));
  Promise.all([
    api(`/dynamics/${dynamicId}/features`),
    api(`/dynamics/${dynamicId}/policy`).catch(() => null),
    loadDynamic(dynamicId),
  ])
    .then(([features, policy]) => {
      const youAreDominant = policy?.you_are_dominant === true;
      const error = el("div", { className: "error hidden" });
      const status = el("p", { className: "muted" });
      const checks = {};
      const list = el("div", { className: "stack" });
      list.appendChild(el("p", { className: "muted" }, "Core items stay on. Turn optional features off when you do not need them."));
      list.appendChild(el("div", { className: "card stack" }, [
        el("strong", {}, "Always included"),
        el("p", { className: "muted" }, features.core.map((id) => {
          const item = allFacetItems().find((f) => f.id === id);
          return item?.title || id;
        }).join(" · ")),
      ]));

      const optionalCard = el("div", { className: "card stack" }, [
        el("strong", {}, "Optional features"),
      ]);
      features.optional.forEach((feature) => {
        const box = el("input", { type: "checkbox" });
        box.checked = feature.enabled;
        checks[feature.id] = box;
        optionalCard.appendChild(
          el("label", { className: "checkbox-label" }, [box, feature.title])
        );
      });
      list.appendChild(optionalCard);

      const actions = [
        el("h1", {}, "Application features"),
        list,
        status,
        error,
      ];
      if (youAreDominant) {
        actions.push(el("button", {
          className: "primary-btn",
          onClick: async () => {
            error.classList.add("hidden");
            try {
              const enabled_optional = [];
              Object.entries(checks).forEach(([id, box]) => {
                if (!box.checked) return;
                enabled_optional.push(id);
                const meta = features.optional.find((f) => f.id === id);
                if (meta?.paired_with) enabled_optional.push(meta.paired_with);
              });
              const updated = await api(`/dynamics/${dynamicId}/features`, {
                method: "PUT",
                body: JSON.stringify({ enabled_optional: [...new Set(enabled_optional)] }),
              });
              if (state.currentDynamic?.id === dynamicId) {
                state.currentDynamic.enabled_features = updated.enabled;
              }
              status.textContent = "Saved. Hidden features no longer appear in the menu.";
              updateBottomNav();
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Save features"));
      } else {
        actions.push(el("p", { className: "muted" }, "Changes need keyholder approval — submit a request below."));
        actions.push(el("button", {
          className: "primary-btn",
          onClick: async () => {
            error.classList.add("hidden");
            try {
              const dirty = [];
              features.optional.forEach((feature) => {
                const box = checks[feature.id];
                if (!box || box.checked === feature.enabled) return;
                dirty.push({
                  settingKey: `features.${feature.id}`,
                  settingLabel: `Feature: ${feature.title}`,
                  requestedValue: box.checked,
                });
              });
              if (!dirty.length) {
                status.textContent = "No changes.";
                return;
              }
              for (const d of dirty) {
                await postSettingsChangeRequest({
                  dynamicId,
                  settingKey: d.settingKey,
                  settingLabel: d.settingLabel,
                  requestedValue: d.requestedValue,
                  note: "From Application features page",
                });
              }
              status.textContent = "Request sent to keyholder.";
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Submit settings change"));
      }
      actions.push(el("button", {
        className: "ghost-btn",
        onClick: () => navigate(`/dynamic/${dynamicId}`),
      }, "Back to dynamic"));
      setViewContent(el("div", { className: "stack" }, actions));
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

function renderGear(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading gear..."));
  let activeCategory = "vanilla_toys";

  function paint(bundle) {
    const error = el("div", { className: "error hidden" });
    const stack = el("div", { className: "stack" }, [
      el("h1", {}, "Gear"),
      el("p", { className: "muted" }, "Mark what you have and what you want. Catalog includes Artebu-style bondage gear plus common and premium toys."),
      el("p", { className: "muted" }, `${bundle.owned_count} owned · ${bundle.want_count} wanted`),
    ]);

    const tabs = el("div", { className: "tabs" });
    bundle.categories.forEach((cat) => {
      const btn = el("button", {
        className: `tab ${cat.id === activeCategory ? "active" : ""}`,
        type: "button",
        onClick: () => {
          activeCategory = cat.id;
          load();
        },
      }, cat.label);
      tabs.appendChild(btn);
    });
    stack.appendChild(tabs);

    const activeMeta = bundle.categories.find((c) => c.id === activeCategory);
    if (activeMeta?.description) {
      stack.appendChild(el("p", { className: "muted" }, activeMeta.description));
    }

    const customName = el("input", { placeholder: "Custom item name" });
    const customNotes = el("input", { placeholder: "Notes (optional)" });
    stack.appendChild(el("div", { className: "card stack" }, [
      el("strong", {}, "Add custom item"),
      customName,
      customNotes,
      el("button", {
        className: "primary-btn",
        type: "button",
        onClick: async () => {
          if (!customName.value.trim()) return;
          error.classList.add("hidden");
          try {
            await api(`/dynamics/${dynamicId}/gear`, {
              method: "POST",
              body: JSON.stringify({
                category: activeCategory,
                name: customName.value.trim(),
                notes: customNotes.value.trim(),
                owned: true,
                want: false,
              }),
            });
            customName.value = "";
            customNotes.value = "";
            load();
          } catch (err) {
            error.textContent = err.message;
            error.classList.remove("hidden");
          }
        },
      }, "Add to inventory"),
    ]));

    const customItems = bundle.inventory.filter((item) => item.is_custom && item.category === activeCategory);
    if (customItems.length) {
      const customList = el("div", { className: "stack" }, [el("h2", {}, "Your custom items")]);
      customItems.forEach((item) => {
        customList.appendChild(el("div", { className: "card stack gear-item" }, [
          el("div", { className: "row" }, [
            el("strong", {}, item.name),
            el("button", {
              className: "ghost-btn",
              type: "button",
              onClick: async () => {
                await api(`/dynamics/${dynamicId}/gear/${item.id}`, { method: "DELETE" });
                load();
              },
            }, "Remove"),
          ]),
          item.notes ? el("p", { className: "muted" }, item.notes) : null,
          el("div", { className: "row wrap gear-flags" }, [
            el("label", { className: "checkbox-label" }, [
              el("input", {
                type: "checkbox",
                checked: item.owned,
                onChange: async (e) => {
                  await api(`/dynamics/${dynamicId}/gear/${item.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({ owned: e.target.checked }),
                  });
                  load();
                },
              }),
              "Owned",
            ]),
            el("label", { className: "checkbox-label" }, [
              el("input", {
                type: "checkbox",
                checked: item.want,
                onChange: async (e) => {
                  await api(`/dynamics/${dynamicId}/gear/${item.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({ want: e.target.checked }),
                  });
                  load();
                },
              }),
              "Want",
            ]),
          ]),
        ]));
      });
      stack.appendChild(customList);
    }

    const catalog = bundle.catalog.filter((item) => item.category === activeCategory);
    const premium = catalog.filter((item) => item.tier === "premium");
    const common = catalog.filter((item) => item.tier !== "premium");

    function renderCatalogGroup(title, items) {
      if (!items.length) return;
      const group = el("div", { className: "stack" }, [el("h2", {}, title)]);
      items.forEach((item) => {
        group.appendChild(el("div", { className: "card stack gear-item" }, [
          el("div", { className: "row" }, [
            el("strong", {}, item.name),
            item.tier === "premium" ? el("span", { className: "pill" }, "Premium") : null,
          ]),
          item.notes ? el("p", { className: "muted" }, item.notes) : null,
          el("div", { className: "row wrap gear-flags" }, [
            el("label", { className: "checkbox-label" }, [
              el("input", {
                type: "checkbox",
                checked: item.owned,
                onChange: async (e) => {
                  error.classList.add("hidden");
                  try {
                    await api(`/dynamics/${dynamicId}/gear`, {
                      method: "POST",
                      body: JSON.stringify({
                        catalog_item_id: item.id,
                        owned: e.target.checked,
                        want: item.want,
                      }),
                    });
                    load();
                  } catch (err) {
                    error.textContent = err.message;
                    error.classList.remove("hidden");
                  }
                },
              }),
              "Owned",
            ]),
            el("label", { className: "checkbox-label" }, [
              el("input", {
                type: "checkbox",
                checked: item.want,
                onChange: async (e) => {
                  error.classList.add("hidden");
                  try {
                    await api(`/dynamics/${dynamicId}/gear`, {
                      method: "POST",
                      body: JSON.stringify({
                        catalog_item_id: item.id,
                        owned: item.owned,
                        want: e.target.checked,
                      }),
                    });
                    load();
                  } catch (err) {
                    error.textContent = err.message;
                    error.classList.remove("hidden");
                  }
                },
              }),
              "Want",
            ]),
          ]),
        ]));
      });
      stack.appendChild(group);
    }

    renderCatalogGroup("Catalog", common);
    renderCatalogGroup("Premium / high-end", premium);
    stack.appendChild(error);
    stack.appendChild(el("button", {
      className: "ghost-btn",
      onClick: () => navigate(`/dynamic/${dynamicId}/knowledge`),
    }, "Back to knowledge"));
    setViewContent(stack);
  }

  function load() {
    api(`/dynamics/${dynamicId}/gear?category=${encodeURIComponent(activeCategory)}`)
      .then(paint)
      .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
  }

  load();
}

function renderVault(dynamicId) {
  setViewContent(el("p", { className: "muted" }, "Loading image vault..."));
  const revealed = new Set();

  async function paint(images) {
    const error = el("div", { className: "error hidden" });
    const grid = el("div", { className: "vault-grid" });
    const fileInput = el("input", { type: "file", accept: "image/*", className: "hidden" });
    const cameraInput = el("input", {
      type: "file",
      accept: "image/*",
      capture: "environment",
      className: "hidden",
    });

    if (!images.length) {
      grid.appendChild(el("p", { className: "muted" }, "No images yet. Chat photos are saved here encrypted, or upload below."));
    }

    for (const image of images) {
      const decrypted = await decryptVaultPayload(dynamicId, image.image_encrypted);
      const card = el("div", { className: "card stack vault-card" });
      if (!decrypted) {
        card.appendChild(el("p", { className: "muted" }, "Encrypted — set up the chat E2E key in Settings to view."));
      } else {
        const img = el("img", {
          className: `vault-image ${image.image_blurred && !revealed.has(image.id) ? "blurred" : ""}`,
          src: decrypted,
          alt: image.title || "Vault image",
        });
        if (image.image_blurred) {
          attachBlurReveal(img, { id: image.id, revealedSet: revealed });
        }
        card.appendChild(img);
      }
      card.appendChild(el("p", { className: "muted" }, image.title || "Untitled"));
      card.appendChild(el("p", { className: "muted" }, new Date(image.created_at).toLocaleString()));
      card.appendChild(el("div", { className: "row wrap" }, [
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: async () => {
            await api(`/dynamics/${dynamicId}/vault/${image.id}`, {
              method: "PATCH",
              body: JSON.stringify({ image_blurred: !image.image_blurred }),
            });
            load();
          },
        }, image.image_blurred ? "Unblur by default" : "Blur by default"),
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: async () => {
            if (!confirm("Delete this vault image?")) return;
            await api(`/dynamics/${dynamicId}/vault/${image.id}`, { method: "DELETE" });
            load();
          },
        }, "Delete"),
      ]));
      grid.appendChild(card);
    }

    async function uploadVaultFile(file) {
      if (!file) return;
      error.classList.add("hidden");
      try {
        await ensureChatCryptoKey(dynamicId, { createIfMissing: false });
        const dataUrl = await readImageFile(file);
        const encrypted = await encryptVaultPayload(dynamicId, dataUrl);
        await api(`/dynamics/${dynamicId}/vault`, {
          method: "POST",
          body: JSON.stringify({
            title: file.name || "Upload",
            image_encrypted: encrypted,
            image_blurred: localStorage.getItem(chatBlurStorage()) !== "false",
          }),
        });
        load();
      } catch (err) {
        error.textContent = err.message;
        error.classList.remove("hidden");
      }
    }

    fileInput.addEventListener("change", async () => {
      const file = fileInput.files?.[0];
      fileInput.value = "";
      await uploadVaultFile(file);
    });
    cameraInput.addEventListener("change", async () => {
      const file = cameraInput.files?.[0];
      cameraInput.value = "";
      await uploadVaultFile(file);
    });

    setViewContent(el("div", { className: "stack" }, [
      el("h1", {}, "Image vault"),
      el("p", { className: "muted" }, "Private images from chat. Blur reveal follows Chat settings (hold / 5s / session). When Encrypted chat is on, images use the shared chat key."),
      el("div", { className: "row wrap" }, [
        el("button", {
          className: "primary-btn",
          type: "button",
          onClick: () => openInAppCamera({
            onCapture: (file) => uploadVaultFile(file),
            onFallback: () => cameraInput.click(),
          }),
        }, "Take photo"),
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => fileInput.click(),
        }, "Upload image"),
      ]),
      fileInput,
      cameraInput,
      grid,
      error,
      el("button", {
        className: "ghost-btn",
        onClick: () => navigate(`/dynamic/${dynamicId}/track`),
      }, "Back to tracking"),
    ]));
  }

  function load() {
    api(`/dynamics/${dynamicId}/vault`)
      .then((images) => paint(images))
      .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
  }

  load();
}

/**
 * In-app photo capture using getUserMedia — avoids handing off to the OS camera app.
 * Falls back to onFallback() (typically a native file input with capture=environment)
 * when getUserMedia is unavailable, denied, or errors out.
 */
async function openInAppCamera({ onCapture, onFallback } = {}) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    if (onFallback) onFallback();
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment" },
      audio: false,
    });
  } catch {
    if (onFallback) onFallback();
    return;
  }

  const video = el("video", { autoplay: true, playsinline: true, muted: true, className: "in-app-camera-video" });
  video.srcObject = stream;
  const captureBtn = el("button", { type: "button", className: "primary-btn" }, "📷 Capture");
  const cancelBtn = el("button", { type: "button", className: "ghost-btn" }, "Cancel");
  const backdrop = el("div", { className: "modal-backdrop in-app-camera-modal" });
  const card = el("div", { className: "card stack in-app-camera-card" }, [
    video,
    el("div", { className: "row wrap" }, [captureBtn, cancelBtn]),
  ]);
  backdrop.appendChild(card);
  document.body.appendChild(backdrop);

  let done = false;
  function cleanup() {
    if (done) return;
    done = true;
    stream.getTracks().forEach((track) => track.stop());
    backdrop.remove();
  }

  cancelBtn.addEventListener("click", cleanup);
  backdrop.addEventListener("click", (ev) => {
    if (ev.target === backdrop) cleanup();
  });

  captureBtn.addEventListener("click", () => {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 720;
    canvas.height = video.videoHeight || 960;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      cleanup();
      if (!blob) return;
      const file = new File([blob], `photo-${Date.now()}.jpg`, { type: "image/jpeg" });
      if (onCapture) onCapture(file);
    }, "image/jpeg", 0.92);
  });
}

function parseChatActionBody(body, dynamicId) {
  const text = String(body || "");
  const re = /\[\[ubetra:([^|\]]+)\|([^\]]+)\]\]/g;
  const nodes = [];
  let last = 0;
  let match;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push(text.slice(last, match.index));
    }
    const path = match[1].trim();
    const label = match[2].trim() || "Open";
    nodes.push(
      el(
        "button",
        {
          className: "chat-action-link",
          type: "button",
          onClick: () => navigate(path.startsWith("/") ? path : `/${path}`),
        },
        label
      )
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) {
    nodes.push(text.slice(last));
  }
  if (!nodes.length) {
    nodes.push(text);
  }
  return nodes;
}

function parseSystemEventBody(body) {
  let text = String(body || "");
  let fromLabel = null;
  const fromMatch = text.match(/^\[\[from:([^\]]+)\]\]\s*/);
  if (fromMatch) {
    fromLabel = fromMatch[1].trim();
    text = text.slice(fromMatch[0].length);
  }
  return { fromLabel, text };
}

function settingsHelp(text) {
  const tip = el("p", { className: "muted settings-help hidden" }, text);
  const btn = el("button", {
    type: "button",
    className: "settings-help-btn",
    title: "Help",
    onClick: (e) => {
      e.preventDefault();
      e.stopPropagation();
      tip.classList.toggle("hidden");
    },
  }, "?");
  return el("span", { className: "settings-help-wrap" }, [btn, tip]);
}

function settingsSection(title, children, { id = "", open = false, help = "" } = {}) {
  const body = (Array.isArray(children) ? children : [children]).filter(Boolean);
  const summaryKids = [title];
  if (help) summaryKids.push(settingsHelp(help));
  const details = el("details", {
    className: "card stack settings-section",
    ...(open ? { open: true } : {}),
    ...(id ? { id: `settings-${id}` } : {}),
  }, [
    el("summary", { className: "settings-section-title" }, summaryKids),
    ...body,
  ]);
  return details;
}

function buildSettingsSetupChecklist({ user, llmSettings, googleStatus, dynamics, providers }) {
  const items = [];
  if (!user?.biological_sex) {
    items.push({
      id: "sex",
      title: "Set biological sex",
      why: "Needed for Playtime scene anatomy context.",
      focus: "account",
    });
  }
  if (!user?.email_set) {
    items.push({
      id: "email",
      title: "Add account email",
      why: "Required to sign in (and for MFA codes when enabled).",
      focus: "account",
    });
  }
  if (!dynamics?.length) {
    items.push({
      id: "dynamic",
      title: "Join or create a dynamic",
      why: "Almost every feature needs a relationship space.",
      focus: "dynamics",
    });
  }
  if (!llmSettings?.configured && !llmSettings?.shared_configured && !dynamics?.some((d) => d.shared_llm_configured)) {
    items.push({
      id: "llm",
      title: "Configure AI provider / API key",
      why: "Powers the assistant, suggested agreements, acts, and interviews.",
      focus: "ai",
    });
  }
  if (googleStatus?.configured && !googleStatus?.connected) {
    items.push({
      id: "google",
      title: "Connect Google Tasks (optional)",
      why: "Lets discreet code-word tasks sync to Google Tasks.",
      focus: "integrations",
    });
  }
  if (!items.length) return null;
  const card = el("div", { className: "card stack settings-checklist", id: "settings-setup" }, [
    el("h2", {}, "Finish setup"),
    el("p", { className: "muted" }, "These are still unset. Tap one to jump to that section."),
  ]);
  items.forEach((item) => {
    card.appendChild(el("button", {
      type: "button",
      className: "choice-btn",
      onClick: () => {
        const target = document.getElementById(`settings-${item.focus}`);
        if (target) {
          target.open = true;
          target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      },
    }, [
      el("span", { className: "facet-title" }, item.title),
      el("span", { className: "facet-subtitle" }, item.why),
    ]));
  });
  return card;
}

function openSettingsRequestModal({ dynamicId, settingKey, settingLabel, requestedValue = null, onSent = null }) {
  const backdrop = el("div", { className: "modal-backdrop" });
  const note = el("textarea", {
    rows: "4",
    placeholder: "Why should this change? (optional)",
  });
  const error = el("p", { className: "error hidden" });
  const card = el("div", { className: "card stack modal-card" }, [
    el("h3", {}, "Request setting change"),
    el("p", {}, settingLabel || settingKey),
    requestedValue != null
      ? el("p", { className: "muted" }, `Requested value: ${typeof requestedValue === "object" ? JSON.stringify(requestedValue) : String(requestedValue)}`)
      : null,
    el("label", { className: "stack" }, ["Message to keyholder", note]),
    error,
    el("div", { className: "row" }, [
      el("button", {
        type: "button",
        className: "primary-btn",
        onClick: async () => {
          error.classList.add("hidden");
          try {
            await postSettingsChangeRequest({
              dynamicId,
              settingKey,
              settingLabel,
              requestedValue,
              note: note.value.trim(),
            });
            backdrop.remove();
            if (typeof onSent === "function") onSent();
            else if (confirm("Request sent. Open chat?")) navigate(`/chat/${dynamicId}`);
          } catch (err) {
            error.textContent = err.message;
            error.classList.remove("hidden");
          }
        },
      }, "Send request"),
      el("button", {
        type: "button",
        className: "ghost-btn",
        onClick: () => backdrop.remove(),
      }, "Cancel"),
    ]),
  ]);
  backdrop.appendChild(card);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) backdrop.remove();
  });
  document.body.appendChild(backdrop);
}

async function postSettingsChangeRequest({
  dynamicId,
  settingKey,
  settingLabel,
  requestedValue = null,
  note = "",
}) {
  if (!dynamicId) throw new Error("No dynamic selected");
  await api(`/dynamics/${dynamicId}/settings-requests`, {
    method: "POST",
    body: JSON.stringify({
      setting_key: settingKey,
      setting_label: settingLabel || settingKey,
      requested_value: requestedValue,
      note: note || "",
    }),
  });
}

/** Locked = keyholder-controlled, but still editable so a sub can stage a change for Submit. */
function lockedSettingsWrap({ locked, children }) {
  if (!locked) return children;
  const wrap = el("div", {
    className: "settings-locked settings-needs-approval",
    title: "Keyholder-controlled — change here, then Submit settings change",
  });
  if (Array.isArray(children)) wrap.append(...children.filter(Boolean));
  else if (children) wrap.appendChild(children);
  return wrap;
}

function createSettingsSaveBar({ isSubmissive }) {
  const error = el("div", { className: "error hidden" });
  const status = el("p", { className: "muted hidden" });
  const btn = el("button", {
    type: "button",
    className: "primary-btn settings-save-btn",
  }, "Save");
  const bar = el("div", { className: "settings-save-bar hidden", id: "settings-save-bar" }, [
    status,
    error,
    btn,
  ]);
  const sections = [];

  function anyDirty() {
    return sections.some((s) => {
      try {
        return !!s.isDirty();
      } catch {
        return false;
      }
    });
  }

  function anyApprovalNeeded() {
    if (!isSubmissive) return false;
    return sections.some((s) => {
      try {
        return !!s.isDirty() && typeof s.needsApproval === "function" && !!s.needsApproval();
      } catch {
        return false;
      }
    });
  }

  function refresh() {
    const dirty = anyDirty();
    bar.classList.toggle("hidden", !dirty);
    document.body.classList.toggle("settings-save-visible", dirty);
    btn.textContent = anyApprovalNeeded() ? "Submit settings change" : "Save";
  }

  function register(section) {
    if (section) sections.push(section);
  }

  function bind(root) {
    if (!root) return;
    root.addEventListener("input", refresh);
    root.addEventListener("change", refresh);
  }

  btn.addEventListener("click", async () => {
    error.classList.add("hidden");
    status.classList.add("hidden");
    btn.disabled = true;
    const notes = [];
    const willSubmit = anyApprovalNeeded();
    try {
      for (const section of sections) {
        if (!section.isDirty()) continue;
        const result = await section.save();
        if (result) notes.push(result);
      }
      status.textContent = notes.filter(Boolean).join(" · ") || (willSubmit ? "Submitted." : "Saved.");
      status.classList.remove("hidden");
      refresh();
    } catch (err) {
      error.textContent = err.message || String(err);
      error.classList.remove("hidden");
    } finally {
      btn.disabled = false;
      refresh();
    }
  });

  return { bar, register, refresh, bind, error, status };
}

function renderChat(dynamicId) {
  const id = dynamicId || getActiveDynamicId();
  if (!id) {
    renderHome();
    return;
  }
  state.activeDynamicId = id;
  setViewContent(el("p", { className: "muted" }, "Loading chat..."));

  let settings = { retain_history: false, e2e_enabled: false, expire_hours: 720, system_events: true, push_enabled: true, you_are_dominant: false };
  const revealedImages = new Set();
  let blurImages = localStorage.getItem(chatBlurStorage()) !== "false";
  let blurMode = getChatBlurMode();
  const logsKey = () => `ubetra_chat_show_logs_${id}`;
  const imagesKey = () => `ubetra_chat_show_images_${id}`;
  let showActivityLogs = localStorage.getItem(logsKey()) !== "false";
  let showImages = localStorage.getItem(imagesKey()) !== "false";
  let lastMessages = [];
  let typingPartners = [];
  let refreshE2eDeviceBanner = () => {};

  async function paintMessages(messages) {
    lastMessages = messages || lastMessages;
    const chatLog = document.getElementById("partner-chat-log");
    if (!chatLog) return;
    const youAreDom = !!settings.you_are_dominant;
    const nodes = [];
    for (const msg of lastMessages) {
      if (msg.message_type === "image" && !showImages) continue;
      if (msg.message_type === "system" || msg.action === "settings_request_resolved" || msg.action === "image_unlock_resolved") {
        if (!showActivityLogs) continue;
        const parsed = parseSystemEventBody(msg.body);
        const path = msg.payload?.path;
        const row = el(
          path ? "button" : "div",
          {
            className: "chat-log-line" + (path ? " chat-system-clickable" : ""),
            type: path ? "button" : undefined,
            onClick: path
              ? () => navigate(path.startsWith("/") ? path : `/${path}`)
              : undefined,
          },
          [
            el("strong", {}, parsed.fromLabel || msg.sender_display_name),
            " ",
            ...parseChatActionBody(parsed.text, id),
          ]
        );
        nodes.push(row);
        continue;
      }

      if (msg.action === "settings_request") {
        const payload = msg.payload || {};
        const pending = !payload.status || payload.status === "pending";
        const card = el("div", {
          className: `chat-bubble ${msg.is_yours ? "user" : "assistant"} chat-settings-request`,
        }, [
          el("span", { className: "muted chat-sender" }, msg.sender_display_name),
          el("strong", {}, "Settings request"),
          el("p", {}, payload.setting_label || msg.body),
          payload.note ? el("p", { className: "muted" }, payload.note) : null,
          payload.requested_value != null
            ? el("p", { className: "muted" }, `Requested: ${String(payload.requested_value)}`)
            : null,
        ]);
        if (pending && youAreDom && !msg.is_yours) {
          const actions = el("div", { className: "row chat-request-actions" }, [
            el("button", {
              type: "button",
              className: "primary-btn",
              onClick: async () => {
                try {
                  await api(
                    `/dynamics/${id}/chat/messages/${msg.id}/resolve-settings-request`,
                    {
                      method: "POST",
                      body: JSON.stringify({
                        decision: "approve",
                        value: payload.requested_value,
                      }),
                    }
                  );
                  await refresh();
                } catch (err) {
                  const errEl = document.querySelector(".chat-screen .error");
                  if (errEl) {
                    errEl.textContent = err.message;
                    errEl.classList.remove("hidden");
                  }
                }
              },
            }, "Change setting"),
            el("button", {
              type: "button",
              className: "ghost-btn",
              onClick: async () => {
                try {
                  await api(
                    `/dynamics/${id}/chat/messages/${msg.id}/resolve-settings-request`,
                    {
                      method: "POST",
                      body: JSON.stringify({ decision: "deny" }),
                    }
                  );
                  await refresh();
                } catch (err) {
                  const errEl = document.querySelector(".chat-screen .error");
                  if (errEl) {
                    errEl.textContent = err.message;
                    errEl.classList.remove("hidden");
                  }
                }
              },
            }, "Deny"),
          ]);
          card.appendChild(actions);
        } else if (!pending) {
          card.appendChild(el("p", { className: "muted" }, `Status: ${payload.status}`));
        }
        nodes.push(card);
        continue;
      }

      if (msg.action === "image_unlock_request") {
        const payload = msg.payload || {};
        const pending = !payload.status || payload.status === "pending";
        const card = el("div", {
          className: `chat-bubble ${msg.is_yours ? "user" : "assistant"} chat-settings-request`,
        }, [
          el("span", { className: "muted chat-sender" }, msg.sender_display_name),
          el("strong", {}, "Image unlock request"),
          el("p", {}, msg.body || "Permission requested to view a locked image."),
        ]);
        if (pending && youAreDom && !msg.is_yours) {
          card.appendChild(
            el("div", { className: "row chat-request-actions" }, [
              el("button", {
                type: "button",
                className: "primary-btn",
                onClick: async () => {
                  try {
                    await api(`/dynamics/${id}/chat/messages/${msg.id}/resolve-image-unlock`, {
                      method: "POST",
                      body: JSON.stringify({ decision: "approve" }),
                    });
                    await refresh();
                  } catch (err) {
                    const errEl = document.querySelector(".chat-screen .error");
                    if (errEl) {
                      errEl.textContent = err.message;
                      errEl.classList.remove("hidden");
                    }
                  }
                },
              }, "Unlock"),
              el("button", {
                type: "button",
                className: "ghost-btn",
                onClick: async () => {
                  try {
                    await api(`/dynamics/${id}/chat/messages/${msg.id}/resolve-image-unlock`, {
                      method: "POST",
                      body: JSON.stringify({ decision: "deny" }),
                    });
                    await refresh();
                  } catch (err) {
                    const errEl = document.querySelector(".chat-screen .error");
                    if (errEl) {
                      errEl.textContent = err.message;
                      errEl.classList.remove("hidden");
                    }
                  }
                },
              }, "Deny"),
            ])
          );
        } else if (!pending) {
          card.appendChild(el("p", { className: "muted" }, `Status: ${payload.status}`));
        }
        nodes.push(card);
        continue;
      }

      let text = msg.body;
      if (msg.body_encrypted) {
        try {
          text = await decryptChatText(id, msg.body_encrypted);
        } catch {
          text = "[Unable to decrypt — open Settings]";
        }
      }
      if (msg.message_type === "image" && msg.image_data) {
        const permissionBlocked =
          !!msg.image_locked && !msg.image_unlock_granted && !msg.is_yours;
        const shouldBlur =
          permissionBlocked ||
          (!!msg.image_blurred && !revealedImages.has(msg.id));
        let imageSrc = msg.image_data;
        if (
          typeof imageSrc === "string" &&
          !imageSrc.startsWith("data:") &&
          !imageSrc.startsWith("blob:") &&
          !imageSrc.startsWith("http")
        ) {
          try {
            const decrypted = await decryptVaultPayload(id, imageSrc);
            imageSrc = decrypted || "[Unable to decrypt image]";
          } catch {
            imageSrc = "[Unable to decrypt image]";
          }
        }
        const isDecryptError = typeof imageSrc === "string" && imageSrc.startsWith("[Unable");
        const bubbleKids = [
          el("span", { className: "muted chat-sender" }, msg.sender_display_name),
        ];
        if (isDecryptError) {
          bubbleKids.push(el("p", { className: "muted" }, imageSrc));
        } else {
          const img = el("img", {
            className: `chat-image ${shouldBlur ? "blurred" : ""}`,
            src: imageSrc,
            alt: "Shared image",
          });
          bubbleKids.push(img);
          if (permissionBlocked) {
            attachBlurReveal(img, { id: msg.id, revealedSet: revealedImages, locked: true });
            bubbleKids.push(
              el("p", { className: "muted" }, "Locked — permission required to view."),
              el("button", {
                type: "button",
                className: "ghost-btn",
                onClick: async () => {
                  try {
                    await api(`/dynamics/${id}/chat/messages/${msg.id}/request-image-unlock`, {
                      method: "POST",
                      body: "{}",
                    });
                    await refresh();
                  } catch (err) {
                    const errEl = document.querySelector(".chat-screen .error");
                    if (errEl) {
                      errEl.textContent = err.message;
                      errEl.classList.remove("hidden");
                    }
                  }
                },
              }, "Request unlock")
            );
          } else if (msg.image_blurred && !revealedImages.has(msg.id)) {
            attachBlurReveal(img, { id: msg.id, revealedSet: revealedImages });
          }
        }
        if (msg.image_locked && msg.is_yours) {
          bubbleKids.push(
            el(
              "p",
              { className: "muted" },
              msg.image_unlock_granted ? "Locked image · unlocked for partner" : "Locked image · awaiting permission"
            )
          );
        }
        nodes.push(
          el("div", { className: `chat-bubble ${msg.is_yours ? "user" : "assistant"}` }, bubbleKids)
        );
      } else {
        nodes.push(
          el("div", { className: `chat-bubble ${msg.is_yours ? "user" : "assistant"}` }, [
            el("span", { className: "muted chat-sender" }, msg.sender_display_name),
            isCryptoPlaceholder(text) ? renderCryptoPlaceholder(id, text) : el("span", {}, text),
          ])
        );
      }
    }
    chatLog.replaceChildren(...nodes);
    requestAnimationFrame(() => {
      chatLog.scrollTop = chatLog.scrollHeight;
    });
  }

  async function sendText(input) {
    const text = input.value.trim();
    if (!text) return;
    const body = { message_type: "text", body: text, body_encrypted: "" };
    if (settings.e2e_enabled) {
      if (!cryptoSubtleAvailable()) {
        throw encryptionUnavailableError();
      }
      body.body = "";
      body.body_encrypted = await encryptChatText(id, text);
    }
    await api(`/dynamics/${id}/chat/messages`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    input.value = "";
  }

  async function sendImage(file, { locked = false } = {}) {
    const data = await readImageFile(file);
    let image_data = data;
    if (settings.e2e_enabled) {
      if (!cryptoSubtleAvailable()) throw encryptionUnavailableError();
      await ensureChatCryptoKey(id, { createIfMissing: false });
      image_data = await encryptChatText(id, data);
    } else {
      await ensureChatCryptoKey(id, { createIfMissing: false }).catch(() => null);
    }
    const vault_image_encrypted = await encryptVaultPayload(id, data);
    const lock = !!locked && !!settings.you_are_dominant;
    await api(`/dynamics/${id}/chat/messages`, {
      method: "POST",
      body: JSON.stringify({
        message_type: "image",
        image_data,
        image_blurred: blurImages || lock,
        image_locked: lock,
        vault_image_encrypted,
        save_to_vault: true,
      }),
    });
  }

  function askDomImageOptions(file) {
    return new Promise((resolve) => {
      const backdrop = el("div", { className: "chat-image-sheet-backdrop" });
      const sheet = el("div", { className: "chat-image-sheet card stack" }, [
        el("strong", {}, "Send image"),
        el("p", { className: "muted" }, file?.name || "Choose how to send this photo."),
        el("button", {
          type: "button",
          className: "primary-btn",
          onClick: () => {
            backdrop.remove();
            resolve({ locked: false });
          },
        }, "Send"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            backdrop.remove();
            resolve({ locked: true });
          },
        }, "Lock — partner needs permission"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            backdrop.remove();
            resolve(null);
          },
        }, "Cancel"),
      ]);
      backdrop.appendChild(sheet);
      backdrop.addEventListener("click", (ev) => {
        if (ev.target === backdrop) {
          backdrop.remove();
          resolve(null);
        }
      });
      document.body.appendChild(backdrop);
    });
  }

  function refresh() {
    return Promise.all([
      api(`/dynamics/${id}/chat/settings`),
      api(`/dynamics/${id}/chat/messages`),
    ]).then(([chatSettings, messages]) => {
      settings = chatSettings;
      refreshE2eDeviceBanner();
      return paintMessages(messages);
    });
  }

  Promise.all([
    api(`/dynamics/${id}/chat/settings`),
    api(`/dynamics/${id}/chat/messages`),
    loadDynamic(id),
  ])
    .then(async ([chatSettings, messages]) => {
      settings = chatSettings;
      if (chatSettings.e2e_enabled) {
        await ensureChatCryptoKey(id, {
          createIfMissing: !chatSettings.key_configured,
        }).catch(() => null);
      }
      if (chatSettings.push_enabled) {
        ensureChatPushEnabled().catch(() => {});
      }
      const error = el("div", { className: "error hidden" });
      const chatLog = el("div", { className: "chat-log", id: "partner-chat-log" });
      const input = el("textarea", {
        className: "chat-input",
        placeholder: "Message your partner…",
        rows: "1",
      });
      const imageInput = el("input", {
        type: "file",
        accept: "image/*",
        className: "hidden",
      });
      const cameraInput = el("input", {
        type: "file",
        accept: "image/*",
        capture: "environment",
        className: "hidden",
      });
      const attachBtn = el("button", {
        className: "chat-icon-btn",
        type: "button",
        title: "Attach or take photo",
        "aria-label": "Attach or take photo",
      }, "+");
      const sendBtn = el("button", {
        className: "chat-send-btn",
        type: "button",
        title: "Send",
        "aria-label": "Send message",
      }, "➤");

      const typingEl = el("div", { className: "chat-typing hidden", "aria-live": "polite" }, [
        el("span", { className: "chat-typing-dots" }, [
          el("i"),
          el("i"),
          el("i"),
        ]),
      ]);

      const composer = el("div", { className: "stack chat-composer-wrap" }, [
        typingEl,
        el("div", { className: "chat-composer" }, [attachBtn, input, sendBtn]),
      ]);

      function paintTyping() {
        if (!typingPartners.length) {
          typingEl.classList.add("hidden");
          return;
        }
        typingEl.classList.remove("hidden");
        const names = typingPartners.map((t) => t.display_name).filter(Boolean);
        const label = names.length ? `${names.join(", ")} typing` : "typing";
        typingEl.title = label;
      }

      async function handleSend() {
        error.classList.add("hidden");
        error.replaceChildren();
        try {
          await sendText(input);
          await refresh();
        } catch (err) {
          error.textContent = err.message;
          error.classList.remove("hidden");
          if (err.code === "ENCRYPTION_UNAVAILABLE" || err.code === "E2E_KEY_MISSING") {
            error.appendChild(document.createTextNode(" "));
            error.appendChild(
              el(
                "button",
                {
                  type: "button",
                  className: "link-btn",
                  onClick: () => navigate(`/settings?dynamic=${id}&focus=chat`),
                },
                "Open Settings"
              )
            );
            refreshE2eDeviceBanner();
          }
        }
      }

      sendBtn.addEventListener("click", handleSend);
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          handleSend();
        }
      });

      async function handleImageFile(file) {
        if (!file) return;
        error.classList.add("hidden");
        try {
          let locked = false;
          if (settings.you_are_dominant) {
            const choice = await askDomImageOptions(file);
            if (!choice) return;
            locked = !!choice.locked;
          }
          await sendImage(file, { locked });
          await refresh();
        } catch (err) {
          error.textContent = err.message;
          error.classList.remove("hidden");
        }
      }

      async function handlePickedImage(inputEl) {
        const file = inputEl.files?.[0];
        await handleImageFile(file);
        inputEl.value = "";
      }

      attachBtn.addEventListener("click", () => {
        const backdrop = el("div", { className: "chat-image-sheet-backdrop" });
        const sheet = el("div", { className: "chat-image-sheet card stack" }, [
          el("strong", {}, "Add photo"),
          el("button", {
            type: "button",
            className: "primary-btn",
            onClick: () => {
              backdrop.remove();
              openInAppCamera({
                onCapture: (file) => handleImageFile(file),
                onFallback: () => cameraInput.click(),
              });
            },
          }, "Take photo"),
          el("button", {
            type: "button",
            className: "ghost-btn",
            onClick: () => {
              backdrop.remove();
              imageInput.click();
            },
          }, "Choose from library"),
          el("button", {
            type: "button",
            className: "ghost-btn",
            onClick: () => backdrop.remove(),
          }, "Cancel"),
        ]);
        backdrop.appendChild(sheet);
        backdrop.addEventListener("click", (ev) => {
          if (ev.target === backdrop) backdrop.remove();
        });
        document.body.appendChild(backdrop);
      });
      imageInput.addEventListener("change", () => handlePickedImage(imageInput));
      cameraInput.addEventListener("change", () => handlePickedImage(cameraInput));

      let typingPingAt = 0;
      input.addEventListener("input", () => {
        const now = Date.now();
        if (now - typingPingAt < 1200) return;
        typingPingAt = now;
        api(`/dynamics/${id}/chat/typing`, { method: "POST", body: "{}" }).catch(() => {});
      });

      function syncToggleLabels() {
        logsToggle.textContent = showActivityLogs ? "Logs on" : "Logs off";
        logsToggle.title = showActivityLogs ? "Hide activity logs" : "Show activity logs";
        logsToggle.classList.toggle("active", showActivityLogs);
        imagesToggle.textContent = showImages ? "Images on" : "Images off";
        imagesToggle.title = showImages ? "Hide images" : "Show images";
        imagesToggle.classList.toggle("active", showImages);
      }

      const logsToggle = el("button", {
        className: `ghost-btn chat-mini-toggle ${showActivityLogs ? "active" : ""}`,
        type: "button",
        onClick: () => {
          showActivityLogs = !showActivityLogs;
          localStorage.setItem(logsKey(), showActivityLogs ? "true" : "false");
          if (panelLogsToggle) panelLogsToggle.checked = showActivityLogs;
          syncToggleLabels();
          paintMessages(lastMessages);
        },
      }, showActivityLogs ? "Logs on" : "Logs off");

      const imagesToggle = el("button", {
        className: `ghost-btn chat-mini-toggle ${showImages ? "active" : ""}`,
        type: "button",
        onClick: () => {
          showImages = !showImages;
          localStorage.setItem(imagesKey(), showImages ? "true" : "false");
          if (panelImagesToggle) panelImagesToggle.checked = showImages;
          syncToggleLabels();
          paintMessages(lastMessages);
        },
      }, showImages ? "Images on" : "Images off");
      syncToggleLabels();

      const settingsPanel = el("div", { className: "chat-settings-dropdown hidden" });
      const retainHistory = el("input", { type: "checkbox" });
      retainHistory.checked = settings.retain_history !== false;
      const e2eMode = el("input", { type: "checkbox" });
      e2eMode.checked = !!settings.e2e_enabled;
      const chatPushEnabled = el("input", { type: "checkbox" });
      chatPushEnabled.checked = settings.push_enabled !== false;
      const systemEvents = el("input", { type: "checkbox" });
      systemEvents.checked = settings.system_events !== false;
      const blurByDefault = el("input", { type: "checkbox" });
      blurByDefault.checked = blurImages;
      const blurModeSelect = el("select");
      [
        ["hold", "Press and hold to unblur"],
        ["timed5", "Unblur for 5 seconds"],
        ["session", "Unblur this session"],
      ].forEach(([v, l]) => {
        const o = el("option", { value: v }, l);
        if (v === blurMode) o.selected = true;
        blurModeSelect.appendChild(o);
      });
      const panelLogsToggle = el("input", { type: "checkbox" });
      panelLogsToggle.checked = showActivityLogs;
      const panelImagesToggle = el("input", { type: "checkbox" });
      panelImagesToggle.checked = showImages;
      panelLogsToggle.addEventListener("change", () => {
        showActivityLogs = panelLogsToggle.checked;
        localStorage.setItem(logsKey(), showActivityLogs ? "true" : "false");
        syncToggleLabels();
        paintMessages(lastMessages);
      });
      panelImagesToggle.addEventListener("change", () => {
        showImages = panelImagesToggle.checked;
        localStorage.setItem(imagesKey(), showImages ? "true" : "false");
        syncToggleLabels();
        paintMessages(lastMessages);
      });
      blurByDefault.addEventListener("change", () => {
        blurImages = blurByDefault.checked;
        localStorage.setItem(chatBlurStorage(), blurImages ? "true" : "false");
        blurModeSelect.disabled = !blurImages;
      });
      blurModeSelect.disabled = !blurImages;
      blurModeSelect.addEventListener("change", () => {
        blurMode = blurModeSelect.value;
        setChatBlurMode(blurMode);
        paintMessages(lastMessages);
      });
      const expireHours = el("input", {
        type: "number",
        min: "1",
        max: String(24 * 90),
        value: String(settings.expire_hours || 720),
      });
      const panelStatus = el("p", { className: "muted" }, "");
      const panelError = el("div", { className: "error hidden" });
      const isDom = !!settings.you_are_dominant;
      if (!cryptoSubtleAvailable() && e2eMode.checked) {
        panelStatus.textContent =
          "Web Crypto unavailable on this URL — turn off E2E or use https:// / localhost. Text and images need Web Crypto when Encrypted chat is on.";
      }

      function appendMaybeLocked(labelNode, settingKey, settingLabel) {
        if (isDom) {
          settingsPanel.appendChild(labelNode);
          return;
        }
        settingsPanel.appendChild(
          lockedSettingsWrap({
            locked: true,
            dynamicId: id,
            settingKey,
            settingLabel,
            requestedValue: true,
            children: labelNode,
          })
        );
      }

      if (!isDom) {
        const taskRequestBody = el("textarea", { rows: "3", placeholder: "Task you want to request…" });
        const taskRequestError = el("div", { className: "error hidden" });
        settingsPanel.append(
          el("div", { className: "card stack" }, [
            el("strong", {}, "Request a task"),
            el("p", { className: "muted" }, "Needs keyholder approval before you can complete it."),
            taskRequestBody,
            taskRequestError,
            el("button", {
              className: "primary-btn",
              type: "button",
              onClick: async () => {
                taskRequestError.classList.add("hidden");
                const content = taskRequestBody.value.trim();
                if (!content) {
                  taskRequestError.textContent = "Describe the task.";
                  taskRequestError.classList.remove("hidden");
                  return;
                }
                try {
                  await api(`/dynamics/${id}/tasks/items`, {
                    method: "POST",
                    body: JSON.stringify({ content }),
                  });
                  taskRequestBody.value = "";
                  settingsPanel.classList.add("hidden");
                  showToast("Task request sent to your keyholder.");
                } catch (err) {
                  taskRequestError.textContent = err.message;
                  taskRequestError.classList.remove("hidden");
                }
              },
            }, "Submit for approval"),
          ])
        );
      }
      settingsPanel.append(
        el("h3", {}, "Chat settings"),
        el("label", { className: "checkbox-label" }, [panelLogsToggle, " Show activity logs"]),
        el("label", { className: "checkbox-label" }, [panelImagesToggle, " Show images in chat"]),
        el("label", { className: "checkbox-label" }, [blurByDefault, " Blur shared images"]),
        el("label", {}, ["When blurred", blurModeSelect]),
        el(
          "p",
          { className: "muted" },
          "Session unblur resets on reload or leaving chat. When Encrypted chat is on, text and images both use the shared AES key."
        ),
      );
      appendMaybeLocked(
        el("label", { className: "checkbox-label" }, [retainHistory, " Keep forever on server (no auto-delete)"]),
        "chat.retain_history",
        "Keep forever on server (no auto-delete)"
      );
      settingsPanel.append(el("label", {}, ["Server cache (days worth of hours, if not forever)", expireHours]));
      settingsPanel.append(el("p", { className: "muted" }, "Default is 30 days (720 hours) so offline phones and other logged-in devices can sync. Encrypted messages stay as ciphertext on the server."));
      settingsPanel.append(el("label", { className: "checkbox-label" }, [e2eMode, " Encrypted chat (shared key)"]));
      settingsPanel.append(el("label", { className: "checkbox-label" }, [chatPushEnabled, " Push notifications"]));
      appendMaybeLocked(
        el("label", { className: "checkbox-label" }, [systemEvents, " Post activity logs to chat"]),
        "chat.system_events",
        "Post activity logs to chat"
      );
      settingsPanel.append(
        panelStatus,
        panelError,
        el("button", {
          className: "primary-btn",
          type: "button",
          onClick: async () => {
            panelError.classList.add("hidden");
            try {
              localStorage.setItem(chatBlurStorage(), blurByDefault.checked ? "true" : "false");
              blurImages = blurByDefault.checked;
              blurMode = blurModeSelect.value;
              setChatBlurMode(blurMode);
              if (e2eMode.checked) {
                if (!cryptoSubtleAvailable()) {
                  throw encryptionUnavailableError();
                }
                await ensureChatCryptoKey(id, {
                  createIfMissing: !settings.e2e_enabled || !settings.key_configured,
                });
              }
              settings = await api(`/dynamics/${id}/chat/settings`, {
                method: "PUT",
                body: JSON.stringify({
                  retain_history: retainHistory.checked,
                  e2e_enabled: e2eMode.checked,
                  expire_hours: parseInt(expireHours.value, 10) || 720,
                  system_events: systemEvents.checked,
                  push_enabled: chatPushEnabled.checked,
                }),
              });
              panelStatus.textContent = "Saved.";
              paintMessages(lastMessages);
            } catch (err) {
              panelError.textContent = err.message;
              panelError.classList.remove("hidden");
              if (err.code === "ENCRYPTION_UNAVAILABLE") {
                const link = el("button", {
                  type: "button",
                  className: "link-btn",
                  onClick: () => navigate(`/settings?dynamic=${id}`),
                }, "Open Settings → Privacy");
                panelError.appendChild(document.createTextNode(" "));
                panelError.appendChild(link);
              }
            }
          },
        }, "Save"),
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => navigate(`/settings?dynamic=${id}`),
        }, "Full settings…")
      );

      const featuresBtnChat = el("button", {
        className: "ghost-btn hub-features-btn chat-features-btn",
        type: "button",
        title: "Application features",
        "aria-label": "Application features",
        onClick: (e) => {
          e.stopPropagation();
          openAppFeaturesPanel(id, "chat");
        },
      }, "☰");

      const settingsBtnChat = el("button", {
        className: "ghost-btn chat-settings-link chat-hamburger",
        type: "button",
        title: "Chat settings",
        "aria-label": "Chat settings",
        onClick: (e) => {
          e.stopPropagation();
          settingsPanel.classList.toggle("hidden");
        },
      }, "⋯");

      const header = el("div", { className: "chat-header row" }, [
        el("div", {}, [
          el("h1", {}, "Chat"),
          el("p", { className: "muted" }, formatDynamicTitle(state.currentDynamic)),
        ]),
        el("div", { className: "chat-header-actions" }, [logsToggle, imagesToggle, featuresBtnChat, settingsBtnChat]),
      ]);

      const headerWrap = el("div", { className: "chat-header-wrap" }, [header, settingsPanel]);

      const e2eDeviceBanner = el("div", { className: "e2e-key-banner warn-banner hidden" });
      const e2eDevicePanel = el("div", { className: "card stack e2e-device-panel hidden" }, [
        e2eDeviceBanner,
        el("p", { className: "muted" }, "Encrypted chat uses a shared key on the server (like the AI key). Sign in on this device and open chat — it should sync automatically."),
        el("button", {
          type: "button",
          className: "primary-btn",
          onClick: async () => {
            error.classList.add("hidden");
            try {
              await ensureChatCryptoKey(id, { createIfMissing: false });
              refreshE2eDeviceBanner();
              await refresh();
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Sync encryption key"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => navigate(`/settings?dynamic=${id}&focus=chat`),
        }, "Open Privacy settings"),
      ]);

      async function refreshE2eDeviceBannerImpl() {
        if (!settings.e2e_enabled) {
          e2eDevicePanel.classList.add("hidden");
          return;
        }
        if (!hasChatCryptoKey(id)) {
          await ensureChatCryptoKey(id, { createIfMissing: false }).catch(() => null);
        }
        const needsKey = !!settings.e2e_enabled && !hasChatCryptoKey(id);
        e2eDevicePanel.classList.toggle("hidden", !needsKey);
        if (needsKey) {
          e2eDeviceBanner.classList.remove("hidden");
          e2eDeviceBanner.textContent = "Encrypted chat is on, but this device has not synced the shared key yet.";
        }
      }
      refreshE2eDeviceBanner = refreshE2eDeviceBannerImpl;
      await refreshE2eDeviceBanner();

      const screen = el("div", { className: "chat-screen" }, [
        headerWrap,
        e2eDevicePanel,
        chatLog,
        error,
        composer,
        imageInput,
        cameraInput,
      ]);
      viewEl.classList.add("chat-view");
      setViewContent(screen);
      document.addEventListener(
        "click",
        (ev) => {
          if (!settingsPanel.contains(ev.target) && !settingsBtnChat.contains(ev.target)) {
            settingsPanel.classList.add("hidden");
          }
        },
        { once: false }
      );
      await paintMessages(messages);
      paintTyping();

      let liveSig = "";
      let alive = true;
      async function liveTick() {
        if (!alive) return;
        try {
          const [msgs, presence] = await Promise.all([
            api(`/dynamics/${id}/chat/messages`),
            api(`/dynamics/${id}/chat/presence`).catch(() => ({ typing: [] })),
          ]);
          typingPartners = presence.typing || [];
          paintTyping();
          const sig = `${msgs.map((m) => m.id).join(",")}|${typingPartners.map((t) => t.membership_id).join(",")}`;
          if (sig !== liveSig) {
            liveSig = sig;
            await paintMessages(msgs);
            paintTyping();
          }
        } catch (_) {
          /* ignore transient poll errors */
        }
      }
      liveSig = `${(messages || []).map((m) => m.id).join(",")}|`;
      const liveTimer = setInterval(liveTick, 2200);
      const onPush = (ev) => {
        if (ev.detail?.dynamicId && ev.detail.dynamicId !== id) return;
        liveTick();
      };
      window.addEventListener("ubetra-chat-push", onPush);
      if (typeof window.__ubetraStopChatLive === "function") window.__ubetraStopChatLive();
      window.__ubetraStopChatLive = () => {
        alive = false;
        clearInterval(liveTimer);
        window.removeEventListener("ubetra-chat-push", onPush);
      };
    })
    .catch((err) => {
      viewEl.classList.remove("chat-view");
      setViewContent(el("p", { className: "error" }, err.message));
    });
}

function renderSettings() {
  viewEl.replaceChildren(el("p", { className: "muted" }, "Loading settings..."));
  const { query } = parseRoute();
  const initialDynamicId = query.get("dynamic") || getActiveDynamicId();
  const initialRedeemCode = query.get("redeem") || "";

  Promise.all([
    api(`/settings/llm${initialDynamicId ? `?dynamic_id=${encodeURIComponent(initialDynamicId)}` : ""}`),
    api("/settings/llm/providers"),
    api(`/settings/assistant${initialDynamicId ? `?dynamic_id=${encodeURIComponent(initialDynamicId)}` : ""}`),
    api("/settings/assistant/tones"),
    api("/dynamics"),
    api("/google/status").catch(() => ({ configured: false, connected: false, list_id: "@default" })),
    initialDynamicId
      ? api(`/dynamics/${initialDynamicId}/policy`).catch(() => null)
      : Promise.resolve(null),
    initialDynamicId
      ? api(`/dynamics/${initialDynamicId}/features`).catch(() => null)
      : Promise.resolve(null),
  ])
    .then(([settings, providers, assistantSettings, tones, dynamics, googleStatus, policy, featuresBundle]) => {
      if (dynamics.length) state.dynamics = dynamics;
      const providerMap = Object.fromEntries(providers.map((p) => [p.id, p]));
      const isSubmissive = !!(policy && policy.you_are_dominant === false);
      const draft = createSettingsSaveBar({ isSubmissive });
      const error = el("div", { className: "error hidden" });
      const status = el("p", { className: "muted" });
      const googleStatusLine = el("p", { className: "muted" });
      const googleFlag = query.get("google");
      if (googleFlag === "connected") {
        googleStatusLine.textContent = "Google Tasks connected.";
      } else if (googleFlag === "error") {
        googleStatusLine.textContent = "Google connection failed. Try again.";
      }

      const providerSelect = el("select");
      providers.forEach((provider) => {
        const option = el("option", { value: provider.id }, provider.label);
        if (provider.id === settings.provider) option.selected = true;
        providerSelect.appendChild(option);
      });

      const modelSelect = el("select");
      const modelCustom = el("input", {
        placeholder: "Or type a custom model name",
      });
      modelCustom.value = settings.model || "";

      const apiKeyInput = el("input", {
        type: "password",
        placeholder: settings.api_key_set
          ? `Saved key ${settings.api_key_hint || ""} — leave blank to keep`
          : "Paste API key",
        autocomplete: "off",
      });

      const description = el("p", { className: "muted" });

      function refreshProviderUi() {
        const selected = providerMap[providerSelect.value];
        description.textContent = selected?.description || "";
        modelSelect.replaceChildren();
        (selected?.models || []).forEach((model) => {
          const option = el("option", { value: model }, model);
          if (model === modelCustom.value) option.selected = true;
          modelSelect.appendChild(option);
        });
        const usingServer = providerSelect.value === "server";
        apiKeyInput.disabled = usingServer;
        if (usingServer) {
          apiKeyInput.value = "";
          apiKeyInput.placeholder = settings.server_env_configured
            ? `Server .env key ${settings.api_key_hint || "configured"}`
            : "Server .env key not set";
        }
      }

      providerSelect.addEventListener("change", refreshProviderUi);
      modelSelect.addEventListener("change", () => {
        modelCustom.value = modelSelect.value;
      });
      refreshProviderUi();

      function refreshLlmStatus() {
        const parts = [];
        if (settings.shared_configured || settings.active_key_source === "shared") {
          const hint = settings.shared_api_key_hint || settings.active_api_key_hint || "";
          const prov = settings.shared_provider || "";
          const model = settings.shared_model || "";
          parts.push(
            `Shared dynamic AI key active${prov || model ? ` · ${[prov, model].filter(Boolean).join(" / ")}` : ""}${hint ? ` ${hint}` : ""}`.trim()
          );
          parts.push("Both partners use this key for the assistant");
        } else if (settings.configured) {
          parts.push(`AI ready · ${settings.provider} / ${settings.model}`);
        } else {
          parts.push("AI not configured yet");
        }
        if (settings.shared_dynamics_count > 0 && !(settings.shared_configured || settings.active_key_source === "shared")) {
          parts.push(`${settings.shared_dynamics_count} dynamic(s) have a shared key on file`);
        }
        status.textContent = parts.join(" · ");
      }
      refreshLlmStatus();

      const assistantError = el("div", { className: "error hidden" });
      const assistantStatus = el("p", { className: "muted" });
      const toneSelect = el("select");
      tones.forEach((tone) => {
        const option = el("option", { value: tone.id }, tone.label);
        if (tone.id === assistantSettings.tone) option.selected = true;
        toneSelect.appendChild(option);
      });
      const toneDescription = el("p", { className: "muted" });
      const extraInstructions = el("textarea", {
        placeholder: "Optional: how you want the assistant domme to respond, boundaries to emphasize, etc.",
      });
      extraInstructions.value = assistantSettings.extra_instructions || "";
      const includeTracking = el("input", { type: "checkbox" });
      includeTracking.checked = assistantSettings.include_tracking !== false;

      function refreshToneUi() {
        const selected = tones.find((t) => t.id === toneSelect.value);
        toneDescription.textContent = selected?.description || "";
      }
      toneSelect.addEventListener("change", refreshToneUi);
      refreshToneUi();

      assistantStatus.textContent = assistantSettings.include_tracking
        ? "Assistant can see orgasm and chastity tracking in context"
        : "Tracking data hidden from assistant";

      const importStatus = el("p", { className: "muted hidden" });

      const privacyError = el("div", { className: "error hidden" });
      const privacyStatus = el("p", { className: "muted" });
      const privacyDynamic = el("select");
      const retainHistory = el("input", { type: "checkbox" });
      const e2eMode = el("input", { type: "checkbox" });
      const expireHours = el("select");
      [
        [24, "24 hours"],
        [72, "3 days"],
        [168, "1 week"],
        [336, "2 weeks"],
        [720, "30 days (default)"],
        [2160, "90 days"],
      ].forEach(([v, l]) => {
        expireHours.appendChild(el("option", { value: String(v) }, l));
      });
      expireHours.value = "720";
      const blurByDefault = el("input", { type: "checkbox" });
      blurByDefault.checked = localStorage.getItem(chatBlurStorage()) !== "false";
      const blurModeSelect = el("select");
      [
        ["hold", "Press and hold to unblur"],
        ["timed5", "Unblur for 5 seconds"],
        ["session", "Unblur this session"],
      ].forEach(([v, l]) => {
        const o = el("option", { value: v }, l);
        if (v === getChatBlurMode()) o.selected = true;
        blurModeSelect.appendChild(o);
      });
      blurModeSelect.disabled = !blurByDefault.checked;
      blurByDefault.addEventListener("change", () => {
        blurModeSelect.disabled = !blurByDefault.checked;
      });
      const systemEvents = el("input", { type: "checkbox" });
      systemEvents.checked = true;
      const chatPushEnabled = el("input", { type: "checkbox" });
      chatPushEnabled.checked = true;
      const pushDeviceEnabled = el("input", { type: "checkbox" });
      const pushDeviceStatus = el("p", { className: "muted" });
      const partnerEmail = el("input", { type: "email", placeholder: "partner@example.com" });
      const partnerPhone = el("input", { type: "tel", placeholder: "+1 555 123 4567" });
      const redeemCode = el("input", { placeholder: "8-character code" });
      redeemCode.value = initialRedeemCode;
      const shareCodeDisplay = el("p", { className: "muted hidden" });
      let privacyBaselineMeta = { keyConfigured: false };

      dynamics.forEach((d) => {
        privacyDynamic.appendChild(el("option", { value: d.id }, formatDynamicTitle(d)));
      });
      if (initialDynamicId) privacyDynamic.value = initialDynamicId;

      const e2eKeyBanner = el("div", { className: "e2e-key-banner muted" });
      const shareKeySection = el("div", { className: "stack" });
      const redeemKeySection = el("div", { className: "stack" });
      let e2eAdvancedReShare = null;

      function refreshE2eKeyUi() {
        const dynamicId = privacyDynamic.value;
        const hasCrypto = cryptoSubtleAvailable();
        const hasKey = !!(dynamicId && localStorage.getItem(chatKeyStorage(dynamicId)));
        const e2eOn = !!e2eMode.checked;
        e2eKeyBanner.classList.remove("ok-banner", "warn-banner", "muted");
        shareKeySection.classList.add("hidden");
        redeemKeySection.classList.add("hidden");
        if (e2eAdvancedReShare) e2eAdvancedReShare.classList.add("hidden");
        if (!dynamicId) {
          e2eKeyBanner.classList.add("muted");
          e2eKeyBanner.textContent = "Join a dynamic to set up chat encryption.";
          return;
        }
        if (!e2eOn) {
          e2eKeyBanner.classList.add("muted");
          e2eKeyBanner.textContent = "Encrypted chat is off. Turn it on once — the key is shared on the server for every signed-in device (same idea as the AI key).";
          return;
        }
        if (!hasCrypto) {
          e2eKeyBanner.classList.add("warn-banner");
          e2eKeyBanner.textContent = "Web Crypto unavailable — open the app over HTTPS (or localhost) to use encrypted text.";
          return;
        }
        if (hasKey) {
          e2eKeyBanner.classList.add("ok-banner");
          e2eKeyBanner.textContent = "Shared encryption key is active. Any device signed into this dynamic can decrypt chat.";
          if (e2eAdvancedReShare) e2eAdvancedReShare.classList.remove("hidden");
          return;
        }
        e2eKeyBanner.classList.add("warn-banner");
        e2eKeyBanner.textContent = "Encrypted chat is on, but this device has not synced the shared key yet. Save privacy settings or open Chat to sync.";
        if (e2eAdvancedReShare) e2eAdvancedReShare.classList.remove("hidden");
      }

      shareKeySection.append(
        el("h3", {}, "Share encryption key with partner"),
        el("p", { className: "muted" }, "Generates a one-time code (30 min). Send via email or text — the raw key is never included."),
        el("label", {}, ["Partner email", partnerEmail]),
        el("label", {}, ["Partner phone", partnerPhone]),
        el("div", { className: "row wrap" }, [
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: async () => {
              privacyError.classList.add("hidden");
              try {
                const dynamicId = await ensureE2eBeforeShare();
                savePartnerContact(dynamicId, {
                  email: partnerEmail.value.trim(),
                  phone: partnerPhone.value.trim(),
                });
                const key = localStorage.getItem(chatKeyStorage(dynamicId));
                const share = await shareChatKeySecure(dynamicId, key);
                const links = buildShareLinks(dynamicId, share.code, share.redeem_hint);
                shareCodeDisplay.textContent = `Code ${share.code} — expires ${new Date(share.expires_at).toLocaleTimeString()}`;
                shareCodeDisplay.classList.remove("hidden");
                if (partnerEmail.value.trim()) {
                  const mail = `mailto:${encodeURIComponent(partnerEmail.value.trim())}?subject=${encodeURIComponent("UBETRA chat key")}&body=${encodeURIComponent(links.message)}`;
                  window.location.href = mail;
                } else {
                  privacyStatus.textContent = "Share code created. Add partner email or copy the code.";
                }
                refreshE2eKeyUi();
              } catch (err) {
                privacyError.textContent = err.message;
                privacyError.classList.remove("hidden");
              }
            },
          }, "Email secure link"),
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: async () => {
              privacyError.classList.add("hidden");
              try {
                const dynamicId = await ensureE2eBeforeShare();
                savePartnerContact(dynamicId, {
                  email: partnerEmail.value.trim(),
                  phone: partnerPhone.value.trim(),
                });
                const key = localStorage.getItem(chatKeyStorage(dynamicId));
                const share = await shareChatKeySecure(dynamicId, key);
                const links = buildShareLinks(dynamicId, share.code, share.redeem_hint);
                shareCodeDisplay.textContent = `Code ${share.code} — expires ${new Date(share.expires_at).toLocaleTimeString()}`;
                shareCodeDisplay.classList.remove("hidden");
                const phone = partnerPhone.value.trim().replace(/\s/g, "");
                if (phone) {
                  window.location.href = `sms:${encodeURIComponent(phone)}?body=${encodeURIComponent(links.message)}`;
                } else {
                  privacyStatus.textContent = "Share code created. Add partner phone or copy the code.";
                }
                refreshE2eKeyUi();
              } catch (err) {
                privacyError.textContent = err.message;
                privacyError.classList.remove("hidden");
              }
            },
          }, "Text secure link"),
          el("button", {
            className: "ghost-btn",
            type: "button",
            onClick: async () => {
              privacyError.classList.add("hidden");
              try {
                const dynamicId = await ensureE2eBeforeShare();
                const key = localStorage.getItem(chatKeyStorage(dynamicId));
                const share = await shareChatKeySecure(dynamicId, key);
                const links = buildShareLinks(dynamicId, share.code, share.redeem_hint);
                await navigator.clipboard.writeText(links.message);
                shareCodeDisplay.textContent = `Copied! Code ${share.code}`;
                shareCodeDisplay.classList.remove("hidden");
                refreshE2eKeyUi();
              } catch (err) {
                privacyError.textContent = err.message;
                privacyError.classList.remove("hidden");
              }
            },
          }, "Copy link & code"),
        ]),
        shareCodeDisplay,
      );

      e2eAdvancedReShare = el("details", { className: "stack hidden" }, [
        el("summary", {}, "Legacy — one-time share codes"),
        el("p", { className: "muted" }, "Optional. New devices normally sync the shared key automatically when you sign in. Codes are only needed if an old device never uploaded its key."),
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: () => {
            shareKeySection.classList.remove("hidden");
            redeemKeySection.classList.remove("hidden");
          },
        }, "Show share & redeem controls"),
      ]);

      // Move advanced re-share into details by appending the same buttons... keep simple: always show share when no key; when has key show details with re-share
      redeemKeySection.append(
        el("h3", {}, "Redeem partner key"),
        el("label", {}, ["One-time code", redeemCode]),
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: async () => {
            privacyError.classList.add("hidden");
            const dynamicId = privacyDynamic.value;
            const code = redeemCode.value.trim();
            if (!dynamicId || !code) return;
            try {
              const result = await api(`/dynamics/${dynamicId}/chat/key-redeem`, {
                method: "POST",
                body: JSON.stringify({ code: code.toUpperCase() }),
              });
              localStorage.setItem(chatKeyStorage(dynamicId), result.key);
              if (!e2eMode.checked) {
                e2eMode.checked = true;
                await api(`/dynamics/${dynamicId}/chat/settings`, {
                  method: "PUT",
                  body: JSON.stringify({ e2e_enabled: true }),
                });
              }
              redeemCode.value = "";
              privacyStatus.textContent = "Partner key saved — encryption is ready on this device.";
              refreshE2eKeyUi();
            } catch (err) {
              privacyError.textContent = err.message;
              privacyError.classList.remove("hidden");
            }
          },
        }, "Redeem code"),
      );

      e2eMode.addEventListener("change", () => refreshE2eKeyUi());
      privacyDynamic.addEventListener("change", () => {
        loadPrivacyUi().then(() => refreshE2eKeyUi());
      });

      api("/push/status")
        .then(async (pushStatus) => {
          let localSub = null;
          try {
            const reg = await getPushRegistration();
            localSub = reg ? await reg.pushManager.getSubscription() : null;
          } catch {
            localSub = null;
          }
          pushDeviceEnabled.checked = !!localSub;
          const insecure =
            !window.isSecureContext &&
            location.hostname !== "localhost" &&
            location.hostname !== "127.0.0.1";
          if (insecure) {
            pushDeviceStatus.textContent =
              "Notifications require HTTPS. Use your public HTTPS URL — browsers lock notifications on plain http:// LAN addresses.";
            pushDeviceEnabled.disabled = true;
          } else if (!pushStatus.configured) {
            pushDeviceStatus.textContent = "Push not available on this server.";
            pushDeviceEnabled.disabled = true;
          } else if (localSub) {
            pushDeviceStatus.textContent = "This device is subscribed for chat notifications.";
          } else if (typeof Notification !== "undefined" && Notification.permission === "denied") {
            pushDeviceStatus.textContent = "Notifications blocked in browser settings.";
            pushDeviceEnabled.disabled = true;
          } else {
            pushDeviceStatus.textContent = "Enable to get notified when your partner messages you.";
          }
        })
        .catch(() => {
          pushDeviceStatus.textContent = "Could not load push status.";
        });

      pushDeviceEnabled.addEventListener("change", async () => {
        privacyError.classList.add("hidden");
        try {
          if (pushDeviceEnabled.checked) {
            await subscribeChatPush();
            pushDeviceStatus.textContent = isNativeApp()
              ? "This Android app is registered for FCM notifications."
              : "This device is subscribed for chat notifications.";
            if (isAndroidBrowser() && !isNativeApp()) {
              openAndroidPushSetupGuide();
            }
          } else {
            await unsubscribeChatPush();
            pushDeviceStatus.textContent = "Push notifications disabled on this device.";
          }
        } catch (err) {
          pushDeviceEnabled.checked = false;
          privacyError.textContent = err.message;
          privacyError.classList.remove("hidden");
        }
      });

      function loadPrivacyUi() {
        const dynamicId = privacyDynamic.value;
        if (!dynamicId) {
          privacyStatus.textContent = "Join a dynamic to configure chat privacy.";
          return Promise.resolve();
        }
        const contact = loadPartnerContact(dynamicId);
        partnerEmail.value = contact.email || "";
        partnerPhone.value = contact.phone || "";
        return api(`/dynamics/${dynamicId}/chat/settings`)
          .then(async (chatSettings) => {
            retainHistory.checked = chatSettings.retain_history;
            e2eMode.checked = chatSettings.e2e_enabled;
            expireHours.value = String(chatSettings.expire_hours || 720);
            expireHours.disabled = chatSettings.retain_history;
            systemEvents.checked = chatSettings.system_events !== false;
            chatPushEnabled.checked = chatSettings.push_enabled !== false;
            privacyStatus.textContent = chatSettings.retain_history
              ? "Messages stay on the server forever (all your devices can sync anytime)."
              : `Messages stay on the server for ${chatSettings.expire_hours || 720} hour(s) so offline / other devices can catch up, then auto-delete.`;
            if (chatSettings.e2e_enabled) {
              await ensureChatCryptoKey(dynamicId, {
                createIfMissing: !chatSettings.key_configured,
              }).catch(() => null);
            }
            privacyBaselineMeta = { keyConfigured: !!chatSettings.key_configured };
            refreshE2eKeyUi();
            if (typeof snapshotPrivacyBaseline === "function") {
              snapshotPrivacyBaseline();
              draft.refresh();
            }
          })
          .catch((err) => {
            privacyStatus.textContent = err.message;
            refreshE2eKeyUi();
          });
      }

      retainHistory.addEventListener("change", () => {
        expireHours.disabled = retainHistory.checked;
      });
      // privacyDynamic change already wired above with refreshE2eKeyUi
      loadPrivacyUi();

      async function ensureE2eBeforeShare() {
        const dynamicId = privacyDynamic.value;
        if (!dynamicId) throw new Error("Select a dynamic first");
        await ensureChatCryptoKey(dynamicId, {
          createIfMissing: !e2eMode.checked || !privacyBaselineMeta.keyConfigured,
        });
        if (!e2eMode.checked) {
          e2eMode.checked = true;
          await api(`/dynamics/${dynamicId}/chat/settings`, {
            method: "PUT",
            body: JSON.stringify({
                  retain_history: retainHistory.checked,
                  e2e_enabled: true,
                  expire_hours: parseInt(expireHours.value, 10),
                  system_events: systemEvents.checked,
                  push_enabled: chatPushEnabled.checked,
                }),
          });
        }
        return dynamicId;
      }

      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Settings"),
      ]);

      const usernameInput = el("input", {
        type: "text",
        value: state.user?.username || "",
        autocomplete: "username",
        maxlength: "64",
      });
      const usernamePassword = el("input", {
        type: "password",
        placeholder: "Current password",
        autocomplete: "current-password",
      });
      const usernameError = el("div", { className: "error hidden" });
      const usernameStatus = el(
        "p",
        { className: "muted" },
        state.user?.username ? `Current username: ${state.user.username}` : ""
      );
      stack.appendChild(el("div", { className: "card stack" }, [
        el("h2", {}, "Username"),
        el("p", { className: "muted" }, "Your name shown in dynamics. Sign-in uses email, not username."),
        usernameStatus,
        el("label", {}, ["Username", usernameInput]),
        el("label", {}, ["Confirm with password", usernamePassword]),
        usernameError,
      ]));
      let usernameBaseline = state.user?.username || "";
      draft.register({
        isDirty: () => usernameInput.value.trim() !== usernameBaseline,
        save: async () => {
          usernameError.classList.add("hidden");
          if (!usernamePassword.value) {
            throw new Error("Enter your password to change username.");
          }
          state.user = await api("/auth/username", {
            method: "PUT",
            body: JSON.stringify({
              username: usernameInput.value.trim(),
              password: usernamePassword.value,
            }),
          });
          usernamePassword.value = "";
          usernameInput.value = state.user.username;
          usernameBaseline = state.user.username;
          usernameStatus.textContent = `Current username: ${state.user.username}`;
          return "Username saved";
        },
      });

      const sexSelect = el("select");
      [
        ["", "Select…"],
        ["male", "Male"],
        ["female", "Female"],
        ["intersex", "Intersex"],
        ["prefer_not_to_say", "Prefer not to say"],
      ].forEach(([value, label]) => {
        const opt = el("option", { value }, label);
        if ((state.user?.biological_sex || "") === value) opt.selected = true;
        sexSelect.appendChild(opt);
      });
      const sexError = el("div", { className: "error hidden" });
      const sexStatus = el(
        "p",
        { className: "muted" },
        state.user?.biological_sex
          ? "Used for scene context and AI language."
          : "Required so Playtime can write scenes with the right anatomy context."
      );
      if (query.get("sex") === "1" && !state.user?.biological_sex) {
        sexStatus.textContent = "Please set your biological sex to continue.";
      }
      stack.appendChild(el("div", { className: "card stack" }, [
        el("h2", {}, "Biological sex"),
        sexStatus,
        el("label", {}, ["Sex", sexSelect]),
        sexError,
      ]));
      let sexBaseline = state.user?.biological_sex || "";
      draft.register({
        isDirty: () => sexSelect.value !== sexBaseline,
        save: async () => {
          sexError.classList.add("hidden");
          if (!sexSelect.value) throw new Error("Choose a biological sex option.");
          state.user = await api("/auth/sex", {
            method: "PUT",
            body: JSON.stringify({ biological_sex: sexSelect.value }),
          });
          sexBaseline = state.user.biological_sex || "";
          sexStatus.textContent = "Saved.";
          if (query.get("sex") === "1") navigateAfterAuth();
          return "Sex saved";
        },
      });

      const emailInput = el("input", {
        type: "email",
        value: state.user?.email || "",
        autocomplete: "email",
      });
      const emailPassword = el("input", {
        type: "password",
        placeholder: "Current password",
        autocomplete: "current-password",
      });
      const emailError = el("div", { className: "error hidden" });
      const emailStatus = el("p", { className: "muted" }, state.user?.email_set
        ? `Sign-in email: ${state.user.email}`
        : "Add an email so you can sign in.");
      stack.appendChild(el("div", { className: "card stack" }, [
        el("h2", {}, "Account email"),
        el("p", { className: "muted" }, "Used to sign in. Also receives one-time codes when MFA is on."),
        emailStatus,
        el("label", {}, ["Email", emailInput]),
        el("label", {}, ["Confirm with password", emailPassword]),
        emailError,
      ]));
      let emailBaseline = (state.user?.email || "").trim();
      draft.register({
        isDirty: () => emailInput.value.trim() !== emailBaseline,
        save: async () => {
          emailError.classList.add("hidden");
          if (!emailPassword.value) throw new Error("Enter your password to change email.");
          state.user = await api("/auth/email", {
            method: "PUT",
            body: JSON.stringify({
              email: emailInput.value.trim(),
              password: emailPassword.value,
            }),
          });
          emailPassword.value = "";
          emailBaseline = (state.user.email || "").trim();
          emailStatus.textContent = state.user.email_set
            ? `Sign-in email: ${state.user.email}`
            : "Add an email so you can sign in.";
          return "Email saved";
        },
      });

      const youAreDomIn = (dynamics || []).filter((d) =>
        (d.partners || []).some((p) => p.is_you && p.role === "dominant")
      );
      const subRenameTargets = [];
      youAreDomIn.forEach((d) => {
        (d.partners || []).forEach((p) => {
          if (!p.is_you && p.role === "submissive") {
            subRenameTargets.push({ dynamic: d, partner: p });
          }
        });
      });
      if (subRenameTargets.length) {
        const renameCard = el("div", { className: "card stack" }, [
          el("h2", {}, "Partner username"),
          el("p", { className: "muted" }, "As keyholder you can change your sub’s username any time. It updates their name everywhere in the dynamic."),
        ]);
        const renameRows = [];
        subRenameTargets.forEach(({ dynamic: d, partner: p }) => {
          const input = el("input", {
            type: "text",
            value: p.username || p.display_name || "",
            maxlength: "64",
            autocomplete: "off",
          });
          const err = el("div", { className: "error hidden" });
          const statusLine = el(
            "p",
            { className: "muted" },
            `${formatDynamicTitle(d)} · currently ${p.username || p.display_name}`
          );
          let baseline = (p.username || p.display_name || "").trim();
          renameRows.push({ d, p, input, err, statusLine, getBaseline: () => baseline, setBaseline: (v) => { baseline = v; } });
          renameCard.appendChild(el("div", { className: "stack" }, [
            statusLine,
            el("label", {}, [`Username for ${p.display_name}`, input]),
            err,
          ]));
        });
        stack.appendChild(renameCard);
        draft.register({
          isDirty: () => renameRows.some((r) => r.input.value.trim() !== r.getBaseline()),
          save: async () => {
            const changed = renameRows.filter((r) => r.input.value.trim() !== r.getBaseline());
            for (const r of changed) {
              r.err.classList.add("hidden");
              try {
                const updated = await api(`/dynamics/${r.d.id}/partners/${r.p.id}/username`, {
                  method: "PUT",
                  body: JSON.stringify({ username: r.input.value.trim() }),
                });
                r.input.value = updated.username || updated.display_name;
                r.setBaseline((updated.username || updated.display_name || "").trim());
                r.statusLine.textContent = `${formatDynamicTitle(r.d)} · currently ${updated.username || updated.display_name}`;
                r.p.username = updated.username;
                r.p.display_name = updated.display_name;
              } catch (ex) {
                r.err.textContent = ex.message;
                r.err.classList.remove("hidden");
                throw ex;
              }
            }
            if (changed.length) state.dynamics = await api("/dynamics");
            return changed.length ? "Partner username saved" : null;
          },
        });
      }

      if (dynamics.length) {
        const dynCard = el("div", { className: "card stack" }, [
          el("h2", {}, "Your dynamics"),
          el("p", { className: "muted" }, "Switch between relationship spaces or start another dynamic."),
        ]);
        dynamics.forEach((d) => {
          dynCard.appendChild(el("button", {
            className: "choice-btn",
            type: "button",
            onClick: () => {
              state.activeDynamicId = d.id;
              navigate(`/dynamic/${d.id}`);
            },
          }, `${formatDynamicTitle(d)} · ${d.partners.length} partner(s)${d.shared_llm_configured ? " · shared AI key" : ""}`));
        });
        stack.appendChild(dynCard);
      } else {
        stack.appendChild(el("div", { className: "card stack" }, [
          el("h2", {}, "Start or join a dynamic"),
          el("p", { className: "muted" }, "You need a dynamic before using the rest of the app."),
          el("button", {
            className: "primary-btn",
            type: "button",
            onClick: () => navigate("/home"),
          }, "Create or join"),
        ]));
      }

      const googleCard = el("div", { className: "card stack" }, [
        el("h2", {}, "Google Tasks"),
        el("p", { className: "muted" }, "Connect the account that should receive discreet, G-rated code-word tasks (usually the submissive). Completing them in Google marks them done in UBETRA."),
        googleStatusLine,
      ]);
      if (!googleStatus.configured) {
        googleCard.appendChild(el("p", { className: "muted" }, "Not configured on this server. Set UBETRA_GOOGLE_CLIENT_ID / SECRET in .env."));
      } else if (googleStatus.connected) {
        googleStatusLine.textContent = googleStatusLine.textContent || `Connected · list ${googleStatus.list_id || "@default"}`;
        googleCard.appendChild(el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: async () => {
            await api("/google/disconnect", { method: "DELETE" });
            renderSettings();
          },
        }, "Disconnect Google"));
      } else {
        googleCard.appendChild(el("button", {
          className: "primary-btn",
          type: "button",
          onClick: async () => {
            try {
              const { auth_url: authUrl } = await api("/google/connect");
              window.location.href = authUrl;
            } catch (err) {
              googleStatusLine.textContent = err.message;
            }
          },
        }, "Connect Google Tasks"));
      }
      stack.appendChild(googleCard);

      stack.appendChild(el("p", { className: "muted" }, "Saving updates your account and any shared dynamic keys. The assistant uses the shared key per relationship when one is set."));
      stack.appendChild(status);
      const helpSlot = el("span");
      function refreshHelp() {
        const tip = providerHelpBtn(providerMap[providerSelect.value]);
        helpSlot.replaceChildren(...(tip ? [tip] : []));
      }
      providerSelect.addEventListener("change", refreshHelp);
      refreshHelp();

      const llmFields = el("div", { className: "stack" }, [
        el("div", { className: "row wrap" }, [
          el("label", { className: "grow" }, ["AI provider", providerSelect]),
          helpSlot,
        ]),
        description,
        el("label", {}, ["Model", modelSelect]),
        el("label", {}, ["Custom model (optional)", modelCustom]),
        el("label", {}, ["API key", apiKeyInput]),
        el("p", { className: "muted" }, "Keys are never shown again after saving. Prefer gemini-3.5-flash (Gemini 2.0/2.5 IDs are retired). Use a dedicated key you can revoke."),
      ]);
      const llmCard = el("div", { className: "card stack" });
      const activeDyn =
        dynamics.find((d) => d.id === (initialDynamicId || settings.active_dynamic_id))
        || dynamics.find((d) => d.shared_llm_configured)
        || dynamics[0];
      const sharedWorking = Boolean(
        settings.shared_configured
        || settings.active_key_source === "shared"
        || activeDyn?.shared_llm_configured
      );
      if (sharedWorking) {
        const hint = settings.shared_api_key_hint || settings.active_api_key_hint || "";
        const prov = settings.shared_provider || activeDyn?.shared_llm_provider || "";
        const model = settings.shared_model || "";
        const detail = [prov, model].filter(Boolean).join(" / ");
        llmCard.appendChild(el("p", { className: "ok-banner e2e-key-banner" },
          `Shared AI key is active${detail ? ` · ${detail}` : ""}${hint ? ` · ${hint}` : ""}`.trim()
        ));
        llmCard.appendChild(el("p", { className: "muted" },
          "Both partners use this key for the assistant in this dynamic. Your personal provider below is only for an override."
        ));
        const advanced = el("details", { className: "stack llm-advanced" }, [
          el("summary", {}, "Advanced — use a different LLM than your partner"),
          el("p", { className: "muted" }, "Saving a personal key here can sync to the shared dynamic key. Only use this if you intentionally want to change what both of you use."),
          llmFields,
        ]);
        llmCard.appendChild(advanced);
      } else {
        llmCard.appendChild(llmFields);
      }
      stack.appendChild(llmCard);
      stack.appendChild(error);
      let llmBaseline = {
        provider: providerSelect.value,
        model: (modelCustom.value || modelSelect.value || "").trim(),
      };
      draft.register({
        isDirty: () => {
          const model = (modelCustom.value || modelSelect.value || "").trim();
          return (
            providerSelect.value !== llmBaseline.provider
            || model !== llmBaseline.model
            || !!apiKeyInput.value.trim()
          );
        },
        save: async () => {
          error.classList.add("hidden");
          const body = {
            provider: providerSelect.value,
            model: modelCustom.value || modelSelect.value,
          };
          if (apiKeyInput.value.trim()) body.api_key = apiKeyInput.value.trim();
          const llmPath = initialDynamicId
            ? `/settings/llm?dynamic_id=${encodeURIComponent(initialDynamicId)}`
            : "/settings/llm";
          const updated = await api(llmPath, {
            method: "PUT",
            body: JSON.stringify(body),
          });
          Object.assign(settings, updated);
          refreshLlmStatus();
          apiKeyInput.value = "";
          apiKeyInput.placeholder = updated.api_key_set
            ? `Saved key ${updated.api_key_hint || ""} — leave blank to keep`
            : "Paste API key";
          llmBaseline = {
            provider: providerSelect.value,
            model: (modelCustom.value || modelSelect.value || "").trim(),
          };
          return "AI settings saved";
        },
      });
      stack.appendChild(el("div", { className: "row wrap" }, [
        el("button", {
          className: "ghost-btn",
          type: "button",
          onClick: async () => {
            error.classList.add("hidden");
            try {
              const testPath = initialDynamicId
                ? `/settings/llm/test?dynamic_id=${encodeURIComponent(initialDynamicId)}`
                : "/settings/llm/test";
              const result = await api(testPath, { method: "POST" });
              if (result.ok) {
                status.textContent = `AI test OK · ${result.provider} / ${result.model} · ${result.active_key_source} key · ${result.reply || "UBETRA_OK"}`;
              } else {
                error.textContent = result.detail || "AI test failed";
                error.classList.remove("hidden");
                status.textContent = `AI test failed · ${result.provider} / ${result.model}`;
              }
            } catch (err) {
              error.textContent = err.message;
              error.classList.remove("hidden");
            }
          },
        }, "Test AI connection"),
        el("button", {
          className: "ghost-btn",
          onClick: async () => {
            if (!confirm("Remove your saved API key?")) return;
            await api("/settings/llm", {
              method: "PUT",
              body: JSON.stringify({
                provider: providerSelect.value,
                model: modelCustom.value || modelSelect.value,
                clear_api_key: true,
              }),
            });
            renderSettings();
          },
        }, "Clear saved API key"),
      ]));
      const assistantDomOnly = !!(assistantSettings.dynamic_id && assistantSettings.you_are_dominant === false);
      const assistantToneBlock = lockedSettingsWrap({
        locked: assistantDomOnly,
        children: el("div", { className: "stack" }, [
          el("label", {}, ["Tone", toneSelect]),
          toneDescription,
        ]),
      });
      const assistantExtraBlock = lockedSettingsWrap({
        locked: assistantDomOnly,
        children: el("label", {}, ["Extra instructions", extraInstructions]),
      });
      stack.appendChild(el("div", { className: "card stack" }, [
          el("h2", {}, "Assistant domme"),
          el("p", { className: "muted" }, "The assistant helps plan scenes, tasks, and acts inside your dynamic. It cannot enforce rules, control devices, or act outside this app."),
          assistantDomOnly
            ? el("p", { className: "muted" }, "Tone and extra instructions are set by the keyholder. Change them below, then Submit settings change to request approval.")
            : el("p", { className: "muted" }, "As keyholder you set the assistant voice for this dynamic. Your partner can request changes."),
          assistantStatus,
          assistantToneBlock,
          assistantExtraBlock,
          el("label", { className: "checkbox-label" }, [
            includeTracking,
            " Share orgasm & chastity tracking with the assistant",
          ]),
      ]));
      stack.appendChild(assistantError);
      let assistantBaseline = {
        tone: toneSelect.value,
        extra: extraInstructions.value,
        tracking: includeTracking.checked,
      };
      draft.register({
        isDirty: () => (
          toneSelect.value !== assistantBaseline.tone
          || extraInstructions.value !== assistantBaseline.extra
          || includeTracking.checked !== assistantBaseline.tracking
        ),
        needsApproval: () => (
          assistantDomOnly
          && (
            toneSelect.value !== assistantBaseline.tone
            || extraInstructions.value !== assistantBaseline.extra
          )
        ),
        save: async () => {
          assistantError.classList.add("hidden");
          const dynId = assistantSettings.dynamic_id || initialDynamicId;
          const assistantPath = dynId
            ? `/settings/assistant?dynamic_id=${encodeURIComponent(dynId)}`
            : "/settings/assistant";
          const toneChanged = toneSelect.value !== assistantBaseline.tone
            || extraInstructions.value !== assistantBaseline.extra;
          const updated = await api(assistantPath, {
            method: "PUT",
            body: JSON.stringify({
              tone: toneSelect.value,
              extra_instructions: extraInstructions.value,
              include_tracking: includeTracking.checked,
            }),
          });
          if (assistantDomOnly && toneChanged && dynId) {
            await postSettingsChangeRequest({
              dynamicId: dynId,
              settingKey: "assistant.tone",
              settingLabel: "Assistant domme tone / instructions",
              requestedValue: {
                tone: toneSelect.value,
                extra_instructions: extraInstructions.value,
              },
            });
          }
          const toneLabel = tones.find((t) => t.id === updated.tone)?.label || updated.tone;
          assistantBaseline = {
            tone: toneSelect.value,
            extra: extraInstructions.value,
            tracking: includeTracking.checked,
          };
          // After request, reset tone UI to server (dom-controlled) values for sub
          if (assistantDomOnly && toneChanged) {
            toneSelect.value = updated.tone;
            extraInstructions.value = updated.extra_instructions || "";
            assistantBaseline.tone = updated.tone;
            assistantBaseline.extra = updated.extra_instructions || "";
            refreshToneUi();
            assistantStatus.textContent = "Tracking preference saved · tone/instructions request sent to keyholder";
            return "Assistant request submitted";
          }
          assistantStatus.textContent = updated.include_tracking
            ? `Saved · ${toneLabel} · tracking shared with assistant`
            : `Saved · ${toneLabel} · tracking hidden from assistant`;
          return "Assistant settings saved";
        },
      });
      stack.appendChild(el("div", { className: "card stack" }, [
          el("h2", {}, "Privacy & security"),
          el("p", { className: "muted" }, "Partner chat privacy, auto-expire, and encrypted chat. The encryption key is shared on the server for your dynamic (like the AI key) so every signed-in device can decrypt."),
          dynamics.length
            ? el("label", {}, ["Dynamic", privacyDynamic])
            : el("p", { className: "muted" }, "Join a dynamic to configure chat."),
          privacyStatus,
          lockedSettingsWrap({
            locked: !!(policy && !policy.you_are_dominant),
            children: el("label", { className: "checkbox-label" }, [retainHistory, " Keep forever on server (no auto-delete)"]),
          }),
          el("label", {}, ["Server cache duration (offline & multi-device sync)", expireHours]),
          el("p", { className: "muted" }, "Default 30 days. Messages are stored on the server (ciphertext when encryption is on) so another phone or an offline device can catch up when it reconnects."),
          el("label", { className: "checkbox-label" }, [e2eMode, " Encrypted chat (shared key)"]),
          el("label", { className: "checkbox-label" }, [chatPushEnabled, " Push notifications for this dynamic's chat"]),
          el("label", { className: "checkbox-label" }, [pushDeviceEnabled, " Notify this device when partner sends a chat message"]),
          el("button", {
            type: "button",
            className: "ghost-btn",
            onClick: () => openAndroidPushSetupGuide(),
          }, "Android Chrome / Edge setup tips"),
          pushDeviceStatus,
          lockedSettingsWrap({
            locked: !!(policy && !policy.you_are_dominant),
            children: el("label", { className: "checkbox-label" }, [systemEvents, " Show activity log in chat (tasks, tracking, chastity…)"]),
          }),
          el("label", { className: "checkbox-label" }, [blurByDefault, " Blur shared images"]),
          el("label", {}, ["When blurred", blurModeSelect]),
          el(
            "p",
            { className: "muted" },
            "Encrypted text needs Web Crypto (HTTPS or localhost). Anyone with access to this server’s database can decrypt chat — same trust model as the shared AI key."
          ),
          e2eKeyBanner,
          shareKeySection,
          redeemKeySection,
          e2eAdvancedReShare,
      ]));
      stack.appendChild(privacyError);
      let privacyBaseline = null;
      function snapshotPrivacyBaseline() {
        privacyBaseline = {
          retain: retainHistory.checked,
          e2e: e2eMode.checked,
          keyConfigured: !!privacyBaselineMeta.keyConfigured || hasChatCryptoKey(privacyDynamic.value),
          expire: expireHours.value,
          system: systemEvents.checked,
          push: chatPushEnabled.checked,
          blur: blurByDefault.checked,
          blurMode: blurModeSelect.value,
          email: partnerEmail.value.trim(),
          phone: partnerPhone.value.trim(),
        };
      }
      draft.register({
        isDirty: () => {
          if (!privacyBaseline) return false;
          return (
            retainHistory.checked !== privacyBaseline.retain
            || e2eMode.checked !== privacyBaseline.e2e
            || expireHours.value !== privacyBaseline.expire
            || systemEvents.checked !== privacyBaseline.system
            || chatPushEnabled.checked !== privacyBaseline.push
            || blurByDefault.checked !== privacyBaseline.blur
            || blurModeSelect.value !== privacyBaseline.blurMode
            || partnerEmail.value.trim() !== privacyBaseline.email
            || partnerPhone.value.trim() !== privacyBaseline.phone
          );
        },
        needsApproval: () => {
          if (!privacyBaseline || !isSubmissive) return false;
          return (
            retainHistory.checked !== privacyBaseline.retain
            || systemEvents.checked !== privacyBaseline.system
          );
        },
        save: async () => {
          privacyError.classList.add("hidden");
          const dynamicId = privacyDynamic.value;
          if (!dynamicId) throw new Error("Select a dynamic for privacy settings.");
          localStorage.setItem(chatBlurStorage(), blurByDefault.checked ? "true" : "false");
          setChatBlurMode(blurModeSelect.value);
          savePartnerContact(dynamicId, {
            email: partnerEmail.value.trim(),
            phone: partnerPhone.value.trim(),
          });
          const retainChanged = privacyBaseline && retainHistory.checked !== privacyBaseline.retain;
          const systemChanged = privacyBaseline && systemEvents.checked !== privacyBaseline.system;
          if (isSubmissive && retainChanged) {
            await postSettingsChangeRequest({
              dynamicId,
              settingKey: "chat.retain_history",
              settingLabel: "Keep chat history on server",
              requestedValue: retainHistory.checked,
            });
            retainHistory.checked = privacyBaseline.retain;
          }
          if (isSubmissive && systemChanged) {
            await postSettingsChangeRequest({
              dynamicId,
              settingKey: "chat.system_events",
              settingLabel: "Show activity log in chat",
              requestedValue: systemEvents.checked,
            });
            systemEvents.checked = privacyBaseline.system;
          }
          if (e2eMode.checked) {
            if (!cryptoSubtleAvailable()) throw encryptionUnavailableError();
            await ensureChatCryptoKey(dynamicId, {
              createIfMissing: !privacyBaseline?.e2e || !privacyBaseline?.keyConfigured,
            });
          }
          const updated = await api(`/dynamics/${dynamicId}/chat/settings`, {
            method: "PUT",
            body: JSON.stringify({
              retain_history: isSubmissive ? privacyBaseline.retain : retainHistory.checked,
              e2e_enabled: e2eMode.checked,
              expire_hours: parseInt(expireHours.value, 10),
              system_events: isSubmissive ? privacyBaseline.system : systemEvents.checked,
              push_enabled: chatPushEnabled.checked,
            }),
          });
          privacyStatus.textContent = updated.retain_history
            ? "Messages stay on the server forever."
            : `Messages stay on the server for ${updated.expire_hours} hour(s), then auto-delete.`;
          refreshE2eKeyUi();
          snapshotPrivacyBaseline();
          const requested = (isSubmissive && (retainChanged || systemChanged));
          return requested ? "Privacy saved · change request sent" : "Privacy settings saved";
        },
      });

      if (featuresBundle && initialDynamicId) {
        const featureChecks = {};
        const featureRows = [];
        const featureBaseline = {};
        (featuresBundle.optional || []).forEach((feature) => {
          const box = el("input", { type: "checkbox" });
          box.checked = feature.enabled;
          featureChecks[feature.id] = box;
          featureBaseline[feature.id] = !!feature.enabled;
          const row = el("label", { className: "checkbox-label" }, [box, feature.title]);
          featureRows.push(
            lockedSettingsWrap({
              locked: !!(policy && !policy.you_are_dominant),
              children: row,
            })
          );
        });
        const featureStatus = el("p", { className: "muted" });
        const featureError = el("div", { className: "error hidden" });
        const featureCard = el("div", { className: "card stack" }, [
          el("h2", {}, "Application features"),
          el("p", { className: "muted" }, "Hide optional app areas you are not using. Core items stay available."),
          ...featureRows,
          featureStatus,
          featureError,
        ]);
        if (!policy?.you_are_dominant) {
          featureCard.appendChild(el("p", { className: "muted" }, "Change features below, then Submit settings change to ask your keyholder."));
        }
        stack.appendChild(featureCard);
        draft.register({
          isDirty: () => Object.keys(featureChecks).some((fid) => featureChecks[fid].checked !== featureBaseline[fid]),
          needsApproval: () => isSubmissive && Object.keys(featureChecks).some((fid) => featureChecks[fid].checked !== featureBaseline[fid]),
          save: async () => {
            featureError.classList.add("hidden");
            const changed = Object.keys(featureChecks).filter((fid) => featureChecks[fid].checked !== featureBaseline[fid]);
            if (!changed.length) return null;
            if (isSubmissive) {
              for (const fid of changed) {
                const meta = featuresBundle.optional.find((f) => f.id === fid);
                await postSettingsChangeRequest({
                  dynamicId: initialDynamicId,
                  settingKey: `features.${fid}`,
                  settingLabel: `Feature: ${meta?.title || fid}`,
                  requestedValue: featureChecks[fid].checked,
                });
                featureChecks[fid].checked = featureBaseline[fid];
              }
              featureStatus.textContent = "Feature change request(s) sent to keyholder.";
              return "Feature requests submitted";
            }
            const enabled_optional = [];
            Object.entries(featureChecks).forEach(([fid, box]) => {
              if (!box.checked) return;
              enabled_optional.push(fid);
              const meta = featuresBundle.optional.find((f) => f.id === fid);
              if (meta?.paired_with) enabled_optional.push(meta.paired_with);
            });
            const updated = await api(`/dynamics/${initialDynamicId}/features`, {
              method: "PUT",
              body: JSON.stringify({ enabled_optional: [...new Set(enabled_optional)] }),
            });
            if (state.currentDynamic?.id === initialDynamicId) {
              state.currentDynamic.enabled_features = updated.enabled;
            }
            Object.keys(featureChecks).forEach((fid) => {
              featureBaseline[fid] = featureChecks[fid].checked;
            });
            featureStatus.textContent = "Saved.";
            return "Features saved";
          },
        });
      }

      // Privacy values may have loaded before the draft existed — snapshot now
      snapshotPrivacyBaseline();
      draft.refresh();

      if (initialDynamicId) {
        const orgPrefsStatus = el("p", { className: "muted" });
        const orgPrefsError = el("div", { className: "error hidden" });
        const orgPrefsCard = el("div", { className: "card stack" }, [
          el("h2", {}, "Sex & orgasm tracking details"),
          el("p", { className: "muted" }, "Turn on optional log fields and history metrics for this dynamic. Defaults keep the form light; enable what your couple wants to track."),
        ]);
        api(`/dynamics/${initialDynamicId}/tracking-prefs`)
          .then((prefs) => {
            const fieldChecks = {};
            const metricChecks = {};
            const fieldBaseline = {};
            const metricBaseline = {};
            const fieldsHost = el("div", { className: "stack" }, [el("h3", {}, "Log fields")]);
            (prefs.fields || []).forEach((f) => {
              const box = el("input", { type: "checkbox" });
              box.checked = !!f.enabled;
              fieldChecks[f.id] = box;
              fieldBaseline[f.id] = !!f.enabled;
              fieldsHost.appendChild(el("label", { className: "checkbox-label" }, [box, ` ${f.title}`]));
            });
            const metricsHost = el("div", { className: "stack" }, [el("h3", {}, "History metrics")]);
            (prefs.metrics || []).forEach((m) => {
              const box = el("input", { type: "checkbox" });
              box.checked = !!m.enabled;
              metricChecks[m.id] = box;
              metricBaseline[m.id] = !!m.enabled;
              metricsHost.appendChild(el("label", { className: "checkbox-label" }, [box, ` ${m.title}`]));
            });
            orgPrefsCard.appendChild(fieldsHost);
            orgPrefsCard.appendChild(metricsHost);
            orgPrefsCard.appendChild(orgPrefsStatus);
            orgPrefsCard.appendChild(orgPrefsError);
            if (!policy?.you_are_dominant) {
              Object.values(fieldChecks).forEach((box) => { box.disabled = true; });
              Object.values(metricChecks).forEach((box) => { box.disabled = true; });
              orgPrefsCard.appendChild(el("p", { className: "muted" }, "Only the keyholder can change these preferences."));
            } else {
              draft.register({
                isDirty: () => (
                  Object.keys(fieldChecks).some((k) => fieldChecks[k].checked !== fieldBaseline[k])
                  || Object.keys(metricChecks).some((k) => metricChecks[k].checked !== metricBaseline[k])
                ),
                save: async () => {
                  orgPrefsError.classList.add("hidden");
                  const fields = {};
                  const metrics = {};
                  Object.entries(fieldChecks).forEach(([k, box]) => { fields[k] = box.checked; });
                  Object.entries(metricChecks).forEach(([k, box]) => { metrics[k] = box.checked; });
                  await api(`/dynamics/${initialDynamicId}/tracking-prefs`, {
                    method: "PUT",
                    body: JSON.stringify({ fields, metrics }),
                  });
                  Object.keys(fieldChecks).forEach((k) => { fieldBaseline[k] = fieldChecks[k].checked; });
                  Object.keys(metricChecks).forEach((k) => { metricBaseline[k] = metricChecks[k].checked; });
                  orgPrefsStatus.textContent = "Saved.";
                  return "Tracking details saved";
                },
              });
              draft.refresh();
            }
          })
          .catch((err) => {
            orgPrefsError.textContent = err.message;
            orgPrefsError.classList.remove("hidden");
            orgPrefsCard.appendChild(orgPrefsError);
          });
        stack.appendChild(orgPrefsCard);
      }

      if (policy && initialDynamicId) {
        const allowDelete = el("input", { type: "checkbox" });
        allowDelete.checked = policy.chastity_sub_can_delete_breaks !== false;
        let chastityBaseline = allowDelete.checked;
        const chastityStatus = el("p", { className: "muted" });
        const chastityError = el("div", { className: "error hidden" });
        const chastityCard = el("div", { className: "card stack" }, [
          el("h2", {}, "Chastity policy"),
          el("p", { className: "muted" }, "Controls who may delete temporary unlock log entries. Deletions by the sub still notify the keyholder in chat logs."),
          lockedSettingsWrap({
            locked: !policy.you_are_dominant,
            children: el("label", { className: "checkbox-label" }, [
              allowDelete,
              " Allow sub to delete temporary unlock logs",
            ]),
          }),
          chastityStatus,
          chastityError,
        ]);
        if (!policy.you_are_dominant) {
          chastityCard.appendChild(el("p", { className: "muted" }, "Change this, then Submit settings change to request approval."));
        }
        stack.appendChild(chastityCard);
        draft.register({
          isDirty: () => allowDelete.checked !== chastityBaseline,
          needsApproval: () => isSubmissive && allowDelete.checked !== chastityBaseline,
          save: async () => {
            chastityError.classList.add("hidden");
            if (isSubmissive) {
              await postSettingsChangeRequest({
                dynamicId: initialDynamicId,
                settingKey: "chastity.sub_can_delete_breaks",
                settingLabel: "Allow sub to delete temporary unlock logs",
                requestedValue: allowDelete.checked,
              });
              allowDelete.checked = chastityBaseline;
              chastityStatus.textContent = "Change request sent to keyholder.";
              return "Chastity policy request submitted";
            }
            await api(`/dynamics/${initialDynamicId}/chastity/policy`, {
              method: "PATCH",
              body: JSON.stringify({ sub_can_delete_breaks: allowDelete.checked }),
            });
            chastityBaseline = allowDelete.checked;
            chastityStatus.textContent = "Saved.";
            return "Chastity policy saved";
          },
        });
      }

      stack.appendChild(el("div", { className: "card stack" }, [
          el("h2", {}, "Backup & restore"),
          el("p", { className: "muted" }, "Export your settings, survey answers, core knowledge, interviews, tasks, agreements, tracking history, and more. Timestamps are preserved for time-based features."),
          el("p", { className: "muted" }, "Includes your API key — keep the file private."),
          el("button", {
            className: "primary-btn",
            onClick: async () => {
              try {
                const response = await fetch(`${API}/account/export`, {
                  headers: { Authorization: `Bearer ${state.token}` },
                });
                if (!response.ok) throw new Error("Export failed");
                const data = await response.json();
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const link = document.createElement("a");
                const stamp = new Date().toISOString().slice(0, 10);
                link.href = url;
                link.download = `ubetra-export-${data.source_username || "user"}-${stamp}.json`;
                link.click();
                URL.revokeObjectURL(url);
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Download export"),
          el("label", {}, [
            "Import from file",
            el("input", {
              type: "file",
              accept: "application/json,.json",
              onChange: async (event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                if (!confirm("Import will merge data into this account. Join matching dynamics first. Continue?")) {
                  event.target.value = "";
                  return;
                }
                error.classList.add("hidden");
                importStatus.classList.add("hidden");
                try {
                  const text = await file.text();
                  const result = await api("/account/import", {
                    method: "POST",
                    body: text,
                  });
                  const lines = [];
                  if (result.dynamics_restored.length) {
                    lines.push(`Restored: ${result.dynamics_restored.join(", ")}`);
                  }
                  result.dynamics_skipped.forEach((item) => {
                    lines.push(`Skipped ${item.invite_code}: ${item.reason}`);
                  });
                  result.warnings.forEach((warning) => lines.push(warning));
                  importStatus.textContent = lines.join(" · ") || "Import complete.";
                  importStatus.classList.remove("hidden");
                  state.dynamics = await api("/dynamics");
                } catch (err) {
                  error.textContent = err.message;
                  error.classList.remove("hidden");
                }
                event.target.value = "";
              },
            }),
          ]),
          importStatus,
          el("p", { className: "muted" }, "To move to a new username: export here, register the new account, re-join your dynamics with the invite codes, then import."),
      ]));
      stack.appendChild(el("div", { className: "card stack" }, [
        el("h2", {}, "Support the project"),
        el("p", { className: "muted" }, "UBETRA is built independently. Tips on Ko-fi help cover hosting and keep development going — optional, no perks or paywalls."),
        el("a", {
          href: "https://ko-fi.com/ubetradev",
          target: "_blank",
          rel: "noopener noreferrer",
          className: "primary-btn kofi-btn",
        }, "Tip on Ko-fi"),
      ]));
      stack.appendChild(el("button", {
          className: "ghost-btn",
          onClick: () => {
            if (state.dynamics.length) navigate(`/dynamic/${getActiveDynamicId() || state.dynamics[0].id}`);
            else navigate("/home");
          },
        }, "Back"));

      providers.forEach((provider) => {
        if (provider.key_url) {
          const link = el("a", {
            href: provider.key_url,
            target: "_blank",
            rel: "noopener noreferrer",
            className: "muted",
          }, `Get a ${provider.label} API key`);
          stack.appendChild(link);
        }
      });

      // Group flat cards by category for clearer dom/sub browsing
      const heading = stack.firstElementChild;
      const leftovers = [];
      const buckets = {
        Account: [],
        Dynamics: [],
        Features: [],
        Chastity: [],
        "Chat & privacy": [],
        "AI & assistant": [],
        Integrations: [],
        Support: [],
      };
      const bucketIds = {
        Account: "account",
        Dynamics: "dynamics",
        Features: "features",
        Chastity: "chastity",
        "Chat & privacy": "chat",
        "AI & assistant": "ai",
        Integrations: "integrations",
        Support: "support",
      };
      const bucketHelp = {
        "AI & assistant": "Gemini: open Google AI Studio → Create API key → paste here. OpenAI: platform.openai.com → API keys. Used by the assistant, suggested ground rules, acts, and interviews. Server default uses the host .env key.",
        Integrations: "Google Tasks is optional. Connect the account that should receive discreet G-rated code-word tasks (usually the submissive).",
        Chastity: "Keyholder policy for whether the sub can delete their own break records.",
        "Chat & privacy": "History retention, end-to-end chat keys, and push notifications for this device.",
        Support: "Optional donations — the app stays free either way.",
      };
      const titleMap = {
        Username: "Account",
        "Biological sex": "Account",
        "Account email": "Account",
        "Backup & restore": "Account",
        "Partner username": "Account",
        "Your dynamics": "Dynamics",
        "Start or join a dynamic": "Dynamics",
        "Application features": "Features",
        "Chastity policy": "Chastity",
        "Privacy & security": "Chat & privacy",
        "Assistant domme": "AI & assistant",
        "Google Tasks": "Integrations",
        "Sex & orgasm tracking details": "Features",
        "Support the project": "Support",
      };
      [...stack.children].forEach((child) => {
        if (child === heading) return;
        const h2 = child.querySelector?.("h2");
        const title = h2?.textContent?.trim() || "";
        if (titleMap[title]) {
          buckets[titleMap[title]].push(child);
          return;
        }
        if (child.querySelector?.("select") && child.textContent?.includes("AI provider")) {
          buckets["AI & assistant"].unshift(child);
          return;
        }
        leftovers.push(child);
      });

      const checklist = buildSettingsSetupChecklist({
        user: state.user,
        llmSettings: settings,
        googleStatus,
        dynamics,
        providers,
      });
      const focus = query.get("focus") || "";
      const grouped = el("div", { className: "stack settings-page" }, [heading]);
      if (checklist) grouped.appendChild(checklist);
      Object.entries(buckets).forEach(([name, items]) => {
        if (!items.length) return;
        const id = bucketIds[name] || "";
        grouped.appendChild(settingsSection(name, items, {
          id,
          open: focus === id || (focus === "setup" && id === "account"),
          help: bucketHelp[name] || "",
        }));
      });
      leftovers.forEach((node) => grouped.appendChild(node));
      grouped.appendChild(draft.bar);
      draft.bind(grouped);
      draft.refresh();

      if (focus) {
        setTimeout(() => {
          const target = document.getElementById(`settings-${focus}`);
          if (target) {
            target.open = true;
            target.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        }, 50);
      }
      setViewContent(grouped);
    })
    .catch((err) => setViewContent(el("p", { className: "error" }, err.message)));
}

async function renderRoute() {
  const hashPath = (location.hash.replace(/^#/, "") || "/");
  rememberRoute(hashPath.startsWith("/") ? hashPath : `/${hashPath}`);
  const { parts } = parseRoute();
  if (!state.token && parts[0] !== "login" && parts[0] !== "register") {
    renderLogin();
    return;
  }

  if (parts[0] === "login") return renderLogin();
  if (parts[0] === "register") return renderRegister();
  if (parts[0] === "onboarding") return renderOnboarding();
  if (state.user && !state.user.onboarding_completed) {
    const onboardingAllowed =
      parts[0] === "onboarding"
      || parts[0] === "settings"
      || (parts[0] === "dynamic" && parts[2] === "survey");
    if (!onboardingAllowed) return renderOnboarding();
  }
  if (parts[0] === "settings") return renderSettings();
  // Legacy History URL — keep Dynamic tab active, never a bottom-nav item.
  if (parts[0] === "dashboard") {
    if (parts[1]) navigate(`/dynamic/${parts[1]}/history`);
    else navigate("/home");
    return;
  }
  if (parts[0] === "chat") return renderChat(parts[1]);
  if (parts[0] === "home" || parts.length === 0) {
    if (state.dynamics.length) return renderTrackingHub(state.dynamics[0].id);
    return renderHome();
  }

  if (parts[0] === "dynamic" && parts[1]) {
    const dynamicId = parts[1];
    if (parts[2] === "history") {
      if (parts[3] === "sessions" && parts[4]) return renderHistorySession(dynamicId, parts[4]);
      if (parts[3]) return renderHistoryReport(dynamicId, parts[3]);
      return renderHistoryHub(dynamicId);
    }
    if (parts[2] === "survey") return renderSurvey(dynamicId);
    if (parts[2] === "ground-rules") return renderGroundRules(dynamicId);
    if (parts[2] === "overlap") return renderOverlap(dynamicId);
    if (parts[2] === "tasks") return renderTasks(dynamicId);
    if (parts[2] === "knowledge") {
      if (parts[3] === "core") return renderCoreKnowledge(dynamicId);
      if (parts[3] === "spti") return renderSptiProfile(dynamicId);
      return renderKnowledgeHub(dynamicId);
    }
    if (parts[2] === "assistant") {
      if (parts[3] === "scene") return renderPlaytimeScene(dynamicId);
      if (parts[3] === "games" && parts[4] === "spin") return renderSpinTheWheel(dynamicId);
      if (parts[3] === "games") return renderPlaytimeGames(dynamicId);
      return renderAssistant(dynamicId);
    }
    if (parts[2] === "interview") return renderInterview(dynamicId);
    if (parts[2] === "context") return renderContext(dynamicId);
    if (parts[2] === "journal") return renderJournal(dynamicId);
    if (parts[2] === "track") return renderTrackingHub(dynamicId);
    if (parts[2] === "tracking") {
      if (parts[3] === "history") return renderOrgasmPriorHistory(dynamicId);
      return renderTracking(dynamicId);
    }
    if (parts[2] === "feelings") return renderFeelings(dynamicId);
    if (parts[2] === "punishment") {
      if (parts[3]) return renderPunishment(dynamicId, parts[3]);
      return renderPunishment(dynamicId);
    }
    if (parts[2] === "chastity") {
      if (parts[3] === "history") return renderChastityPriorHistory(dynamicId);
      return renderChastity(dynamicId);
    }
    if (parts[2] === "acts") return renderActs(dynamicId);
    if (parts[2] === "gear") return renderGear(dynamicId);
    if (parts[2] === "vault") return renderVault(dynamicId);
    if (parts[2] === "features") return renderFeatureSettings(dynamicId);
    return renderDynamicOverview(dynamicId);
  }

  renderHome();
  updateBottomNav();
}

bootstrap();
