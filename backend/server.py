"""
FastAPI backend for the KOTOR Mod Installer.

Wraps the existing Python pipeline (scraper / detector / patcher_strategy /
pipeline) behind a small REST API plus a WebSocket that streams live status,
log, and progress events. The Tauri + React frontend talks to this over
localhost. The same backend is frozen by PyInstaller into a sidecar exe and
spawned by the Tauri shell on launch.

Run standalone:  python -m backend.server --port 8756
"""

import argparse
import asyncio
import threading
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config as cfg
from backend.models import (
    LoginRequest,
    SettingsModel,
    StartInstallRequest,
    build_mod_to_dict,
    pipeline_mod_to_dict,
)
from installer._version import __version__
from installer.config_loader import find_system_holopatcher
from installer.pipeline import ModStatus, Pipeline
from scraper.build_scraper import BUILD_GAME, BUILD_URLS, scrape_build
from scraper.deadlystream import AuthError, DeadlyStreamClient

BUILD_LABELS = {
    "k1_full":        "KOTOR 1 — Full Build",
    "k1_spoilerfree": "KOTOR 1 — Spoiler-Free",
    "k2_full":        "KOTOR 2 — Full Build",
    "k2_spoilerfree": "KOTOR 2 — Spoiler-Free",
}


# ---------------------------------------------------------------------------
# Event hub — bridges background-thread pipeline callbacks to WebSocket clients
# ---------------------------------------------------------------------------

class EventHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._queue: "asyncio.Queue[dict]" = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._history: list[dict] = []   # last-known state replay for new clients

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    def publish(self, event: dict) -> None:
        """Thread-safe publish from any thread."""
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except RuntimeError:
            pass

    async def run(self) -> None:
        while True:
            event = await self._queue.get()
            dead = []
            for ws in list(self._clients):
                try:
                    await ws.send_json(event)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------

class AppState:
    def __init__(self) -> None:
        self.client = DeadlyStreamClient()
        self.hub = EventHub()
        self.pipeline: Optional[Pipeline] = None
        self.loaded_mods: dict[str, list] = {}   # build_key -> list[BuildMod]
        self.current_build: str = ""

    def game_path_for(self, build_key: str, override: Optional[str]) -> Optional[Path]:
        if override:
            return Path(override)
        conf = cfg.load()
        game = BUILD_GAME.get(build_key, "KOTOR1")
        key = "kotor1_path" if game == "KOTOR1" else "kotor2_path"
        p = conf.get(key, "")
        return Path(p) if p else None


