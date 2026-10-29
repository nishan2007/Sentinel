# Sentinel Local Controller

A local FastAPI backend for Sentinel smart-home device control. It supports LAN control for Meross smart plugs and switches and cloud-backed integrations for other device sources.

Meross LAN control is unofficial and can vary by model and firmware. This project starts with smart-plug style devices on channel `0`, while keeping the database and service layer ready for multi-channel power strips later.

## Project Structure

```text
sentinel-controller/
  app/
    main.py
    db.py
    models.py
    meross_service.py
    discovery.py
    schemas.py
  data/
    devices.db
  requirements.txt
  .env
```

## Setup

From the parent Sentinel folder, the easiest start path is:

```bash
./start-sentinel.sh
```

On macOS, you can also double-click `Start Sentinel.command`.

For SmartThings OAuth without a public tunnel, start Sentinel over local HTTPS:

```bash
SENTINEL_HTTPS=1 SENTINEL_HOST=127.0.0.1 ./start-sentinel.sh
```

On macOS, you can also double-click `Start Sentinel HTTPS.command` from the parent Sentinel folder. The first HTTPS start creates a local self-signed certificate in `sentinel-controller/data/tls/`.

Use these SmartThings OAuth values for local HTTPS:

```text
Target URL:   https://localhost:8088
Redirect URI: https://localhost:8088/setup/smartthings/oauth/callback
```

Your browser may show a local certificate warning the first time. Open the dashboard anyway so the OAuth callback can return to Sentinel.

### macOS/Linux

```bash
cd sentinel-controller
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

### Windows PowerShell

```powershell
cd sentinel-controller
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

## Configuration

Tuya / Smart Life devices automatically recover from changed IP addresses when a
LAN request fails. Sentinel discovers the saved device ID, verifies the candidate
with its existing local key, saves the working address, and retries the request.
Dashboard and Apple Home requests both use the updated address. Failed discovery
is limited to once per device every 30 seconds. Discovery requires the device's
local broadcast network; routed VLANs may still need a DHCP reservation or a
manual address update. This recovery does not apply to cameras or printers.

Printer monitoring includes a Python SNMP client, so Windows does not need separate
`snmpget` or `snmpwalk` programs. Existing Net-SNMP installations are still supported.
After updating requirements, restart Sentinel and rediscover printers.

The dashboard's Sentinel setup section and Cameras / NVR header include a **Restart Sentinel** button. Start Sentinel using the platform launcher (or `python -m app.server --host 0.0.0.0 --port 8088`) to enable it. The server gracefully stops recording and device tasks, starts a fresh process with the same address and TLS settings, and the page reloads when ready. After updating an existing installation, close the old server and open the launcher once. Direct `uvicorn` starts do not support this button.

`.env`:

```env
DATABASE_PATH=data/devices.db
MEROSS_REQUEST_TIMEOUT_SECONDS=5
MEROSS_SCAN_CONNECT_TIMEOUT_SECONDS=0.35
CUDY_REQUEST_TIMEOUT_SECONDS=5
SENTINEL_FFMPEG_PATH=/optional/path/to/ffmpeg
SENTINEL_FFPROBE_PATH=/optional/path/to/ffprobe
SENTINEL_RECORDING_ROOT=/optional/local/or/mounted/nas/path
```

Reserve static IPs for your Meross devices in the router so saved device records stay stable, for example:

```text
Meross Sign Plug:   10.1.1.60
Meross Lights Plug: 10.1.1.61
Meross Office Plug: 10.1.1.62
```

Keep the Windows wall PC and Meross devices on the same LAN.

## API

```text
GET    /health
GET    /devices
POST   /devices
GET    /devices/{id}
PUT    /devices/{id}
DELETE /devices/{id}
POST   /devices/{id}/turn-on
POST   /devices/{id}/turn-off
POST   /devices/{id}/toggle
GET    /devices/{id}/state
POST   /devices/{id}/open
POST   /devices/{id}/close
POST   /devices/{id}/lock
POST   /devices/{id}/unlock
POST   /devices/{id}/brightness
GET    /devices/{id}/capabilities
POST   /devices/{id}/tuya/command
POST   /devices/{id}/smartthings/command
GET    /devices/{id}/cudy/stats
POST   /devices/{id}/cudy/reboot
POST   /scan/network
POST   /setup/meross-cloud/import
POST   /setup/smartthings/import
POST   /setup/ring/import
POST   /setup/yale/import
```

