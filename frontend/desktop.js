function desktopMode() {
  return window.matchMedia("(min-width: 1100px)").matches;
}

function bindDesktopModeRerender() {
  const mq = window.matchMedia("(min-width: 1100px)");
  const onChange = () => renderRoute();
  if (typeof mq.addEventListener === "function") mq.addEventListener("change", onChange);
  else if (typeof mq.addListener === "function") mq.addListener(onChange);
}

const TASK_SECTION_STORE = "ubetra_task_sections_v1";

function taskSectionIsOpen(id, fallback) {
  try {
    const map = JSON.parse(localStorage.getItem(TASK_SECTION_STORE) || "{}");
    if (Object.prototype.hasOwnProperty.call(map, id)) return !!map[id];
  } catch {
    /* keep fallback */
  }
  return !!fallback;
}

function rememberTaskSection(id, open) {
  let map = {};
  try {
    map = JSON.parse(localStorage.getItem(TASK_SECTION_STORE) || "{}");
  } catch {
    map = {};
  }
  map[id] = open ? 1 : 0;
  localStorage.setItem(TASK_SECTION_STORE, JSON.stringify(map));
}

function goalRequirementTags(goal) {
  return (goal?.requirements || [])
    .map((req) => (req?.type === "tasks_completed" ? String(req.tag || "").trim().toLowerCase() : ""))
    .filter(Boolean);
}

function activeGoalConfigs(goalsData) {
  const goals = goalsData?.config?.goals || [];
  return goals.filter((goal) => goal && goal.active !== false && !goal.archived_at);
}

function matchTaskGoal(task, goals) {
  const tags = (task?.tags || []).map((tag) => String(tag).trim().toLowerCase());
  if (!tags.length) return null;
  for (const goal of goals || []) {
    const needles = goalRequirementTags(goal);
    if (needles.some((needle) => tags.includes(needle))) return goal;
  }
  return null;
}

