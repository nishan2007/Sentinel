(function () {
  "use strict";

  const state = {
    devices: [],
    states: new Map(),
    inspections: new Map(),
    ringPeerConnections: new Map(),
    ringSnapshotTimers: new Map(),
    ringTileSnapshotRefreshes: new Set(),
    ringTileSnapshotLastRefresh: new Map(),
    ipCameraTileSnapshotUrls: new Map(),
    ipCameraTileSnapshotLastRefresh: new Map(),
    ipCameraTileSnapshotLoaded: new Set(),
    ipCameraTileSnapshotRefreshes: new Set(),
    ipCameraTileLivePlayers: new Map(),
    ipCameraTileLiveWatchdogs: new Map(),
    ipCameraTileLiveLastFrame: new Map(),
    ipCameraTileLiveRepairs: new Set(),
    showLiveCameraTiles: window.localStorage.getItem("sentinel.showLiveCameraTiles") === "true",
    seenRingAlerts: new Set(),
    activeRingNotification: null,
    ringNotificationDismissTimer: null,
    isPollingRingAlerts: false,
    audioContext: null,
    filter: "all",
    search: "",
    isRefreshing: false,
    isCloudRefreshRunning: false,
    isRepairingDuplicates: false,
    showAdminDeviceDetails: false,
    favoriteDeviceIds: loadFavoriteDeviceIds(),
    tileLayoutByDevice: loadTileLayoutPrefs(),
    isSidebarCollapsed: window.localStorage.getItem("sentinel.sidebarCollapsed") === "true",
    isDarkMode: window.localStorage.getItem("sentinel.theme") === "dark"
  };

  const stateRefreshTimeoutMs = 3500;
  const printerStateRefreshTimeoutMs = 18000;
  const iconBasePath = "/icons/";

  const friendlyCapabilityNames = {
    "switch": "Power",
    "samsungce.switch": "Power",
    "switchLevel": "Dimmer",
    "ovenMode": "Oven mode",
    "samsungce.ovenMode": "Oven mode",
    "ovenSetpoint": "Oven temperature",
    "samsungce.ovenSetpoint": "Oven temperature",
    "microwaveMode": "Microwave mode",
    "samsungce.microwavePower": "Microwave power",
    "samsungce.lamp": "Lamp",
    "samsungce.hoodFanSpeed": "Hood fan",
    "samsungce.audioVolumeLevel": "Volume",
    "audioNotification": "Audio notification",
    "refrigeration": "Cooling",
    "thermostatCoolingSetpoint": "Temperature",
    "samsungce.powerCool": "Power Cool",
    "samsungce.powerFreeze": "Power Freeze",
    "custom.waterFilter": "Water filter",
    "custom.fridgeMode": "Fridge mode",
    "samsungce.fridgePantryMode": "Pantry mode",
    "samsungce.foodDefrost": "Food defrost",
    "samsungce.freezerConvertMode": "Freezer mode",
    "samsungce.sabbathMode": "Sabbath mode",
    "custom.washerWaterTemperature": "Water temperature",
    "custom.washerSpinLevel": "Spin level",
    "custom.washerSoilLevel": "Soil level",
    "custom.washerRinseCycles": "Rinse cycles",
    "custom.dryerDryLevel": "Dry level",
    "samsungce.washerOperatingState": "Washer",
    "washerOperatingState": "Washer",
    "samsungce.washerCycle": "Cycle",
    "samsungce.washerDelayEnd": "Delay end",
    "samsungce.washerBubbleSoak": "Bubble soak",
    "samsungce.washerWaterLevel": "Water level",
    "samsungce.washerWaterValve": "Water valve",
    "samsungce.dryerDryingTemperature": "Drying temperature",
    "samsungce.dryerDryingTime": "Drying time",
    "custom.supportedOptions": "Course",
    "custom.washerAutoDetergent": "Auto detergent",
    "custom.washerAutoSoftener": "Auto softener",
    "doorControl": "Door",
    "garageDoorControl": "Door"
  };

  const friendlyCommandNames = {
    activate: "Turn on",
    deactivate: "Turn off",
    on: "Turn on",
    off: "Turn off",
    open: "Open",
    close: "Close",
    start: "Start",
    stop: "Stop",
    pause: "Pause",
    resume: "Resume",
    setLevel: "Set level",
    setOvenMode: "Set mode",
    setOvenSetpoint: "Set temperature",
    setMicrowaveMode: "Set mode",
    setPower: "Set power",
    setPowerLevel: "Set power",
    setFanSpeed: "Set fan speed",
    setHoodFanSpeed: "Set fan speed",
    setBrightnessLevel: "Set brightness",
    setCoolingSetpoint: "Set temperature",
    setRapidCooling: "Rapid cool",
    setRapidFreezing: "Rapid freeze",
    setDefrost: "Defrost",
    resetWaterFilter: "Reset filter",
    setFridgeMode: "Set mode",
    setFreezerConvertMode: "Set mode",
    setMode: "Set mode",
    setVolumeLevel: "Set volume",
    volumeDown: "Volume down",
    volumeUp: "Volume up",
    playTrack: "Play URL",
    playTrackAndRestore: "Play URL once",
    playTrackAndResume: "Play URL and resume",
    setWasherWaterTemperature: "Set water temp",
    setWasherSpinLevel: "Set spin",
    setWasherSoilLevel: "Set soil",
    setWasherRinseCycles: "Set rinses",
    setDryerDryLevel: "Set dry level",
    setDryingTemperature: "Set dry temp",
    setDryingTime: "Set dry time",
    setDelayEnd: "Set delay",
    cancel: "Cancel",
    pause: "Pause",
    resume: "Resume",
    setCourse: "Set course",
    setWasherCycle: "Set cycle",
    setCycleType: "Set cycle type",
    setWasherAutoDetergent: "Auto detergent",
    setWasherAutoSoftener: "Auto softener",
    setWaterLevel: "Set water level",
    setWaterValve: "Set water valve",
    setAmount: "Set amount",
    setDensity: "Set density",
    setRecommendedAmount: "Set recommended amount",
    unsetRecommendedAmount: "Clear recommendation",
    setType: "Set type"
  };

  const friendlyArgumentNames = {
    setpoint: "Temperature",
    mode: "Mode",
    time: "Time",
    operationTime: "Cook time",
    power: "Power",
    level: "Level",
    speed: "Speed",
    defrost: "Defrost",
    rapidCooling: "Rapid cool",
    rapidFreezing: "Rapid freeze",
    volumeLevel: "Volume",
    uri: "Audio URL",
    foodType: "Food type",
    weight: "Weight",
    temperature: "Temperature",
    spinLevel: "Spin",
    soilLevel: "Soil",
    delayTime: "Delay minutes",
    waterLevel: "Water level",
    waterValve: "Water valve"
  };

  const applianceControlCapabilities = new Set([
    "switch",
    "samsungce.switch",
    "refrigeration",
    "thermostatCoolingSetpoint",
    "custom.thermostatSetpointControl",
    "custom.waterFilter",
    "custom.fridgeMode",
    "samsungce.powerCool",
    "samsungce.powerFreeze",
    "samsungce.sabbathMode",
    "samsungce.fridgePantryMode",
    "samsungce.foodDefrost",
    "samsungce.freezerConvertMode",
    "audioNotification",
    "samsungce.audioVolumeLevel",
    "ovenMode",
    "samsungce.ovenMode",
    "ovenSetpoint",
    "ovenOperatingState",
    "samsungce.ovenOperatingState",
    "samsungce.microwavePower",
    "samsungce.lamp",
    "samsungce.hoodFanSpeed",
    "washerOperatingState",
    "samsungce.washerOperatingState",
    "samsungce.washerCycle",
    "samsungce.washerDelayEnd",
    "samsungce.washerBubbleSoak",
    "samsungce.washerWaterLevel",
    "samsungce.washerWaterValve",
    "custom.supportedOptions",
    "custom.washerWaterTemperature",
    "custom.washerSpinLevel",
    "custom.washerSoilLevel",
    "custom.washerRinseCycles",
    "custom.washerAutoDetergent",
    "custom.washerAutoSoftener",
    "custom.dryerDryLevel",
    "custom.dryerWrinklePrevent",
    "samsungce.dryerDryingTemperature",
    "samsungce.dryerDryingTime",
    "samsungce.autoDispenseDetergent",
    "samsungce.autoDispenseSoftener"
  ]);

  const hiddenCommandCapabilities = new Set([
    "execute",
    "ocf",
    "refresh",
    "samsungce.softwareUpdate",
    "logTrigger",
    "demandResponseLoadControl",
    "sec.smartthingsHub",
    "samsungce.runestoneHomeContext",
    "samsungce.accessibility",
    "custom.deviceReportStateConfiguration",
    "samsungce.deviceReportStateConfiguration",
    "samsungce.fridgeFoodList",
    "samsungce.viewInside",
    "samsungce.definedRecipe",
    "samsungce.energyPlanner",
    "samsungce.welcomeMessage",
    "samsungce.washerCyclePreset",
    "samsungce.washerLabelScanCyclePreset"
  ]);

  const elements = {
    appShell: document.querySelector(".app-shell"),
    sidebarToggle: document.getElementById("sidebarToggle"),
    themeToggle: document.getElementById("themeToggle"),
    allCount: document.getElementById("allCount"),
    onCount: document.getElementById("onCount"),
    offCount: document.getElementById("offCount"),
    errorCount: document.getElementById("errorCount"),
    localCount: document.getElementById("localCount"),
    cloudCount: document.getElementById("cloudCount"),
    onlineTotal: document.getElementById("onlineTotal"),
    checkingTotal: document.getElementById("checkingTotal"),
    offlineErrorTotal: document.getElementById("offlineErrorTotal"),
    lastRefresh: document.getElementById("lastRefresh"),
    statusBanner: document.getElementById("statusBanner"),
    deviceGrid: document.getElementById("deviceGrid"),
    emptyState: document.getElementById("emptyState"),
    refreshButton: document.getElementById("refreshButton"),
    searchInput: document.getElementById("searchInput"),
    navButtons: Array.from(document.querySelectorAll(".nav-button")),
    sceneButtons: Array.from(document.querySelectorAll(".scene-button")),
    importDialog: document.getElementById("importDialog"),
    importProviderButtons: Array.from(document.querySelectorAll(".import-provider-button")),
    importProviderPanels: Array.from(document.querySelectorAll(".import-provider-panel")),
    openImportButton: document.getElementById("openImportButton"),
    closeImportButton: document.getElementById("closeImportButton"),
    importForm: document.getElementById("importForm"),
    merossEmail: document.getElementById("merossEmail"),
    merossPassword: document.getElementById("merossPassword"),
    merossMfa: document.getElementById("merossMfa"),
    runImportButton: document.getElementById("runImportButton"),
    reliabilityStatus: document.getElementById("reliabilityStatus"),
    reliabilityDetail: document.getElementById("reliabilityDetail"),
    runCloudRefreshButton: document.getElementById("runCloudRefreshButton"),
    repairDuplicatesButton: document.getElementById("repairDuplicatesButton"),
    smartThingsImportForm: document.getElementById("smartThingsImportForm"),
    smartThingsClientId: document.getElementById("smartThingsClientId"),
    smartThingsClientSecret: document.getElementById("smartThingsClientSecret"),
    smartThingsAuthorizationCode: document.getElementById("smartThingsAuthorizationCode"),
    smartThingsRedirectUri: document.getElementById("smartThingsRedirectUri"),
    smartThingsRefreshToken: document.getElementById("smartThingsRefreshToken"),
    smartThingsAccessToken: document.getElementById("smartThingsAccessToken"),
    smartThingsToken: document.getElementById("smartThingsToken"),
    excludeOverlaps: document.getElementById("excludeOverlaps"),
    smartThingsOAuthNote: document.getElementById("smartThingsOAuthNote"),
    startSmartThingsOAuthButton: document.getElementById("startSmartThingsOAuthButton"),
    runSmartThingsImportButton: document.getElementById("runSmartThingsImportButton"),
    nestImportForm: document.getElementById("nestImportForm"),
    nestProjectId: document.getElementById("nestProjectId"),
    nestClientId: document.getElementById("nestClientId"),
    nestClientSecret: document.getElementById("nestClientSecret"),
    nestAuthorizationCode: document.getElementById("nestAuthorizationCode"),
    nestRefreshToken: document.getElementById("nestRefreshToken"),
    nestAccessToken: document.getElementById("nestAccessToken"),
    runNestImportButton: document.getElementById("runNestImportButton"),
    ringImportForm: document.getElementById("ringImportForm"),
    ringEmail: document.getElementById("ringEmail"),
    ringPassword: document.getElementById("ringPassword"),
    ringOtp: document.getElementById("ringOtp"),
    runRingImportButton: document.getElementById("runRingImportButton"),
    yaleImportForm: document.getElementById("yaleImportForm"),
    yaleEmail: document.getElementById("yaleEmail"),
    yalePassword: document.getElementById("yalePassword"),
    yaleVerificationCode: document.getElementById("yaleVerificationCode"),
    yaleAccessToken: document.getElementById("yaleAccessToken"),
    yaleBrand: document.getElementById("yaleBrand"),
    runYaleImportButton: document.getElementById("runYaleImportButton"),
    cudyAddForm: document.getElementById("cudyAddForm"),
    cudyName: document.getElementById("cudyName"),
    cudyHost: document.getElementById("cudyHost"),
    cudyModel: document.getElementById("cudyModel"),
    cudyUsername: document.getElementById("cudyUsername"),
    cudyPassword: document.getElementById("cudyPassword"),
    runCudyAddButton: document.getElementById("runCudyAddButton"),
    printerAddForm: document.getElementById("printerAddForm"),
    printerName: document.getElementById("printerName"),
    printerHost: document.getElementById("printerHost"),
    printerModel: document.getElementById("printerModel"),
    printerCommunity: document.getElementById("printerCommunity"),
    printerDiscoverySubnet: document.getElementById("printerDiscoverySubnet"),
    printerDiscoveryStatus: document.getElementById("printerDiscoveryStatus"),
    discoverPrintersButton: document.getElementById("discoverPrintersButton"),
    discoveredPrinters: document.getElementById("discoveredPrinters"),
    runPrinterAddButton: document.getElementById("runPrinterAddButton"),
    deviceDetailDialog: document.getElementById("deviceDetailDialog"),
    closeDeviceDetailButton: document.getElementById("closeDeviceDetailButton"),
    renameDeviceButton: document.getElementById("renameDeviceButton"),
    removeDeviceButton: document.getElementById("removeDeviceButton"),
    showDeviceDetailsToggle: document.getElementById("showDeviceDetailsToggle"),
    showCameraLiveToggle: document.getElementById("showCameraLiveToggle"),
    deviceDetailIcon: document.getElementById("deviceDetailIcon"),
    deviceDetailEyebrow: document.getElementById("deviceDetailEyebrow"),
    deviceDetailTitle: document.getElementById("deviceDetailTitle"),
    deviceDetailContent: document.getElementById("deviceDetailContent"),
    cudyRebootDialog: document.getElementById("cudyRebootDialog"),
    cudyRebootForm: document.getElementById("cudyRebootForm"),
    cudyRebootTarget: document.getElementById("cudyRebootTarget"),
    cudyRebootNote: document.getElementById("cudyRebootNote"),
    closeCudyRebootButton: document.getElementById("closeCudyRebootButton"),
    cancelCudyRebootButton: document.getElementById("cancelCudyRebootButton")
  };

  applyTheme();
  applySidebarCollapse();
  if (elements.showCameraLiveToggle) {
    elements.showCameraLiveToggle.checked = state.showLiveCameraTiles;
  }
  setSmartThingsRedirectDefault();

  elements.themeToggle.addEventListener("click", function () {
    state.isDarkMode = !state.isDarkMode;
    window.localStorage.setItem("sentinel.theme", state.isDarkMode ? "dark" : "light");
    applyTheme();
  });

  elements.sidebarToggle.addEventListener("click", function () {
    state.isSidebarCollapsed = !state.isSidebarCollapsed;
    window.localStorage.setItem("sentinel.sidebarCollapsed", String(state.isSidebarCollapsed));
    applySidebarCollapse();
  });

  elements.refreshButton.addEventListener("click", function () {
    unlockDashboardAudio();
    refreshDashboard({ showBanner: true });
  });
  document.addEventListener("pointerdown", unlockDashboardAudio, { once: true });

  elements.searchInput.addEventListener("input", function (event) {
    state.search = event.target.value.trim().toLowerCase();
    render();
  });

  elements.navButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      state.filter = button.dataset.filter;
      elements.navButtons.forEach(function (item) {
        item.classList.toggle("is-active", item === button);
      });
      render();
    });
  });

  elements.sceneButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      runScene(button.dataset.scene);
    });
  });
  if (elements.runCloudRefreshButton) {
    elements.runCloudRefreshButton.addEventListener("click", runCloudRefresh);
  }
  if (elements.repairDuplicatesButton) {
    elements.repairDuplicatesButton.addEventListener("click", repairDuplicates);
  }

  elements.openImportButton.addEventListener("click", function () {
    showImportProvider("meross");
    elements.importDialog.showModal();
  });

  elements.closeImportButton.addEventListener("click", function () {
    elements.importDialog.close();
  });

  elements.closeDeviceDetailButton.addEventListener("click", function () {
    elements.deviceDetailDialog.close();
  });
  elements.renameDeviceButton.addEventListener("click", function () {
    const deviceId = Number(elements.deviceDetailDialog.dataset.deviceId);
    if (deviceId) {
      renameDevice(deviceId);
    }
  });
  elements.removeDeviceButton.addEventListener("click", function () {
    const deviceId = Number(elements.deviceDetailDialog.dataset.deviceId);
    if (deviceId) {
      removeDevice(deviceId);
    }
  });
  elements.showDeviceDetailsToggle.addEventListener("change", function (event) {
    state.showAdminDeviceDetails = event.target.checked;
    render();
    if (elements.deviceDetailDialog.open) {
      const currentDevice = state.devices.find(function (item) {
        return item.id === Number(elements.deviceDetailDialog.dataset.deviceId);
      });
      if (currentDevice) {
        renderDeviceDetail(currentDevice);
      }
    }
  });
  if (elements.showCameraLiveToggle) {
    elements.showCameraLiveToggle.addEventListener("change", function (event) {
      state.showLiveCameraTiles = event.target.checked;
      window.localStorage.setItem("sentinel.showLiveCameraTiles", String(state.showLiveCameraTiles));
      render();
    });
  }
  elements.deviceDetailDialog.addEventListener("close", function () {
    closeAllRingWebRtcFeeds();
  });
  elements.closeCudyRebootButton.addEventListener("click", function () {
    elements.cudyRebootDialog.close("cancel");
  });
  elements.cancelCudyRebootButton.addEventListener("click", function () {
    elements.cudyRebootDialog.close("cancel");
  });
  elements.importProviderButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      showImportProvider(button.dataset.importProvider || "meross");
    });
  });

  elements.importForm.addEventListener("submit", handleImportSubmit);
  elements.smartThingsImportForm.addEventListener("submit", handleSmartThingsImportSubmit);
  elements.startSmartThingsOAuthButton.addEventListener("click", handleSmartThingsOAuthStart);
  elements.nestImportForm.addEventListener("submit", handleNestImportSubmit);
  elements.ringImportForm.addEventListener("submit", handleRingImportSubmit);
  elements.yaleImportForm.addEventListener("submit", handleYaleImportSubmit);
  elements.cudyAddForm.addEventListener("submit", handleCudyAddSubmit);
  elements.printerAddForm.addEventListener("submit", handlePrinterAddSubmit);
  elements.discoverPrintersButton.addEventListener("click", discoverPrinters);
  elements.discoveredPrinters.addEventListener("change", handleDiscoveredPrinterSelect);

  function showImportProvider(provider) {
    const activeProvider = provider || "meross";
    const labels = {
      meross: "Import Meross devices",
      smartthings: "Add SmartThings devices",
      nest: "Add Nest thermostats",
      ring: "Add Ring devices",
      yale: "Add Yale locks",
      cudy: "Add Cudy router",
      printers: "Add printer monitor"
    };
    elements.importDialog.dataset.importProvider = activeProvider;
    elements.importProviderButtons.forEach(function (button) {
      const isActive = button.dataset.importProvider === activeProvider;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-selected", isActive ? "true" : "false");
    });
    elements.importProviderPanels.forEach(function (panel) {
      panel.hidden = panel.dataset.importPanel !== activeProvider;
    });
    const title = elements.importForm.querySelector(".modal-header h2");
    if (title) {
      title.textContent = labels[activeProvider] || "Import devices";
    }
  }

  function applySidebarCollapse() {
    elements.appShell.classList.toggle("is-sidebar-collapsed", state.isSidebarCollapsed);
    elements.sidebarToggle.setAttribute("aria-expanded", state.isSidebarCollapsed ? "false" : "true");
    elements.sidebarToggle.setAttribute("aria-label", state.isSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar");
    elements.sidebarToggle.setAttribute("title", state.isSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar");
  }

  function applyTheme() {
    document.body.classList.toggle("is-dark-mode", state.isDarkMode);
    elements.appShell.classList.toggle("is-dark-mode", state.isDarkMode);
    elements.themeToggle.setAttribute("aria-label", state.isDarkMode ? "Use light mode" : "Use dark mode");
    elements.themeToggle.setAttribute("title", state.isDarkMode ? "Use light mode" : "Use dark mode");
    const icon = elements.themeToggle.querySelector("span");
    if (icon) {
      icon.textContent = state.isDarkMode ? "☀" : "☾";
    }
  }

  refreshDashboard({ showBanner: false });
  loadReliabilityHealth();
  window.setInterval(function () {
    refreshDashboard({ showBanner: false });
  }, 30000);
  window.setInterval(function () {
    loadReliabilityHealth();
  }, 60000);
  window.setInterval(function () {
    pollRingAlerts();
  }, 4000);
  window.setInterval(function () {
    refreshRingTileSnapshots();
    refreshIpCameraTileSnapshots();
  }, 60000);

  async function refreshDashboard(options) {
    if (state.isRefreshing) {
      return;
    }

    state.isRefreshing = true;
    elements.refreshButton.disabled = true;

    try {
      const devices = await requestJson("/devices");
      state.devices = devices.filter(function (device) {
        return device.is_enabled;
      });
      await refreshDeviceStates(state.devices);
      pollRingAlerts();
      elements.lastRefresh.textContent = new Date().toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit"
      });
      if (options.showBanner) {
        showBanner("Device states refreshed.", "success");
      }
    } catch (error) {
      showBanner(error.message || "Could not refresh devices.", "error");
    } finally {
      state.isRefreshing = false;
      elements.refreshButton.disabled = false;
      render();
    }
  }

  async function loadReliabilityHealth() {
    if (!elements.reliabilityStatus || !elements.reliabilityDetail) {
      return;
    }
    try {
      const health = await requestJson("/reliability/health");
      renderReliabilityHealth(health);
    } catch (error) {
      elements.reliabilityStatus.textContent = "Needs attention";
      elements.reliabilityDetail.textContent = error.message || "Could not load reliability health.";
    }
  }

  function renderReliabilityHealth(health) {
    const errors = (health.credentials || []).filter(function (item) {
      return item.status === "error";
    });
    const duplicates = health.duplicate_candidates || [];
    const refresh = health.background_refresh || {};
    const parts = [];

    if (refresh.running) {
      parts.push("Cloud refresh is running");
    } else if (refresh.last_finished_at) {
      parts.push("Cloud refresh ran " + formatRelativeTime(refresh.last_finished_at));
    } else {
      parts.push("Cloud refresh is waiting");
    }

    if (errors.length) {
      parts.push(errors.length + " credential issue" + (errors.length === 1 ? "" : "s"));
    }
    if (duplicates.length) {
      parts.push(duplicates.length + " duplicate candidate" + (duplicates.length === 1 ? "" : "s"));
    }

    elements.reliabilityStatus.textContent = health.status === "ok" ? "Healthy" : "Needs attention";
    elements.reliabilityDetail.textContent = parts.join(". ") + ".";
    if (elements.runCloudRefreshButton) {
      elements.runCloudRefreshButton.disabled = Boolean(refresh.running || state.isCloudRefreshRunning);
    }
    if (elements.repairDuplicatesButton) {
      elements.repairDuplicatesButton.disabled = state.isRepairingDuplicates;
    }
  }

  async function runCloudRefresh() {
    if (state.isCloudRefreshRunning) {
      return;
    }
    state.isCloudRefreshRunning = true;
    if (elements.runCloudRefreshButton) {
      elements.runCloudRefreshButton.disabled = true;
      elements.runCloudRefreshButton.textContent = "Refreshing...";
    }
    try {
      const health = await requestJson("/reliability/cloud-refresh", { method: "POST" });
      renderReliabilityHealth(health);
      showBanner("Cloud devices refreshed in the background cache.", "success");
      await refreshDashboard({ showBanner: false });
    } catch (error) {
      showBanner(error.message || "Cloud refresh failed.", "error");
      await loadReliabilityHealth();
    } finally {
      state.isCloudRefreshRunning = false;
      if (elements.runCloudRefreshButton) {
        elements.runCloudRefreshButton.textContent = "Refresh cloud";
      }
    }
  }

  async function repairDuplicates() {
    if (state.isRepairingDuplicates) {
      return;
    }
    state.isRepairingDuplicates = true;
    if (elements.repairDuplicatesButton) {
      elements.repairDuplicatesButton.disabled = true;
      elements.repairDuplicatesButton.textContent = "Repairing...";
    }
    try {
      const result = await requestJson("/maintenance/repair-duplicates", { method: "POST" });
      showBanner(result.note || "Duplicate repair complete.", "success");
      await refreshDashboard({ showBanner: false });
      await loadReliabilityHealth();
    } catch (error) {
      showBanner(error.message || "Duplicate repair failed.", "error");
    } finally {
      state.isRepairingDuplicates = false;
      if (elements.repairDuplicatesButton) {
        elements.repairDuplicatesButton.textContent = "Repair duplicates";
      }
    }
  }

  function formatRelativeTime(value) {
    const timestamp = Date.parse(value);
    if (!timestamp) {
      return "recently";
    }
    const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
    if (seconds < 60) {
      return "just now";
    }
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) {
      return minutes + " min ago";
    }
    const hours = Math.round(minutes / 60);
    return hours + " hr ago";
  }

  async function refreshDeviceStates(devices) {
    const liveDevices = devices.filter(shouldRefreshLiveOnDashboard);
    const liveIds = new Set(liveDevices.map(function (device) {
      return device.id;
    }));
    devices.forEach(function (device) {
      const cached = cachedDeviceState(device);
      state.states.set(device.id, liveIds.has(device.id) ? refreshingDeviceState(device, cached) : cached || { status: "loading", isOn: null, error: "", checkedAt: null });
    });
    render();

    await Promise.allSettled(liveDevices.map(async function (device) {
      try {
        const result = await requestJson("/devices/" + device.id + "/state", {
          timeoutMs: stateTimeoutMs(device)
        });
        state.states.set(device.id, checkedDeviceState({
          status: stateStatus(device, result),
          isOn: result.is_on,
          isOpen: result.is_open,
          luminance: result.luminance,
          appliance: result.appliance,
          raw: result.raw,
          error: ""
        }));
      } catch (error) {
        const fallback = cachedDeviceState(device, (error.message || "State unavailable") + "; showing last known state.");
        state.states.set(device.id, fallback || checkedDeviceState({
          status: "error",
          isOn: null,
          error: error.message || "State unavailable"
        }));
      } finally {
        render();
      }
    }));
  }

  function shouldRefreshLiveOnDashboard(device) {
    if (isSmartThings(device)) {
      const cached = cachedDeviceState(device);
      return Boolean(cached?.appliance);
    }
    return !isNest(device);
  }

  function stateTimeoutMs(device) {
    return isPrinter(device) ? printerStateRefreshTimeoutMs : stateRefreshTimeoutMs;
  }

  function cachedDeviceState(device, errorMessage) {
    if (!device.last_state) {
      return null;
    }

    try {
      const result = JSON.parse(device.last_state);
      return {
        status: stateStatus(device, result),
        isOn: result.is_on,
        isOpen: result.is_open,
        luminance: result.luminance,
        appliance: result.appliance,
        raw: result.raw,
        error: errorMessage || "",
        checkedAt: device.updated_at || null
      };
    } catch (error) {
      return null;
    }
  }

  function checkedDeviceState(deviceState, checkedAt) {
    return Object.assign({}, deviceState, { checkedAt: checkedAt || new Date().toISOString() });
  }

  function refreshingDeviceState(device, existingState) {
    const existing = existingState || state.states.get(device.id) || cachedDeviceState(device);
    if (existing) {
      return Object.assign({}, existing, {
        status: "loading",
        error: "",
        checkedAt: existing.checkedAt || existingCheckedAt(device.id)
      });
    }
    return { status: "loading", isOn: null, error: "", checkedAt: existingCheckedAt(device.id) };
  }

  function existingCheckedAt(deviceId) {
    const current = state.states.get(deviceId);
    return current ? current.checkedAt || null : null;
  }

  async function handleImportSubmit(event) {
    event.preventDefault();

    const body = {
      email: elements.merossEmail.value.trim(),
      password: elements.merossPassword.value,
      save_devices: true
    };

    if (elements.merossMfa.value.trim()) {
      body.mfa_code = elements.merossMfa.value.trim();
    }

    elements.runImportButton.disabled = true;
    elements.runImportButton.textContent = "Importing...";

    try {
      const result = await requestJson("/setup/meross-cloud/import", {
        method: "POST",
        body: JSON.stringify(body)
      });
      const savedCount = result.imported.filter(function (item) {
        return item.saved;
      }).length;
      elements.importDialog.close();
      elements.importForm.reset();
      showBanner("Imported " + savedCount + " Meross device records.", "success");
      await refreshDashboard({ showBanner: false });
    } catch (error) {
      showBanner(error.message || "Import failed.", "error");
    } finally {
      elements.runImportButton.disabled = false;
      elements.runImportButton.textContent = "Import";
    }
  }

  async function handleSmartThingsImportSubmit(event) {
    event.preventDefault();

    const body = {
      save_devices: true,
      exclude_overlaps: elements.excludeOverlaps.checked
    };
    [
      ["client_id", elements.smartThingsClientId],
      ["client_secret", elements.smartThingsClientSecret],
      ["authorization_code", elements.smartThingsAuthorizationCode],
      ["redirect_uri", elements.smartThingsRedirectUri],
      ["refresh_token", elements.smartThingsRefreshToken],
      ["access_token", elements.smartThingsAccessToken],
      ["token", elements.smartThingsToken]
    ].forEach(function (entry) {
      const value = entry[1].value.trim();
      if (value) {
        body[entry[0]] = value;
      }
    });

    elements.runSmartThingsImportButton.disabled = true;
    elements.runSmartThingsImportButton.textContent = "Importing...";

    try {
      const result = await requestJson("/setup/smartthings/import", {
        method: "POST",
        body: JSON.stringify(body)
      });
      elements.importDialog.close();
      elements.smartThingsImportForm.reset();
      elements.excludeOverlaps.checked = true;
      setSmartThingsRedirectDefault();
      showBanner(
        "Imported " + result.imported.length + " SmartThings devices; skipped " + result.skipped.length + " overlap(s).",
        "success"
      );
      await refreshDashboard({ showBanner: false });
    } catch (error) {
      showBanner(error.message || "SmartThings import failed.", "error");
    } finally {
      elements.runSmartThingsImportButton.disabled = false;
      elements.runSmartThingsImportButton.textContent = "Import SmartThings";
    }
  }

  async function handleSmartThingsOAuthStart() {
    elements.smartThingsOAuthNote.textContent = "Starting SmartThings sign-in...";
    const body = {
      client_id: elements.smartThingsClientId.value.trim(),
      client_secret: elements.smartThingsClientSecret.value.trim(),
      redirect_uri: elements.smartThingsRedirectUri.value.trim(),
      save_devices: true,
      exclude_overlaps: elements.excludeOverlaps.checked
    };

    if (!body.client_id || !body.client_secret) {
      elements.smartThingsOAuthNote.textContent = "Enter the SmartThings OAuth client ID and secret first, then click Sign in with SmartThings.";
      return;
    }

    elements.startSmartThingsOAuthButton.disabled = true;
    elements.startSmartThingsOAuthButton.textContent = "Opening sign-in...";

    try {
      const result = await requestJson("/setup/smartthings/oauth/start", {
        method: "POST",
        body: JSON.stringify(body)
      });
      window.location.href = result.authorization_url;
    } catch (error) {
      elements.smartThingsOAuthNote.textContent = error.message || "Could not start SmartThings sign-in.";
      elements.startSmartThingsOAuthButton.disabled = false;
      elements.startSmartThingsOAuthButton.textContent = "Sign in with SmartThings";
    }
  }

  function smartThingsRedirectDefault() {
    return window.location.origin + "/setup/smartthings/oauth/callback";
  }

  function setSmartThingsRedirectDefault() {
    if (elements.smartThingsRedirectUri && !elements.smartThingsRedirectUri.value.trim()) {
      elements.smartThingsRedirectUri.value = smartThingsRedirectDefault();
    }
  }

  async function handleNestImportSubmit(event) {
    event.preventDefault();

    const body = {
      project_id: elements.nestProjectId.value.trim(),
      save_devices: true,
      exclude_overlaps: true
    };
    [
      ["client_id", elements.nestClientId],
      ["client_secret", elements.nestClientSecret],
      ["authorization_code", elements.nestAuthorizationCode],
      ["refresh_token", elements.nestRefreshToken],
      ["access_token", elements.nestAccessToken]
    ].forEach(function (item) {
      const value = item[1].value.trim();
      if (value) {
        body[item[0]] = value;
      }
    });

    elements.runNestImportButton.disabled = true;
    elements.runNestImportButton.textContent = "Importing...";

    try {
      const result = await requestJson("/setup/nest/import", {
        method: "POST",
        body: JSON.stringify(body)
      });
      elements.importDialog.close();
      elements.nestImportForm.reset();
      showBanner(
        "Imported " + result.imported.length + " Nest thermostats; skipped " + result.skipped.length + " overlap(s).",
        "success"
      );
      await refreshDashboard({ showBanner: false });
    } catch (error) {
      showBanner(error.message || "Nest import failed.", "error");
    } finally {
      elements.runNestImportButton.disabled = false;
      elements.runNestImportButton.textContent = "Import Nest";
    }
  }

  async function handleRingImportSubmit(event) {
    event.preventDefault();

    const body = {
      email: elements.ringEmail.value.trim(),
      password: elements.ringPassword.value,
      save_devices: true,
      exclude_overlaps: true
    };
    if (elements.ringOtp.value.trim()) {
      body.otp_code = elements.ringOtp.value.trim();
    }

    elements.runRingImportButton.disabled = true;
    elements.runRingImportButton.textContent = "Importing...";

    try {
      const result = await requestJson("/setup/ring/import", {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (result.requires_2fa) {
        showBanner("Ring needs a 2FA code. Enter it and run Ring import again.", "error");
        return;
      }
      elements.importDialog.close();
      elements.ringImportForm.reset();
      showBanner(
        "Imported " + result.imported.length + " Ring devices; skipped " + result.skipped.length + " overlap(s).",
        "success"
      );
      await refreshDashboard({ showBanner: false });
    } catch (error) {
      showBanner(error.message || "Ring import failed.", "error");
    } finally {
      elements.runRingImportButton.disabled = false;
      elements.runRingImportButton.textContent = "Import Ring";
    }
  }

  async function handleYaleImportSubmit(event) {
    event.preventDefault();

    const body = {
      brand: elements.yaleBrand.value,
      save_devices: true,
      exclude_overlaps: true
    };
    if (elements.yaleAccessToken.value.trim()) {
      body.access_token = elements.yaleAccessToken.value.trim();
    } else {
      body.email = elements.yaleEmail.value.trim();
      body.password = elements.yalePassword.value;
      body.login_method = "email";
      if (elements.yaleVerificationCode.value.trim()) {
        body.verification_code = elements.yaleVerificationCode.value.trim();
      }
    }

    elements.runYaleImportButton.disabled = true;
    elements.runYaleImportButton.textContent = "Importing...";

    try {
      const result = await requestJson("/setup/yale/import", {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (result.requires_validation) {
        showBanner("Yale sent a verification code. Enter it and run Yale import again.", "error");
        return;
      }
      elements.importDialog.close();
      elements.yaleImportForm.reset();
      showBanner(
        "Imported " + result.imported.length + " Yale locks; skipped " + result.skipped.length + " overlap(s).",
        "success"
      );
      await refreshDashboard({ showBanner: false });
    } catch (error) {
      showBanner(error.message || "Yale import failed.", "error");
    } finally {
      elements.runYaleImportButton.disabled = false;
      elements.runYaleImportButton.textContent = "Import Yale";
    }
  }

  async function handleCudyAddSubmit(event) {
    event.preventDefault();

    const name = elements.cudyName.value.trim();
    const host = cleanRouterHost(elements.cudyHost.value);
    const model = elements.cudyModel.value.trim();
    const username = elements.cudyUsername.value.trim() || "root";
    const password = elements.cudyPassword.value;

    if (!name || !host) {
      showBanner("Router name and address are required.", "error");
      return;
    }

    const body = {
      name: name,
      brand: "cudy",
      model: model || null,
      host: host,
      device_type: "router",
      channel: 0,
      is_enabled: true
    };

    if (password) {
      body.device_key = JSON.stringify({ username: username, password: password });
    }

    elements.runCudyAddButton.disabled = true;
    elements.runCudyAddButton.textContent = "Adding...";

    try {
      const result = await requestJson("/devices", {
        method: "POST",
        body: JSON.stringify(body)
      });
      elements.importDialog.close();
      elements.cudyAddForm.reset();
      elements.cudyName.value = "Main Cudy Router";
      elements.cudyHost.value = "192.168.10.1";
      elements.cudyUsername.value = "root";
      showBanner("Added " + result.name + ".", "success");
      await refreshDashboard({ showBanner: false });
    } catch (error) {
      showBanner(error.message || "Could not add Cudy router.", "error");
    } finally {
      elements.runCudyAddButton.disabled = false;
      elements.runCudyAddButton.textContent = "Add Cudy router";
    }
  }

  async function handlePrinterAddSubmit(event) {
    event.preventDefault();

    const name = elements.printerName.value.trim();
    const host = cleanRouterHost(elements.printerHost.value);
    const model = elements.printerModel.value.trim();
    const community = elements.printerCommunity.value.trim() || "public";

    if (!name || !host) {
      showBanner("Printer name and address are required.", "error");
      return;
    }

    const body = {
      name: name,
      brand: "printer",
      model: model || null,
      host: host,
      device_type: "printer",
      channel: 0,
      is_enabled: true,
      device_key: JSON.stringify({ community: community })
    };

    elements.runPrinterAddButton.disabled = true;
    elements.runPrinterAddButton.textContent = "Adding...";

    try {
      const result = await requestJson("/devices", {
        method: "POST",
        body: JSON.stringify(body)
      });
      elements.importDialog.close();
      elements.printerAddForm.reset();
      elements.printerCommunity.value = "public";
      showBanner("Added " + result.name + ".", "success");
      await refreshDashboard({ showBanner: false });
    } catch (error) {
      showBanner(error.message || "Could not add printer.", "error");
    } finally {
      elements.runPrinterAddButton.disabled = false;
      elements.runPrinterAddButton.textContent = "Add printer";
    }
  }

  async function discoverPrinters() {
    if (elements.discoverPrintersButton.disabled) {
      return;
    }

    const subnets = elements.printerDiscoverySubnet.value.split(",").map(function (value) {
      return value.trim();
    }).filter(Boolean);
    const directHost = cleanRouterHost(elements.printerHost.value || "");
    if (directHost && !subnets.includes(directHost) && !subnets.includes(directHost + "/32")) {
      subnets.unshift(directHost);
    }
    const body = {
      timeout_seconds: 3,
      subnets: subnets,
      scan_routed_subnets: true,
      community: elements.printerCommunity.value.trim() || "public",
      model_hint: elements.printerModel.value.trim() || null
    };

    elements.discoverPrintersButton.disabled = true;
    elements.discoverPrintersButton.textContent = "Searching...";
    elements.discoveredPrinters.innerHTML = '<option value="">Searching for printers...</option>';
    elements.printerDiscoveryStatus.textContent = discoveryStatusText(subnets);

    try {
      const result = await requestJson("/api/printers/discover", {
        method: "POST",
        body: JSON.stringify(body)
      });
      renderDiscoveredPrinters(result.printers || []);
      const scanned = (result.scanned_subnets || []).join(", ");
      if (result.printers && result.printers.length) {
        showBanner("Found " + result.printers.length + " printer candidate" + (result.printers.length === 1 ? "" : "s") + ".", "success");
        elements.printerDiscoveryStatus.textContent = "Search complete. Select a result below, then add it to the dashboard.";
      } else {
        showBanner("No printers answered yet" + (scanned ? " while scanning " + scanned : "") + ".", "error");
        elements.printerDiscoveryStatus.textContent = "Search complete. No printer answered from this Sentinel machine.";
      }
    } catch (error) {
      elements.discoveredPrinters.innerHTML = '<option value="">Discovery failed</option>';
      elements.printerDiscoveryStatus.textContent = error.message || "Printer discovery failed.";
      showBanner(error.message || "Printer discovery failed.", "error");
    } finally {
      elements.discoverPrintersButton.disabled = false;
      elements.discoverPrintersButton.textContent = "Discover printers";
    }
  }

  function discoveryStatusText(subnets) {
    const targets = subnets.length ? subnets.join(", ") : "the current local network";
    return "Searching " + targets + " with CUPS, Bonjour, SNMP, IPP, and raw printer port checks...";
  }

  function renderDiscoveredPrinters(printers) {
    elements.discoveredPrinters.innerHTML = '<option value="">Select a discovered printer</option>';
    printers.forEach(function (printer, index) {
      const option = document.createElement("option");
      option.value = String(index);
      option.dataset.host = printer.host || "";
      option.dataset.name = printer.name || "";
      option.dataset.model = printer.model || "";
      option.dataset.snmp = printer.snmp_supported ? "true" : "false";
      option.textContent = discoveredPrinterLabel(printer);
      elements.discoveredPrinters.appendChild(option);
    });
  }

  function discoveredPrinterLabel(printer) {
    const parts = [
      printer.name || printer.model || printer.host || "Printer",
      printer.host,
      printer.model,
      printer.snmp_supported ? "SNMP ready" : printer.status || "Found"
    ].filter(Boolean);
    if (printer.ink_count) {
      parts.push(printer.ink_count + " supplies");
    }
    return parts.join(" · ");
  }

  function handleDiscoveredPrinterSelect(event) {
    const option = event.target.selectedOptions[0];
    if (!option || !option.value) {
      return;
    }
    if (option.dataset.name) {
      elements.printerName.value = option.dataset.name;
    }
    if (option.dataset.host) {
      elements.printerHost.value = option.dataset.host;
    }
    if (option.dataset.model) {
      setPrinterModel(option.dataset.model);
    }
  }

  function setPrinterModel(model) {
    const matching = Array.from(elements.printerModel.options).find(function (option) {
      return option.value === model;
    });
    if (matching) {
      elements.printerModel.value = model;
      return;
    }
    elements.printerModel.value = "";
  }

  function cleanRouterHost(value) {
    const trimmed = value.trim();
    if (!trimmed) {
      return "";
    }
    try {
      const parsed = new URL(trimmed.includes("://") ? trimmed : "http://" + trimmed);
      return parsed.host;
    } catch (error) {
      return trimmed.replace(/^https?:\/\//i, "").replace(/\/+$/, "");
    }
  }

  async function runDeviceAction(deviceId, action) {
    const existing = state.states.get(deviceId) || {};
    state.states.set(deviceId, Object.assign({}, existing, { status: "loading", error: "" }));
    render();

    try {
      const result = await requestJson("/devices/" + deviceId + "/" + action, {
        method: "POST"
      });
      state.states.set(deviceId, checkedDeviceState({
        status: result.is_open !== null && result.is_open !== undefined ? (result.is_open ? "on" : "off") : (result.is_on ? "on" : "off"),
        isOn: result.is_on,
        isOpen: result.is_open,
        luminance: result.luminance,
        appliance: existing.appliance,
        raw: existing.raw,
        error: ""
      }));
      showBanner(result.message || "Command completed.", "success");
    } catch (error) {
      state.states.set(deviceId, checkedDeviceState({
        status: "error",
        isOn: null,
        error: error.message || "Command failed"
      }));
      showBanner(error.message || "Command failed.", "error");
    } finally {
      render();
    }
  }

  async function setBrightness(deviceId, luminance) {
    const existing = state.states.get(deviceId) || {};
    state.states.set(deviceId, Object.assign({}, existing, { status: "loading", error: "" }));
    render();

    try {
      const result = await requestJson("/devices/" + deviceId + "/brightness", {
        method: "POST",
        body: JSON.stringify({ luminance: Number(luminance) })
      });
      state.states.set(deviceId, checkedDeviceState({
        status: "on",
        isOn: true,
        isOpen: existing.isOpen,
        luminance: result.luminance,
        appliance: existing.appliance,
        raw: existing.raw,
        error: ""
      }));
      showBanner(result.message || "Brightness updated.", "success");
    } catch (error) {
      state.states.set(deviceId, checkedDeviceState({
        status: "error",
        isOn: null,
        isOpen: existing.isOpen,
        luminance: existing.luminance,
        error: error.message || "Brightness update failed"
      }));
      showBanner(error.message || "Brightness update failed.", "error");
    } finally {
      render();
    }
  }

  async function runScene(scene) {
    const targets = sceneTargets(scene);
    if (!targets.length) {
      showBanner("No matching devices for that scene.", "error");
      return;
    }

    elements.sceneButtons.forEach(function (button) {
      button.disabled = true;
    });
    showBanner("Running scene...", "success");

    const results = await Promise.allSettled(targets.map(function (target) {
      return runSceneAction(target.device, target.action);
    }));
    const failures = results.filter(function (result) {
      return result.status === "rejected";
    }).length;

    elements.sceneButtons.forEach(function (button) {
      button.disabled = false;
    });
    render();

    if (failures) {
      showBanner((targets.length - failures) + " scene actions completed, " + failures + " failed.", "error");
    } else {
      showBanner(sceneLabel(scene) + " complete.", "success");
    }
  }

  function sceneTargets(scene) {
    if (scene === "lights-off") {
      return controllableLightDevices().map(function (device) {
        return { device: device, action: "turn-off" };
      });
    }
    if (scene === "night") {
      return controllableLightDevices().map(function (device) {
        return { device: device, action: "turn-off" };
      });
    }
    if (scene === "away") {
      const lightTargets = controllableLightDevices().map(function (device) {
        return { device: device, action: "turn-off" };
      });
      const lockTargets = state.devices.filter(isLock).map(function (device) {
        return { device: device, action: "lock" };
      });
      const garageTargets = state.devices.filter(isGarage).map(function (device) {
        return { device: device, action: "close" };
      });
      return lightTargets.concat(lockTargets, garageTargets);
    }
    return [];
  }

  function controllableLightDevices() {
    return state.devices.filter(function (device) {
      return (isSimpleLightSwitch(device) || isDimmer(device)) && !isGarage(device);
    });
  }

  async function runSceneAction(device, action) {
    const existing = state.states.get(device.id) || {};
    state.states.set(device.id, Object.assign({}, existing, { status: "loading", error: "" }));
    render();

    const result = await requestJson("/devices/" + device.id + "/" + action, {
      method: "POST",
      timeoutMs: 6000
    });
    state.states.set(device.id, checkedDeviceState({
      status: result.is_open !== null && result.is_open !== undefined ? (result.is_open ? "on" : "off") : (result.is_on ? "on" : "off"),
      isOn: result.is_on,
      isOpen: result.is_open,
      luminance: existing.luminance,
      appliance: existing.appliance,
      raw: existing.raw,
      error: ""
    }));
  }

  function sceneLabel(scene) {
    if (scene === "lights-off") {
      return "Turn off all lights";
    }
    if (scene === "night") {
      return "Night mode";
    }
    if (scene === "away") {
      return "Away mode";
    }
    return "Scene";
  }

  function render() {
    const rows = getFilteredDevices();
    const counts = getCounts();

    elements.allCount.textContent = String(state.devices.length);
    elements.onCount.textContent = String(counts.on);
    elements.offCount.textContent = String(counts.off);
    elements.errorCount.textContent = String(counts.errors);
    elements.localCount.textContent = String(counts.local);
    elements.cloudCount.textContent = String(counts.cloud);
    elements.onlineTotal.textContent = String(counts.online);
    elements.checkingTotal.textContent = String(counts.checking);
    elements.offlineErrorTotal.textContent = String(counts.offlineError);

    const existingCards = new Map(Array.from(elements.deviceGrid.children).map(function (card) {
      return [Number(card.dataset.deviceId || 0), card];
    }).filter(function (entry) {
      return entry[0];
    }));
    const preservedLiveCameraIds = new Set();
    const cards = rows.map(function (device) {
      const existingCard = existingCards.get(device.id);
      if (shouldPreserveLiveCameraCard(device, existingCard)) {
        preservedLiveCameraIds.add(device.id);
        return existingCard;
      }
      return renderDeviceCard(device);
    });
    cleanupCameraTileLiveViews(preservedLiveCameraIds);
    elements.deviceGrid.replaceChildren(...cards);

    elements.emptyState.hidden = rows.length > 0;
  }

  function renderDeviceCard(device) {
    const deviceState = state.states.get(device.id) || { status: "loading", isOn: null, error: "" };
    const tileApplianceType = dashboardApplianceType(device, deviceState);
    const isCameraLandscape = isCameraLandscapeTile(device);
    const card = document.createElement("article");
    card.className = "device-card";
    card.dataset.deviceId = String(device.id);
    if (isAppliance(device) || isNest(device) || isPrinter(device)) {
      card.classList.add("appliance-card");
    }
    if (tileApplianceType === "refrigerator") {
      card.classList.add("fridge-dashboard-card");
    }
    if (tileApplianceType === "oven") {
      card.classList.add("cooking-dashboard-card");
    }
    if (tileApplianceType === "microwave") {
      card.classList.add("microwave-dashboard-card");
    }
    if (isRing(device) || isIpCamera(device)) {
      card.classList.add("ring-card");
    }
    if (isCameraLandscape) {
      card.classList.add("camera-landscape-card");
    }
    if (isGarage(device)) {
      card.classList.add("garage-card");
    }
    if (tileLayoutForDevice(device) === "compact") {
      card.classList.add("switch-dashboard-card");
    }
    card.dataset.status = deviceState.status;
    card.tabIndex = 0;
    card.role = "button";
    card.setAttribute("aria-label", "Open " + device.name + " controls");
    card.addEventListener("click", function (event) {
      if (event.target.closest("button, input, select, textarea, a, form")) {
        return;
      }
      openDeviceDetail(device.id);
    });
    card.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      if (event.target.closest("button, input, select, textarea, a, form")) {
        return;
      }
      event.preventDefault();
      openDeviceDetail(device.id);
    });

    const header = document.createElement("div");
    header.className = "device-header";

    const titleCluster = document.createElement("div");
    titleCluster.className = "device-title-cluster";
    const iconStack = document.createElement("div");
    iconStack.className = "device-icon-stack";
    iconStack.appendChild(renderDeviceIcon(device, deviceState, "device-card-icon"));

    const title = document.createElement("div");
    title.className = "device-title";
    title.innerHTML = "<h3></h3>";
    title.querySelector("h3").textContent = device.name;
    const alerts = applianceAlerts(device, deviceState);
    const titleAlerts = isPrinter(device) ? alerts : [];
    titleCluster.appendChild(iconStack);
    titleCluster.appendChild(title);

    const pill = document.createElement("span");
    pill.className = "state-pill " + deviceState.status;
    pill.textContent = stateLabel(device, deviceState.status, deviceState.isOn);

    const source = document.createElement("span");
    source.className = "source-badge " + deviceSourceKind(device);
    source.textContent = sourceBadgeLabel(device);

    const favoriteButton = document.createElement("button");
    favoriteButton.type = "button";
    favoriteButton.className = "favorite-button";
    favoriteButton.dataset.active = isFavoriteDevice(device.id) ? "true" : "false";
    favoriteButton.setAttribute("aria-label", (isFavoriteDevice(device.id) ? "Unpin " : "Pin ") + device.name);
    favoriteButton.title = isFavoriteDevice(device.id) ? "Unpin" : "Pin to top";
    favoriteButton.textContent = "★";
    favoriteButton.addEventListener("click", function (event) {
      event.stopPropagation();
      toggleFavoriteDevice(device.id);
    });

    const cardControls = document.createElement("div");
    cardControls.className = "device-card-controls";
    const iconControls = document.createElement("div");
    iconControls.className = "card-icon-controls";
    if (supportsCardRefreshControl(device)) {
      iconControls.appendChild(cardRefreshButton(device, deviceState.status));
    }
    iconControls.appendChild(favoriteButton);
    cardControls.appendChild(iconControls);
    if (showsSourceBadge(device) || !usesInlineSwitchState(device)) {
      header.classList.add("has-control-badges");
    }
    if (showsSourceBadge(device)) {
      cardControls.appendChild(source);
    }
    if (!usesInlineSwitchState(device)) {
      cardControls.appendChild(pill);
    }

    header.appendChild(titleCluster);
    header.appendChild(cardControls);
    if (titleAlerts.length) {
      header.classList.add("has-header-alerts");
      header.appendChild(renderAlertChips(titleAlerts, "header-alerts"));
    }

    const body = document.createElement("div");
    body.className = "device-body";
    if (alerts.length && !titleAlerts.length) {
      body.appendChild(renderAlertChips(alerts));
    }
    if (isRing(device)) {
      body.appendChild(renderRingTileSnapshot(device));
    } else if (isIpCamera(device)) {
      body.appendChild(renderIpCameraTileSnapshot(device));
    }
    if (state.showAdminDeviceDetails && !isCameraLandscape) {
      body.appendChild(renderMeta(device));
    }
    if (isGarage(device)) {
      body.appendChild(renderGarageTileStatus(deviceState));
    } else if (isPrinter(device)) {
      body.appendChild(renderPrinterTileStatus(deviceState.appliance || {}, deviceState));
    } else if (deviceState.appliance?.type === "laundry") {
      body.appendChild(renderLaundryTileStatus(deviceState.appliance, deviceState));
    } else if (tileApplianceType === "refrigerator") {
      body.appendChild(renderFridgeTileStatus(device, applianceForDashboard(device, deviceState)));
    } else if (deviceState.appliance?.type === "microwave" || deviceState.appliance?.type === "oven") {
      body.appendChild(renderCookingTileStatus(device, deviceState.appliance));
    } else if (deviceState.appliance) {
      body.appendChild(renderAppliance(deviceState.appliance));
    }
    if (deviceState.error && shouldShowDeviceStateError(device, deviceState)) {
      const error = document.createElement("p");
      error.className = "device-error";
      error.textContent = deviceState.error;
      body.appendChild(error);
    }
    const actions = document.createElement("div");
    actions.className = "device-actions";
    if (isCudy(device)) {
      actions.appendChild(actionButton("Stats", "cudy-stats", device.id, deviceState.status));
      actions.appendChild(actionButton("Speed test", "cudy-speedtest", device.id, deviceState.status));
      actions.appendChild(actionButton("Credentials", "cudy-credentials", device.id, deviceState.status));
      actions.appendChild(actionButton("Reboot", "cudy-reboot", device.id, deviceState.status));
    } else if (isLock(device)) {
      actions.appendChild(actionButton("Lock", "lock", device.id, deviceState.status));
      actions.appendChild(actionButton("Unlock", "unlock", device.id, deviceState.status));
    } else if (isGarage(device)) {
      actions.appendChild(actionButton("Open", "open", device.id, deviceState.status));
      actions.appendChild(actionButton("Close", "close", device.id, deviceState.status));
    } else if (usesHeaderRefreshOnly(device)) {
      // These dashboard cards are monitors; they use the header refresh button instead of power controls.
    } else if (isDimmer(device)) {
      actions.classList.add("switch-toggle-actions");
      actions.appendChild(renderDimmerToggle(device, deviceState));
    } else if (isSimpleLightSwitch(device)) {
      actions.classList.add("switch-toggle-actions");
      actions.appendChild(renderSwitchToggle(device, deviceState));
    } else {
      actions.appendChild(actionButton("On", "turn-on", device.id, deviceState.status));
      actions.appendChild(actionButton("Off", "turn-off", device.id, deviceState.status));
      actions.appendChild(actionButton("Toggle", "toggle", device.id, deviceState.status));
    }

    if (isCameraLandscape) {
      card.appendChild(body);
      return card;
    }

    card.appendChild(header);
    card.appendChild(body);
    if (actions.children.length) {
      card.appendChild(actions);
    }
    return card;
  }

  function supportsCardRefreshControl(device) {
    return isCudy(device) || isAppliance(device) || isSensor(device) || isRing(device) || isIpCamera(device) || isNest(device) || isPrinter(device) || isLock(device) || isGarage(device);
  }

  function cardRefreshButton(device, status) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "favorite-button card-refresh-button";
    button.disabled = status === "loading";
    button.setAttribute("aria-label", "Refresh " + device.name);
    button.title = status === "loading" ? "Refreshing" : "Refresh";
    button.textContent = "↻";
    button.addEventListener("click", async function (event) {
      event.stopPropagation();
      await refreshOneDevice(device.id);
    });
    return button;
  }

  function usesHeaderRefreshOnly(device) {
    return isAppliance(device) || isSensor(device) || isRing(device) || isIpCamera(device) || isNest(device) || isPrinter(device);
  }

  function usesInlineSwitchState(device) {
    return isInlineSwitchTile(device) || isAppliance(device) || isGarage(device);
  }

  function isInlineSwitchTile(device) {
    return isSimpleLightSwitch(device) || isDimmer(device);
  }

  function showsSourceBadge(device) {
    return !["smartthings", "meross", "ring"].includes(device.brand);
  }

  function dashboardApplianceType(device, deviceState) {
    if (deviceState.appliance?.type) {
      return deviceState.appliance.type;
    }
    const type = deviceText(device);
    if (type.includes("refrigerator") || type.includes("fridge") || type.includes("freezer")) {
      return "refrigerator";
    }
    return "";
  }

  function applianceForDashboard(device, deviceState) {
    const appliance = deviceState.appliance || {};
    const type = appliance.type || dashboardApplianceType(device, deviceState);
    if (!type) {
      return appliance;
    }
    return Object.assign({ type: type, title: humanize(type) }, appliance);
  }

  function renderGarageTileStatus(deviceState) {
    const isOpen = deviceState.status === "on" || deviceState.isOn === true;
    const wrapper = document.createElement("div");
    wrapper.className = "garage-door-visual " + (isOpen ? "is-open" : "is-closed");
    wrapper.setAttribute("aria-label", isOpen ? "Garage door open" : "Garage door closed");
    wrapper.innerHTML = [
      '<div class="garage-door-frame" aria-hidden="true">',
      '<span class="garage-door-panel garage-door-panel-top"></span>',
      '<span class="garage-door-panel garage-door-panel-middle"></span>',
      '<span class="garage-door-panel garage-door-panel-bottom"></span>',
      '<span class="garage-door-opening"></span>',
      '</div>'
    ].join("");
    return wrapper;
  }

  function renderRingTileSnapshot(device) {
    const preview = document.createElement("div");
    preview.className = "ring-tile-preview";

    const image = document.createElement("img");
    image.alt = device.name + " camera snapshot";
    image.loading = "lazy";
    image.dataset.ringTileSnapshot = String(device.id);
    image.src = ringTileSnapshotUrl(device.id);

    const fallback = document.createElement("span");
    fallback.textContent = "Snapshot unavailable";

    image.addEventListener("load", function () {
      preview.classList.remove("snapshot-error");
    });
    image.addEventListener("error", function () {
      preview.classList.add("snapshot-error");
    });
    window.setTimeout(function () {
      refreshRingTileSnapshotInBackground(device.id, false);
    }, 0);

    preview.appendChild(image);
    preview.appendChild(fallback);
    return preview;
  }

  function renderIpCameraTileSnapshot(device) {
    const deviceState = state.states.get(device.id) || {};
    const cameraId = Number(deviceState.raw?.camera_id || 0);
    if (state.showLiveCameraTiles && cameraId) {
      return renderIpCameraTileLiveView(device, cameraId);
    }

    const preview = document.createElement("div");
    preview.className = "ring-tile-preview ip-camera-tile-preview";
    const image = document.createElement("img");
    image.alt = device.name + " camera preview";
    image.loading = "eager";
    image.decoding = "async";
    image.dataset.ipCameraTileSnapshot = String(device.id);
    image.src = ipCameraTileSnapshotUrl(device.id);
    const fallback = document.createElement("span");
    fallback.textContent = state.showLiveCameraTiles ? "Starting live view..." : "Loading snapshot...";
    if (!state.ipCameraTileSnapshotLoaded.has(Number(device.id))) {
      preview.classList.add("snapshot-loading");
    }
    image.addEventListener("load", function () {
      state.ipCameraTileSnapshotLoaded.add(Number(device.id));
      preview.classList.remove("snapshot-error");
      preview.classList.remove("snapshot-loading");
    });
    image.addEventListener("error", function () {
      fallback.textContent = "Camera unavailable";
      preview.classList.add("snapshot-error");
      preview.classList.remove("snapshot-loading");
    });
    window.setTimeout(function () {
      refreshIpCameraTileSnapshotInBackground(device.id, false);
    }, 0);
    preview.appendChild(image); preview.appendChild(fallback);
    return preview;
  }

  function renderIpCameraTileLiveView(device, cameraId) {
    const preview = document.createElement("div");
    preview.className = "ring-tile-preview ip-camera-tile-preview ip-camera-live-preview snapshot-loading";
    const video = document.createElement("video");
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    video.dataset.ipCameraTileLive = String(device.id);
    video.dataset.ipCameraId = String(cameraId);
    video.setAttribute("aria-label", device.name + " live camera view");
    const fallback = document.createElement("span");
    fallback.textContent = "Connecting live view...";
    const badge = document.createElement("div");
    badge.className = "camera-live-badge";
    badge.textContent = "LIVE";
    const fixButton = document.createElement("button");
    fixButton.type = "button";
    fixButton.className = "camera-feed-fix-button";
    fixButton.textContent = "Fix feed";
    fixButton.addEventListener("click", function (event) {
      event.stopPropagation();
      repairIpCameraTileLiveView(device.id, cameraId, video, preview, fallback, "Repairing live view...");
    });

    video.addEventListener("loadeddata", function () {
      markIpCameraLiveFrame(device.id);
      preview.classList.remove("snapshot-loading");
      preview.classList.remove("snapshot-error");
    });
    ["playing", "timeupdate", "progress"].forEach(function (eventName) {
      video.addEventListener(eventName, function () {
        markIpCameraLiveFrame(device.id);
      });
    });
    video.addEventListener("waiting", function () {
      fallback.textContent = "Live feed buffering...";
    });
    video.addEventListener("stalled", function () {
      repairIpCameraTileLiveView(device.id, cameraId, video, preview, fallback, "Live feed stalled. Repairing...");
    });
    video.addEventListener("error", function () {
      repairIpCameraTileLiveView(device.id, cameraId, video, preview, fallback, "Live feed error. Repairing...");
    });

    preview.appendChild(video);
    preview.appendChild(fallback);
    preview.appendChild(badge);
    preview.appendChild(fixButton);
    window.setTimeout(function () {
      startIpCameraTileLiveView(device.id, cameraId, video, preview, fallback);
    }, 0);
    return preview;
  }

  function shouldPreserveLiveCameraCard(device, existingCard) {
    if (!state.showLiveCameraTiles || !isIpCamera(device) || !existingCard) {
      return false;
    }
    const deviceState = state.states.get(device.id) || {};
    const cameraId = Number(deviceState.raw?.camera_id || 0);
    if (!cameraId) {
      return false;
    }
    const liveVideo = existingCard.querySelector("[data-ip-camera-tile-live]");
    const existingLandscape = existingCard.classList.contains("camera-landscape-card");
    return Boolean(
      liveVideo &&
      Number(liveVideo.dataset.ipCameraId || 0) === cameraId &&
      existingLandscape === isCameraLandscapeTile(device)
    );
  }

  function renderPrinterTileStatus(appliance, deviceState) {
    const wrapper = document.createElement("div");
    wrapper.className = "printer-tile";
    const supplies = (appliance.inkLevels || []).slice(0, 6);
    const hasEstimatedInk = supplies.some(isBucketedInkEstimate);
    const summary = document.createElement("div");
    summary.className = "printer-summary-row";
    summary.innerHTML = "<strong></strong><span></span>";
    const lowest = appliance.lowestInkPercent;
    const isRefreshing = deviceState.status === "loading";
    summary.querySelector("strong").textContent = lowest !== null && lowest !== undefined ? (hasEstimatedInk ? "~" : "") + lowest + "% lowest" : isRefreshing ? "Refreshing" : appliance.status || (deviceState.isOn ? "Online" : "Offline");
    summary.querySelector("span").textContent = appliance.stale ? "Last known" : isRefreshing ? "Updating" : hasEstimatedInk ? "Canon estimate" : appliance.message || appliance.status || "Ready";
    wrapper.appendChild(summary);

    const bars = document.createElement("div");
    bars.className = "printer-ink-bars";
    supplies.forEach(function (supply) {
      bars.appendChild(renderInkBar(supply, true));
    });
    if (!supplies.length) {
      const empty = document.createElement("p");
      empty.className = "detail-muted";
      empty.textContent = isRefreshing ? "Refreshing printer status..." : appliance.stale ? "Cached status only" : appliance.emptySupplyMessage || "Supply data unavailable";
      wrapper.appendChild(empty);
    } else {
      wrapper.appendChild(bars);
    }
    if (Array.isArray(appliance.alerts) && appliance.alerts.length) {
      const alert = document.createElement("p");
      alert.className = "printer-alert-summary";
      alert.textContent = printerAlertSummary(appliance.alerts);
      wrapper.appendChild(alert);
    }
    return wrapper;
  }

  function renderInkBar(supply, compact) {
    const percent = supply.percent;
    const displayPercent = typeof percent === "number" && Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : null;
    const thresholdOnly = supply.measurement === "threshold-only";
    const visualPercent = displayPercent === null && thresholdOnly ? 8 : displayPercent;
    const bucketed = isBucketedInkEstimate(supply);
    const item = document.createElement("div");
    item.className = "printer-ink " + inkStatusClass(supply.status) + (bucketed ? " bucketed-ink" : "");
    item.style.setProperty("--ink-level", String(visualPercent === null ? 0 : visualPercent));
    item.style.setProperty("--ink-color", inkColor(supply));
    item.innerHTML = [
      '<div class="printer-ink-label"><span></span><strong></strong></div>',
      bucketed ? bucketedInkTrack(visualPercent) : '<div class="printer-ink-track" aria-hidden="true"><span></span></div>',
      compact ? "" : '<small></small>'
    ].join("");
    item.querySelector(".printer-ink-label span").textContent = printerSupplyLabel(supply);
    item.querySelector(".printer-ink-label strong").textContent = thresholdOnly ? "Low" : displayPercent === null ? "--" : (bucketed ? "~" : "") + displayPercent + "%";
    const detail = item.querySelector("small");
    if (detail) {
      detail.textContent = printerSupplyDetail(supply);
    }
    return item;
  }

  function isBucketedInkEstimate(supply) {
    return supply && (
      supply.measurement === "remote-ui-estimate" ||
      supply.measurement === "manual-refill" ||
      supply.measurement === "threshold-only"
    );
  }

  function printerSupplyLabel(supply) {
    const label = supply.color || supply.name || supply.reportedName || "Ink";
    if (/fixed ink absorber/i.test(String(supply.name || supply.reportedName || ""))) {
      return "Ink absorber";
    }
    return label;
  }

  function isRefillableInkSupply(supply) {
    const color = String(supply.color || "").toLowerCase();
    return ["black", "cyan", "magenta", "yellow"].includes(color);
  }

  function bucketedInkTrack(displayPercent) {
    const filledSegments = displayPercent === null ? 0 : Math.max(0, Math.min(10, Math.round(displayPercent / 10)));
    let html = '<div class="printer-ink-buckets" aria-hidden="true">';
    for (let index = 0; index < 10; index += 1) {
      html += '<span class="' + (index < filledSegments ? "filled" : "") + '"></span>';
    }
    html += "</div>";
    return html;
  }

  function inkStatusClass(status) {
    if (status === "empty" || status === "low") {
      return "needs-ink";
    }
    if (status === "watch") {
      return "watch-ink";
    }
    return "ok-ink";
  }

  function inkColor(supply) {
    const color = String(supply.color || supply.name || "").toLowerCase();
    if (color.includes("cyan")) return "#00a3d7";
    if (color.includes("magenta")) return "#d9287c";
    if (color.includes("yellow")) return "#f2c500";
    if (color.includes("orange")) return "#f97316";
    if (color.includes("red")) return "#dc2626";
    if (color.includes("blue")) return "#2563eb";
    if (color.includes("gray") || color.includes("grey")) return "#8b95a1";
    if (color.includes("waste") || color.includes("maintenance")) return "#64748b";
    if (color.includes("black")) return "#111827";
    return "#2f8f7f";
  }

  function printerSupplyDetail(supply) {
    const parts = [];
    if (supply.measurement === "threshold-only") {
      return "Canon estimate · last bucket · Low";
    }
    if (isBucketedInkEstimate(supply)) {
      if (supply.measurement === "manual-refill") {
        parts.push("Manual refill");
      } else {
        parts.push("Canon estimate");
        parts.push("bucketed");
      }
      if (supply.remoteUiLevelIndex !== null && supply.remoteUiLevelIndex !== undefined) {
        parts.push("bucket " + String(supply.remoteUiLevelIndex));
      }
      if (supply.manualRefillAt) {
        parts.push("refilled " + lastCheckedLabel(supply.manualRefillAt));
      }
      if (supply.status && supply.status !== "ok") {
        parts.push(humanize(supply.status));
      }
      return parts.join(" · ");
    }
    if (supply.level !== null && supply.level !== undefined) {
      parts.push(String(supply.level) + (supply.max ? " / " + supply.max : ""));
    }
    if (supply.unit) {
      parts.push(supply.unit);
    }
    if (supply.status && supply.status !== "ok") {
      parts.push(humanize(supply.status));
    }
    return parts.join(" · ") || "Reported by printer";
  }

  function shouldShowDeviceStateError(device, deviceState) {
    if (!isPrinter(device)) {
      return true;
    }
    const appliance = deviceState.appliance || {};
    if (deviceState.isOn && appliance.type === "printer" && appliance.checkedAt && !appliance.stale) {
      return false;
    }
    return true;
  }

  function renderAlertChips(alerts, extraClass) {
    const list = document.createElement("div");
    list.className = "alert-chip-list" + (extraClass ? " " + extraClass : "");
    alerts.forEach(function (alert) {
      const chip = document.createElement("span");
      chip.className = "alert-chip " + alert.severity;
      chip.textContent = alert.label;
      list.appendChild(chip);
    });
    return list;
  }

  function applianceAlerts(device, deviceState) {
    const appliance = deviceState.appliance;
    if (!appliance) {
      return [];
    }

    const alerts = [];
    if (appliance.type === "laundry" && isLaundryDone(appliance, deviceState)) {
      alerts.push({ label: "Washer done", severity: "success" });
    }
    if (appliance.type === "refrigerator") {
      if (String(appliance.coolerDoor || "").toLowerCase() === "open" || String(appliance.freezerDoor || "").toLowerCase() === "open") {
        alerts.push({ label: "Fridge door open", severity: "warning" });
      }
      if (String(appliance.waterFilterStatus || "").toLowerCase() === "replace" || Number(appliance.waterFilterUsage || 0) >= 95) {
        alerts.push({ label: "Filter needs replacing", severity: "warning" });
      }
    }
    if ((appliance.type === "microwave" || appliance.type === "oven") && isCookingActive(appliance)) {
      alerts.push({ label: humanize(appliance.type) + " active", severity: "info" });
    }
    if (appliance.type === "printer") {
      if (appliance.stale) {
        alerts.push({ label: "Last known supplies", severity: "warning" });
      }
      if (Array.isArray(appliance.alerts) && appliance.alerts.length) {
        alerts.push({
          label: printerAlertSummary(appliance.alerts),
          severity: "warning"
        });
      }
      const lowSupply = (appliance.inkLevels || []).find(function (item) {
        return item.status === "empty" || item.status === "low";
      });
      if (lowSupply) {
        const supplyName = lowSupply.supplyType === "ribbon" ? "Ribbon" : lowSupply.supplyType === "ink" ? "Ink" : "Supply";
        alerts.push({ label: supplyName + (lowSupply.status === "empty" ? " empty" : " low"), severity: "warning" });
      }
    }
    return alerts;
  }

  function printerAlertSummary(alerts) {
    if (!Array.isArray(alerts) || !alerts.length) {
      return "Printer alert";
    }
    const first = alerts[0] || {};
    const label = first.description || first.message || (first.code ? "Alert " + first.code : "Printer alert");
    return alerts.length > 1 ? label + " +" + (alerts.length - 1) : label;
  }

  function isLaundryDone(appliance, deviceState) {
    if (isLaundryActive(appliance, deviceState)) {
      return false;
    }
    const text = [
      appliance.operatingState,
      appliance.machineState,
      appliance.jobState,
      appliance.jobPhase
    ].join(" ").toLowerCase();
    return ["complete", "completed", "finish", "finished", "end"].some(function (value) {
      return text.includes(value);
    });
  }

  function isCookingActive(appliance) {
    const text = [
      appliance.operatingState,
      appliance.jobState,
      appliance.mode
    ].join(" ").toLowerCase();
    return Boolean(text.trim()) && !["ready", "idle", "off", "none"].some(function (value) {
      return text.split(/\s+/).includes(value);
    });
  }

  function refreshRingTileSnapshots() {
    document.querySelectorAll("[data-ring-tile-snapshot]").forEach(function (image) {
      refreshRingTileSnapshotInBackground(Number(image.dataset.ringTileSnapshot), true);
    });
  }

  function ipCameraTileSnapshotUrl(deviceId) {
    const id = Number(deviceId);
    if (!state.ipCameraTileSnapshotUrls.has(id)) {
      state.ipCameraTileSnapshotUrls.set(id, "/api/cameras/device/" + id + "/snapshot?t=initial");
    }
    return state.ipCameraTileSnapshotUrls.get(id);
  }

  function refreshIpCameraTileSnapshots() {
    document.querySelectorAll("[data-ip-camera-tile-snapshot]").forEach(function (image) {
      refreshIpCameraTileSnapshotInBackground(Number(image.dataset.ipCameraTileSnapshot), true);
    });
  }

  function startIpCameraTileLiveView(deviceId, cameraId, video, preview, fallback, options) {
    if (!video.isConnected || !state.showLiveCameraTiles) {
      return;
    }
    const id = Number(deviceId);
    const url = "/api/cameras/" + Number(cameraId) + "/live/index.m3u8?t=" + encodeURIComponent(options?.token || Date.now());
    markIpCameraLiveFrame(id);
    setupIpCameraLiveWatchdog(id, Number(cameraId), video, preview, fallback);
    try {
      if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = url;
        video.play().catch(function () {});
        return;
      }
      if (window.Hls && window.Hls.isSupported()) {
        const player = new window.Hls({ liveSyncDurationCount: 2 });
        player.on(window.Hls.Events.ERROR, function (event, data) {
          if (data && data.fatal) {
            repairIpCameraTileLiveView(id, Number(cameraId), video, preview, fallback, "Live feed error. Repairing...");
          }
        });
        player.loadSource(url);
        player.attachMedia(video);
        state.ipCameraTileLivePlayers.set(id, player);
        video.play().catch(function () {});
        return;
      }
      fallback.textContent = "Live view unsupported";
      preview.classList.add("snapshot-error");
      preview.classList.remove("snapshot-loading");
    } catch (error) {
      fallback.textContent = "Live view unavailable";
      preview.classList.add("snapshot-error");
      preview.classList.remove("snapshot-loading");
    }
  }

  function cleanupCameraTileLiveViews(keepDeviceIds) {
    state.ipCameraTileLivePlayers.forEach(function (player, deviceId) {
      if (keepDeviceIds && keepDeviceIds.has(Number(deviceId))) {
        return;
      }
      try {
        player.destroy();
      } catch (error) {}
      state.ipCameraTileLivePlayers.delete(deviceId);
    });
    state.ipCameraTileLiveWatchdogs.forEach(function (timer, deviceId) {
      if (keepDeviceIds && keepDeviceIds.has(Number(deviceId))) {
        return;
      }
      window.clearInterval(timer);
      state.ipCameraTileLiveWatchdogs.delete(deviceId);
      state.ipCameraTileLiveLastFrame.delete(deviceId);
      state.ipCameraTileLiveRepairs.delete(deviceId);
    });
  }

  function markIpCameraLiveFrame(deviceId) {
    state.ipCameraTileLiveLastFrame.set(Number(deviceId), Date.now());
  }

  function setupIpCameraLiveWatchdog(deviceId, cameraId, video, preview, fallback) {
    const id = Number(deviceId);
    if (state.ipCameraTileLiveWatchdogs.has(id)) {
      return;
    }
    const timer = window.setInterval(function () {
      if (!video.isConnected || !state.showLiveCameraTiles) {
        window.clearInterval(timer);
        state.ipCameraTileLiveWatchdogs.delete(id);
        state.ipCameraTileLiveLastFrame.delete(id);
        state.ipCameraTileLiveRepairs.delete(id);
        return;
      }
      const lastFrameAt = state.ipCameraTileLiveLastFrame.get(id) || 0;
      const stalled = Date.now() - lastFrameAt > 22000;
      if (stalled || video.readyState < 2) {
        repairIpCameraTileLiveView(id, Number(cameraId), video, preview, fallback, "Live feed stalled. Repairing...");
      } else if (video.paused) {
        video.play().catch(function () {});
      }
    }, 7000);
    state.ipCameraTileLiveWatchdogs.set(id, timer);
  }

  async function repairIpCameraTileLiveView(deviceId, cameraId, video, preview, fallback, message) {
    const id = Number(deviceId);
    if (!id || !cameraId || state.ipCameraTileLiveRepairs.has(id)) {
      return;
    }
    state.ipCameraTileLiveRepairs.add(id);
    fallback.textContent = message || "Repairing live view...";
    preview.classList.add("snapshot-loading");
    preview.classList.remove("snapshot-error");
    const player = state.ipCameraTileLivePlayers.get(id);
    if (player) {
      try {
        player.destroy();
      } catch (error) {}
      state.ipCameraTileLivePlayers.delete(id);
    }
    try {
      video.pause();
      video.removeAttribute("src");
      video.load();
    } catch (error) {}
    try {
      await requestJson("/api/cameras/" + Number(cameraId) + "/live/restart", {
        method: "POST",
        timeoutMs: 12000
      });
      markIpCameraLiveFrame(id);
      startIpCameraTileLiveView(id, Number(cameraId), video, preview, fallback, { token: Date.now() });
    } catch (error) {
      fallback.textContent = error.message || "Live repair failed";
      preview.classList.add("snapshot-error");
      preview.classList.remove("snapshot-loading");
    } finally {
      window.setTimeout(function () {
        state.ipCameraTileLiveRepairs.delete(id);
      }, 12000);
    }
  }

  function refreshIpCameraTileSnapshotInBackground(deviceId, force) {
    const id = Number(deviceId);
    if (!id) {
      return;
    }
    if (state.ipCameraTileSnapshotRefreshes.has(id)) {
      return;
    }
    const lastRefresh = state.ipCameraTileSnapshotLastRefresh.get(id) || 0;
    if (!force && Date.now() - lastRefresh < 55000) {
      return;
    }
    state.ipCameraTileSnapshotLastRefresh.set(id, Date.now());
    const nextUrl = "/api/cameras/device/" + id + "/snapshot?t=" + Date.now();
    state.ipCameraTileSnapshotRefreshes.add(id);
    const preload = new Image();
    preload.onload = function () {
      state.ipCameraTileSnapshotUrls.set(id, nextUrl);
      state.ipCameraTileSnapshotLoaded.add(id);
      state.ipCameraTileSnapshotRefreshes.delete(id);
      document.querySelectorAll("[data-ip-camera-tile-snapshot=\"" + id + "\"]").forEach(function (image) {
        const preview = image.closest(".ip-camera-tile-preview");
        if (preview) {
          preview.classList.remove("snapshot-error");
          preview.classList.remove("snapshot-loading");
        }
        image.src = nextUrl;
      });
    };
    preload.onerror = function () {
      state.ipCameraTileSnapshotRefreshes.delete(id);
    };
    preload.src = nextUrl;
  }

  async function refreshRingTileSnapshotInBackground(deviceId, force) {
    if (!deviceId || state.ringTileSnapshotRefreshes.has(deviceId)) {
      return;
    }

    const lastRefresh = state.ringTileSnapshotLastRefresh.get(deviceId) || 0;
    if (!force && Date.now() - lastRefresh < 55000) {
      return;
    }

    state.ringTileSnapshotRefreshes.add(deviceId);
    try {
      await requestJson("/devices/" + deviceId + "/ring/snapshot/refresh", {
        method: "POST",
        timeoutMs: 25000
      });
      state.ringTileSnapshotLastRefresh.set(deviceId, Date.now());
      document.querySelectorAll("[data-ring-tile-snapshot=\"" + deviceId + "\"]").forEach(function (image) {
        image.src = ringTileSnapshotUrl(deviceId);
      });
    } catch (error) {
      state.ringTileSnapshotLastRefresh.set(deviceId, Date.now());
    } finally {
      state.ringTileSnapshotRefreshes.delete(deviceId);
    }
  }

  async function openDeviceDetail(deviceId) {
    const device = state.devices.find(function (item) {
      return item.id === deviceId;
    });
    if (!device) {
      return;
    }

    elements.deviceDetailEyebrow.textContent = detailEyebrowLabel(device);
    updateDeviceIconElement(elements.deviceDetailIcon, device, state.states.get(device.id), "detail-device-icon");
    elements.deviceDetailTitle.textContent = device.name;
    elements.deviceDetailDialog.dataset.deviceId = String(device.id);
    renderDeviceDetail(device);
    if (!elements.deviceDetailDialog.open) {
      elements.deviceDetailDialog.showModal();
    }

    if (device.brand === "smartthings" && !state.inspections.has(device.id)) {
      await inspectDevice(device.id, { silent: true });
      renderDeviceDetail(device);
    }
  }

  function detailEyebrowLabel(device) {
    return [sourceLabel(device), device.model].filter(Boolean).join(" · ");
  }

  function renderDeviceDetail(device) {
    const deviceState = state.states.get(device.id) || { status: "loading", isOn: null, error: "" };
    const content = elements.deviceDetailContent;
    updateDeviceIconElement(elements.deviceDetailIcon, device, deviceState, "detail-device-icon");
    content.innerHTML = "";

    if (device.brand === "smartthings" && deviceState.appliance?.type === "refrigerator") {
      renderRefrigeratorDetail(device, deviceState, content);
      appendAdminDeviceInfo(content, device);
      return;
    }
    if (device.brand === "smartthings" && deviceState.appliance?.type === "laundry") {
      renderLaundryDetail(device, deviceState, content);
      appendAdminDeviceInfo(content, device);
      return;
    }
    if (device.brand === "smartthings" && (deviceState.appliance?.type === "microwave" || deviceState.appliance?.type === "oven")) {
      renderCookingDetail(device, deviceState, content);
      appendAdminDeviceInfo(content, device);
      return;
    }
    if (isRing(device)) {
      renderRingDetail(device, deviceState, content);
      appendAdminDeviceInfo(content, device);
      return;
    }
    if (isIpCamera(device)) {
      renderIpCameraDetail(device, deviceState, content);
      appendAdminDeviceInfo(content, device);
      return;
    }
    if (isCudy(device)) {
      renderCudyDetail(device, deviceState, content);
      appendAdminDeviceInfo(content, device);
      return;
    }
    if (isNest(device)) {
      renderNestDetail(device, deviceState, content);
      appendAdminDeviceInfo(content, device);
      return;
    }
    if (isPrinter(device)) {
      renderPrinterDetail(device, deviceState, content);
      appendAdminDeviceInfo(content, device);
      return;
    }

    const summary = document.createElement("section");
    summary.className = "detail-section";
    const summaryHeader = document.createElement("div");
    summaryHeader.className = "detail-summary";
    const pill = document.createElement("span");
    pill.className = "state-pill " + deviceState.status;
    pill.textContent = stateLabel(device, deviceState.status, deviceState.isOn);
    summaryHeader.appendChild(pill);
    const type = document.createElement("p");
    type.textContent = [device.model, device.device_type || sourceLabel(device)].filter(Boolean).join(" · ");
    summaryHeader.appendChild(type);
    summary.appendChild(summaryHeader);
    summary.appendChild(renderDetailActions(device, deviceState));
    content.appendChild(summary);

    if (deviceState.appliance) {
      const appliance = document.createElement("section");
      appliance.className = "detail-section";
      appliance.appendChild(sectionTitle(deviceState.appliance.title || "Status"));
      appliance.appendChild(renderAppliance(deviceState.appliance));
      content.appendChild(appliance);
    }

    appendAdminDeviceInfo(content, device);

    if (deviceState.error) {
      const error = document.createElement("p");
      error.className = "device-error detail-error";
      error.textContent = deviceState.error;
      content.appendChild(error);
    }

    if (device.brand === "smartthings") {
      content.appendChild(renderSmartThingsDetailControls(device));
    }
  }

  function appendAdminDeviceInfo(content, device) {
    if (!state.showAdminDeviceDetails) {
      return;
    }

    const meta = document.createElement("section");
    meta.className = "detail-section admin-device-info";
    meta.appendChild(sectionTitle("Device info"));
    meta.appendChild(renderMeta(device));
    content.appendChild(meta);
  }

  function renderRefrigeratorDetail(device, deviceState, content) {
    const appliance = deviceState.appliance || {};
    const raw = deviceState.raw || {};
    const components = raw.components || {};
    const main = components.main || {};
    const cooler = components.cooler || {};
    const freezer = components.freezer || {};
    const cvroom = components.cvroom || {};

    const shell = document.createElement("section");
    shell.className = "smartthings-fridge-screen";

    const top = document.createElement("div");
    top.className = "fridge-status-hero";
    [
      ["Fridge", appliance.coolerTemp, "°F"],
      ["Freezer", appliance.freezerTemp, "°F"],
      ["FlexZone™", flexZoneLabel(valueAt(cvroom, "custom.fridgeMode", "fridgeMode")), ""]
    ].forEach(function (item) {
      const metric = document.createElement("div");
      metric.innerHTML = "<span></span><strong></strong>";
      metric.querySelector("span").textContent = item[0];
      metric.querySelector("strong").textContent = item[2] ? formatApplianceValue(item[1], item[2]) : item[1] || "--";
      top.appendChild(metric);
    });
    shell.appendChild(top);

    shell.appendChild(renderViewInsidePanel(device, main));
    shell.appendChild(renderTemperatureCard(device, appliance, cooler, freezer));
    shell.appendChild(renderFeatureTiles(device, appliance));
    shell.appendChild(renderFlexZoneCard(device, cvroom));
    shell.appendChild(renderIceMakerCard(device, components));
    shell.appendChild(renderSmartThingsDetailControls(device, { compact: true, hideAdvanced: true }));
    shell.appendChild(renderFridgeTabs(device, appliance, main));
    content.appendChild(shell);

    if (deviceState.error) {
      const error = document.createElement("p");
      error.className = "device-error detail-error";
      error.textContent = deviceState.error;
      content.appendChild(error);
    }

  }

  function renderLaundryDetail(device, deviceState, content) {
    const appliance = deviceState.appliance || {};
    const raw = deviceState.raw || {};
    const components = raw.components || {};
    const main = components.main || {};

    const shell = document.createElement("section");
    shell.className = "smartthings-fridge-screen smartthings-appliance-screen laundry-screen";
    shell.appendChild(renderApplianceHero("laundry", [
      ["State", appliance.operatingState || appliance.machineState],
      ["Remaining", appliance.remainingTime],
      ["Cycle", appliance.cycleType || appliance.jobState]
    ]));
    shell.appendChild(renderLaundryStatusCard(appliance));
    shell.appendChild(renderLaundryActionGrid(device));
    shell.appendChild(renderApplianceSettingsCard("Wash and dry settings", [
      ["Water temperature", appliance.waterTemperature],
      ["Spin", appliance.spinLevel],
      ["Soil", appliance.soilLevel],
      ["Dry level", appliance.dryLevel],
      ["Dry temperature", appliance.dryingTemperature],
      ["Detergent", appliance.detergent],
      ["Softener", appliance.softener],
      ["Remote control", appliance.remoteControl || valueAt(main, "remoteControlStatus", "remoteControlEnabled")]
    ]));
    shell.appendChild(renderSmartThingsDetailControls(device, { compact: true, hideAdvanced: true }));
    content.appendChild(shell);
    appendDetailError(deviceState, content);
  }

  function renderCookingDetail(device, deviceState, content) {
    const appliance = deviceState.appliance || {};
    const raw = deviceState.raw || {};
    const components = raw.components || {};
    const isMicrowave = appliance.type === "microwave";

    const shell = document.createElement("section");
    shell.className = "smartthings-fridge-screen smartthings-appliance-screen cooking-screen";
    shell.appendChild(renderApplianceHero("cooking", [
      ["Mode", appliance.mode],
      ["Set temp", appliance.setpoint, appliance.setpoint !== undefined ? "°F" : ""],
      [isMicrowave ? "Door" : "Cavity", isMicrowave ? appliance.door : appliance.cavity]
    ]));
    shell.appendChild(renderCookingStatusCard(appliance, isMicrowave));
    if (!isMicrowave) {
      shell.appendChild(renderCookingPlanner(device, appliance));
    }
    shell.appendChild(renderCookingActionGrid(device, isMicrowave));
    shell.appendChild(renderCookingFeatureCard(appliance, components, isMicrowave));
    shell.appendChild(renderSmartThingsDetailControls(device, { compact: true, hideAdvanced: true }));
    content.appendChild(shell);
    appendDetailError(deviceState, content);
  }

  function appendDetailError(deviceState, content) {
    if (!deviceState.error) {
      return;
    }
    const error = document.createElement("p");
    error.className = "device-error detail-error";
    error.textContent = deviceState.error;
    content.appendChild(error);
  }

  function renderApplianceHero(kind, metrics) {
    const top = document.createElement("div");
    top.className = "fridge-status-hero appliance-hero " + kind;
    metrics.forEach(function (item) {
      const metric = document.createElement("div");
      metric.innerHTML = "<span></span><strong></strong>";
      metric.querySelector("span").textContent = item[0];
      metric.querySelector("strong").textContent = formatApplianceValue(item[1], item[2] || "");
      top.appendChild(metric);
    });
    return top;
  }

  function renderLaundryStatusCard(appliance) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle("Cycle status"));
    const timeline = document.createElement("div");
    timeline.className = "appliance-timeline";
    [
      ["Machine", appliance.machineState || appliance.operatingState],
      ["Job", appliance.jobState || appliance.jobPhase],
      ["Remaining", appliance.remainingTime || "--"]
    ].forEach(function (item) {
      const step = document.createElement("div");
      step.innerHTML = "<span></span><strong></strong>";
      step.querySelector("span").textContent = item[0];
      step.querySelector("strong").textContent = formatApplianceValue(item[1]);
      timeline.appendChild(step);
    });
    card.appendChild(timeline);
    return card;
  }

  function renderLaundryActionGrid(device) {
    const grid = document.createElement("div");
    grid.className = "fridge-feature-grid appliance-action-grid";
    [
      ["Start", "Start washer", "samsungce.washerOperatingState", "start"],
      ["Pause", "Pause cycle", "samsungce.washerOperatingState", "pause"],
      ["Resume", "Resume cycle", "samsungce.washerOperatingState", "resume"],
      ["Cancel", "Cancel cycle", "samsungce.washerOperatingState", "cancel"]
    ].forEach(function (item) {
      grid.appendChild(applianceCommandTile(device, item[0], item[1], "main", item[2], item[3], []));
    });
    return grid;
  }

  function renderCookingStatusCard(appliance, isMicrowave) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle(isMicrowave ? "Microwave status" : "Oven status"));
    const grid = document.createElement("div");
    grid.className = "appliance-setting-grid";
    [
      ["State", appliance.operatingState],
      ["Job", appliance.jobState],
      ["Current temp", appliance.temperature, appliance.temperature !== undefined ? "°F" : ""],
      ["Completion", appliance.completionTime],
      ["Door", appliance.door],
      ["Switch", appliance.switch]
    ].forEach(function (item) {
      grid.appendChild(settingPill(item[0], item[1], item[2] || ""));
    });
    card.appendChild(grid);
    return card;
  }

  function renderCookingActionGrid(device, isMicrowave) {
    const grid = document.createElement("div");
    grid.className = "fridge-feature-grid appliance-action-grid";
    const primaryCapability = isMicrowave ? "samsungce.ovenOperatingState" : "samsungce.ovenOperatingState";
    [
      ["Start", isMicrowave ? "Start microwave" : "Start oven", primaryCapability, "start"],
      ["Stop", isMicrowave ? "Stop microwave" : "Stop oven", primaryCapability, "stop"],
      ["Pause", "Pause cooking", primaryCapability, "pause"]
    ].forEach(function (item) {
      grid.appendChild(applianceCommandTile(device, item[0], item[1], "main", item[2], item[3], []));
    });
    return grid;
  }

  function renderCookingPlanner(device, appliance) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card stove-planner-card";
    card.appendChild(sectionTitle("Cook setup"));

    const inspection = state.inspections.get(device.id);
    if (!inspection || inspection.status === "loading") {
      const loading = document.createElement("p");
      loading.className = "detail-muted";
      loading.textContent = "Checking oven controls...";
      card.appendChild(loading);
      return card;
    }
    if (inspection.status === "error") {
      const error = document.createElement("p");
      error.className = "device-error";
      error.textContent = inspection.error || "Could not load oven controls.";
      card.appendChild(error);
      return card;
    }

    const controls = cookingStartControls(inspection);
    if (!controls.length) {
      const empty = document.createElement("p");
      empty.className = "detail-muted";
      empty.textContent = "This stove did not expose a guided start command.";
      card.appendChild(empty);
      return card;
    }

    const layout = document.createElement("div");
    layout.className = "stove-planner";
    const compartments = document.createElement("div");
    compartments.className = "stove-compartment-list";
    const panels = document.createElement("div");
    panels.className = "stove-compartment-panels";

    controls.forEach(function (control, index) {
      const compartment = document.createElement("button");
      compartment.type = "button";
      compartment.className = "stove-compartment-button" + (index === 0 ? " is-active" : "");
      compartment.dataset.compartment = control.component;
      compartment.innerHTML = "<span></span><strong></strong><small></small>";
      compartment.querySelector("span").textContent = control.component === "main" ? "Primary compartment" : "Compartment";
      compartment.querySelector("strong").textContent = cookingComponentLabel(control.component);
      compartment.querySelector("small").textContent = [humanize(appliance.mode || "ready"), formatApplianceValue(appliance.temperature || appliance.setpoint, appliance.temperature !== undefined || appliance.setpoint !== undefined ? "°F" : "")].filter(function (value) {
        return !isBlankValue(value);
      }).join(" · ") || "Tap to set";
      compartment.addEventListener("click", function () {
        setActiveCookingCompartment(card, control.component);
      });
      compartments.appendChild(compartment);

      const panel = renderCookingStartForm(device, appliance, control, index === 0);
      panels.appendChild(panel);
    });

    layout.appendChild(compartments);
    layout.appendChild(panels);
    card.appendChild(layout);
    return card;
  }

  function renderCookingStartForm(device, appliance, control, isActive) {
    const form = document.createElement("form");
    form.className = "stove-start-form" + (isActive ? " is-active" : "");
    form.dataset.compartment = control.component;
    form.dataset.deviceId = String(device.id);
    form.dataset.component = control.component;
    form.dataset.capability = control.capability.id;
    form.dataset.command = control.command.name;
    form.innerHTML = [
      '<label><span>Mode</span><select name="mode" required></select></label>',
      '<label><span>Temperature</span><input name="setpoint" type="number" min="0" step="5" required></label>',
      '<label><span>Time</span><input name="time" type="number" min="0" step="1"></label>',
      '<button class="command-send" type="submit">Start oven</button>'
    ].join("");

    const modeSelect = form.querySelector('select[name="mode"]');
    const modeArgument = commandArgument(control.command, "mode");
    const modes = prioritizedCookingModes(modeArgument?.options || []);
    modes.forEach(function (mode) {
      const option = document.createElement("option");
      option.value = String(mode);
      option.textContent = humanize(mode);
      modeSelect.appendChild(option);
    });
    const preferredMode = appliance.mode && modes.includes(appliance.mode) ? appliance.mode : modes.find(function (mode) {
      return mode === "Bake" || mode === "ConvectionBake";
    }) || modes[0] || "";
    modeSelect.value = preferredMode;

    const setpointInput = form.querySelector('input[name="setpoint"]');
    setpointInput.value = String(appliance.setpoint || 350);
    setpointInput.placeholder = "350";
    const timeInput = form.querySelector('input[name="time"]');
    timeInput.value = "0";
    timeInput.placeholder = "0 for no timer";

    form.addEventListener("submit", handleCookingStartSubmit);
    return form;
  }

  function setActiveCookingCompartment(card, component) {
    card.querySelectorAll(".stove-compartment-button").forEach(function (button) {
      button.classList.toggle("is-active", button.dataset.compartment === component);
    });
    card.querySelectorAll(".stove-start-form").forEach(function (form) {
      form.classList.toggle("is-active", form.dataset.compartment === component);
    });
  }

  async function handleCookingStartSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button");
    const mode = form.querySelector('select[name="mode"]').value;
    const time = Number.parseInt(form.querySelector('input[name="time"]').value || "0", 10);
    const setpoint = Number.parseInt(form.querySelector('input[name="setpoint"]').value, 10);
    if (!mode || Number.isNaN(setpoint)) {
      showBanner("Choose an oven mode and temperature.", "error");
      return;
    }
    button.disabled = true;
    button.textContent = "Starting...";
    await sendSmartThingsCommand(
      Number(form.dataset.deviceId),
      form.dataset.component,
      form.dataset.capability,
      form.dataset.command,
      [mode, Number.isNaN(time) ? 0 : time, setpoint]
    );
    button.disabled = false;
    button.textContent = "Start oven";
  }

  function cookingStartControls(inspection) {
    const controls = [];
    (inspection.controllable || []).forEach(function (capability) {
      if (!["ovenOperatingState", "samsungce.ovenOperatingState"].includes(capability.id)) {
        return;
      }
      (capability.commands || []).forEach(function (command) {
        if (command.name === "start") {
          controls.push({
            component: capability.component || "main",
            capability: capability,
            command: command
          });
        }
      });
    });
    controls.sort(function (left, right) {
      return cookingComponentRank(left.component) - cookingComponentRank(right.component);
    });
    return controls;
  }

  function cookingComponentRank(component) {
    if (component === "cavity-01") {
      return 0;
    }
    if (component === "main") {
      return 1;
    }
    return 2;
  }

  function cookingComponentLabel(component) {
    if (component === "main") {
      return "Main oven";
    }
    if (component === "cavity-01") {
      return "Oven cavity";
    }
    return friendlyComponentLabel(component) || humanize(component || "Oven");
  }

  function commandArgument(command, name) {
    return (command.arguments || []).find(function (argument) {
      return argument.name === name;
    });
  }

  function prioritizedCookingModes(modes) {
    const preferred = ["Bake", "ConvectionBake", "ConvectionRoast", "Broil", "AirFry", "Proof", "KeepWarm", "WarmHold"];
    const uniqueModes = Array.from(new Set(modes));
    return uniqueModes.sort(function (left, right) {
      const leftIndex = preferred.indexOf(left);
      const rightIndex = preferred.indexOf(right);
      const leftRank = leftIndex === -1 ? preferred.length : leftIndex;
      const rightRank = rightIndex === -1 ? preferred.length : rightIndex;
      return leftRank - rightRank || humanize(left).localeCompare(humanize(right));
    });
  }

  function renderCookingFeatureCard(appliance, components, isMicrowave) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle(isMicrowave ? "Power and hood" : "Oven settings"));
    const hood = components.hood || {};
    const grid = document.createElement("div");
    grid.className = "appliance-setting-grid";
    [
      ["Mode", appliance.mode],
      ["Setpoint", appliance.setpoint, appliance.setpoint !== undefined ? "°F" : ""],
      ["Power", appliance.power],
      ["Lamp", appliance.lamp || valueAt(hood, "samsungce.lamp", "brightnessLevel")],
      ["Hood fan", appliance.hoodFan || valueAt(hood, "samsungce.hoodFanSpeed", "hoodFanSpeed")],
      ["Cavity", appliance.cavity]
    ].forEach(function (item) {
      grid.appendChild(settingPill(item[0], item[1], item[2] || ""));
    });
    card.appendChild(grid);
    return card;
  }

  function renderApplianceSettingsCard(title, fields) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle(title));
    const grid = document.createElement("div");
    grid.className = "appliance-setting-grid";
    fields.forEach(function (item) {
      grid.appendChild(settingPill(item[0], item[1], item[2] || ""));
    });
    card.appendChild(grid);
    return card;
  }

  function settingPill(label, value, unit) {
    const pill = document.createElement("div");
    pill.className = "setting-pill";
    pill.innerHTML = "<span></span><strong></strong>";
    pill.querySelector("span").textContent = label;
    pill.querySelector("strong").textContent = formatApplianceValue(value, unit);
    return pill;
  }

  function applianceCommandTile(device, label, helper, component, capability, command, args) {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "feature-tile appliance-command-tile";
    tile.innerHTML = "<em></em><strong></strong><small></small>";
    tile.querySelector("em").textContent = label;
    tile.querySelector("strong").textContent = helper;
    tile.querySelector("small").textContent = applianceActionSourceLabel(capability, component);
    tile.disabled = commandKnownUnavailable(device.id, component, capability, command);
    tile.addEventListener("click", function () {
      sendSmartThingsCommand(device.id, component, capability, command, args || []);
    });
    return tile;
  }

  function applianceActionSourceLabel(capability, component) {
    if (capability.includes("washer") || capability.includes("dryer")) {
      return "Laundry control";
    }
    if (capability.includes("oven") || capability.includes("microwave")) {
      return component === "cavity-01" ? "Oven cavity control" : "Cooking control";
    }
    if (capability === "switch" || capability === "samsungce.switch") {
      return "Power control";
    }
    return friendlyCapabilityTitle(capability, component);
  }

  function commandKnownUnavailable(deviceId, component, capability, commandName) {
    const inspection = state.inspections.get(deviceId);
    if (!inspection || inspection.status !== "ready") {
      return false;
    }
    return !(inspection.controllable || []).some(function (item) {
      return (item.component || "main") === component && item.id === capability && (item.commands || []).some(function (command) {
        return command.name === commandName;
      });
    });
  }

  function renderRingDetail(device, deviceState, content) {
    const raw = deviceState.raw || {};
    const shell = document.createElement("section");
    shell.className = "ring-detail-screen";
    shell.appendChild(renderRingHero(deviceState, raw));
    shell.appendChild(renderRingLivePanel(device, raw));
    shell.appendChild(renderRingStatusCard(raw));
    shell.appendChild(renderDetailActions(device, deviceState));
    content.appendChild(shell);
    appendDetailError(deviceState, content);
  }

  function renderIpCameraDetail(device, deviceState, content) {
    const raw = deviceState.raw || {};
    const shell = document.createElement("section");
    shell.className = "ring-detail-screen";
    const card = document.createElement("div");
    card.className = "ring-live-card";
    const toolbar = document.createElement("div");
    toolbar.className = "ring-live-toolbar";
    const title = document.createElement("div");
    title.innerHTML = "<strong>Live feed</strong><span></span>";
    title.querySelector("span").textContent = raw.recording_enabled ? "Continuous recording enabled" : "Live view only";
    const controls = document.createElement("div"); controls.className = "ring-live-actions";
    const nvr = document.createElement("a"); nvr.className = "device-action"; nvr.href = "/cameras"; nvr.textContent = "Open NVR";
    controls.appendChild(nvr); toolbar.appendChild(title); toolbar.appendChild(controls); card.appendChild(toolbar);
    const viewport = document.createElement("div"); viewport.className = "ring-live-viewport";
    const video = document.createElement("video"); video.controls = true; video.playsInline = true; video.muted = true;
    viewport.appendChild(video); card.appendChild(viewport);
    const note = document.createElement("p"); note.className = "detail-muted ring-live-note";
    note.textContent = raw.error || "Live video is muted by default. Recording continues independently."; card.appendChild(note);
    shell.appendChild(card); shell.appendChild(renderDetailActions(device, deviceState)); content.appendChild(shell);
    if (!raw.camera_id) return;
    const url = "/api/cameras/" + raw.camera_id + "/live/index.m3u8";
    if (video.canPlayType("application/vnd.apple.mpegurl")) { video.src = url; }
    else if (window.Hls && window.Hls.isSupported()) { const player = new window.Hls({liveSyncDurationCount:2}); player.loadSource(url); player.attachMedia(video); }
  }

  function renderRingHero(deviceState, raw) {
    const hero = document.createElement("div");
    hero.className = "ring-hero";
    [
      ["Status", deviceState.isOn ? "Online" : "Offline"],
      ["Battery", raw.battery_life !== null && raw.battery_life !== undefined ? raw.battery_life : "--", raw.battery_life !== null && raw.battery_life !== undefined ? "%" : ""],
      ["Wi-Fi", raw.wifi_signal_category || raw.connection_status]
    ].forEach(function (item) {
      const metric = document.createElement("div");
      metric.innerHTML = "<span></span><strong></strong>";
      metric.querySelector("span").textContent = item[0];
      metric.querySelector("strong").textContent = formatApplianceValue(item[1], item[2] || "");
      hero.appendChild(metric);
    });
    return hero;
  }

  function renderRingLivePanel(device, raw) {
    const card = document.createElement("div");
    card.className = "ring-live-card";

    const toolbar = document.createElement("div");
    toolbar.className = "ring-live-toolbar";
    const title = document.createElement("div");
    title.innerHTML = "<strong></strong><span></span>";
    title.querySelector("strong").textContent = "Live feed";
    title.querySelector("span").textContent = raw.subscribed === false ? "Ring may require a Protect plan for recordings; snapshots can still work on supported cameras." : "Doorbell camera";

    const controls = document.createElement("div");
    controls.className = "ring-live-actions";
    const snapshotButton = document.createElement("button");
    snapshotButton.type = "button";
    snapshotButton.textContent = "Refresh image";
    snapshotButton.addEventListener("click", function () {
      refreshRingSnapshot(device.id);
    });
    const liveButton = document.createElement("button");
    liveButton.type = "button";
    liveButton.textContent = "Start live feed";
    liveButton.addEventListener("click", function () {
      startRingLiveFeed(device.id);
    });
    const stopButton = document.createElement("button");
    stopButton.type = "button";
    stopButton.textContent = "Stop live feed";
    stopButton.addEventListener("click", function () {
      stopRingLiveFeed(device.id);
    });
    controls.appendChild(snapshotButton);
    controls.appendChild(liveButton);
    controls.appendChild(stopButton);
    toolbar.appendChild(title);
    toolbar.appendChild(controls);
    card.appendChild(toolbar);

    const viewport = document.createElement("div");
    viewport.className = "ring-live-viewport";
    const image = document.createElement("img");
    image.alt = "Ring doorbell camera";
    image.loading = "lazy";
    image.src = ringSnapshotUrl(device.id);
    image.addEventListener("error", function () {
      viewport.classList.add("snapshot-error");
    });
    viewport.appendChild(image);
    const video = document.createElement("video");
    video.controls = true;
    video.playsInline = true;
    video.hidden = true;
    viewport.appendChild(video);
    const empty = document.createElement("span");
    empty.textContent = "Camera image unavailable";
    viewport.appendChild(empty);
    card.appendChild(viewport);

    const note = document.createElement("p");
    note.className = "detail-muted ring-live-note";
    note.dataset.ringLiveNote = String(device.id);
    note.textContent = "Start live feed tries Ring video and falls back to a live-refreshing camera image if Ring does not provide browser video.";
    card.appendChild(note);
    return card;
  }

  function renderRingStatusCard(raw) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle("Doorbell status"));
    const grid = document.createElement("div");
    grid.className = "appliance-setting-grid";
    [
      ["Model", raw.model],
      ["Kind", raw.kind],
      ["Connection", raw.connection_status],
      ["Wi-Fi network", raw.wifi_name],
      ["Signal", raw.wifi_signal_strength],
      ["Subscription", raw.subscribed === null || raw.subscribed === undefined ? null : raw.subscribed ? "Active" : "Not active"]
    ].forEach(function (item) {
      grid.appendChild(settingPill(item[0], item[1], ""));
    });
    card.appendChild(grid);
    return card;
  }

  function renderCudyDetail(device, deviceState, content) {
    const raw = deviceState.raw || {};
    const appliance = deviceState.appliance || {};
    const shell = document.createElement("section");
    shell.className = "router-detail-screen";
    shell.appendChild(renderRouterHero(deviceState, appliance));
    shell.appendChild(renderRouterStatusCard(device, appliance, raw));
    if (Array.isArray(appliance.meshNodes) && appliance.meshNodes.length) {
      shell.appendChild(renderRouterMeshCard(appliance));
    }
    shell.appendChild(renderDetailActions(device, deviceState));
    content.appendChild(shell);
    appendDetailError(deviceState, content);
  }

  function renderPrinterDetail(device, deviceState, content) {
    const raw = deviceState.raw || {};
    const appliance = deviceState.appliance || {};
    const shell = document.createElement("section");
    shell.className = "printer-detail-screen";
    shell.appendChild(renderPrinterHero(deviceState, appliance));
    shell.appendChild(renderPrinterInkCard(device, appliance));
    shell.appendChild(renderPrinterInfoCard(device, appliance, raw));
    if (Array.isArray(appliance.media) && appliance.media.length) {
      shell.appendChild(renderPrinterMediaCard(appliance.media));
    }
    if (Array.isArray(appliance.alerts) && appliance.alerts.length) {
      shell.appendChild(renderPrinterAlertsCard(appliance.alerts));
    }
    shell.appendChild(renderDetailActions(device, deviceState));
    if (state.showAdminDeviceDetails) {
      shell.appendChild(renderPrinterRawCard(raw));
    }
    content.appendChild(shell);
    appendDetailError(deviceState, content);
  }

  function renderPrinterHero(deviceState, appliance) {
    const hero = document.createElement("div");
    hero.className = "printer-hero";
    [
      ["Status", appliance.stale ? "Offline" : appliance.status || (deviceState.isOn ? "Online" : "Offline")],
      [appliance.supplyMetricLabel || "Lowest supply", appliance.lowestInkPercent !== null && appliance.lowestInkPercent !== undefined ? appliance.lowestInkPercent + "%" : "--"],
      ["Supplies", Array.isArray(appliance.inkLevels) ? appliance.inkLevels.length : "--"]
    ].forEach(function (item) {
      const metric = document.createElement("div");
      metric.innerHTML = "<span></span><strong></strong>";
      metric.querySelector("span").textContent = item[0];
      metric.querySelector("strong").textContent = formatApplianceValue(item[1], "");
      hero.appendChild(metric);
    });
    return hero;
  }

  function renderPrinterInkCard(device, appliance) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card printer-ink-card";
    card.appendChild(sectionTitle(appliance.supplyLabel || "Supplies"));
    const grid = document.createElement("div");
    grid.className = "printer-ink-detail-grid";
    (appliance.inkLevels || []).forEach(function (supply) {
      const item = document.createElement("div");
      item.className = "printer-supply-control";
      item.appendChild(renderInkBar(supply, false));
      if (isRefillableInkSupply(supply)) {
        const button = document.createElement("button");
        button.className = "secondary-button printer-refill-button";
        button.type = "button";
        button.textContent = "Mark refilled";
        button.addEventListener("click", function () {
          markPrinterInkRefilled(device.id, supply.color || supply.name || "");
        });
        item.appendChild(button);
      }
      grid.appendChild(item);
    });
    if (!grid.children.length) {
      const note = document.createElement("p");
      note.className = "detail-muted";
      note.textContent = appliance.stale ? "The printer is offline and no supply rows have been cached yet." : "The printer answered, but did not expose supply rows through SNMP.";
      card.appendChild(note);
    } else {
      card.appendChild(grid);
    }
    return card;
  }

  function renderPrinterInfoCard(device, appliance, raw) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle("Printer"));
    const grid = document.createElement("div");
    grid.className = "appliance-setting-grid";
    [
      ["Host", device.host],
      ["Model", appliance.model || device.model],
      ["Serial", appliance.serial],
      ["Printhead serial", appliance.printheadSerial],
      ["Firmware", appliance.firmware],
      ["Dye film", appliance.dyeFilmType],
      ["Hand feed", appliance.handFeed],
      ["System name", appliance.systemName],
      ["Last online", appliance.lastOnlineAt ? lastCheckedLabel(appliance.lastOnlineAt) : null],
      ["Checked", appliance.checkedAt ? lastCheckedLabel(appliance.checkedAt) : null],
      ["Source", raw.source],
      ["Message", appliance.message]
    ].forEach(function (item) {
      if (isBlankValue(item[1])) {
        return;
      }
      grid.appendChild(settingPill(item[0], item[1], ""));
    });
    card.appendChild(grid);
    return card;
  }

  function renderPrinterMediaCard(media) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle("Media"));
    const grid = document.createElement("div");
    grid.className = "appliance-setting-grid";
    media.forEach(function (item) {
      const value = [
        item.percent !== null && item.percent !== undefined ? item.percent + "%" : null,
        item.level !== null && item.level !== undefined ? item.level + (item.max ? " / " + item.max : "") : null,
        item.levelLabel || null,
        item.max && (item.level === null || item.level === undefined) ? "capacity " + item.max + (item.unit ? " " + item.unit : "") : null,
        item.status
      ].filter(Boolean).join(" · ");
      grid.appendChild(settingPill(item.name || "Media", value || item.description || "--", ""));
    });
    card.appendChild(grid);
    return card;
  }

  function renderPrinterAlertsCard(alerts) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle("Alerts"));
    const grid = document.createElement("div");
    grid.className = "appliance-setting-grid";
    alerts.forEach(function (alert) {
      const meta = [
        alert.severityLabel || (alert.severity !== null && alert.severity !== undefined ? "severity " + alert.severity : null),
        alert.code ? "code " + alert.code : null
      ].filter(Boolean).join(" · ");
      const value = alert.description || humanize(alert.severity) || "Printer alert";
      grid.appendChild(settingPill("Alert " + (alert.code || alert.id), meta ? value + " - " + meta : value, ""));
    });
    card.appendChild(grid);
    return card;
  }

  function renderPrinterRawCard(raw) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle("Raw printer data"));
    const pre = document.createElement("pre");
    pre.className = "printer-raw";
    pre.textContent = JSON.stringify(raw || {}, null, 2);
    card.appendChild(pre);
    return card;
  }

  function renderNestDetail(device, deviceState, content) {
    const appliance = deviceState.appliance || {};
    const shell = document.createElement("section");
    shell.className = "smartthings-fridge-screen smartthings-appliance-screen thermostat-screen";
    shell.appendChild(renderApplianceHero("thermostat", [
      ["Ambient", appliance.ambientFahrenheit ?? appliance.ambientCelsius, appliance.ambientFahrenheit !== undefined ? "°F" : "°C"],
      ["Mode", appliance.mode],
      ["HVAC", appliance.hvacStatus || appliance.connectivity]
    ]));
    shell.appendChild(renderNestSetpointCard(device, appliance));
    shell.appendChild(renderNestModeCard(device, appliance));
    shell.appendChild(renderApplianceSettingsCard("Thermostat status", [
      ["Humidity", appliance.humidity, appliance.humidity !== undefined ? "%" : ""],
      ["Eco", appliance.ecoMode],
      ["Scale", appliance.temperatureScale],
      ["Connection", appliance.connectivity],
      ["Heat", appliance.heatFahrenheit ?? appliance.heatCelsius, appliance.heatFahrenheit !== undefined ? "°F" : "°C"],
      ["Cool", appliance.coolFahrenheit ?? appliance.coolCelsius, appliance.coolFahrenheit !== undefined ? "°F" : "°C"]
    ]));
    shell.appendChild(renderDetailActions(device, deviceState));
    content.appendChild(shell);
    appendDetailError(deviceState, content);
  }

  function renderNestSetpointCard(device, appliance) {
    const card = document.createElement("div");
    card.className = "fridge-card temp-card thermostat-setpoint-card";
    card.appendChild(sectionTitle("Setpoints"));
    if (appliance.mode === "HEAT" || appliance.mode === "HEATCOOL") {
      card.appendChild(renderNestSetpointRow(device, "Heat", appliance.heatCelsius, "set-heat", "heat_celsius"));
    }
    if (appliance.mode === "COOL" || appliance.mode === "HEATCOOL") {
      card.appendChild(renderNestSetpointRow(device, "Cool", appliance.coolCelsius, "set-cool", "cool_celsius"));
    }
    if (appliance.mode !== "HEAT" && appliance.mode !== "COOL" && appliance.mode !== "HEATCOOL") {
      const note = document.createElement("p");
      note.className = "detail-muted";
      note.textContent = "Setpoints are available in heat, cool, or heat-cool mode.";
      card.appendChild(note);
    }
    return card;
  }

  function renderNestSetpointRow(device, label, celsius, command, fieldName) {
    const value = Number(celsius);
    const row = document.createElement("div");
    row.className = "temp-row";
    const text = document.createElement("div");
    text.innerHTML = "<span></span><strong></strong>";
    text.querySelector("span").textContent = label;
    text.querySelector("strong").textContent = Number.isFinite(value) ? formatApplianceValue(celsiusToFahrenheit(value), "°F") : "--";

    const controls = document.createElement("div");
    controls.className = "stepper-controls";
    const minus = stepperButton("−");
    const plus = stepperButton("+");
    minus.disabled = !Number.isFinite(value);
    plus.disabled = !Number.isFinite(value);
    minus.addEventListener("click", function () {
      sendNestCommand(device.id, command, { [fieldName]: roundCelsius(fahrenheitToCelsius(celsiusToFahrenheit(value) - 1)) });
    });
    plus.addEventListener("click", function () {
      sendNestCommand(device.id, command, { [fieldName]: roundCelsius(fahrenheitToCelsius(celsiusToFahrenheit(value) + 1)) });
    });
    controls.appendChild(minus);
    controls.appendChild(plus);
    row.appendChild(text);
    row.appendChild(controls);
    return row;
  }

  function renderNestModeCard(device, appliance) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card thermostat-mode-card";
    card.appendChild(sectionTitle("Mode"));
    const grid = document.createElement("div");
    grid.className = "fridge-feature-grid appliance-action-grid";
    (appliance.availableModes || ["HEAT", "COOL", "HEATCOOL", "OFF"]).forEach(function (mode) {
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "feature-tile appliance-command-tile";
      tile.innerHTML = "<em></em><strong></strong><small></small>";
      tile.querySelector("em").textContent = mode === appliance.mode ? "Active" : "Mode";
      tile.querySelector("strong").textContent = humanize(mode);
      tile.querySelector("small").textContent = "Nest SDM";
      tile.disabled = mode === appliance.mode;
      tile.addEventListener("click", function () {
        sendNestCommand(device.id, "set-mode", { mode: mode });
      });
      grid.appendChild(tile);
    });
    card.appendChild(grid);
    return card;
  }

  function renderRouterHero(deviceState, appliance) {
    const hero = document.createElement("div");
    hero.className = "router-hero";
    [
      ["Status", deviceState.isOn ? "Online" : "Offline"],
      ["Uptime", appliance.uptime],
      ["WAN", appliance.wan],
      ["Traffic", appliance.traffic]
    ].forEach(function (item) {
      if (isBlankValue(item[1])) {
        return;
      }
      const metric = document.createElement("div");
      metric.innerHTML = "<span></span><strong></strong>";
      metric.querySelector("span").textContent = item[0];
      metric.querySelector("strong").textContent = formatApplianceValue(item[1], "");
      hero.appendChild(metric);
    });
    return hero;
  }

  function renderRouterStatusCard(device, appliance, raw) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle("Cudy router"));
    const grid = document.createElement("div");
    grid.className = "appliance-setting-grid";
    [
      ["Host", device.host],
      ["Model", appliance.model || device.model],
      ["Status", appliance.status],
      ["Load", appliance.load],
      ["Memory", appliance.memory],
      ["Download", appliance.download],
      ["Upload", appliance.upload],
      ["Total downloaded", appliance.totalDownload],
      ["Total uploaded", appliance.totalUpload],
      ["Speed test down", appliance.speedtest && appliance.speedtest.download],
      ["Speed test up", appliance.speedtest && appliance.speedtest.upload],
      ["Speed test latency", appliance.speedtest && appliance.speedtest.latencyMs !== undefined ? appliance.speedtest.latencyMs + " ms" : null],
      ["Routes", appliance.clients],
      ["Mesh units", appliance.meshUnits],
      ["HTTP", raw.http_status],
      ["Source", raw.source || (raw.board ? "ubus" : "web probe")]
    ].forEach(function (item) {
      if (isBlankValue(item[1])) {
        return;
      }
      grid.appendChild(settingPill(item[0], item[1], ""));
    });
    card.appendChild(grid);
    return card;
  }

  function renderRouterMeshCard(appliance) {
    const card = document.createElement("div");
    card.className = "fridge-card appliance-status-card";
    card.appendChild(sectionTitle("Mesh units"));
    const grid = document.createElement("div");
    grid.className = "appliance-setting-grid";
    appliance.meshNodes.forEach(function (node) {
      const title = (node.name || node.id || "Mesh unit") + (node.isMain ? " · Main" : "");
      const details = [
        node.ip,
        node.model,
        node.state,
        node.firmware ? "FW " + node.firmware : ""
      ].filter(Boolean).join(" · ");
      grid.appendChild(settingPill(title, details || node.id, ""));
    });
    card.appendChild(grid);
    return card;
  }

  function ringSnapshotUrl(deviceId) {
    return "/devices/" + deviceId + "/ring/snapshot?t=" + encodeURIComponent(Date.now());
  }

  function ringTileSnapshotUrl(deviceId) {
    return "/devices/" + deviceId + "/ring/snapshot/cached?t=" + encodeURIComponent(Date.now());
  }

  function refreshRingSnapshot(deviceId) {
    const image = elements.deviceDetailContent.querySelector(".ring-live-viewport img");
    const viewport = elements.deviceDetailContent.querySelector(".ring-live-viewport");
    if (!image || !viewport) {
      return;
    }
    viewport.classList.remove("snapshot-error");
    image.src = ringSnapshotUrl(deviceId);
    showBanner("Ring camera image refreshed.", "success");
  }

  async function startRingLiveFeed(deviceId) {
    const note = elements.deviceDetailContent.querySelector("[data-ring-live-note=\"" + deviceId + "\"]");
    const video = elements.deviceDetailContent.querySelector(".ring-live-viewport video");
    const image = elements.deviceDetailContent.querySelector(".ring-live-viewport img");
    if (note) {
      note.textContent = "Starting Ring WebRTC live feed...";
    }
    startRingSnapshotFeed(deviceId, image, note);
    scheduleRingVideoFallback(deviceId, 6000);
    await tryStartRingWebRtcFeed(deviceId, video, image, note);
  }

  async function tryStartRingWebRtcFeed(deviceId, video, image, note) {
    try {
      await startRingWebRtcFeed(deviceId, video, image, note);
    } catch (error) {
      if (note) {
        note.textContent = "Live camera image is refreshing. Ring video error: " + (error.message || "video stream failed.");
      }
      showBanner(error.message || "Ring live feed failed.", "error");
    }
  }

  async function startRingWebRtcFeed(deviceId, video, image, note) {
    if (!window.RTCPeerConnection) {
      throw new Error("This browser does not support WebRTC live video.");
    }
    await closeRingWebRtcFeed(deviceId);
    window.__ringLiveDebug = {
      deviceId: deviceId,
      candidatesSent: 0,
      candidatesReceived: 0,
      connectionState: "",
      iceConnectionState: "",
      iceGatheringState: "",
      tracks: 0,
      readyState: 0,
      messages: []
    };
    const peer = new RTCPeerConnection({
      iceServers: [
        { urls: "stun:stun.l.google.com:19302" },
        { urls: "stun:stun1.l.google.com:19302" }
      ]
    });
    peer.__ringDeviceId = deviceId;
    const pendingCandidates = [];
    const connection = { peer: peer, sessionId: "", pendingCandidates: pendingCandidates };
    state.ringPeerConnections.set(deviceId, connection);

    peer.addTransceiver("video", { direction: "recvonly" });
    peer.addTransceiver("audio", { direction: "recvonly" });
    peer.onicecandidate = function (event) {
      if (!event.candidate) {
        return;
      }
      window.__ringLiveDebug.candidatesSent += 1;
      const current = state.ringPeerConnections.get(deviceId);
      if (!current || !current.sessionId) {
        pendingCandidates.push(event.candidate);
        return;
      }
      sendRingIceCandidate(deviceId, current.sessionId, event.candidate);
    };
    peer.ontrack = function (event) {
      if (!video) {
        return;
      }
      video.srcObject = event.streams[0];
      video.onloadeddata = function () {
        stopRingSnapshotFeed(deviceId);
        video.hidden = false;
        window.__ringLiveDebug.readyState = video.readyState;
        if (image) {
          image.hidden = true;
        }
        if (note) {
          note.textContent = "Live feed started through Ring WebRTC.";
        }
      };
      video.onplaying = video.onloadeddata;
      video.play().catch(function () {});
      if (note) {
        note.textContent = "Ring video track found; waiting for picture...";
      }
      window.__ringLiveDebug.tracks += 1;
      window.__ringLiveDebug.messages.push("track");
    };
    peer.onconnectionstatechange = function () {
      window.__ringLiveDebug.connectionState = peer.connectionState;
      if (!note) {
        return;
      }
      if (peer.connectionState === "connecting") {
        note.textContent = state.ringSnapshotTimers.has(deviceId)
          ? "Live camera image is refreshing while Ring video connects..."
          : "Connecting Ring live feed...";
      }
      if (peer.connectionState === "connected") {
        if (!attachRingRemoteStream(peer, video, image, note)) {
          showRingSnapshotFallback(deviceId);
        }
      }
      if (peer.connectionState === "failed" || peer.connectionState === "disconnected") {
        note.textContent = "Ring video disconnected. Live camera image refresh still works.";
      }
    };
    peer.oniceconnectionstatechange = function () {
      window.__ringLiveDebug.iceConnectionState = peer.iceConnectionState;
      if (!note) {
        return;
      }
      if (peer.iceConnectionState === "checking") {
        note.textContent = state.ringSnapshotTimers.has(deviceId)
          ? "Live camera image is refreshing while Ring video connects..."
          : "Checking Ring live video connection...";
      }
      if (peer.iceConnectionState === "connected" || peer.iceConnectionState === "completed") {
        if (!attachRingRemoteStream(peer, video, image, note)) {
          showRingSnapshotFallback(deviceId);
        }
      }
    };
    peer.onicegatheringstatechange = function () {
      window.__ringLiveDebug.iceGatheringState = peer.iceGatheringState;
    };

    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);

    const answer = await requestJson("/devices/" + deviceId + "/ring/webrtc/offer", {
      method: "POST",
      body: JSON.stringify({ sdp_offer: peer.localDescription.sdp })
    });
    connection.sessionId = answer.session_id || "";
    state.ringPeerConnections.set(deviceId, connection);
    await peer.setRemoteDescription({ type: "answer", sdp: answer.sdp_answer });
    pollRingWebRtcMessages(deviceId, connection.sessionId, peer, note);
    attachRingRemoteStream(peer, video, image, note);
    pendingCandidates.splice(0).forEach(function (candidate) {
      sendRingIceCandidate(deviceId, connection.sessionId, candidate);
    });
    if (note) {
      note.textContent = state.ringSnapshotTimers.has(deviceId)
        ? "Live camera image is refreshing while Ring video connects..."
        : "Connecting Ring live feed...";
    }
    showBanner("Ring live feed connecting.", "success");
  }

  function scheduleRingVideoFallback(deviceId, delayMs) {
    window.setTimeout(function () {
      showRingSnapshotFallback(deviceId);
    }, delayMs);
  }

  function showRingSnapshotFallback(deviceId) {
    const currentVideo = elements.deviceDetailContent.querySelector(".ring-live-viewport video");
    const currentImage = elements.deviceDetailContent.querySelector(".ring-live-viewport img");
    const currentNote = elements.deviceDetailContent.querySelector("[data-ring-live-note=\"" + deviceId + "\"]");
    if (!state.ringSnapshotTimers.has(deviceId) || !currentVideo || currentVideo.readyState > 0) {
      return;
    }
    currentVideo.hidden = true;
    currentVideo.srcObject = null;
    if (currentImage) {
      currentImage.hidden = false;
      currentImage.src = ringSnapshotUrl(deviceId);
    }
    if (currentNote) {
      currentNote.textContent = "Ring video is not providing frames here, so Sentinel is showing a live-refreshing camera image.";
    }
  }

  async function pollRingWebRtcMessages(deviceId, sessionId, peer, note) {
    let cursor = 0;
    while (state.ringPeerConnections.get(deviceId)?.sessionId === sessionId) {
      try {
        const response = await requestJson("/devices/" + deviceId + "/ring/webrtc/" + encodeURIComponent(sessionId) + "/messages?since=" + encodeURIComponent(cursor));
        cursor = response.next ?? cursor;
        for (const message of response.messages || []) {
          if (message.type === "candidate" && message.candidate) {
            window.__ringLiveDebug.candidatesReceived += 1;
            await peer.addIceCandidate({
              candidate: message.candidate,
              sdpMLineIndex: message.sdp_m_line_index || 0
            }).catch(function () {});
          }
          if (message.type === "error" && note) {
            note.textContent = message.error_message || "Ring live feed failed.";
          }
          if (message.type === "closed" && note) {
            note.textContent = message.error_message || "Ring live feed closed.";
            return;
          }
        }
      } catch (error) {
        if (note) {
          note.textContent = error.message || "Ring live feed message polling failed.";
        }
        return;
      }
      await new Promise(function (resolve) {
        window.setTimeout(resolve, 700);
      });
    }
  }

  function attachRingRemoteStream(peer, video, image, note) {
    if (!video || video.srcObject) {
      return Boolean(video?.srcObject);
    }
    const tracks = peer.getReceivers().map(function (receiver) {
      return receiver.track;
    }).filter(Boolean);
    if (!tracks.length) {
      return false;
    }
    video.srcObject = new MediaStream(tracks);
    video.onloadeddata = function () {
      stopRingSnapshotFeed(peer.__ringDeviceId);
      video.hidden = false;
      if (image) {
        image.hidden = true;
      }
      if (note) {
        note.textContent = "Ring live feed connected.";
      }
    };
    video.onplaying = video.onloadeddata;
    video.play().catch(function () {});
    if (note) {
      note.textContent = "Ring video connected; waiting for picture...";
    }
    return true;
  }

  async function sendRingIceCandidate(deviceId, sessionId, candidate) {
    if (!sessionId || !candidate?.candidate) {
      return;
    }
    await fetch("/devices/" + deviceId + "/ring/webrtc/" + encodeURIComponent(sessionId) + "/candidate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        candidate: candidate.candidate,
        sdp_m_line_index: candidate.sdpMLineIndex || 0
      })
    }).catch(function () {});
  }

  async function closeRingWebRtcFeed(deviceId) {
    const current = state.ringPeerConnections.get(deviceId);
    if (!current) {
      return;
    }
    state.ringPeerConnections.delete(deviceId);
    try {
      current.peer.close();
    } catch (error) {}
    if (current.sessionId) {
      await fetch("/devices/" + deviceId + "/ring/webrtc/" + encodeURIComponent(current.sessionId), {
        method: "DELETE"
      }).catch(function () {});
    }
  }

  async function stopRingLiveFeed(deviceId) {
    await closeRingWebRtcFeed(deviceId);
    stopRingSnapshotFeed(deviceId);
    const note = elements.deviceDetailContent.querySelector("[data-ring-live-note=\"" + deviceId + "\"]");
    const video = elements.deviceDetailContent.querySelector(".ring-live-viewport video");
    const image = elements.deviceDetailContent.querySelector(".ring-live-viewport img");
    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.srcObject = null;
      video.hidden = true;
    }
    if (image) {
      image.hidden = false;
    }
    if (note) {
      note.textContent = "Live feed stopped. Refresh image is still available.";
    }
  }

  function startRingSnapshotFeed(deviceId, image, note) {
    stopRingSnapshotFeed(deviceId);
    if (!image) {
      return;
    }
    image.hidden = false;
    image.src = ringSnapshotUrl(deviceId);
    const timer = window.setInterval(function () {
      image.src = ringSnapshotUrl(deviceId);
    }, 8000);
    state.ringSnapshotTimers.set(deviceId, timer);
    if (note) {
      note.textContent = "Live snapshot feed running. Ring video is connecting...";
    }
  }

  function stopRingSnapshotFeed(deviceId) {
    const timer = state.ringSnapshotTimers.get(deviceId);
    if (!timer) {
      return;
    }
    window.clearInterval(timer);
    state.ringSnapshotTimers.delete(deviceId);
  }

  function closeAllRingWebRtcFeeds() {
    Array.from(state.ringPeerConnections.keys()).forEach(function (deviceId) {
      closeRingWebRtcFeed(deviceId);
    });
    Array.from(state.ringSnapshotTimers.keys()).forEach(function (deviceId) {
      stopRingSnapshotFeed(deviceId);
    });
  }

  function firstPlayableRingUrl(payload) {
    const urls = [];
    collectRingUrls(payload, urls);
    return urls.find(function (url) {
      return /\.(m3u8|mp4|webm)(\?|$)/i.test(url) || url.includes(".m3u8") || url.includes("playlist");
    }) || "";
  }

  function collectRingUrls(value, urls) {
    if (!value) {
      return;
    }
    if (typeof value === "string") {
      if (/^https?:\/\//i.test(value)) {
        urls.push(value);
      }
      return;
    }
    if (Array.isArray(value)) {
      value.forEach(function (item) {
        collectRingUrls(item, urls);
      });
      return;
    }
    if (typeof value === "object") {
      Object.keys(value).forEach(function (key) {
        collectRingUrls(value[key], urls);
      });
    }
  }

  function renderViewInsidePanel(device, main) {
    const wrapper = document.createElement("div");
    wrapper.className = "fridge-camera-wrap";
    const toolbar = document.createElement("div");
    toolbar.className = "fridge-camera-toolbar";
    const title = document.createElement("strong");
    title.textContent = "View Inside";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Refresh live view";
    button.addEventListener("click", function () {
      refreshViewInside(device.id);
    });
    toolbar.appendChild(title);
    toolbar.appendChild(button);
    wrapper.appendChild(toolbar);

    const panel = document.createElement("div");
    panel.className = "fridge-camera-card";
    const contents = valueAt(main, "samsungce.viewInside", "contents") || [];
    const imageCount = Array.isArray(contents) ? contents.length : 0;

    if (imageCount) {
      contents.slice(0, 3).forEach(function (item, index) {
        const slot = document.createElement("div");
        slot.className = "fridge-camera-slot";
        const image = document.createElement("img");
        image.alt = "Fridge view " + (index + 1);
        image.loading = "lazy";
        image.src = "/devices/" + device.id + "/smartthings/view-inside/images/" + encodeURIComponent(item.fileId) + "?t=" + encodeURIComponent(item.expiredTime || Date.now());
        image.addEventListener("error", function () {
          slot.classList.add("image-unavailable");
          image.remove();
        });
        const art = document.createElement("div");
        const label = document.createElement("span");
        slot.appendChild(image);
        slot.appendChild(art);
        slot.appendChild(label);
        slot.querySelector("span").textContent = (item.focusArea ? humanize(item.focusArea) : "View inside") + " " + (index + 1);
        panel.appendChild(slot);
      });
    } else {
      const empty = document.createElement("div");
      empty.className = "fridge-camera-empty";
      empty.textContent = "View Inside images unavailable";
      panel.appendChild(empty);
    }
    wrapper.appendChild(panel);

    const updated = valueAt(main, "samsungce.viewInside", "lastUpdatedTime");
    if (updated) {
      const caption = document.createElement("p");
      caption.className = "fridge-camera-caption";
      caption.textContent = "Last updated " + new Date(updated).toLocaleString();
      wrapper.appendChild(caption);
    }
    return wrapper;
  }

  function renderTemperatureCard(device, appliance, cooler, freezer) {
    const card = document.createElement("div");
    card.className = "fridge-card temp-card";
    card.appendChild(renderTemperatureRow(device, "Fridge", appliance.coolerSetpoint ?? appliance.coolerTemp, cooler, "cooler"));
    card.appendChild(renderTemperatureRow(device, "Freezer", appliance.freezerSetpoint ?? appliance.freezerTemp, freezer, "freezer"));
    return card;
  }

  function renderTemperatureRow(device, label, value, component, componentId) {
    const range = valueAt(component, "thermostatCoolingSetpoint", "coolingSetpointRange") || {};
    const row = document.createElement("div");
    row.className = "temp-row";
    const text = document.createElement("div");
    text.innerHTML = "<span></span><strong></strong>";
    text.querySelector("span").textContent = label;
    text.querySelector("strong").textContent = formatApplianceValue(value, "°F");

    const controls = document.createElement("div");
    controls.className = "stepper-controls";
    const minus = stepperButton("−");
    const plus = stepperButton("+");
    minus.addEventListener("click", function () {
      sendSmartThingsCommand(device.id, componentId, "thermostatCoolingSetpoint", "setCoolingSetpoint", [
        clampSetpoint(Number(value) - Number(range.step || 1), range)
      ]);
    });
    plus.addEventListener("click", function () {
      sendSmartThingsCommand(device.id, componentId, "thermostatCoolingSetpoint", "setCoolingSetpoint", [
        clampSetpoint(Number(value) + Number(range.step || 1), range)
      ]);
    });
    controls.appendChild(minus);
    controls.appendChild(plus);
    row.appendChild(text);
    row.appendChild(controls);
    return row;
  }

  function renderFeatureTiles(device, appliance) {
    const grid = document.createElement("div");
    grid.className = "fridge-feature-grid";
    grid.appendChild(featureTile("❄", "Power cool", appliance.powerCool ? "On" : "Off", function () {
      sendSmartThingsCommand(device.id, "main", "samsungce.powerCool", appliance.powerCool ? "deactivate" : "activate", []);
    }));
    grid.appendChild(featureTile("✳", "Power freeze", appliance.powerFreeze ? "On" : "Off", function () {
      sendSmartThingsCommand(device.id, "main", "samsungce.powerFreeze", appliance.powerFreeze ? "deactivate" : "activate", []);
    }));
    return grid;
  }

  function renderFlexZoneCard(device, cvroom) {
    const modes = valueAt(cvroom, "custom.fridgeMode", "supportedFridgeModes") || valueAt(cvroom, "custom.fridgeMode", "supportedFullFridgeModes") || [];
    const current = valueAt(cvroom, "custom.fridgeMode", "fridgeMode");
    const card = document.createElement("div");
    card.className = "fridge-card flex-card";
    const label = document.createElement("span");
    label.textContent = "FlexZone™";
    card.appendChild(label);
    if (Array.isArray(modes) && modes.length) {
      const select = document.createElement("select");
      modes.forEach(function (mode) {
        const option = document.createElement("option");
        option.value = mode;
        option.textContent = flexZoneLabel(mode);
        option.selected = mode === current;
        select.appendChild(option);
      });
      select.addEventListener("change", function () {
        sendSmartThingsCommand(device.id, "cvroom", "custom.fridgeMode", "setFridgeMode", [select.value]);
      });
      card.appendChild(select);
    } else {
      const strong = document.createElement("strong");
      strong.textContent = flexZoneLabel(current);
      card.appendChild(strong);
    }
    return card;
  }

  function renderIceMakerCard(device, components) {
    const card = document.createElement("div");
    card.className = "fridge-card switch-card";
    const label = document.createElement("span");
    label.textContent = "Ice maker";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "smart-toggle";
    const current = valueAt(components.icemaker || {}, "switch", "switch");
    toggle.dataset.on = current === "on" ? "true" : "false";
    toggle.setAttribute("aria-label", "Toggle ice maker");
    toggle.addEventListener("click", function () {
      sendSmartThingsCommand(device.id, "icemaker", "switch", current === "on" ? "off" : "on", []);
    });
    card.appendChild(label);
    card.appendChild(toggle);
    return card;
  }

  function renderFridgeTabs(device, appliance, main) {
    const wrapper = document.createElement("div");
    wrapper.className = "fridge-tabs";
    const tabs = document.createElement("div");
    tabs.className = "tab-row";
    const control = document.createElement("button");
    control.type = "button";
    control.className = "is-active";
    control.textContent = "Device control";
    const service = document.createElement("button");
    service.type = "button";
    service.textContent = "Service";
    tabs.appendChild(control);
    tabs.appendChild(service);

    const servicePanel = document.createElement("div");
    servicePanel.className = "service-panel";
    servicePanel.hidden = true;
    servicePanel.appendChild(renderServiceCards(device, appliance, main));

    control.addEventListener("click", function () {
      control.classList.add("is-active");
      service.classList.remove("is-active");
      servicePanel.hidden = true;
    });
    service.addEventListener("click", function () {
      service.classList.add("is-active");
      control.classList.remove("is-active");
      servicePanel.hidden = false;
    });

    wrapper.appendChild(tabs);
    wrapper.appendChild(servicePanel);
    return wrapper;
  }

  function renderServiceCards(device, appliance, main) {
    const container = document.createElement("div");
    container.className = "service-card-stack";
    const filterUsage = Number(appliance.waterFilterUsage || 0);
    const filterStatus = appliance.waterFilterStatus === "replace" ? "Needs to be replaced" : humanize(appliance.waterFilterStatus || "OK");
    const care = document.createElement("div");
    care.className = "service-card";
    care.innerHTML = "<h4>Care status</h4><span>Water filter</span><strong></strong><div class=\"filter-bar\"><i></i></div>";
    care.querySelector("strong").textContent = filterStatus;
    care.querySelector("i").style.width = String(Math.max(0, Math.min(100, 100 - filterUsage))) + "%";
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "service-button";
    reset.textContent = "Reset filter usage";
    reset.addEventListener("click", function () {
      sendSmartThingsCommand(device.id, "main", "custom.waterFilter", "resetWaterFilter", []);
    });
    care.appendChild(reset);
    container.appendChild(care);

    const energy = valueAt(main, "powerConsumptionReport", "powerConsumption") || {};
    const energyCard = document.createElement("div");
    energyCard.className = "service-card";
    energyCard.innerHTML = "<h4>Energy usage</h4><span>Current power</span><strong></strong>";
    energyCard.querySelector("strong").textContent = energy.power !== undefined ? energy.power + " W" : "--";
    container.appendChild(energyCard);
    return container;
  }

  function featureTile(icon, label, value, handler) {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "feature-tile";
    tile.innerHTML = "<span></span><em></em><strong></strong>";
    tile.querySelector("span").textContent = icon;
    tile.querySelector("em").textContent = label;
    tile.querySelector("strong").textContent = value;
    tile.addEventListener("click", handler);
    return tile;
  }

  function stepperButton(label) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "stepper-button";
    button.textContent = label;
    return button;
  }

  function clampSetpoint(value, range) {
    const minimum = range.minimum !== undefined ? Number(range.minimum) : value;
    const maximum = range.maximum !== undefined ? Number(range.maximum) : value;
    return Math.max(minimum, Math.min(maximum, value));
  }

  async function sendSmartThingsCommand(deviceId, component, capability, command, args) {
    try {
      const result = await requestJson("/devices/" + deviceId + "/smartthings/command", {
        method: "POST",
        body: JSON.stringify({
          component: component,
          capability: capability,
          command: command,
          arguments: args || []
        })
      });
      showBanner(result.message || "Action sent.", "success");
      await refreshOneDevice(deviceId);
    } catch (error) {
      showBanner(error.message || "Action failed.", "error");
    }
  }

  async function sendNestCommand(deviceId, command, fields) {
    try {
      const result = await requestJson("/devices/" + deviceId + "/nest/command", {
        method: "POST",
        body: JSON.stringify(Object.assign({ command: command }, fields || {}))
      });
      showBanner(result.message || "Nest command sent.", "success");
      await refreshOneDevice(deviceId);
    } catch (error) {
      showBanner(error.message || "Nest command failed.", "error");
    }
  }

  function celsiusToFahrenheit(value) {
    return Math.round(((Number(value) * 9 / 5) + 32) * 10) / 10;
  }

  function fahrenheitToCelsius(value) {
    return (Number(value) - 32) * 5 / 9;
  }

  function roundCelsius(value) {
    return Math.round(Number(value) * 10) / 10;
  }

  async function refreshViewInside(deviceId) {
    showBanner("Refreshing fridge live view...", "success");
    try {
      const result = await requestJson("/devices/" + deviceId + "/smartthings/view-inside/refresh", {
        method: "POST"
      });
      const device = state.devices.find(function (item) {
        return item.id === deviceId;
      });
      if (device) {
        state.states.set(deviceId, checkedDeviceState({
          status: stateStatus(device, result),
          isOn: result.is_on,
          isOpen: result.is_open,
          luminance: result.luminance,
          appliance: result.appliance,
          raw: result.raw,
          error: ""
        }));
        renderDeviceDetail(device);
      }
      showBanner("Fridge live view refreshed.", "success");
    } catch (error) {
      showBanner(error.message || "Live view refresh failed.", "error");
    } finally {
      render();
    }
  }

  function valueAt(component, capability, attribute) {
    return component?.[capability]?.[attribute]?.value;
  }

  function flexZoneLabel(value) {
    const labels = {
      CV_FHUB_FREEZER: "Freeze",
      CV_FHUB_SOFT_FREEZER: "Soft Freeze",
      CV_FHUB_MEAT_FISH: "Meat/Fish",
      CV_FHUB_VEGETABLE_CHEESE: "Veggie/Cheese",
      CV_FHUB_BEER: "Beverage"
    };
    return labels[value] || humanize(value || "Freeze");
  }

  function renderDetailActions(device, deviceState) {
    const actions = document.createElement("div");
    actions.className = "detail-actions";
    if (isCudy(device)) {
      actions.appendChild(actionButton("Stats", "cudy-stats", device.id, deviceState.status));
      actions.appendChild(actionButton("Speed test", "cudy-speedtest", device.id, deviceState.status));
      actions.appendChild(actionButton("Credentials", "cudy-credentials", device.id, deviceState.status));
      actions.appendChild(actionButton("Reboot", "cudy-reboot", device.id, deviceState.status));
      actions.appendChild(actionButton("Refresh", "refresh", device.id, deviceState.status));
    } else if (isAppliance(device) || isSensor(device) || isRing(device) || isIpCamera(device) || isNest(device) || isPrinter(device)) {
      actions.appendChild(actionButton("Refresh", "refresh", device.id, deviceState.status));
      if (device.brand === "smartthings") {
        actions.appendChild(actionButton("Find actions", "inspect", device.id, deviceState.status));
      }
    } else if (isLock(device)) {
      actions.appendChild(actionButton("Lock", "lock", device.id, deviceState.status));
      actions.appendChild(actionButton("Unlock", "unlock", device.id, deviceState.status));
      actions.appendChild(actionButton("Refresh", "refresh", device.id, deviceState.status));
    } else if (isGarage(device)) {
      actions.appendChild(actionButton("Open", "open", device.id, deviceState.status));
      actions.appendChild(actionButton("Close", "close", device.id, deviceState.status));
      actions.appendChild(actionButton("Refresh", "refresh", device.id, deviceState.status));
    } else {
      actions.appendChild(actionButton("On", "turn-on", device.id, deviceState.status));
      actions.appendChild(actionButton("Off", "turn-off", device.id, deviceState.status));
      actions.appendChild(actionButton("Toggle", "toggle", device.id, deviceState.status));
    }
    if (isInlineSwitchTile(device)) {
      const nextLabel = tileLayoutForDevice(device) === "compact" ? "Use large tile" : "Use compact tile";
      actions.appendChild(actionButton(nextLabel, "tile-size", device.id, "ready"));
    } else if (isCameraTile(device)) {
      const nextLabel = tileLayoutForDevice(device) === "landscape" ? "Use normal tile" : "Use landscape tile";
      actions.appendChild(actionButton(nextLabel, "tile-size", device.id, "ready"));
    }
    return actions;
  }

  function renderSmartThingsDetailControls(device, options) {
    const section = document.createElement("section");
    section.className = options?.compact ? "fridge-card fridge-actions-card" : "detail-section";
    section.appendChild(sectionTitle(options?.compact ? "More controls" : "Actions"));
    const inspection = state.inspections.get(device.id);

    if (!inspection || inspection.status === "loading") {
      const loading = document.createElement("p");
      loading.className = "detail-muted";
      loading.textContent = "Checking available SmartThings controls...";
      section.appendChild(loading);
      return section;
    }
    if (inspection.status === "error") {
      const error = document.createElement("p");
      error.className = "device-error";
      error.textContent = inspection.error || "Could not load SmartThings controls.";
      section.appendChild(error);
      return section;
    }

    const groups = friendlyCommandGroups(inspection);
    if (!groups.length) {
      const empty = document.createElement("p");
      empty.className = "detail-muted";
      empty.textContent = "No safe dashboard actions are exposed for this device yet.";
      section.appendChild(empty);
    } else {
      groups.forEach(function (group) {
        const groupSection = document.createElement("div");
        groupSection.className = "friendly-command-section";
        const heading = document.createElement("h4");
        heading.textContent = group.title;
        groupSection.appendChild(heading);
        if (group.note) {
          const note = document.createElement("p");
          note.className = "detail-muted";
          note.textContent = group.note;
          groupSection.appendChild(note);
        }
        const grid = document.createElement("div");
        grid.className = "friendly-command-grid";
        group.controls.forEach(function (control) {
          grid.appendChild(renderFriendlyCommandForm(device, control.capability, control.command));
        });
        groupSection.appendChild(grid);
        section.appendChild(groupSection);
      });
    }

    if (!options?.hideAdvanced) {
      const raw = document.createElement("details");
      raw.className = "detail-advanced";
      const summary = document.createElement("summary");
      summary.textContent = "Advanced capability list";
      raw.appendChild(summary);
      raw.appendChild(renderCapabilityGroup("Controllable", inspection.controllable || [], true, inspection.deviceId));
      raw.appendChild(renderCapabilityGroup("Status only", inspection.statusOnly || [], false));
      section.appendChild(raw);
    }
    return section;
  }

  function friendlyCommandGroups(inspection) {
    const controls = [];
    (inspection.controllable || []).forEach(function (capability) {
      if (!isDashboardCommandCapability(capability)) {
        return;
      }
      (capability.commands || []).forEach(function (command) {
        if (isFriendlyCommand(capability, command)) {
          controls.push({
            capability: capability,
            command: command,
            category: friendlyCommandCategory(capability, command),
            priority: friendlyCommandPriority(capability, command)
          });
        }
      });
    });
    controls.sort(function (left, right) {
      return left.priority - right.priority || friendlyCommandTitle(left.capability, left.command).localeCompare(friendlyCommandTitle(right.capability, right.command));
    });

    const grouped = [];
    controls.slice(0, 36).forEach(function (control) {
      let group = grouped.find(function (item) {
        return item.key === control.category.key;
      });
      if (!group) {
        group = {
          key: control.category.key,
          title: control.category.title,
          note: control.category.note || "",
          controls: []
        };
        grouped.push(group);
      }
      group.controls.push(control);
    });
    return grouped;
  }

  function isFriendlyCommand(capability, command) {
    const args = command.arguments || [];
    if (!applianceControlCapabilities.has(capability.id)) {
      return false;
    }
    if (args.length > 3) {
      return false;
    }
    if (capability.id === "execute") {
      return false;
    }
    return args.every(function (argument) {
      return argument.options || argument.type === "integer" || argument.type === "number" || argument.type === "string" || !argument.type;
    });
  }

  function friendlyCommandCategory(capability, command) {
    if (capability.id === "audioNotification") {
      return {
        key: "audio",
        title: "Audio",
        note: "This plays a reachable audio URL on the appliance. It is not live computer speaker streaming."
      };
    }
    if (capability.id === "samsungce.audioVolumeLevel") {
      return { key: "audio", title: "Audio" };
    }
    if (capability.id.includes("waterFilter")) {
      return { key: "filter", title: "Water filter" };
    }
    if (capability.id.includes("refrigeration") || capability.id.includes("powerCool") || capability.id.includes("powerFreeze") || capability.id.includes("fridge") || capability.id.includes("freezer") || capability.component === "cooler" || capability.component === "freezer" || capability.component === "pantry-01" || capability.component === "icemaker" || capability.component.indexOf("icemaker") === 0) {
      return { key: "cooling", title: "Cooling and zones" };
    }
    if (capability.id.includes("oven") || capability.id.includes("microwave") || capability.id.includes("hood") || capability.id === "samsungce.lamp") {
      return { key: "cooking", title: "Cooking" };
    }
    if (capability.id.includes("washer") || capability.id.includes("dryer") || capability.id.includes("Detergent") || capability.id.includes("Softener") || capability.id.includes("supportedOptions")) {
      return { key: "laundry", title: "Laundry" };
    }
    if (capability.id === "switch" || capability.id === "samsungce.switch") {
      return { key: "switches", title: "Switches" };
    }
    return { key: "other", title: "Other actions" };
  }

  function friendlyCommandPriority(capability, command) {
    const key = capability.id + "." + command.name;
    const exact = {
      "refrigeration.setRapidCooling": 10,
      "refrigeration.setRapidFreezing": 11,
      "refrigeration.setDefrost": 12,
      "samsungce.powerCool.activate": 13,
      "samsungce.powerCool.deactivate": 14,
      "samsungce.powerFreeze.activate": 15,
      "samsungce.powerFreeze.deactivate": 16,
      "thermostatCoolingSetpoint.setCoolingSetpoint": 20,
      "custom.waterFilter.resetWaterFilter": 30,
      "audioNotification.playTrack": 40,
      "audioNotification.playTrackAndRestore": 41,
      "audioNotification.playTrackAndResume": 42,
      "ovenMode.setOvenMode": 50,
      "samsungce.ovenMode.setOvenMode": 51,
      "ovenSetpoint.setOvenSetpoint": 52,
      "ovenOperatingState.start": 53,
      "samsungce.ovenOperatingState.start": 54,
      "ovenOperatingState.stop": 55,
      "samsungce.ovenOperatingState.stop": 56,
      "samsungce.microwavePower.setPowerLevel": 57,
      "custom.washerWaterTemperature.setWasherWaterTemperature": 70,
      "custom.washerSpinLevel.setWasherSpinLevel": 71,
      "custom.washerSoilLevel.setWasherSoilLevel": 72,
      "samsungce.washerOperatingState.start": 73,
      "samsungce.washerOperatingState.pause": 74,
      "samsungce.washerOperatingState.resume": 75,
      "samsungce.washerOperatingState.cancel": 76
    };
    if (exact[key] !== undefined) {
      return exact[key];
    }
    if (capability.component === "freezer") {
      return 21;
    }
    if (capability.component === "cooler") {
      return 22;
    }
    return 100;
  }

  function renderFriendlyCommandForm(device, capability, command) {
    const form = document.createElement("form");
    form.className = "friendly-command";
    form.dataset.deviceId = String(device.id);
    form.dataset.component = capability.component || "main";
    form.dataset.capability = capability.id;
    form.dataset.command = command.name;

    const header = document.createElement("div");
    header.className = "friendly-command-header";
    const title = document.createElement("strong");
    title.textContent = friendlyCommandTitle(capability, command);
    const caption = document.createElement("span");
    caption.textContent = friendlyCapabilityTitle(capability.id, capability.component);
    header.appendChild(title);
    header.appendChild(caption);
    form.appendChild(header);

    (command.arguments || []).forEach(function (argument, index) {
      form.appendChild(renderCommandArgument(argument, index));
    });

    const button = document.createElement("button");
    button.type = "submit";
    button.className = "command-send";
    button.textContent = "Run";
    form.appendChild(button);
    form.addEventListener("submit", handleFriendlyCommandSubmit);
    return form;
  }

  async function handleFriendlyCommandSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const deviceId = Number(form.dataset.deviceId);
    let args;
    try {
      args = collectCommandArguments(form);
    } catch (error) {
      showBanner(error.message || "Check action values.", "error");
      return;
    }

    const button = form.querySelector("button");
    button.disabled = true;
    button.textContent = "Running...";
    try {
      const result = await requestJson("/devices/" + deviceId + "/smartthings/command", {
        method: "POST",
        body: JSON.stringify({
          component: form.dataset.component,
          capability: form.dataset.capability,
          command: form.dataset.command,
          arguments: args
        })
      });
      showBanner(result.message || "Action sent.", "success");
      await refreshOneDevice(deviceId);
      const device = state.devices.find(function (item) {
        return item.id === deviceId;
      });
      if (device && elements.deviceDetailDialog.open) {
        renderDeviceDetail(device);
      }
    } catch (error) {
      showBanner(error.message || "Action failed.", "error");
    } finally {
      button.disabled = false;
      button.textContent = "Run";
    }
  }

  function friendlyCapabilityTitle(capabilityId, component) {
    const base = friendlyCapabilityNames[capabilityId] || humanize(capabilityId);
    const componentLabel = friendlyComponentLabel(component);
    return componentLabel ? componentLabel + " · " + base : base;
  }

  function friendlyCommandTitle(capability, command) {
    if ((capability.id === "samsungce.powerCool" || capability.id === "samsungce.powerFreeze") && command.name === "activate") {
      return friendlyCapabilityTitle(capability.id, capability.component) + " on";
    }
    if ((capability.id === "samsungce.powerCool" || capability.id === "samsungce.powerFreeze") && command.name === "deactivate") {
      return friendlyCapabilityTitle(capability.id, capability.component) + " off";
    }
    if (capability.id === "custom.waterFilter" && command.name === "resetWaterFilter") {
      return "Reset water filter";
    }
    if (capability.id === "refrigeration" && command.name === "setRapidCooling") {
      return "Rapid cool";
    }
    if (capability.id === "refrigeration" && command.name === "setRapidFreezing") {
      return "Rapid freeze";
    }
    if (capability.id === "refrigeration" && command.name === "setDefrost") {
      return "Defrost mode";
    }
    if (capability.id === "thermostatCoolingSetpoint" && command.name === "setCoolingSetpoint") {
      return "Set " + (friendlyComponentLabel(capability.component) || "zone") + " temperature";
    }
    return friendlyCommandNames[command.name] || humanize(command.name || capability.id);
  }

  function friendlyComponentLabel(component) {
    const labels = {
      main: "",
      freezer: "Freezer",
      cooler: "Fridge",
      cvroom: "Convertible zone",
      "pantry-01": "Pantry",
      icemaker: "Ice maker",
      "icemaker-02": "Ice maker 2",
      "icemaker-03": "Ice maker 3",
      "camera-01": "Camera",
      hood: "Hood",
      "cavity-01": "Oven cavity"
    };
    if (labels[component] !== undefined) {
      return labels[component];
    }
    return component && component !== "main" ? humanize(component) : "";
  }

  function humanize(value) {
    return String(value || "")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/[._-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/^./, function (letter) {
        return letter.toUpperCase();
      });
  }

  function sectionTitle(text) {
    const heading = document.createElement("h3");
    heading.className = "detail-section-title";
    heading.textContent = text;
    return heading;
  }

  function sourceLabel(device) {
    if (device.brand === "smartthings") {
      return "SmartThings";
    }
    if (device.brand === "nest") {
      return "Google Nest";
    }
    if (device.brand === "yale") {
      return "Yale";
    }
    if (device.brand === "ring") {
      return "Ring";
    }
    if (device.brand === "ip-camera") {
      return "IP Camera";
    }
    if (device.brand === "cudy") {
      return "Cudy";
    }
    if (device.brand === "printer") {
      return "Printer";
    }
    if (device.brand === "meross") {
      return "Meross";
    }
    return humanize(device.brand || "Device");
  }

  function sourceBadgeLabel(device) {
    if (device.brand === "smartthings") {
      return "SmartThings cloud";
    }
    if (device.brand === "ring") {
      return "Ring cloud";
    }
    if (device.brand === "ip-camera") {
      return "Camera local";
    }
    if (device.brand === "nest") {
      return "Nest cloud";
    }
    if (device.brand === "meross") {
      return "Meross local";
    }
    if (device.brand === "cudy") {
      return "Cudy local";
    }
    if (device.brand === "printer") {
      return "Printer local";
    }
    if (device.brand === "yale") {
      return "Yale local";
    }
    return deviceSourceKind(device) === "cloud" ? "Cloud" : "Local";
  }

  function deviceSourceKind(device) {
    return isCloudDevice(device) ? "cloud" : "local";
  }

  function isCloudDevice(device) {
    return ["smartthings", "ring", "nest"].includes(device.brand);
  }

  function lastCheckedLabel(value) {
    if (!value) {
      return "not yet";
    }
    const checkedAt = new Date(value);
    if (Number.isNaN(checkedAt.getTime())) {
      return String(value);
    }
    return checkedAt.toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit"
    });
  }

  function renderDeviceIcon(device, deviceState, extraClassName) {
    const icon = document.createElement("span");
    updateDeviceIconElement(icon, device, deviceState, extraClassName);
    return icon;
  }

  function updateDeviceIconElement(element, device, deviceState, extraClassName) {
    if (!element) {
      return;
    }
    const iconName = deviceIconName(device, deviceState);
    element.className = ["device-icon", extraClassName].filter(Boolean).join(" ");
    element.style.setProperty("--device-icon-url", "url('" + iconBasePath + iconName + ".svg')");
    element.title = humanize(iconName);
  }

  function deviceIconName(device, deviceState) {
    const applianceType = deviceState?.appliance?.type;
    if (applianceType === "refrigerator") {
      return "refrigerator";
    }
    if (applianceType === "laundry") {
      return deviceText(device).includes("dryer") ? "dryer" : "washer";
    }
    if (applianceType === "microwave") {
      return "microwave";
    }
    if (applianceType === "oven") {
      return "oven";
    }
    if (applianceType === "router") {
      return "router";
    }
    if (applianceType === "thermostat") {
      return "thermostat";
    }
    if (applianceType === "printer") {
      return "printer";
    }

    const type = deviceText(device);
    const checks = [
      ["garage-door", ["garage", "garagedoorcontrol", "msg"]],
      ["doorbell", ["doorbell", "ding", "chime"]],
      ["camera", ["camera", "stick up cam", "floodlight cam", "spotlight cam", "ring"]],
      ["lock", ["lock", "yale", "august"]],
      ["router", ["router", "gateway", "cudy", "wifi access point"]],
      ["thermostat", ["thermostat", "nest"]],
      ["air-conditioner", ["air conditioner", "air-conditioner", "ac ", "cooling"]],
      ["heater", ["heater", "radiator", "heat"]],
      ["fan", ["fan", "hood fan"]],
      ["air-purifier", ["air purifier", "purifier", "filter"]],
      ["humidifier", ["humidifier", "humidity"]],
      ["refrigerator", ["refrigerator", "fridge", "freezer", "cooler"]],
      ["microwave", ["microwave"]],
      ["oven", ["oven", "range", "stove"]],
      ["dishwasher", ["dishwasher"]],
      ["washer", ["washer", "washing machine", "laundry"]],
      ["dryer", ["dryer"]],
      ["coffee-maker", ["coffee", "espresso"]],
      ["vacuum", ["vacuum"]],
      ["tv", ["tv", "television", "display"]],
      ["speaker", ["speaker", "audio", "sound"]],
      ["printer", ["printer", "sawgrass", "imageprograf", "canon gp", "canon g", "pixma"]],
      ["water-leak", ["water leak", "leak sensor", "water sensor"]],
      ["smoke-detector", ["smoke", "fire"]],
      ["co-detector", ["carbon monoxide", "co detector", "co alarm"]],
      ["motion-sensor", ["motion", "occupancy", "presence"]],
      ["contact-sensor", ["contact", "open close", "contactsensor", "sensor"]],
      ["blinds", ["blind", "shade", "curtain"]],
      ["light-strip", ["light strip", "led strip", "strip light"]],
      ["ceiling-light", ["ceiling light", "overhead light"]],
      ["lamp", ["lamp"]],
      ["dimmer-switch", ["dimmer", "switchlevel", "mss560"]],
      ["light-switch", ["switch", "mss510", "mss550", "wall switch"]],
      ["smart-plug", ["plug", "outlet", "mss110", "mss210", "mss310", "mss315"]],
      ["light-bulb", ["bulb", "light"]]
    ];

    for (const item of checks) {
      if (item[1].some(function (needle) {
        return type.includes(needle);
      })) {
        return item[0];
      }
    }
    if (isGarage(device)) {
      return "garage-door";
    }
    if (isLock(device)) {
      return "lock";
    }
    if (isRing(device)) {
      return "camera";
    }
    if (isCudy(device)) {
      return "router";
    }
    if (isNest(device)) {
      return "thermostat";
    }
    if (isPrinter(device)) {
      return "printer";
    }
    if (isDimmer(device)) {
      return "dimmer-switch";
    }
    if (isSensor(device)) {
      return "contact-sensor";
    }
    if (isAppliance(device)) {
      return "appliance";
    }
    return "power";
  }

  function renderCapabilityInspection(inspection) {
    const wrapper = document.createElement("div");
    wrapper.className = "capability-panel";

    const title = document.createElement("h4");
    if (inspection.status === "loading") {
      title.textContent = "Checking controls...";
      wrapper.appendChild(title);
      return wrapper;
    }
    if (inspection.status === "error") {
      title.textContent = "Inspector unavailable";
      const error = document.createElement("p");
      error.className = "device-error";
      error.textContent = inspection.error || "Could not inspect capabilities.";
      wrapper.appendChild(title);
      wrapper.appendChild(error);
      return wrapper;
    }

    title.textContent = "Capability inspector";
    const note = document.createElement("p");
    note.textContent = "Commands are sent directly to SmartThings for this appliance.";
    wrapper.appendChild(title);
    wrapper.appendChild(note);
    wrapper.appendChild(renderCapabilityGroup("Controllable", inspection.controllable || [], true, inspection.deviceId));
    wrapper.appendChild(renderCapabilityGroup("Status only", inspection.statusOnly || [], false));
    return wrapper;
  }

  function renderCapabilityGroup(title, capabilities, includeCommands, smartThingsDeviceId) {
    const section = document.createElement("section");
    const heading = document.createElement("h5");
    const visibleCapabilities = includeCommands ? capabilities.filter(isDashboardCommandCapability) : capabilities;
    heading.textContent = title + " (" + visibleCapabilities.length + ")";
    const list = document.createElement("div");
    list.className = "capability-list";

    visibleCapabilities.slice(0, 8).forEach(function (capability) {
      const item = document.createElement("div");
      item.className = "capability-item";
      const name = document.createElement("strong");
      name.textContent = capability.id;
      const detail = document.createElement("span");
      if (includeCommands) {
        detail.textContent = commandSummary(capability.commands || []);
        item.appendChild(name);
        item.appendChild(detail);
        (capability.commands || []).forEach(function (command) {
          item.appendChild(renderCommandForm(smartThingsDeviceId, capability, command));
        });
      } else {
        detail.textContent = attributeSummary(capability.attributes || []);
        item.appendChild(name);
        item.appendChild(detail);
      }
      list.appendChild(item);
    });

    if (visibleCapabilities.length > 8) {
      const more = document.createElement("p");
      more.textContent = "+" + (visibleCapabilities.length - 8) + " more";
      list.appendChild(more);
    }

    section.appendChild(heading);
    section.appendChild(list);
    return section;
  }

  function isDashboardCommandCapability(capability) {
    return !hiddenCommandCapabilities.has(capability.id) && (capability.commands || []).length > 0;
  }

  function renderCommandForm(smartThingsDeviceId, capability, command) {
    const form = document.createElement("form");
    form.className = "command-form";
    form.dataset.smartThingsDeviceId = smartThingsDeviceId;
    form.dataset.component = capability.component || "main";
    form.dataset.capability = capability.id;
    form.dataset.command = command.name;

    (command.arguments || []).forEach(function (argument, index) {
      form.appendChild(renderCommandArgument(argument, index));
    });

    const button = document.createElement("button");
    button.type = "submit";
    button.className = "command-send";
    button.textContent = "Send " + command.name;
    form.appendChild(button);
    form.addEventListener("submit", handleCommandSubmit);
    return form;
  }

  function renderCommandArgument(argument, index) {
    const label = document.createElement("label");
    const name = friendlyArgumentNames[argument.name] || humanize(argument.name || "Argument " + (index + 1));
    label.textContent = name + (argument.optional ? " (optional)" : "");

    let input;
    if (argument.options && argument.options.length) {
      input = document.createElement("select");
      if (argument.optional) {
        const empty = document.createElement("option");
        empty.value = "";
        empty.textContent = "No value";
        input.appendChild(empty);
      }
      argument.options.forEach(function (option) {
        const item = document.createElement("option");
        item.value = String(option);
        item.textContent = String(option);
        input.appendChild(item);
      });
    } else if (argument.type === "integer" || argument.type === "number") {
      input = document.createElement("input");
      input.type = "number";
      if (argument.minimum !== undefined) {
        input.min = String(argument.minimum);
      }
      if (argument.maximum !== undefined) {
        input.max = String(argument.maximum);
      }
      input.placeholder = argumentPlaceholder(argument, argument.optional ? "Optional" : "Required");
    } else if (argument.type === "object" || argument.type === "array") {
      input = document.createElement("textarea");
      input.placeholder = argument.optional ? "Optional JSON" : "{}";
    } else {
      input = document.createElement("input");
      input.type = "text";
      input.placeholder = argumentPlaceholder(argument, argument.optional ? "Optional" : "Required");
    }

    input.dataset.type = argument.type || "string";
    input.dataset.optional = argument.optional ? "true" : "false";
    input.dataset.argumentName = argument.name || "";
    label.appendChild(input);
    return label;
  }

  function argumentPlaceholder(argument, fallback) {
    const placeholders = {
      uri: "https://.../sound.mp3",
      operationTime: "HH:mm:ss or model format",
      time: "Minutes",
      setpoint: "Temperature",
      weight: "Weight",
      foodType: "Food type"
    };
    return placeholders[argument.name] || fallback;
  }

  async function handleCommandSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const device = state.devices.find(function (item) {
      return item.device_uuid === form.dataset.smartThingsDeviceId;
    });
    if (!device) {
      showBanner("Could not find device for command.", "error");
      return;
    }

    let args;
    try {
      args = collectCommandArguments(form);
    } catch (error) {
      showBanner(error.message || "Check command arguments.", "error");
      return;
    }

    const button = form.querySelector("button");
    button.disabled = true;
    button.textContent = "Sending...";

    try {
      const result = await requestJson("/devices/" + device.id + "/smartthings/command", {
        method: "POST",
        body: JSON.stringify({
          component: form.dataset.component,
          capability: form.dataset.capability,
          command: form.dataset.command,
          arguments: args
        })
      });
      showBanner(result.message || "Command sent.", "success");
      await refreshOneDevice(device.id);
    } catch (error) {
      showBanner(error.message || "Command failed.", "error");
    } finally {
      button.disabled = false;
      button.textContent = "Send " + form.dataset.command;
    }
  }

  function collectCommandArguments(form) {
    const inputs = Array.from(form.querySelectorAll("input, select, textarea"));
    return inputs.reduce(function (args, input, index) {
      const rawValue = input.value.trim();
      const optional = input.dataset.optional === "true";
      if (!rawValue && optional) {
        const laterHasValue = inputs.slice(index + 1).some(function (laterInput) {
          return laterInput.value.trim();
        });
        if (laterHasValue) {
          throw new Error((input.dataset.argumentName || "Optional argument") + " must be filled before later arguments.");
        }
        return args;
      }
      if (!rawValue && !optional) {
        throw new Error((input.dataset.argumentName || "Argument") + " is required.");
      }

      if (input.dataset.type === "integer") {
        args.push(Number.parseInt(rawValue, 10));
      } else if (input.dataset.type === "number") {
        args.push(Number(rawValue));
      } else if (input.dataset.type === "object" || input.dataset.type === "array") {
        args.push(JSON.parse(rawValue));
      } else {
        args.push(rawValue);
      }
      return args;
    }, []);
  }

  function commandSummary(commands) {
    if (!commands.length) {
      return "No commands";
    }
    return commands.map(function (command) {
      const args = (command.arguments || []).map(function (arg) {
        const options = arg.options ? " [" + arg.options.slice(0, 6).join(", ") + "]" : "";
        const range = arg.minimum !== undefined || arg.maximum !== undefined ? " " + [arg.minimum, arg.maximum].filter(function (value) { return value !== undefined; }).join("-") : "";
        return [arg.name || "value", arg.type, range, options].filter(Boolean).join(":");
      }).join("; ");
      return command.name + (args ? "(" + args + ")" : "()");
    }).join(", ");
  }

  function attributeSummary(attributes) {
    if (!attributes.length) {
      return "Metadata unavailable";
    }
    return attributes.slice(0, 6).map(function (attribute) {
      const options = attribute.options ? " [" + attribute.options.slice(0, 6).join(", ") + "]" : "";
      const range = attribute.minimum !== undefined || attribute.maximum !== undefined ? " " + [attribute.minimum, attribute.maximum].filter(function (value) { return value !== undefined; }).join("-") : "";
      return [attribute.name, attribute.type, range, options].filter(Boolean).join(":");
    }).join(", ");
  }

  function renderAppliance(appliance) {
    const wrapper = document.createElement("div");
    wrapper.className = "appliance-panel";
    const title = document.createElement("h4");
    title.textContent = appliance.title || "Appliance";
    const grid = document.createElement("div");
    grid.className = "appliance-grid";

    applianceFields(appliance).forEach(function (item) {
      const field = document.createElement("div");
      field.className = "appliance-field";
      field.innerHTML = "<span></span><strong></strong>";
      field.querySelector("span").textContent = item.label;
      field.querySelector("strong").textContent = formatApplianceValue(item.value, item.unit);
      grid.appendChild(field);
    });

    wrapper.appendChild(title);
    wrapper.appendChild(grid);
    return wrapper;
  }

  function renderLaundryTileStatus(appliance, deviceState) {
    const active = isLaundryActive(appliance, deviceState);
    const stage = laundryStage(appliance, active);
    const remaining = laundryRemainingLabel(appliance);
    const progress = active ? laundryProgress(appliance, stage) : 0;
    const cycle = appliance.cycleType || appliance.jobState || "Ready";
    const wrapper = document.createElement("div");
    wrapper.className = "laundry-tile " + (active ? "is-active" : "is-idle");
    wrapper.style.setProperty("--laundry-progress", String(progress));
    wrapper.innerHTML = [
      '<div class="laundry-tile-top">',
      '<div>',
      '<span class="laundry-kicker"></span>',
      '<strong class="laundry-stage"></strong>',
      '</div>',
      '<div class="laundry-arc" aria-hidden="true"><span></span></div>',
      '</div>',
      '<div class="laundry-time-row">',
      '<strong class="laundry-time"></strong>',
      '<span class="laundry-end"></span>',
      '</div>',
      '<div class="laundry-phase-bar">',
      '<span class="is-complete">Wash</span>',
      '<span>Dry</span>',
      '</div>',
      '<div class="laundry-cycle-row">',
      '<span>Cycle</span>',
      '<strong></strong>',
      '</div>'
    ].join("");

    wrapper.querySelector(".laundry-kicker").textContent = active ? "Active cycle" : "Washer / dryer";
    wrapper.querySelector(".laundry-stage").textContent = active ? stage.label : "Ready";
    wrapper.querySelector(".laundry-time").textContent = active ? remaining : "Idle";
    wrapper.querySelector(".laundry-end").textContent = active ? laundryCompletionLabel(appliance) : "No active cycle";
    wrapper.querySelector(".laundry-cycle-row strong").textContent = humanize(cycle);
    const phases = wrapper.querySelectorAll(".laundry-phase-bar span");
    phases[0].classList.toggle("is-complete", active && progress >= 50);
    phases[0].classList.toggle("is-current", active && stage.kind !== "dry");
    phases[1].classList.toggle("is-complete", active && progress >= 96);
    phases[1].classList.toggle("is-current", active && stage.kind === "dry");
    return wrapper;
  }

  function renderFridgeTileStatus(device, appliance) {
    const wrapper = document.createElement("div");
    wrapper.className = "fridge-dashboard";
    wrapper.appendChild(renderFridgeDashboardCompartment(device, {
      className: "fridge-compartment-primary",
      label: "Fridge",
      feature: appliance.powerCool ? "Power Cool on" : "Power Cool",
      value: appliance.coolerSetpoint ?? appliance.coolerTemp,
      actual: appliance.coolerTemp,
      componentId: "cooler",
      range: { minimum: 34, maximum: 44, step: 1 },
      door: appliance.coolerDoor
    }));

    const lower = document.createElement("div");
    lower.className = "fridge-compartment-row";
    lower.appendChild(renderFridgeDashboardCompartment(device, {
      className: "fridge-compartment-secondary",
      label: "Freezer",
      feature: appliance.powerFreeze ? "Power Freeze on" : "Power Freeze",
      value: appliance.freezerSetpoint ?? appliance.freezerTemp,
      actual: appliance.freezerTemp,
      componentId: "freezer",
      range: { minimum: -8, maximum: 5, step: 1 },
      door: appliance.freezerDoor
    }));
    lower.appendChild(renderFridgeDashboardInfo(appliance));
    wrapper.appendChild(lower);
    return wrapper;
  }

  function renderFridgeDashboardCompartment(device, options) {
    const compartment = document.createElement("div");
    compartment.className = "fridge-compartment " + options.className;
    const value = Number(options.value);
    const displayValue = Number.isFinite(value) ? value : options.value;
    compartment.innerHTML = [
      '<button class="fridge-step fridge-step-up" type="button" aria-label=""></button>',
      '<div class="fridge-compartment-content">',
      '<span class="fridge-compartment-label"></span>',
      '<strong class="fridge-temp-value"></strong>',
      '<span class="fridge-feature-label"></span>',
      '<span class="fridge-door-label"></span>',
      '</div>',
      '<button class="fridge-step fridge-step-down" type="button" aria-label=""></button>'
    ].join("");

    compartment.querySelector(".fridge-compartment-label").textContent = options.label;
    compartment.querySelector(".fridge-temp-value").textContent = formatApplianceValue(displayValue, "°F");
    compartment.querySelector(".fridge-feature-label").textContent = options.feature;
    compartment.querySelector(".fridge-door-label").textContent = "Door " + humanize(options.door || "unknown");

    const up = compartment.querySelector(".fridge-step-up");
    const down = compartment.querySelector(".fridge-step-down");
    up.setAttribute("aria-label", "Raise " + options.label + " temperature");
    down.setAttribute("aria-label", "Lower " + options.label + " temperature");
    if (Number.isFinite(value)) {
      up.addEventListener("click", function () {
        sendSmartThingsCommand(device.id, options.componentId, "thermostatCoolingSetpoint", "setCoolingSetpoint", [
          clampSetpoint(value + Number(options.range.step || 1), options.range)
        ]);
      });
      down.addEventListener("click", function () {
        sendSmartThingsCommand(device.id, options.componentId, "thermostatCoolingSetpoint", "setCoolingSetpoint", [
          clampSetpoint(value - Number(options.range.step || 1), options.range)
        ]);
      });
    } else {
      up.disabled = true;
      down.disabled = true;
    }
    return compartment;
  }

  function renderFridgeDashboardInfo(appliance) {
    const info = document.createElement("div");
    info.className = "fridge-compartment fridge-compartment-secondary fridge-info-compartment";
    info.innerHTML = [
      '<span class="fridge-compartment-label">Ice / filter</span>',
      '<strong class="fridge-info-main"></strong>',
      '<span class="fridge-feature-label"></span>',
      '<span class="fridge-door-label"></span>'
    ].join("");
    info.querySelector(".fridge-info-main").textContent = humanize(appliance.iceMaker || "unknown");
    info.querySelector(".fridge-feature-label").textContent = fridgeFilterLabel(appliance);
    info.querySelector(".fridge-door-label").textContent = appliance.waterFilterStatus === "replace" || Number(appliance.waterFilterUsage || 0) >= 95 ? "Needs filter" : "Filter OK";
    if (appliance.waterFilterStatus === "replace" || Number(appliance.waterFilterUsage || 0) >= 95) {
      info.classList.add("needs-service");
    }
    return info;
  }

  function renderCookingTileStatus(device, appliance) {
    if (appliance.type === "oven") {
      return renderStoveTileStatus(device, appliance);
    }
    if (appliance.type === "microwave") {
      return renderMicrowaveTileStatus(appliance);
    }
    const wrapper = document.createElement("div");
    wrapper.className = "quick-appliance-panel cooking-quick-panel";
    [
      ["State", appliance.operatingState || appliance.jobState || "--", isCookingActive(appliance) ? "is-active" : ""],
      ["Mode", appliance.mode || "--", ""],
      ["Door", appliance.door || appliance.cavity || "--", doorStateClass(appliance.door)]
    ].forEach(function (item) {
      wrapper.appendChild(quickPanelItem(item[0], item[1], item[2]));
    });
    return wrapper;
  }

  function renderMicrowaveTileStatus(appliance) {
    const active = isCookingActive(appliance);
    const panel = document.createElement("div");
    panel.className = "microwave-tile " + (active ? "is-active" : "is-idle");
    panel.innerHTML = [
      '<div class="microwave-face">',
      '<div class="microwave-window">',
      '<span class="microwave-window-glow"></span>',
      '<strong class="microwave-primary"></strong>',
      '<small class="microwave-secondary"></small>',
      '</div>',
      '<div class="microwave-controls" aria-hidden="true">',
      '<span></span><span></span><span></span>',
      '<span></span><span></span><span></span>',
      '<span></span><span></span><span></span>',
      '</div>',
      '</div>'
    ].join("");
    panel.querySelector(".microwave-primary").textContent = humanize(appliance.operatingState || appliance.jobState || "Ready");
    panel.querySelector(".microwave-secondary").textContent = active ? "Cooking" : "Idle";
    return panel;
  }

  function renderStoveTileStatus(device, appliance) {
    const panel = document.createElement("div");
    panel.className = "stove-tile";
    panel.innerHTML = [
      '<div class="stove-front-view" aria-hidden="true">',
      '<div class="stove-control-strip"><strong class="stove-inline-state"></strong><span></span><span></span><span></span></div>',
      '<div class="oven-section oven-section-top">',
      '<span>Top oven</span>',
      '<strong></strong>',
      '<small></small>',
      '</div>',
      '<div class="oven-section oven-section-bottom">',
      '<span>Bottom oven</span>',
      '<strong></strong>',
      '<small></small>',
      '</div>',
      '</div>'
    ].join("");
    panel.querySelector(".stove-inline-state").textContent = humanize(appliance.operatingState || appliance.jobState || "Ready");
    const topSection = panel.querySelector(".oven-section-top");
    const bottomSection = panel.querySelector(".oven-section-bottom");
    topSection.querySelector("strong").textContent = humanize(appliance.mode || "Ready");
    topSection.querySelector("small").textContent = appliance.cavity ? humanize(appliance.cavity) : "Compartment control";
    bottomSection.querySelector("strong").textContent = formatApplianceValue(appliance.temperature || appliance.setpoint, appliance.temperature !== undefined || appliance.setpoint !== undefined ? "°F" : "");
    bottomSection.querySelector("small").textContent = isCookingActive(appliance) ? humanize(appliance.operatingState || appliance.jobState || "Cooking") : humanize(appliance.door || "closed");
    return panel;
  }

  function quickPanelItem(label, value, className) {
    const item = document.createElement("div");
    item.className = ["quick-panel-item", className].filter(Boolean).join(" ");
    item.innerHTML = "<span></span><strong></strong>";
    item.querySelector("span").textContent = label;
    item.querySelector("strong").textContent = humanize(value || "--");
    return item;
  }

  function doorStateClass(value) {
    return String(value || "").toLowerCase() === "open" ? "is-warning" : "";
  }

  function fridgeFilterLabel(appliance) {
    const status = appliance.waterFilterStatus || "--";
    if (Number(appliance.waterFilterUsage || 0) > 0) {
      return humanize(status) + " · " + appliance.waterFilterUsage + "%";
    }
    return humanize(status);
  }

  function fridgeFilterClass(appliance) {
    return String(appliance.waterFilterStatus || "").toLowerCase() === "replace" || Number(appliance.waterFilterUsage || 0) >= 95 ? "is-warning" : "";
  }

  function isLaundryActive(appliance, deviceState) {
    if (deviceState.isOn === true) {
      return true;
    }
    const text = [
      appliance.operatingState,
      appliance.machineState,
      appliance.jobState,
      appliance.jobPhase
    ].join(" ").toLowerCase();
    if (!text.trim()) {
      return false;
    }
    return !["ready", "stop", "stopped", "none", "complete", "completed", "finish", "finished"].some(function (value) {
      return text.split(/\s+/).includes(value);
    });
  }

  function laundryStage(appliance, active) {
    if (!active) {
      return { kind: "idle", label: "Ready" };
    }
    const text = [
      appliance.jobPhase,
      appliance.jobState,
      appliance.operatingState,
      appliance.machineState
    ].join(" ").toLowerCase();
    if (text.includes("dry")) {
      return { kind: "dry", label: "Drying" };
    }
    if (text.includes("spin")) {
      return { kind: "spin", label: "Spinning" };
    }
    if (text.includes("rinse")) {
      return { kind: "rinse", label: "Rinsing" };
    }
    if (text.includes("wash")) {
      return { kind: "wash", label: "Washing" };
    }
    if (text.includes("pause")) {
      return { kind: "paused", label: "Paused" };
    }
    return { kind: "wash", label: humanize(appliance.jobState || appliance.operatingState || "Running") };
  }

  function laundryProgress(appliance, stage) {
    const stageProgress = {
      wash: 28,
      rinse: 48,
      spin: 68,
      dry: 84,
      paused: 50
    };
    return Math.max(8, Math.min(96, stageProgress[stage.kind] || 34));
  }

  function laundryRemainingLabel(appliance) {
    const parsed = parseLaundryDuration(appliance.remainingTime);
    if (!parsed) {
      return "-- left";
    }
    if (parsed.hours > 0) {
      return parsed.hours + ":" + String(parsed.minutes).padStart(2, "0") + " left";
    }
    return parsed.minutes + " min left";
  }

  function parseLaundryDuration(value) {
    if (!value) {
      return null;
    }
    const match = String(value).match(/(\d{1,2}):(\d{2})/);
    if (!match) {
      return null;
    }
    return {
      hours: Number(match[1]),
      minutes: Number(match[2])
    };
  }

  function laundryCompletionLabel(appliance) {
    if (appliance.completionTime) {
      const date = new Date(appliance.completionTime);
      if (!Number.isNaN(date.getTime())) {
        return "Ends at " + date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      }
    }
    return "End time unknown";
  }

  function applianceFields(appliance) {
    if (appliance.type === "laundry") {
      return [
        ["State", appliance.operatingState || appliance.machineState],
        ["Job", appliance.jobState || appliance.jobPhase],
        ["Remaining", appliance.remainingTime],
        ["Cycle", appliance.cycleType],
        ["Water", appliance.waterTemperature],
        ["Spin", appliance.spinLevel],
        ["Dry level", appliance.dryLevel],
        ["Detergent", appliance.detergent],
        ["Softener", appliance.softener]
      ].map(fieldTuple);
    }

    if (appliance.type === "refrigerator") {
      return [
        ["Fridge", appliance.coolerTemp, "°F"],
        ["Fridge set", appliance.coolerSetpoint, "°F"],
        ["Freezer", appliance.freezerTemp, "°F"],
        ["Freezer set", appliance.freezerSetpoint, "°F"],
        ["Fridge door", appliance.coolerDoor],
        ["Freezer door", appliance.freezerDoor],
        ["Ice maker", appliance.iceMaker],
        ["Filter", appliance.waterFilterStatus],
        ["Filter use", appliance.waterFilterUsage, "%"]
      ].map(fieldTuple);
    }

    if (appliance.type === "router") {
      return [
        ["Status", appliance.status],
        ["Model", appliance.model],
        ["Uptime", appliance.uptime],
        ["Load", appliance.load],
        ["Memory", appliance.memory],
        ["Download", appliance.download],
        ["Upload", appliance.upload],
        ["Total down", appliance.totalDownload],
        ["Total up", appliance.totalUpload],
        ["Speed down", appliance.speedtest && appliance.speedtest.download],
        ["Speed up", appliance.speedtest && appliance.speedtest.upload],
        ["WAN", appliance.wan],
        ["Routes", appliance.clients],
        ["Mesh units", appliance.meshUnits]
      ].filter(function (item) {
        return !isBlankValue(item[1]);
      }).map(fieldTuple);
    }

    if (appliance.type === "thermostat") {
      return [
        ["Ambient", appliance.ambientFahrenheit, "°F"],
        ["Mode", appliance.mode],
        ["HVAC", appliance.hvacStatus],
        ["Heat", appliance.heatFahrenheit, "°F"],
        ["Cool", appliance.coolFahrenheit, "°F"],
        ["Humidity", appliance.humidity, "%"]
      ].map(fieldTuple);
    }

    if (appliance.type === "oven") {
      return [
        ["State", appliance.operatingState],
        ["Job", appliance.jobState],
        ["Mode", appliance.mode],
        ["Cavity", appliance.cavity],
        ["Door", appliance.door],
        ["Temp", appliance.temperature, "°F"],
        ["Setpoint", appliance.setpoint, "°F"],
        ["Lamp", appliance.lamp],
        ["Hood fan", appliance.hoodFan],
        ["Done", appliance.completionTime]
      ].map(fieldTuple);
    }

    return [
      ["State", appliance.operatingState],
      ["Job", appliance.jobState],
      ["Mode", appliance.mode],
      ["Door", appliance.door],
      ["Power", appliance.power],
      ["Temp", appliance.temperature, "°F"],
      ["Done", appliance.completionTime],
      ["Switch", appliance.switch]
    ].map(fieldTuple);
  }

  function fieldTuple(parts) {
    return { label: parts[0], value: parts[1], unit: parts[2] || "" };
  }

  function isBlankValue(value) {
    return value === null || value === undefined || value === "" || value === "--";
  }

  function formatApplianceValue(value, unit) {
    if (value === null || value === undefined || value === "") {
      return "--";
    }
    if (typeof value === "boolean") {
      return value ? "Yes" : "No";
    }
    return String(value) + (unit || "");
  }

  function renderDimmer(device, deviceState) {
    const value = deviceState.luminance || 50;
    const wrapper = document.createElement("div");
    wrapper.className = "dimmer-control";
    wrapper.innerHTML = [
      '<div class="dimmer-row">',
      '<span>Dimmer</span>',
      '<strong class="dimmer-value"></strong>',
      '</div>',
      '<input type="range" min="1" max="100" step="1">'
    ].join("");

    const valueLabel = wrapper.querySelector(".dimmer-value");
    const slider = wrapper.querySelector("input");
    valueLabel.textContent = value + "%";
    slider.value = String(value);
    slider.disabled = deviceState.status === "loading";

    slider.addEventListener("input", function () {
      valueLabel.textContent = slider.value + "%";
    });
    slider.addEventListener("change", function () {
      setBrightness(device.id, slider.value);
    });

    return wrapper;
  }

  function renderMeta(device) {
    const meta = document.createElement("div");
    meta.className = "device-meta";
    [
      ["Host", device.host],
      ["Model", device.model],
      ["Type", device.device_type || "meross"],
      ["ID", String(device.id)],
      ["Enabled", device.is_enabled ? "Yes" : "No"]
    ].forEach(function (item) {
      if (item[1] === null || item[1] === undefined || item[1] === "") {
        return;
      }
      const cell = document.createElement("div");
      cell.className = "meta-item";
      cell.innerHTML = "<span></span><strong></strong>";
      cell.querySelector("span").textContent = item[0];
      cell.querySelector("strong").textContent = item[1];
      meta.appendChild(cell);
    });
    return meta;
  }

  function actionButton(label, action, deviceId, status) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "device-action " + action;
    button.textContent = label;
    button.disabled = status === "loading";
    button.addEventListener("click", async function () {
      if (action === "tile-size") {
        toggleDeviceTileLayout(deviceId);
      } else if (action === "refresh") {
        await refreshOneDevice(deviceId);
      } else if (action === "cudy-stats") {
        await refreshCudyStats(deviceId);
      } else if (action === "cudy-speedtest") {
        await runCudySpeedTest(deviceId);
      } else if (action === "cudy-credentials") {
        await updateCudyCredentials(deviceId);
      } else if (action === "cudy-reboot") {
        await rebootCudyRouter(deviceId);
      } else if (action === "inspect") {
        await inspectDevice(deviceId);
        const device = state.devices.find(function (item) {
          return item.id === deviceId;
        });
        if (device && elements.deviceDetailDialog.open) {
          renderDeviceDetail(device);
        }
      } else {
        await runDeviceAction(deviceId, action);
        const device = state.devices.find(function (item) {
          return item.id === deviceId;
        });
        if (device && elements.deviceDetailDialog.open) {
          renderDeviceDetail(device);
        }
      }
    });
    return button;
  }

  function renderSwitchToggle(device, deviceState) {
    const isOn = deviceState.isOn === true;
    const isLoading = deviceState.status === "loading";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "switch-toggle " + (isOn ? "is-on" : "is-off");
    if (isLoading) {
      button.classList.add("is-loading");
    }
    if (deviceState.status === "error") {
      button.classList.add("is-error");
    }
    button.disabled = isLoading;
    button.setAttribute("aria-pressed", isOn ? "true" : "false");
    button.setAttribute("aria-label", (isOn ? "Turn off " : "Turn on ") + device.name);
    button.innerHTML = [
      '<span class="switch-toggle-label"></span>',
      '<span class="switch-toggle-track" aria-hidden="true">',
      '<span class="switch-toggle-thumb"></span>',
      '</span>'
    ].join("");
    button.querySelector(".switch-toggle-label").textContent = switchToggleLabel(deviceState, isOn);

    let pointerStartX = 0;
    let pointerId = null;
    let wasDragged = false;
    let suppressClick = false;
    button.addEventListener("pointerdown", function (event) {
      if (button.disabled) {
        return;
      }
      pointerStartX = event.clientX;
      pointerId = event.pointerId;
      wasDragged = false;
      suppressClick = false;
      button.classList.add("is-dragging");
      button.setPointerCapture?.(event.pointerId);
      updateSwitchDragPosition(button, isOn ? 1 : 0);
    });
    button.addEventListener("pointermove", function (event) {
      if (pointerId !== event.pointerId || button.disabled) {
        return;
      }
      const progress = switchDragProgress(button, event.clientX);
      if (Math.abs(event.clientX - pointerStartX) >= 8) {
        wasDragged = true;
      }
      updateSwitchDragPosition(button, progress);
    });
    button.addEventListener("pointerup", function (event) {
      if (pointerId !== event.pointerId || button.disabled) {
        return;
      }
      const progress = switchDragProgress(button, event.clientX);
      cleanupSwitchDrag(button, event.pointerId);
      if (!wasDragged) {
        return;
      }
      event.preventDefault();
      suppressClick = true;
      runSwitchToggleAction(device.id, progress >= 0.5 ? "turn-on" : "turn-off", isOn);
    });
    button.addEventListener("pointercancel", function (event) {
      if (pointerId !== event.pointerId) {
        return;
      }
      cleanupSwitchDrag(button, event.pointerId);
    });
    button.addEventListener("click", function (event) {
      if (suppressClick) {
        suppressClick = false;
        return;
      }
      event.preventDefault();
      runSwitchToggleAction(device.id, isOn ? "turn-off" : "turn-on", isOn);
    });

    return button;
  }

  function renderDimmerToggle(device, deviceState) {
    const level = dimmerLevel(deviceState);
    const isOn = level > 0;
    const isLoading = deviceState.status === "loading";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "switch-toggle dimmer-toggle " + (isOn ? "is-on" : "is-off");
    if (isLoading) {
      button.classList.add("is-loading");
    }
    if (deviceState.status === "error") {
      button.classList.add("is-error");
    }
    button.disabled = isLoading;
    button.setAttribute("aria-pressed", isOn ? "true" : "false");
    button.setAttribute("aria-label", "Set " + device.name + " brightness");
    button.style.setProperty("--dimmer-level", String(level));
    button.innerHTML = [
      '<span class="switch-toggle-label"></span>',
      '<span class="switch-toggle-track" aria-hidden="true">',
      '<span class="switch-toggle-fill"></span>',
      '<span class="switch-toggle-thumb"></span>',
      '</span>'
    ].join("");
    updateDimmerToggleLabel(button, level);

    let pointerStartX = 0;
    let pointerId = null;
    let wasDragged = false;
    let suppressClick = false;
    button.addEventListener("pointerdown", function (event) {
      if (button.disabled) {
        return;
      }
      pointerStartX = event.clientX;
      pointerId = event.pointerId;
      wasDragged = false;
      suppressClick = false;
      button.classList.add("is-dragging");
      button.setPointerCapture?.(event.pointerId);
      updateDimmerDragPosition(button, level);
    });
    button.addEventListener("pointermove", function (event) {
      if (pointerId !== event.pointerId || button.disabled) {
        return;
      }
      const nextLevel = dimmerLevelFromProgress(switchDragProgress(button, event.clientX));
      if (Math.abs(event.clientX - pointerStartX) >= 8) {
        wasDragged = true;
      }
      updateDimmerDragPosition(button, nextLevel);
    });
    button.addEventListener("pointerup", function (event) {
      if (pointerId !== event.pointerId || button.disabled) {
        return;
      }
      const nextLevel = dimmerLevelFromProgress(switchDragProgress(button, event.clientX));
      cleanupDimmerDrag(button, event.pointerId);
      if (!wasDragged) {
        return;
      }
      event.preventDefault();
      suppressClick = true;
      runDimmerLevelAction(device.id, nextLevel, deviceState);
    });
    button.addEventListener("pointercancel", function (event) {
      if (pointerId !== event.pointerId) {
        return;
      }
      cleanupDimmerDrag(button, event.pointerId);
    });
    button.addEventListener("click", function (event) {
      if (suppressClick) {
        suppressClick = false;
        return;
      }
      event.preventDefault();
      runDimmerLevelAction(device.id, isOn ? 0 : Math.max(level, 50), deviceState);
    });

    return button;
  }

  function switchDragProgress(button, clientX) {
    const track = button.querySelector(".switch-toggle-track");
    const bounds = (track || button).getBoundingClientRect();
    const thumbWidth = 44;
    const usableWidth = Math.max(1, bounds.width - thumbWidth);
    const raw = (clientX - bounds.left - (thumbWidth / 2)) / usableWidth;
    return Math.max(0, Math.min(1, raw));
  }

  function updateSwitchDragPosition(button, progress) {
    button.style.setProperty("--switch-drag-progress", String(progress));
  }

  function cleanupSwitchDrag(button, pointerId) {
    button.classList.remove("is-dragging");
    button.style.removeProperty("--switch-drag-progress");
    button.releasePointerCapture?.(pointerId);
  }

  function switchToggleLabel(deviceState, isOn) {
    if (deviceState.status === "error") {
      return "Retry switch";
    }
    return isOn ? "Light on" : "Light off";
  }

  function dimmerLevel(deviceState) {
    if (deviceState.isOn === false) {
      return 0;
    }
    return Math.max(0, Math.min(100, Number(deviceState.luminance || (deviceState.isOn ? 50 : 0))));
  }

  function dimmerLevelFromProgress(progress) {
    return Math.max(0, Math.min(100, Math.round(progress * 100)));
  }

  function updateDimmerToggleLabel(button, level) {
    const label = button.querySelector(".switch-toggle-label");
    if (label) {
      label.textContent = level <= 0 ? "Light off" : level + "%";
    }
    button.classList.toggle("is-on", level > 0);
    button.classList.toggle("is-off", level <= 0);
    button.setAttribute("aria-pressed", level > 0 ? "true" : "false");
  }

  function updateDimmerDragPosition(button, level) {
    button.style.setProperty("--dimmer-drag-level", String(level));
    updateDimmerToggleLabel(button, level);
  }

  function cleanupDimmerDrag(button, pointerId) {
    button.classList.remove("is-dragging");
    button.style.removeProperty("--dimmer-drag-level");
    button.releasePointerCapture?.(pointerId);
  }

  async function runDimmerLevelAction(deviceId, level, previousState) {
    const existing = state.states.get(deviceId) || previousState || {};
    const nextLevel = Math.max(0, Math.min(100, Number(level)));
    const optimistic = Object.assign({}, existing, {
      status: "loading",
      isOn: nextLevel > 0,
      luminance: nextLevel > 0 ? Math.max(1, nextLevel) : existing.luminance,
      error: ""
    });
    state.states.set(deviceId, optimistic);
    render();

    try {
      const result = nextLevel <= 0
        ? await requestJson("/devices/" + deviceId + "/turn-off", { method: "POST" })
        : await requestJson("/devices/" + deviceId + "/brightness", {
          method: "POST",
          body: JSON.stringify({ luminance: Math.max(1, nextLevel) })
        });
      state.states.set(deviceId, checkedDeviceState({
        status: result.is_open !== null && result.is_open !== undefined ? (result.is_open ? "on" : "off") : (result.is_on ? "on" : "off"),
        isOn: result.is_on,
        isOpen: result.is_open,
        luminance: result.luminance || (nextLevel > 0 ? nextLevel : existing.luminance),
        appliance: existing.appliance,
        raw: existing.raw,
        error: ""
      }));
      showBanner(result.message || "Brightness updated.", "success");
    } catch (error) {
      state.states.set(deviceId, checkedDeviceState(Object.assign({}, existing, {
        status: existing.isOn ? "on" : "off",
        isOn: existing.isOn,
        luminance: existing.luminance,
        error: error.message || "Brightness update failed"
      })));
      showBanner(error.message || "Brightness update failed.", "error");
    } finally {
      render();
    }
  }

  async function runSwitchToggleAction(deviceId, action, isCurrentlyOn) {
    if ((action === "turn-on" && isCurrentlyOn) || (action === "turn-off" && !isCurrentlyOn)) {
      return;
    }
    const existing = state.states.get(deviceId) || {};
    state.states.set(deviceId, Object.assign({}, existing, {
      status: "loading",
      isOn: action === "turn-on",
      error: ""
    }));
    render();

    try {
      const result = await requestJson("/devices/" + deviceId + "/" + action, {
        method: "POST"
      });
      state.states.set(deviceId, checkedDeviceState({
        status: result.is_open !== null && result.is_open !== undefined ? (result.is_open ? "on" : "off") : (result.is_on ? "on" : "off"),
        isOn: result.is_on,
        isOpen: result.is_open,
        luminance: result.luminance,
        appliance: existing.appliance,
        raw: existing.raw,
        error: ""
      }));
      showBanner(result.message || "Command completed.", "success");
    } catch (error) {
      state.states.set(deviceId, Object.assign({}, existing, {
        status: isCurrentlyOn ? "on" : "off",
        isOn: isCurrentlyOn,
        error: error.message || "Command failed"
      }));
      showBanner(error.message || "Command failed.", "error");
    } finally {
      render();
    }
  }

  async function renameDevice(deviceId) {
    const device = state.devices.find(function (item) {
      return item.id === deviceId;
    });
    if (!device) {
      return;
    }

    const requestedName = window.prompt("Device name", device.name);
    if (requestedName === null) {
      return;
    }

    const name = requestedName.trim();
    if (!name) {
      showBanner("Device name cannot be blank.", "error");
      return;
    }
    if (name === device.name) {
      return;
    }

    try {
      const updated = await requestJson("/devices/" + deviceId, {
        method: "PUT",
        body: JSON.stringify({ name: name })
      });
      updateDeviceInState(updated);
      showBanner("Renamed device to " + updated.name + ".", "success");
      if (elements.deviceDetailDialog.open && Number(elements.deviceDetailDialog.dataset.deviceId) === deviceId) {
        elements.deviceDetailEyebrow.textContent = detailEyebrowLabel(updated);
        updateDeviceIconElement(elements.deviceDetailIcon, updated, state.states.get(updated.id), "detail-device-icon");
        elements.deviceDetailTitle.textContent = updated.name;
        renderDeviceDetail(updated);
      }
      render();
    } catch (error) {
      showBanner(error.message || "Could not rename device.", "error");
    }
  }

  function updateDeviceInState(updatedDevice) {
    const index = state.devices.findIndex(function (item) {
      return item.id === updatedDevice.id;
    });
    if (index >= 0) {
      state.devices[index] = updatedDevice;
    }
  }

  async function inspectDevice(deviceId, options) {
    if (state.inspections.get(deviceId)?.status === "loading") {
      return;
    }
    state.inspections.set(deviceId, { status: "loading" });
    if (!options || !options.silent) {
      render();
    }
    try {
      const result = await requestJson("/devices/" + deviceId + "/capabilities");
      result.status = "ready";
      state.inspections.set(deviceId, result);
    } catch (error) {
      state.inspections.set(deviceId, {
        status: "error",
        error: error.message || "Could not inspect capabilities."
      });
    }
    if (!options || !options.silent) {
      render();
    }
  }

  async function refreshOneDevice(deviceId) {
    const device = state.devices.find(function (item) {
      return item.id === deviceId;
    });
    if (!device) {
      return;
    }
    state.states.set(deviceId, refreshingDeviceState(device));
    render();
    try {
      const result = await requestJson("/devices/" + deviceId + "/state", {
        timeoutMs: stateTimeoutMs(device)
      });
      state.states.set(deviceId, checkedDeviceState({
        status: stateStatus(device, result),
        isOn: result.is_on,
        isOpen: result.is_open,
        luminance: result.luminance,
        appliance: result.appliance,
        raw: result.raw,
        error: ""
      }));
      if (elements.deviceDetailDialog.open) {
        renderDeviceDetail(device);
      }
    } catch (error) {
      const fallback = cachedDeviceState(device, (error.message || "State unavailable") + "; showing last known state.");
      state.states.set(deviceId, fallback || checkedDeviceState({
        status: "error",
        isOn: null,
        error: error.message || "State unavailable"
      }));
      if (elements.deviceDetailDialog.open) {
        renderDeviceDetail(device);
      }
    }
    render();
  }

  async function markPrinterInkRefilled(deviceId, color) {
    const device = state.devices.find(function (item) {
      return item.id === deviceId;
    });
    const normalizedColor = String(color || "").trim().toLowerCase();
    if (!device || !normalizedColor) {
      return;
    }
    const existing = state.states.get(deviceId) || {};
    state.states.set(deviceId, refreshingDeviceState(device, existing));
    render();
    try {
      const result = await requestJson("/devices/" + deviceId + "/printer/ink-refill", {
        method: "POST",
        body: JSON.stringify({ color: normalizedColor })
      });
      state.states.set(deviceId, checkedDeviceState({
        status: stateStatus(device, result),
        isOn: result.is_on,
        isOpen: result.is_open,
        luminance: result.luminance,
        appliance: result.appliance,
        raw: result.raw,
        error: ""
      }));
      showBanner(humanize(normalizedColor) + " ink marked refilled.", "success");
      if (elements.deviceDetailDialog.open && Number(elements.deviceDetailDialog.dataset.deviceId) === deviceId) {
        renderDeviceDetail(device);
      }
    } catch (error) {
      state.states.set(deviceId, Object.assign({}, existing, {
        status: existing.status || "error",
        error: error.message || "Could not mark ink refilled."
      }));
      showBanner(error.message || "Could not mark ink refilled.", "error");
    } finally {
      render();
    }
  }

  async function refreshCudyStats(deviceId) {
    const device = state.devices.find(function (item) {
      return item.id === deviceId;
    });
    if (!device) {
      return;
    }
    const existing = state.states.get(deviceId) || {};
    state.states.set(deviceId, Object.assign({}, existing, { status: "loading", error: "" }));
    render();
    try {
      const result = await requestJson("/devices/" + deviceId + "/cudy/stats");
      if (result.appliance && existing.appliance && existing.appliance.speedtest) {
        result.appliance.speedtest = existing.appliance.speedtest;
      }
      state.states.set(deviceId, checkedDeviceState({
        status: stateStatus(device, result),
        isOn: result.is_on,
        isOpen: result.is_open,
        luminance: result.luminance,
        appliance: result.appliance,
        raw: result.raw,
        error: ""
      }));
      showBanner("Cudy router stats refreshed.", "success");
    } catch (error) {
      state.states.set(deviceId, checkedDeviceState({
        status: "error",
        isOn: null,
        appliance: existing.appliance,
        raw: existing.raw,
        error: error.message || "Cudy stats unavailable"
      }));
      showBanner(error.message || "Cudy stats unavailable.", "error");
    } finally {
      if (elements.deviceDetailDialog.open) {
        renderDeviceDetail(device);
      }
      render();
    }
  }

  async function runCudySpeedTest(deviceId) {
    const device = state.devices.find(function (item) {
      return item.id === deviceId;
    });
    if (!device) {
      return;
    }
    const existing = state.states.get(deviceId) || {};
    state.states.set(deviceId, Object.assign({}, existing, { status: "loading", error: "" }));
    render();
    try {
      const result = await requestJson("/devices/" + deviceId + "/cudy/speedtest", {
        method: "POST"
      });
      const appliance = Object.assign({}, existing.appliance || {}, { speedtest: result });
      state.states.set(deviceId, checkedDeviceState({
        status: existing.status && existing.status !== "loading" ? existing.status : "on",
        isOn: existing.isOn === undefined ? true : existing.isOn,
        appliance: appliance,
        raw: Object.assign({}, existing.raw || {}, { speedtest: result }),
        error: ""
      }));
      showBanner("Speed test: " + result.download + " down / " + result.upload + " up.", "success");
    } catch (error) {
      state.states.set(deviceId, checkedDeviceState({
        status: "error",
        isOn: existing.isOn,
        appliance: existing.appliance,
        raw: existing.raw,
        error: error.message || "Speed test failed"
      }));
      showBanner(error.message || "Speed test failed.", "error");
    } finally {
      if (elements.deviceDetailDialog.open) {
        renderDeviceDetail(device);
      }
      render();
    }
  }

  async function updateCudyCredentials(deviceId) {
    const device = state.devices.find(function (item) {
      return item.id === deviceId;
    });
    if (!device) {
      return;
    }

    const username = window.prompt("Cudy admin username", "root");
    if (username === null) {
      return;
    }

    const password = window.prompt("Cudy admin password", "");
    if (password === null) {
      return;
    }
    if (!password) {
      showBanner("Cudy admin password is required for stats and reboot.", "error");
      return;
    }

    try {
      const updated = await requestJson("/devices/" + deviceId, {
        method: "PUT",
        body: JSON.stringify({
          device_key: JSON.stringify({
            username: username.trim() || "root",
            password: password
          })
        })
      });
      updateDeviceInState(updated);
      showBanner("Cudy credentials updated for " + updated.name + ".", "success");
      await refreshCudyStats(deviceId);
    } catch (error) {
      showBanner(error.message || "Could not update Cudy credentials.", "error");
    }
  }

  async function rebootCudyRouter(deviceId) {
    const device = state.devices.find(function (item) {
      return item.id === deviceId;
    });
    if (!device) {
      return;
    }
    const target = await chooseCudyRebootTarget(deviceId);
    if (!target) {
      return;
    }
    const targetLabel = target === "main" ? "main router" : target === "satellites" ? "mesh satellites" : "all mesh units";
    if (!window.confirm("Reboot " + targetLabel + "? Network access may drop for a few minutes.")) {
      return;
    }
    const existing = state.states.get(deviceId) || {};
    state.states.set(deviceId, Object.assign({}, existing, { status: "loading", error: "" }));
    render();
    try {
      const result = await requestJson("/devices/" + deviceId + "/cudy/reboot", {
        method: "POST",
        body: JSON.stringify({ target: target })
      });
      state.states.set(deviceId, checkedDeviceState({
        status: "loading",
        isOn: result.is_on,
        appliance: existing.appliance,
        raw: existing.raw,
        error: ""
      }));
      showBanner(result.message || "Cudy router reboot command sent.", "success");
    } catch (error) {
      state.states.set(deviceId, checkedDeviceState({
        status: "error",
        isOn: null,
        appliance: existing.appliance,
        raw: existing.raw,
        error: error.message || "Cudy reboot failed"
      }));
      showBanner(error.message || "Cudy reboot failed.", "error");
    } finally {
      if (elements.deviceDetailDialog.open) {
        renderDeviceDetail(device);
      }
      render();
    }
  }

  function chooseCudyRebootTarget(deviceId) {
    const current = state.states.get(deviceId) || {};
    const nodes = current.appliance && Array.isArray(current.appliance.meshNodes) ? current.appliance.meshNodes : [];
    const satellites = nodes.filter(function (node) {
      return !node.isMain;
    });
    if (!satellites.length) {
      return Promise.resolve("main");
    }
    return new Promise(function (resolve) {
      elements.cudyRebootTarget.value = "main";
      elements.cudyRebootNote.textContent = "Detected " + satellites.length + " satellite" + (satellites.length === 1 ? "" : "s") + ". Mesh IPs are refreshed from Cudy before the command is sent.";

      function cleanup(value) {
        elements.cudyRebootForm.removeEventListener("submit", onSubmit);
        elements.cudyRebootDialog.removeEventListener("close", onClose);
        resolve(value);
      }

      function onSubmit(event) {
        event.preventDefault();
        const value = elements.cudyRebootTarget.value;
        cleanup(value);
        elements.cudyRebootDialog.close("confirm");
      }

      function onClose() {
        cleanup("");
      }

      elements.cudyRebootForm.addEventListener("submit", onSubmit, { once: true });
      elements.cudyRebootDialog.addEventListener("close", onClose, { once: true });
      elements.cudyRebootDialog.showModal();
    });
  }

  async function pollRingAlerts() {
    if (state.isPollingRingAlerts || !state.devices.length) {
      return;
    }
    const ringDevices = state.devices.filter(isRing);
    if (!ringDevices.length) {
      return;
    }
    state.isPollingRingAlerts = true;
    try {
      for (const device of ringDevices) {
        await checkRingAlertsForDevice(device);
      }
    } finally {
      state.isPollingRingAlerts = false;
    }
  }

  async function checkRingAlertsForDevice(device) {
    let result;
    try {
      result = await requestJson("/devices/" + device.id + "/ring/alerts");
    } catch (error) {
      return;
    }
    if (!result.active || !Array.isArray(result.alerts)) {
      return;
    }
    const freshAlert = result.alerts.find(function (alert) {
      return !state.seenRingAlerts.has(ringAlertKey(device.id, alert));
    });
    if (!freshAlert) {
      return;
    }
    state.seenRingAlerts.add(ringAlertKey(device.id, freshAlert));
    await showRingAlertPopup(device, freshAlert);
  }

  function ringAlertKey(deviceId, alert) {
    return [deviceId, alert.id || alert.kind || "alert", alert.state || ""].join(":");
  }

  async function showRingAlertPopup(device, alert) {
    playDoorbellChime();
    showRingCallNotification(device, alert);
  }

  function showRingCallNotification(device, alert) {
    dismissRingCallNotification();

    const overlay = document.createElement("div");
    overlay.className = "ring-call-overlay";
    overlay.setAttribute("role", "alertdialog");
    overlay.setAttribute("aria-label", "Ring doorbell notification");

    const card = document.createElement("section");
    card.className = "ring-call-card";

    const snapshot = document.createElement("div");
    snapshot.className = "ring-call-snapshot";
    const image = document.createElement("img");
    image.alt = device.name + " detection snapshot";
    image.src = ringTileSnapshotUrl(device.id);
    image.addEventListener("error", function () {
      snapshot.classList.add("snapshot-error");
    });
    image.addEventListener("load", function () {
      snapshot.classList.remove("snapshot-error");
    });
    const fallback = document.createElement("span");
    fallback.textContent = "Snapshot unavailable";
    snapshot.appendChild(image);
    snapshot.appendChild(fallback);

    const body = document.createElement("div");
    body.className = "ring-call-body";
    const eyebrow = document.createElement("span");
    eyebrow.className = "ring-call-eyebrow";
    eyebrow.textContent = alert.kind ? humanize(alert.kind) : "Ring alert";
    const title = document.createElement("strong");
    title.textContent = device.name;
    const subtitle = document.createElement("p");
    subtitle.textContent = "Someone was detected at the door.";
    body.appendChild(eyebrow);
    body.appendChild(title);
    body.appendChild(subtitle);

    const actions = document.createElement("div");
    actions.className = "ring-call-actions";
    const decline = document.createElement("button");
    decline.type = "button";
    decline.className = "ring-call-button decline";
    decline.setAttribute("aria-label", "Decline Ring notification");
    decline.innerHTML = "<span aria-hidden=\"true\">☎</span><strong>Decline</strong>";
    decline.addEventListener("click", function () {
      dismissRingCallNotification();
    });
    const answer = document.createElement("button");
    answer.type = "button";
    answer.className = "ring-call-button answer";
    answer.setAttribute("aria-label", "Answer Ring notification");
    answer.innerHTML = "<span aria-hidden=\"true\">☎</span><strong>Answer</strong>";
    answer.addEventListener("click", async function () {
      dismissRingCallNotification();
      await openDeviceDetail(device.id);
      window.setTimeout(function () {
        startRingLiveFeed(device.id);
      }, 450);
    });
    actions.appendChild(decline);
    actions.appendChild(answer);

    card.appendChild(snapshot);
    card.appendChild(body);
    card.appendChild(actions);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    state.activeRingNotification = overlay;
    state.ringNotificationDismissTimer = window.setTimeout(dismissRingCallNotification, 60000);

    refreshRingNotificationSnapshot(device.id, image);
  }

  function dismissRingCallNotification() {
    if (state.ringNotificationDismissTimer) {
      window.clearTimeout(state.ringNotificationDismissTimer);
      state.ringNotificationDismissTimer = null;
    }
    if (state.activeRingNotification) {
      state.activeRingNotification.remove();
      state.activeRingNotification = null;
    }
  }

  async function refreshRingNotificationSnapshot(deviceId, image) {
    try {
      await requestJson("/devices/" + deviceId + "/ring/snapshot/refresh", {
        method: "POST",
        timeoutMs: 25000
      });
      image.src = ringTileSnapshotUrl(deviceId);
    } catch (error) {}
  }

  function playDoorbellChime() {
    try {
      const audio = unlockDashboardAudio();
      if (!audio) {
        return;
      }
      audio.resume().catch(function () {});
      const now = audio.currentTime;
      [
        { frequency: 880, start: 0, duration: 0.16 },
        { frequency: 660, start: 0.18, duration: 0.22 }
      ].forEach(function (tone) {
        const oscillator = audio.createOscillator();
        const gain = audio.createGain();
        oscillator.type = "sine";
        oscillator.frequency.value = tone.frequency;
        gain.gain.setValueAtTime(0.0001, now + tone.start);
        gain.gain.exponentialRampToValueAtTime(0.18, now + tone.start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + tone.start + tone.duration);
        oscillator.connect(gain);
        gain.connect(audio.destination);
        oscillator.start(now + tone.start);
        oscillator.stop(now + tone.start + tone.duration + 0.03);
      });
    } catch (error) {}
  }

  function unlockDashboardAudio() {
    try {
      if (state.audioContext) {
        if (state.audioContext.state === "suspended") {
          state.audioContext.resume().catch(function () {});
        }
        return state.audioContext;
      }
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextCtor) {
        return null;
      }
      state.audioContext = new AudioContextCtor();
      if (state.audioContext.state === "suspended") {
        state.audioContext.resume().catch(function () {});
      }
      return state.audioContext;
    } catch (error) {
      return null;
    }
  }

  function getFilteredDevices() {
    return state.devices.filter(function (device) {
      const current = state.states.get(device.id) || { status: "loading" };
      const matchesFilter =
        state.filter === "all" ||
        (state.filter === "on" && current.status === "on") ||
        (state.filter === "off" && current.status === "off") ||
        (state.filter === "errors" && current.status === "error") ||
        (state.filter === "local" && deviceSourceKind(device) === "local") ||
        (state.filter === "cloud" && deviceSourceKind(device) === "cloud");

      const searchable = [
        device.name,
        device.model,
        device.device_type,
        device.host,
        String(device.id)
      ].join(" ").toLowerCase();

      return matchesFilter && searchable.includes(state.search);
    }).sort(comparePinnedDevices);
  }

  function comparePinnedDevices(a, b) {
    const aPinned = isFavoriteDevice(a.id);
    const bPinned = isFavoriteDevice(b.id);
    if (aPinned !== bPinned) {
      return aPinned ? -1 : 1;
    }
    return String(a.name || "").localeCompare(String(b.name || ""));
  }

  function isFavoriteDevice(deviceId) {
    return state.favoriteDeviceIds.has(String(deviceId));
  }

  function toggleFavoriteDevice(deviceId) {
    const id = String(deviceId);
    if (state.favoriteDeviceIds.has(id)) {
      state.favoriteDeviceIds.delete(id);
    } else {
      state.favoriteDeviceIds.add(id);
    }
    saveFavoriteDeviceIds();
    render();
  }

  function loadFavoriteDeviceIds() {
    try {
      return new Set(JSON.parse(window.localStorage.getItem("sentinel.favoriteDeviceIds") || "[]").map(String));
    } catch (error) {
      return new Set();
    }
  }

  function saveFavoriteDeviceIds() {
    window.localStorage.setItem("sentinel.favoriteDeviceIds", JSON.stringify(Array.from(state.favoriteDeviceIds)));
  }

  async function removeDevice(deviceId) {
    const device = state.devices.find(function (item) {
      return item.id === deviceId;
    });
    if (!device) {
      return;
    }

    const confirmed = window.confirm(
      "Remove “" + device.name + "” from Sentinel?\n\n" +
      "This does not remove or reset the physical device or its cloud account. A later provider import can add it again."
    );
    if (!confirmed) {
      return;
    }

    elements.removeDeviceButton.disabled = true;
    elements.removeDeviceButton.textContent = "Removing...";
    try {
      await requestJson("/devices/" + deviceId, { method: "DELETE" });
      state.devices = state.devices.filter(function (item) {
        return item.id !== deviceId;
      });
      state.states.delete(deviceId);
      state.inspections.delete(deviceId);
      state.favoriteDeviceIds.delete(String(deviceId));
      delete state.tileLayoutByDevice[String(deviceId)];
      saveFavoriteDeviceIds();
      saveTileLayoutPrefs();
      elements.deviceDetailDialog.close();
      render();
      showBanner(device.name + " was removed from Sentinel.", "success");
    } catch (error) {
      showBanner(error.message || "Could not remove device.", "error");
    } finally {
      elements.removeDeviceButton.disabled = false;
      elements.removeDeviceButton.textContent = "Remove device";
    }
  }

  function tileLayoutForDevice(device) {
    const override = state.tileLayoutByDevice[String(device.id)];
    if (override === "compact" || override === "large" || override === "landscape") {
      return override;
    }
    return isInlineSwitchTile(device) ? "compact" : "large";
  }

  function toggleDeviceTileLayout(deviceId) {
    const device = state.devices.find(function (item) {
      return item.id === deviceId;
    });
    if (!device) {
      return;
    }
    const currentLayout = tileLayoutForDevice(device);
    const nextLayout = isCameraTile(device)
      ? (currentLayout === "landscape" ? "large" : "landscape")
      : (currentLayout === "compact" ? "large" : "compact");
    state.tileLayoutByDevice[String(deviceId)] = nextLayout;
    saveTileLayoutPrefs();
    render();
    if (elements.deviceDetailDialog.open) {
      renderDeviceDetail(device);
    }
  }

  function loadTileLayoutPrefs() {
    try {
      return JSON.parse(window.localStorage.getItem("sentinel.tileLayoutByDevice") || "{}") || {};
    } catch (error) {
      return {};
    }
  }

  function saveTileLayoutPrefs() {
    window.localStorage.setItem("sentinel.tileLayoutByDevice", JSON.stringify(state.tileLayoutByDevice));
  }

  function getCounts() {
    const counts = { on: 0, off: 0, errors: 0, checking: 0, online: 0, offlineError: 0, local: 0, cloud: 0 };
    state.devices.forEach(function (device) {
      const current = state.states.get(device.id);
      if (deviceSourceKind(device) === "cloud") {
        counts.cloud += 1;
      } else {
        counts.local += 1;
      }
      if (!current || current.status === "loading") {
        counts.checking += 1;
      } else if (current.status === "on") {
        counts.on += 1;
        counts.online += 1;
      } else if (current.status === "off") {
        counts.off += 1;
        counts.online += 1;
      } else if (current.status === "error") {
        counts.errors += 1;
        counts.offlineError += 1;
      }
    });
    return counts;
  }

  function stateLabel(device, status, isOn) {
    if (status === "loading") {
      return "Refreshing";
    }
    if (status === "error") {
      return "Error";
    }
    if (isLock(device)) {
      return isOn ? "Locked" : "Unlocked";
    }
    if (isGarage(device) || isSensor(device)) {
      return isOn ? "Open" : "Closed";
    }
    if (isRing(device)) {
      return isOn ? "Online" : "Offline";
    }
    if (isIpCamera(device)) {
      return isOn ? "Online" : "Offline";
    }
    if (isCudy(device)) {
      return isOn ? "Online" : "Offline";
    }
    if (isPrinter(device)) {
      return isOn ? "Online" : "Offline";
    }
    if (isNest(device)) {
      return isOn ? "Active" : "Idle";
    }
    return isOn ? "On" : "Off";
  }

  function stateStatus(device, result) {
    if (isGarage(device) && result.is_open !== null && result.is_open !== undefined) {
      return result.is_open ? "on" : "off";
    }
    if (isNest(device)) {
      return result.is_on ? "on" : "off";
    }
    return result.is_on ? "on" : "off";
  }

  function isGarage(device) {
    const type = deviceText(device);
    return type.includes("msg") || type.includes("garage") || type.includes("doorcontrol");
  }

  function isDimmer(device) {
    const type = deviceText(device);
    return type.includes("mss560") || type.includes("switchlevel");
  }

  function isSimpleLightSwitch(device) {
    const type = deviceText(device);
    return !isDimmer(device) && (
      type.includes("mss510") ||
      type.includes("mss550") ||
      (type.includes("wall switch") && type.includes("switch"))
    );
  }

  function isAppliance(device) {
    const type = deviceText(device);
    return [
      "washer",
      "dryer",
      "laundry",
      "refrigerator",
      "fridge",
      "freezer",
      "microwave",
      "oven",
      "range",
      "stove",
      "thermostat"
    ].some(function (needle) {
      return type.includes(needle);
    });
  }

  function isSensor(device) {
    return deviceText(device).includes("contactsensor");
  }

  function isLock(device) {
    const type = deviceText(device);
    return device.brand === "yale" || type.includes("lock");
  }

  function isRing(device) {
    return device.brand === "ring";
  }

  function isIpCamera(device) {
    return device.brand === "ip-camera";
  }

  function isCameraTile(device) {
    return isRing(device) || isIpCamera(device);
  }

  function isCameraLandscapeTile(device) {
    return isCameraTile(device) && tileLayoutForDevice(device) === "landscape";
  }

  function isSmartThings(device) {
    return device.brand === "smartthings";
  }

  function isCudy(device) {
    return device.brand === "cudy";
  }

  function isNest(device) {
    return device.brand === "nest";
  }

  function isPrinter(device) {
    return device.brand === "printer";
  }

  function deviceText(device) {
    return [device.name, device.model, device.device_type, device.brand].map(function (part) {
      return String(part || "").toLowerCase();
    }).join(" ");
  }

  async function requestJson(url, options) {
    const requestOptions = Object.assign({
      headers: {
        "Content-Type": "application/json"
      }
    }, options || {});
    const timeoutMs = requestOptions.timeoutMs;
    let timeoutId;

    if (timeoutMs && window.AbortController) {
      const controller = new AbortController();
      requestOptions.signal = controller.signal;
      delete requestOptions.timeoutMs;
      timeoutId = window.setTimeout(function () {
        controller.abort();
      }, timeoutMs);
    } else {
      delete requestOptions.timeoutMs;
    }

    let response;
    try {
      response = await fetch(url, requestOptions);
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("State check timed out");
      }
      throw error;
    } finally {
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    }

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch (error) {
        detail = response.statusText;
      }
      throw new Error(detail);
    }

    if (response.status === 204) {
      return null;
    }
    return response.json();
  }

  function showBanner(message, type) {
    elements.statusBanner.textContent = message;
    elements.statusBanner.className = "status-banner " + type;
    elements.statusBanner.hidden = false;
    window.clearTimeout(showBanner.timeoutId);
    showBanner.timeoutId = window.setTimeout(function () {
      elements.statusBanner.hidden = true;
    }, 4200);
  }
})();