OpenAPI docs are available at:

```text
http://localhost:8088/docs
```

The local dashboard is available at:

```text
http://localhost:8088/dashboard
```

The local camera/NVR screen is available at:

```text
http://localhost:8088/cameras
```

## IP Cameras And Recording

Sentinel supports local ONVIF discovery and manual RTSP camera setup. Install FFmpeg and FFprobe on the computer running Sentinel before enabling live video or recording:

Discovery combines same-LAN ONVIF multicast with bounded unicast probing of directly connected LAN and routed private `/22` through `/30` networks in the host routing table. Cameras that do not answer multicast can still be found through ONVIF or RTSP, including across reachable VPNs and VLANs. Add extra networks in the setup form or with `SENTINEL_CAMERA_SUBNETS=10.1.1.0/24,192.168.50.0/24`. The VPN/router firewall must permit the camera's ONVIF web port and RTSP port from the Sentinel computer. RTSP-only results require a stream path and camera credentials for video setup.

- macOS with Homebrew: `brew install ffmpeg`
- Windows with winget: `winget install Gyan.FFmpeg`

Restart Sentinel after installation. If FFmpeg is installed in a custom folder, set `SENTINEL_FFMPEG_PATH` and `SENTINEL_FFPROBE_PATH` in `.env`.

Recordings default to `data/recordings`. A mounted SMB or NFS share works by selecting its mounted folder in Cameras / NVR → Storage. Mount the share before Sentinel starts and ensure the Sentinel user can write to it. When no capacity is configured, Sentinel preserves 10 GB of free space and removes the oldest indexed camera segments first. It never removes unrelated files.

Camera credentials are stored only in the local SQLite camera profile and are excluded from camera APIs and logs. Sentinel remains LAN-only and has no dashboard login, so restrict port `8088` to trusted networks.

## Add A Device

```bash
curl -X POST http://localhost:8088/devices \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Meross Plug","brand":"meross","model":"MSS110","host":"10.1.1.60","device_key":"YOUR_KEY","channel":0}'
```

Example JSON:

```json
{
  "name": "Front Sign Plug",
  "brand": "meross",
  "model": "MSS110",
  "host": "10.1.1.60",
  "device_key": "PASTE_DEVICE_KEY_HERE",
  "channel": 0
}
```

## Control A Device

```bash
curl -X POST http://localhost:8088/devices/1/turn-on
curl -X POST http://localhost:8088/devices/1/turn-off
curl -X POST http://localhost:8088/devices/1/toggle
curl http://localhost:8088/devices/1/state
```

Garage door devices use:

```bash
curl -X POST http://localhost:8088/devices/6/open
curl -X POST http://localhost:8088/devices/6/close
curl http://localhost:8088/devices/6/state
```

Dimmer-capable devices use:

```bash
curl -X POST http://localhost:8088/devices/10/brightness \
  -H "Content-Type: application/json" \
  -d '{"luminance":50}'
```

## Creality K2 Pro 3D Printer

Add the K2 Pro from **Add devices → Printers** and choose **Creality K2 Pro 3D printer**. Enter the printer's LAN IP address. Sentinel reads the local Creality WebSocket on port `9999` and shows the active file, print state and progress, layers, elapsed and remaining time, nozzle/bed/chamber temperatures, fan speeds, print speed, and CFS filament slots (including material, color, RFID percentage, and selected slot when reported).

The camera field is optional and defaults to:

```text
http://PRINTER-IP:4408/camera.html
```

That URL expects a local K2 camera viewer installed in Fluidd. If your firmware exposes the legacy camera page instead, enter its URL (commonly `http://PRINTER-IP:8000/`). Camera interfaces vary by K2 firmware; the dashboard also provides an **Open camera viewer** link if the browser refuses to embed the page. Keep ports `9999`, `4408`, and any camera endpoint private to your LAN or VPN.