function taskDueChip(task) {
  const due = taskDueDate(task);
  if (!due) return "";
  return due.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function addMinutesIso(iso, minutes) {
  const when = parseServerDate(iso) || (iso ? new Date(iso) : null);
  if (!when || Number.isNaN(when.getTime())) return iso || null;
  return new Date(when.getTime() + Number(minutes) * 60000).toISOString();
}

function sheetDuration(startIso, endIso) {
  const start = parseServerDate(startIso) || (startIso ? new Date(startIso) : null);
  if (!start || Number.isNaN(start.getTime())) return "";
  const end = endIso ? (parseServerDate(endIso) || new Date(endIso)) : new Date();
  if (!end || Number.isNaN(end.getTime())) return "";
  return formatDurationMs(end.getTime() - start.getTime());
}

function downloadAuthedCsv(path, filename) {
  return el("button", {
    type: "button",
    className: "ghost-btn",
    onClick: async () => {
      const res = await fetch(`${API}${path}`, {
        headers: state.token ? { Authorization: `Bearer ${state.token}` } : {},
      });
      if (!res.ok) throw new Error("Could not export CSV");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = el("a", { href: url, download: filename });
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
  }, "Export CSV");
}

function createChangeSet() {
  const updates = new Map();
  const deletes = new Set();
  const listeners = new Set();
  const touch = () => listeners.forEach((fn) => fn());
  return {
    onChange(fn) { listeners.add(fn); },
    count() { return updates.size + deletes.size; },
    isDeleted(id) { return deletes.has(id); },
    get(id) { return updates.get(id) || null; },
    patch(id, fields) {
      if (deletes.has(id)) deletes.delete(id);
      const prev = updates.get(id) || { id };
      const next = { ...prev, ...fields, id };
      if (fields.breaks) {
        const byId = new Map((prev.breaks || []).map((row) => [row.id, row]));
        fields.breaks.forEach((row) => byId.set(row.id, { ...(byId.get(row.id) || {}), ...row }));
        next.breaks = [...byId.values()];
      }
      if (fields.delete_breaks) {
        next.delete_breaks = [...new Set([...(prev.delete_breaks || []), ...fields.delete_breaks])];
      }
      updates.set(id, next);
      touch();
    },
    patchBreak(parentId, breakId, fields) {
      this.patch(parentId, { breaks: [{ id: breakId, ...fields }] });
    },
    deleteBreak(parentId, breakId) {
      const prev = updates.get(parentId) || { id: parentId };
      updates.set(parentId, {
        ...prev,
        id: parentId,
        breaks: (prev.breaks || []).filter((row) => row.id !== breakId),
        delete_breaks: [...new Set([...(prev.delete_breaks || []), breakId])],
      });
      if (deletes.has(parentId)) deletes.delete(parentId);
      touch();
    },
    remove(id) {
      updates.delete(id);
      deletes.add(id);
      touch();
    },
    payload() {
      return { updates: [...updates.values()], deletes: [...deletes] };
    },
    clear() {
      updates.clear();
      deletes.clear();
      touch();
    },
  };
}

function promptMinutes(label) {
  const raw = window.prompt(label, "60");
  if (raw == null) return null;
  const minutes = Number(raw);
  if (!Number.isFinite(minutes) || minutes === 0) return null;
  return Math.trunc(minutes);
}

function splitTags(text) {
  return String(text || "").split(",").map((tag) => tag.trim()).filter(Boolean);
}

function sheetTextCell(display, value, onCommit) {
  const td = el("td");
  const show = () => {
    td.replaceChildren(el("button", {
      type: "button",
      className: "sheet-cell-btn",
      onClick: (ev) => {
        ev.stopPropagation();
        const input = el("input", { type: "text", value: value ?? "" });
        let done = false;
        const finish = (save) => {
          if (done) return;
          done = true;
          if (save) onCommit(input.value);
          show();
        };
        input.addEventListener("keydown", (ev2) => {
          if (ev2.key === "Enter") { ev2.preventDefault(); finish(true); }
          if (ev2.key === "Escape") { ev2.preventDefault(); finish(false); }
        });
        input.addEventListener("blur", () => finish(true));
        td.replaceChildren(input);
        input.focus();
        input.select();
      },
    }, display || "—"));
  };
  show();
  return td;
}

function sheetTimeCell(iso, onCommit) {
  const when = iso ? (parseServerDate(iso) || new Date(iso)) : null;
  const display = when && !Number.isNaN(when.getTime())
    ? when.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    : "—";
  const td = el("td");
  const show = () => {
    td.replaceChildren(el("button", {
      type: "button",
      className: "sheet-cell-btn",
      onClick: (ev) => {
        ev.stopPropagation();
        const input = el("input", { type: "datetime-local", value: iso ? toLocalDatetimeValue(iso) : "" });
        let done = false;
        const finish = (save) => {
          if (done) return;
          done = true;
          if (save) onCommit(input.value ? datetimeLocalToIso(input.value) : null);
          show();
        };
        input.addEventListener("keydown", (ev2) => {
          if (ev2.key === "Enter") { ev2.preventDefault(); finish(true); }
          if (ev2.key === "Escape") { ev2.preventDefault(); finish(false); }
        });
        input.addEventListener("blur", () => finish(true));
        td.replaceChildren(input);
        input.focus();
      },
    }, display));
  };
  show();
  return td;
}

function sheetSelectCell(display, options, current, onCommit) {
  const td = el("td");
  const show = () => {
    td.replaceChildren(el("button", {
      type: "button",
      className: "sheet-cell-btn",
      onClick: (ev) => {
        ev.stopPropagation();
        const select = el("select");
        options.forEach(([value, label]) => {
          const opt = el("option", { value }, label);
          if (String(value) === String(current ?? "")) opt.selected = true;
          select.appendChild(opt);
        });
        let done = false;
        const finish = (save) => {
          if (done) return;
          done = true;
          if (save) onCommit(select.value);
          show();
        };
        select.addEventListener("change", () => finish(true));
        select.addEventListener("blur", () => finish(true));
        select.addEventListener("keydown", (ev2) => {
          if (ev2.key === "Escape") { ev2.preventDefault(); finish(false); }
        });
        td.replaceChildren(select);
        select.focus();
      },
    }, display || "—"));
  };
  show();
  return td;
}

function sortSheetRows(rows, key, dir, valueOf) {
  const mul = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = valueOf(a, key);
    const bv = valueOf(b, key);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (av < bv) return -1 * mul;
    if (av > bv) return 1 * mul;
    return 0;
  });
}

