(function () {
  const $ = (id) => document.getElementById(id);
  let cameras = [];
  let devices = [];
  let selected = null;
  let hls = null;
  let refreshTimers = [];
  let gridHls = [];
  let viewMode = "wall";
  let recordingSegments = [];
  let playbackSegmentIndex = -1;
  let playbackRun = 0;
  let playbackPlayer = null;
  let timelineStartMs = 0;
  let timelineEndMs = 0;
  let discoveredCameras = [];
  let liveReconnectTimer = null;
  let liveStallTimer = null;
  let liveReconnectAttempts = 0;
  let liveProgressTimer = null;
  let liveLastCurrentTime = -1;
  let liveStalledChecks = 0;
  let liveRecoveryAttempts = 0;

  const request = async (url, options = {}) => {
    const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
    if (!r.ok) {
      let m = r.statusText;
      try {
        m = (await r.json()).detail || m;
      } catch {}
      throw new Error(m);
    }
    return r.status === 204 ? null : r.json();
  };

  const banner = (message, error = true) => {
    $("banner").textContent = message;
    $("banner").hidden = !message;
    $("banner").style.background = error ? "#ffe6e7" : "#dff5ee";
  };

  const bytes = (value) =>
    value == null ? "—" : value > 1099511627776 ? (value / 1099511627776).toFixed(1) + " TB" : (value / 1073741824).toFixed(1) + " GB";
  const clock = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  function updateLiveClocks() {
    document.querySelectorAll("[data-live-label]").forEach((el) => {
      el.textContent = (el.dataset.liveLabel || "LIVE") + " · " + clock();
    });
  }

  function showLiveStatus(label = "LIVE NOW") {
    const el = $("playbackLiveStatus");
    if (!el) return;
    el.hidden = false;
    el.dataset.liveLabel = label;
    updateLiveClocks();
  }

  function showPlaybackStatus(text) {
    const el = $("playbackLiveStatus");
    if (!el) return;
    el.hidden = false;
    delete el.dataset.liveLabel;
    el.textContent = text;
  }

  function cleanupGridStreams() {
    refreshTimers.forEach(clearInterval);
    refreshTimers = [];
    gridHls.forEach((instance) => instance.destroy());
    gridHls = [];
  }

  async function load() {
    cleanupGridStreams();
    try {
      [cameras, devices] = await Promise.all([request("/api/cameras"), request("/devices")]);
      render();
      await health();
      if (selected) await recordings();
    } catch (e) {
      banner(e.message);
    }
  }

  async function health() {
    try {
      const h = await request("/api/camera-health");
      $("recorderStatus").textContent = h.ffmpeg.available ? (h.status === "ok" ? "Healthy" : "Needs attention") : "FFmpeg missing";
      $("storageStatus").textContent = h.storage.free_bytes != null ? bytes(h.storage.free_bytes) + " free" : "Unavailable";
      $("cameraCount").textContent = String(cameras.length + devices.filter((d) => d.brand === "ring").length);
    } catch (e) {
      $("recorderStatus").textContent = "Unavailable";
    }
  }

  function attachLiveVideo(video, url, fallback) {
    if (fallback) {
      fallback.hidden = false;
      fallback.textContent = "Connecting live preview…";
    }
    video.muted = true;
    video.autoplay = true;
    video.playsInline = true;
    video.controls = false;
    const hideFallback = () => {
      if (fallback) fallback.hidden = true;
    };
    const startPlayback = () => video.play().catch(() => {
      if (fallback) {
        fallback.hidden = false;
        fallback.textContent = "Live preview unavailable";
      }
    });
    video.addEventListener("loadeddata", hideFallback);
    video.addEventListener("loadeddata", startPlayback, { once: true });
    video.addEventListener("canplay", () => {
      hideFallback();
      if (video.paused) startPlayback();
    });
    video.addEventListener("playing", hideFallback);
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = url;
      startPlayback();
      return;
    }
    if (window.Hls && Hls.isSupported()) {
      const instance = new Hls({
        liveSyncDurationCount: 1,
        liveMaxLatencyDurationCount: 3,
        maxLiveSyncPlaybackRate: 1.5,
        maxBufferLength: 4,
        backBufferLength: 2,
      });
      gridHls.push(instance);
      instance.loadSource(url);
      instance.attachMedia(video);
      instance.on(Hls.Events.MANIFEST_PARSED, startPlayback);
      instance.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal && fallback) {
          fallback.hidden = false;
          fallback.textContent = "Live preview unavailable";
        }
      });
      return;
    }
    if (fallback) fallback.textContent = "Browser cannot play live HLS";
  }

  function render() {
    const grid = $("cameraGrid");
    grid.innerHTML = "";
    const ring = devices.filter((d) => d.brand === "ring");
    const rows = [
      ...cameras.map((c) => ({ ...c, kind: "ip" })),
      ...ring.map((d) => ({ id: d.id, device_id: d.id, name: d.name, host: "Ring cloud", model: d.model, kind: "ring", recording_enabled: false })),
    ];
    $("emptyState").hidden = rows.length > 0;
    const split = viewMode === "split";
    const wall = viewMode === "wall";
    grid.classList.toggle("split-view", split);
    grid.classList.toggle("wall-view", wall);
    grid.dataset.count = String(rows.length);
    $("liveViewTitle").textContent = wall ? "All cameras" : split ? "4-camera view" : "Camera grid";
    $("wallViewButton").setAttribute("aria-pressed", String(wall));
    $("cardViewButton").setAttribute("aria-pressed", String(viewMode === "cards"));
    $("splitViewButton").setAttribute("aria-pressed", String(split));
    if (split || wall) {
      renderSplitView(grid, rows, wall ? rows.length : 4);
      fitCameraWall();
      updateLiveClocks();
      return;
    }
    rows.forEach((c) => {
      const card = document.createElement("article");
      card.className = "camera-card";
      const mediaMarkup =
        c.kind === "ring"
          ? `<img alt="${escapeHtml(c.name)} camera">`
          : `<video muted autoplay playsinline aria-label="${escapeHtml(c.name)} live preview"></video>`;
      card.innerHTML = `<div class="camera-preview">${mediaMarkup}<span class="unavailable">Camera preview unavailable</span><div class="camera-badges"><span class="badge">${c.kind === "ring" ? "RING" : "LOCAL"}</span>${c.recording_enabled ? '<span class="badge recording">● REC</span>' : ""}</div><div class="live-clock" data-live-label="${c.kind === "ring" ? "LIVE SNAP" : "LIVE"}"></div></div><div class="camera-info"><div><h3>${escapeHtml(c.name)}</h3><p>${escapeHtml(c.model || c.host || "")}</p></div><div class="camera-card-actions"><button type="button" data-action="view">View</button>${c.kind === "ip" ? `<button type="button" data-action="record">${c.recording_enabled ? "Stop REC" : "Start REC"}</button><button type="button" data-action="delete" aria-label="Remove ${escapeHtml(c.name)}">×</button>` : ""}</div></div>`;
      const fallback = card.querySelector(".unavailable");
      if (c.kind === "ring") {
        const img = card.querySelector("img");
        const source = `/devices/${c.id}/ring/snapshot/cached`;
        const update = () => (img.src = source + "?t=" + Date.now());
        update();
        refreshTimers.push(setInterval(update, 30000));
      } else {
        attachLiveVideo(card.querySelector("video"), `/api/cameras/${c.id}/live/index.m3u8`, fallback);
      }
      card.querySelector('[data-action="view"]').onclick = () => selectCamera(c);
      const record = card.querySelector('[data-action="record"]');
      if (record) record.onclick = () => toggleRecording(c);
      const remove = card.querySelector('[data-action="delete"]');
      if (remove) remove.onclick = () => deleteCamera(c);
      card.querySelector(".camera-preview").onclick = () => selectCamera(c);
      grid.appendChild(card);
    });
    updateLiveClocks();
  }

  function fitCameraWall() {
    const grid = $("cameraGrid");
    if (viewMode !== "wall") return;
    const width = grid.clientWidth;
    const columns = width >= 1500 ? 5 : width >= 1000 ? 4 : width >= 700 ? 3 : width >= 440 ? 2 : 1;
    const count = Number(grid.dataset.count) || 1;
    const actualColumns = Math.min(columns, count);
    const rows = Math.ceil(count / actualColumns);
    grid.style.setProperty("--wall-columns", actualColumns);
    grid.style.setProperty("--wall-rows", rows);
    const available = window.innerHeight - grid.getBoundingClientRect().top - 8;
    grid.style.setProperty("--wall-height", Math.max(rows * (width < 700 ? 160 : 110), available) + "px");
  }

  function renderSplitView(grid, rows, count = 4) {
    for (let index = 0; index < count; index += 1) {
      const camera = rows[index];
      const pane = document.createElement("article");
      pane.className = "split-camera" + (camera ? "" : " empty");
      if (!camera) {
        pane.innerHTML = `<div class="split-empty"><strong>Camera ${index + 1}</strong><span>No camera assigned</span></div>`;
        grid.appendChild(pane);
        continue;
      }
      const mediaMarkup = camera.kind === "ring"
        ? `<img alt="${escapeHtml(camera.name)} camera">`
        : `<video muted autoplay playsinline aria-label="${escapeHtml(camera.name)} live view"></video>`;
      pane.innerHTML = `${mediaMarkup}<span class="split-unavailable">Connecting…</span><div class="split-camera-label"><span>${escapeHtml(camera.name)}</span><small data-live-label="${camera.kind === "ring" ? "LIVE SNAP" : "LIVE"}"></small></div>${camera.recording_enabled ? '<span class="split-rec">REC</span>' : ""}`;
      const fallback = pane.querySelector(".split-unavailable");
      if (camera.kind === "ring") {
        const img = pane.querySelector("img");
        const source = `/devices/${camera.id}/ring/snapshot/cached`;
        const update = () => {
          img.src = source + "?t=" + Date.now();
          fallback.hidden = true;
        };
        update();
        refreshTimers.push(setInterval(update, 30000));
      } else {
        attachLiveVideo(pane.querySelector("video"), `/api/cameras/${camera.id}/live/index.m3u8`, fallback);
      }
      pane.tabIndex = 0;
      pane.setAttribute("role", "button");
      pane.setAttribute("aria-label", `Open ${camera.name} timeline`);
      pane.onclick = () => selectCamera(camera);
      pane.onkeydown = (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectCamera(camera);
        }
      };
      grid.appendChild(pane);
    }
  }

  function setViewMode(mode) {
    if (viewMode === mode) return;
    cleanupGridStreams();
    viewMode = mode;
    render();
  }

  async function toggleRecording(camera) {
    try {
      await request(`/api/cameras/${camera.id}`, { method: "PUT", body: JSON.stringify({ recording_enabled: !camera.recording_enabled }) });
      banner(camera.recording_enabled ? "Recording stopped." : "Recording is starting.", false);
      await load();
    } catch (e) {
      banner(e.message);
    }
  }

  async function deleteCamera(camera) {
    if (!window.confirm(`Remove ${camera.name} from Sentinel? Existing recording files will be retained.`)) return;
    try {
      await request(`/api/cameras/${camera.id}`, { method: "DELETE" });
      if (selected && selected.id === camera.id) {
        selected = null;
        $("playbackSection").hidden = true;
        stopPlayer();
      }
      banner("Camera removed.", false);
      await load();
    } catch (e) {
      banner(e.message);
    }
  }

  async function selectCamera(c) {
    if (document.fullscreenElement) {
      try { await document.exitFullscreen(); }
      catch { banner("Exit fullscreen to open the camera timeline."); return; }
    }
    selected = c;
    // The large player is the priority view. Stop background HLS decoders so
    // several camera tiles cannot starve it of browser decode/buffer resources.
    cleanupGridStreams();
    $("ptzControls").hidden = true;
    $("playbackSection").hidden = false;
    $("playbackTitle").textContent = c.name + " timeline";
    $("timelineDate").value = $("timelineDate").value || localDateValue();
    window.scrollTo({ top: $("playbackSection").offsetTop - 90, behavior: "smooth" });
    startLive();
    recordings();
    loadPtzCapabilities(c);
  }

  async function loadPtzCapabilities(camera) {
    if (camera.kind === "ring") return;
    $("ptzStatus").textContent = "Checking camera…";
    try {
      const capability = await request(`/api/cameras/${camera.id}/ptz`);
      if (!selected || selected.id !== camera.id) return;
      $("ptzControls").hidden = !capability.supported;
      $("ptzStatus").textContent = capability.supported ? "Press and hold to move" : "PTZ unavailable";
      document.querySelectorAll("[data-ptz-pan]").forEach((button) => (button.disabled = !capability.pan_tilt));
      document.querySelectorAll("[data-ptz-zoom]").forEach((button) => (button.disabled = !capability.zoom));
    } catch (error) {
      if (selected && selected.id === camera.id) {
        $("ptzControls").hidden = true;
        $("ptzStatus").textContent = error.message;
      }
    }
  }

  async function ptzMove(pan, tilt, zoom) {
    if (!selected) return;
    $("ptzStatus").textContent = "Moving…";
    try {
      await request(`/api/cameras/${selected.id}/ptz/move`, {
        method: "POST", body: JSON.stringify({ pan, tilt, zoom }),
      });
    } catch (error) {
      $("ptzStatus").textContent = error.message;
    }
  }

  async function ptzStop() {
    if (!selected || $("ptzControls").hidden) return;
    try {
      await request(`/api/cameras/${selected.id}/ptz/stop`, { method: "POST" });
      $("ptzStatus").textContent = "Press and hold to move";
    } catch (error) {
      $("ptzStatus").textContent = error.message;
    }
  }

  function bindPtzButton(button, velocity) {
    const start = (event) => {
      event.preventDefault();
      if (button.setPointerCapture && event.pointerId != null) button.setPointerCapture(event.pointerId);
      ptzMove(velocity.pan || 0, velocity.tilt || 0, velocity.zoom || 0);
    };
    button.addEventListener("pointerdown", start);
    button.addEventListener("pointerup", ptzStop);
    button.addEventListener("pointercancel", ptzStop);
    button.addEventListener("lostpointercapture", ptzStop);
    button.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && !event.repeat) start(event);
    });
    button.addEventListener("keyup", (event) => {
      if (event.key === "Enter" || event.key === " ") ptzStop();
    });
  }

  function stopPlayer(preserveLiveRetry = false) {
    playbackRun += 1;
    playbackSegmentIndex = -1;
    clearTimeout(liveReconnectTimer);
    clearTimeout(liveStallTimer);
    clearInterval(liveProgressTimer);
    liveReconnectTimer = null;
    liveStallTimer = null;
    liveProgressTimer = null;
    liveLastCurrentTime = -1;
    liveStalledChecks = 0;
    liveRecoveryAttempts = 0;
    if (!preserveLiveRetry) liveReconnectAttempts = 0;
    if (hls) {
      hls.destroy();
      hls = null;
    }
    [$("player"), $("playerBuffer")].forEach((player, index) => {
      player.pause();
      player.onended = null;
      player.ontimeupdate = null;
      player.onloadedmetadata = null;
      player.oncanplay = null;
      player.onplaying = null;
      player.onwaiting = null;
      player.onstalled = null;
      player.onerror = null;
      player.onended = null;
      player.removeAttribute("src");
      player.classList.toggle("playback-active", index === 0);
      player.setAttribute("aria-hidden", index === 0 ? "false" : "true");
      player.load();
    });
    playbackPlayer = $("player");
  }

  function scheduleLiveReconnect(message = "Live video paused. Reconnecting…") {
    if (liveReconnectTimer || !selected || selected.kind === "ring") return;
    const cameraId = selected.id;
    const video = $("player");
    if (!video.poster) video.poster = `/api/cameras/${cameraId}/snapshot?t=${Date.now()}`;
    const delay = Math.min(500 + liveReconnectAttempts * 500, 2000);
    $("playerMessage").textContent = message;
    liveReconnectTimer = setTimeout(() => {
      liveReconnectTimer = null;
      if (!selected || selected.id !== cameraId) return;
      if (selected && selected.id === cameraId) startLive(true);
    }, delay);
  }

  function recoverLiveInPlace(message = "Live video paused. Recovering…") {
    clearTimeout(liveStallTimer);
    if (!selected || selected.kind === "ring") return;
    $("playerMessage").textContent = message;
    liveRecoveryAttempts += 1;
    if (hls) {
      try {
        hls.stopLoad();
        hls.startLoad(-1);
        if (liveRecoveryAttempts > 1) hls.recoverMediaError();
        $("player").play().catch(() => {});
      } catch {}
    } else {
      $("player").play().catch(() => {});
    }
    liveStallTimer = setTimeout(() => {
      if (liveStalledChecks >= 2) scheduleLiveReconnect("Live feed is reconnecting…");
    }, 3500);
  }

  function watchForLiveStall() {
    clearTimeout(liveStallTimer);
    liveStallTimer = setTimeout(() => recoverLiveInPlace(), 2500);
  }

  function startLiveProgressWatchdog(video) {
    clearInterval(liveProgressTimer);
    liveLastCurrentTime = video.currentTime;
    liveStalledChecks = 0;
    liveProgressTimer = setInterval(() => {
      if (!selected || selected.kind === "ring" || video.paused || video.ended) return;
      const current = video.currentTime;
      if (current > liveLastCurrentTime + 0.05) {
        liveLastCurrentTime = current;
        liveStalledChecks = 0;
        liveRecoveryAttempts = 0;
        clearTimeout(liveStallTimer);
        liveStallTimer = null;
        $("playerMessage").textContent = "";
        return;
      }
      if (video.readyState < HTMLMediaElement.HAVE_FUTURE_DATA) {
        liveStalledChecks += 1;
        if (liveStalledChecks === 2) recoverLiveInPlace();
        else if (liveStalledChecks >= 4) scheduleLiveReconnect("Live feed is reconnecting…");
      }
    }, 1500);
  }

  function startLive(isRetry = false) {
    if (!selected) return;
    stopPlayer(isRetry);
    if (isRetry) liveReconnectAttempts += 1;
    showLiveStatus(selected.kind === "ring" ? "LIVE SNAP" : "LIVE NOW");
    const video = $("player");
    $("playerMessage").textContent = "Connecting to live video…";
    if (selected.kind === "ring") {
      $("playerMessage").textContent = "Open this Ring camera from the dashboard for its live WebRTC feed.";
      return;
    }
    const url = `/api/cameras/${selected.id}/live/index.m3u8?session=${Date.now()}`;
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = url;
      video.play().catch(() => {});
    } else if (window.Hls && Hls.isSupported()) {
      hls = new Hls({
        liveSyncDurationCount: 1,
        liveMaxLatencyDurationCount: 3,
        maxLiveSyncPlaybackRate: 1.5,
        maxBufferLength: 4,
        backBufferLength: 2,
        manifestLoadingMaxRetry: 8,
        levelLoadingMaxRetry: 8,
        fragLoadingMaxRetry: 8,
        manifestLoadingRetryDelay: 300,
        levelLoadingRetryDelay: 300,
        fragLoadingRetryDelay: 300
      });
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (!data.fatal) return;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          recoverLiveInPlace("Live network hiccup. Recovering…");
        } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          try { hls.recoverMediaError(); } catch {}
          watchForLiveStall();
        } else {
          scheduleLiveReconnect("Live stream interrupted. Reconnecting…");
        }
      });
    } else {
      $("playerMessage").textContent = "Live video needs HLS support; camera previews remain available.";
    }
    video.onplaying = () => {
      clearTimeout(liveStallTimer);
      liveReconnectAttempts = 0;
      liveRecoveryAttempts = 0;
      liveStalledChecks = 0;
      video.removeAttribute("poster");
      $("playerMessage").textContent = "";
    };
    video.onwaiting = watchForLiveStall;
    video.onstalled = watchForLiveStall;
    video.onerror = () => scheduleLiveReconnect("Live video failed. Reconnecting…");
    video.onended = () => scheduleLiveReconnect();
    startLiveProgressWatchdog(video);
  }

  function localDateValue(date = new Date()) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  async function recordings() {
    if (!selected || selected.kind === "ring") {
      $("timeline").innerHTML = "";
      $("timelineSummary").textContent = "Ring is live-only";
      return;
    }
    const day = $("timelineDate").value || localDateValue();
    const start = new Date(day + "T00:00:00");
    const end = new Date(day + "T23:59:59.999");
    try {
      const data = await request(`/api/cameras/${selected.id}/recordings?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`);
      const timeline = $("timeline");
      timeline.innerHTML = "";
      $("timelineSummary").textContent = data.segments.length + " recorded segments";
      recordingSegments = normalizeRecordingSegments(data.segments);
      if (!recordingSegments.length) {
        timeline.innerHTML = '<div class="timeline-empty">No recordings are available for this date.</div>';
        return;
      }
      timelineStartMs = recordingSegments[0].startMs;
      timelineEndMs = Math.max(...recordingSegments.map((segment) => segment.endMs));
      renderRecordingTimeline(timeline);
    } catch (e) {
      banner(e.message);
    }
  }

  function normalizeRecordingSegments(segments) {
    const sorted = segments.map((segment) => {
      const startMs = new Date(segment.started_at).getTime();
      const duration = Math.max(1, Number(segment.duration_seconds) || 10);
      return { ...segment, startMs, endMs: startMs + duration * 1000 };
    }).filter((segment) => Number.isFinite(segment.startMs)).sort((a, b) => a.startMs - b.startMs);
    const normalized = [];
    sorted.forEach((segment) => {
      const previous = normalized[normalized.length - 1];
      if (!previous || segment.startMs >= previous.endMs - 1000) normalized.push(segment);
    });
    return normalized;
  }

  function timelineClock(milliseconds, includeSeconds = true) {
    return new Date(milliseconds).toLocaleTimeString([], {
      hour: "2-digit", minute: "2-digit", second: includeSeconds ? "2-digit" : undefined,
    });
  }

  function renderRecordingTimeline(timeline) {
    const durationSeconds = Math.max(1, Math.ceil((timelineEndMs - timelineStartMs) / 1000));
    timeline.innerHTML = `<div class="timeline-readout"><div><span>Selected time</span><strong id="timelineSelectedTime">${timelineClock(timelineStartMs)}</strong></div><p>Drag or click to choose a time. Playback continues through every later recording until you pause or choose another time.</p></div><div class="timeline-track-wrap"><div id="timelineCoverage" class="timeline-coverage" aria-hidden="true"></div><input id="timelineScrubber" type="range" min="0" max="${durationSeconds}" step="0.1" value="0" aria-label="Select recording time"></div><div class="timeline-labels"><span>${timelineClock(timelineStartMs)}</span><span>${timelineClock(timelineStartMs + (timelineEndMs - timelineStartMs) / 2, false)}</span><span>${timelineClock(timelineEndMs)}</span></div>`;
    const coverage = $("timelineCoverage");
    recordingSegments.forEach((segment) => {
      const block = document.createElement("span");
      block.style.left = ((segment.startMs - timelineStartMs) / (timelineEndMs - timelineStartMs) * 100) + "%";
      block.style.width = (Math.max(0.2, (segment.endMs - segment.startMs) / (timelineEndMs - timelineStartMs) * 100)) + "%";
      coverage.appendChild(block);
    });
    const scrubber = $("timelineScrubber");
    scrubber.oninput = () => updateTimelineReadout(Number(scrubber.value));
    scrubber.onchange = () => playFromTimeline(Number(scrubber.value));
  }

  function updateTimelineReadout(offsetSeconds) {
    const selectedMs = Math.min(timelineEndMs, timelineStartMs + offsetSeconds * 1000);
    if ($("timelineSelectedTime")) $("timelineSelectedTime").textContent = timelineClock(selectedMs);
  }

  function playFromTimeline(offsetSeconds) {
    const requestedMs = Math.min(timelineEndMs, timelineStartMs + offsetSeconds * 1000);
    let index = recordingSegments.findIndex((segment) => requestedMs >= segment.startMs && requestedMs < segment.endMs);
    if (index < 0) index = recordingSegments.findIndex((segment) => segment.startMs > requestedMs);
    if (index < 0) index = recordingSegments.length - 1;
    const segment = recordingSegments[index];
    const seekSeconds = Math.max(0, Math.min((requestedMs - segment.startMs) / 1000, (segment.endMs - segment.startMs) / 1000 - 0.1));
    stopPlayer();
    const run = playbackRun;
    playRecordingSegment(index, seekSeconds, run);
  }

  function playRecordingSegment(index, seekSeconds, run) {
    if (run !== playbackRun || index < 0 || index >= recordingSegments.length) return;
    const segment = recordingSegments[index];
    const player = playbackPlayer || $("player");
    const alreadyPrepared = player.getAttribute("src") === segment.media_url && player.readyState >= 1;
    activatePlaybackPlayer(player);
    playbackSegmentIndex = index;
    showPlaybackStatus("PLAYBACK · " + new Date(segment.startMs + seekSeconds * 1000).toLocaleString());
    $("playerMessage").textContent = "";
    player.onloadedmetadata = () => {
      if (run !== playbackRun) return;
      player.currentTime = Math.min(seekSeconds, Math.max(0, player.duration - 0.1));
      player.play().catch(() => {});
    };
    player.ontimeupdate = () => {
      if (run !== playbackRun || playbackSegmentIndex !== index) return;
      const absoluteMs = Math.min(timelineEndMs, segment.startMs + player.currentTime * 1000);
      const offset = Math.max(0, (absoluteMs - timelineStartMs) / 1000);
      if ($("timelineScrubber")) $("timelineScrubber").value = String(offset);
      updateTimelineReadout(offset);
      showPlaybackStatus("PLAYBACK · " + new Date(absoluteMs).toLocaleString());
    };
    player.onended = () => {
      if (run !== playbackRun) return;
      const nextIndex = index + 1;
      if (nextIndex < recordingSegments.length) {
        const nextPlayer = otherPlaybackPlayer(player);
        nextPlayer.muted = player.muted;
        nextPlayer.volume = player.volume;
        nextPlayer.playbackRate = player.playbackRate;
        playbackPlayer = nextPlayer;
        playRecordingSegment(nextIndex, 0, run);
      }
      else showPlaybackStatus("PLAYBACK COMPLETE");
    };
    if (alreadyPrepared) {
      player.currentTime = Math.min(seekSeconds, Math.max(0, player.duration - 0.1));
      player.play().catch(() => {});
    } else {
      player.src = segment.media_url;
      player.load();
    }
    preloadRecordingSegment(index + 1, player, run);
  }

  function otherPlaybackPlayer(player) {
    return player === $("player") ? $("playerBuffer") : $("player");
  }

  function activatePlaybackPlayer(player) {
    [$("player"), $("playerBuffer")].forEach((candidate) => {
      const active = candidate === player;
      candidate.classList.toggle("playback-active", active);
      candidate.setAttribute("aria-hidden", active ? "false" : "true");
    });
  }

  function preloadRecordingSegment(index, currentPlayer, run) {
    if (run !== playbackRun || index >= recordingSegments.length) return;
    const nextPlayer = otherPlaybackPlayer(currentPlayer);
    nextPlayer.pause();
    nextPlayer.onended = null;
    nextPlayer.ontimeupdate = null;
    nextPlayer.onloadedmetadata = null;
    nextPlayer.src = recordingSegments[index].media_url;
    nextPlayer.load();
  }

  async function discover() {
    const b = $("discoverButton");
    b.disabled = true;
    b.textContent = "Scanning VPN and LAN…";
    try {
      const requested = $("discoverySubnet").value.split(",").map((v) => v.trim()).filter(Boolean);
      const data = await request("/api/cameras/discover", { method: "POST", body: JSON.stringify({ timeout_seconds: 3, subnets: requested, scan_routed_subnets: true }) });
      discoveredCameras = data.cameras;
      renderDiscoveredCameras();
      const scanned = (data.scanned_subnets || []).join(", ");
      if (!data.cameras.length) banner("No ONVIF or RTSP cameras answered on " + (scanned || "the detected networks") + ". Confirm the VPN route and camera firewall rules.", false);
      else banner("Found " + data.cameras.length + " camera candidate(s) while scanning " + scanned + ".", false);
    } catch (e) {
      banner(e.message);
    } finally {
      b.disabled = false;
      b.textContent = "Discover cameras";
    }
  }

  function normalizedHost(value) {
    return String(value || "").trim().toLowerCase();
  }

  function cameraLabel(camera) {
    return (camera.types && camera.types[0]) || camera.source || "ONVIF camera";
  }

  function renderDiscoveredCameras() {
    const panel = $("discoveredCameraPanel");
    const list = $("discoveredCameraList");
    const existingHosts = new Set(cameras.map((camera) => normalizedHost(camera.host)));
    list.innerHTML = "";
    discoveredCameras.forEach((camera, index) => {
      const alreadyAdded = existingHosts.has(normalizedHost(camera.host));
      const label = document.createElement("label");
      label.className = "discovered-camera-item" + (alreadyAdded ? " is-added" : "");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "discovered-camera-check";
      checkbox.dataset.index = String(index);
      checkbox.disabled = alreadyAdded;
      checkbox.onchange = updateBatchSelection;
      const details = document.createElement("span");
      const host = document.createElement("strong");
      host.textContent = camera.host;
      const description = document.createElement("small");
      description.textContent = cameraLabel(camera) + (camera.subnet ? " · " + camera.subnet : "");
      details.append(host, description);
      const state = document.createElement("em");
      state.textContent = alreadyAdded ? "Already added" : "New";
      label.append(checkbox, details, state);
      list.appendChild(label);
    });
    const available = discoveredCameras.filter((camera) => !existingHosts.has(normalizedHost(camera.host))).length;
    $("discoveredCameraSummary").textContent = available + " new · " + (discoveredCameras.length - available) + " already added";
    panel.hidden = false;
    $("selectAllDiscovered").checked = false;
    $("selectAllDiscovered").disabled = available === 0;
    $("batchCameraStatus").textContent = "";
    updateBatchSelection();
  }

  function selectedDiscoveredCameras() {
    return [...document.querySelectorAll(".discovered-camera-check:checked")]
      .map((checkbox) => discoveredCameras[Number(checkbox.dataset.index)])
      .filter(Boolean);
  }

  function updateBatchSelection() {
    const selectedCount = selectedDiscoveredCameras().length;
    const available = [...document.querySelectorAll(".discovered-camera-check:not(:disabled)")];
    $("addSelectedCamerasButton").disabled = selectedCount === 0;
    $("addSelectedCamerasButton").textContent = selectedCount ? `Add ${selectedCount} selected camera${selectedCount === 1 ? "" : "s"}` : "Add selected cameras";
    $("selectAllDiscovered").checked = available.length > 0 && available.every((checkbox) => checkbox.checked);
    $("selectAllDiscovered").indeterminate = selectedCount > 0 && selectedCount < available.length;
  }

  async function fetchProfiles(camera) {
    const data = await request("/api/cameras/onvif-profiles", {
      method: "POST",
      body: JSON.stringify({
        host: camera.host,
        port: Number(camera.onvif_port || 80),
        username: $("cameraUsername").value || null,
        password: $("cameraPassword").value || null,
      }),
    });
    if (!data.profiles.length) throw new Error("No ONVIF stream profiles were returned.");
    return data.profiles;
  }

  async function addSelectedCameras() {
    const selectedCameras = selectedDiscoveredCameras();
    if (!selectedCameras.length) return;
    const button = $("addSelectedCamerasButton");
    const checkboxes = [...document.querySelectorAll(".discovered-camera-check")];
    button.disabled = true;
    checkboxes.forEach((checkbox) => (checkbox.disabled = true));
    const added = [];
    const failed = [];
    for (let index = 0; index < selectedCameras.length; index += 1) {
      const camera = selectedCameras[index];
      $("batchCameraStatus").textContent = `Loading profiles and adding ${index + 1} of ${selectedCameras.length}: ${camera.host}`;
      try {
        const cameraProfiles = await fetchProfiles(camera);
        const bySize = [...cameraProfiles].sort((a, b) => ((b.width || 0) * (b.height || 0)) - ((a.width || 0) * (a.height || 0)));
        const main = bySize[0];
        const sub = bySize.length > 1 ? bySize[bySize.length - 1] : null;
        await request("/api/cameras", {
          method: "POST",
          body: JSON.stringify({
            name: `IP Camera ${camera.host}`,
            host: camera.host,
            model: null,
            username: $("cameraUsername").value || null,
            password: $("cameraPassword").value || null,
            main_stream_url: main.stream_url,
            sub_stream_url: sub && sub.stream_url !== main.stream_url ? sub.stream_url : null,
            recording_enabled: $("recordingEnabled").checked,
          }),
        });
        added.push(camera.host);
      } catch (error) {
        failed.push(`${camera.host}: ${error.message}`);
      }
    }
    await load();
    renderDiscoveredCameras();
    if (failed.length) {
      $("batchCameraStatus").textContent = `Added ${added.length}. Could not add ${failed.length}: ${failed.join("; ")}`;
      banner(`Added ${added.length} camera${added.length === 1 ? "" : "s"}; ${failed.length} need attention.`, true);
    } else {
      $("batchCameraStatus").textContent = `Added ${added.length} camera${added.length === 1 ? "" : "s"} successfully.`;
      banner(`Added ${added.length} camera${added.length === 1 ? "" : "s"}. Sentinel is starting their recorders.`, false);
    }
  }

  async function profiles() {
    try {
      const data = { profiles: await fetchProfiles({ host: $("cameraHost").value, onvif_port: Number($("onvifPort").value) }) };
      ["mainProfile", "subProfile"].forEach((id) => {
        $(id).innerHTML = `<option value="">${id === "mainProfile" ? "Enter RTSP URL manually" : "Use main stream"}</option>`;
        data.profiles.forEach((p) => {
          const o = document.createElement("option");
          o.value = p.stream_url;
          o.textContent = p.name + (p.width ? ` · ${p.width}×${p.height}` : "");
          $(id).appendChild(o);
        });
      });
      if (data.profiles[0]) {
        $("mainProfile").value = data.profiles[0].stream_url;
        $("mainStream").value = data.profiles[0].stream_url;
      }
      if (data.profiles.length > 1) {
        const low = [...data.profiles].sort((a, b) => (a.width || 0) - (b.width || 0))[0];
        $("subProfile").value = low.stream_url;
        $("subStream").value = low.stream_url;
      }
    } catch (e) {
      banner(e.message);
    }
  }

  async function saveCamera(e) {
    e.preventDefault();
    try {
      await request("/api/cameras", {
        method: "POST",
        body: JSON.stringify({
          name: $("cameraName").value,
          host: $("cameraHost").value,
          model: $("cameraModel").value || null,
          username: $("cameraUsername").value || null,
          password: $("cameraPassword").value || null,
          main_stream_url: $("mainStream").value,
          sub_stream_url: $("subStream").value || null,
          recording_enabled: $("recordingEnabled").checked,
        }),
      });
      $("cameraDialog").close();
      $("cameraForm").reset();
      banner("Camera saved. Sentinel is starting its recorder.", false);
      await load();
    } catch (e) {
      banner(e.message);
    }
  }

  async function openStorage() {
    try {
      const s = await request("/api/camera-settings");
      $("recordingRoot").value = s.recording_root;
      $("capacityGb").value = s.capacity_gb || "";
      $("reserveGb").value = s.reserve_gb;
      $("storageDialog").showModal();
    } catch (e) {
      banner(e.message);
    }
  }

  async function saveStorage(e) {
    e.preventDefault();
    try {
      await request("/api/camera-settings", {
        method: "PUT",
        body: JSON.stringify({ recording_root: $("recordingRoot").value, capacity_gb: $("capacityGb").value ? Number($("capacityGb").value) : null, reserve_gb: Number($("reserveGb").value) }),
      });
      $("storageDialog").close();
      banner("Storage settings saved.", false);
      health();
    } catch (e) {
      banner(e.message);
    }
  }

  function escapeHtml(v) {
    return String(v || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  $("addButton").onclick = $("emptyAddButton").onclick = () => $("cameraDialog").showModal();
  $("storageButton").onclick = openStorage;
  $("cardViewButton").onclick = () => setViewMode("cards");
  $("wallViewButton").onclick = () => setViewMode("wall");
  $("stretchViewButton").onclick = () => {
    const stretched = $("cameraGrid").classList.toggle("stretched-view");
    $("stretchViewButton").setAttribute("aria-pressed", String(stretched));
  };
  $("fullscreenButton").onclick = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await $("liveSection").requestFullscreen();
    } catch (error) {
      banner("Fullscreen is unavailable. You can still use the camera wall in this window.");
    }
  };
  document.addEventListener("fullscreenchange", () => {
    $("fullscreenButton").textContent = document.fullscreenElement ? "Exit fullscreen" : "Fullscreen";
    fitCameraWall();
  });
  window.addEventListener("resize", fitCameraWall);
  new ResizeObserver(fitCameraWall).observe($("liveSection"));
  $("splitViewButton").onclick = () => setViewMode("split");
  $("refreshButton").onclick = load;
  $("discoverButton").onclick = discover;
  $("addSelectedCamerasButton").onclick = addSelectedCameras;
  $("selectAllDiscovered").onchange = (event) => {
    document.querySelectorAll(".discovered-camera-check:not(:disabled)").forEach((checkbox) => (checkbox.checked = event.target.checked));
    updateBatchSelection();
  };
  $("loadProfilesButton").onclick = profiles;
  $("cameraForm").onsubmit = saveCamera;
  $("storageForm").onsubmit = saveStorage;
  $("timelineDate").onchange = () => {
    stopPlayer();
    recordings();
  };
  $("jumpLiveButton").onclick = startLive;
  document.querySelectorAll("[data-ptz-pan]").forEach((button) => bindPtzButton(button, {
    pan: Number(button.dataset.ptzPan), tilt: Number(button.dataset.ptzTilt),
  }));
  document.querySelectorAll("[data-ptz-zoom]").forEach((button) => bindPtzButton(button, {
    zoom: Number(button.dataset.ptzZoom),
  }));
  $("ptzStopButton").onclick = ptzStop;
  $("mainProfile").onchange = (e) => {
    if (e.target.value) $("mainStream").value = e.target.value;
  };
  $("subProfile").onchange = (e) => ($("subStream").value = e.target.value);
  document.querySelectorAll("[data-close]").forEach((b) => (b.onclick = () => $(b.dataset.close).close()));
  load();
  setInterval(health, 30000);
  setInterval(updateLiveClocks, 1000);
})();