Sentinel keeps up to 200 diagnostic events per printer. It records disconnect/reconnect transitions, print errors or unexpected stops, and the job, layer, temperatures, and progress at the time. The printer detail screen can also enable key-based SSH diagnostics. When enabled, Sentinel connects as `root` using the Sentinel host's existing SSH key and samples `/proc/uptime`, the Linux boot ID, and recent `logread` output once per minute. Boot-ID changes or uptime resets provide strong evidence of an actual printer reboot instead of a Wi-Fi interruption. Configure key access first; Sentinel deliberately does not store an SSH password.

## Scan The Network

Scan the computer's current `/24` subnet for hosts with port `80` open:

```bash
curl -X POST http://localhost:8088/scan/network
```

Scan a specific subnet:

```bash
curl -X POST http://localhost:8088/scan/network \
  -H "Content-Type: application/json" \
  -d '{"subnet":"10.1.1.0/24","port":80,"timeout_seconds":0.35}'
```

The scan endpoint only finds hosts with an open port. It does not prove a host is Meross until you add the correct IP and device key and call `/state`.

## Easy Device Import

The easiest setup path for the future app is:

1. Ask the user for their Meross email/password once.
2. Call `POST /setup/meross-cloud/import`.
3. Save imported devices with the Meross account key as `device_key`.
4. Use LAN control after that.

The backend does not store the Meross email or password. It only stores imported device records and the Meross key needed to sign local LAN commands.

```bash
curl -X POST http://localhost:8088/setup/meross-cloud/import \
  -H "Content-Type: application/json" \
  -d '{"email":"YOUR_MEROSS_EMAIL","password":"YOUR_MEROSS_PASSWORD","save_devices":true}'
```

If your Meross account uses MFA, include:

```json
{
  "email": "YOUR_MEROSS_EMAIL",
  "password": "YOUR_MEROSS_PASSWORD",
  "mfa_code": "123456",
  "save_devices": true
}
```

The importer tries to discover each device's LAN IP. If an IP is not discovered, find it in the router by MAC address and update the imported device's `host` with `PUT /devices/{id}`.

## SmartThings Import

SmartThings devices should be imported with a SmartThings OAuth-In SmartApp for long-term access. New SmartThings personal access tokens are valid for only 24 hours, so PAT import remains available only as a short-lived fallback. These devices are controlled through the SmartThings cloud API, not LAN-local Meross control.

Create an OAuth-In SmartApp with the SmartThings CLI, request the device scopes you need such as `r:devices:* x:devices:*`, and register this redirect URI:

```text
http://localhost:8088/setup/smartthings/oauth/callback
```

Open the SmartThings authorization URL with your OAuth app values:

```text
https://api.smartthings.com/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A8088%2Fsetup%2Fsmartthings%2Foauth%2Fcallback&scope=r%3Adevices%3A%2A%20x%3Adevices%3A%2A
```

After SmartThings redirects back to Sentinel, paste the authorization code into the dashboard import form with the OAuth client ID and secret. Sentinel stores the refresh-token bundle on imported SmartThings device records and refreshes access tokens automatically.

```bash
curl -X POST http://localhost:8088/setup/smartthings/import \
  -H "Content-Type: application/json" \
  -d '{
    "client_id":"YOUR_OAUTH_CLIENT_ID",
    "client_secret":"YOUR_OAUTH_CLIENT_SECRET",
    "authorization_code":"CODE_FROM_CALLBACK",
    "redirect_uri":"http://localhost:8088/setup/smartthings/oauth/callback",
    "save_devices":true,
    "exclude_overlaps":true
  }'
```

When `exclude_overlaps` is true, the importer skips likely duplicate SmartThings records for devices already controlled directly through a native source such as Meross, Ring, or Yale. It checks for native manufacturer metadata, matching device IDs, and matching normalized device names.

Washer/dryer, refrigerator, microwave, oven/range, and contact-sensor style SmartThings devices are imported as read-only appliance/status cards when their capabilities are present. These cards intentionally show `Refresh` instead of generic On/Off/Toggle controls until a safe model-specific command is identified.

