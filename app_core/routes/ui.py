import base64
import io
import json
import math
import os
import re
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt, degrees

import astropy
import geojson
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pycraf
import requests
from sklearn.linear_model import LinearRegression
from PIL import Image
from astropy import units as u
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.colors import LinearSegmentedColormap, ListedColormap, Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.table import Table
from datetime import datetime, timedelta
from pycraf import pathprof, antenna, conversions as cnv
from pycraf.pathprof import SrtmConf
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from scipy.constants import c
from scipy.integrate import simpson
from scipy.interpolate import interp1d, CubicSpline
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import Point, Polygon
from geopy.distance import geodesic
from geopy.point import Point
from types import SimpleNamespace
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from user import User
from app_core.models import (
    Project,
    Asset,
    AssetType,
    CoverageEngine,
    CoverageJob,
    CoverageStatus,
)
from app_core.email_utils import generate_token, load_token, send_email
from app_core.storage import ensure_storage_structure, storage_root
from app_core.utils import (
    ensure_unique_slug,
    project_by_slug_or_404,
    project_to_dict,
    projects_to_dict,
    slugify,
)

matplotlib.use('Agg')

bp = Blueprint('ui', __name__)


# === Helper utilities ======================================================


def _create_default_project(user: User) -> Project:
    base_label = user.username or (user.email.split('@')[0] if user.email else 'projeto-atx')
    slug_candidate = slugify(base_label)
    slug = ensure_unique_slug(user.uuid, slug_candidate)
    project = Project(
        user_uuid=user.uuid,
        name=f"Projeto de {base_label}",
        slug=slug,
        description="Projeto padrão criado automaticamente.",
    )
    db.session.add(project)
    db.session.flush()
    ensure_storage_structure(str(user.uuid), project.slug)
    return project


# ==========================================================================
# =========================
# Helpers para parsing/validação
# =========================

def _is_db_values(vals):
    vals = np.asarray(vals, dtype=float)
    if vals.size == 0:
        return False
    if np.nanmin(vals) < -0.5:  # valores negativos plausíveis em dB
        return True
    return np.nanmax(vals) > 20  # acima de 20 em "campo" é improvável

def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return np.nan

def _mirror_vertical_if_needed(angles_deg, values):
    """
    Recebe listas possivelmente só com 0..-90 (ou 0..+90) e devolve pares
    cobrindo -90..+90 por simetria em torno de 0°.
    """
    a = np.asarray(angles_deg, dtype=float)
    v = np.asarray(values,     dtype=float)

    # Remove NaN e ordena
    m = np.isfinite(a) & np.isfinite(v)
    a, v = a[m], v[m]
    if a.size == 0:
        return np.array([-90.0,  0.0, 90.0]), np.array([0.0, 1.0, 0.0])

    order = np.argsort(a)
    a, v = a[order], v[order]

    has_neg = np.any(a < 0)
    has_pos = np.any(a > 0)

    if not has_neg and has_pos:
        # só 0..+90: espelha para o lado negativo
        a_neg = -a[a >= 0]
        v_neg =  v[a >= 0]
        a_all = np.concatenate([a_neg, a])
        v_all = np.concatenate([v_neg, v])
        order = np.argsort(a_all)
        return a_all[order], v_all[order]

    if has_neg and not has_pos:
        # só -90..0: espelha para + lado
        a_pos = -a[a <= 0]
        v_pos =  v[a <= 0]
        a_all = np.concatenate([a, a_pos])
        v_all = np.concatenate([v, v_pos])
        order = np.argsort(a_all)
        return a_all[order], v_all[order]

    return a, v  # já tem dos dois lados

def parse_pat(text):
    """
    Saída:
      horiz_lin: (360,)  E/Emax linear (0..1), azimutes 0..359
      vert_lin:  (181,)  E/Emax linear (0..1), ângulos -90..+90 (passo 1°)
      meta: dict
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    meta = {}

    # Cabeçalho opcional
    header_re = re.compile(r"^['\"]?(.*?)[\"']?\s*,\s*([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)$")
    if lines and (lines[0].startswith("'") or lines[0][0].isalpha()):
        m = header_re.match(lines[0])
        if m:
            meta['title']  = m.group(1).strip()
            meta['param1'] = _safe_float(m.group(2))
            meta['param2'] = _safe_float(m.group(3))
        lines = lines[1:]

    # Horizontal até '999'
    horiz_map = {}
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln == '999':
            i += 1
            break
        parts = [p.strip() for p in ln.split(',')]
        if parts and re.fullmatch(r"[-+]?\d+", parts[0] or ""):
            az = int(parts[0]) % 360
            val = _safe_float(parts[1]) if len(parts) >= 2 and parts[1] != '' else np.nan
            horiz_map[az] = val
        i += 1

    # Vertical: pares (ângulo, valor) livres
    v_angles, v_vals = [], []
    while i < len(lines):
        ln = lines[i]
        parts = [p.strip() for p in ln.split(',')]
        if len(parts) >= 2 and parts[0] and parts[1]:
            a0 = _safe_float(parts[0]); v0 = _safe_float(parts[1])
            if np.isfinite(a0) and np.isfinite(v0) and -360 <= a0 <= 360:
                v_angles.append(a0); v_vals.append(v0)
        i += 1

    # --- Horizontal: vetor 0..359, preenchimento + normalização para E/Emax ---
    horiz_vals = np.full(360, np.nan, float)
    for az, val in horiz_map.items():
        horiz_vals[az] = val

    if np.isnan(horiz_vals).any():
        # forward/backward fill + média
        last = np.nan
        for k in range(360):
            if np.isfinite(horiz_vals[k]): last = horiz_vals[k]
            else:                          horiz_vals[k] = last
        last = np.nan
        for k in range(359, -1, -1):
            if np.isfinite(horiz_vals[k]): last = horiz_vals[k]
            else:                          horiz_vals[k] = last
        if np.isnan(horiz_vals).any():
            mean_val = np.nanmean(horiz_vals)
            horiz_vals[np.isnan(horiz_vals)] = 0.0 if np.isnan(mean_val) else mean_val

    horiz_lin = 10**(horiz_vals/20.0) if _is_db_values(horiz_vals) else horiz_vals.astype(float)
    max_h = np.nanmax(horiz_lin) if np.isfinite(horiz_lin).any() else 1.0
    horiz_lin = np.clip(horiz_lin/max_h, 0.0, 1.0)

    # --- Vertical: reconstrução simétrica e interp. para -90..+90 ---
    if len(v_angles) == 0:
        # fallback "gaussiano"
        target = np.arange(-90, 91, 1.0)
        vert_lin = np.exp(-0.5 * (target/15.0)**2)
        vert_lin /= vert_lin.max()
        return horiz_lin.astype(float), vert_lin.astype(float), meta

    v_angles = np.asarray(v_angles, float)
    v_vals   = np.asarray(v_vals,   float)
    # Some .pat variants include a metadata/count line like "1, 91" before the real pairs.
    # If we detect unusually large values (>>1) mixed with normal 0..1 samples, drop those metadata entries.
    try:
        if np.any(v_vals > 10) and np.nanmax(v_vals[np.where(v_vals <= 10)]) <= 2:
            # remove entries with implausibly large values
            mask_valid = v_vals <= 10
            v_angles = v_angles[mask_valid]
            v_vals = v_vals[mask_valid]
            try:
                current_app.logger.debug(f"parse_pat: removed metadata vertical entries, kept {len(v_vals)} samples")
            except Exception:
                pass
    except Exception:
        pass
    v_angles, v_vals = _mirror_vertical_if_needed(v_angles, v_vals)

    # passa p/ E/Emax linear
    v_vals_lin = 10**(v_vals/20.0) if _is_db_values(v_vals) else v_vals.astype(float)

    # normaliza por pico
    vmax = np.nanmax(v_vals_lin) if np.isfinite(v_vals_lin).any() else 1.0
    v_vals_lin = np.clip(v_vals_lin / vmax, 0.0, 1.0)

    # garante cobertura de -90 e +90
    if v_angles[0] > -90:
        # If the vertical samples don't reach -90, pad with 0 at the edge
        v_angles   = np.insert(v_angles,  0, -90.0)
        v_vals_lin = np.insert(v_vals_lin, 0, 0.0)
    if v_angles[-1] < 90:
        # If the vertical samples don't reach +90, pad with 0 at the edge
        v_angles   = np.append(v_angles,  90.0)
        v_vals_lin = np.append(v_vals_lin, 0.0)

    target = np.arange(-90.0, 91.0, 1.0, dtype=float)
    vert_lin = np.interp(target, v_angles, v_vals_lin)

    # Debug: log vertical parsing details
    try:
        from flask import current_app
        current_app.logger.debug(f"parse_pat: v_angles_in={v_angles.tolist() if hasattr(v_angles,'tolist') else v_angles}, v_vals_in_sample={v_vals[:10].tolist() if hasattr(v_vals,'tolist') else v_vals}")
        current_app.logger.debug(f"parse_pat: v_vals_lin_sample={v_vals_lin[:10].tolist() if hasattr(v_vals_lin,'tolist') else v_vals_lin}, vert_lin_len={len(vert_lin)}")
        current_app.logger.debug(f"parse_pat: is_db_values={_is_db_values(v_vals)}")
    except Exception:
        pass

    return horiz_lin.astype(float), vert_lin.astype(float), meta

# =========================
# Funções Auxiliares
# =========================

def salvar_diagrama_usuario(user, file, direction, tilt):
    """Função auxiliar para salvar diagrama no usuário"""
    try:
        file_content = file.read()
        user.antenna_pattern = file_content
        user.antenna_direction = direction
        user.antenna_tilt = tilt
        db.session.commit()
        return True, "Diagrama salvo com sucesso"
    except Exception as e:
        db.session.rollback()
        return False, f"Erro ao salvar: {str(e)}"

# =========================
# Correção para Curvatura da Terra
# =========================

def earth_curvature_correction(distance_km, height_above_ground=0):
    """
    Calcula a correção da curvatura da Terra para uma dada distância.
    
    Parâmetros:
    - distance_km: distância em quilômetros
    - height_above_ground: altura acima do solo em metros
    
    Retorna:
    - drop: queda devido à curvatura em metros
    """
    # Raio da Terra em metros
    R = 6371000  # metros
    
    # Para distâncias maiores, usar fórmula mais precisa
    if distance_km > 10:
        drop = (distance_km * 1000) ** 2 / (8 * R)
    else:
        # Ângulo central em radianos
        theta = distance_km * 1000 / R
        # Queda devido à curvatura (metros)
        drop = R * (1 - np.cos(theta/2))
    
    return drop

def adjust_heights_for_curvature(distances, heights, h_tg, h_rg):
    """
    Ajusta as alturas considerando a curvatura da Terra.
    
    Parâmetros:
    - distances: array de distâncias do TX em metros
    - heights: array de alturas do terreno em metros
    - h_tg: altura da antena TX em metros
    - h_rg: altura da antena RX em metros
    
    Retorna:
    - adjusted_heights: alturas ajustadas considerando curvatura
    """
    distances_km = distances / 1000.0
    adjusted_heights = heights.copy()
    
    # Ajustar para cada ponto ao longo do perfil
    for i, dist_km in enumerate(distances_km):
        if i == 0:
            # Ponto do transmissor
            adjusted_heights[i] += h_tg
        elif i == len(distances_km) - 1:
            # Ponto do receptor
            adjusted_heights[i] += h_rg
        else:
            # Pontos intermediários - calcular queda da curvatura
            drop = earth_curvature_correction(dist_km)
            adjusted_heights[i] -= drop
    
    return adjusted_heights

def calculate_effective_earth_radius(k_factor=4/3):
    """
    Calcula o raio efetivo da Terra considerando refração atmosférica.
    
    Parâmetros:
    - k_factor: fator de refração (padrão 4/3 para condições normais)
    
    Retorna:
    - Raio efetivo em metros
    """
    R_earth = 6371000  # Raio real da Terra em metros
    return k_factor * R_earth


def get_google_maps_key():
    return current_app.config.get('GOOGLE_MAPS_API_KEY')


def get_solid_png_dir():
    return current_app.config['SOLID_PNG_ROOT']

def _coerce_float(value):
    """
    Converte value para float ou retorna None.
    Aceita "", None, "   ", etc.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        v = value.strip()
        if v == "":
            return None
        try:
            return float(v)
        except ValueError:
            return None
    # qualquer outro tipo inesperado
    return None


def _coerce_str(value):
    """
    Aceita string, número, None.
    Normaliza "" -> None, senão retorna string.
    """
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v if v != "" else None
    # ex. número (frequency às vezes mandam como 105.7 mas você quer string? não, mas p/ campos textuais)
    return str(value)