state = AppState()
app = FastAPI(title="KOTOR Mod Installer Backend", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # localhost-only service; Tauri + Vite dev
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mod-manager (Library) routes
from backend.library_routes import bind_state as _bind_library, library_router  # noqa: E402

_bind_library(state)
app.include_router(library_router)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup() -> None:
    state.hub.bind_loop(asyncio.get_running_loop())
    asyncio.create_task(state.hub.run())
    # Best-effort auto-login from saved credentials
    u, p = DeadlyStreamClient.load_credentials()
    if u and p:
        threading.Thread(target=_login_safe, args=(u, p), daemon=True).start()


def _login_safe(u: str, p: str) -> None:
    try:
        state.client.login(u, p)
        state.hub.publish({"type": "auth", "logged_in": True, "username": u})
        state.hub.publish({"type": "log", "message": f"Logged in as {u}.", "tag": "success"})
    except AuthError as e:
        state.hub.publish({"type": "log", "message": f"Auto-login failed: {e}", "tag": "error"})


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/status")
def status() -> dict:
    holo = find_system_holopatcher()
    return {
        "version": __version__,
        "logged_in": state.client._logged_in,
        "pipeline_running": bool(state.pipeline and state.pipeline.is_running),
        "shim_available": holo is not None,
        "shim_path": str(holo) if holo else None,
        "current_build": state.current_build,
    }


@app.get("/api/builds")
def builds() -> dict:
    return {
        "builds": [
            {"key": k, "label": BUILD_LABELS.get(k, k), "game": BUILD_GAME.get(k, "")}
            for k in BUILD_URLS
        ]
    }


@app.post("/api/login")
def login(req: LoginRequest) -> dict:
    try:
        state.client.login(req.username, req.password)
    except AuthError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    if req.save:
        DeadlyStreamClient.save_credentials(req.username, req.password)
    state.hub.publish({"type": "auth", "logged_in": True, "username": req.username})
    return {"ok": True, "username": req.username}


@app.post("/api/logout")
def logout() -> dict:
    """Reset the in-memory DeadlyStream session (keeps saved credentials)."""
    state.client = DeadlyStreamClient()
    state.hub.publish({"type": "auth", "logged_in": False, "username": ""})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Self-update check (GitHub Releases)
# ---------------------------------------------------------------------------

UPDATE_REPO = "ChristopherVR/kotor-mod-manager"


def _version_tuple(v: str) -> tuple:
    import re
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


@app.get("/api/update/check")
def update_check() -> dict:
    """Compare the running version against the latest GitHub release."""
    import json
    import urllib.request

    api_url = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
    req = urllib.request.Request(
        api_url,
        headers={"User-Agent": "kotor-mod-installer",
                 "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"available": False, "current_version": __version__, "error": str(e)}

    tag = data.get("tag_name", "") or ""
    latest = tag.lstrip("vV")
    available = bool(latest) and _version_tuple(latest) > _version_tuple(__version__)
    asset_url = None
    for a in data.get("assets", []):
        if a.get("name", "").lower().endswith(".exe"):
            asset_url = a.get("browser_download_url")
            break
    return {
        "available": available,
        "current_version": __version__,
        "latest_version": latest,
        "url": data.get("html_url"),
        "asset_url": asset_url,
        "notes": (data.get("body") or "")[:2000],
        "repo": UPDATE_REPO,
    }


@app.post("/api/update/open")
def update_open(url: str = "") -> dict:
    """Open a release URL in the user's default browser."""
    import webbrowser
    target = url or f"https://github.com/{UPDATE_REPO}/releases/latest"
    try:
        webbrowser.open(target)
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/api/settings")
def get_settings() -> dict:
    conf = cfg.load()
    return {
        "kotor1_path": conf.get("kotor1_path", ""),
        "kotor2_path": conf.get("kotor2_path", ""),
        "download_dir": conf.get("download_dir", ""),
    }


@app.post("/api/settings")
def set_settings(s: SettingsModel) -> dict:
    conf = cfg.load()
    conf.update(s.model_dump())
    cfg.save(conf)
    return {"ok": True}


@app.post("/api/builds/{build_key}/load")
def load_build(build_key: str) -> dict:
    if build_key not in BUILD_URLS:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Unknown build"})
    try:
        mods = scrape_build(build_key)
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": f"Scrape failed: {e}"})
    state.loaded_mods[build_key] = mods
    state.current_build = build_key
    return {"ok": True, "build_key": build_key, "mods": [build_mod_to_dict(m) for m in mods]}


@app.get("/api/credentials")
def get_credentials() -> dict:
    u, _ = DeadlyStreamClient.load_credentials()
    return {"username": u}


@app.post("/api/install/start")
def install_start(req: StartInstallRequest) -> dict:
    if state.pipeline and state.pipeline.is_running:
        return JSONResponse(status_code=409, content={"ok": False, "error": "Install already running"})
    mods = state.loaded_mods.get(req.build_key)
    if not mods:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Load the mod list first"})
    if not state.client._logged_in:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Not logged in"})

    game_path = state.game_path_for(req.build_key, req.game_path)
    if not game_path or not game_path.exists():
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "game_path_required",
                     "game": BUILD_GAME.get(req.build_key, "")},
        )

    conf = cfg.load()
    dl_dir = Path(conf.get("download_dir") or (Path.home() / "Downloads" / "KOTOR_Mods"))

    # Persist a game_path override into settings for convenience.
    if req.game_path:
        key = "kotor1_path" if BUILD_GAME.get(req.build_key) == "KOTOR1" else "kotor2_path"
        conf[key] = req.game_path
        cfg.save(conf)

    hub = state.hub

    def on_status(file_id: str, st: ModStatus, detail: str) -> None:
        hub.publish({"type": "status", "file_id": file_id,
                     "status": st.name, "status_label": st.value, "detail": detail})

    def on_log(message: str, tag: str) -> None:
        hub.publish({"type": "log", "message": message, "tag": tag})

    def on_progress(file_id: str, pct: float, kb: int, total_kb: int) -> None:
        hub.publish({"type": "progress", "file_id": file_id,
                     "pct": pct, "kb": kb, "total_kb": total_kb})

    def on_install_progress(file_id: str, pct: float, label: str) -> None:
        hub.publish({"type": "install_progress", "file_id": file_id,
                     "pct": pct, "label": label})

    state.pipeline = Pipeline(
        mods=mods,
        game_path=game_path,
        download_dir=dl_dir,
        client=state.client,
        on_status=on_status,
        on_log=on_log,
        on_progress=on_progress,
        on_install_progress=on_install_progress,
        auto_unattended=req.unattended,
        game_key=BUILD_GAME.get(req.build_key, ""),
    )
    state.pipeline.start()
    hub.publish({"type": "pipeline", "event": "started",
                 "build_key": req.build_key, "total": len(mods)})

    # Notify completion on a watcher thread.
    def _watch(pl: Pipeline) -> None:
        pl._thread.join() if pl._thread else None
        done = sum(1 for pm in pl.mods if pm.status == ModStatus.DONE)
        errors = sum(1 for pm in pl.mods if pm.status == ModStatus.ERROR)
        hub.publish({"type": "pipeline", "event": "finished",
                     "done": done, "errors": errors, "total": len(pl.mods)})

    threading.Thread(target=_watch, args=(state.pipeline,), daemon=True).start()
    return {"ok": True, "total": len(mods), "game_path": str(game_path)}


@app.post("/api/install/{action}")
def install_control(action: str) -> dict:
    pl = state.pipeline
    if not pl:
        return JSONResponse(status_code=400, content={"ok": False, "error": "No pipeline"})
    if action == "pause":
        pl.pause()
    elif action == "resume":
        pl.resume()
    elif action == "stop":
        pl.stop()
    elif action == "retry":
        pl.retry_failed()
    else:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Unknown action"})
    return {"ok": True, "action": action}


@app.get("/api/install/state")
def install_state() -> dict:
    pl = state.pipeline
    if not pl:
        return {"running": False, "mods": []}
    return {
        "running": pl.is_running,
        "mods": [pipeline_mod_to_dict(pm) for pm in pl.mods],
    }


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await state.hub.connect(ws)
    try:
        # Send a hello + current status snapshot on connect.
        await ws.send_json({"type": "hello", "version": __version__})
        while True:
            await ws.receive_text()   # keep the connection open; ignore inbound
    except WebSocketDisconnect:
        state.hub.disconnect(ws)
    except Exception:
        state.hub.disconnect(ws)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8756)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
