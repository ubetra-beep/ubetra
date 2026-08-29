/* UBETRA Instructor — Playtime game.
 *
 * Game design adapted from rororosi/fapinstructor-client (GPL-2.0), itself a
 * Fap Instructor client. Auth0/Sentry/live scrapers are not included.
 * Media is local redgifs + optional chat vault. See plugins/instructor/LICENSE.txt.
 *
 * Depends on globals from app.js: el, api, API, state, showToast, navigate
 */
(function (global) {
  const HUD_KEY = "ubetra-instructor-hud";
  const BEAT_PX_PER_SEC = 92;
  let overlayOpen = false;
  let overlayIncoming = null;
  let pendingIncoming = null;
  let dismissedSessionId = "";
  const GRIP_LABELS = ["Barely touching", "Very light", "Light", "Normal", "Tight", "Very tight", "Death grip"];
  const STYLE_LABELS = {
    dominant: "Dominant",
    nondominant: "Nondominant",
    headOnly: "Head Only",
    shaftOnly: "Shaft Only",
    overhandGrip: "Overhand Grip",
    bothHands: "Both Hands",
    handsOff: "Hands Off",
  };
  const TASK_GROUPS = [
    {
      id: "speed",
      label: "Speed",
      tasks: {
        doubleStrokes: "Double Strokes",
        halvedStrokes: "Halved Strokes",
        teasingStrokes: "Teasing Strokes",
        accelerationCycles: "Acceleration Cycles",
        randomBeat: "Random Beats",
        randomStrokeSpeed: "Random Stroke Speed",
        redLightGreenLight: "Red Light Green Light",
        clusterStrokes: "Cluster Strokes",
        gripChallenge: "Grip Challenge",
      },
    },
    {
      id: "style",
      label: "Stroke Style",
      tasks: {
        dominant: "Dominant",
        nondominant: "Nondominant",
        headOnly: "Head Only",
        shaftOnly: "Shaft Only",
        overhandGrip: "Overhand Grip",
        bothHands: "Both Hands",
        handsOff: "Hands Off",
      },
    },
    {
      id: "cbt",
      label: "Cock & Ball Torture",
      tasks: {
        bindCockBalls: "Bind Cock and Balls",
        rubberBands: "Rubber Bands",
        clothespins: "Clothespins",
        headPalming: "Head Palming",
        icyHot: "Icy Hot",
        toothpaste: "Toothpaste",
        ballSlaps: "Ball Slaps",
        squeezeBalls: "Squeeze Balls",
        breathPlay: "Breath Play",
        scratching: "Scratching",
        flicking: "Flicking",
        cbtIce: "Ice cubes",
      },
    },
    {
      id: "cei",
      label: "Cum Eating",
      tasks: { precum: "Precum" },
    },
    {
      id: "anal",
      label: "Anal",
      tasks: { buttplug: "Butt Plug" },
    },
    {
      id: "nipple",
      label: "Nipples",
      tasks: { rubNipples: "Rub Nipples", nipplesAndStroke: "Nipples and Stroking" },
    },
  ];
  const TASK_WEIGHT = {
    doubleStrokes: 15,
    halvedStrokes: 5,
    teasingStrokes: 5,
    randomBeat: 5,
    randomStrokeSpeed: 20,
    accelerationCycles: 7,
    redLightGreenLight: 7,
    clusterStrokes: 7,
    handsOff: 5,
    gripChallenge: 7,
    dominant: 15,
    nondominant: 5,
    headOnly: 1,
    shaftOnly: 2,
    overhandGrip: 1,
    bothHands: 5,
    precum: 3,
    buttplug: 3,
    rubNipples: 5,
    nipplesAndStroke: 10,
    ballSlaps: 4,
    squeezeBalls: 4,
    rubberBands: 2,
    bindCockBalls: 1,
    icyHot: 1,
    toothpaste: 1,
    headPalming: 1,
    breathPlay: 1,
    scratching: 1,
    flicking: 1,
    cbtIce: 1,
    clothespins: 3,
  };
  const EDGE_LINES = [
    "Edge! I know you can do it.",
    "Get to the edge for me.",
    "Edge!",
    "Get to the edge.",
    "Edge for me.",
    "Time to Edge!",
  ];
  const RUIN_LINES = [
    "RUIN IT! That's right, no full orgasms for you!",
    "Ruin it. Hands off as soon as you start.",
    "RUIN. NOW.",
  ];
  const DENY_LINES = [
    "Hands off! No cumming for you today.",
    "Stop. Put it away.",
    "STOP! No cumming.",
  ];
  const HANDS_OFF_LINES = [
    "Let go.",
    "Hands off!",
    "Don't you dare touch.",
    "Relax. Rest for a bit.",
  ];

  function clamp(n, lo, hi) {
    return Math.max(lo, Math.min(hi, n));
  }
  function randInt(lo, hi) {
    return lo + Math.floor(Math.random() * (hi - lo + 1));
  }
  function pick(list) {
    return list[Math.floor(Math.random() * list.length)];
  }
  function shuffle(list) {
    const next = list.slice();
    for (let i = next.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [next[i], next[j]] = [next[j], next[i]];
    }
    return next;
  }
  function loadHud(isDom) {
    const base = { ticks: true, beatMeter: true, videoAudio: !isDom, statusOpen: true, zoom: false };
    try {
      const saved = JSON.parse(localStorage.getItem(HUD_KEY) || "{}");
      const merged = { ...base, ...saved };
      if (isDom) merged.videoAudio = false;
      return merged;
    } catch {
      return base;
    }
  }
  function saveHud(hud) {
    try { localStorage.setItem(HUD_KEY, JSON.stringify(hud)); } catch { /* ignore */ }
  }

  let sharedAudioCtx = null;
  function unlockInstructorAudio() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!sharedAudioCtx || sharedAudioCtx.state === "closed") {
      sharedAudioCtx = new AC();
    }
    sharedAudioCtx.resume?.();
    try {
      const buf = sharedAudioCtx.createBuffer(1, 1, 22050);
      const src = sharedAudioCtx.createBufferSource();
      src.buffer = buf;
      src.connect(sharedAudioCtx.destination);
      src.start(0);
    } catch { /* ignore */ }
    return sharedAudioCtx;
  }
  function controllerDisplayName() {
    const partner = (state.currentDynamic?.partners || []).find((p) => p.role === "dominant");
    return String(partner?.display_name || partner?.username || "Instructor");
  }
  function tokenQuery(url) {
    if (!state?.token) return url;
    return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(state.token);
  }
  function mediaSrc(item) {
    if (item?.url && item.url.startsWith("/api/")) return tokenQuery(item.url);
    return "";
  }
  function vaultBlob(item) {
    const raw = String(item?.image_encrypted || "");
    return raw.startsWith("ubetra:plain:") ? raw.slice("ubetra:plain:".length) : raw;
  }
  function speak(text, hud) {
    if (!hud.voice || !text) return;
    try {
      window.speechSynthesis?.cancel();
      const u = new SpeechSynthesisUtterance(String(text).replace(/[!]+/g, "."));
      u.rate = 1;
      u.pitch = 1.05;
      window.speechSynthesis.speak(u);
    } catch { /* ignore */ }
  }

  function createAudio() {
    let tickTimer = null;
    let speed = 1;
    let hud = { ticks: true };
    let pulseFn = null;
    let silent = false;
    let nextBeatAt = 0;
    let epoch = Date.now();

    function ensure() {
      return unlockInstructorAudio();
    }
    function intervalMs() {
      return Math.max(120, Math.round(1000 / Math.max(0.15, speed)));
    }
    function nextAligned() {
      const ms = intervalMs();
      const elapsed = Date.now() - epoch;
      const rem = ((elapsed % ms) + ms) % ms;
      return Date.now() + (ms - rem || ms);
    }
    function beep() {
      const audio = ensure();
      if (!audio) return;
      const play = () => {
        if (audio.state !== "running") return;
        const t = clamp((speed - 0.2) / 3.8, 0, 1);
        const osc = audio.createOscillator();
        const gain = audio.createGain();
        osc.type = "triangle";
        osc.frequency.value = 196 * Math.pow(2, t * 2.15);
        gain.gain.value = 0.11 + t * 0.05;
        osc.connect(gain);
        gain.connect(audio.destination);
        osc.start();
        const dur = 0.08;
        gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + dur);
        osc.stop(audio.currentTime + dur + 0.02);
      };
      if (audio.state === "suspended") {
        Promise.resolve(audio.resume?.()).then(play).catch(() => {});
        return;
      }
      play();
    }
    function tick() {
      pulseFn?.(true);
      if (silent || !hud.ticks) return;
      try { beep(); } catch { /* ignore */ }
    }
    function scheduleTick() {
      if (tickTimer) clearTimeout(tickTimer);
      nextBeatAt = nextAligned();
      const loop = () => {
        tick();
        nextBeatAt += intervalMs();
        tickTimer = setTimeout(loop, Math.max(10, nextBeatAt - Date.now()));
      };
      tickTimer = setTimeout(loop, Math.max(10, nextBeatAt - Date.now()));
    }
    return {
      setPulse(fn) { pulseFn = fn; },
      setHud(next) { hud = next || hud; },
      setEpoch(ms) {
        epoch = Number(ms) || Date.now();
        scheduleTick();
      },
      setSpeed(next, epochMs) {
        speed = clamp(Number(next) || 1, 0.1, 8);
        if (epochMs != null && Number(epochMs) > 0) epoch = Number(epochMs);
        scheduleTick();
        return speed;
      },
      getSpeed() { return speed; },
      getIntervalMs: intervalMs,
      getNextBeatAt() { return nextBeatAt; },
      nextBeatIn() { return Math.max(0, (nextBeatAt - Date.now()) / 1000); },
      mute(on) { silent = !!on; },
      resume() {
        ensure()?.resume?.();
        scheduleTick();
      },
      stop() {
        if (tickTimer) clearTimeout(tickTimer);
        tickTimer = null;
      },
    };
  }

  async function fetchCatalog(dynamicId) {
    return api(`/dynamics/${dynamicId}/instructor/catalog`);
  }

  function applyLive(root, live, audio, videoEl, hud, stageWrap) {
    const paused = !!live?.paused;
    const red = !!live?.red_light;
    const lock = !!live?.lock_input;
    root.classList.toggle("instructor-paused", paused);
    root.classList.toggle("instructor-locked", lock);
    let cover = stageWrap?.querySelector(".instructor-red-cover");
    if (red) {
      if (!cover && stageWrap) {
        cover = el("div", { className: "instructor-red-cover" }, "RED LIGHT");
        stageWrap.appendChild(cover);
      }
    } else {
      cover?.remove();
    }
    if (videoEl) {
      if (paused || red) videoEl.pause?.();
      else if (videoEl.tagName === "VIDEO") videoEl.play?.().catch(() => {});
      if (videoEl.tagName === "VIDEO") videoEl.muted = !hud.videoAudio || red;
    }
    return { paused, red, lock };
  }

  function switchRow(id, label, checked, onChange) {
    const box = el("input", { type: "checkbox", id, className: "instructor-switch-input" });
    box.checked = !!checked;
    box.addEventListener("change", () => onChange(!!box.checked));
    return el("label", { className: "instructor-switch" }, [
      box,
      label,
      el("span", { className: "instructor-switch-track" }, el("span", { className: "instructor-switch-thumb" })),
    ]);
  }

  function showOverlaySheet(host, { title, buttons }) {
    return new Promise((resolve) => {
      const sheet = el("div", { className: "instructor-sheet" }, [
        el("p", { className: "instructor-sheet-title" }, title),
        ...buttons.map((btn) => el("button", {
          type: "button",
          className: btn.danger ? "danger-btn" : (btn.primary ? "primary-btn" : "ghost-btn"),
          onClick: () => {
            sheet.remove();
            resolve(btn.id);
          },
        }, btn.label)),
      ]);
      host.appendChild(sheet);
    });
  }

  async function openSession(dynamicId, opts = {}) {
    unlockInstructorAudio();
    if (overlayOpen) return;
    overlayOpen = true;
    const you = state.currentDynamic?.partners?.find((p) => p.is_you);
    const isDom = you?.role === "dominant";
    const controllerName = controllerDisplayName();
    let catalog;
    try {
      catalog = await fetchCatalog(dynamicId);
    } catch (err) {
      overlayOpen = false;
      showToast(err.message || "Could not load Instructor");
      return;
    }
    const config = catalog.config || {};
    const hud = loadHud(isDom);
    const minMin = Number(config.duration_min || 5);
    const maxMin = Math.max(minMin, Number(config.duration_max || minMin));
    const durationMin = opts.minutes || randInt(minMin, maxMin);
    const actionSec = Number(config.action_frequency || 30);
    const speedMin = Number(config.stroke_min || 0.25);
    const speedMax = Number(config.stroke_max || 4);
    const tasks = (config.tasks || []).filter((id) => TASK_WEIGHT[id] || STYLE_LABELS[id]);

    function mediaByKey(list) {
      const map = new Map();
      (list || []).forEach((item) => {
        if (item?.key) map.set(item.key, item);
      });
      return map;
    }
    function orderMedia(live, catalogMedia) {
      const byKey = mediaByKey(catalogMedia);
      const keys = live?.media_keys || [];
      const ordered = keys.map((key) => byKey.get(key)).filter(Boolean);
      return ordered.length ? ordered : (catalogMedia || []).slice();
    }
    function newCmdId() {
      try { return crypto.randomUUID(); } catch { return `c-${Date.now()}-${Math.random().toString(16).slice(2)}`; }
    }

    let liveState = catalog.live || {};
    if (opts.source === "live" && dismissedSessionId && dismissedSessionId === liveState.session_id) {
      overlayOpen = false;
      return;
    }
    if (opts.source !== "live") dismissedSessionId = "";
    const joining = !isDom && !!liveState.session_id && !liveState.force_end;
    let session = null;
    let ownsSession = false;
    if (!joining) {
      try {
        session = await api(`/dynamics/${dynamicId}/instructor/sessions`, {
          method: "POST",
          body: JSON.stringify({
            title: "Instructor",
            source: opts.source || "manual",
            task_id: opts.taskId || null,
          }),
        });
        ownsSession = true;
        liveState = await api(`/dynamics/${dynamicId}/instructor/live`);
      } catch { /* still play */ }
    } else {
      session = { id: liveState.session_id };
    }

    let media = orderMedia(liveState, catalog.media || []);
    const audio = createAudio();
    const started = Date.now();
    let playing = false;
    let closed = false;
    let holdSlide = false;
    let mediaIndex = Number(liveState.media_index || 0);
    let lastMediaSeq = Number(liveState.media_seq || 0);
    let advanceSentSeq = -1;
    let lastLiveBeat = null;
    let lastEpoch = Number(liveState.beat_epoch_ms || 0);
    let lastCommandId = "";
    let lastEventAt = 0;
    let commandBusy = false;
    let gen = 0;
    let liveTimer = null;
    let actionTimer = null;
    let clock = null;
    let status = {
      grip: Number(config.initial_grip ?? 3),
      style: config.default_style || "dominant",
      edges: 0,
      ruins: 0,
      orgasms: 0,
      plug: false,
      bands: 0,
      pins: 0,
      bound: false,
    };
    let cooldownUntil = 0;
    let callCtl = null;
    let lastCamId = "";
    let setWantCamera = async () => {};
    let setWantDomCamera = async () => {};
    let localCamOn = true;
    let recorder = null;
    let recChunks = [];
    let beatRaf = 0;
    const endAt = { t: started + durationMin * 60000 };

    const elapsedEl = el("span", { className: "instructor-stat-val" }, "0 min");
    const gripEl = el("span", { className: "instructor-stat-val" }, GRIP_LABELS[status.grip] || "Normal");
    const styleEl = el("span", { className: "instructor-stat-val" }, STYLE_LABELS[status.style] || "Dominant");
    const extraStats = el("div", { className: "instructor-stat-extra" });
    const instructionText = el("div", { className: "instructor-instruction-text" }, "Get ready");
    const progress = el("div", { className: "instructor-progress-bar" });
    const instruction = el("div", { className: "instructor-instruction" }, [instructionText, progress]);
    const stage = el("div", { className: "instructor-stage" });
    const stageWrap = el("div", { className: "instructor-stage-wrap" }, [stage]);
    const triggers = el("div", { className: "instructor-triggers" });
    const beatDots = el("div", { className: "instructor-beat-lane-flow" });
    const beatHit = el("div", { className: "instructor-beat-hit" });
    const beatLane = el("div", { className: "instructor-beat-lane" }, [beatDots, beatHit]);
    beatLane.classList.toggle("hidden", !hud.beatMeter);
    const blocked = el("div", { className: "instructor-blocked hidden" }, `${controllerName} has the controls`);
    const empty = el("p", { className: "muted instructor-empty hidden" }, "No playlists yet.");
    if (!media.length) empty.classList.remove("hidden");
    const camVideo = el("video", { className: "instructor-cam-video", autoplay: "true", playsinline: "true", muted: "true" });
    camVideo.muted = true;
    camVideo.playsInline = true;
    camVideo.autoplay = true;
    const camPane = el("div", { className: "instructor-cam-pane hidden" }, [camVideo]);
    const recBadge = el("div", { className: "instructor-rec-badge hidden" }, "REC");
    camPane.appendChild(recBadge);
    const camSelect = el("select", { className: "instructor-cam-select" });
    camSelect.appendChild(el("option", { value: "" }, "Waiting for cameras…"));
    const camLabel = el("label", { className: "instructor-cam-label hidden" }, ["Sub camera", camSelect]);
    const recSelect = el("select", { className: "instructor-cam-select" });
    [["off", "Recording: off"], ["sub", "Record sub"], ["domme", "Record me"], ["both", "Record both"]].forEach(([value, label]) => {
      recSelect.appendChild(el("option", { value }, label));
    });
    recSelect.value = liveState.recording || "off";
    const recLabel = el("label", { className: "instructor-cam-label" }, ["Recording", recSelect]);
    const subCamFlip = el("button", { type: "button", className: "ghost-btn instructor-dom-btn" }, "Flip camera");
    const subCamToggle = el("button", { type: "button", className: "ghost-btn instructor-dom-btn" }, "Camera off");
    const subCamSelect = el("select", { className: "instructor-cam-select" });
    const subCamBox = el("div", { className: "instructor-sub-cam-ctl" }, [
      el("div", { className: "instructor-dom-row" }, [subCamFlip, subCamToggle]),
      el("label", { className: "instructor-cam-label" }, ["My camera", subCamSelect]),
    ]);
    if (isDom) subCamBox.classList.add("hidden");

    const pauseBtn = el("button", { type: "button", className: "ghost-btn instructor-dom-btn hidden" }, "Pause");
    const redBtn = el("button", { type: "button", className: "ghost-btn instructor-dom-btn hidden" }, "Red light");
    const lockBtn = el("button", { type: "button", className: "ghost-btn instructor-dom-btn hidden" }, "Lock");
    const endBtn = el("button", { type: "button", className: "ghost-btn instructor-dom-btn hidden" }, "End");
    if (isDom) [pauseBtn, redBtn, lockBtn, endBtn].forEach((btn) => btn.classList.remove("hidden"));

    const speedValEl = el("span", { className: "instructor-beat-speed" }, "1.00 /s");
    const nextBeatEl = el("span", { className: "instructor-beat-next" }, "next beat in —");
    const beatSlider = el("input", {
      type: "range",
      className: "instructor-beat-slider",
      min: String(speedMin),
      max: String(Math.max(speedMin, speedMax)),
      step: "0.05",
      value: String(Number(liveState.beat_speed) || (speedMin + speedMax) / 2),
    });
    const beatMinus = el("button", { type: "button", className: "instructor-beat-step" }, "−");
    const beatPlus = el("button", { type: "button", className: "instructor-beat-step" }, "+");
    const beatCtl = el("div", { className: "instructor-beat-ctl" }, [
      beatMinus, beatSlider, beatPlus, speedValEl, nextBeatEl,
    ]);
    if (!isDom) beatCtl.classList.add("hidden");

    const edgeSec = el("input", { type: "number", className: "instructor-cmd-sec", min: "0", step: "1", value: "0", title: "Countdown seconds (0 = none)" });
    const ruinSec = el("input", { type: "number", className: "instructor-cmd-sec", min: "0", step: "1", value: "0", title: "Countdown seconds (0 = none)" });
    const ruinBtn = el("button", { type: "button", className: "instructor-ruin" }, ["Ruin", el("span", { className: "instructor-hotkey" }, "[r]")]);
    const edgeBtn = el("button", { type: "button", className: "instructor-edge" }, ["Edge", el("span", { className: "instructor-hotkey" }, "[e]")]);
    const persistent = el("div", { className: "instructor-persistent" }, isDom ? [
      el("div", { className: "instructor-cmd" }, [
        ruinBtn,
        el("span", { className: "instructor-cmd-in" }, ["in", ruinSec, "sec"]),
      ]),
      el("div", { className: "instructor-cmd" }, [
        edgeBtn,
        el("span", { className: "instructor-cmd-in" }, ["in", edgeSec, "sec"]),
      ]),
    ] : []);

    function paintStats() {
      const mins = Math.max(0, Math.floor((Date.now() - started) / 60000));
      elapsedEl.textContent = `${mins} min`;
      gripEl.textContent = GRIP_LABELS[status.grip] || "Normal";
      styleEl.textContent = STYLE_LABELS[status.style] || "Dominant";
      extraStats.replaceChildren();
      const add = (k, v) => extraStats.appendChild(el("div", { className: "instructor-stat-line" }, [
        el("span", { className: "instructor-stat-key" }, k),
        el("span", { className: "instructor-stat-val" }, v),
      ]));
      if (status.plug) add("Butt Plug:", "Inserted");
      if (status.bands) add("Rubberbands:", String(status.bands));
      if (status.pins) add("Clothespins:", String(status.pins));
      if (status.bound) add("Cock & Balls:", "Bound");
      if (status.edges) add("Edges:", String(status.edges));
      if (status.ruins) add("Ruins:", String(status.ruins));
      if (status.orgasms) add("Orgasms:", String(status.orgasms));
    }

    function syncBeatLane() {
      if (beatLane.classList.contains("hidden")) return;
      const laneW = beatLane.clientWidth || 1;
      const center = laneW / 2;
      const interval = audio.getIntervalMs();
      const next = audio.getNextBeatAt();
      const now = Date.now();
      const spacing = Math.max(22, (interval / 1000) * BEAT_PX_PER_SEC);
      const maxI = Math.ceil((laneW / 2) / spacing) + 3;
      const needed = maxI * 2 + 1;
      while (beatDots.childElementCount < needed) beatDots.appendChild(el("span", { className: "instructor-beat-dot" }));
      while (beatDots.childElementCount > needed) beatDots.lastChild.remove();
      const dots = beatDots.children;
      let n = 0;
      for (let i = -maxI; i <= maxI; i += 1) {
        const t = next + i * interval;
        const x = center + ((t - now) / 1000) * BEAT_PX_PER_SEC;
        const span = dots[n];
        n += 1;
        if (!span) continue;
        if (x < -28 || x > laneW + 28) {
          span.style.opacity = "0";
          continue;
        }
        const past = i < 0;
        const dist = Math.abs(i);
        const fade = past ? clamp(1 - dist / Math.max(2, maxI * 0.7), 0.08, 0.55) : clamp(0.95 - dist * 0.04, 0.45, 0.95);
        const scale = past ? 0.65 + fade * 0.4 : 1;
        span.style.opacity = String(fade);
        span.style.transform = `translate3d(${x}px, -50%, 0) scale(${scale})`;
      }
    }
    function paintBeatHud() {
      const spd = audio.getSpeed();
      speedValEl.textContent = `${spd.toFixed(2)} /s`;
      nextBeatEl.textContent = `next beat in ${audio.nextBeatIn().toFixed(1)}s`;
      if (document.activeElement !== beatSlider) beatSlider.value = String(spd);
      syncBeatLane();
    }
    function paintCameras(list, selected) {
      const cams = list || [];
      camSelect.replaceChildren();
      if (!cams.length) {
        camSelect.appendChild(el("option", { value: "" }, "Waiting for cameras…"));
        camLabel.classList.add("hidden");
        return;
      }
      camLabel.classList.remove("hidden");
      cams.forEach((cam) => {
        const opt = el("option", { value: cam.id }, cam.label || "Camera");
        if (cam.id === selected) opt.selected = true;
        camSelect.appendChild(opt);
      });
    }

    function setHudFlag(key, value) {
      hud[key] = value;
      saveHud(hud);
      audio.setHud(hud);
      beatLane.classList.toggle("hidden", !hud.beatMeter);
      const video = stage.querySelector("video");
      if (video) video.muted = !hud.videoAudio || !!stageWrap.querySelector(".instructor-red-cover");
      root.classList.toggle("is-zoom", !!hud.zoom);
    }

    const statusBody = el("div", { className: "instructor-status-body" }, [
      el("div", { className: "instructor-stat-grid" }, [
        el("div", {}, [
          el("div", { className: "instructor-stat-line" }, [el("span", { className: "instructor-stat-key" }, "Elapsed Time:"), elapsedEl]),
          el("div", { className: "instructor-stat-line" }, [el("span", { className: "instructor-stat-key" }, "Stroke Grip:"), gripEl]),
          el("div", { className: "instructor-stat-line" }, [el("span", { className: "instructor-stat-key" }, "Stroke Style:"), styleEl]),
          extraStats,
        ]),
      ]),
      el("div", { className: "instructor-toggles" }, [
        switchRow("enableVideoAudio", "Mute Videos", !hud.videoAudio, (v) => setHudFlag("videoAudio", !v)),
      ]),
      el("div", { className: "instructor-toggles" }, [
        switchRow("enableTicks", "Metronome", hud.ticks, (v) => {
          setHudFlag("ticks", v);
          if (v) {
            unlockInstructorAudio();
            audio.resume();
          }
        }),
        switchRow("enableBeatMeter", "Beat Meter", hud.beatMeter, (v) => setHudFlag("beatMeter", v)),
      ]),
      ...(isDom ? [
        el("div", { className: "instructor-toggles" }, [
          switchRow("enableSubCam", "Sub camera", false, (v) => { setWantCamera(v); }),
        ]),
        el("div", { className: "instructor-toggles" }, [
          switchRow("enableDomCam", "My camera", false, (v) => { setWantDomCamera(v); }),
        ]),
        camLabel,
        recLabel,
      ] : []),
      el("div", { className: "instructor-dom-row" }, [pauseBtn, redBtn, lockBtn, endBtn]),
    ]);
    if (!hud.statusOpen) statusBody.classList.add("hidden");
    const statusToggle = el("button", { type: "button", className: "instructor-brand" }, [
      el("span", { className: "instructor-brand-mark" }, "▲"),
      controllerName,
      el("span", { className: "instructor-caret" }, hud.statusOpen ? "▾" : "▴"),
    ]);
    statusToggle.addEventListener("click", () => {
      hud.statusOpen = !hud.statusOpen;
      saveHud(hud);
      statusBody.classList.toggle("hidden", !hud.statusOpen);
      statusToggle.querySelector(".instructor-caret").textContent = hud.statusOpen ? "▾" : "▴";
      root.classList.toggle("is-sidebar-collapsed", isDom && !hud.statusOpen);
    });
    const statusPanel = el("div", { className: "instructor-status" }, [statusToggle, statusBody]);

    function currentMedia() {
      if (!media.length) return null;
      return media[((mediaIndex % media.length) + media.length) % media.length];
    }
    function isVideoItem(item) {
      return item?.kind === "video" || item?.media_type === "video";
    }
    function mediaUnlocked() {
      return !!(liveState.playing || liveState.sub_ready);
    }
    function showMedia() {
      if (!mediaUnlocked()) {
        stage.replaceChildren();
        return;
      }
      stage.replaceChildren();
      const item = currentMedia();
      if (!item) return;
      const attachVideo = (video) => {
        video.muted = !hud.videoAudio || !!stageWrap.querySelector(".instructor-red-cover");
        video.loop = false;
        video.removeAttribute("loop");
        video.addEventListener("ended", () => requestAdvance("ended"));
        stage.appendChild(video);
        if (!root.classList.contains("instructor-paused")) video.play?.().catch(() => {});
      };
      if (item.url && item.url.startsWith("vault:")) {
        const src = vaultBlob(item);
        if (isVideoItem(item) && src.startsWith("data:video")) {
          const video = el("video", { className: "instructor-media", autoplay: "true", playsinline: "true" });
          video.src = src;
          video.setAttribute("playsinline", "");
          video.playsInline = true;
          attachVideo(video);
        } else {
          stage.appendChild(el("img", { className: "instructor-media", alt: item.name || "media", src }));
        }
        return;
      }
      const href = mediaSrc(item);
      if (!href) return;
      if (isVideoItem(item)) {
        const video = el("video", { className: "instructor-media", autoplay: "true", playsinline: "true" });
        video.src = href;
        video.setAttribute("playsinline", "");
        video.playsInline = true;
        attachVideo(video);
      } else {
        stage.appendChild(el("img", { className: "instructor-media", alt: item.name || "media", src: href }));
      }
    }
    async function requestAdvance(reason) {
      if (closed || !mediaUnlocked()) return;
      if (reason !== "nav" && (holdSlide || root.classList.contains("instructor-paused"))) return;
      if (advanceSentSeq === lastMediaSeq) return;
      advanceSentSeq = lastMediaSeq;
      const live = await patchLive({ advance_media: true });
      if (!live) advanceSentSeq = -1;
    }
    async function requestPrev() {
      if (closed || !media.length || !mediaUnlocked()) return;
      const idx = (mediaIndex - 1 + media.length) % media.length;
      await patchLive({ media_index: idx });
    }
    function maybeAdvanceImage(live) {
      if (!mediaUnlocked()) return;
      const item = currentMedia();
      if (!item || isVideoItem(item)) return;
      const until = Number(live?.media_until || liveState.media_until || 0);
      if (!until || Date.now() <= until) return;
      requestAdvance("until");
    }

    const bookmarkBtn = el("button", { type: "button", className: "instructor-icon-btn", title: "Hold this slide" }, "🔖");
    bookmarkBtn.addEventListener("click", () => {
      holdSlide = !holdSlide;
      bookmarkBtn.classList.toggle("on", holdSlide);
    });
    const prevBtn = el("button", { type: "button", className: "instructor-nav-btn", title: "Previous" }, "⏮");
    const nextBtn = el("button", { type: "button", className: "instructor-nav-btn", title: "Next" }, "⏭");
    prevBtn.addEventListener("click", () => requestPrev());
    nextBtn.addEventListener("click", () => requestAdvance("nav"));
    const zoomBtn = el("button", { type: "button", className: "instructor-icon-btn instructor-zoom-btn hidden", title: "Zoom stage" }, "Zoom");
    if (isDom) zoomBtn.classList.remove("hidden");
    zoomBtn.addEventListener("click", () => setHudFlag("zoom", !hud.zoom));
    const exitBtn = el("button", { type: "button", className: "instructor-exit-btn", title: "Exit" }, "Exit");
    const fullBtn = el("button", { type: "button", className: "instructor-icon-btn", title: "Fullscreen" }, "⛶");
    fullBtn.addEventListener("click", () => {
      if (document.fullscreenElement) document.exitFullscreen?.();
      else root.requestFullscreen?.().catch(() => {});
    });
    const nav = el("div", { className: "instructor-nav" }, [bookmarkBtn, prevBtn, nextBtn, zoomBtn, exitBtn, fullBtn]);
    if (isDom) {
      statusBody.appendChild(persistent);
      statusBody.appendChild(beatCtl);
      statusBody.appendChild(nav);
    }

    const split = el("div", { className: "instructor-split" }, [camPane, stageWrap]);
    const sidebar = isDom
      ? el("aside", { className: "instructor-sidebar" }, [statusPanel])
      : el("div", { className: "instructor-hud-top" }, [
        el("div", { className: "instructor-hud-left" }, [statusPanel, persistent]),
        nav,
      ]);

    const root = el("div", {
      className: `instructor-overlay${isDom ? " is-dom" : ""}${hud.zoom ? " is-zoom" : ""}${isDom && !hud.statusOpen ? " is-sidebar-collapsed" : ""}`,
      role: "dialog",
      "aria-label": controllerName,
    }, [
      sidebar,
      split,
      instruction,
      triggers,
      beatLane,
      ...(isDom ? [] : [beatCtl]),
      empty,
      blocked,
    ]);
    document.body.appendChild(root);
    root.addEventListener("pointerdown", () => unlockInstructorAudio(), { passive: true });

    audio.setPulse(() => {
      beatLane.classList.remove("tick");
      void beatLane.offsetWidth;
      beatLane.classList.add("tick");
    });
    audio.setHud(hud);
    const startSpeed = Number(liveState.beat_speed) || (speedMin + speedMax) / 2;
    lastLiveBeat = startSpeed;
    audio.setSpeed(startSpeed, liveState.beat_epoch_ms);
    audio.resume();
    paintBeatHud();
    function beatLoop() {
      if (closed) return;
      syncBeatLane();
      beatRaf = requestAnimationFrame(beatLoop);
    }
    beatRaf = requestAnimationFrame(beatLoop);

    function setSpeed(next) {
      const value = audio.setSpeed(clamp(next, 0.1, 8));
      paintBeatHud();
      return value;
    }
    function setStyle(id) {
      status.style = id;
      paintStats();
    }
    function setGrip(next) {
      status.grip = clamp(next, 0, 6);
      paintStats();
    }
    function mediaEl() {
      return stage.querySelector("video, img");
    }
    function setTriggers(items) {
      triggers.replaceChildren();
      (items || []).forEach((item) => {
        const btn = el("button", { type: "button", className: item.primary ? "instructor-go" : "instructor-go instructor-go-alt" }, item.label);
        btn.addEventListener("click", () => item.onClick());
        triggers.appendChild(btn);
      });
    }
    function notice(text, durationMs) {
      instructionText.textContent = text;
      progress.style.transition = "none";
      progress.style.width = durationMs > 0 ? "100%" : "0";
      void progress.offsetWidth;
      if (durationMs > 0) {
        progress.style.transition = `width ${durationMs}ms linear`;
        progress.style.width = "0";
      }
    }
    function cancelled(my) {
      return closed || my !== gen;
    }
    function sleep(ms, my) {
      return new Promise((resolve) => {
        const t = setTimeout(() => resolve(!cancelled(my)), ms);
        if (cancelled(my)) {
          clearTimeout(t);
          resolve(false);
        }
      });
    }
    async function runFor(text, ms, my, extras = {}) {
      notice(text, ms);
      if (extras.speed != null) setSpeed(extras.speed);
      if (extras.style) setStyle(extras.style);
      if (extras.grip != null) setGrip(extras.grip);
      if (extras.silence) audio.mute(true);
      const ok = await sleep(ms, my);
      if (extras.silence && hud.ticks) audio.mute(false);
      return ok;
    }
    function waitFor(text, label) {
      return new Promise((resolve) => {
        notice(text, 0);
        setTriggers([{
          label: label || "Done",
          primary: true,
          onClick: () => {
            setTriggers([]);
            resolve(true);
          },
        }]);
      });
    }

    async function doTask(id, my) {
      const dur = () => randInt(5, 30) * 1000;
      const base = audio.getSpeed();
      if (id === "doubleStrokes") {
        await runFor("Double your stroke speed!", dur(), my, { speed: base * 2 });
        if (!cancelled(my)) setSpeed(base);
        return;
      }
      if (id === "halvedStrokes") {
        await runFor("Half speed.", dur(), my, { speed: base / 2 });
        if (!cancelled(my)) setSpeed(base);
        return;
      }
      if (id === "teasingStrokes") {
        await runFor("Teasing strokes. Barely there.", dur(), my, { speed: speedMin });
        if (!cancelled(my)) setSpeed(base);
        return;
      }
      if (id === "randomStrokeSpeed" || id === "randomBeat") {
        await runFor("Random stroke speed.", dur(), my, { speed: speedMin + Math.random() * (speedMax - speedMin) });
        return;
      }
      if (id === "accelerationCycles") {
        const steps = 6;
        const step = ((speedMax - speedMin) / steps);
        notice("Acceleration cycle. Faster.", steps * 2500);
        for (let i = 0; i <= steps && !cancelled(my); i += 1) {
          setSpeed(speedMin + step * i);
          await sleep(2500, my);
        }
        if (!cancelled(my)) setSpeed(base);
        return;
      }
      if (id === "redLightGreenLight") {
        await runFor("Red light. Hands off.", randInt(4, 10) * 1000, my, { silence: true, style: "handsOff" });
        if (cancelled(my)) return;
        await runFor("Green light. Stroke.", randInt(6, 14) * 1000, my, { style: config.default_style || "dominant" });
        return;
      }
      if (id === "clusterStrokes") {
        await runFor("Cluster strokes. Fast bursts.", 8000, my, { speed: speedMax });
        if (!cancelled(my)) setSpeed(base);
        return;
      }
      if (id === "gripChallenge") {
        await runFor("Grip challenge. Squeeze tighter.", dur(), my, { grip: 6 });
        if (!cancelled(my) && config.grip_adjustments) setGrip(config.initial_grip ?? 3);
        return;
      }
      if (id === "handsOff") {
        await runFor(pick(HANDS_OFF_LINES), randInt(8, 18) * 1000, my, { silence: true, style: "handsOff" });
        if (!cancelled(my)) setStyle(config.default_style || "dominant");
        return;
      }
      if (STYLE_LABELS[id]) {
        await runFor(`Stroke style: ${STYLE_LABELS[id]}`, dur(), my, { style: id });
        return;
      }
      const waits = {
        bindCockBalls: ["Bind cock and balls.", "Bound"],
        rubberBands: ["Add a rubber band.", "On"],
        clothespins: ["Add a clothespin.", "Clipped"],
        headPalming: ["Palm the head. Hold pressure.", "Done"],
        icyHot: ["Apply icy hot where it stings.", "Applied"],
        toothpaste: ["Toothpaste. You know where.", "Applied"],
        ballSlaps: ["Slap your balls to the beat.", "Done"],
        squeezeBalls: ["Squeeze your balls.", "Done"],
        breathPlay: ["Hold your breath.", "Breathe"],
        scratching: ["Scratch chest, shoulders, or thighs.", "Done"],
        flicking: ["Flick the head.", "Done"],
        cbtIce: ["Ice cubes. Hold them against your balls.", "Done"],
        precum: ["Taste precum. Stay ready.", "Ready"],
        buttplug: [status.plug ? "Remove the plug." : "Insert the butt plug.", "In"],
        rubNipples: ["Rub your nipples.", "Done"],
        nipplesAndStroke: ["Nipples and stroking together.", "Done"],
      };
      const spec = waits[id];
      if (spec) {
        await waitFor(spec[0], spec[1]);
        if (id === "buttplug") status.plug = !status.plug;
        if (id === "rubberBands") status.bands += 1;
        if (id === "clothespins") status.pins += 1;
        if (id === "bindCockBalls") status.bound = true;
        paintStats();
        setTriggers(playing ? [] : startTriggers());
      }
    }

    function pickTaskId() {
      const pool = tasks.filter((id) => TASK_WEIGHT[id] || STYLE_LABELS[id] || true);
      if (!pool.length) return "randomStrokeSpeed";
      const weighted = [];
      pool.forEach((id) => {
        const w = TASK_WEIGHT[id] || 2;
        for (let i = 0; i < w; i += 1) weighted.push(id);
      });
      return pick(weighted);
    }

    async function fireTask() {
      if (isDom || !playing || closed || commandBusy) return;
      if (Date.now() < cooldownUntil) return;
      if (Math.random() * 100 < Number(config.edge_frequency || 0)) {
        beginEdge();
        return;
      }
      const my = ++gen;
      setTriggers([]);
      await doTask(pickTaskId(), my);
      if (!cancelled(my) && playing) scheduleAction();
    }

    function scheduleAction() {
      if (actionTimer) clearTimeout(actionTimer);
      if (isDom || !actionSec) return;
      actionTimer = setTimeout(fireTask, actionSec * 1000);
    }

    function inCooldown() {
      return Date.now() < cooldownUntil;
    }

    async function beginEdge() {
      if (isDom || inCooldown() || closed) return;
      const my = ++gen;
      setSpeed(speedMax);
      notice(pick(EDGE_LINES), 0);
      setTriggers([
        {
          label: "I'm there",
          primary: true,
          onClick: async () => {
            if (cancelled(my)) return;
            status.edges += 1;
            paintStats();
            cooldownUntil = Date.now() + Number(config.edge_cooldown || 10) * 1000;
            setTriggers([]);
            await runFor(pick(HANDS_OFF_LINES), Number(config.edge_cooldown || 10) * 1000, my, { silence: true, style: "handsOff" });
            if (!cancelled(my)) {
              setStyle(config.default_style || "dominant");
              setSpeed((speedMin + speedMax) / 2);
              scheduleAction();
            }
          },
        },
        {
          label: "I can't",
          onClick: () => {
            setSpeed((speedMin + speedMax) / 2);
            scheduleAction();
          },
        },
      ]);
    }

    async function beginRuin(accidental) {
      if (isDom || inCooldown() || closed) return;
      const my = ++gen;
      notice(pick(RUIN_LINES), 0);
      setTriggers([{
        label: "Ruined",
        primary: true,
        onClick: async () => {
          if (cancelled(my)) return;
          status.ruins += 1;
          paintStats();
          cooldownUntil = Date.now() + Number(config.ruin_cooldown || 20) * 1000;
          await runFor(pick(HANDS_OFF_LINES), Number(config.ruin_cooldown || 20) * 1000, my, { silence: true, style: "handsOff" });
          if (!cancelled(my) && playing && accidental) {
            setStyle(config.default_style || "dominant");
            scheduleAction();
          }
        },
      }]);
    }

    async function handleDomCommand(cmd) {
      if (isDom || !cmd || commandBusy) return;
      if (cmd.id && cmd.id === lastCommandId) return;
      lastCommandId = cmd.id || "";
      commandBusy = true;
      const my = ++gen;
      const isEdge = cmd.type === "edge";
      const line = pick(isEdge ? EDGE_LINES : RUIN_LINES);
      if (isEdge) setSpeed(speedMax);
      let settled = false;
      const finishAck = async () => {
        if (settled || cancelled(my)) return;
        settled = true;
        if (isEdge) status.edges += 1;
        else status.ruins += 1;
        paintStats();
        setTriggers([]);
        await patchLive({ command_ack: true, at_ms: Date.now() });
        const cd = Number(isEdge ? config.edge_cooldown || 10 : config.ruin_cooldown || 20) * 1000;
        cooldownUntil = Date.now() + cd;
        await runFor(pick(HANDS_OFF_LINES), cd, my, { silence: true, style: "handsOff" });
        commandBusy = false;
        if (!cancelled(my)) {
          setStyle(config.default_style || "dominant");
          if (playing) scheduleAction();
        }
      };
      const failTimeout = async () => {
        if (settled || cancelled(my)) return;
        settled = true;
        setTriggers([]);
        await patchLive({
          command_failed: true,
          reason: "timeout",
          at_ms: Date.now(),
          message: isEdge ? "Edge timed out." : "Ruin timed out.",
        });
        const cd = Number(isEdge ? config.edge_cooldown || 10 : config.ruin_cooldown || 20) * 1000;
        cooldownUntil = Date.now() + cd;
        await runFor("Too late. Hands off.", cd, my, { silence: true, style: "handsOff" });
        commandBusy = false;
        if (!cancelled(my) && playing) {
          setStyle(config.default_style || "dominant");
          scheduleAction();
        }
      };
      setTriggers([{
        label: isEdge ? "I'm there" : "Ruined",
        primary: true,
        onClick: finishAck,
      }]);
      const deadline = Number(cmd.deadline_ms || 0);
      if (deadline > Date.now()) {
        while (!settled && !cancelled(my) && Date.now() < deadline) {
          const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
          notice(`${line} (${left}s)`, 0);
          await sleep(200, my);
        }
        if (!settled && !cancelled(my)) await failTimeout();
      } else {
        notice(line, 0);
      }
    }

    async function sendCommand(type, secInput) {
      const sec = Math.max(0, Number(secInput.value) || 0);
      const now = Date.now();
      await patchLive({
        command: {
          type,
          id: newCmdId(),
          issued_ms: now,
          deadline_ms: sec > 0 ? now + sec * 1000 : 0,
        },
      });
    }

    async function finale() {
      if (isDom) return;
      playing = false;
      if (actionTimer) clearTimeout(actionTimer);
      const my = ++gen;
      const needEdges = Number(config.minimum_edges || 0);
      if (status.edges < needEdges) {
        notice(`Minimum edges: ${needEdges}. Edge again.`, 0);
        playing = true;
        beginEdge();
        endAt.t = Date.now() + 20000;
        return;
      }
      const o = Number(config.finale_orgasm || 0);
      const d = Number(config.finale_denied || 0);
      const r = Number(config.finale_ruined || 0);
      const roll = Math.random() * Math.max(1, o + d + r);
      let mode = "denied";
      if (roll < o) mode = "orgasm";
      else if (roll < o + r) mode = "ruined";
      if (mode === "orgasm") {
        status.orgasms += 1;
        paintStats();
        await waitFor("Cum. Now.", "Finished");
        if (config.post_orgasm_torture) {
          const pot = randInt(Number(config.pot_min || 10), Number(config.pot_max || 90)) * 1000;
          await runFor("Keep going. Post-orgasm torture.", pot, my, { speed: speedMax });
        }
      } else if (mode === "ruined") {
        await waitFor(pick(RUIN_LINES), "Ruined");
        status.ruins += 1;
        paintStats();
      } else {
        await waitFor(pick(DENY_LINES), "Stopped");
      }
      await patchLive({ force_end: true });
      shutdown({ endSession: false });
    }

    function startPlay() {
      if (isDom) return;
      gen += 1;
      playing = true;
      const mins = durationMin;
      endAt.t = Date.now() + mins * 60000;
      setSpeed(Number(liveState.beat_speed) || (speedMin + speedMax) / 2);
      setStyle(config.default_style || "dominant");
      setTriggers([]);
      notice("Stroke to the beat.", 4000);
      scheduleAction();
    }

    async function warmup() {
      await patchLive({ playing: true });
      const my = ++gen;
      setSpeed(0.5);
      if (!(await runFor("Warming up", 30000, my, { speed: 0.5 }))) return;
      if (!(await runFor("Warming up", 60000, my, { speed: 1 }))) return;
      setSpeed(0.75);
      notice("When you're ready…", 0);
      setTriggers(startTriggers());
    }

    function startTriggers() {
      return [
        { label: "WARM UP", onClick: warmup },
        {
          label: "I'M READY!",
          primary: true,
          onClick: async () => {
            await patchLive({ sub_ready: true, playing: true });
            startPlay();
          },
        },
      ];
    }

    if (isDom) {
      ruinBtn.addEventListener("click", () => sendCommand("ruin", ruinSec));
      edgeBtn.addEventListener("click", () => sendCommand("edge", edgeSec));
    }

    async function patchLive(body) {
      try {
        const live = await api(`/dynamics/${dynamicId}/instructor/live`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        applyIncomingLive(live);
        return live;
      } catch (err) {
        showToast(err.message || "Could not update controls");
        return null;
      }
    }

    function applyIncomingLive(live) {
      if (!live || closed) return;
      liveState = live;
      blocked.classList.toggle("hidden", isDom || !live.lock_input);
      if (live.media_keys?.length) {
        const nextMedia = orderMedia(live, catalog.media || []);
        if (nextMedia.length) media = nextMedia;
        empty.classList.toggle("hidden", !!media.length);
      }
      const seq = Number(live.media_seq || 0);
      if (seq !== lastMediaSeq) {
        lastMediaSeq = seq;
        advanceSentSeq = -1;
        mediaIndex = Number(live.media_index || 0);
        showMedia();
      } else {
        mediaIndex = Number(live.media_index || 0);
      }
      applyLive(root, live, audio, mediaEl(), hud, stageWrap);
      if (mediaUnlocked() !== !!stage.querySelector(".instructor-media, img.instructor-media")) {
        showMedia();
      }
      const beat = Number(live.beat_speed);
      const epoch = Number(live.beat_epoch_ms || 0);
      if (Number.isFinite(beat) && (beat !== lastLiveBeat || epoch !== lastEpoch)) {
        lastLiveBeat = beat;
        lastEpoch = epoch;
        audio.setSpeed(beat, epoch);
        paintBeatHud();
      }
      if (isDom && live.command_event && Number(live.command_event.at_ms || 0) !== lastEventAt) {
        lastEventAt = Number(live.command_event.at_ms || 0);
        const evt = live.command_event;
        const fallback = evt.type === "completed" ? "Sub acknowledged." : "Sub missed the command.";
        showToast(evt.message || fallback);
        patchLive({ clear_command_event: true });
      }
      if (!isDom && live.command?.id && live.command.id !== lastCommandId) {
        handleDomCommand(live.command);
      }
      if (isDom) {
        paintCameras(live.cameras || [], live.camera_device_id || lastCamId);
        if (document.activeElement !== recSelect) recSelect.value = live.recording || "off";
      } else if (live.camera_device_id && live.camera_device_id !== lastCamId && callCtl && typeof switchCallCamera === "function") {
        lastCamId = live.camera_device_id;
        switchCallCamera(callCtl, lastCamId).catch(() => {});
      }
      if (!isDom && callCtl) {
        if (typeof setCallVideoEnabled === "function") setCallVideoEnabled(callCtl, !!live.want_camera);
      }
      if (isDom) {
        camPane.classList.toggle("hidden", !live.want_camera);
        root.classList.toggle("has-cam", !!live.want_camera && !camPane.classList.contains("hidden"));
      } else {
        camPane.classList.toggle("hidden", !live.want_dom_camera);
        root.classList.toggle("has-cam", !!live.want_dom_camera);
      }
      syncRecording(live.recording || "off");
      if (live.force_end) shutdown({ endSession: isDom });
    }

    pauseBtn.addEventListener("click", () => patchLive({ paused: !root.classList.contains("instructor-paused") }));
    redBtn.addEventListener("click", () => patchLive({ red_light: !root.querySelector(".instructor-red-cover") }));
    lockBtn.addEventListener("click", () => patchLive({ lock_input: !root.classList.contains("instructor-locked") }));
    endBtn.addEventListener("click", () => requestExit());
    function nudgeBeat(delta) {
      const next = clamp(audio.getSpeed() + delta, speedMin, Math.max(speedMin, speedMax));
      audio.setSpeed(next, Date.now());
      paintBeatHud();
      patchLive({ beat_speed: next });
    }
    beatMinus.addEventListener("click", () => nudgeBeat(-0.1));
    beatPlus.addEventListener("click", () => nudgeBeat(0.1));
    beatSlider.addEventListener("change", () => {
      const next = clamp(Number(beatSlider.value) || 1, 0.1, 8);
      audio.setSpeed(next, Date.now());
      paintBeatHud();
      patchLive({ beat_speed: next });
    });
    camSelect.addEventListener("change", () => {
      const id = camSelect.value;
      lastCamId = id;
      patchLive({ camera_device_id: id });
      if (callCtl && typeof patchVideoControls === "function") {
        patchVideoControls(callCtl, { camera_facing: id || "user" }).catch(() => {});
      }
    });

    function camEmbed() {
      return {
        remoteEl: camVideo,
        onLive() {
          const show = isDom ? !!liveState.want_camera : !!liveState.want_dom_camera;
          camPane.classList.toggle("hidden", !show);
          root.classList.toggle("has-cam", show);
        },
      };
    }
    async function fillLocalCameras() {
      if (typeof listVideoInputs !== "function") return [];
      const devices = await listVideoInputs().catch(() => []);
      const target = isDom ? null : subCamSelect;
      if (target) {
        target.replaceChildren();
        devices.forEach((d, i) => {
          target.appendChild(el("option", { value: d.deviceId }, d.label || `Camera ${i + 1}`));
        });
        if (!devices.length) {
          target.appendChild(el("option", { value: "user" }, "Front"));
          target.appendChild(el("option", { value: "environment" }, "Rear"));
        }
      }
      return devices;
    }
    async function publishSubCameras() {
      if (isDom) return;
      try {
        const devices = await fillLocalCameras();
        await patchLive({
          cameras: devices.map((d, i) => ({
            id: d.deviceId || (i === 0 ? "user" : "environment"),
            label: d.label || `Camera ${i + 1}`,
          })),
        });
      } catch { /* ignore */ }
    }
    async function joinEmbedCall(call) {
      if (closed || callCtl || !call || call.status === "ended") return;
      if (typeof joinVideoCall !== "function") return;
      try {
        if (call.status === "ringing" && !call.you_are_caller) {
          await api(`/dynamics/${dynamicId}/video/calls/${call.id}/accept`, { method: "POST", body: "{}" });
        }
        const next = await joinVideoCall(dynamicId, call, {
          isCaller: !!call.you_are_caller,
          alreadyAccepted: true,
          embed: camEmbed(),
        });
        if (next && !next.embedded) return;
        callCtl = next || callCtl;
        await publishSubCameras();
        if (isDom && liveState.want_dom_camera) await setWantDomCamera(true);
      } catch (err) {
        showToast(err.message || "Could not open camera");
      }
    }
    overlayIncoming = (dynId, call) => {
      if (dynId !== dynamicId) return;
      joinEmbedCall(call);
    };
    async function ensureCam({ demandSub = false } = {}) {
      if (closed || callCtl) return;
      if (typeof startVideoCall !== "function" && typeof joinVideoCall !== "function") return;
      try {
        const data = await api(`/dynamics/${dynamicId}/video/call`).catch(() => null);
        const existing = data?.call;
        if (existing && existing.status !== "ended") {
          await joinEmbedCall(existing);
          return;
        }
        if (!isDom) return;
        const next = await startVideoCall(dynamicId, {
          demandCamera: !!demandSub,
          embed: camEmbed(),
        });
        if (next && !next.embedded) return;
        callCtl = next || callCtl;
      } catch (err) {
        showToast(err.message || "Could not open camera");
      }
    }
    setWantCamera = async (on) => {
      await patchLive({ want_camera: !!on });
      if (on) {
        await ensureCam({ demandSub: true });
        camPane.classList.remove("hidden");
        root.classList.add("has-cam");
        if (callCtl && typeof setCallVideoEnabled === "function") setCallVideoEnabled(callCtl, true);
        return;
      }
      camPane.classList.add("hidden");
      root.classList.remove("has-cam");
      if (!liveState.want_dom_camera && callCtl?.embedded && typeof leaveVideoCall === "function") {
        await leaveVideoCall().catch(() => {});
        callCtl = null;
      }
    };
    setWantDomCamera = async (on) => {
      await patchLive({ want_dom_camera: !!on });
      if (!on) return;
      await ensureCam({ demandSub: false });
      if (callCtl && typeof enableEmbeddedCamera === "function") {
        try {
          await enableEmbeddedCamera(callCtl);
        } catch (err) {
          showToast(err.message || "Could not open your camera");
        }
      }
    };
    if (pendingIncoming?.dynamicId === dynamicId) {
      const queued = pendingIncoming;
      pendingIncoming = null;
      joinEmbedCall(queued.call);
    }

    recSelect.addEventListener("change", () => patchLive({ recording: recSelect.value || "off" }));
    subCamFlip.addEventListener("click", async () => {
      if (!callCtl || typeof switchCallCamera !== "function") return;
      const next = callCtl.cameraFacing === "environment" ? "user" : "environment";
      try {
        await switchCallCamera(callCtl, next);
        lastCamId = next;
        await patchLive({ camera_device_id: next });
        await publishSubCameras();
      } catch (err) {
        showToast(err.message || "Could not flip camera");
      }
    });
    subCamToggle.addEventListener("click", () => {
      localCamOn = !localCamOn;
      if (liveState.want_camera && !localCamOn) {
        localCamOn = true;
        showToast(`${controllerName} has your camera on`);
      }
      if (callCtl && typeof setCallVideoEnabled === "function") setCallVideoEnabled(callCtl, localCamOn);
      subCamToggle.textContent = localCamOn ? "Camera off" : "Camera on";
    });
    subCamSelect.addEventListener("change", async () => {
      const id = subCamSelect.value;
      lastCamId = id;
      await patchLive({ camera_device_id: id });
      if (callCtl && typeof switchCallCamera === "function") {
        switchCallCamera(callCtl, id).catch((err) => showToast(err.message || "Could not switch camera"));
      }
    });

    function shouldRecordHere(mode) {
      if (mode === "both") return true;
      if (mode === "sub") return !isDom;
      if (mode === "domme") return isDom;
      return false;
    }
    function stopRecorder() {
      try { recorder?.stop(); } catch { /* ignore */ }
      recorder = null;
      recBadge.classList.add("hidden");
    }
    async function uploadClip(file) {
      try {
        const data = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
        await api(`/dynamics/${dynamicId}/chat/messages`, {
          method: "POST",
          body: JSON.stringify({
            message_type: "image",
            image_data: data,
            save_to_vault: true,
            media_kind: "video",
          }),
        });
        showToast("Recording saved to vault");
      } catch (err) {
        showToast(err.message || "Could not save recording");
      }
    }
    function syncRecording(mode) {
      const want = shouldRecordHere(mode);
      recBadge.classList.toggle("hidden", !want);
      if (!want) {
        stopRecorder();
        return;
      }
      if (recorder) return;
      const stream = callCtl?.rawStream || camVideo.srcObject;
      if (!stream || typeof MediaRecorder === "undefined") return;
      recChunks = [];
      const mime = typeof pickRecorderMime === "function" ? pickRecorderMime() : "";
      try {
        recorder = mime ? new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 400000 }) : new MediaRecorder(stream);
      } catch {
        recBadge.classList.add("hidden");
        return;
      }
      recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) recChunks.push(ev.data); };
      recorder.onstop = () => {
        const type = recorder?.mimeType || mime || "video/webm";
        const blob = new Blob(recChunks, { type });
        if (blob.size) {
          const ext = type.includes("mp4") ? "mp4" : "webm";
          uploadClip(new File([blob], `instructor-${Date.now()}.${ext}`, { type }));
        }
        recorder = null;
      };
      try { recorder.start(400); } catch { recorder = null; recBadge.classList.add("hidden"); }
    }

    async function pollLive() {
      try {
        const live = await api(`/dynamics/${dynamicId}/instructor/live`);
        applyIncomingLive(live);
        maybeAdvanceImage(live);
        if (callCtl?.leaving) {
          callCtl = null;
          camPane.classList.add("hidden");
          root.classList.remove("has-cam");
        }
        if (!callCtl) {
          const data = await api(`/dynamics/${dynamicId}/video/call`).catch(() => null);
          if (data?.call && data.call.status !== "ended") joinEmbedCall(data.call);
        }
      } catch { /* ignore */ }
    }

    function onKey(event) {
      if (closed || event.repeat || event.target?.closest?.("input,textarea,select")) return;
      if (event.key === "e") {
        if (isDom) sendCommand("edge", edgeSec);
        else beginEdge();
      }
      if (event.key === "r") {
        if (isDom) sendCommand("ruin", ruinSec);
        else beginRuin(true);
      }
      if (event.key === "ArrowRight") requestAdvance("nav");
      if (event.key === "ArrowLeft") requestPrev();
    }
    document.addEventListener("keydown", onKey);

    async function shutdown({ endSession = false } = {}) {
      if (closed) return;
      closed = true;
      playing = false;
      gen += 1;
      if (beatRaf) cancelAnimationFrame(beatRaf);
      stopRecorder();
      clearInterval(clock);
      if (liveTimer) clearInterval(liveTimer);
      if (actionTimer) clearTimeout(actionTimer);
      document.removeEventListener("keydown", onKey);
      audio.stop();
      overlayOpen = false;
      overlayIncoming = null;
      pendingIncoming = null;
      if (callCtl?.embedded && typeof leaveVideoCall === "function") {
        leaveVideoCall().catch(() => {});
        callCtl = null;
      }
      try { if (document.fullscreenElement) document.exitFullscreen?.(); } catch { /* ignore */ }
      const elapsed = Math.max(0, Math.round((Date.now() - started) / 1000));
      if (endSession && ownsSession && session?.id) {
        api(`/dynamics/${dynamicId}/instructor/sessions/${session.id}`, {
          method: "PATCH",
          body: JSON.stringify({ duration_sec: elapsed, title: "Instructor" }),
        }).catch(() => {});
      }
      root.remove();
      opts.onClose?.();
    }

    async function requestExit() {
      if (isDom) {
        const choice = await showOverlaySheet(root, {
          title: "Leave Instructor?",
          buttons: [
            { id: "continue", label: "Allow sub to continue till game ends", primary: true },
            { id: "end", label: "End sub's game now", danger: true },
            { id: "cancel", label: "Cancel" },
          ],
        });
        if (!choice || choice === "cancel") return;
        if (choice === "end") {
          await patchLive({ force_end: true });
          await shutdown({ endSession: true });
          return;
        }
        await shutdown({ endSession: false });
        return;
      }
      const choice = await showOverlaySheet(root, {
        title: "Leave Instructor?",
        buttons: [
          { id: "leave", label: "Leave", danger: true },
          { id: "cancel", label: "Cancel" },
        ],
      });
      if (choice !== "leave") return;
      dismissedSessionId = liveState.session_id || session?.id || "";
      shutdown({ endSession: false });
    }
    exitBtn.addEventListener("click", () => requestExit());

    clock = setInterval(() => {
      paintStats();
      paintBeatHud();
      maybeAdvanceImage(liveState);
      if (!isDom && playing && Date.now() >= endAt.t) finale();
    }, 200);
    liveTimer = setInterval(pollLive, 800);
    showMedia();
    paintStats();
    if (!isDom && !liveState.sub_ready) {
      setTriggers(startTriggers());
      notice("Warm up, or start when you're ready.", 0);
    } else if (!isDom && liveState.sub_ready) {
      startPlay();
    } else {
      notice(liveState.sub_ready ? "Session live." : "Waiting for your sub to start.", 0);
    }
    applyIncomingLive(liveState);
    global.__ubetraInstructorClose = shutdown;
  }

  function playlistChecks(allPlaylists, selected) {
    const chosen = new Set(selected || []);
    const box = el("div", { className: "stack instructor-playlists" });
    if (!allPlaylists.length) {
      box.appendChild(el("p", { className: "muted" }, "No playlists yet. Media lands in subfolders of the shared redgifs directory."));
      return { box, values: () => [] };
    }
    const inputs = [];
    allPlaylists.forEach((p) => {
      const cb = el("input", { type: "checkbox" });
      cb.checked = !chosen.size || chosen.has(p.id);
      inputs.push({ id: p.id, cb });
      box.appendChild(el("label", { className: "instructor-check" }, [cb, ` ${p.title} (${p.count})`]));
    });
    return {
      box,
      values() {
        const on = inputs.filter((row) => row.cb.checked).map((row) => row.id);
        if (on.length === inputs.length) return [];
        return on;
      },
    };
  }

  function numField(label, value, attrs) {
    const input = el("input", { type: "number", value: String(value), ...attrs });
    return { input, wrap: el("label", {}, [label, input]) };
  }

  function taskPicker(selected) {
    const chosen = new Set(selected || []);
    const boxes = {};
    const wrap = el("div", { className: "stack instructor-task-groups" });
    const randomBtn = el("button", { type: "button", className: "ghost-btn" }, "Randomize");
    wrap.appendChild(randomBtn);
    TASK_GROUPS.forEach((group) => {
      const ids = Object.keys(group.tasks);
      const list = el("div", { className: "instructor-task-list" });
      const all = el("input", { type: "checkbox" });
      const refreshAll = () => { all.checked = ids.every((id) => boxes[id]?.checked); };
      all.addEventListener("change", () => {
        ids.forEach((id) => { boxes[id].checked = all.checked; });
      });
      list.appendChild(el("label", { className: "instructor-check" }, [all, " Select All"]));
      ids.forEach((id) => {
        const cb = el("input", { type: "checkbox" });
        cb.checked = chosen.has(id);
        boxes[id] = cb;
        cb.addEventListener("change", refreshAll);
        list.appendChild(el("label", { className: "instructor-check" }, [cb, ` ${group.tasks[id]}`]));
      });
      refreshAll();
      wrap.appendChild(el("fieldset", { className: "instructor-task-group" }, [
        el("legend", {}, group.label),
        list,
      ]));
    });
    randomBtn.addEventListener("click", () => {
      Object.values(boxes).forEach((cb) => { cb.checked = Math.random() < 0.5; });
      wrap.querySelectorAll("fieldset input").forEach((cb) => cb.dispatchEvent(new Event("change")));
    });
    return {
      wrap,
      values() {
        return Object.entries(boxes).filter(([, cb]) => cb.checked).map(([id]) => id);
      },
    };
  }

  async function renderHub(dynamicId, viewEl) {
    viewEl.replaceChildren(el("p", { className: "muted" }, "Loading Instructor…"));
    try {
      const [catalog, sessions, cfg] = await Promise.all([
        fetchCatalog(dynamicId),
        api(`/dynamics/${dynamicId}/instructor/sessions?limit=20`).catch(() => []),
        api(`/dynamics/${dynamicId}/instructor/config`),
      ]);
      const you = state.currentDynamic?.partners?.find((p) => p.is_you);
      const isDom = you?.role === "dominant";
      const error = el("div", { className: "error hidden" });
      const stack = el("div", { className: "stack" }, [
        el("h1", {}, "Instructor"),
        el("p", { className: "muted" }, "Local-files Instructor: stroke to the beat, task mode, and on-screen controls. Media is the shared redgifs folder — not a website."),
        error,
      ]);
      if (!catalog.ok || catalog.empty) {
        stack.appendChild(el("div", { className: "card stack" }, [
          el("p", { className: "muted" }, "No playlists yet. Drop video/image files into subdirectories of the Instructor media folder on the host (UBETRA_REDGIFS_HOST)."),
        ]));
      }
      stack.appendChild(el("button", {
        type: "button",
        className: "primary-btn",
        onClick: () => {
          unlockInstructorAudio();
          openSession(dynamicId, { source: "manual" });
        },
      }, catalog.empty ? "Open anyway" : "Start session"));

      if (isDom) {
        const durationMin = numField("Minimum game duration (min)", cfg.duration_min || 5, { min: "1" });
        const durationMax = numField("Maximum game duration (min)", cfg.duration_max || cfg.duration_min || 15, { min: "1" });
        const slide = numField("Slide duration (sec)", cfg.slide_duration || 10, { min: "3" });
        const strokeMin = numField("Minimum stroke speed (per sec)", cfg.stroke_min || 0.25, { min: "0.1", step: "0.05" });
        const strokeMax = numField("Maximum stroke speed (per sec)", cfg.stroke_max || 4, { min: "0.1", step: "0.05" });
        const gripAdj = el("input", { type: "checkbox" });
        gripAdj.checked = cfg.grip_adjustments !== false;
        const grip = el("select", {});
        GRIP_LABELS.forEach((label, value) => {
          const opt = el("option", { value: String(value) }, label);
          if (Number(cfg.initial_grip ?? 3) === value) opt.selected = true;
          grip.appendChild(opt);
        });
        const finaleO = numField("Probability of an orgasm %", cfg.finale_orgasm ?? 100, { min: "0", max: "100" });
        const finaleD = numField("Probability to be denied %", cfg.finale_denied ?? 0, { min: "0", max: "100" });
        const finaleR = numField("Probability of a ruined orgasm %", cfg.finale_ruined ?? 0, { min: "0", max: "100" });
        const minEdges = numField("Minimum edges", cfg.minimum_edges || 0, { min: "0" });
        const edgeFreq = numField("Edge frequency %", cfg.edge_frequency ?? 10, { min: "0", max: "100" });
        const edgeCd = numField("Edge cooldown (sec)", cfg.edge_cooldown || 10, { min: "0" });
        const ruinsMin = numField("Minimum ruined orgasms", cfg.ruins_min || 0, { min: "0" });
        const ruinsMax = numField("Maximum ruined orgasms", cfg.ruins_max || 0, { min: "0" });
        const ruinCd = numField("Ruin cooldown (sec)", cfg.ruin_cooldown || 20, { min: "0" });
        const pot = el("input", { type: "checkbox" });
        pot.checked = !!cfg.post_orgasm_torture;
        const potMin = numField("Minimum POT (sec)", cfg.pot_min || 10, { min: "0" });
        const potMax = numField("Maximum POT (sec)", cfg.pot_max || 90, { min: "0" });
        const freq = numField("Task frequency (sec)", cfg.action_frequency ?? 30, { min: "0" });
        const lock = el("input", { type: "checkbox" });
        lock.checked = !!cfg.locked;
        const vault = el("input", { type: "checkbox" });
        vault.checked = !!cfg.include_chat_vault;
        const kinds = {};
        const kindRow = el("div", { className: "row wrap" });
        ["picture", "gif", "video"].forEach((kind) => {
          const cb = el("input", { type: "checkbox" });
          cb.checked = (cfg.media_kinds || ["picture", "gif", "video"]).includes(kind);
          kinds[kind] = cb;
          kindRow.appendChild(el("label", { className: "instructor-check" }, [cb, ` ${kind}`]));
        });
        const lists = playlistChecks(catalog.playlists || [], cfg.playlists || []);
        const tasks = taskPicker(cfg.tasks || []);
        stack.appendChild(el("div", { className: "card stack" }, [
          el("h2", {}, "Create a game"),
          el("p", { className: "muted" }, `${controllerDisplayName()} setup. Locked config cannot be changed by the sub. Assign a session as a UBETRA task when you want them to run this.`),
          el("h3", {}, "Game duration"),
          durationMin.wrap,
          durationMax.wrap,
          el("h3", {}, "Media"),
          el("p", { className: "muted" }, "Local files only. Subreddits / Scrolller are not used."),
          kindRow,
          slide.wrap,
          el("h3", {}, "Playlists"),
          lists.box,
          el("label", { className: "instructor-check" }, [vault, " Also use chat vault media"]),
          el("h3", {}, "Stroke"),
          strokeMin.wrap,
          strokeMax.wrap,
          el("label", { className: "instructor-check" }, [gripAdj, " Enable grip adjustments"]),
          el("label", {}, ["Starting grip strength", grip]),
          el("h3", {}, "Game finale"),
          finaleO.wrap,
          finaleD.wrap,
          finaleR.wrap,
          el("h3", {}, "Edging"),
          minEdges.wrap,
          edgeFreq.wrap,
          edgeCd.wrap,
          el("h3", {}, "Ruined orgasms"),
          ruinsMin.wrap,
          ruinsMax.wrap,
          ruinCd.wrap,
          el("h3", {}, "Post orgasm torture"),
          el("label", { className: "instructor-check" }, [pot, " Enable post orgasm torture"]),
          potMin.wrap,
          potMax.wrap,
          el("h3", {}, "Tasks"),
          el("p", { className: "muted" }, "Task mode fires these during play at the frequency below."),
          freq.wrap,
          tasks.wrap,
          el("label", { className: "instructor-check" }, [lock, " Lock settings"]),
          el("button", {
            type: "button",
            className: "primary-btn",
            onClick: async () => {
              error.classList.add("hidden");
              try {
                await api(`/dynamics/${dynamicId}/instructor/config`, {
                  method: "PUT",
                  body: JSON.stringify({
                    duration_min: Number(durationMin.input.value) || 5,
                    duration_max: Number(durationMax.input.value) || 15,
                    slide_duration: Number(slide.input.value) || 10,
                    stroke_min: Number(strokeMin.input.value) || 0.25,
                    stroke_max: Number(strokeMax.input.value) || 4,
                    grip_adjustments: !!gripAdj.checked,
                    initial_grip: Number(grip.value) || 3,
                    finale_orgasm: Number(finaleO.input.value) || 0,
                    finale_denied: Number(finaleD.input.value) || 0,
                    finale_ruined: Number(finaleR.input.value) || 0,
                    minimum_edges: Number(minEdges.input.value) || 0,
                    edge_frequency: Number(edgeFreq.input.value) || 0,
                    edge_cooldown: Number(edgeCd.input.value) || 10,
                    ruins_min: Number(ruinsMin.input.value) || 0,
                    ruins_max: Number(ruinsMax.input.value) || 0,
                    ruin_cooldown: Number(ruinCd.input.value) || 20,
                    post_orgasm_torture: !!pot.checked,
                    pot_min: Number(potMin.input.value) || 10,
                    pot_max: Number(potMax.input.value) || 90,
                    action_frequency: Number(freq.input.value) || 30,
                    locked: !!lock.checked,
                    include_chat_vault: !!vault.checked,
                    media_kinds: Object.keys(kinds).filter((k) => kinds[k].checked),
                    playlists: lists.values(),
                    tasks: tasks.values(),
                  }),
                });
                showToast("Instructor settings saved.");
                renderHub(dynamicId, viewEl);
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Save"),
          el("button", {
            type: "button",
            className: "ghost-btn",
            onClick: async () => {
              try {
                await api(`/dynamics/${dynamicId}/instructor/assign-task`, {
                  method: "POST",
                  body: JSON.stringify({ duration_min: Number(durationMin.input.value) || cfg.duration_min }),
                });
                showToast("Assigned as an Instructor task.");
              } catch (err) {
                error.textContent = err.message;
                error.classList.remove("hidden");
              }
            },
          }, "Assign as task"),
        ]));
      } else {
        stack.appendChild(el("p", { className: "muted" }, cfg.locked
          ? `${controllerDisplayName()} locked this game. Start when you're told.`
          : `${controllerDisplayName()} sets duration, tasks, and playlists.`));
      }

      const log = el("div", { className: "stack" });
      (sessions || []).forEach((row) => {
        const when = typeof formatLocalDateTime === "function" ? formatLocalDateTime(row.started_at) : row.started_at;
        const dur = row.ended_at
          ? `${Math.max(1, Math.round((row.duration_sec || 0) / 60))} min`
          : "open";
        log.appendChild(el("p", { className: "muted" }, `${row.member_name || "Partner"} · ${dur} · ${when}`));
      });
      if (!(sessions || []).length) log.appendChild(el("p", { className: "muted" }, "No sessions yet."));
      stack.appendChild(el("div", { className: "card stack" }, [
        el("h2", {}, isDom ? "Session log" : "Your sessions"),
        log,
      ]));
      stack.appendChild(el("button", {
        type: "button",
        className: "ghost-btn",
        onClick: () => navigate(`/dynamic/${dynamicId}/assistant`),
      }, "Back to Playtime"));
      viewEl.replaceChildren(stack);
    } catch (err) {
      viewEl.replaceChildren(el("p", { className: "error" }, err.message || "Could not load Instructor"));
    }
  }

  global.UbetraInstructor = {
    renderHub,
    openSession,
    isOpen() { return overlayOpen; },
    handleIncomingCall(dynamicId, call) {
      if (overlayIncoming) overlayIncoming(dynamicId, call);
      else pendingIncoming = { dynamicId, call };
    },
  };
})(window);