def _coerce_optional(value):
    """
    Converte valores opcionais para float, retornando None caso vazio ou inválido.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value_str = str(value).strip()
    if not value_str:
        return None
    try:
        return float(value_str)
    except ValueError:
        return None


def _normalize_direction_value(value, default=None):
    try:
        ang = float(value)
    except (TypeError, ValueError):
        if default is None:
            return None
        ang = float(default)
    ang = ang % 360.0
    if ang < 0:
        ang += 360.0
    return float(ang)


def _prepare_tx_object(base_tx, overrides=None, pattern_bytes=None):
    """
    Constroi um objeto compatível com User para cálculos de cobertura.
    """
    overrides = overrides or {}
    attrs = {
        'propagation_model': getattr(base_tx, 'propagation_model', None),
        'frequencia': getattr(base_tx, 'frequencia', None),
        'tower_height': getattr(base_tx, 'tower_height', None),
        'rx_height': getattr(base_tx, 'rx_height', None),
        'total_loss': getattr(base_tx, 'total_loss', None),
        'transmission_power': getattr(base_tx, 'transmission_power', None),
        'antenna_gain': getattr(base_tx, 'antenna_gain', None),
        'rx_gain': getattr(base_tx, 'rx_gain', None),
        'antenna_direction': getattr(base_tx, 'antenna_direction', None),
        'antenna_tilt': getattr(base_tx, 'antenna_tilt', None),
        'latitude': getattr(base_tx, 'latitude', None),
        'longitude': getattr(base_tx, 'longitude', None),
        'servico': getattr(base_tx, 'servico', None),
        'time_percentage': getattr(base_tx, 'time_percentage', None),
        'polarization': getattr(base_tx, 'polarization', None),
        'p452_version': getattr(base_tx, 'p452_version', None),
        'temperature_k': getattr(base_tx, 'temperature_k', None),
        'pressure_hpa': getattr(base_tx, 'pressure_hpa', None),
        'water_density': getattr(base_tx, 'water_density', None),
        'tx_location_name': getattr(base_tx, 'tx_location_name', None),
        'tx_site_elevation': getattr(base_tx, 'tx_site_elevation', None),
        'climate_lat': getattr(base_tx, 'climate_lat', None),
        'climate_lon': getattr(base_tx, 'climate_lon', None),
        'climate_updated_at': getattr(base_tx, 'climate_updated_at', None),
        'antenna_pattern': getattr(base_tx, 'antenna_pattern', pattern_bytes),
    }
    attrs.update(overrides or {})
    return SimpleNamespace(**attrs)


@bp.route("/salvar-dados", methods=["POST"])
@login_required
def salvar_dados():
    data = request.get_json(silent=True) or {}
    project_slug = request.args.get('project') or data.get('projectSlug')
    project = None
    if project_slug:
        project = project_by_slug_or_404(project_slug, current_user.uuid)

    coverage_engine = data.get('coverageEngine') or CoverageEngine.p1546.value
    valid_engines = {engine.value for engine in CoverageEngine}
    if coverage_engine not in valid_engines:
        coverage_engine = CoverageEngine.p1546.value

    # 1. Extrair cada campo do payload sem assumir que existe
    #    Se não existir, não sobrescreve o valor atual.
    #    Se existir mas vier vazio, salva como None.

    simple_float_fields = {
        "towerHeight": "tower_height",
        "rxHeight": "rx_height",
        "Total_loss": "total_loss",
        "antennaGain": "antenna_gain",
        "rxGain": "rx_gain",
        "transmissionPower": "transmission_power",
        "frequency": "frequencia",
        "antennaTilt": "antenna_tilt",
        "latitude": "latitude",
        "longitude": "longitude",
        "waterDensity": "water_density",
    }

    for incoming_key, model_attr in simple_float_fields.items():
        if incoming_key in data:
            value = _coerce_float(data.get(incoming_key))
            if value is not None:
                setattr(current_user, model_attr, value)

    # tempo percentual (0.001 a 50%)
    if "timePercentage" in data:
        time_pct_val = _coerce_float(data.get("timePercentage"))
        if time_pct_val is not None:
            current_user.time_percentage = max(0.001, min(time_pct_val, 50.0))

    # temperatura (°C -> K)
    if "temperature" in data:
        temp_c = _coerce_float(data.get("temperature"))
        if temp_c is not None:
            current_user.temperature_k = temp_c + 273.15

    # pressão (hPa)
    if "pressure" in data:
        pressure_val = _coerce_float(data.get("pressure"))
        if pressure_val is not None:
            current_user.pressure_hpa = pressure_val

    # azimute (0..359°)
    if "antennaDirection" in data:
        direction_raw = data.get("antennaDirection")
        if direction_raw is None or str(direction_raw).strip() == "":
            current_user.antenna_direction = None
        else:
            # usar a versão unificada do helper que pode retornar None
            current_user.antenna_direction = _normalize_direction_value(direction_raw)

    # campos textuais / categóricos
    if "propagationModel" in data:
        current_user.propagation_model = _coerce_str(data.get("propagationModel"))

    if "serviceType" in data:
        current_user.servico = _coerce_str(data.get("serviceType"))
    elif "service" in data:
        current_user.servico = _coerce_str(data.get("service"))

    if "polarization" in data:
        pol_val = _coerce_str(data.get("polarization"))
        if pol_val:
            current_user.polarization = pol_val.lower()

    if "p452Version" in data:
        version_val = data.get("p452Version")
        try:
            version_val = int(version_val)
        except (TypeError, ValueError):
            version_val = current_user.p452_version or 16
        if version_val not in (14, 16):
            version_val = 16
        current_user.p452_version = version_val

    # 4. Persistir configurações no projeto (snapshot)
    project_settings_payload = {}
    temperature_c = (current_user.temperature_k - 273.15) if current_user.temperature_k is not None else None
    if project:
        project_settings_payload = {
            "propagationModel": current_user.propagation_model,
            "Total_loss": current_user.total_loss,
            "antennaGain": current_user.antenna_gain,
            "rxGain": current_user.rx_gain,
            "transmissionPower": current_user.transmission_power,
            "frequency": current_user.frequencia,
            "towerHeight": current_user.tower_height,
            "rxHeight": current_user.rx_height,
            "antennaTilt": getattr(current_user, "antenna_tilt", None),
            "antennaDirection": getattr(current_user, "antenna_direction", None),
            "timePercentage": current_user.time_percentage,
            "temperature": temperature_c,
            "pressure": current_user.pressure_hpa,
            "waterDensity": current_user.water_density,
            "serviceType": current_user.servico,
            "polarization": current_user.polarization,
            "p452Version": current_user.p452_version,
            "latitude": current_user.latitude,
            "longitude": current_user.longitude,
            "coverageEngine": coverage_engine,
            "radius": _coerce_float(data.get('radius')) if 'radius' in data else None,
            "minSignalLevel": _coerce_float(data.get('minSignalLevel')),
            "maxSignalLevel": _coerce_float(data.get('maxSignalLevel')),
        }
        existing_settings = project.settings or {}
        existing_settings.update({k: v for k, v in project_settings_payload.items() if v is not None})
        existing_settings["lastSavedAt"] = datetime.utcnow().isoformat()
        project.settings = existing_settings

    # 5. Commit no banco
    try:
        db.session.add(current_user)
        if project:
            db.session.add(project)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Aqui NÃO vamos devolver 500 cego. Vamos devolver JSON dizendo erro,
        # mas ainda assim status 200 se você quiser que o front trate como "ok mas com aviso".
        # Se preferir status 500 mantenha 500.
        return jsonify({
            "status": "error",
            "message": "Falha ao gravar no banco",
            "detail": str(e),
        }), 500

    # 6. Retornar snapshot atualizado
    response_payload = {
        "status": "ok",
        "towerHeight": current_user.tower_height,
        "rxHeight": current_user.rx_height,
        "Total_loss": current_user.total_loss,
        "antennaGain": current_user.antenna_gain,
        "rxGain": current_user.rx_gain,
        "transmissionPower": current_user.transmission_power,
        "frequency": current_user.frequencia,
        "antennaTilt": getattr(current_user, "antenna_tilt", None),
        "antennaDirection": getattr(current_user, "antenna_direction", None),
        "timePercentage": current_user.time_percentage,
        "temperature": temperature_c,
        "pressure": current_user.pressure_hpa,
        "waterDensity": current_user.water_density,
        "propagationModel": current_user.propagation_model,
        "service": current_user.servico,
        "polarization": current_user.polarization,
        "p452Version": current_user.p452_version,
        "latitude": current_user.latitude,
        "longitude": current_user.longitude,
        "coverageEngine": coverage_engine,
        "projectSlug": project.slug if project else None,
    }
    if project:
        response_payload["projectSettings"] = project.settings or {}

    return jsonify(response_payload), 200

@bp.route('/')
def inicio():
    return render_template('inicio.html')

@bp.route('/sensors')
def sensors():
    return render_template('sensors2.html')

@bp.route('/index')
def index():
    return render_template('index.html')

@bp.route('/antena')
@login_required
def antena():
    return render_template('antena.html')

@bp.route('/calcular-cobertura')
@login_required
def calcular_cobertura():
    maps_api_key = get_google_maps_key()
    projects = (
        current_user.projects.order_by(Project.created_at.asc()).all()
        if hasattr(current_user, "projects")
        else []
    )
    requested_slug = request.args.get('project')
    active_project = None
    if requested_slug:
        try:
            active_project = project_by_slug_or_404(requested_slug, current_user.uuid)
        except Exception:
            if projects:
                active_project = projects[0]
    elif projects:
        active_project = projects[0]

    if requested_slug and not active_project:
        # slug informado mas nenhum projeto encontrado
        flash('Projeto não encontrado ou sem acesso.', 'error')
        return redirect(url_for('projects.list_projects'))

    engines = list(CoverageEngine)
    selected_engine = None
    if active_project and active_project.settings:
        selected_engine = active_project.settings.get('coverageEngine')

    return render_template(
        'calcular_cobertura.html',
        maps_api_key=maps_api_key,
        project=active_project,
        projects=projects,
        engines=engines,
        selected_engine=selected_engine,
    )

@bp.route('/save-map-image', methods=['POST'])
@login_required
def save_map_image():
    data = request.get_json()
    image_data = data['image']
    user = current_user
    if image_data:
        image_data = base64.b64decode(image_data.split(',')[1])
        user.cobertura_img = image_data
        db.session.commit()
    return jsonify({"message": "Imagem salva com sucesso"})

@bp.route('/list_files/<path:folder>', methods=['GET'])
def list_files(folder):
    base_dir = get_solid_png_dir()
    folder_path = os.path.join(base_dir, folder)
    if os.path.exists(folder_path) and os.path.isdir(folder_path):
        files = [f for f in os.listdir(folder_path) if f.lower().endswith('.png')]
        return jsonify(files)
    else:
        return jsonify([]), 404

@bp.route('/static/SOLID_PRT_ASM/PNGS/<path:filename>', methods=['GET'])
def serve_file(filename):
    return send_from_directory(get_solid_png_dir(), filename)

@bp.route('/calculos-rf')
@login_required
def calculos_rf():
    return render_template('calculos-rf.html')

@bp.route('/gerar-relatorio', methods=['GET'])
@login_required
def download_report():
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    def add_text(text, y_offset=20):
        nonlocal y_position
        c.drawString(50, y_position, text)
        y_position -= y_offset

    def add_image(image_data, y_offset=200, image_width=600):
        nonlocal y_position
        if image_data:
            image_stream = io.BytesIO(image_data)
            try:
                img = Image.open(image_stream)
                img_reader = ImageReader(img)
                aspect_ratio = img.width / img.height
                image_height = image_width / aspect_ratio

                image_x = (width - image_width) / 2
                image_y = y_position - image_height - 20

                if image_y < 50:
                    c.showPage()
                    y_position = height - 50
                    image_y = y_position - image_height - 20

                c.drawImage(img_reader, image_x, image_y, width=image_width, height=image_height,
                            preserveAspectRatio=True, mask='auto')
                y_position = image_y - 10
            except Exception as e:
                print(f"Erro ao adicionar imagem: {e}")
            finally:
                image_stream.close()

    user = current_user
    y_position = height - 50

    fields = [
        f"Frequência: {user.frequencia} MHz",
        f"Altura do centro de fase da antena: {user.tower_height} m",
        f"Total de Perdas: {user.total_loss} dB",
        f"Potência de Transmissão: {user.transmission_power} Watts",
        f"Ganho da Antena: {user.antenna_gain} dBi",
        f"Direção da Antena: {user.antenna_direction}°",
        f"Tilt Elétrico: {user.antenna_tilt}°",
        f"Latitude: {user.latitude}",
        f"Longitude: {user.longitude}",
        f"Serviço: {user.servico}",
        f"Notas: {user.notes or 'Nenhuma nota disponível.'}"
    ]
    for field in fields:
        add_text(field, 15)

    add_image(user.antenna_pattern_img_dia_H, 100)
    add_image(user.antenna_pattern_img_dia_V, 100)
    add_image(user.cobertura_img, 100)
    add_image(user.perfil_img, 100)

    c.showPage()
    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='relatorio.pdf', mimetype='application/pdf')

@bp.route('/calculate-distance', methods=['POST'])
def calculate_distance():
    data = request.get_json()
    start = data['start']; end = data['end']
    start_str = f"{start['lat']},{start['lng']}"
    end_str   = f"{end['lat']},{end['lng']}"

    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
            'origins': start_str,
            'destinations': end_str,
            'key': get_google_maps_key()
        }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        distance_matrix_data = response.json()
        if distance_matrix_data['rows'][0]['elements'][0]['status'] == 'OK':
            distance = distance_matrix_data['rows'][0]['elements'][0]['distance']['value']
            return jsonify({'distance': distance})
        else:
            return jsonify({'error': 'Não foi possível calcular a distância.'}), 400
    else:
        return jsonify({'error': 'Falha na requisição à Google Maps Distance Matrix API.'}), response.status_code

@bp.route('/mapa')
@login_required
def mapa():
    maps_key = get_google_maps_key()
    if current_user.latitude is None or current_user.longitude is None:
        flash('Por favor, defina a posição da torre primeiro.', 'error')
        return redirect(url_for('ui.calcular_cobertura'))
    else:
        start_coords = {"lat": current_user.latitude, "lng": current_user.longitude}
        return render_template('mapa.html', start_coords=start_coords, maps_api_key=maps_key)

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user is None:
            error = 'Usuário não existe.'
            return render_template('index.html', error=error)
        elif not user.check_password(password):
            error = 'Senha incorreta.'
            return render_template('index.html', error=error)
        elif not user.is_active:
            error = 'Conta desativada. Entre em contato com o suporte.'
            return render_template('index.html', error=error)
        elif (not user.is_email_confirmed) and not current_app.config.get('ALLOW_UNCONFIRMED', False):
            flash('Confirme o seu e-mail para acessar a plataforma.', 'warning')
            return render_template('index.html', error='Confirmação de e-mail pendente.')
        login_user(user)
        flash('Login realizado com sucesso.', 'success')
        return redirect(url_for('ui.home'))
    return render_template('index.html')

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email    = request.form['email'].strip().lower()
        password = request.form['password']

        existing_user  = User.query.filter_by(username=username).first()
        existing_email = User.query.filter_by(email=email).first()

        if existing_user:
            return render_template('register.html', error="Usuário já existe.")
        if existing_email:
            return render_template('register.html', error="E-mail já cadastrado.")

        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()
        _create_default_project(new_user)
        db.session.commit()

        token = generate_token(new_user.email, 'confirm')
        confirm_url = url_for('ui.confirm_email', token=token, _external=True)
        send_email(
            "Confirme sua conta ATX Coverage",
            new_user.email,
            "email/confirm_email.html",
            "email/confirm_email.txt",
            user=new_user,
            confirm_url=confirm_url,
        )
        flash('Cadastro realizado! Verifique seu e-mail para confirmar a conta.', 'success')
        return redirect(url_for('ui.index'))

    return render_template('register.html')


@bp.route('/auth/confirm/<token>')
def confirm_email(token):
    max_age = current_app.config.get('EMAIL_CONFIRM_MAX_AGE', 86400)
    email = load_token(token, max_age=max_age, expected_purpose='confirm')
    if not email:
        flash('Link de confirmação inválido ou expirado.', 'error')
        return redirect(url_for('ui.index'))

    user = User.query.filter_by(email=email.lower()).first()
    if user is None:
        flash('Conta não encontrada para o e-mail informado.', 'error')
        return redirect(url_for('ui.index'))

    if not user.is_email_confirmed:
        user.is_email_confirmed = True
        user.updated_at = datetime.utcnow()
        db.session.commit()
        flash('E-mail confirmado com sucesso!', 'success')
    else:
        flash('Sua conta já estava confirmada.', 'info')

    if not current_user.is_authenticated:
        login_user(user)
    return redirect(url_for('ui.home'))


@bp.route('/auth/resend-confirmation', methods=['GET', 'POST'])
def resend_confirmation():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and not user.is_email_confirmed:
            token = generate_token(user.email, 'confirm')
            confirm_url = url_for('ui.confirm_email', token=token, _external=True)
            send_email(
                "Confirme sua conta ATX Coverage",
                user.email,
                "email/confirm_email.html",
                "email/confirm_email.txt",
                user=user,
                confirm_url=confirm_url,
            )
        flash('Se o e-mail estiver cadastrado e pendente de confirmação, reenviamos as instruções.', 'info')
        return redirect(url_for('ui.index'))
    return render_template('auth/resend_confirmation.html')


@bp.route('/auth/request-reset', methods=['GET', 'POST'])
def request_password_reset():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = generate_token(user.email, 'reset')
            reset_url = url_for('ui.reset_password', token=token, _external=True)
            send_email(
                "Redefina sua senha ATX Coverage",
                user.email,
                "email/reset_password.html",
                "email/reset_password.txt",
                user=user,
                reset_url=reset_url,
            )
        flash('Se o e-mail estiver cadastrado, enviaremos instruções de redefinição.', 'info')
        return redirect(url_for('ui.index'))
    return render_template('auth/request_reset.html')


@bp.route('/auth/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    max_age = current_app.config.get('PASSWORD_RESET_MAX_AGE', 7200)
    email = load_token(token, max_age=max_age, expected_purpose='reset')
    if not email:
        flash('Token de redefinição inválido ou expirado.', 'error')
        return redirect(url_for('ui.index'))

    user = User.query.filter_by(email=email.lower()).first()
    if user is None:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('ui.index'))

    error = None
    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        if password != confirm_password:
            error = 'As senhas não coincidem.'
        elif len(password) < 8:
            error = 'A senha deve possuir pelo menos 8 caracteres.'
        else:
            user.set_password(password)
            user.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Senha atualizada com sucesso! Faça login com a nova credencial.', 'success')
            return redirect(url_for('ui.index'))
    return render_template('auth/reset_password.html', token=token, error=error)


@bp.route('/home')
@login_required
def home():
    projects = current_user.projects.order_by(Project.created_at.desc()).all()
    return render_template('home.html', projects=projects)

# -------- Antena: carregar/mostrar diagramas --------

@bp.route('/carregar_imgs', methods=['GET'])
@login_required
def carregar_imgs():
    user_id = current_user.id
    user = User.query.get(user_id)

    direction = user.antenna_direction
    tilt      = user.antenna_tilt

    if not user.antenna_pattern:
        return jsonify({'error': 'Nenhum diagrama salvo.'}), 404

    file_content = user.antenna_pattern.decode('latin1', errors='ignore')

    # Parser universal
    horizontal_data, vertical_data, meta = parse_pat(file_content)

    # Horizontal: original vs rotacionado (se houver direção)
    if direction is not None:
        rotation_index = int(direction / (360 / len(horizontal_data)))
        rotated_data   = np.roll(horizontal_data, rotation_index)
        horizontal_image_base64 = generate_dual_polar_plot(horizontal_data, rotated_data, direction)
    else:
        horizontal_image_base64 = generate_polar_plot(horizontal_data)

    # Vertical: com/sem tilt
    angles = np.linspace(-90, 90, len(vertical_data), endpoint=True)
    if tilt is not None:
        vertical_image_base64 = generate_dual_rectangular_plot(vertical_data, angles, tilt)
    else:
        vertical_image_base64 = generate_rectangular_plot(vertical_data)

    return jsonify({
        'fileContent': file_content,
        'horizontal_image_base64': horizontal_image_base64,
        'vertical_image_base64': vertical_image_base64
    })

@bp.route('/salvar_diagrama', methods=['POST'])
@login_required
def salvar_diagrama():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    direction = request.form.get('direction')
    tilt      = request.form.get('tilt')

    try:
        direction = float(direction) if direction and direction.strip() != '' else None
    except ValueError:
        direction = None
    try:
        tilt = float(tilt) if tilt and tilt.strip() != '' else None
    except ValueError:
        tilt = None

    user_id = current_user.id
    user = User.query.get(user_id)
    if user:
        success, message = salvar_diagrama_usuario(user, file, direction, tilt)
        if success:
            return jsonify({'message': 'File and settings saved successfully'})
        else:
            return jsonify({'error': message}), 500
    else:
        return jsonify({'error': 'User not found'}), 404

@bp.route('/upload_diagrama', methods=['POST'])
@login_required
def gerardiagramas():
    tilt = request.form.get('tilt', type=float)
    direction = request.form.get('direction', type=float)
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file provided'}), 400

    # salva no banco usando função auxiliar
    success, message = salvar_diagrama_usuario(current_user, file, direction, tilt)
    if not success:
        return jsonify({'error': message}), 500

    # lê para parse - resetar o ponteiro do arquivo
    file.seek(0)
    file_content = file.read().decode('latin1', errors='ignore')
    horizontal_data, vertical_data, meta = parse_pat(file_content)

    if direction is None:
        horizontal_image_base64 = generate_polar_plot(horizontal_data)
    else:
        rotation_index = int(direction / (360 / len(horizontal_data)))
        rotated_data   = np.roll(horizontal_data, rotation_index)
        horizontal_image_base64 = generate_dual_polar_plot(horizontal_data, rotated_data, direction)

    angles_v = np.linspace(-90, 90, len(vertical_data), endpoint=True)
    if tilt is None:
        vertical_image_base64 = generate_rectangular_plot(vertical_data)
    else:
        vertical_image_base64 = generate_dual_rectangular_plot(vertical_data, angles_v, tilt)

    return jsonify({
        'horizontal_image_base64': horizontal_image_base64,
        'vertical_image_base64': vertical_image_base64
    })

# -------- Plots H/V --------

def generate_polar_plot(data):
    azimutes = np.linspace(0, 2 * np.pi, len(data))
    fig = plt.figure(figsize=(10, 10))
    ax = plt.subplot(111, polar=True)
    ax.plot(azimutes, data, label='Horizontal Radiation Pattern')

    threshold = 1/np.sqrt(2)
    indices = np.where(data <= threshold)[0]
    if len(indices) > 1:
        idx_first = indices[0]; idx_last = indices[-1]
        ax.plot([azimutes[idx_first], azimutes[idx_first]], [0, data[idx_first]], 'k-', linewidth=2)
        ax.plot([azimutes[idx_last],  azimutes[idx_last]],  [0, data[idx_last]],  'k-', linewidth=2)
        angle_first_deg = np.degrees(azimutes[idx_first])
        angle_last_deg  = np.degrees(azimutes[idx_last])
        hpbw = 360 - angle_last_deg + angle_first_deg
        ax.text(0.97, 0.99, f'HPBW: {hpbw:.2f}°', transform=ax.transAxes,
                ha='left', va='top', bbox=dict(facecolor='white', alpha=0.8))

        front_attenuation = data[np.argmin(np.abs(azimutes - 0))]
        back_attenuation  = data[np.argmin(np.abs(azimutes - np.pi))]
        fbr = 20 * math.log10(max(front_attenuation,1e-6) / max(back_attenuation,1e-6))
        ax.text(0.97, 0.95, f'F_B Ratio: {fbr:.2f} dB', transform=ax.transAxes,
                ha='left', va='top', bbox=dict(facecolor='white', alpha=0.8))

    peak_to_peak = np.ptp(data)
    ax.text(0.97, 0.91, f'Peak2Peak: {peak_to_peak:.2f} E/Emax', transform=ax.transAxes,
            ha='left', va='top', bbox=dict(facecolor='white', alpha=0.8))

    directivity_dB = calculate_directivity(data, 'h')
    data_table = [{"azimuth": f"{np.degrees(a):.1f}°", "gain": f"{g:.3f}"} for a, g in zip(azimutes, data)]
    current_user.antenna_pattern_data_h = json.dumps(data_table)
    db.session.commit()
    ax.text(0.97, 0.87, f'Directivity: {directivity_dB:.2f} dB', transform=ax.transAxes,
            ha='left', va='top', bbox=dict(facecolor='white', alpha=0.8))

    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)
    ax.set_title('E/Emax')
    plt.ylim(0, 1)
    plt.grid(True)

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', bbox_inches='tight')
    img_buffer.seek(0)
    current_user.antenna_pattern_img_dia_H = img_buffer.getvalue()
    db.session.commit()
    img_buffer.seek(0)
    img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
    img_buffer.close()
    plt.close(fig)
    return img_base64

def generate_dual_polar_plot(original_data, rotated_data, direction):
    azimutes = np.linspace(0, 2 * np.pi, len(original_data))
    fig = plt.figure(figsize=(10, 10))
    ax = plt.subplot(111, polar=True)
    ax.plot(azimutes, original_data, linestyle='dashed', color='red', label='Original Pattern')
    ax.plot(azimutes, rotated_data, color='blue', label=f'Rotated Pattern to {direction}°')

    threshold = 1/np.sqrt(2)
    indices = np.where(original_data <= threshold)[0]
    if len(indices) > 1:
        idx_first = indices[0]; idx_last = indices[-1]
        ax.plot([azimutes[idx_first], azimutes[idx_first]], [0, original_data[idx_first]], 'k-', linewidth=2)
        ax.plot([azimutes[idx_last],  azimutes[idx_last]],  [0, original_data[idx_last]],  'k-', linewidth=2)
        angle_first_deg = np.degrees(azimutes[idx_first])
        angle_last_deg  = np.degrees(azimutes[idx_last])
        hpbw = 360 - angle_last_deg + angle_first_deg
        ax.text(0.97, 0.99, f'HPBW: {hpbw:.2f}°', transform=ax.transAxes,
                ha='left', va='top', bbox=dict(facecolor='white', alpha=0.8))

    front_attenuation = original_data[np.argmin(np.abs(azimutes - 0))]
    back_attenuation  = original_data[np.argmin(np.abs(azimutes - np.pi))]
    fbr = 20 * math.log10(max(front_attenuation,1e-6) / max(back_attenuation,1e-6))
    ax.text(0.97, 0.95, f'F_B Ratio: {fbr:.2f} dB', transform=ax.transAxes,
            ha='left', va='top', bbox=dict(facecolor='white', alpha=0.8))

    peak_to_peak = np.ptp(original_data)
    ax.text(0.97, 0.91, f'Peak2Peak: {peak_to_peak:.2f} E/Emax', transform=ax.transAxes,
            ha='left', va='top', bbox=dict(facecolor='white', alpha=0.8))

    directivity_dB = calculate_directivity(original_data, 'h')
    ax.text(0.97, 0.87, f'Directivity: {directivity_dB:.2f} dB', transform=ax.transAxes,
            ha='left', va='top', bbox=dict(facecolor='white', alpha=0.8))

    data_table = [{"azimuth": f"{np.degrees(a):.1f}°", "gain": f"{g:.3f}"} for a, g in zip(azimutes, rotated_data)]
    current_user.antenna_pattern_data_h_modified = json.dumps(data_table)
    db.session.commit()

    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)
    ax.set_title('Antenna Horizontal Radiation Pattern')
    plt.ylim(0, 1)
    ax.grid(True)
    ax.legend(loc='upper left')

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', bbox_inches='tight')
    img_buffer.seek(0)
    current_user.antenna_pattern_img_dia_H = img_buffer.getvalue()
    db.session.commit()
    img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
    img_buffer.close()
    plt.close()
    return img_base64

# --- util para HPBW em campo ---
def _hpbw_from_field(angles_deg, field_norm):
    ang = np.asarray(angles_deg, float)
    f   = np.asarray(field_norm,  float)
    if ang.ndim != 1 or f.ndim != 1 or ang.size != f.size or ang.size < 3:
        return np.nan
    level = 1/np.sqrt(2)  # 0.707
    peak_idx = int(np.nanargmax(f))

    left  = np.where(f[:peak_idx]  <= level)[0]
    right = np.where(f[peak_idx:] <= level)[0] + peak_idx

    def interp_cross(i1, i2):
        x1, y1 = ang[i1], f[i1]
        x2, y2 = ang[i2], f[i2]
        if x1 == x2: return x1
        w = (level - y1) / (y2 - y1)
        return x1 + w*(x2 - x1)

    if left.size > 0:
        i2 = left[-1]
        i1 = i2 + 1
        ang_left = interp_cross(i1, i2)
    else:
        ang_left = ang[0]

    if right.size > 0:
        i2 = right[0]
        i1 = i2 - 1
        ang_right = interp_cross(i1, i2)
    else:
        ang_right = ang[-1]

    return float(ang_right - ang_left)

def generate_rectangular_plot(vert_lin):
    angles = np.linspace(-90, 90, len(vert_lin), endpoint=True)
    v = np.asarray(vert_lin, float)
    # Debug: log shape and sample values to help diagnose flat-line plots
    try:
        current_app.logger.debug(f"generate_rectangular_plot: angles_len={len(angles)}, v_shape={v.shape}, v_min={np.nanmin(v):.6g}, v_max={np.nanmax(v):.6g}")
        current_app.logger.debug(f"generate_rectangular_plot: v_sample={v[:10].tolist()}")
    except Exception:
        pass
    vmax = np.nanmax(v) if np.isfinite(v).any() else 1.0
    v = np.clip(v / (vmax if vmax > 0 else 1.0), 0.0, 1.0)

    directivity_dB = calculate_directivity(v, 'v')
    hpbw = _hpbw_from_field(angles, v)

    plt.figure(figsize=(10, 9))
    mask = np.isfinite(v)
    plt.plot(angles[mask], v[mask], label=f'Elevation (Directivity: {directivity_dB:.2f} dB)')

    if np.isfinite(hpbw):
        plt.annotate(f'HPBW: {hpbw:.2f}°', xy=(0.95, 0.95), xycoords='axes fraction',
                     ha='right', va='top', bbox=dict(boxstyle="round", fc="white", ec="black"))

    i0 = np.argmin(np.abs(angles))
    plt.annotate(f'E/Emax at 0°: {v[i0]*100:.1f}%',
                 xy=(0, v[i0]), xytext=(0, -40), textcoords='offset points',
                 arrowprops=dict(arrowstyle='->'), ha='center', va='top',
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="b", lw=1.5))

    plt.xlabel('Elevation Angle (degrees)')
    plt.ylabel('E/Emax')
    plt.title('Elevation Pattern')
    plt.ylim(0, 1)
    # Ensure x-axis maps -90..+90 with clear ticks
    plt.xlim(-90, 90)
    plt.xticks(np.arange(-90, 91, 30))
    plt.grid(True)
    plt.legend()

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight')
    plt.close()
    buffer.seek(0)
    current_user.antenna_pattern_img_dia_V = buffer.getvalue()
    db.session.commit()
    buffer.seek(0)
    img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    buffer.close()
    return img_base64

def generate_dual_rectangular_plot(original_vert_lin, angles, tilt=None):
    base = np.asarray(original_vert_lin, float)
    # Debug: log shape and sample values to help diagnose flat-line plots
    try:
        current_app.logger.debug(f"generate_dual_rectangular_plot: angles_len={len(angles)}, base_shape={base.shape}, base_min={np.nanmin(base):.6g}, base_max={np.nanmax(base):.6g}")
        current_app.logger.debug(f"generate_dual_rectangular_plot: base_sample={base[:10].tolist()}")
    except Exception:
        pass
    vmax = np.nanmax(base) if np.isfinite(base).any() else 1.0
    base = np.clip(base / (vmax if vmax > 0 else 1.0), 0.0, 1.0)

    mod = base.copy()
    if tilt is not None:
        shift = int(np.round(tilt))  # ~1 amostra/°
        mod = np.roll(mod, shift)

    directivity_base = calculate_directivity(base, 'v')
    directivity_mod  = calculate_directivity(mod,  'v')
    hpbw_mod = _hpbw_from_field(angles, mod)

    plt.figure(figsize=(10, 9))
    plt.plot(angles, base, 'r--', label=f'Original (Dir: {directivity_base:.2f} dB)')
    plt.plot(angles, mod,  'b-', label=f'Tilted (Dir: {directivity_mod:.2f} dB)')

    if np.isfinite(hpbw_mod):
        plt.annotate(f'HPBW: {hpbw_mod:.2f}°', xy=(0.95, 0.95), xycoords='axes fraction',
                     ha='right', va='top', bbox=dict(boxstyle="round", fc="white", ec="black"))

    i0 = np.argmin(np.abs(angles))
    plt.annotate(f'E/Emax at 0°: {mod[i0]*100:.1f}%',
                 xy=(0, mod[i0]), xytext=(0, -40), textcoords='offset points',
                 arrowprops=dict(arrowstyle='->'), ha='center', va='top',
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="b", lw=1.5))

    plt.xlabel('Elevation Angle (degrees)')
    plt.ylabel('E/Emax')
    plt.title('Dual Elevation Pattern Comparison')
    plt.legend()
    plt.ylim(0, 1)
    # Ensure x-axis maps -90..+90 with clear ticks
    try:
        plt.xlim(-90, 90)
        plt.xticks(np.arange(-90, 91, 30))
    except Exception:
        pass
    plt.grid(True)

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight')
    plt.close()
    buffer.seek(0)
    current_user.antenna_pattern_img_dia_V = buffer.getvalue()
    db.session.commit()
    buffer.seek(0)
    img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    buffer.close()
    return img_base64

# -------- Diretividade --------

def calculate_directivity(smoothed_data, tipo):
    if tipo == 'h':
        power_normalized = smoothed_data / np.max(smoothed_data)
        azimutes = np.linspace(0, 2 * np.pi, len(smoothed_data))
        integral = simpson(y=power_normalized, x=azimutes)
        directivity = 2 * np.pi / integral
        return 10 * np.log10(directivity)
    elif tipo == 'v':
        angles = np.linspace(-90, 90, len(smoothed_data), endpoint=True)
        power_normalized = smoothed_data / np.max(smoothed_data)
        radians_ang = np.deg2rad(angles)
        integral = simpson(y=power_normalized, x=radians_ang)
        directivity = np.pi / integral
        return 10 * np.log10(directivity)

# -------- Notas --------

@bp.route('/update-notes', methods=['POST'])
@login_required
def update_notes():
    notes = request.form.get('notes')
    if notes is not None:
        current_user.notes = notes
        db.session.commit()
        return jsonify({'message': 'Notas atualizadas com sucesso!'}), 200
    else:
        return jsonify({'error': 'Nenhuma nota fornecida.'}), 400

# -------- Elevação Google --------

@bp.route('/fetch-elevation', methods=['POST'])
def fetch_elevation():
    try:
        path_data = request.json['path']
        path_str  = '|'.join([f"{point['lat']},{point['lng']}" for point in path_data])
        url = f"https://maps.googleapis.com/maps/api/elevation/json?path={path_str}&samples=256&key={get_google_maps_key()}"

        response = requests.get(url)
        if response.status_code == 200:
            elevation_data = response.json()
            return jsonify(elevation_data)
        else:
            current_app.logger.error('Erro na API de Elevação: Status code {}'.format(response.status_code))
            return jsonify({"error": "Failed to fetch elevation data"}), 500
    except Exception as e:
        current_app.logger.error('Erro ao processar /fetch-elevation: {}'.format(e))
        return jsonify({"error": "Internal server error"}), 500

# -------- Utilitários geodésicos --------

def adjust_center_for_coverage(lon_center, lat_center, radius_km):
    original_location = (lat_center.to(u.deg).value, lon_center.to(u.deg).value)
    northern_point = geodesic(kilometers=radius_km).destination(original_location, bearing=0)
    return northern_point.longitude, northern_point.latitude

def generate_coverage_image(lons, lats, _total_atten, radius_km, lon_center, lat_center):
    fig, ax = plt.subplots()
    atten_db = _total_atten.to(u.dB).value
    levels = np.linspace(atten_db.min(), atten_db.max(), 100)
    cim = ax.contourf(lons, lats, atten_db, levels=levels, cmap='rainbow')

    cax = fig.add_axes([0.85, 0.15, 0.05, 0.7])
    plt.colorbar(cim, cax=cax, orientation='vertical', label='Atenuação [dB]')

    earth_radius_km = 6371.0
    radius_degrees_lat = radius_km / (earth_radius_km * (np.pi/180))
    radius_degrees_lon = radius_km / (earth_radius_km * np.cos(np.radians(lat_center.to(u.deg).value)) * (np.pi/180))

    lon_center_adjusted = lon_center.to(u.deg).value
    lat_center_adjusted = lat_center.to(u.deg).value

    circle = plt.Circle((lon_center_adjusted, lat_center_adjusted),
                        max(radius_degrees_lon, radius_degrees_lat),
                        color='red', fill=False, linestyle='--')
    ax.add_artist(circle)

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', transparent=True)
    img_buffer.seek(0)
    plt.close(fig)
    return img_buffer

def calculate_bearing(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dLon = lng2 - lng1
    x = math.sin(dLon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    initial_bearing = math.atan2(x, y)
    initial_bearing = math.degrees(initial_bearing)
    compass_bearing = (initial_bearing + 360) % 360
    return compass_bearing

def fresnel_zone_radius(d1, d2, wavelength):
    return np.sqrt(wavelength * d1 * d2 / (d1 + d2))

# -------- Perfil (TX → RX) COM CORREÇÃO DA CURVATURA --------

@bp.route('/gerar_img_perfil', methods=['POST'])
@login_required
def gerar_img_perfil():
    data = request.get_json()
    start_coords = data['path'][0]
    end_coords   = data['path'][1]
    path = data['path']

    # ========= parâmetros TX/RX =========
    Ptx_W         = max(float(current_user.transmission_power or 0.0), 1e-6)  # W
    G_tx_dBi_base = current_user.antenna_gain or 0.0                          # dBi pico nominal TX
    G_rx_dbi      = current_user.rx_gain or 0.0                                # dBi RX
    freq_mhz_user = current_user.frequencia or 100.0                           # MHz
    totalloss     = current_user.total_loss or 0.0                             # perdas sistêmicas (cabos etc.) dB
    pattern       = current_user.antenna_pattern
    direction     = current_user.antenna_direction
    tilt          = current_user.antenna_tilt

    # bearing TX->RX (graus azimute)
    direction_rx = calculate_bearing(
        start_coords['lat'], start_coords['lng'],
        end_coords['lat'],   end_coords['lng']
    )

    # ========= ganho TX efetivo incluindo padrão direcional =========
    delta_dir_dB  = 0.0
    delta_tilt_dB = 0.0
    horizontal_data = None
    vertical_data   = None

    if pattern is not None:
        file_content = pattern.decode('latin1', errors='ignore')

        # parse_pat retorna padrão horizontal/vertical em E/Emax (linear)
        horizontal_data, vertical_data, _meta = parse_pat(file_content)

        # Ajuste horizontal (azimute)
        if horizontal_data is not None:
            horiz = np.asarray(horizontal_data, dtype=float)
            # aplica rotação global da antena
            if direction is not None:
                rotation_index = int(direction / (360.0 / len(horiz)))
                horiz = np.roll(horiz, rotation_index)

            # valor E/Emax na direção real do RX
            e_emax = horiz[int(direction_rx) % 360]
            e_emax = max(e_emax, 1e-6)
            # 20log10(E/Emax) -> variação de ganho em dB
            delta_dir_dB = 20.0 * math.log10(e_emax)

        # Ajuste vertical (tilt mecânico/elétrico)
        if vertical_data is not None:
            vert = np.asarray(vertical_data, dtype=float)
            # aplica tilt (rolagem positiva = inclinar feixe)
            if tilt:
                vert = np.roll(vert, int(np.round(tilt)))

            # assumimos índice central = 0° elétrico
            idx_zero = len(vert) // 2
            e_vert = max(vert[idx_zero], 1e-6)
            delta_tilt_dB = 20.0 * math.log10(e_vert)

    G_tx_dBi = G_tx_dBi_base + delta_dir_dB + delta_tilt_dB  # dBi efetivo TX naquela direção

    # ========= frequência e ERP =========
    # limite inferior só pra não quebrar log10
    if freq_mhz_user < 100.0:
        # fora da faixa ideal do P.452 (< ~700 MHz), mas mantemos coerência interna
        freq_mhz_user = 100.0
    frequency = (freq_mhz_user / 1000.0) * u.GHz  # pycraf espera GHz

    # Potência TX em dBm
    P_dBm = 10.0 * math.log10(Ptx_W / 0.001)  # W → dBm
    # ERP naquela direção (já descontando perdas de cabo)
    erp = P_dBm + G_tx_dBi - totalloss

    # ========= coordenadas geográficas e perfil SRTM =========
    tx_coords = path[0]
    rx_coords = path[1]
    lon_tx, lat_tx = float(tx_coords['lng']) * u.deg, float(tx_coords['lat']) * u.deg
    lon_rx, lat_rx = float(rx_coords['lng']) * u.deg, float(rx_coords['lat']) * u.deg

    temperature   = 293.15 * u.K
    pressure      = 1013.0 * u.hPa
    time_percent  = 40.0 * u.percent
    zone_t, zone_r = pathprof.CLUTTER.UNKNOWN, pathprof.CLUTTER.UNKNOWN

    with SrtmConf.set(srtm_dir='./SRTM', download='missing', server='viewpano'):
        profile = pathprof.srtm_height_profile(
            lon_tx, lat_tx,
            lon_rx, lat_rx,
            step=1 * u.m
        )
        longitudes, latitudes, total_distance, distances, heights, angle1, angle2, additional_data = profile

    # alturas das antenas acima do solo
    h_rg = (current_user.rx_height or 1.0) * u.m
    h_tg = (current_user.tower_height or 30.0) * u.m

    # ========= curvatura da Terra =========
    distances_m = distances.to(u.m).value
    heights_m   = heights.to(u.m).value

    # (opcional) alturas ajustadas por curvatura local da Terra
    # mantemos aqui se você quiser usar depois p/ debug:
    adjusted_heights = adjust_heights_for_curvature(
        distances_m,
        heights_m,
        h_tg.value,
        h_rg.value
    )

    # raio efetivo da Terra (k-factor). Guardamos pra uso futuro se quiser plotar info.
    effective_radius = calculate_effective_earth_radius()

    # ========= perdas ITU-R P.452 no enlace ponto-a-ponto =========
    results = pathprof.losses_complete(
        frequency,
        temperature,
        pressure,
        lon_tx, lat_tx,
        lon_rx, lat_rx,
        h_tg, h_rg,
        1 * u.m,
        time_percent,
        zone_t=zone_t,
        zone_r=zone_r,
    )

    # distância total TX→RX
    rx_position_km = distances.to(u.km)[-1].value

    # tentar ler L_b_corr se existir, senão L_b
    _Lb_corr_obj = results.get('L_b_corr', None)
    if _Lb_corr_obj is None:
        _Lb_corr_obj = results.get('L_b', None)

    if hasattr(_Lb_corr_obj, 'value'):
        val = _Lb_corr_obj.value
        if isinstance(val, np.ndarray):
            Lb_corr = float(val[0])
        else:
            Lb_corr = float(val)
    else:
        # fallback bruto
        Lb_corr = float(_Lb_corr_obj)

    # potência recebida estimada em dBm no RX:
    # Prx = ERP(dBm) + G_rx(dBi) - L_path(dB)
    sinal_recebido = erp + G_rx_dbi - Lb_corr  # dBm

    # ========= geometria básica pra plot =========
    distances_km = distances.to(u.km).value
    terrain_x    = distances_km  # eixo X em km

    tx_top = heights_m[0]    + h_tg.value
    rx_top = heights_m[-1]   + h_rg.value

    min_height = float(np.min(heights_m))

    # ========= figura / layout =========
    fig = plt.figure(figsize=(15, 8))
    gs  = fig.add_gridspec(
        2, 1,
        height_ratios=[4, 1],
        hspace=0.18
    )
    ax = fig.add_subplot(gs[0])

    # ===== Terreno base (areia/marrom) =====
    ax.fill_between(
        terrain_x,
        heights_m,
        color='#d8c9a7',
        alpha=0.85,
        label='Terreno'
    )
    ax.plot(
        terrain_x,
        heights_m,
        color='#564d33',
        linewidth=2
    )

    # ===== Curvatura da Terra (referência do feixe seguindo Terra efetiva) =====
    curvature_line = []
    for i, dist_km in enumerate(terrain_x):
        if i == 0:
            height_point = heights_m[i] + h_tg.value
        elif i == len(terrain_x) - 1:
            height_point = heights_m[i] + h_rg.value
        else:
            drop = earth_curvature_correction(dist_km)  # queda geométrica da curvatura
            height_point = heights_m[i] - drop
        curvature_line.append(height_point)

    ax.plot(
        terrain_x,
        curvature_line,
        color='#b71c1c',
        linestyle='--',
        linewidth=1.6,
        alpha=0.8,
        label='Curvatura da Terra'
    )

    # ===== Torres TX / RX (retângulos azuis/roxo) =====
    total_span_km = max(rx_position_km, 1e-3)
    tower_width   = max(total_span_km * 0.02, 0.06)

    tx_rect = Rectangle(
        (-tower_width / 2.0, heights_m[0]),
        tower_width,
        h_tg.value,
        facecolor='#0d6efd',
        edgecolor='#0a58ca',
        alpha=0.9,
        label='TX',
        zorder=6
    )
    rx_rect = Rectangle(
        (terrain_x[-1] - tower_width / 2.0, heights_m[-1]),
        tower_width,
        h_rg.value,
        facecolor='#6610f2',
        edgecolor='#520dc2',
        alpha=0.9,
        label='RX',
        zorder=6
    )
    ax.add_patch(tx_rect)
    ax.add_patch(rx_rect)

    # ===== Linha de visada ideal (reta, sem curvatura) =====
    ax.plot(
        [0.0, rx_position_km],
        [tx_top, rx_top],
        color='#ff9800',
        linestyle=':',
        linewidth=1.5,
        label='Linha Reta (sem curvatura)'
    )

    # ===== 1ª Zona de Fresnel =====
    # amostragem suave pra preencher área
    n_points = 200
    x_smooth = np.linspace(0.0, rx_position_km, n_points)

    # comprimento de onda
    c0 = c  # velocidade da luz já importada (m/s)
    wavelength = c0 / frequency.to(u.Hz).value  # m

    # raio da 1ª Fresnel para cada ponto x_smooth
    fresnel_radius = np.array([
        fresnel_zone_radius(
            xi * 1000.0,
            (rx_position_km - xi) * 1000.0,
            wavelength
        )
        for xi in x_smooth
    ])

    # linha base reta entre topos TX/RX
    direct_line = np.linspace(tx_top, rx_top, n_points)

    # correção da curvatura da Terra pra cada ponto
    curvature_adjustment = np.array([
        earth_curvature_correction(xi)
        for xi in x_smooth
    ])

    # base ajustada = linha direta menos queda de curvatura
    adjusted_base = direct_line - curvature_adjustment

    fresnel_top    = adjusted_base + fresnel_radius
    fresnel_bottom = adjusted_base - fresnel_radius

    # preencher Fresnel
    ax.fill_between(
        x_smooth,
        fresnel_bottom,
        fresnel_top,
        color='#ffe082',
        alpha=0.45,
        label='1ª Zona Fresnel'
    )
    # contorno superior/inferior em roxo tracejado
    ax.plot(
        x_smooth,
        fresnel_top,
        color='#9c27b0',
        linestyle='--',
        linewidth=1.2,
        alpha=0.8
    )
    ax.plot(
        x_smooth,
        fresnel_bottom,
        color='#9c27b0',
        linestyle='--',
        linewidth=1.2,
        alpha=0.8
    )

    # ===== Bloqueio da Fresnel (regiões em vermelho no terreno) =====
    # calcular no grid do terreno (mesma resolução SRTM)
    base_line_profile = np.linspace(tx_top, rx_top, len(terrain_x))
    curvature_profile = np.array([
        earth_curvature_correction(dist)
        for dist in terrain_x
    ])
    fresnel_radius_profile = np.array([
        fresnel_zone_radius(
            d * 1000.0,
            (rx_position_km - d) * 1000.0,
            wavelength
        )
        for d in terrain_x
    ])

    # limite inferior permitido (bottom da zona)
    fresnel_bottom_profile = (
        base_line_profile
        - curvature_profile
        - fresnel_radius_profile
    )

    # ponto obstruído se o terreno está acima da "fresnel_bottom_profile"
    obstruction_mask = heights_m >= fresnel_bottom_profile
    # não marcar as torres como obstáculo
    if len(obstruction_mask) >= 2:
        obstruction_mask[0]  = False
        obstruction_mask[-1] = False

    # sobrepinta solo onde tem obstrução (faixa vermelha mais grossa)
    if np.any(obstruction_mask):
        ax.fill_between(
            terrain_x,
            heights_m,
            where=obstruction_mask,
            color='#c62828',
            alpha=0.7,
            interpolate=True,
            label='Obstáculo na Fresnel'
        )

    # também marcar pontos discretos (marcadores vermelhos)
    obstacle_distances = terrain_x[obstruction_mask]
    if obstacle_distances.size:
        ax.scatter(
            obstacle_distances,
            heights_m[obstruction_mask],
            color='#c62828',
            s=32,
            zorder=10
        )

    # ===== Escalas de altura =====
    max_profile_height = max(
        float(np.max(heights_m)),
        float(np.max(fresnel_top)),
        tx_top,
        rx_top,
    )
    span = max(max_profile_height - min_height, 1.0)

    # baseline visual pra dar "respiro" embaixo
    if abs(min_height) < 1e-3:
        baseline = min_height - 0.3 * span
    else:
        baseline = min_height - abs(min_height) * 0.3

    y_min = min(baseline, min_height - 0.15 * span)
    y_max = max_profile_height + max(span * 0.12, 10.0)

    ax.set_ylim(y_min, y_max)
    ax.set_xlim(0.0, rx_position_km)

    # ========= Campo elétrico estimado no RX =========
    # fórmula já discutida: E(dBµV/m) = Prx(dBm) - Grx(dBi) + 77.2 + 20log10(fMHz)
    freq_for_field = max(float(freq_mhz_user), 0.1)
    field_rx_dbuv = (
        sinal_recebido
        - (G_rx_dbi or 0.0)
        + 77.2
        + 20.0 * math.log10(freq_for_field)
    )

    # ===== Lista de obstáculos (até 6 primeiras distâncias km) =====
    if obstacle_distances.size:
        obstacle_desc = ", ".join(f"{dist:.2f} km" for dist in obstacle_distances[:6])
    else:
        obstacle_desc = 'Nenhum'

    # ========= Subplot de informações =========
    ax_info = fig.add_subplot(gs[1])
    ax_info.axis('off')

    info_lines = [
        f"Distância TX→RX: {rx_position_km:.2f} km",
        f"Direção RX: {direction_rx:.2f}°",
        f"Ganho TX (base + ΔH + ΔV): {G_tx_dBi:.2f} dBi ({G_tx_dBi_base:.2f} + {delta_dir_dB:.2f} + {delta_tilt_dB:.2f})",
        f"ERP na direção: {erp:.2f} dBm",
        f"Perdas (P.452): {Lb_corr:.2f} dB",
        f"Ganho RX: {G_rx_dbi:.2f} dBi",
        f"Potência recebida estimada: {sinal_recebido:.2f} dBm",
        f"Campo estimado no RX: {field_rx_dbuv:.2f} dBµV/m",
        f"Obstáculos na 1ª Fresnel: {obstacle_desc}",
    ]

    ax_info.text(
        0.01, 0.95,
        "\n".join(info_lines),
        fontsize=10,
        ha='left',
        va='top'
    )

    # ========= rotulagem e legenda =========
    ax.set_xlabel('Distância (km)', fontsize=11)
    ax.set_ylabel('Elevação (m)', fontsize=11)
    ax.set_title('Perfil de Elevação com Curvatura e Fresnel', fontsize=13)

    ax.grid(True, which="both", ls="--", alpha=0.5)

    # legenda organizada
    ax.legend(
        loc='lower right',
        fontsize=9,
        frameon=True,
        framealpha=0.9
    )

    # ========= render final =========
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', bbox_inches='tight', dpi=120)
    img_buffer.seek(0)

    # salva no usuário (binário bruto na sessão)
    current_user.perfil_img = img_buffer.getvalue()
    db.session.commit()

    # devolve base64
    img_buffer.seek(0)
    img_base64 = base64.b64encode(img_buffer.read()).decode('utf-8')
    img_buffer.close()
    plt.close(fig)

    return jsonify({
        "image": img_base64,
        "info": info_lines,
        "distance_km": rx_position_km,
        "erp_dbm": erp,
        "rx_power_dbm": sinal_recebido,
        "rx_field_dbuvm": field_rx_dbuv,
        "obstacles": obstacle_desc,
    })




# -------- Cobertura (mapa) --------

def create_attenuation_dict(lons, lats, attenuation):
    attenuation_dict = {}
    if attenuation.shape == (len(lats), len(lons)):
        for i in range(len(lats)):
            for j in range(len(lons)):
                key = f"({lats[i]}, {lons[j]})"
                attenuation_dict[key] = float(attenuation[i, j].value)
    else:
        raise ValueError("A dimensão do array de atenuação não corresponde ao número de latitudes e longitudes.")
    return attenuation_dict

def calculate_geodesic_bounds(lon, lat, radius_km):
    central_point = (lat, lon)
    north = geodesic(kilometers=radius_km).destination(central_point, bearing=0)
    south = geodesic(kilometers=radius_km).destination(central_point, bearing=180)
    east  = geodesic(kilometers=radius_km).destination(central_point, bearing=90)
    west  = geodesic(kilometers=radius_km).destination(central_point, bearing=270)
    return {"north": north.latitude, "south": south.latitude, "east": east.longitude, "west": west.longitude}

radii = np.array([20, 40, 60, 100, 300]).reshape(-1, 1)  # km
delta_lat = np.array([-0.002316, -0.002324, -0.005666, -0.011404, -0.034283])
delta_lon = np.array([0.006451, 0.013683, 0.018373, 0.030432, 0.090573])
model_lat = LinearRegression().fit(radii, delta_lat)
model_lon = LinearRegression().fit(radii, delta_lon)

def adjust_center(radius_km, center_lat, center_lon):
    adj_lat = model_lat.predict(np.array([[radius_km]]))[0]
    adj_lon = model_lon.predict(np.array([[radius_km]]))[0]
    scale_factor_lat = 1
    scale_factor_log = 1

    if radius_km in range(0, 21):
        scale_factor_lat = 1.9;  scale_factor_log = 0.95
    elif radius_km in range(21, 31):
        scale_factor_lat = 1.4;  scale_factor_log = 0.93
    elif radius_km in range(31, 41):
        scale_factor_lat = 1.28; scale_factor_log = 1.0
    elif radius_km in range(41, 51):
        scale_factor_lat = 1.21; scale_factor_log = 1.03
    elif radius_km in range(51, 61):
        scale_factor_lat = 1.19; scale_factor_log = .97
    elif radius_km in range(61, 71):
        scale_factor_lat = 1.17; scale_factor_log = 1.025
    elif radius_km in range(71, 101):
        scale_factor_lat = 1.1;  scale_factor_log = 1.027

    new_lat = center_lat - adj_lat*scale_factor_lat
    new_lon = center_lon - adj_lon*scale_factor_log
    return new_lat, new_lon

def determine_hgt_files(bounds):
    files_hgt = []
    lat_start = int(math.floor(bounds['south']))
    lat_end   = int(math.ceil(bounds['north']))
    lon_start = int(math.floor(bounds['west']))
    lon_end   = int(math.ceil(bounds['east']))
    for lat in range(lat_start, lat_end):
        for lon in range(lon_start, lon_end):
            lat_prefix = 'N' if lat >= 0 else 'S'
            lon_prefix = 'E' if lon >= 0 else 'W'
            filename = f"{lat_prefix}{abs(lat):02d}{lon_prefix}{abs(lon):03d}.hgt"
            files_hgt.append(filename)
    return files_hgt


def _load_antenna_patterns(user):
    if not user.antenna_pattern:
        return None, None
    file_content = user.antenna_pattern.decode('latin1', errors='ignore')
    horizontal_data, vertical_data, _ = parse_pat(file_content)
    return horizontal_data, vertical_data


def _compute_gain_components(user, hprof_cache):
    horizontal_linear, vertical_linear = _load_antenna_patterns(user)
    direction = float(user.antenna_direction or 0.0)
    tilt = float(user.antenna_tilt or 0.0)

    gain_data = {
        'horizontal_gain_grid_db': 0.0,
        'horizontal_pattern_db': None,
        'vertical_gain_grid_db': 0.0,
        'vertical_pattern_db': None,
        'vertical_horizon_db': 0.0,
    }

    if horizontal_linear is None or vertical_linear is None:
        return gain_data

    bearing_map = np.asarray(hprof_cache.get('bearing_map'))
    dist_map = np.asarray(hprof_cache.get('dist_map'))

    if bearing_map.size == 0 or dist_map.size == 0:
        return gain_data

    horizontal_linear = np.asarray(horizontal_linear, dtype=float)
    vertical_linear = np.asarray(vertical_linear, dtype=float)
    horizontal_linear = np.clip(horizontal_linear, 1e-6, None)
    vertical_linear = np.clip(vertical_linear, 1e-6, None)

    horizontal_db = 20.0 * np.log10(horizontal_linear)
    horizontal_db -= np.nanmax(horizontal_db)
    vertical_db_table = 20.0 * np.log10(vertical_linear)
    vertical_db_table -= np.nanmax(vertical_db_table)

    # -------- Horizontal pattern (azimute relativo) --------
    azimuth_deg = np.degrees(bearing_map) % 360.0
    relative_az = (azimuth_deg - direction) % 360.0
    relative_az_flat = relative_az.ravel()

    base_angles = np.arange(0, 360, dtype=float)
    horizontal_interp = np.interp(relative_az_flat, np.concatenate([base_angles, [360.0]]),
                                  np.concatenate([horizontal_db, [horizontal_db[0]]]))
    horizontal_interp = horizontal_interp.reshape(relative_az.shape)

    # -------- Vertical pattern (considera distância e tilt) --------
    # pathprof dist_map é em km
    dist_m = np.maximum(dist_map, 1e-3) * 1000.0
    tx_height_m = float(user.tower_height or 0.0)
    rx_height_m = float(user.rx_height or 0.0)
    vertical_angles = np.linspace(-90.0, 90.0, len(vertical_db_table), dtype=float)

    elevation = np.degrees(np.arctan2(rx_height_m - tx_height_m, dist_m))
    relative_el = np.clip(elevation - tilt, -90.0, 90.0)
    vertical_interp = np.interp(relative_el.ravel(), vertical_angles, vertical_db_table)
    vertical_gain_db = vertical_interp.reshape(relative_el.shape)
    horizon_delta_db = float(np.interp(np.clip(-tilt, -90.0, 90.0), vertical_angles, vertical_db_table))

    gain_data['horizontal_gain_grid_db'] = horizontal_interp
    abs_angles = np.arange(0, 360, dtype=float)
    rotated_db = np.interp((abs_angles - direction) % 360.0, base_angles, horizontal_db, period=360.0)

    gain_data['horizontal_pattern_db'] = rotated_db
    gain_data['vertical_gain_grid_db'] = vertical_gain_db
    gain_data['vertical_pattern_db'] = vertical_db_table
    gain_data['vertical_horizon_db'] = horizon_delta_db

    return gain_data


def _to_degree_array(values):
    if isinstance(values, np.ndarray):
        if hasattr(values, 'unit'):
            return values.to(u.deg).value
        return values
    arr = np.asarray([
        val.to(u.deg).value if hasattr(val, 'unit') else val
        for val in values
    ], dtype=float)
    return arr


def _determine_auto_scale(values, min_val, max_val):
    finite = np.isfinite(values)
    if not np.any(finite):
        return -110.0, -40.0

    data = values[finite]
    if min_val is None or max_val is None:
        p5, p95 = np.percentile(data, [5, 95])
        span = max(p95 - p5, 6.0)
        min_val = p5 - 0.1 * span
        max_val = p95 + 0.1 * span
    if min_val is None:
        min_val = float(np.nanmin(data))
    if max_val is None:
        max_val = float(np.nanmax(data))
    if min_val >= max_val:
        delta = abs(min_val) * 0.05 + 3.0
        min_val -= delta
        max_val += delta
    return float(min_val), float(max_val)


def _select_map_resolution(radius_km, min_arcsec=0.5, max_arcsec=20.0):
    radius_km = max(float(radius_km), 0.5)
    if radius_km <= 25:
        target_pixels = 640.0
    elif radius_km <= 80:
        target_pixels = 512.0
    else:
        target_pixels = 384.0

    km_per_degree = 111.32
    diameter_deg = max((2.0 * radius_km) / km_per_degree, 0.01)
    resolution_arcsec = (diameter_deg * 3600.0) / max(target_pixels, 256.0)
    resolution_arcsec = float(np.clip(resolution_arcsec, min_arcsec, max_arcsec))
    return resolution_arcsec * u.arcsec


def _compute_site_elevation(lat, lon):
    try:
        with pathprof.SrtmConf.set(srtm_dir='./SRTM', download='missing', server='viewpano'):
            _, _, height_map = pathprof.srtm_height_map(
                lon * u.deg,
                lat * u.deg,
                0.02 * u.deg,
                0.02 * u.deg,
                map_resolution=3 * u.arcsec,
            )
        hm = np.asarray(height_map.to(u.m).value, dtype=float)
        if hm.size == 0:
            return None
        center_idx = hm.shape[0] // 2
        return float(hm[center_idx, center_idx])
    except Exception as exc:
        current_app.logger.warning('Falha ao obter elevação SRTM: %s', exc)
        return None


def _lookup_municipality(lat, lon):
    try:
        resp = requests.get(
            'https://geocoding-api.open-meteo.com/v1/reverse',
            params={
                'latitude': lat,
                'longitude': lon,
                'count': 1,
                'language': 'pt',
                'format': 'json',
            },
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get('results') or []
        if not results:
            return None
        item = results[0]
        parts = [item.get('name'), item.get('admin1'), item.get('country')]
        formatted = ', '.join([p for p in parts if p])
        return formatted or None
    except Exception as exc:
        current_app.logger.warning('Falha na geocodificação reversa: %s', exc)
        return None


def _render_field_strength_image(lons_deg, lats_deg, field_levels,
                                 radius_km, lon_center_deg, lat_center_deg,
                                 min_val, max_val, horizontal_pattern_db,
                                 dist_map_km=None, colorbar_label='Nível de Campo [dBµV/m]'):
    lon_grid, lat_grid = np.meshgrid(lons_deg, lats_deg)
    field_plot = np.array(field_levels, copy=True)

    if dist_map_km is not None:
        dist_km = np.asarray(dist_map_km, dtype=float)
        if dist_km.shape != field_plot.shape:
            raise ValueError('dist_map_km shape mismatch with field levels grid')
    else:
        dist = np.sqrt((lon_grid - lon_center_deg) ** 2 + (lat_grid - lat_center_deg) ** 2)
        earth_radius_km = 6371.0
        dist_km = dist * (np.pi / 180.0) * earth_radius_km
    field_plot[dist_km > radius_km] = np.nan

    masked_plot = np.ma.masked_invalid(field_plot)
    base_cmap = plt.cm.get_cmap('turbo')
    try:
        cmap = base_cmap.copy()
    except AttributeError:
        cmap = ListedColormap(base_cmap(np.linspace(0, 1, base_cmap.N)))
    cmap.set_bad(alpha=0.0)

    fig, ax = plt.subplots(figsize=(6, 6))

    feather_width = max(radius_km * 0.07, 0.5)
    transition = (radius_km - dist_km) / feather_width
    alpha_mask = np.clip(transition, 0.0, 1.0)
    alpha_mask[dist_km > radius_km] = 0.0
    if np.ma.isMaskedArray(masked_plot):
        alpha_mask = np.where(masked_plot.mask, 0.0, alpha_mask)

    mesh = ax.pcolormesh(
        lon_grid,
        lat_grid,
        masked_plot,
        cmap=cmap,
        shading='auto',
        vmin=min_val,
        vmax=max_val,
        alpha=alpha_mask,
    )

    if horizontal_pattern_db is not None:
        pattern_db = np.asarray(horizontal_pattern_db, dtype=float)
        pattern_lin = np.power(10.0, np.clip(pattern_db, -60.0, 0.0) / 20.0)
        polar_dimension = min(fig.get_size_inches()) * 0.35
        inset_left = (1.0 - polar_dimension / fig.get_size_inches()[0]) * 0.5
        inset_bottom = (1.0 - polar_dimension / fig.get_size_inches()[1]) * 0.5
        ax_inset = fig.add_axes([inset_left, inset_bottom, polar_dimension / fig.get_size_inches()[0],
                                 polar_dimension / fig.get_size_inches()[1]], polar=True)
        ax_inset.set_theta_zero_location('N')
        ax_inset.set_theta_direction(-1)
        azimutes = np.linspace(0, 2 * np.pi, len(pattern_lin), endpoint=False)
        ax_inset.plot(azimutes, pattern_lin, linestyle='dashed', label='|E/Emax| (dir. atual)')
        ax_inset.set_xticks([]); ax_inset.set_yticks([])
        ax_inset.spines['polar'].set_visible(False)

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])
    ax.xaxis.label.set_visible(False); ax.yaxis.label.set_visible(False)

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', transparent=True)
    img_buffer.seek(0)
    image_base64 = base64.b64encode(img_buffer.read()).decode('utf-8')
    plt.close(fig)

    fig_cb, ax_cb = plt.subplots(figsize=(6, 1))
    plt.colorbar(mesh, cax=ax_cb, orientation='horizontal')
    ax_cb.set_title(colorbar_label)
    fig_cb.tight_layout()
    cb_buffer = io.BytesIO()
    fig_cb.savefig(cb_buffer, format='png', transparent=True)
    cb_buffer.seek(0)
    colorbar_base64 = base64.b64encode(cb_buffer.read()).decode('utf-8')
    plt.close(fig_cb)

    return image_base64, colorbar_base64


def _persist_coverage_artifacts(user, project, engine_value, request_payload, coverage_payload):
    if project is None:
        return None

    engine_enum = CoverageEngine(engine_value)
    timestamp = datetime.utcnow()
    timestamp_iso = timestamp.isoformat()
    base_name = f"coverage_{timestamp.strftime('%Y%m%d_%H%M%S')}_{engine_enum.value}"

    def _json_default(obj):
        if isinstance(obj, (np.floating, float)):
            return float(obj)
        if isinstance(obj, (np.integer, int)):
            return int(obj)
        if isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        return str(obj)

    def _clean_json(data):
        if data is None:
            return None
        try:
            return json.loads(json.dumps(data, default=_json_default))
        except TypeError:
            return data

    storage_paths = ensure_storage_structure(str(user.uuid), project.slug)
    coverage_dir = storage_paths.get('assets/coverage')
    if coverage_dir is None:
        coverage_dir = storage_root() / str(user.uuid) / project.slug / 'assets' / 'coverage'
        coverage_dir.mkdir(parents=True, exist_ok=True)

    root_path = storage_root()

    def _decode_image_b64(data_str):
        if not data_str:
            return b''
        return base64.b64decode(data_str)

    img_dbuv_b64 = coverage_payload.get('images', {}).get('dbuv', {}).get('image')
    colorbar_b64 = coverage_payload.get('images', {}).get('dbuv', {}).get('colorbar')

    heatmap_bytes = _decode_image_b64(img_dbuv_b64)
    colorbar_bytes = _decode_image_b64(colorbar_b64)

    heatmap_path = coverage_dir / f"{base_name}_field.png"
    colorbar_path = coverage_dir / f"{base_name}_colorbar.png"
    json_path = coverage_dir / f"{base_name}_summary.json"

    if heatmap_bytes:
        heatmap_path.write_bytes(heatmap_bytes)
    if colorbar_bytes:
        colorbar_path.write_bytes(colorbar_bytes)

    summary_payload = {
        "engine": engine_enum.value,
        "generated_at": timestamp_iso,
        "request": _clean_json(request_payload),
        "center_metrics": _clean_json(coverage_payload.get('center_metrics')),
        "loss_components": _clean_json(coverage_payload.get('loss_components')),
        "bounds": _clean_json(coverage_payload.get('bounds')),
        "colorbar_bounds": _clean_json(coverage_payload.get('colorbar_bounds')),
        "scale": _clean_json(coverage_payload.get('scale')),
        "tx_location": _clean_json(coverage_payload.get('center')),
    }
    json_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2, default=_json_default))

    heatmap_asset = Asset(
        project_id=project.id,
        type=AssetType.heatmap,
        path=str(heatmap_path.relative_to(root_path)),
        mime_type='image/png',
        byte_size=heatmap_path.stat().st_size if heatmap_path.exists() else 0,
        meta={
            "engine": engine_enum.value,
            "generated_at": timestamp_iso,
            "unit": coverage_payload.get('images', {}).get('dbuv', {}).get('unit'),
            "radius_km": coverage_payload.get('requested_radius_km'),
        },
    )
    db.session.add(heatmap_asset)

    json_asset = Asset(
        project_id=project.id,
        type=AssetType.json,
        path=str(json_path.relative_to(root_path)),
        mime_type='application/json',
        byte_size=json_path.stat().st_size if json_path.exists() else 0,
        meta={
            "engine": engine_enum.value,
            "generated_at": timestamp_iso,
        },
    )
    db.session.add(json_asset)

    colorbar_asset = None
    if colorbar_bytes:
        colorbar_asset = Asset(
            project_id=project.id,
            type=AssetType.png,
            path=str(colorbar_path.relative_to(root_path)),
            mime_type='image/png',
            byte_size=colorbar_path.stat().st_size if colorbar_path.exists() else 0,
            meta={
                "engine": engine_enum.value,
                "generated_at": timestamp_iso,
                "label": coverage_payload.get('images', {}).get('dbuv', {}).get('label'),
            },
        )
        db.session.add(colorbar_asset)

    db.session.flush()

    job = CoverageJob(
        project_id=project.id,
        status=CoverageStatus.succeeded,
        engine=engine_enum,
        inputs={
            "request": request_payload,
            "project_settings": _clean_json(project.settings),
        },
        metrics={
            "center_metrics": _clean_json(coverage_payload.get('center_metrics')),
            "loss_components": _clean_json(coverage_payload.get('loss_components')),
        },
        outputs_asset_id=heatmap_asset.id,
        started_at=timestamp,
        finished_at=timestamp,
    )
    db.session.add(job)

    settings = project.settings or {}
    last_coverage = {
        "generated_at": timestamp_iso,
        "engine": engine_enum.value,
        "asset_id": str(heatmap_asset.id),
        "asset_path": heatmap_asset.path,
        "json_asset_id": str(json_asset.id),
        "radius_km": coverage_payload.get('requested_radius_km'),
        "center_metrics": _clean_json(coverage_payload.get('center_metrics')),
    }
    if colorbar_asset:
        last_coverage["colorbar_asset_id"] = str(colorbar_asset.id)

    settings['lastCoverage'] = last_coverage
    project.settings = settings

    return {
        "heatmap_asset": heatmap_asset,
        "json_asset": json_asset,
        "colorbar_asset": colorbar_asset,
        "job": job,
        "timestamp": timestamp_iso,
    }
def _compute_coverage_map(tx, data, include_arrays=False, label=None):
    """
    Gera todos os artefatos de cobertura (heatmap, barra de cores, metadados)
    em formato compatível com mapa.js / generateCoverage() / applyCoverageOverlay().

    tx   -> objeto "transmissor" (ex: current_user)
    data -> payload JSON vindo do front (radius, min/max escala, customCenter ...)
    """

    # -------------------------------------------------
    # helpers internos
    # -------------------------------------------------
    def _coerce_optional(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        value_str = str(value).strip()
        if not value_str:
            return None
        try:
            return float(value_str)
        except ValueError:
            return None

    def _determine_auto_scale_local(arr, user_min, user_max):
        """
        Decide faixa de cores.
        Se user_min/max vierem, respeita.
        Caso contrário usa min/max dos valores finitos.
        Garante que vmax > vmin.
        """
        arr_np = np.asarray(arr, dtype=float)
        finite_vals = arr_np[np.isfinite(arr_np)]
        if finite_vals.size == 0:
            # fallback qualquer para não quebrar
            return (0.0, 1.0)

        auto_min = float(np.nanmin(finite_vals))
        auto_max = float(np.nanmax(finite_vals))

        vmin = float(user_min) if user_min is not None else auto_min
        vmax = float(user_max) if user_max is not None else auto_max

        if abs(vmax - vmin) < 1e-9:
            vmax = vmin + 1.0

        return (vmin, vmax)

    def _safe_value_at_center(arr, center_idx):
        """
        Extrai um valor "representativo" de um array (2D normalmente),
        tentando pegar no índice [lat, lon] mais próximo do TX.
        """
        arr_np = np.asarray(arr, dtype=float)
        try:
            return float(arr_np[center_idx])
        except Exception:
            # se for escalar
            if np.ndim(arr_np) == 0:
                return float(arr_np)
            finite_mask = np.isfinite(arr_np)
            if np.any(finite_mask):
                return float(np.nanmean(arr_np[finite_mask]))
            return None

    def _summarize_component(arr, center_idx):
        """
        min, max e valor central (dB) de um mapa de perdas.
        """
        arr_np = np.asarray(arr, dtype=float)
        finite_mask = np.isfinite(arr_np)
        if not np.any(finite_mask):
            return None
        out = {
            'min': float(np.nanmin(arr_np)),
            'max': float(np.nanmax(arr_np)),
            'unit': 'dB',
        }
        try:
            out['center'] = float(arr_np[center_idx])
        except Exception:
            out['center'] = float(np.nanmean(arr_np[finite_mask]))
        return out

    def adjust_center(radius_km, center_lat, center_lon):
        """
        Corrige o centro do raster em função do raio, para compensar
        o desalinhamento visual do GroundOverlay no Google Maps.

        Usa dois modelos regressivos (model_lat, model_lon) que estimam
        o quanto precisamos deslocar em graus, e depois aplica fatores
        empíricos diferentes por faixa de raio.

        Se os modelos não existirem ou der erro -> fallback = sem ajuste.
        """
        # fallback (sem ajuste)
        base_adj_lat = 0.0
        base_adj_lon = 0.0

        try:
            # os modelos esperam [[raio]]
            base_adj_lat = float(model_lat.predict(np.array([[radius_km]], dtype=float))[0])
            base_adj_lon = float(model_lon.predict(np.array([[radius_km]], dtype=float))[0])
        except Exception:
            # sem modelo treinado disponível? não quebra.
            base_adj_lat = 0.0
            base_adj_lon = 0.0

        # fatores empíricos
        if radius_km < 21:
            scale_factor_lat = 1.90
            scale_factor_lon = 0.95
        elif radius_km < 31:
            scale_factor_lat = 1.40
            scale_factor_lon = 0.93
        elif radius_km < 41:
            scale_factor_lat = 1.28
            scale_factor_lon = 1.00
        elif radius_km < 51:
            scale_factor_lat = 1.21
            scale_factor_lon = 1.03
        elif radius_km < 61:
            scale_factor_lat = 1.19
            scale_factor_lon = 0.97
        elif radius_km < 71:
            scale_factor_lat = 1.17
            scale_factor_lon = 1.025
        elif radius_km < 101:
            scale_factor_lat = 1.10
            scale_factor_lon = 1.027
        else:
            # acima de 100 km ainda não calibrado -> último conhecido
            scale_factor_lat = 1.10
            scale_factor_lon = 1.027

        # aplica deslocamento (mesma lógica que você mandou: center - adj*scale)
        new_lat = center_lat - base_adj_lat * scale_factor_lat
        new_lon = center_lon - base_adj_lon * scale_factor_lon

        return float(new_lat), float(new_lon)

    # -------------------------------------------------
    # 1. PARÂMETROS DO TX / AMBIENTE / UI
    # -------------------------------------------------

    # perdas fixas sistêmicas (cabos, conectores) [dB]
    loss_sys_db = tx.total_loss or 0.0

    # potência transmitida [W] (evitar log(0))
    Ptx_W = max(float(tx.transmission_power or 0.0), 1e-6)

    # ganho nominal de pico da antena TX [dBi]
    Gtx_peak_dBi = tx.antenna_gain or 0.0

    # ganho da RX [dBi]
    Grx_dBi = tx.rx_gain or 0.0

    # override de centro vindo do front (posição "real"/visível da TX)
    center_override = data.get('customCenter') or {}
    try:
        lon_tx_deg = float(center_override.get('lng', tx.longitude))
        lat_tx_deg = float(center_override.get('lat', tx.latitude))
    except (TypeError, ValueError):
        lon_tx_deg, lat_tx_deg = tx.longitude, tx.latitude

    # raio solicitado [km]
    radius_requested = _coerce_optional(data.get('radius'))
    if radius_requested is None or radius_requested <= 0:
        radius_requested = 10.0
    radius_km = float(radius_requested)

    # >>> AQUI entra o teu ajuste empírico
    lat_ref_deg, lon_ref_deg = adjust_center(radius_km, lat_tx_deg, lon_tx_deg)

    # esses são os centros que vamos usar pro cálculo SRTM / pycraf
    lat_ref = lat_ref_deg * u.deg
    lon_ref = lon_ref_deg * u.deg

    # frequência (MHz → GHz p/ pycraf)
    freq_mhz = getattr(tx, 'frequencia', None) or 100.0
    if freq_mhz < 100.0:
        freq_mhz = 100.0
    frequency = (freq_mhz / 1000.0) * u.GHz  # pycraf usa GHz

    # alturas TX / RX acima do solo
    rx_height_m = tx.rx_height if tx.rx_height is not None else 1.0
    tx_height_m = tx.tower_height if tx.tower_height is not None else 30.0
    h_rx = rx_height_m * u.m
    h_tx = tx_height_m * u.m

    # porcentagem de tempo P.452 (p%)
    time_pct = tx.time_percentage if getattr(tx, 'time_percentage', None) else 40.0
    time_pct = max(0.001, min(float(time_pct), 50.0))
    timepercent = time_pct * u.percent  # unidade correta pro pycraf

    # polarização
    pol = (getattr(tx, 'polarization', None) or 'vertical').lower()
    polarization = 1 if pol == 'vertical' else 0

    # versão P.452
    version = getattr(tx, 'p452_version', None) or 16
    if version not in (14, 16):
        version = 16

    # escala manual de cores (UI)
    min_valu = _coerce_optional(data.get('minSignalLevel'))
    max_valu = _coerce_optional(data.get('maxSignalLevel'))

    # resolução do grid em função do raio
    map_resolution = _select_map_resolution(radius_km)

    # bounding box geodésico aproximado só pra recortar SRTM
    # IMPORTANTE: usamos o centro AJUSTADO aqui, pois é ele que vamos
    # realmente rasterizar.
    bounds_hint = calculate_geodesic_bounds(lon_ref_deg, lat_ref_deg, radius_km)

    def _span_deg(a, b):
        span = abs(float(a) - float(b))
        if span > 180.0:
            span = 360.0 - span
        return max(span, 1e-6)

    pad_factor = 1.05
    span_lon = _span_deg(bounds_hint['east'], bounds_hint['west']) * pad_factor
    span_lat = _span_deg(bounds_hint['north'], bounds_hint['south']) * pad_factor
    map_size_lon = span_lon * u.deg
    map_size_lat = span_lat * u.deg

    # condições atmosféricas
    temperature_k = tx.temperature_k if getattr(tx, 'temperature_k', None) else 293.15
    pressure_hpa  = tx.pressure_hpa  if getattr(tx, 'pressure_hpa', None)  else 1013.0
    water_density = tx.water_density if getattr(tx, 'water_density', None) else 7.5
    if water_density is None or (isinstance(water_density, float) and math.isnan(water_density)):
        water_density = 7.5

    temperature = temperature_k * u.K
    pressure    = pressure_hpa * u.hPa

    # tipo de clutter (ambiente)
    modelo = getattr(tx, 'propagation_model', None)
    if modelo == 'modelo1':
        zone_t, zone_r = pathprof.CLUTTER.URBAN, pathprof.CLUTTER.URBAN
    elif modelo == 'modelo2':
        zone_t, zone_r = pathprof.CLUTTER.SUBURBAN, pathprof.CLUTTER.SUBURBAN
    elif modelo == 'modelo3':
        zone_t, zone_r = pathprof.CLUTTER.TROPICAL_FOREST, pathprof.CLUTTER.TROPICAL_FOREST
    elif modelo == 'modelo4':
        zone_t, zone_r = pathprof.CLUTTER.CONIFEROUS_TREES, pathprof.CLUTTER.CONIFEROUS_TREES
    else:
        zone_t, zone_r = pathprof.CLUTTER.UNKNOWN, pathprof.CLUTTER.UNKNOWN

    # -------------------------------------------------
    # 2. GERA GRID DE TERRENO + ATENUAÇÃO P.452
    #     (usando o centro AJUSTADO!)
    # -------------------------------------------------
    with pathprof.SrtmConf.set(
        srtm_dir='./SRTM',
        download='missing',
        server='viewpano'
    ):
        hprof_cache = pathprof.height_map_data(
            lon_ref,
            lat_ref,
            map_size_lon,
            map_size_lat,
            map_resolution=map_resolution,
            zone_t=zone_t,
            zone_r=zone_r,
        )

    results = pathprof.atten_map_fast(
        freq=frequency,
        temperature=temperature,
        pressure=pressure,
        h_tg=h_tx,
        h_rg=h_rx,
        timepercent=timepercent,
        hprof_data=hprof_cache,
        polarization=polarization,
        version=version,
        base_water_density=(water_density if water_density is not None else 7.5) * u.g / u.m**3
    )

    # vetores 1D de coordenadas (centros de pixel) do RASTER AJUSTADO
    _lons = hprof_cache['xcoords']
    _lats = hprof_cache['ycoords']

    # -------------------------------------------------
    # 3. MAPAS DE PERDA
    # -------------------------------------------------
    loss_maps = {}
    for key in ('L_b0p', 'L_bd', 'L_bs', 'L_ba', 'L_b', 'L_b_corr'):
        if key in results and results[key] is not None:
            try:
                loss_maps[key] = results[key].to(u.dB).value
            except Exception:
                loss_maps[key] = np.asarray(results[key], dtype=float)

    if 'L_b_corr' in loss_maps:
        combined_loss_map = loss_maps['L_b_corr']
    elif 'L_b' in loss_maps:
        combined_loss_map = loss_maps['L_b']
    else:
        combined_loss_map = results['L_b'].to(u.dB).value

    total_path_loss_db = np.asarray(combined_loss_map, dtype=float)
    _total_atten = u.Quantity(total_path_loss_db, u.dB)

    # -------------------------------------------------
    # 4. AJUSTE DE DIMENSÃO (garante [nlat, nlon])
    # -------------------------------------------------
    lons_deg = np.asarray(_to_degree_array(_lons), dtype=float)
    lats_deg = np.asarray(_to_degree_array(_lats), dtype=float)

    if lons_deg.ndim == 2:
        lons_deg = lons_deg[0, :]
    else:
        lons_deg = lons_deg.ravel()
    if lats_deg.ndim == 2:
        lats_deg = lats_deg[:, 0]
    else:
        lats_deg = lats_deg.ravel()

    nlon = int(lons_deg.size)
    nlat = int(lats_deg.size)

    # Se a matriz veio (nlon, nlat), transpõe pra (nlat, nlon).
    if total_path_loss_db.shape == (nlon, nlat):
        total_path_loss_db = total_path_loss_db.T
        _total_atten = u.Quantity(total_path_loss_db, u.dB)
    elif total_path_loss_db.shape != (nlat, nlon):
        # fallback: tenta a transposta
        if total_path_loss_db.T.shape == (nlat, nlon):
            total_path_loss_db = total_path_loss_db.T
            _total_atten = u.Quantity(total_path_loss_db, u.dB)
        # se ainda não bateu, seguimos assim mesmo

    # tamanhos angulares médios por pixel (pra calcular bounds com meia célula)
    if lons_deg.size > 1:
        dlon = float(np.median(np.abs(np.diff(lons_deg))))
    else:
        dlon = 0.0
    if lats_deg.size > 1:
        dlat = float(np.median(np.abs(np.diff(lats_deg))))
    else:
        dlat = 0.0

    # -------------------------------------------------
    # 5. PADRÃO DE ANTENA / CORREÇÃO DE ORIENTAÇÃO (+90°)
    # -------------------------------------------------
    gain_comp_raw = _compute_gain_components(tx, hprof_cache)

    horiz_grid = gain_comp_raw['horizontal_gain_grid_db']
    vert_grid  = gain_comp_raw['vertical_gain_grid_db']

    def _coerce_gain_grid(arr, target_shape):
        """
        Garante que horiz_grid / vert_grid tenham shape (nlat, nlon)
        e possam somar com total_path_loss_db.
        """
        if np.isscalar(arr) or arr is None:
            return np.zeros(target_shape, dtype=float)

        a = np.asarray(arr, dtype=float)

        if a.shape == target_shape:
            return a

        if a.shape == (target_shape[1], target_shape[0]):
            return a.T

        if a.ndim == 1:
            # broadcast linha/coluna
            if a.size == target_shape[1]:
                return np.tile(a, (target_shape[0], 1))
            if a.size == target_shape[0]:
                return np.tile(a[:, None], (1, target_shape[1]))

        try:
            return a.reshape(target_shape)
        except Exception:
            return np.zeros(target_shape, dtype=float)

    horiz_grid = _coerce_gain_grid(horiz_grid, total_path_loss_db.shape)
    vert_grid  = _coerce_gain_grid(vert_grid,  total_path_loss_db.shape)

    # correção de +90° no padrão (offset entre diagrama e mapa):
    # rotaciona ambos 90° horário (np.rot90(..., k=3))
    if horiz_grid.shape == vert_grid.shape and horiz_grid.shape[0] == horiz_grid.shape[1]:
        horiz_grid = np.rot90(horiz_grid, k=3)
        vert_grid  = np.rot90(vert_grid,  k=3)

    # -------------------------------------------------
    # 6. LINK BUDGET (Friis em dB) E CAMPO ELÉTRICO
    # -------------------------------------------------
    # Ptx em dBm
    Ptx_dBm = 10.0 * math.log10(Ptx_W / 0.001)

    # ganho TX efetivo por pixel
    Gtx_eff_db = (
        float(Gtx_peak_dBi)
        + horiz_grid
        + vert_grid
    )

    # potência recebida estimada no conector RX [dBm]:
    # Prx = Ptx_dBm + Gtx_eff + Grx_dBi - loss_sys - L_path
    Prx_dbm = (
        Ptx_dBm
        + Gtx_eff_db
        + float(Grx_dBi)
        - float(loss_sys_db)
        - total_path_loss_db
    )
    Prx_dbm = np.asarray(Prx_dbm, dtype=float)

    # campo elétrico equivalente [dBµV/m]
    # E = Prx(dBm) - Grx(dBi) + 77.2 + 20log10(f_MHz)
    freq_mhz_safe = max(float(freq_mhz), 0.1)
    E_dbuv = (
        Prx_dbm
        - float(Grx_dBi)
        + 77.2
        + 20.0 * np.log10(freq_mhz_safe)
    )
    E_dbuv = np.asarray(E_dbuv, dtype=float)

    # -------------------------------------------------
    # 7. MÁSCARA CIRCULAR (preencher TODO o disco)
    #    IMPORTANTE: o círculo é em torno da TX REAL (lat_tx_deg/lon_tx_deg),
    #    não do centro ajustado.
    # -------------------------------------------------
    lon_grid, lat_grid = np.meshgrid(lons_deg, lats_deg)

    def _haversine_km(lat1, lon1, lat2, lon2):
        R = 6371.0  # km
        lat1r = np.radians(lat1)
        lon1r = np.radians(lon1)
        lat2r = np.radians(lat2)
        lon2r = np.radians(lon2)
        dlat  = lat2r - lat1r
        dlon  = lon2r - lon1r
        a = (
            np.sin(dlat / 2.0) ** 2
            + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
        )
        return 2.0 * R * np.arcsin(np.sqrt(a))

    dist_km_grid = _haversine_km(lat_grid, lon_grid, lat_tx_deg, lon_tx_deg)
    inrange_mask = dist_km_grid <= radius_km

    # inicializa com NaN
    E_plot   = np.full_like(E_dbuv, np.nan, dtype=float)
    Prx_plot = np.full_like(Prx_dbm, np.nan, dtype=float)

    # mantém apenas dentro do raio
    E_plot[inrange_mask]   = E_dbuv[inrange_mask]
    Prx_plot[inrange_mask] = Prx_dbm[inrange_mask]

    # preencher buracos NaN DENTRO do raio com valor mínimo dentro do raio
    def _fill_holes(mask_in, arr_plot):
        vals = arr_plot[mask_in & np.isfinite(arr_plot)]
        if vals.size > 0:
            fill_val = float(np.nanmin(vals))
            hole_mask = mask_in & ~np.isfinite(arr_plot)
            arr_plot[hole_mask] = fill_val
        return arr_plot

    E_plot   = _fill_holes(inrange_mask, E_plot)
    Prx_plot = _fill_holes(inrange_mask, Prx_plot)

    # -------------------------------------------------
    # 8. ESCALA DE CORES
    # -------------------------------------------------
    min_val, max_val = _determine_auto_scale_local(E_plot, min_valu, max_valu)
    if min_valu is None and max_valu is None:
        if (not np.isfinite(min_val)) or (not np.isfinite(max_val)):
            min_val, max_val = 10.0, 60.0

    power_min, power_max = _determine_auto_scale_local(Prx_plot, None, None)

    # -------------------------------------------------
    # 9. ENCONTRAR ÍNDICE DO PIXEL MAIS PRÓXIMO DO TX REAL
    #    (pra summaries e painéis do front)
    # -------------------------------------------------
    lat_diff = np.abs(lats_deg - lat_tx_deg)
    lon_diff = np.abs(lons_deg - lon_tx_deg)
    center_idx_lat = int(np.argmin(lat_diff))
    center_idx_lon = int(np.argmin(lon_diff))
    center_idx = (center_idx_lat, center_idx_lon)

    # -------------------------------------------------
    # 10. BOUNDS DO OVERLAY
    #     usamos a grade AJUSTADA (lat_ref_deg/lon_ref_deg),
    #     sem mais delta sub-pixel. Só expandimos meia célula.
    # -------------------------------------------------
    lat_min_center = float(np.nanmin(lats_deg))
    lat_max_center = float(np.nanmax(lats_deg))
    lon_min_center = float(np.nanmin(lons_deg))
    lon_max_center = float(np.nanmax(lons_deg))

    south_edge = lat_min_center - dlat / 2.0
    north_edge = lat_max_center + dlat / 2.0
    west_edge  = lon_min_center - dlon / 2.0
    east_edge  = lon_max_center + dlon / 2.0

    bounds = {
        'north': north_edge,
        'south': south_edge,
        'east':  east_edge,
        'west':  west_edge,
    }

    lat_span = max(bounds['north'] - bounds['south'], 1e-6)
    colorbar_height = max(lat_span * 0.05, 1e-4)
    colorbar_bounds = {
        'north': bounds['north'],
        'south': bounds['north'] - colorbar_height,
        'east':  bounds['east'],
        'west':  bounds['west'],
    }

    # -------------------------------------------------
    # 11. STATUS CLIMÁTICO / MÉTRICAS DO CENTRO
    # -------------------------------------------------
    climate_lat = getattr(tx, 'climate_lat', None)
    climate_lon = getattr(tx, 'climate_lon', None)
    location_changed = True
    if climate_lat is not None and climate_lon is not None:
        dlat_check = abs(float(climate_lat) - lat_tx_deg)
        dlon_check = abs(float(climate_lon) - lon_tx_deg)
        location_changed = max(dlat_check, dlon_check) > 1e-4

    if location_changed:
        location_status = (
            'A localização da TX mudou desde o último ajuste climático. '
            'Atualize as condições atmosféricas para refletir o novo município.'
        )
    else:
        if getattr(tx, 'climate_updated_at', None):
            location_status = (
                f"Localização inalterada desde "
                f"{tx.climate_updated_at.strftime('%d/%m/%Y %H:%M UTC')}"
            )
        else:
            location_status = (
                'Localização confirmada. Ajuste climático ainda não foi registrado para este ponto.'
            )

    # path_type (LoS, ducting etc.) no ponto central
    path_type_info = results.get('path_type')
    path_type_value = None
    if path_type_info is not None:
        try:
            if hasattr(path_type_info, '__getitem__'):
                ptv = path_type_info[center_idx]
            else:
                ptv = path_type_info
            if isinstance(ptv, bytes):
                ptv = ptv.decode('utf-8', errors='ignore')
            path_type_value = str(ptv)
        except Exception:
            path_type_value = None

    loss_components_summary = {}
    for k, arr in loss_maps.items():
        s = _summarize_component(arr, center_idx)
        if s:
            loss_components_summary[k] = s

    center_metrics = {
        'path_type': path_type_value,
        'combined_loss_center_db': _safe_value_at_center(total_path_loss_db, center_idx),
        'received_power_center_dbm': _safe_value_at_center(Prx_dbm, center_idx),
        'field_center_dbuv_m': _safe_value_at_center(E_dbuv, center_idx),
        'effective_gain_center_db': _safe_value_at_center(Gtx_eff_db, center_idx),
        'tx_power_dbm': float(Ptx_dBm),
        'system_losses_db': float(loss_sys_db),
        'frequency_mhz': float(freq_mhz),
        'radius_km': float(radius_km),
    }

    try:
        center_metrics['distance_center_km'] = float(dist_km_grid[center_idx])
    except Exception:
        pass

    # -------------------------------------------------
    # 12. IMAGENS (heatmap/base64) p/ overlay e barra
    # -------------------------------------------------
    img_dbuv_b64, colorbar_dbuv_b64 = _render_field_strength_image(
        lons_deg,
        lats_deg,
        E_plot,
        radius_km,
        lon_tx_deg,
        lat_tx_deg,
        min_val,
        max_val,
        gain_comp_raw['horizontal_pattern_db'],
        dist_map_km=dist_km_grid,
        colorbar_label='Campo elétrico [dBµV/m]'
    )

    img_dbm_b64, colorbar_dbm_b64 = _render_field_strength_image(
        lons_deg,
        lats_deg,
        Prx_plot,
        radius_km,
        lon_tx_deg,
        lat_tx_deg,
        power_min,
        power_max,
        gain_comp_raw['horizontal_pattern_db'],
        dist_map_km=dist_km_grid,
        colorbar_label='Potência recebida [dBm]'
    )

    # -------------------------------------------------
    # 13. DICIONÁRIOS DE NÍVEL DE CAMPO (p/ clique RX)
    # -------------------------------------------------
    signal_level_dict = {}
    signal_level_dict_dbm = {}

    if E_plot.shape == (len(lats_deg), len(lons_deg)):
        for i, lat_val in enumerate(lats_deg):
            for j, lon_val in enumerate(lons_deg):
                if not inrange_mask[i, j]:
                    continue
                if np.isfinite(E_dbuv[i, j]):
                    signal_level_dict[f"({lat_val}, {lon_val})"] = float(E_dbuv[i, j])
                if np.isfinite(Prx_dbm[i, j]):
                    signal_level_dict_dbm[f"({lat_val}, {lon_val})"] = float(Prx_dbm[i, j])

    # -------------------------------------------------
    # 14. GAIN COMPONENTS (interface com updateGainSummary no front)
    # -------------------------------------------------
    if np.isfinite(horiz_grid).any():
        horiz_min = float(np.nanmin(horiz_grid))
        horiz_max = float(np.nanmax(horiz_grid))
    else:
        horiz_min = 0.0
        horiz_max = 0.0

    vert_center = _safe_value_at_center(vert_grid, center_idx)
    if vert_center is None or not np.isfinite(vert_center):
        vert_center = 0.0

    gain_components_payload = {
        "base_gain_dbi": float(Gtx_peak_dBi),
        "horizontal_adjustment_db_min": horiz_min,
        "horizontal_adjustment_db_max": horiz_max,
        "vertical_adjustment_db": float(vert_center),
        "horizontal_pattern_db": (
            gain_comp_raw['horizontal_pattern_db'].tolist()
            if gain_comp_raw.get('horizontal_pattern_db') is not None and include_arrays
            else None
        ),
        "vertical_pattern_db": (
            gain_comp_raw['vertical_pattern_db'].tolist()
            if gain_comp_raw.get('vertical_pattern_db') is not None and include_arrays
            else None
        ),
        "vertical_horizon_db": gain_comp_raw.get('vertical_horizon_db'),
    }

    # -------------------------------------------------
    # 15. OBJETO FINAL (compatível com mapa.js)
    # -------------------------------------------------
    payload = {
        "images": {
            "dbuv": {
                "image": img_dbuv_b64,
                "colorbar": colorbar_dbuv_b64,
                "label": "Campo elétrico [dBµV/m]",
                "unit": "dBµV/m",
            },
            "dbm": {
                "image": img_dbm_b64,
                "colorbar": colorbar_dbm_b64,
                "label": "Potência recebida [dBm]",
                "unit": "dBm",
            },
        },

        # bounds agora vêm da malha calculada em torno do centro AJUSTADO
        # (ou seja, já com o deslocamento empírico por raio)
        "bounds": bounds,
        "colorbar_bounds": colorbar_bounds,

        "scale": {
            "default_unit": "dbuv",
            "min": min_val,
            "max": max_val,
            "units": {
                "dbuv": {"min": min_val, "max": max_val},
                "dbm": {"min": power_min, "max": power_max},
            },
        },

        # AQUI mandamos a posição REAL da TX (marcador vermelho),
        # pra desenhar o círculo azul e pra atualizar o painel.
        "center": {"lat": float(lat_tx_deg), "lng": float(lon_tx_deg)},
        "requested_radius_km": radius_km,

        "location_status": location_status,
        "location_changed": location_changed,
        "tx_location_name": getattr(tx, 'tx_location_name', None),
        "tx_site_elevation": getattr(tx, 'tx_site_elevation', None),
        "climate_updated_at": tx.climate_updated_at.isoformat()
            if getattr(tx, 'climate_updated_at', None) else None,

        # usado no front para desenhar a linha de azimute (refreshDirectionGuide)
        "antenna_direction": getattr(tx, 'antenna_direction', None),

        # resumo de ganho usado em updateGainSummary()
        "gain_components": gain_components_payload,

        "loss_components": loss_components_summary,
        "center_metrics": center_metrics,

        # usado por computeReceiverSummary() pra estimar o nível no RX clicado
        "signal_level_dict": signal_level_dict,
        "signal_level_dict_dbm": signal_level_dict_dbm,
    }

    if label is not None:
        payload["label"] = str(label)

    return payload





@bp.route('/calculate-coverage', methods=['POST'])
@login_required
def calculate_coverage():
    data = request.get_json() or {}
    project_slug = data.get('projectSlug') or data.get('project_slug')
    project = None
    if project_slug:
        project = project_by_slug_or_404(project_slug, current_user.uuid)

    engine_value = data.get('coverageEngine') or CoverageEngine.p1546.value
    if engine_value not in {engine.value for engine in CoverageEngine}:
        engine_value = CoverageEngine.p1546.value

    result = _compute_coverage_map(current_user, data)

    persisted = None
    try:
        persisted = _persist_coverage_artifacts(current_user, project, engine_value, data, result)
        db.session.commit()
    except Exception as exc:
        current_app.logger.exception('Falha ao persistir artefatos de cobertura: %s', exc)
        db.session.rollback()
    else:
        if persisted:
            result.setdefault('assets', {})['heatmap'] = {
                'id': str(persisted['heatmap_asset'].id),
                'path': persisted['heatmap_asset'].path,
            }
            result['coverage_job_id'] = str(persisted['job'].id)
            result['generated_at'] = persisted['timestamp']
            if project:
                result['project_slug'] = project.slug

    return jsonify(result)




@bp.route('/tx-location', methods=['POST'])
@login_required
def atualizar_localizacao_tx():
    data = request.get_json() or {}
    try:
        lat = float(data.get('latitude'))
        lon = float(data.get('longitude'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Coordenadas inválidas.'}), 400

    user = User.query.get(current_user.id)
    if not user:
        return jsonify({'error': 'Usuário não encontrado.'}), 404

    user.latitude = lat
    user.longitude = lon

    municipality = _lookup_municipality(lat, lon)
    elevation = _compute_site_elevation(lat, lon)

    if municipality:
        user.tx_location_name = municipality
    if elevation is not None:
        user.tx_site_elevation = elevation

    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500

    return jsonify({
        'municipality': user.tx_location_name,
        'elevation': user.tx_site_elevation,
    }), 200

@bp.route('/clima-recomendado', methods=['GET'])
@login_required
def clima_recomendado():
    user = User.query.get(current_user.id)
    if not user or user.latitude is None or user.longitude is None:
        return jsonify({'error': 'Latitude/longitude não definidos. Informe a posição da TX primeiro.'}), 400

    lat = float(user.latitude)
    lon = float(user.longitude)
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=360)

    params = {
        'latitude': lat,
        'longitude': lon,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'daily': 'temperature_2m_mean,relative_humidity_2m_mean,surface_pressure_mean',
        'timezone': 'UTC',
    }
    try:
        resp = requests.get('https://archive-api.open-meteo.com/v1/archive', params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        current_app.logger.warning('Falha ao consultar Open-Meteo: %s', exc)
        return jsonify({'error': 'Não foi possível obter dados climáticos.'}), 502

    daily = payload.get('daily', {})
    temps = daily.get('temperature_2m_mean') or []
    humidity = daily.get('relative_humidity_2m_mean') or []
    pressure = daily.get('surface_pressure_mean') or []

    def _safe_mean(seq):
        values = [float(v) for v in seq if v is not None]
        return float(np.mean(values)) if values else None

    avg_temp = _safe_mean(temps)
    avg_humidity = _safe_mean(humidity)
    avg_pressure = _safe_mean(pressure)

    if avg_temp is None:
        avg_temp = 20.0
    if avg_humidity is None:
        avg_humidity = 70.0
    if avg_pressure is None:
        avg_pressure = 1013.0

    temp_c = avg_temp
    rh = max(0.0, min(avg_humidity, 100.0))

    # densidade de vapor diário, depois média anual
    abs_samples = []
    for t, rel in zip(temps, humidity):
        if t is None or rel is None:
            continue
        rel = max(0.0, min(float(rel), 100.0))
        saturation_vapor_pressure = 6.112 * math.exp((17.67 * t) / (t + 243.5))
        actual_vapor_pressure = (rel / 100.0) * saturation_vapor_pressure
        abs_samples.append(216.7 * (actual_vapor_pressure / (t + 273.15)))

    if abs_samples:
        absolute_humidity = float(np.mean(abs_samples))
    else:
        saturation_vapor_pressure = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
        actual_vapor_pressure = (rh / 100.0) * saturation_vapor_pressure
        absolute_humidity = 216.7 * (actual_vapor_pressure / (temp_c + 273.15))

    user.temperature_k = temp_c + 273.15
    user.pressure_hpa = avg_pressure
    user.water_density = absolute_humidity
    user.climate_lat = lat
    user.climate_lon = lon
    user.climate_updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'temperature': round(temp_c, 2),
        'pressure': round(avg_pressure, 1),
        'relativeHumidity': round(rh, 1),
        'waterDensity': round(max(0.0, absolute_humidity), 2),
        'daysSampled': len(temps),
        'municipality': user.tx_location_name,
        'climateUpdatedAt': user.climate_updated_at.isoformat() if user.climate_updated_at else None,
    })

@bp.route('/visualizar-dados-salvos')
@login_required
def visualizar_dados_salvos():
    dados_salvos = current_user
    image_data = {
        'perfil_img': base64.b64encode(dados_salvos.perfil_img).decode('utf-8') if dados_salvos.perfil_img else None,
        'cobertura_img': base64.b64encode(dados_salvos.cobertura_img).decode('utf-8') if dados_salvos.cobertura_img else None,
        'antenna_pattern_img_dia_H': base64.b64encode(dados_salvos.antenna_pattern_img_dia_H).decode('utf-8') if dados_salvos.antenna_pattern_img_dia_H else None,
        'antenna_pattern_img_dia_V': base64.b64encode(dados_salvos.antenna_pattern_img_dia_V).decode('utf-8') if dados_salvos.antenna_pattern_img_dia_V else None,
    }

    coverage_cards = []
    try:
        projects = dados_salvos.projects.order_by(Project.created_at.desc()).all()
    except Exception:
        projects = []

    for project in projects:
        settings = project.settings or {}
        summary = settings.get('lastCoverage')
        asset_id = summary.get('asset_id') if summary else None
        if summary and asset_id:
            coverage_cards.append({
                'project': project,
                'engine': summary.get('engine'),
                'generated_at': summary.get('generated_at'),
                'radius_km': summary.get('radius_km'),
                'center_metrics': summary.get('center_metrics'),
                'preview_url': url_for('projects.asset_preview', slug=project.slug, asset_id=asset_id),
                'detail_url': url_for('projects.view_project', slug=project.slug),
            })

    return render_template('dados_salvos.html', dados_salvos=dados_salvos, image_data=image_data, coverage_cards=coverage_cards)

@bp.route('/update-tilt', methods=['POST'])
@login_required
def update_tilt():
    data = request.get_json() or {}
    tilt = data.get('tilt')
    direction = data.get('direction')
    try:
        user = User.query.get(current_user.id)
        if not user:
            return jsonify({'error': 'Usuário não encontrado.'}), 404
        if tilt is not None and str(tilt).strip() != '':
            tilt_val = _coerce_float(tilt)
            if tilt_val is not None:
                user.antenna_tilt = tilt_val
        if direction is not None:
            direction_str = str(direction).strip()
            if direction_str == '':
                user.antenna_direction = None
            else:
                try:
                    normalized_dir = float(direction_str)
                except ValueError:
                    raise ValueError('Direção inválida')
                normalized_dir = normalized_dir % 360.0
                if normalized_dir < 0:
                    normalized_dir += 360.0
                user.antenna_direction = float(normalized_dir)
        db.session.commit()
        return jsonify({
            'antennaTilt': user.antenna_tilt,
            'antennaDirection': user.antenna_direction
        }), 200
    except (ValueError, SQLAlchemyError) as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400

@bp.route('/carregar-dados', methods=['GET'])
@login_required
def carregar_dados():
    try:
        user = User.query.get(current_user.id)
        if not user:
            return jsonify({'error': 'Usuário não encontrado.'}), 404
        project_slug = request.args.get('project')
        project = None
        project_settings = {}
        if project_slug:
            project = project_by_slug_or_404(project_slug, current_user.uuid)
            project_settings = project.settings or {}

        user_data = {
            'username': user.username,
            'email': user.email,
            'propagationModel': user.propagation_model,
            'frequency': user.frequencia,
            'towerHeight': user.tower_height,
            'rxHeight': user.rx_height,
            'Total_loss': user.total_loss,
            'transmissionPower': user.transmission_power,
            'antennaGain': user.antenna_gain,
            'antennaTilt': user.antenna_tilt,
            'antennaDirection': user.antenna_direction,
            'rxGain': user.rx_gain,
            'latitude': user.latitude,
            'longitude': user.longitude,
            'serviceType': user.servico,
            'nomeUsuario': user.username,
            'timePercentage': user.time_percentage or 40.0,
            'polarization': (user.polarization or 'vertical').lower(),
            'p452Version': user.p452_version or 16,
            'temperature': (user.temperature_k - 273.15) if user.temperature_k else 20.0,
            'pressure': user.pressure_hpa or 1013.0,
            'waterDensity': user.water_density or 7.5,
            'txLocationName': user.tx_location_name,
            'txElevation': user.tx_site_elevation,
            'climateUpdatedAt': user.climate_updated_at.isoformat() if user.climate_updated_at else None,
            'climateLatitude': user.climate_lat,
            'climateLongitude': user.climate_lon,
            'coverageEngine': CoverageEngine.p1546.value,
        }

        if project_settings:
            for key, value in project_settings.items():
                if value is not None:
                    user_data[key] = value
            user_data['coverageEngine'] = project_settings.get('coverageEngine', CoverageEngine.p1546.value)
            user_data['projectSettings'] = project_settings
        if project:
            user_data['projectSlug'] = project.slug
            user_data['projectName'] = project.name
            user_data['projectDescription'] = project.description
            if project_settings.get('lastSavedAt'):
                user_data['projectLastSavedAt'] = project_settings.get('lastSavedAt')

        return jsonify(user_data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('ui.index'))
