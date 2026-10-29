const $ = (id) => document.getElementById(id);
const message = (value) => { $("message").textContent = value || ""; };

async function api(path, options) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

function renderStatus(status) {
  $("enabled").checked = status.enabled;
  $("bridgeName").value = status.bridge_name;
  $("port").value = status.port;
  $("statusBadge").textContent = status.running ? "Bridge online" : status.enabled ? "Bridge stopped" : "Disabled";
  $("statusBadge").classList.toggle("online", status.running);
  $("pairing").hidden = !status.running || status.paired || !status.setup_uri;
  $("paired").hidden = !status.paired;
  if (status.setup_uri) $("qr").src = `/api/homekit/pairing-qr?t=${Date.now()}`;
  $("pin").textContent = status.pin || "";
  if (status.last_error) message(status.last_error);
}

async function load() {
  const [status, devices] = await Promise.all([api("/api/homekit/status"), api("/api/homekit/accessories")]);
  renderStatus(status);
  $("count").textContent = `${devices.filter((d) => d.enabled).length} selected`;
  $("devices").replaceChildren(...devices.map((device) => {
    const row = document.createElement("label"); row.className = `device${device.supported ? "" : " unsupported"}`;
    const copy = document.createElement("span");
    copy.innerHTML = `<strong>${device.name}</strong><small>${device.brand} · ${device.profile || "Unsupported"}${device.unsupported_reason ? ` · ${device.unsupported_reason}` : ""}</small>`;
    const input = document.createElement("input"); input.type = "checkbox"; input.checked = device.enabled; input.disabled = !device.supported;
    input.addEventListener("change", async () => { try { await api(`/api/homekit/accessories/${device.device_id}`, {method:"PUT",body:JSON.stringify({enabled:input.checked})}); message(`${device.name} updated.`); await load(); } catch(error){ input.checked=!input.checked; message(error.message); } });
    row.append(copy,input); return row;
  }));
}

$("save").addEventListener("click", async () => { try { renderStatus(await api("/api/homekit/settings", {method:"PUT",body:JSON.stringify({enabled:$("enabled").checked,bridge_name:$("bridgeName").value,port:Number($("port").value)})})); message("Apple Home settings saved."); await load(); } catch(error){message(error.message);} });
$("restart").addEventListener("click", async () => { try { message("Restarting bridge…"); renderStatus(await api("/api/homekit/restart", {method:"POST"})); message("Bridge restarted."); } catch(error){message(error.message);} });
$("reset").addEventListener("click", async () => { if(!confirm("Remove this Sentinel Bridge pairing? You must add it to Apple Home again.")) return; try { renderStatus(await api("/api/homekit/reset-pairing", {method:"POST"})); message("Pairing reset."); } catch(error){message(error.message);} });
load().catch((error) => message(error.message));