Use `GET /devices/{id}/capabilities` or the dashboard's `Inspect` button on SmartThings appliance cards to see which capabilities expose commands versus status-only attributes. Add controls only after confirming the exact command and allowed argument values for that model.

The dashboard can send validated SmartThings commands exposed by the inspector. Broad raw capabilities such as `execute`, `ocf`, `refresh`, and software update commands are hidden from dashboard execution.

## Nest Thermostat Import

Nest thermostats should be imported from Google Nest Device Access / Smart Device Management API when you want the closest official source. Google Home is useful for app/Assistant control, but it is not the source API for this local dashboard.

Create a Google Nest Device Access project, enable the Smart Device Management API on a Google Cloud OAuth client, and register this redirect URI:

```text
http://localhost:8088/setup/nest/oauth/callback
```

Then import with an authorization code, refresh token, or short-lived access token:

```bash
curl -X POST http://localhost:8088/setup/nest/import \
  -H "Content-Type: application/json" \
  -d '{
    "project_id":"YOUR_DEVICE_ACCESS_PROJECT_ID",
    "client_id":"YOUR_OAUTH_CLIENT_ID",
    "client_secret":"YOUR_OAUTH_CLIENT_SECRET",
    "authorization_code":"GOOGLE_AUTHORIZATION_CODE",
    "save_devices":true,
    "exclude_overlaps":true
  }'
```

Imported Nest rows use `brand: "nest"` and `device_type: "thermostat"`. Their `device_key` stores the Device Access project id plus OAuth token material as JSON so the dashboard can read current temperature, humidity, HVAC mode/status, and send SDM mode/setpoint commands. Native Nest rows disable lower-priority SmartThings mirrors that match the same thermostat name or id.

Thermostat controls use Celsius at the API boundary because SDM setpoint commands require Celsius, while the dashboard displays Fahrenheit where possible.

## Ring Import

Ring devices can be imported with your Ring email and password. If Ring requires two-factor authentication, call the endpoint once to trigger the code, then call it again with `otp_code`.

```bash
curl -X POST http://localhost:8088/setup/ring/import \
  -H "Content-Type: application/json" \
  -d '{"email":"YOUR_RING_EMAIL","password":"YOUR_RING_PASSWORD","otp_code":"123456","save_devices":true,"exclude_overlaps":true}'
```

Imported Ring cards are status-only for now. Native Ring rows automatically hide lower-priority SmartThings copies that match the same device name or ID.

## Yale Import

Yale locks can be imported with your Yale/August email and password for supported non-OAuth brands. If Yale requires verification, the first import sends a code; run import again with `verification_code`.

```bash
curl -X POST http://localhost:8088/setup/yale/import \
  -H "Content-Type: application/json" \
  -d '{"email":"YOUR_YALE_EMAIL","password":"YOUR_YALE_PASSWORD","verification_code":"123456","brand":"yale_access","save_devices":true,"exclude_overlaps":true}'
```

Supported password-login `brand` values are `yale_access`, `yale_home`, and `august`. Native Yale rows automatically hide lower-priority SmartThings copies that match the same lock name or ID. The API still accepts `access_token` as an optional fallback if you already have one.

## Cudy Router Management

Add a Cudy router as a normal device row with `brand` set to `cudy`. The dashboard will show it as a router with `Stats`, `Reboot`, and `Refresh` actions.

```bash
curl -X POST http://localhost:8088/devices \
  -H "Content-Type: application/json" \
  -d '{"name":"Main Cudy Router","brand":"cudy","model":"WR3000","host":"192.168.10.1","device_type":"router","device_key":"{\"username\":\"root\",\"password\":\"YOUR_ADMIN_PASSWORD\"}"}'
```

If you omit `device_key`, the dashboard can still probe whether the router web UI is reachable, but stats and reboot require credentials. The management path uses the LuCI/ubus API exposed by OpenWrt-style Cudy firmware. Stock firmware that only exposes the browser admin interface may report reachability but reject stats or reboot until the router exposes ubus or a supported management endpoint.

```bash
curl http://localhost:8088/devices/12/cudy/stats
curl -X POST http://localhost:8088/devices/12/cudy/reboot
```

## Milexus / Smart Life AC (local Tuya LAN)

