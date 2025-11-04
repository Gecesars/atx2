from __future__ import annotations

import json

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
    flash,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from app_core.models import Project, Asset, CoverageJob, Report, DatasetSource
from app_core.storage import ensure_storage_structure, remove_project_storage, storage_root
from app_core.utils import (
    ensure_unique_slug,
    project_by_slug_or_404,
    project_to_dict,
    projects_to_dict,
    slugify,
)


bp = Blueprint("projects", __name__, url_prefix="/projects")
api_bp = Blueprint("projects_api", __name__, url_prefix="/api/projects")


# ---------------------------------------------------------------------------#
# UI routes                                                                  #
# ---------------------------------------------------------------------------#


@bp.route("/", methods=["GET"])
@login_required
def list_projects():
    projects = (
        current_user.projects.order_by(Project.created_at.desc()).all()
        if hasattr(current_user, "projects")
        else []
    )
    return render_template("projects/index.html", projects=projects)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_project():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None
        crs = request.form.get("crs", "EPSG:4326").strip() or "EPSG:4326"
        aoi_raw = request.form.get("aoi_geojson", "").strip()
        aoi_geojson = None

        if not name:
            error = "Informe um nome para o projeto."
        else:
            if aoi_raw:
                try:
                    aoi_geojson = json.loads(aoi_raw)
                except json.JSONDecodeError:
                    error = "GeoJSON inválido. Corrija o conteúdo informado."

        if error is None:
            slug_candidate = slugify(name)
            slug = ensure_unique_slug(current_user.uuid, slug_candidate)
            project = Project(
                user_uuid=current_user.uuid,
                name=name,
                slug=slug,
                description=description,
                aoi_geojson=aoi_geojson,
                crs=crs,
            )
            db.session.add(project)
            try:
                db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                error = f"Erro ao criar projeto: {exc}"
            else:
                ensure_storage_structure(str(current_user.uuid), slug)
                flash("Projeto criado com sucesso!", "success")
                return redirect(url_for("projects.view_project", slug=slug))

    return render_template("projects/new.html", error=error)


@bp.route("/<slug>", methods=["GET"])
@login_required
def view_project(slug):
    project = project_by_slug_or_404(slug, current_user.uuid)
    assets = project.assets
    jobs = project.coverage_jobs
    reports = project.reports
    dataset_sources = project.dataset_sources
    return render_template(
        "projects/detail.html",
        project=project,
        assets=assets,
        jobs=jobs,
        reports=reports,
        dataset_sources=dataset_sources,
    )


@bp.route("/<slug>/assets/<asset_id>/preview", methods=["GET"])
@login_required
def asset_preview(slug, asset_id):
    project = project_by_slug_or_404(slug, current_user.uuid)
    asset = Asset.query.filter_by(id=asset_id, project_id=project.id).first()
    if asset is None:
        abort(404)
    file_path = storage_root() / asset.path
    if not file_path.exists():
        abort(404)
    return send_file(file_path, mimetype=asset.mime_type or 'application/octet-stream')


@bp.route("/<slug>/coverage", methods=["GET"])
@login_required
def project_coverage_redirect(slug):
    project_by_slug_or_404(slug, current_user.uuid)
    return redirect(url_for("ui.calcular_cobertura", project=slug))


@bp.route("/<slug>/update", methods=["POST"])
@login_required
def update_project(slug):
    project = project_by_slug_or_404(slug, current_user.uuid)
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    crs = request.form.get("crs", "").strip() or project.crs
    aoi_raw = request.form.get("aoi_geojson", "").strip()

    if name:
        if name != project.name:
            candidate = slugify(name)
            if candidate != project.slug:
                project.slug = ensure_unique_slug(project.user_uuid, candidate)
        project.name = name
    project.description = description
    project.crs = crs
    if aoi_raw:
        try:
            project.aoi_geojson = json.loads(aoi_raw)
        except json.JSONDecodeError:
            flash("GeoJSON inválido. Mantendo valor anterior.", "warning")
    else:
        project.aoi_geojson = None

    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        flash(f"Erro ao atualizar projeto: {exc}", "error")
    else:
        ensure_storage_structure(str(project.user_uuid), project.slug)
        flash("Projeto atualizado com sucesso!", "success")
    return redirect(url_for("projects.view_project", slug=project.slug))


@bp.route("/<slug>/delete", methods=["POST"])
@login_required
def delete_project(slug):
    project = project_by_slug_or_404(slug, current_user.uuid)
    remove_project_storage(str(project.user_uuid), project.slug)
    db.session.delete(project)
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        flash(f"Erro ao remover projeto: {exc}", "error")
        return redirect(url_for("projects.view_project", slug=slug))
    flash("Projeto removido.", "success")
    return redirect(url_for("projects.list_projects"))


