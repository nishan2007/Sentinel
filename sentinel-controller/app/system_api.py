import secrets

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

router = APIRouter()
INSTANCE_ID = secrets.token_hex(16)


@router.get("/api/system/status")
async def system_status(request: Request):
    return {"instance_id": INSTANCE_ID,
            "restart_supported": callable(getattr(request.app.state, "request_restart", None))}


@router.post("/api/system/restart", status_code=202)
async def restart(request: Request, background_tasks: BackgroundTasks):
    # Require a same-origin browser request with a custom header, blocking forms
    # and cross-origin fetches from restarting this unauthenticated LAN service.
    if (request.headers.get("x-sentinel-action") != "restart"
            or request.headers.get("sec-fetch-site") == "cross-site"
            or (request.headers.get("origin") and
                request.headers["origin"] != str(request.base_url).rstrip("/"))):
        raise HTTPException(403, "Restart must be requested from the Sentinel web app.")
    callback = getattr(request.app.state, "request_restart", None)
    if not callable(callback):
        raise HTTPException(409, "Close Sentinel and start it with the updated Start Sentinel launcher to enable web restarts.")
    if not getattr(request.app.state, "restart_requested", False):
        request.app.state.restart_requested = True
        background_tasks.add_task(callback)
    return {"status": "restarting", "instance_id": INSTANCE_ID}