function renderPendingBar(pending, { onSave, extras }) {
  const bar = el("div", { className: "sheet-pending card row wrap" });
  bar.classList.toggle("hidden", pending.count() === 0);
  bar.append(
    el("span", {}, `${pending.count()} unsaved change${pending.count() === 1 ? "" : "s"}`),
    ...(extras || []),
    el("button", { type: "button", className: "ghost-btn", onClick: () => pending.clear() }, "Discard"),
    el("button", {
      type: "button",
      className: "primary-btn",
      onClick: onSave,
    }, "Save"),
  );
  return bar;
}

const LOCK_KINDS = [
  ["", "Active"],
  ["unlocked", "Unlocked"],
  ["released_orgasm", "Released"],
  ["released_timer", "Timer release"],
  ["historical", "Historical"],
];

const BREAK_KINDS = [
  ["emergency_hygiene", "Hygiene"],
  ["emergency_sleep", "Sleep"],
  ["emergency_discomfort", "Discomfort"],
  ["emergency_medical", "Medical"],
  ["emergency_other", "Other"],
  ["authorized_hygiene", "Authorized hygiene"],
  ["authorized_sleep", "Authorized sleep"],
  ["authorized_play", "Authorized play"],
  ["authorized_denial", "Authorized denial"],
  ["authorized_ruin", "Authorized ruin"],
  ["authorized_other", "Authorized other"],
];

