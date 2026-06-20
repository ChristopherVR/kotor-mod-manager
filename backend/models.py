"""Pydantic request/response models and serialization helpers for the API."""

from typing import Optional

from pydantic import BaseModel

from installer.pipeline import PipelineMod
from scraper.build_scraper import BuildMod


class LoginRequest(BaseModel):
    username: str
    password: str
    save: bool = True


class SettingsModel(BaseModel):
    kotor1_path: str = ""
    kotor2_path: str = ""
    download_dir: str = ""


class StartInstallRequest(BaseModel):
    build_key: str
    unattended: bool = False
    game_path: Optional[str] = None   # override; otherwise resolved from settings


def build_mod_to_dict(m: BuildMod) -> dict:
    return {
        "install_order": m.install_order,
        "file_id": m.file_id,
        "slug": m.slug,
        "name": m.name,
        "url": m.url,
        "game": m.game,
        "section": m.section,
        "category": m.category,
        "note": m.note,
        "option_hint": m.option_hint,
        "install_method_hint": m.install_method_hint,
        "build_key": m.build_key,
    }


def pipeline_mod_to_dict(pm: PipelineMod) -> dict:
    return {
        "file_id": pm.build_mod.file_id,
        "name": pm.build_mod.name,
        "install_order": pm.build_mod.install_order,
        "status": pm.status.name,
        "status_label": pm.status.value,
        "error": pm.error,
        "strategy_used": pm.strategy_used,
        "download_progress": pm.download_progress,
        "download_kb": pm.download_kb,
        "download_total_kb": pm.download_total_kb,
    }
