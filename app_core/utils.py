import re
import unicodedata
import uuid
from typing import Iterable, Optional

from flask import abort
from flask_login import current_user

from extensions import db
from app_core.models import Project


def slugify(value: str) -> str:
    if not value:
        return ""
    value = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    value = re.sub(r"[-\s]+", "-", value)
    return value or f"project-{uuid.uuid4().hex[:8]}"


def ensure_unique_slug(user_uuid, candidate: str) -> str:
    base = candidate or f"project-{uuid.uuid4().hex[:8]}"
    slug = base
    suffix = 2
    while (
        Project.query.filter_by(user_uuid=user_uuid, slug=slug).first()
        is not None
    ):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def project_by_slug_or_404(slug: str, user_uuid=None) -> Project:
    user_id = user_uuid or getattr(current_user, "uuid", None)
    if not user_id:
        abort(403)
    project = Project.query.filter_by(user_uuid=user_id, slug=slug).first()
    if project is None:
        abort(404)
    return project


def projects_to_dict(projects: Iterable[Project]) -> list[dict]:
    return [project_to_dict(project) for project in projects]


def project_to_dict(project: Project) -> dict:
    return {
        "id": str(project.id),
        "user_uuid": str(project.user_uuid),
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "aoi_geojson": project.aoi_geojson,
        "crs": project.crs,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "settings": project.settings or {},
    }


def touched(instance):
    """Mark SQLAlchemy instance as dirty (useful for updates)."""
    db.session.add(instance)
    return instance
