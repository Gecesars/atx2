from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable

from flask import current_app


def storage_root() -> Path:
    root = current_app.config.get("STORAGE_ROOT")
    if not root:
        raise RuntimeError("STORAGE_ROOT not configured")
    return Path(root)


def project_storage_path(user_uuid: str, project_slug: str) -> Path:
    base = storage_root() / str(user_uuid) / project_slug
    base.mkdir(parents=True, exist_ok=True)
    return base


def ensure_storage_structure(user_uuid: str, project_slug: str) -> dict[str, Path]:
    base = project_storage_path(user_uuid, project_slug)
    subfolders = {
        "assets": [
            "dem",
            "lulc",
            "buildings",
            "mesh3d",
            "coverage",
            "reports",
        ]
    }
    created = {}
    for parent, children in subfolders.items():
        parent_path = base / parent
        parent_path.mkdir(parents=True, exist_ok=True)
        created[parent] = parent_path
        for child in children:
            child_path = parent_path / child
            child_path.mkdir(parents=True, exist_ok=True)
            created[f"{parent}/{child}"] = child_path
    return created


def remove_project_storage(user_uuid: str, project_slug: str) -> None:
    path = storage_root() / str(user_uuid) / project_slug
    if path.exists():
        shutil.rmtree(path)


def iter_user_projects(user_uuid: str) -> Iterable[Path]:
    user_dir = storage_root() / str(user_uuid)
    if not user_dir.exists():
        return []
    return [p for p in user_dir.iterdir() if p.is_dir()]