function renderChastityDesktopTable(dynamicId, lockups, { partners = [], onSaved } = {}) {
  const pending = createChangeSet();
  const selected = new Set();
  const expanded = new Set();
  let sortKey = "started_at";
  let sortDir = "desc";
  const host = el("div", { className: "stack" });
  const partnerOptions = (partners || []).map((p) => [p.id || p.membership_id, p.display_name || p.name]);

  function viewOf(lockup) {
    const patch = pending.get(lockup.id) || {};
    const removed = new Set(patch.delete_breaks || []);
    const breaks = (lockup.breaks || [])
      .filter((brk) => !removed.has(brk.id))
      .map((brk) => {
        const edited = (patch.breaks || []).find((row) => row.id === brk.id);
        return edited ? { ...brk, ...edited } : brk;
      });
    return {
      ...lockup,
      started_at: patch.started_at || lockup.started_at,
      ended_at: patch.clear_ended_at ? null : (patch.ended_at !== undefined ? patch.ended_at : lockup.ended_at),
      device_notes: patch.device_notes !== undefined ? patch.device_notes : lockup.device_notes,
      tags: patch.tags !== undefined ? patch.tags : (lockup.tags || []),
      ended_kind: patch.ended_kind !== undefined ? patch.ended_kind : (lockup.ended_kind || ""),
      for_membership_id: patch.for_membership_id || lockup.for_membership_id,
      for_display_name: partnerOptions.find((p) => p[0] === (patch.for_membership_id || lockup.for_membership_id))?.[1]
        || lockup.for_display_name,
      breaks,
    };
  }

  function valueOf(lockup, key) {
    const row = viewOf(lockup);
    if (key === "started_at" || key === "ended_at") return row[key] || "";
    if (key === "duration") return sheetDuration(row.started_at, row.ended_at);
    if (key === "kind") return row.ended_kind || "";
    if (key === "tags") return (row.tags || []).join(", ");
    if (key === "note") return row.device_notes || "";
    if (key === "partner") return row.for_display_name || "";
    return "";
  }

  function paint() {
    const visible = (lockups || []).filter((lockup) => !pending.isDeleted(lockup.id));
    const ordered = sortSheetRows(visible, sortKey, sortDir, valueOf);
    const table = el("table", { className: "sheet-table" });
    const head = el("tr", {}, [
      el("th", {}, ""),
      ...[
        ["started_at", "Start"],
        ["ended_at", "End"],
        ["duration", "Duration"],
        ["kind", "Kind"],
        ["tags", "Tags"],
        ["note", "Note"],
        ["partner", "Partner"],
      ].map(([key, label]) => el("th", {
        onClick: () => {
          if (sortKey === key) sortDir = sortDir === "asc" ? "desc" : "asc";
          else { sortKey = key; sortDir = key === "started_at" ? "desc" : "asc"; }
          paint();
        },
      }, `${label}${sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}`)),
    ]);
    table.appendChild(el("thead", {}, [head]));
    const body = el("tbody");
    ordered.forEach((lockup) => {
      const row = viewOf(lockup);
      const check = el("input", { type: "checkbox" });
      check.checked = selected.has(lockup.id);
      check.addEventListener("change", () => {
        if (check.checked) selected.add(lockup.id);
        else selected.delete(lockup.id);
        paint();
      });
      const toggle = el("button", {
        type: "button",
        className: "sheet-expand",
        onClick: () => {
          if (expanded.has(lockup.id)) expanded.delete(lockup.id);
          else expanded.add(lockup.id);
          paint();
        },
      }, expanded.has(lockup.id) ? "▾" : "▸");
      const tr = el("tr", {}, [
        el("td", {}, [check, toggle]),
        sheetTimeCell(row.started_at, (iso) => pending.patch(lockup.id, { started_at: iso })),
        sheetTimeCell(row.ended_at, (iso) => pending.patch(lockup.id, iso ? { ended_at: iso, clear_ended_at: false } : { clear_ended_at: true })),
        sheetTextCell(sheetDuration(row.started_at, row.ended_at), "", (text) => {
          if (!String(text).trim()) return;
          const mins = Number(text);
          if (!Number.isFinite(mins) || mins < 0) return;
          pending.patch(lockup.id, { ended_at: addMinutesIso(row.started_at, mins), clear_ended_at: false });
        }),
        sheetSelectCell(
          LOCK_KINDS.find((item) => item[0] === (row.ended_kind || ""))?.[1] || row.ended_kind || "Active",
          LOCK_KINDS,
          row.ended_kind || "",
          (value) => pending.patch(lockup.id, { ended_kind: value }),
        ),
        sheetTextCell((row.tags || []).join(", "), (row.tags || []).join(", "), (text) => pending.patch(lockup.id, { tags: splitTags(text) })),
        sheetTextCell(row.device_notes || "", row.device_notes || "", (text) => pending.patch(lockup.id, { device_notes: text })),
        partnerOptions.length
          ? sheetSelectCell(row.for_display_name || "—", partnerOptions, row.for_membership_id, (value) => pending.patch(lockup.id, { for_membership_id: value }))
          : el("td", {}, row.for_display_name || "—"),
      ]);
      body.appendChild(tr);
      if (expanded.has(lockup.id)) {
        const sub = el("tr", { className: "sheet-sub" }, [
          el("td", { colspan: "8" }, [renderBreakTable(lockup, row)]),
        ]);
        body.appendChild(sub);
      }
    });
    table.appendChild(body);
    const bulk = el("div", { className: "row wrap" });
    if (selected.size) {
      bulk.append(
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => { selected.forEach((id) => pending.remove(id)); selected.clear(); },
        }, "Delete"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            const text = window.prompt("Set tags (comma-separated)");
            if (text == null) return;
            const tags = splitTags(text);
            selected.forEach((id) => pending.patch(id, { tags }));
          },
        }, "Set tags"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            const text = window.prompt("Remove tags (comma-separated)");
            if (text == null) return;
            const drop = new Set(splitTags(text).map((tag) => tag.toLowerCase()));
            selected.forEach((id) => {
              const lockup = lockups.find((item) => item.id === id);
              if (!lockup) return;
              const tags = (viewOf(lockup).tags || []).filter((tag) => !drop.has(String(tag).toLowerCase()));
              pending.patch(id, { tags });
            });
          },
        }, "Remove tags"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            const minutes = promptMinutes("Shift start and end by minutes (negative moves earlier)");
            if (minutes == null) return;
            selected.forEach((id) => {
              const lockup = lockups.find((item) => item.id === id);
              if (!lockup) return;
              const view = viewOf(lockup);
              const patch = { started_at: addMinutesIso(view.started_at, minutes) };
              if (view.ended_at) patch.ended_at = addMinutesIso(view.ended_at, minutes);
              pending.patch(id, patch);
            });
          },
        }, "Shift times"),
      );
    }
    host.replaceChildren(
      el("div", { className: "sheet-wrap" }, [table]),
      bulk,
      renderPendingBar(pending, {
        onSave: async () => {
          await api(`/dynamics/${dynamicId}/chastity/bulk`, {
            method: "PATCH",
            body: JSON.stringify(pending.payload()),
          });
          showToast("Chastity changes saved.");
          onSaved?.();
        },
      }),
    );
  }

  function renderBreakTable(lockup, view) {
    const table = el("table", { className: "sheet-table" });
    table.appendChild(el("thead", {}, [
      el("tr", {}, ["Start", "End", "Duration", "Kind", "Tags", "Note", ""].map((label) => el("th", {}, label))),
    ]));
    const body = el("tbody");
    (view.breaks || []).forEach((brk) => {
      body.appendChild(el("tr", {}, [
        sheetTimeCell(brk.started_at, (iso) => pending.patchBreak(lockup.id, brk.id, { started_at: iso })),
        sheetTimeCell(brk.ended_at, (iso) => pending.patchBreak(lockup.id, brk.id, iso ? { ended_at: iso, clear_ended_at: false } : { clear_ended_at: true })),
        el("td", {}, sheetDuration(brk.started_at, brk.ended_at)),
        sheetSelectCell(
          BREAK_KINDS.find((item) => item[0] === brk.break_type)?.[1] || brk.break_type || "—",
          BREAK_KINDS,
          brk.break_type,
          (value) => pending.patchBreak(lockup.id, brk.id, { break_type: value }),
        ),
        sheetTextCell((brk.tags || []).join(", "), (brk.tags || []).join(", "), (text) => pending.patchBreak(lockup.id, brk.id, { tags: splitTags(text) })),
        sheetTextCell(brk.note || "", brk.note || "", (text) => pending.patchBreak(lockup.id, brk.id, { note: text })),
        el("td", {}, el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => pending.deleteBreak(lockup.id, brk.id),
        }, "Delete")),
      ]));
    });
    if (!(view.breaks || []).length) body.appendChild(el("tr", {}, [el("td", { colspan: "7" }, "No breaks")]));
    table.appendChild(body);
    return table;
  }

  pending.onChange(paint);
  paint();
  return host;
}

