import enum
import uuid
from datetime import datetime

from sqlalchemy import event
from sqlalchemy.orm import validates

from extensions import db
from app_core.db_types import GUID


class TimestampMixin:
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=db.func.now(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=db.func.now(),
    )


class AssetType(enum.Enum):
    dem = "dem"
    lulc = "lulc"
    building_footprints = "building_footprints"
    mesh3d = "mesh3d"
    heatmap = "heatmap"
    pdf = "pdf"
    csv = "csv"
    png = "png"
    json = "json"
    other = "other"


class CoverageEngine(enum.Enum):
    p1546 = "p1546"
    itm = "itm"
    pycraf = "pycraf"
    rt3d = "rt3d"


class CoverageStatus(enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


class DatasetSourceKind(enum.Enum):
    SRTM = "SRTM"
    TOPODATA = "TOPODATA"
    CGLS_LC100 = "CGLS_LC100"
    MAPBIOMAS = "MAPBIOMAS"
    OSM = "OSM"
    CADASTRE = "CADASTRE"
    GEE = "GEE"
    CUSTOM = "CUSTOM"


class Project(TimestampMixin, db.Model):
    __tablename__ = "projects"
    __table_args__ = (
        db.UniqueConstraint("user_uuid", "slug", name="uq_projects_user_slug"),
    )

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_uuid = db.Column(
        GUID(),
        db.ForeignKey("users.uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text(), nullable=True)
    aoi_geojson = db.Column(db.JSON, nullable=True)
    crs = db.Column(db.String(32), nullable=False, default="EPSG:4326")
    settings = db.Column(db.JSON, nullable=True)

    user = db.relationship("User", back_populates="projects")
    assets = db.relationship(
        "Asset", back_populates="project", cascade="all, delete-orphan"
    )
    coverage_jobs = db.relationship(
        "CoverageJob", back_populates="project", cascade="all, delete-orphan"
    )
    reports = db.relationship(
        "Report", back_populates="project", cascade="all, delete-orphan"
    )
    dataset_sources = db.relationship(
        "DatasetSource", back_populates="project", cascade="all, delete-orphan"
    )

    @validates("slug")
    def _normalize_slug(self, key, value):
        return (value or "").strip().lower()


class Asset(TimestampMixin, db.Model):
    __tablename__ = "assets"

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id = db.Column(
        GUID(),
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = db.Column(db.Enum(AssetType, name="asset_type"), nullable=False)
    path = db.Column(db.String(512), nullable=False)
    mime_type = db.Column(db.String(128), nullable=True)
    byte_size = db.Column(db.BigInteger, nullable=True)
    checksum_sha256 = db.Column(db.String(64), nullable=True)
    meta = db.Column(db.JSON, nullable=True)

    project = db.relationship("Project", back_populates="assets")
    coverage_jobs = db.relationship(
        "CoverageJob",
        back_populates="output_asset",
        cascade="all",
        passive_deletes=True,
        lazy="dynamic",
    )


class CoverageJob(TimestampMixin, db.Model):
    __tablename__ = "coverage_jobs"

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id = db.Column(
        GUID(),
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(
        db.Enum(CoverageStatus, name="coverage_job_status"),
        nullable=False,
        default=CoverageStatus.queued,
        server_default=CoverageStatus.queued.value,
    )
    engine = db.Column(
        db.Enum(CoverageEngine, name="coverage_engine"), nullable=False
    )
    inputs = db.Column(db.JSON, nullable=False)
    metrics = db.Column(db.JSON, nullable=True)
    outputs_asset_id = db.Column(
        GUID(),
        db.ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)

    project = db.relationship("Project", back_populates="coverage_jobs")
    output_asset = db.relationship("Asset", back_populates="coverage_jobs", foreign_keys=[outputs_asset_id])


class Report(TimestampMixin, db.Model):
    __tablename__ = "reports"

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id = db.Column(
        GUID(),
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text(), nullable=True)
    template_name = db.Column(db.String(255), nullable=False)
    json_payload = db.Column(db.JSON, nullable=False)
    pdf_asset_id = db.Column(
        GUID(),
        db.ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    project = db.relationship("Project", back_populates="reports")
    pdf_asset = db.relationship("Asset", foreign_keys=[pdf_asset_id])


class DatasetSource(TimestampMixin, db.Model):
    __tablename__ = "dataset_sources"

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id = db.Column(
        GUID(),
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = db.Column(
        db.Enum(DatasetSourceKind, name="dataset_source_kind"), nullable=False
    )
    locator = db.Column(db.JSON, nullable=True)
    time_range = db.Column(db.String(64), nullable=True)
    notes = db.Column(db.Text(), nullable=True)

    project = db.relationship("Project", back_populates="dataset_sources")


@event.listens_for(Project, "before_insert", propagate=True)
def _set_project_slug(mapper, connection, target):
    if not target.slug:
        base_slug = (target.name or "project").strip().lower().replace(" ", "-")
        target.slug = base_slug[:255]
