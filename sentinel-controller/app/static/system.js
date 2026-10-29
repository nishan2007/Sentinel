(() => {
  const button = document.getElementById("restartSentinelButton");
  const status = document.getElementById("restartSentinelStatus");
  if (!button || !status) return;
  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Restarting…";
    status.textContent = "Restarting Sentinel. Video and recording will pause briefly.";
    try {
      const response = await fetch("/api/system/restart", {
        method: "POST", headers: { "X-Sentinel-Action": "restart" },
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "Unable to request restart. Refresh the page and try again.");
      }
      const previous = await response.json();
      const deadline = Date.now() + 90000;
      while (Date.now() < deadline) {
        await pause(1500);
        try {
          const ready = await fetch("/api/system/status", {
            cache: "no-store", signal: AbortSignal.timeout(3000),
          });
          if (ready.ok && (await ready.json()).instance_id !== previous.instance_id) {
            window.location.reload();
            return;
          }
        } catch (_) { /* Expected while the server is shutting down or starting. */ }
      }
      throw new Error("Sentinel has not returned yet. Check its server window, then refresh this page.");
    } catch (error) {
      status.textContent = error.message;
      button.disabled = false;
      button.textContent = "Restart Sentinel";
    }
  });
})();