Sentinel can control a Wi-Fi Milexus AC locally when the unit is a Tuya / Smart
Life device. Runtime control goes directly from Sentinel to the AC on the LAN;
Sentinel neither links to nor stores a Smart Life account.

You need its reserved LAN IP, Tuya device ID, 16-character local key, and
protocol version (usually 3.3, 3.4, or 3.5). Find the device ID and version with:

```powershell
python -m tinytuya scan
```

Stock Tuya firmware does not disclose the local key over the LAN. Retrieve it
once using TinyTuya's Tuya IoT setup wizard (temporary cloud project/app link)
or a local Android extraction method. This is only for key retrieval, not normal
operation. Resetting or re-pairing the AC changes the key.

Inspect the AC's raw datapoints:

```powershell
python -c "import tinytuya; d=tinytuya.Device('DEVICE_ID','192.168.1.50','LOCAL_KEY',version=3.3); print(d.status())"
```

Compare that output while changing power, mode, temperature, fan, and swing in
Smart Life. Record which numbered DP changes. Add the AC using the observed DP
numbers (the numbers below are placeholders):

```powershell
$config = '{"local_key":"LOCAL_KEY","version":3.3,"temperature_divisor":1,"dps":{"power":"1","mode":"2","target_temperature":"3","current_temperature":"4","fan_speed":"5","swing":"8"}}'
$body = @{name='Milexus AC'; brand='milexus'; model='Smart WiFi AC'; host='192.168.1.50'; device_uuid='TUYA_DEVICE_ID'; device_type='air-conditioner'; device_key=$config} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8088/devices -ContentType application/json -Body $body
```

On, Off, Toggle, and state now use Sentinel's normal routes. AC settings use:

```powershell
$body = @{power=$true; mode='cold'; target_temperature=24; fan_speed='auto'} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8088/devices/DEVICE_ROW_ID/tuya/command -ContentType application/json -Body $body
```

Use the exact mode/fan values shown in the raw response. If `240` means 24.0 C,
set `temperature_divisor` to `10`. Reserve the IP and allow local TCP port 6668.
After setup you can block the AC's internet access, provided Sentinel can still
reach it on the LAN/VLAN.

## Manual Device Key Notes

For testing, pair the device normally in the Meross app, use a temporary Home Assistant install with the Meross LAN HACS integration to retrieve the device key, then save the IP and key in this controller. Normal LAN control should work without internet when:

- the device stays on the same Wi-Fi/LAN
- the router reserves the device IP
- the saved key is correct
- the device firmware supports local LAN control

## Apple Home bridge

Sentinel can advertise supported devices as one local Apple Home bridge. Use
the **Set up Apple Home** button in Sentinel, or open
`http://THIS-PC-IP:8088/homekit` from any device on the same trusted network.
Enable the bridge, then scan the displayed QR code in the Apple Home app. The Sentinel computer and Apple devices must be on
the same LAN, and the network must allow Bonjour/mDNS traffic.

Switches, outlets, lights, locks, garage doors, thermostats, common sensors,
and configured local RTSP cameras are mapped to native Apple Home services.
Camera streaming requires FFmpeg. Devices are selected by default and can be
disabled individually on the Apple Home setup page to avoid duplicates from
another bridge.

Ring doorbells publish doorbell and motion events through the bridge. Ring live
video remains in Sentinel's camera view in this release because its cloud WebRTC
feed cannot be passed directly to HomeKit's SRTP camera session. Local RTSP
cameras support snapshots and live Apple Home video.

Pairing keys remain local in `data/homekit/`. The **Reset pairing** action
removes only the Apple Home bridge pairing; it does not delete Sentinel devices.
This software bridge is intended for personal/local installations and is not an
Apple-certified commercial accessory.

## Implementation Notes

- `app/meross_service.py` owns all Meross LAN protocol logic.
- The current command path posts signed JSON to `http://{host}/config`.
- `Appliance.System.All` is used for state.
- `Appliance.Control.ToggleX` is used for smart-plug on/off commands.
- Errors are mapped to HTTP responses for missing host/key, disabled devices, timeouts, unreachable devices, bad keys/signatures, and unsupported response shapes.
