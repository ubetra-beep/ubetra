/* UBETRA Assistant Domme — keyholder co-pilot sheet and full page.
 * Depends on globals from app.js: el, api, state, navigate, parseRoute, showToast, isAiEnabled
 */
(function (global) {
  let sheetOpen = false;
  let lastNag = 0;
  let pollTimer = 0;
  let lastPermissions = null;
  let lastChanges = [];
  let lastExamplePrompts = [];
  let lastLlmConfigured = true;

  function currentDynamicId() {
    const { parts } = parseRoute();
    if (parts[0] === "dynamic" && parts[1]) return parts[1];
    if (parts[0] === "chat" && parts[1]) return parts[1];
    return state.currentDynamic?.id || state.activeDynamicId || "";
  }

  function currentRoute() {
    return location.hash.replace(/^#/, "") || "/";
  }

  const PAGE_CONTEXT_SCREENS = {
    "": "Tracking hub",
    track: "Tracking hub",
    history: "History",
    tracking: "Sex & orgasm tracking",
    chastity: "Chastity tracking",
    feelings: "Feelings",
    sleep: "Sleep tracking",
    cycle: "Cycle tracking",
    punishment: "Punishment / confessions",
    journal: "Journal",
    vault: "Image vault",
    tasks: "Tasks & acts",
    acts: "Acts of submission",
    assistant: "Playtime",
    "assistant/scene": "Scene builder",
    "assistant/games": "Playtime games",
    "assistant/games/spin": "Spin the wheel",
    instructor: "Instructor",
    manga: "Monthly manga",
    "ground-rules": "Ground rules",
    interview: "Dynamic interview",
    survey: "Kink list",
    overlap: "Kink overlap",
    knowledge: "Core knowledge",
    "knowledge/spti": "SPTI profile",
    context: "Context library",
    gear: "Gear",
    features: "Application features",
  };

  function pageContextKey() {
    const { parts } = parseRoute();
    if (parts[0] === "chat") return "";
    if (parts[0] !== "dynamic") return "";
    const rest = parts.slice(2);
    if (!rest.length) return "track";
    if (rest[0] === "assistant" && rest[1] === "games") return rest.slice(0, 3).join("/");
    if (rest[0] === "assistant" && rest[1] && rest[1] !== "chat") return rest.slice(0, 2).join("/");
    if (rest[0] === "assistant") return "assistant";
    if (rest[0] === "knowledge" && rest[1]) return rest.slice(0, 2).join("/");
    return rest[0];
  }

  function isAssistantContextScreen() {
    const key = pageContextKey();
    return Boolean(key && PAGE_CONTEXT_SCREENS[key]);
  }

  function youAreDom(dynamicId) {
    const dyn = state.currentDynamic?.id === dynamicId
      ? state.currentDynamic
      : (state.dynamics || []).find((d) => d.id === dynamicId);
    const you = dyn?.partners?.find((p) => p.is_you);
    return you?.role === "dominant";
  }

  function onAssistantChatPage() {
    const { parts } = parseRoute();
    return parts[0] === "dynamic" && parts[2] === "assistant" && parts[3] === "chat";
  }

  function assistantAvailable() {
    if (!state.token || !isAiEnabled()) return false;
    const { parts } = parseRoute();
    const onDynamic = (parts[0] === "dynamic" && parts[1]) || (parts[0] === "chat" && parts[1]);
    if (!onDynamic) return false;
    const dynamicId = currentDynamicId();
    if (!dynamicId || !youAreDom(dynamicId)) return false;
    return true;
  }

  const FAB_POS_KEY = "ubetra_assistant_fab_pos";
  const FAB_HIDDEN_KEY = "ubetra_assistant_fab_hidden";

  function isFabHidden() {
    try {
      return localStorage.getItem(FAB_HIDDEN_KEY) === "1";
    } catch {
      return false;
    }
  }

  function setFabHidden(hidden) {
    try {
      if (hidden) localStorage.setItem(FAB_HIDDEN_KEY, "1");
      else localStorage.removeItem(FAB_HIDDEN_KEY);
    } catch {
      /* ignore */
    }
    if (hidden) closeSheet();
    ensureFab();
    sync().catch(() => {});
  }

  function readFabPos() {
    try {
      const pos = JSON.parse(localStorage.getItem(FAB_POS_KEY) || "null");
      if (pos && typeof pos.left === "number" && typeof pos.top === "number") return pos;
    } catch {
      /* ignore */
    }
    return null;
  }

  function applyFabPosition(host) {
    const pos = readFabPos();
    if (!pos) {
      host.classList.remove("placed");
      host.style.left = "";
      host.style.top = "";
      return;
    }
    const w = host.offsetWidth || 88;
    const h = host.offsetHeight || 52;
    const left = Math.max(8, Math.min(window.innerWidth - w - 8, pos.left));
    const top = Math.max(8, Math.min(window.innerHeight - h - 8, pos.top));
    host.classList.add("placed");
    host.style.left = `${left}px`;
    host.style.top = `${top}px`;
  }

  function bindFabDrag(host, fab) {
    if (host.dataset.dragBound) return;
    host.dataset.dragBound = "1";
    let dragging = false;
    let moved = false;
    let startX = 0;
    let startY = 0;
    let origLeft = 0;
    let origTop = 0;
    fab.addEventListener("pointerdown", (ev) => {
      if (ev.button && ev.button !== 0) return;
      const rect = host.getBoundingClientRect();
      startX = ev.clientX;
      startY = ev.clientY;
      origLeft = rect.left;
      origTop = rect.top;
      dragging = true;
      moved = false;
      fab.setPointerCapture(ev.pointerId);
    });
    fab.addEventListener("pointermove", (ev) => {
      if (!dragging) return;
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if (Math.abs(dx) + Math.abs(dy) > 8) moved = true;
      if (!moved) return;
      host.classList.add("placed");
      host.style.left = `${origLeft + dx}px`;
      host.style.top = `${origTop + dy}px`;
    });
    const endDrag = (ev) => {
      if (!dragging) return;
      dragging = false;
      try {
        fab.releasePointerCapture(ev.pointerId);
      } catch {
        /* ignore */
      }
      if (moved) {
        const rect = host.getBoundingClientRect();
        try {
          localStorage.setItem(FAB_POS_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
        } catch {
          /* ignore */
        }
        applyFabPosition(host);
      }
    };
    fab.addEventListener("pointerup", endDrag);
    fab.addEventListener("pointercancel", endDrag);
    fab.addEventListener("click", (ev) => {
      if (moved) {
        ev.preventDefault();
        ev.stopPropagation();
        moved = false;
      }
    }, true);
  }

  function ensureShowTab() {
    let tab = document.getElementById("assistant-domme-show-tab");
    if (!assistantAvailable() || onAssistantChatPage() || !isFabHidden()) {
      tab?.remove();
      return;
    }
    if (!tab) {
      tab = el("button", {
        id: "assistant-domme-show-tab",
        type: "button",
        className: "assistant-domme-show-tab",
        title: "Show Assistant bubble",
        "aria-label": "Show Assistant bubble",
        onClick: () => setFabHidden(false),
      }, "✦");
      document.body.appendChild(tab);
    }
  }

  function ensureFab() {
    ensureShowTab();
    let host = document.getElementById("assistant-domme-fab-host");
    if (!assistantAvailable() || onAssistantChatPage() || isFabHidden()) {
      host?.remove();
      document.getElementById("assistant-domme-fab")?.remove();
      if (!onAssistantChatPage() && !isFabHidden()) {
        document.getElementById("assistant-domme-sheet")?.remove();
        sheetOpen = false;
      }
      return null;
    }
    if (!host) {
      const fab = el("button", {
        id: "assistant-domme-fab",
        type: "button",
        className: "assistant-domme-fab",
        "aria-label": "Assistant",
        title: "Drag to move · tap to chat",
        onClick: () => toggleSheet(),
      }, [
        el("span", { className: "assistant-domme-fab-icon" }, "✦"),
        el("span", { className: "assistant-domme-fab-label" }, "Assistant"),
        el("span", { id: "assistant-domme-fab-badge", className: "assistant-domme-fab-badge hidden" }, "0"),
      ]);
      const hide = el("button", {
        type: "button",
        className: "assistant-domme-fab-hide",
        title: "Hide Assistant bubble",
        "aria-label": "Hide Assistant bubble",
        onClick: (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          setFabHidden(true);
        },
      }, "×");
      host = el("div", { id: "assistant-domme-fab-host", className: "assistant-domme-fab-host" }, [fab, hide]);
      document.body.appendChild(host);
      bindFabDrag(host, fab);
      window.addEventListener("resize", () => {
        const live = document.getElementById("assistant-domme-fab-host");
        if (live) applyFabPosition(live);
      });
    }
    applyFabPosition(host);
    const fab = document.getElementById("assistant-domme-fab");
    fab?.classList.toggle("on-context", isAssistantContextScreen());
    return fab;
  }

  function setBadge(count) {
    const badge = document.getElementById("assistant-domme-fab-badge");
    const fab = document.getElementById("assistant-domme-fab");
    const tab = document.getElementById("assistant-domme-show-tab");
    if (tab) tab.classList.toggle("has-nag", count > 0);
    if (!badge || !fab) return;
    if (count > 0) {
      badge.textContent = count > 9 ? "9+" : String(count);
      badge.classList.remove("hidden");
      fab.classList.add("has-nag");
    } else {
      badge.classList.add("hidden");
      fab.classList.remove("has-nag");
    }
  }

  async function fetchTriggers(dynamicId) {
    try {
      return await api(`/dynamics/${dynamicId}/assistant/triggers`);
    } catch {
      return { available: false, triggers: [], subjects: [], nag_count: 0, llm_configured: false };
    }
  }

  function suggestionLabel(suggestion) {
    const type = suggestion.type;
    if (suggestion.label) return suggestion.label;
    if (type === "create_task") return "Assign this task";
    if (type === "assign_punishment_task") return "Assign punishment task";
    if (type === "adjust_target") return "Adjust balance target";
    if (type === "create_standing_target") return "Add standing target";
    if (type === "adjust_gift_goal") return "Adjust gift goal";
    if (type === "toggle_feature") return suggestion.enabled ? "Enable feature" : "Disable feature";
    if (type === "open_scene") return "Open scene builder";
    if (type === "open_path") return "Open";
    return "Apply";
  }

  function suggestionPreview(suggestion) {
    return suggestion.content
      || suggestion.title
      || (suggestion.feature_id ? `Feature ${suggestion.feature_id}` : "")
      || (suggestion.target_id ? `Target ${suggestion.target_id}` : "")
      || suggestion.path
      || "";
  }

  function askGrant(capabilityLabel) {
    return new Promise((resolve) => {
      const backdrop = el("div", { className: "modal-backdrop" });
      const card = el("div", { className: "card stack modal-card" }, [
        el("h3", {}, "Allow Assistant?"),
        el("p", {}, `Apply “${capabilityLabel}” for this dynamic.`),
        el("p", { className: "muted" }, "You can allow once, this session (12 hours), always, or block it."),
        el("div", { className: "stack" }, [
          el("button", { type: "button", className: "primary-btn", onClick: () => done("once") }, "Allow once"),
          el("button", { type: "button", className: "ghost-btn", onClick: () => done("session") }, "Allow this session"),
          el("button", { type: "button", className: "ghost-btn", onClick: () => done("always") }, "Always allow"),
          el("button", { type: "button", className: "ghost-btn", onClick: () => done("deny") }, "Don’t allow"),
        ]),
      ]);
      function done(choice) {
        backdrop.remove();
        resolve(choice);
      }
      backdrop.appendChild(card);
      backdrop.addEventListener("click", (ev) => {
        if (ev.target === backdrop) done(null);
      });
      document.body.appendChild(backdrop);
    });
  }

  function suggestionCard(dynamicId, suggestion, onDone) {
    const type = suggestion.type;
    const preview = suggestionPreview(suggestion);
    return el("div", { className: "assistant-suggestion-card stack" }, [
      preview ? el("p", {}, preview) : null,
      el("button", {
        type: "button",
        className: "primary-btn",
        onClick: async () => {
          try {
            if (type === "open_scene") {
              closeSheet();
              navigate(`/dynamic/${dynamicId}/assistant/scene`);
              return;
            }
            if (type === "open_path" && suggestion.path) {
              closeSheet();
              navigate(suggestion.path.startsWith("/") ? suggestion.path : `/${suggestion.path}`);
              return;
            }
            const applied = await applyWithGrant(dynamicId, suggestion);
            if (!applied) return;
            showToast(applied.applied === "create_task" || applied.applied === "assign_punishment_task"
              ? "Task assigned."
              : "Updated.");
            if (typeof onDone === "function") onDone();
          } catch (err) {
            showToast(err.message || "Could not apply.");
          }
        },
      }, suggestionLabel(suggestion)),
    ]);
  }

  async function applyWithGrant(dynamicId, suggestion, grant) {
    const body = { ...suggestion, grant, subject_id: suggestion.subject_id || "" };
    const result = await api(`/dynamics/${dynamicId}/assistant/suggestions/apply`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (result?.needs_permission) {
      const choice = await askGrant(result.label || result.capability || "this action");
      if (!choice) return null;
      if (choice === "deny") {
        await api(`/dynamics/${dynamicId}/assistant/suggestions/apply`, {
          method: "POST",
          body: JSON.stringify({ ...suggestion, grant: "deny" }),
        }).catch(() => {});
        showToast("Blocked that Assistant action.");
        return null;
      }
      return applyWithGrant(dynamicId, suggestion, choice);
    }
    return result;
  }

  function paintMessages(log, messages, dynamicId, extraSuggestions) {
    log.replaceChildren();
    (messages || []).forEach((msg) => {
      log.appendChild(
        el("div", { className: `chat-bubble ${msg.role === "user" ? "user" : "assistant"}` }, msg.content || "")
      );
      (msg.suggestions || []).forEach((sug) => {
        log.appendChild(suggestionCard(dynamicId, sug));
      });
    });
    (extraSuggestions || []).forEach((sug) => {
      log.appendChild(suggestionCard(dynamicId, sug));
    });
    log.scrollTop = log.scrollHeight;
  }

  function paintExamplePrompts(host, prompts, input) {
    const row = host.querySelector(".assistant-example-prompts");
    if (!row) return;
    row.replaceChildren();
    (prompts || []).forEach((prompt) => {
      row.appendChild(el("button", {
        type: "button",
        className: "assistant-prompt-chip",
        onClick: () => {
          if (input) input.value = prompt.text || prompt.label || "";
          if (prompt.subject_id) {
            const btn = [...host.querySelectorAll(".assistant-subject-btn")].find(
              (b) => b.dataset.subjectId === prompt.subject_id
            );
            if (btn) btn.click();
          }
          input?.focus();
        },
      }, prompt.label || prompt.text));
    });
  }

  function paintPermissions(host, dynamicId, permissions) {
    const box = host.querySelector(".assistant-permissions");
    if (!box) return;
    const caps = permissions?.capabilities || [];
    box.replaceChildren(
      el("summary", {}, "Permissions"),
      el("p", { className: "muted" }, "Ask each time, allow this session (12h), always, or deny. Navigation stays allowed.")
    );
    caps.forEach((cap) => {
      const select = el("select");
      [["ask", "Ask each time"], ["session", "This session"], ["always", "Always"], ["deny", "Don’t allow"]].forEach(([v, l]) => {
        select.appendChild(el("option", { value: v }, l));
      });
      select.value = cap.level || "ask";
      select.addEventListener("change", async () => {
        try {
          lastPermissions = await api(`/dynamics/${dynamicId}/assistant/permissions`, {
            method: "PUT",
            body: JSON.stringify({ capability: cap.id, level: select.value }),
          });
          showToast("Permission saved.");
        } catch (err) {
          showToast(err.message || "Could not save permission.");
        }
      });
      box.appendChild(el("label", { className: "assistant-perm-row" }, [
        el("span", {}, cap.label),
        select,
      ]));
    });
  }

  function paintChanges(host, changes) {
    const box = host.querySelector(".assistant-changes");
    if (!box) return;
    const rows = changes || [];
    box.replaceChildren(el("summary", {}, `Changes from chat (${rows.length})`));
    if (!rows.length) {
      box.appendChild(el("p", { className: "muted" }, "Nothing applied yet. Tap an Apply card to log a change."));
      return;
    }
    rows.slice(0, 30).forEach((row) => {
      const when = row.created_at ? new Date(row.created_at).toLocaleString() : "";
      box.appendChild(el("p", { className: "assistant-change-row" }, `${when} — ${row.summary || row.action}`));
    });
  }

  async function openSubject(dynamicId, subject, host) {
    const related = subject.related_entity_id || "";
    const log = host.querySelector(".assistant-domme-log");
    const error = host.querySelector(".assistant-domme-error");
    const title = host.querySelector(".assistant-domme-subject-title");
    const blurb = host.querySelector(".assistant-domme-subject-blurb");
    title.textContent = subject.title || "Assistant";
    blurb.textContent = subject.detail || subject.blurb || "";
    host.dataset.subjectId = subject.id;
    host.dataset.relatedEntityId = related;
    error.classList.add("hidden");
    log.replaceChildren(el("p", { className: "muted" }, "Loading…"));
    try {
      const thread = await api(
        `/dynamics/${dynamicId}/assistant/chat?subject_id=${encodeURIComponent(subject.id)}&related_entity_id=${encodeURIComponent(related)}`
      );
      lastLlmConfigured = thread.llm_configured !== false;
      lastPermissions = thread.permissions || lastPermissions;
      lastChanges = thread.changes || lastChanges;
      lastExamplePrompts = thread.example_prompts || lastExamplePrompts;
      paintPermissions(host, dynamicId, lastPermissions);
      paintChanges(host, lastChanges);
      const input = host.querySelector(".assistant-domme-input");
      paintExamplePrompts(host, lastExamplePrompts, input);
      const extras = (
        !host.classList.contains("page-context")
        && !(thread.messages || []).length
        && (thread.demo_suggestions || []).length
      )
        ? thread.demo_suggestions
        : [];
      if (!(thread.messages || []).length && extras.length) {
        log.replaceChildren(
          el("div", { className: "chat-bubble assistant" },
            "Here is what I can do. Tap a card to try Apply — nothing happens until you confirm. Example prompts sit above the composer.")
        );
        extras.forEach((sug) => log.appendChild(suggestionCard(dynamicId, sug)));
      } else {
        paintMessages(log, thread.messages, dynamicId);
      }
      const wantSeed = lastLlmConfigured && !(thread.messages || []).length && (
        subject.triggered
        || (host.classList.contains("page-context") && subject.id === "this_page")
      );
      if (wantSeed) {
        const seed = host.classList.contains("page-context")
          ? `I'm on ${PAGE_CONTEXT_SCREENS[host.dataset.pageKey] || "this screen"}. Give me your read of what is going on and what you would do next. One concrete opinion, then ask if I want another direction.`
          : (subject.detail || "Look at this with me. Is it intentional, or should we adjust?");
        const updated = await api(`/dynamics/${dynamicId}/assistant/chat`, {
          method: "POST",
          body: JSON.stringify({
            message: seed,
            subject_id: subject.id,
            related_entity_id: related,
            route: currentRoute(),
          }),
        });
        paintMessages(log, updated.messages, dynamicId);
      } else if (!(thread.messages || []).length && input && !input.value) {
        input.placeholder = lastLlmConfigured ? "What should we look at?" : "Add an API key in Settings to chat — Apply cards still work.";
      }
    } catch (err) {
      log.replaceChildren();
      error.textContent = err.message || "Could not load this thread.";
      error.classList.remove("hidden");
    }
  }

  function buildChatUI(dynamicId, payload, { fullPage = false, host = null, pageContext = false, pageKey = "" } = {}) {
    const compact = pageContext && !fullPage;
    let subjects = payload.subjects || [];
    if (compact) {
      const pageSubject = subjects.find((s) => s.id === "this_page") || {
        id: "this_page",
        title: PAGE_CONTEXT_SCREENS[pageKey] || "This page",
        blurb: "What you can do on this screen, and a next step.",
        related_entity_id: pageKey,
      };
      subjects = [{ ...pageSubject, related_entity_id: pageKey, title: PAGE_CONTEXT_SCREENS[pageKey] || pageSubject.title }];
    }
    lastPermissions = payload.permissions || lastPermissions;
    lastExamplePrompts = payload.example_prompts || lastExamplePrompts;
    lastLlmConfigured = payload.llm_configured !== false;
    lastChanges = payload.changes || lastChanges;

    const index = el("div", { className: "assistant-domme-index" });
    const log = el("div", { className: "assistant-domme-log chat-log" });
    const error = el("div", { className: "error hidden assistant-domme-error" });
    const input = el("textarea", {
      className: "assistant-domme-input",
      rows: fullPage ? "3" : "2",
      placeholder: lastLlmConfigured ? "Ask Assistant Domme…" : "Add an API key in Settings to chat…",
    });
    const sendBtn = el("button", { type: "button", className: "primary-btn" }, "Send");
    const title = el("h2", { className: "assistant-domme-subject-title" }, "Assistant Domme");
    const blurb = el("p", { className: "muted assistant-domme-subject-blurb" }, "");
    const prompts = el("div", { className: "assistant-example-prompts" });
    const perms = el("details", { className: "assistant-permissions" });
    const changes = el("details", { className: "assistant-changes" });
    const root = host || el("div", {
      id: "assistant-domme-sheet",
      className: fullPage ? "assistant-domme-page" : "assistant-domme-sheet",
    });
    root.className = fullPage
      ? "assistant-domme-page"
      : `assistant-domme-sheet${compact ? " page-context" : ""}`;
    if (fullPage) root.id = "assistant-domme-page";
    else root.id = "assistant-domme-sheet";
    if (compact) root.dataset.pageKey = pageKey;
    root.replaceChildren();

    function selectSubject(subject, btn) {
      index.querySelectorAll(".assistant-subject-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      openSubject(dynamicId, subject, root);
    }

    subjects.forEach((subject) => {
      const btn = el("button", {
        type: "button",
        className: `assistant-subject-btn${subject.nag ? " nag" : ""}${subject.triggered ? " triggered" : ""}`,
        "data-subject-id": subject.id,
        onClick: () => selectSubject(subject, btn),
      }, [
        el("span", {}, subject.title),
        subject.nag ? el("span", { className: "assistant-subject-dot", "aria-hidden": "true" }, "") : null,
      ]);
      index.appendChild(btn);
    });

    sendBtn.addEventListener("click", async () => {
      const text = input.value.trim();
      if (!text) return;
      if (!lastLlmConfigured) {
        showToast("Turn on AI and add a key in Settings to chat. Apply cards still work.");
        navigate("/settings?focus=ai");
        return;
      }
      error.classList.add("hidden");
      sendBtn.disabled = true;
      try {
        const thread = await api(`/dynamics/${dynamicId}/assistant/chat`, {
          method: "POST",
          body: JSON.stringify({
            message: text,
            subject_id: root.dataset.subjectId || "open_chat",
            related_entity_id: root.dataset.relatedEntityId || "",
            route: currentRoute(),
          }),
        });
        input.value = "";
        paintMessages(log, thread.messages, dynamicId);
        if (thread.changes) {
          lastChanges = thread.changes;
          paintChanges(root, lastChanges);
        }
      } catch (err) {
        error.textContent = err.message || "Send failed.";
        error.classList.remove("hidden");
      } finally {
        sendBtn.disabled = false;
      }
    });

    async function clearAssistantChat() {
      if (!confirm("Move all Assistant messages to trash? You can recover them for 7 days from Chat tools.")) return;
      try {
        await api(`/dynamics/${dynamicId}/assistant/chat/clear`, { method: "POST", body: "{}" });
        const sid = root.dataset.subjectId || "open_chat";
        const related = root.dataset.relatedEntityId || "";
        const sub = subjects.find((s) => s.id === sid) || { id: sid, related_entity_id: related };
        await openSubject(dynamicId, sub, root);
        showToast("Assistant chat moved to trash.");
      } catch (err) {
        showToast(err.message || "Could not clear Assistant chat.");
      }
    }

    async function recoverAssistantChat() {
      try {
        const info = await api(`/dynamics/${dynamicId}/assistant/chat/trashed`);
        if (!info.count) {
          showToast("Nothing to recover.");
          return;
        }
        if (!confirm(`Restore ${info.count} Assistant message(s) cleared in the last 7 days?`)) return;
        await api(`/dynamics/${dynamicId}/assistant/chat/recover`, { method: "POST", body: "{}" });
        const sid = root.dataset.subjectId || "open_chat";
        const related = root.dataset.relatedEntityId || "";
        const sub = subjects.find((s) => s.id === sid) || { id: sid, related_entity_id: related };
        await openSubject(dynamicId, sub, root);
        showToast("Assistant chat restored.");
      } catch (err) {
        showToast(err.message || "Could not recover Assistant chat.");
      }
    }

    const tools = el("details", { className: "assistant-chat-tools" }, [
      el("summary", {}, "Chat tools"),
      el("p", { className: "muted" }, "Clear-all moves messages to trash for 7 days, then they are permanently deleted."),
      el("div", { className: "row wrap" }, [
        el("button", { type: "button", className: "ghost-btn", onClick: clearAssistantChat }, "Clear all messages…"),
        el("button", { type: "button", className: "ghost-btn", onClick: recoverAssistantChat }, "Recover (7 days)"),
      ]),
    ]);

    const headChildren = [
      el("strong", {}, "Assistant Domme"),
    ];
    if (!fullPage) {
      headChildren.push(
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => closeSheet(),
        }, "Close")
      );
      if (!compact) {
        headChildren.push(
          el("button", {
            type: "button",
            className: "ghost-btn",
            onClick: () => {
              closeSheet();
              navigate(`/dynamic/${dynamicId}/assistant/chat`);
            },
          }, "Open full page")
        );
      } else {
        headChildren.push(
          el("button", {
            type: "button",
            className: "ghost-btn",
            onClick: () => {
              closeSheet();
              navigate(`/dynamic/${dynamicId}/assistant/chat`);
            },
          }, "All subjects")
        );
      }
    }
    root.appendChild(el("div", { className: "assistant-domme-sheet-inner" }, [
      el("div", { className: "assistant-domme-sheet-head row wrap" }, headChildren),
      el("p", { className: "muted" }, "Partner Chat is never sent. Nothing is assigned until you tap Apply."),
      index,
      title,
      blurb,
      prompts,
      perms,
      changes,
      log,
      error,
      input,
      sendBtn,
      tools,
    ]));
    if (!host) document.body.appendChild(root);
    paintPermissions(root, dynamicId, lastPermissions);
    paintChanges(root, lastChanges);
    paintExamplePrompts(root, lastExamplePrompts, input);

    const preferred = compact
      ? subjects[0]
      : (subjects.find((s) => s.nag)
        || subjects.find((s) => s.id === "what_can_you_do")
        || subjects.find((s) => s.id === "this_page")
        || subjects[0]);
    if (preferred) {
      const btn = [...index.querySelectorAll(".assistant-subject-btn")].find(
        (b) => b.dataset.subjectId === preferred.id
      );
      if (btn) selectSubject(preferred, btn);
    }
    if (!fullPage) sheetOpen = true;
    return root;
  }

  function closeSheet() {
    document.getElementById("assistant-domme-sheet")?.remove();
    sheetOpen = false;
  }

  async function toggleSheet() {
    if (sheetOpen) {
      closeSheet();
      return;
    }
    const dynamicId = currentDynamicId();
    if (!dynamicId) return;
    const payload = await fetchTriggers(dynamicId);
    if (!payload.available) {
      showToast("Assistant Domme is for the keyholder with AI turned on.");
      return;
    }
    if (payload.llm_configured === false) {
      showToast("No API key yet — you can still open Assistant and try Apply cards.");
    }
    const contextual = isAssistantContextScreen();
    buildChatUI(dynamicId, payload, {
      fullPage: false,
      pageContext: contextual,
      pageKey: contextual ? pageContextKey() : "",
    });
  }

  async function openFullPage(host, opts = {}) {
    const dynamicId = currentDynamicId() || opts.dynamicId;
    if (!dynamicId || !host) return;
    host.replaceChildren(el("p", { className: "muted" }, "Loading Assistant…"));
    const payload = await fetchTriggers(dynamicId);
    if (!payload.available) {
      host.replaceChildren(el("p", { className: "error" }, "Assistant Domme is for the keyholder with AI turned on."));
      return;
    }
    buildChatUI(dynamicId, payload, { fullPage: true, host });
    if (opts.subjectId) {
      const btn = host.querySelector(`[data-subject-id="${opts.subjectId}"]`);
      if (btn) btn.click();
    }
  }

  async function sync() {
    ensureFab();
    if (!assistantAvailable()) {
      setBadge(0);
      return;
    }
    const dynamicId = currentDynamicId();
    const payload = await fetchTriggers(dynamicId);
    if (!payload.available) {
      document.getElementById("assistant-domme-fab")?.remove();
      closeSheet();
      return;
    }
    lastNag = payload.nag_count || 0;
    lastPermissions = payload.permissions || lastPermissions;
    lastExamplePrompts = payload.example_prompts || lastExamplePrompts;
    lastLlmConfigured = payload.llm_configured !== false;
    setBadge(lastNag);
    const fab = document.getElementById("assistant-domme-fab");
    fab?.classList.toggle("on-context", isAssistantContextScreen());
  }

  function start() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      if (document.visibilityState !== "visible") return;
      if (!assistantAvailable()) return;
      sync().catch(() => {});
    }, 60000);
  }

  global.UbetraAssistantDomme = {
    sync,
    start,
    isFabHidden,
    setFabHidden,
    open: (opts = {}) => {
      if (opts.fullPage) return openFullPage(opts.host, opts);
      return toggleSheet();
    },
    close: closeSheet,
    openFullPage,
  };
})(window);