# ---------------------------------------------------------------------------#
# API routes                                                                 #
# ---------------------------------------------------------------------------#


@api_bp.route("/", methods=["GET"])
@login_required
def api_list_projects():
    projects = (
        current_user.projects.order_by(Project.created_at.desc()).all()
        if hasattr(current_user, "projects")
        else []
    )
    return jsonify({"projects": projects_to_dict(projects)})


@api_bp.route("/", methods=["POST"])
@login_required
def api_create_project():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Campo 'name' é obrigatório."}), 400

    description = (payload.get("description") or "").strip() or None
    crs = (payload.get("crs") or "EPSG:4326").strip() or "EPSG:4326"
    aoi_geojson = payload.get("aoi_geojson")

    slug_candidate = slugify(name)
    slug = ensure_unique_slug(current_user.uuid, slug_candidate)

    project = Project(
        user_uuid=current_user.uuid,
        name=name,
        slug=slug,
        description=description,
        aoi_geojson=aoi_geojson,
        crs=crs,
    )
    db.session.add(project)
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        return jsonify({"error": f"Não foi possível criar o projeto: {exc}"}), 500

    ensure_storage_structure(str(current_user.uuid), slug)
    response = jsonify({"project": project_to_dict(project)})
    response.status_code = 201
    response.headers["Location"] = url_for("projects_api.api_get_project", slug=slug)
    return response


def _asset_to_dict(asset: Asset) -> dict:
    return {
        "id": str(asset.id),
        "type": asset.type.value if asset.type else None,
        "path": asset.path,
        "mime_type": asset.mime_type,
        "byte_size": asset.byte_size,
        "checksum_sha256": asset.checksum_sha256,
        "meta": asset.meta,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


def _job_to_dict(job: CoverageJob) -> dict:
    return {
        "id": str(job.id),
        "engine": job.engine.value if job.engine else None,
        "status": job.status.value if job.status else None,
        "inputs": job.inputs,
        "metrics": job.metrics,
        "outputs_asset_id": str(job.outputs_asset_id) if job.outputs_asset_id else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def _report_to_dict(report: Report) -> dict:
    return {
        "id": str(report.id),
        "title": report.title,
        "description": report.description,
        "template_name": report.template_name,
        "json_payload": report.json_payload,
        "pdf_asset_id": str(report.pdf_asset_id) if report.pdf_asset_id else None,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


def _dataset_source_to_dict(dataset: DatasetSource) -> dict:
    return {
        "id": str(dataset.id),
        "kind": dataset.kind.value if dataset.kind else None,
        "locator": dataset.locator,
        "time_range": dataset.time_range,
        "notes": dataset.notes,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
    }


@api_bp.route("/<slug>", methods=["GET"])
@login_required
def api_get_project(slug):
    project = project_by_slug_or_404(slug, current_user.uuid)
    data = project_to_dict(project)
    data["assets"] = [_asset_to_dict(asset) for asset in project.assets]
    data["coverage_jobs"] = [_job_to_dict(job) for job in project.coverage_jobs]
    data["reports"] = [_report_to_dict(report) for report in project.reports]
    data["dataset_sources"] = [
        _dataset_source_to_dict(ds) for ds in project.dataset_sources
    ]
    return jsonify({"project": data})


@api_bp.route("/<slug>", methods=["PATCH"])
@login_required
def api_update_project(slug):
    project = project_by_slug_or_404(slug, current_user.uuid)
    payload = request.get_json(silent=True) or {}

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Campo 'name' não pode ser vazio."}), 400
        if name != project.name:
            candidate = slugify(name)
            if candidate != project.slug:
                project.slug = ensure_unique_slug(project.user_uuid, candidate)
        project.name = name

    if "description" in payload:
        project.description = (payload.get("description") or "").strip() or None

    if "crs" in payload:
        project.crs = (payload.get("crs") or project.crs).strip() or project.crs

    if "aoi_geojson" in payload:
        project.aoi_geojson = payload.get("aoi_geojson")

    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        return jsonify({"error": f"Não foi possível atualizar o projeto: {exc}"}), 500

    ensure_storage_structure(str(project.user_uuid), project.slug)
    return jsonify({"project": project_to_dict(project)})


@api_bp.route("/<slug>", methods=["DELETE"])
@login_required
def api_delete_project(slug):
    project = project_by_slug_or_404(slug, current_user.uuid)
    remove_project_storage(str(project.user_uuid), project.slug)
    db.session.delete(project)
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        return jsonify({"error": f"Não foi possível remover o projeto: {exc}"}), 500
    return jsonify({"status": "deleted"})