function renderTrackingDesktopTable(dynamicId, entries, { partners = [], onSaved } = {}) {
  const pending = createChangeSet();
  const selected = new Set();
  let sortKey = "started_at";
  let sortDir = "desc";
  const host = el("div", { className: "stack" });
  const partnerOptions = (partners || []).map((p) => [p.id, p.display_name]);
  const kinds = [["orgasm", "Orgasm"], ["no_orgasm", "Play"]];

  function viewOf(entry) {
    const patch = pending.get(entry.id) || {};
    const partnerId = patch.for_membership_id || entry.for_membership_id;
    return {
      ...entry,
      occurred_at: patch.occurred_at || entry.occurred_at,
      ended_at: patch.ended_at !== undefined ? patch.ended_at : entry.ended_at,
      notes: patch.notes !== undefined ? patch.notes : entry.notes,
      tags: patch.tags !== undefined ? patch.tags : (entry.tags || []),
      event_type: patch.event_type || entry.event_type,
      for_membership_id: partnerId,
      for_display_name: partnerOptions.find((p) => p[0] === partnerId)?.[1] || entry.for_display_name,
    };
  }

  function valueOf(entry, key) {
    const row = viewOf(entry);
    if (key === "started_at") return row.occurred_at || "";
    if (key === "ended_at") return row.ended_at || "";
    if (key === "duration") return sheetDuration(row.occurred_at, row.ended_at);
    if (key === "kind") return row.event_type || "";
    if (key === "tags") return (row.tags || []).join(", ");
    if (key === "note") return row.notes || "";
    if (key === "partner") return row.for_display_name || "";
    return "";
  }

  function paint() {
    const visible = (entries || []).filter((entry) => !pending.isDeleted(entry.id));
    const ordered = sortSheetRows(visible, sortKey, sortDir, valueOf);
    const table = el("table", { className: "sheet-table" });
    const head = el("tr", {}, [
      el("th", {}, ""),
      ...[
        ["started_at", "Start"],
        ["ended_at", "End"],
        ["duration", "Duration"],
        ["kind", "Kind"],
        ["tags", "Tags"],
        ["note", "Note"],
        ["partner", "Partner"],
      ].map(([key, label]) => el("th", {
        onClick: () => {
          if (sortKey === key) sortDir = sortDir === "asc" ? "desc" : "asc";
          else { sortKey = key; sortDir = "asc"; }
          paint();
        },
      }, `${label}${sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}`)),
    ]);
    table.appendChild(el("thead", {}, [head]));
    const body = el("tbody");
    ordered.forEach((entry) => {
      const row = viewOf(entry);
      const check = el("input", { type: "checkbox" });
      check.checked = selected.has(entry.id);
      check.addEventListener("change", () => {
        if (check.checked) selected.add(entry.id);
        else selected.delete(entry.id);
        paint();
      });
      body.appendChild(el("tr", {}, [
        el("td", {}, [check]),
        sheetTimeCell(row.occurred_at, (iso) => pending.patch(entry.id, { occurred_at: iso })),
        sheetTimeCell(row.ended_at, (iso) => pending.patch(entry.id, { ended_at: iso })),
        sheetTextCell(sheetDuration(row.occurred_at, row.ended_at), "", (text) => {
          if (!String(text).trim()) return;
          const mins = Number(text);
          if (!Number.isFinite(mins) || mins < 0) return;
          pending.patch(entry.id, { ended_at: addMinutesIso(row.occurred_at, mins), duration_minutes: Math.round(mins) });
        }),
        sheetSelectCell(
          kinds.find((item) => item[0] === row.event_type)?.[1] || row.event_type,
          kinds,
          row.event_type,
          (value) => pending.patch(entry.id, { event_type: value }),
        ),
        sheetTextCell((row.tags || []).join(", "), (row.tags || []).join(", "), (text) => pending.patch(entry.id, { tags: splitTags(text) })),
        sheetTextCell(row.notes || "", row.notes || "", (text) => pending.patch(entry.id, { notes: text })),
        sheetSelectCell(row.for_display_name || "—", partnerOptions, row.for_membership_id, (value) => pending.patch(entry.id, { for_membership_id: value })),
      ]));
    });
    table.appendChild(body);
    const bulk = el("div", { className: "row wrap" });
    if (selected.size) {
      bulk.append(
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => { selected.forEach((id) => pending.remove(id)); selected.clear(); },
        }, "Delete"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            const text = window.prompt("Set tags (comma-separated)");
            if (text == null) return;
            const tags = splitTags(text);
            selected.forEach((id) => pending.patch(id, { tags }));
          },
        }, "Set tags"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            const text = window.prompt("Remove tags (comma-separated)");
            if (text == null) return;
            const drop = new Set(splitTags(text).map((tag) => tag.toLowerCase()));
            selected.forEach((id) => {
              const entry = entries.find((item) => item.id === id);
              if (!entry) return;
              const tags = (viewOf(entry).tags || []).filter((tag) => !drop.has(String(tag).toLowerCase()));
              pending.patch(id, { tags });
            });
          },
        }, "Remove tags"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            const minutes = promptMinutes("Shift start and end by minutes (negative moves earlier)");
            if (minutes == null) return;
            selected.forEach((id) => {
              const entry = entries.find((item) => item.id === id);
              if (!entry) return;
              const view = viewOf(entry);
              const patch = { occurred_at: addMinutesIso(view.occurred_at, minutes) };
              if (view.ended_at) patch.ended_at = addMinutesIso(view.ended_at, minutes);
              pending.patch(id, patch);
            });
          },
        }, "Shift times"),
      );
    }
    host.replaceChildren(
      el("div", { className: "sheet-wrap" }, [table]),
      bulk,
      renderPendingBar(pending, {
        onSave: async () => {
          await api(`/dynamics/${dynamicId}/tracking/bulk`, {
            method: "PATCH",
            body: JSON.stringify(pending.payload()),
          });
          showToast("Tracking changes saved.");
          onSaved?.();
        },
      }),
    );
  }

  pending.onChange(paint);
  paint();
  return host;
}

