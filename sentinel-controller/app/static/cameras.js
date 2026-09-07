(function () {
  const $ = (id) => document.getElementById(id);
  let cameras = [];
  let devices = [];
  let selected = null;
  let hls = null;
  let refreshTimers = [];
  let gridHls = [];
  let viewMode = "cards";
  let recordingSegments = [];
  let playbackSegmentIndex = -1;
  let playbackRun = 0;
  let playbackPlayer = null;
  let timelineStartMs = 0;
  let timelineEndMs = 0;

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
      const instance = new Hls({ liveSyncDurationCount: 2, maxBufferLength: 8 });
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
    grid.classList.toggle("split-view", split);
    $("liveViewTitle").textContent = split ? "4-camera view" : "Camera grid";
    $("cardViewButton").setAttribute("aria-pressed", String(!split));
    $("splitViewButton").setAttribute("aria-pressed", String(split));
    if (split) {
      renderSplitView(grid, rows);
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

  function renderSplitView(grid, rows) {
    for (let index = 0; index < 4; index += 1) {
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

  function selectCamera(c) {
    selected = c;
    $("playbackSection").hidden = false;
    $("playbackTitle").textContent = c.name + " timeline";
    $("timelineDate").value = $("timelineDate").value || new Date().toISOString().slice(0, 10);
    window.scrollTo({ top: $("playbackSection").offsetTop - 90, behavior: "smooth" });
    startLive();
    recordings();
  }

  function stopPlayer() {
    playbackRun += 1;
    playbackSegmentIndex = -1;
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
      player.removeAttribute("src");
      player.classList.toggle("playback-active", index === 0);
      player.setAttribute("aria-hidden", index === 0 ? "false" : "true");
      player.load();
    });
    playbackPlayer = $("player");
  }

  function startLive() {
    if (!selected) return;
    stopPlayer();
    showLiveStatus(selected.kind === "ring" ? "LIVE SNAP" : "LIVE NOW");
    const video = $("player");
    $("playerMessage").textContent = "Connecting to live video…";
    if (selected.kind === "ring") {
      $("playerMessage").textContent = "Open this Ring camera from the dashboard for its live WebRTC feed.";
      return;
    }
    const url = `/api/cameras/${selected.id}/live/index.m3u8`;
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = url;
      video.play().catch(() => {});
    } else if (window.Hls && Hls.isSupported()) {
      hls = new Hls({ liveSyncDurationCount: 2 });
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal) $("playerMessage").textContent = "Live stream unavailable.";
      });
    } else {
      $("playerMessage").textContent = "Live video needs HLS support; camera previews remain available.";
    }
    video.onplaying = () => ($("playerMessage").textContent = "");
  }

  async function recordings() {
    if (!selected || selected.kind === "ring") {
      $("timeline").innerHTML = "";
      $("timelineSummary").textContent = "Ring is live-only";
      return;
    }
    const day = $("timelineDate").value || new Date().toISOString().slice(0, 10);
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
      const select = $("discoveredCameras");
      select.innerHTML = '<option value="">Select a discovered camera</option>';
      data.cameras.forEach((c) => {
        const o = document.createElement("option");
        o.value = c.host;
        o.dataset.port = String(c.onvif_port || 80);
        o.textContent = c.host + " · " + (c.types[0] || c.source || "camera") + (c.subnet ? " · " + c.subnet : "");
        select.appendChild(o);
      });
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

  async function profiles() {
    try {
      const data = await request("/api/cameras/onvif-profiles", {
        method: "POST",
        body: JSON.stringify({ host: $("cameraHost").value, port: Number($("onvifPort").value), username: $("cameraUsername").value || null, password: $("cameraPassword").value || null }),
      });
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
  $("splitViewButton").onclick = () => setViewMode("split");
  $("refreshButton").onclick = load;
  $("discoverButton").onclick = discover;
  $("loadProfilesButton").onclick = profiles;
  $("cameraForm").onsubmit = saveCamera;
  $("storageForm").onsubmit = saveStorage;
  $("timelineDate").onchange = () => {
    stopPlayer();
    recordings();
  };
  $("jumpLiveButton").onclick = startLive;
  $("discoveredCameras").onchange = (e) => {
    if (e.target.value) {
      $("cameraHost").value = e.target.value;
      $("onvifPort").value = e.target.selectedOptions[0].dataset.port || 80;
      $("cameraName").value = $("cameraName").value || "IP Camera";
    }
  };
  $("mainProfile").onchange = (e) => {
    if (e.target.value) $("mainStream").value = e.target.value;
  };
  $("subProfile").onchange = (e) => ($("subStream").value = e.target.value);
  document.querySelectorAll("[data-close]").forEach((b) => (b.onclick = () => $(b.dataset.close).close()));
  load();
  setInterval(health, 30000);
  setInterval(updateLiveClocks, 1000);
})();