function renderTaskDesktopTable(dynamicId, rows, { partners = [], goals = [], onSaved, onOpen, onError } = {}) {
  const pending = createChangeSet();
  const selected = new Set();
  let sortKey = "due";
  let sortDir = "asc";
  const host = el("div", { className: "stack" });
  const assignees = [["", "Unassigned"], ...(partners || []).map((p) => [p.id, p.display_name])];
  const recurrences = [["none", "None"], ["daily", "Daily"], ["weekly", "Weekly"], ["monthly", "Monthly"]];

  function viewOf(row) {
    const patch = pending.get(row.task.id) || {};
    return { ...row.task, ...patch, tags: patch.tags !== undefined ? patch.tags : (row.task.tags || []) };
  }

  function valueOf(row, key) {
    const task = viewOf(row);
    if (key === "status") return task.completed_at ? "done" : task.paused ? "paused" : "open";
    if (key === "task") return task.content || "";
    if (key === "assignee") return task.assigned_to_display_name || "";
    if (key === "due") return task.next_due_at || task.due_at || "";
    if (key === "recurrence") return task.recurrence || "";
    if (key === "reminders") return Array.isArray(task.reminder_offsets) ? task.reminder_offsets.join(",") : "";
    if (key === "tags") return (task.tags || []).join(", ");
    if (key === "goal") return matchTaskGoal(task, goals)?.title || "";
    return "";
  }

  function statusLabel(task) {
    if (task.completed_at || task.mark_complete) return "Complete";
    if (task.paused) return "Paused";
    if (task.approval_status === "pending") return "Needs approval";
    if (taskIsPastDue(task)) return "Late";
    return "Open";
  }

  function paint() {
    const visible = rows.filter((row) => !pending.isDeleted(row.task.id));
    const ordered = sortSheetRows(visible, sortKey, sortDir, valueOf);
    const table = el("table", { className: "sheet-table" });
    table.appendChild(el("thead", {}, [
      el("tr", {}, [
        el("th", {}, ""),
        ...[
          ["status", "Status"],
          ["task", "Task"],
          ["assignee", "Assignee"],
          ["due", "Due"],
          ["recurrence", "Recurrence"],
          ["reminders", "Reminders"],
          ["tags", "Tags"],
          ["goal", "Goal"],
        ].map(([key, label]) => el("th", {
          onClick: () => {
            if (sortKey === key) sortDir = sortDir === "asc" ? "desc" : "asc";
            else { sortKey = key; sortDir = "asc"; }
            paint();
          },
        }, `${label}${sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}`)),
      ]),
    ]));
    const body = el("tbody");
    ordered.forEach((row) => {
      const task = viewOf(row);
      const check = el("input", { type: "checkbox" });
      check.checked = selected.has(task.id);
      check.addEventListener("click", (ev) => ev.stopPropagation());
      check.addEventListener("change", () => {
        if (check.checked) selected.add(task.id);
        else selected.delete(task.id);
        paint();
      });
      const goal = matchTaskGoal(task, goals);
      const goalCell = el("td");
      if (goal) {
        goalCell.appendChild(el("button", {
          type: "button",
          className: "tag-chip task-goal-chip",
          onClick: () => navigate(`/dynamic/${dynamicId}/tasks?tab=goals&goal=${encodeURIComponent(goal.id)}`),
        }, goal.title || "Goal"));
      } else goalCell.textContent = "—";
      const title = el("button", {
        type: "button",
        className: "sheet-cell-btn",
        onClick: () => onOpen?.(row.list, row.task),
      }, task.content || "Task");
      body.appendChild(el("tr", {}, [
        el("td", {}, [check]),
        sheetSelectCell(statusLabel(task), [["open", "Open"], ["paused", "Paused"], ["complete", "Complete"]], task.paused ? "paused" : "open", (value) => {
          if (value === "complete") pending.patch(task.id, { mark_complete: true, completed_at: new Date().toISOString(), paused: false });
          else if (value === "paused") pending.patch(task.id, { paused: true, mark_complete: false });
          else pending.patch(task.id, { paused: false, mark_complete: false });
        }),
        el("td", {}, [
          title,
          el("button", {
            type: "button",
            className: "sheet-cell-btn",
            onClick: (ev) => {
              ev.stopPropagation();
              const input = el("input", { type: "text", value: task.content || "" });
              input.addEventListener("change", () => pending.patch(task.id, { content: input.value.trim() }));
              input.addEventListener("blur", () => { if (input.value.trim()) pending.patch(task.id, { content: input.value.trim() }); });
              title.replaceWith(input);
              input.focus();
            },
          }, "Edit"),
        ]),
        sheetSelectCell(
          assignees.find((item) => item[0] === (task.assigned_to_membership_id || ""))?.[1] || task.assigned_to_display_name || "Unassigned",
          assignees,
          task.clear_assignee ? "" : (task.assigned_to_membership_id || ""),
          (value) => pending.patch(task.id, value ? { assigned_to_membership_id: value, clear_assignee: false } : { clear_assignee: true }),
        ),
        sheetTimeCell(task.due_at || task.next_due_at, (iso) => { if (iso) pending.patch(task.id, { due_at: iso }); }),
        sheetSelectCell(task.recurrence || "none", recurrences, task.recurrence || "none", (value) => pending.patch(task.id, { recurrence: value })),
        sheetTextCell(
          Array.isArray(task.reminder_offsets) ? formatReminderOffsets(task.reminder_offsets) : "Default",
          Array.isArray(task.reminder_offsets) ? task.reminder_offsets.join(", ") : "",
          (text) => {
            const offsets = splitTags(text).map((part) => Number(part)).filter((n) => Number.isFinite(n));
            pending.patch(task.id, { reminder_offsets: offsets });
          },
        ),
        sheetTextCell((task.tags || []).join(", "), (task.tags || []).join(", "), (text) => pending.patch(task.id, { tags: splitTags(text) })),
        goalCell,
      ]));
    });
    table.appendChild(body);
    const bulk = el("div", { className: "row wrap" });
    if (selected.size) {
      const reassign = el("select");
      assignees.forEach(([value, label]) => reassign.appendChild(el("option", { value }, label)));
      bulk.append(
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => selected.forEach((id) => pending.patch(id, { mark_complete: true, completed_at: new Date().toISOString() })),
        }, "Complete"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => selected.forEach((id) => pending.patch(id, { paused: true })),
        }, "Pause"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => { selected.forEach((id) => pending.remove(id)); selected.clear(); },
        }, "Delete"),
        reassign,
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            selected.forEach((id) => pending.patch(id, reassign.value
              ? { assigned_to_membership_id: reassign.value, clear_assignee: false }
              : { clear_assignee: true }));
          },
        }, "Reassign"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            const minutes = promptMinutes("Shift due dates by minutes (negative moves earlier)");
            if (minutes == null) return;
            selected.forEach((id) => pending.patch(id, { due_shift_minutes: minutes }));
          },
        }, "Shift due"),
        el("button", {
          type: "button",
          className: "ghost-btn",
          onClick: () => {
            const text = window.prompt("Reminder minutes, comma-separated (for example 30, 10)");
            if (text == null) return;
            const offsets = splitTags(text).map((part) => Number(part)).filter((n) => Number.isFinite(n));
            selected.forEach((id) => pending.patch(id, { reminder_offsets: offsets }));
          },
        }, "Set reminders"),
      );
    }
    host.replaceChildren(
      el("div", { className: "sheet-wrap" }, [table]),
      bulk,
      renderPendingBar(pending, {
        onSave: async () => {
          try {
            await api(`/dynamics/${dynamicId}/tasks/bulk-update`, {
              method: "PATCH",
              body: JSON.stringify(pending.payload()),
            });
            showToast("Task changes saved.");
            onSaved?.();
          } catch (err) {
            onError?.(err.message);
          }
        },
      }),
    );
  }

  pending.onChange(paint);
  paint();
  return host;
}
