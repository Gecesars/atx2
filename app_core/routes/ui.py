import base64
import io
import json
import math
import os
import re
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
from matplotlib.table import Table
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

matplotlib.use('Agg')

bp = Blueprint('ui', __name__)

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
    return render_template('calcular_cobertura.html', maps_api_key=maps_api_key)

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
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user is None:
            error = 'Usuário não existe.'
            return render_template('index.html', error=error)
        elif not user.check_password(password):
            error = 'Senha incorreta.'
            return render_template('index.html', error=error)
        login_user(user)
        return redirect(url_for('ui.home'))
    return render_template('index.html')

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email    = request.form['email']
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
        db.session.commit()
        return redirect(url_for('ui.index'))

    return render_template('register.html')

@bp.route('/home')
@login_required
def home():
    return render_template('home.html')

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

    Ptx_W   = current_user.transmission_power
    G_tx_dBi_base = current_user.antenna_gain  # dBi base (pico)
    G_rx_dbi = current_user.rx_gain
    frequency = current_user.frequencia
    totalloss = current_user.total_loss
    pattern   = current_user.antenna_pattern
    direction = current_user.antenna_direction
    tilt      = current_user.antenna_tilt

    direction_rx = calculate_bearing(start_coords['lat'], start_coords['lng'],
                                     end_coords['lat'],   end_coords['lng'])

    # Δ ganho (H) a partir do E/Emax horizontal
    delta_dir_dB = 0.0
    if pattern is not None:
        file_content = pattern.decode('latin1', errors='ignore')
        horizontal_data, vertical_data, _meta = parse_pat(file_content)  # E/Emax linear
        if direction is not None:
            rotation_index = int(direction / (360 / len(horizontal_data)))
            horizontal_data = np.roll(horizontal_data, rotation_index)

        e_emax = horizontal_data[int(direction_rx) % 360]
        e_emax = max(e_emax, 1e-6)  # evita log(0)
        delta_dir_dB = 20.0 * math.log10(e_emax)

    G_tx_dBi = G_tx_dBi_base + delta_dir_dB

    if frequency < 100:
        frequency = 100
    frequency = (frequency / 1000) * u.GHz

    P_dBm = 10 * math.log10(Ptx_W / 0.001)  # W → dBm
    erp = P_dBm + G_tx_dBi - totalloss

    tx_coords = path[0]; rx_coords = path[1]
    lon_tx, lat_tx = float(tx_coords['lng']) * u.deg, float(tx_coords['lat']) * u.deg
    lon_rx, lat_rx = float(rx_coords['lng']) * u.deg, float(rx_coords['lat']) * u.deg

    temperature = 293.15 * u.K
    pressure = 1013. * u.hPa
    time_percent = 40 * u.percent
    zone_t, zone_r = pathprof.CLUTTER.UNKNOWN, pathprof.CLUTTER.UNKNOWN

    with SrtmConf.set(srtm_dir='./SRTM', download='missing', server='viewpano'):
        profile = pathprof.srtm_height_profile(
            lon_tx, lat_tx, lon_rx, lat_rx, step=1 * u.m
        )
        longitudes, latitudes, total_distance, distances, heights, angle1, angle2, additional_data = profile

    h_rg = current_user.rx_height * u.m
    h_tg = current_user.tower_height * u.m

    # APLICAR CORREÇÃO DA CURVATURA DA TERRA
    distances_m = distances.to(u.m).value
    heights_m = heights.to(u.m).value

    # Calcular alturas ajustadas considerando curvatura
    adjusted_heights = adjust_heights_for_curvature(distances_m, heights_m, h_tg.value, h_rg.value)

    # Calcular raio efetivo da Terra
    effective_radius = calculate_effective_earth_radius()

    results = pathprof.losses_complete(
        frequency,
        temperature,
        pressure,
        lon_tx, lat_tx,
        lon_rx, lat_rx,
        h_tg, h_rg,
        1 * u.m,
        time_percent,
        zone_t=zone_t, zone_r=zone_r,
    )

    rx_position_km = distances.to(u.km)[-1].value
    Lb_corr = results['L_b_corr'].value[0] if isinstance(results['L_b_corr'].value, np.ndarray) else results['L_b_corr'].value
    sinal_recebido = erp + G_rx_dbi - Lb_corr  # dBm

    # Plot com curvatura da Terra
    fig, ax = plt.subplots(figsize=(15, 8))
    distances_km = distances.to(u.km)

    # Plot terreno original
    ax.fill_between(distances_km.to_value(u.km), heights_m, color='saddlebrown', alpha=0.7, label='Terreno')
    ax.plot(distances_km, heights_m, color='darkgreen')

    # Plot linha considerando curvatura da Terra
    curvature_line = []
    for i, dist_km in enumerate(distances_km.to_value(u.km)):
        if i == 0:
            height_point = heights_m[i] + h_tg.value
        elif i == len(distances_km) - 1:
            height_point = heights_m[i] + h_rg.value
        else:
            # Calcular queda da curvatura para este ponto
            drop = earth_curvature_correction(dist_km)
            height_point = heights_m[i] - drop

        curvature_line.append(height_point)

    ax.plot(distances_km.to_value(u.km), curvature_line, 'r--', alpha=0.7, label='Curvatura da Terra')

    # Antenas
    ax.vlines(0, heights_m[0], heights_m[0] + h_tg.value, color='red', linewidth=3, label='Torre TX')
    ax.vlines(distances_km[-1].value, heights_m[-1], heights_m[-1] + h_rg.value, color='blue', linewidth=3, label='Antena RX')

    # Linha de visada reta (para comparação)
    ax.plot([0, rx_position_km], [heights_m[0] + h_tg.value, heights_m[-1] + h_rg.value], 
            color='orange', linestyle=':', label='Linha Reta (sem curvatura)')

    # Fresnel 1 com curvatura
    n_points = 100
    x = np.linspace(0, rx_position_km, n_points)

    # Calcular zona de Fresnel considerando curvatura
    wavelength = (c / frequency.to(u.Hz).value)
    fresnel_radius = np.array([fresnel_zone_radius(xi, rx_position_km - xi, wavelength) for xi in x])

    # Ajustar a linha base para curvatura
    base_line = np.linspace(heights_m[0] + h_tg.value, heights_m[-1] + h_rg.value, n_points)
    curvature_adjustment = np.array([earth_curvature_correction(xi) for xi in x])
    adjusted_base = base_line - curvature_adjustment

    fresnel_top = adjusted_base + fresnel_radius
    fresnel_bottom = adjusted_base - fresnel_radius

    ax.fill_between(x, fresnel_bottom, fresnel_top, color='yellow', alpha=0.3, label='1ª Zona Fresnel')
    ax.plot(x, fresnel_top, 'm--', linewidth=1, alpha=0.7)
    ax.plot(x, fresnel_bottom, 'm--', linewidth=1, alpha=0.7)

    # Informações no gráfico
    annotation_text = (
        f'ERP: {erp:.2f} dBm\n'
        f'Direção RX: {direction_rx:.2f}°\n'
        f'ΔG direcional(H): {delta_dir_dB:.2f} dB\n'
        f'Nível de Sinal: {sinal_recebido:.2f} dBm\n'
        f'Total Loss (P.452): {Lb_corr:.2f} dB\n'
        f'Distância: {distances_km[-1].to_value(u.km):.2f} km\n'
        f'Raio Terra Ef.: {effective_radius/1000:.0f} km (k=4/3)'
    )
    ax.text(0.02, 0.98, annotation_text, transform=ax.transAxes, fontsize=10,
            va='top', ha='left', bbox=dict(boxstyle='round,pad=0.3', ec='black', fc='lightyellow'))

    ax.set_xlabel('Distância (km)')
    ax.set_ylabel('Elevação (m)')
    ax.set_title('Perfil de Elevação com Curvatura da Terra')
    plt.grid(True, which="both", ls="--")
    ax.legend(loc='lower right')

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', bbox_inches='tight')
    img_buffer.seek(0)
    current_user.perfil_img = img_buffer.getvalue()
    db.session.commit()
    img_buffer.seek(0)
    img_base64 = base64.b64encode(img_buffer.read()).decode('utf-8')
    img_buffer.close()
    plt.close(fig)

    return jsonify({"image": img_base64})

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


def _compute_gain_components(user, lons, lats, lon_center_deg, lat_center_deg):
    horizontal_linear, vertical_linear = _load_antenna_patterns(user)
    direction = user.antenna_direction
    tilt = user.antenna_tilt

    gain_data = {
        'horizontal_gain_grid_db': 0.0,
        'horizontal_pattern': None,
        'vertical_gain_db': 0.0,
        'vertical_value_linear': None,
    }

    if horizontal_linear is None or vertical_linear is None:
        return gain_data

    horizontal_linear = np.asarray(horizontal_linear, dtype=float)
    if direction is not None:
        rotation_index = int((direction) % 360)
        horizontal_linear = np.roll(horizontal_linear, rotation_index)

    lons_deg = np.asarray(lons, dtype=float)
    lats_deg = np.asarray(lats, dtype=float)
    lon_grid, lat_grid = np.meshgrid(lons_deg, lats_deg)
    azimutes_grid = np.degrees(np.arctan2(lon_grid - lon_center_deg, lat_grid - lat_center_deg)) % 360
    az_idx = np.round(azimutes_grid).astype(int) % 360
    horizontal_gain_db = 20.0 * np.log10(np.clip(horizontal_linear, 1e-6, None))
    gain_data['horizontal_gain_grid_db'] = horizontal_gain_db[az_idx]
    gain_data['horizontal_pattern'] = horizontal_linear

    vertical_linear = np.asarray(vertical_linear, dtype=float)
    if tilt:
        vertical_linear = np.roll(vertical_linear, int(np.round(tilt)))
    idx_zero = len(vertical_linear) // 2
    vertical_value = np.clip(vertical_linear[idx_zero], 1e-6, None)
    gain_data['vertical_gain_db'] = float(20.0 * math.log10(vertical_value))
    gain_data['vertical_value_linear'] = vertical_linear

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


def _render_field_strength_image(lons_deg, lats_deg, field_levels_dbuv, radius_km,
                                 lon_center_deg, lat_center_deg,
                                 min_val, max_val, horizontal_pattern_linear):
    lon_grid, lat_grid = np.meshgrid(lons_deg, lats_deg)
    field_plot = np.array(field_levels_dbuv, copy=True)

    dist = np.sqrt((lon_grid - lon_center_deg) ** 2 + (lat_grid - lat_center_deg) ** 2)
    earth_radius_km = 6371.0
    dist_km = dist * (np.pi / 180.0) * earth_radius_km
    field_plot[dist_km > radius_km] = np.nan

    fig, ax = plt.subplots(figsize=(6, 6))
    mesh = ax.pcolormesh(lon_grid, lat_grid, field_plot, cmap='rainbow', shading='auto',
                         vmin=min_val, vmax=max_val)

    if horizontal_pattern_linear is not None:
        polar_dimension = min(fig.get_size_inches()) * 0.35
        inset_left = (1.0 - polar_dimension / fig.get_size_inches()[0]) * 0.5
        inset_bottom = (1.0 - polar_dimension / fig.get_size_inches()[1]) * 0.5
        ax_inset = fig.add_axes([inset_left, inset_bottom, polar_dimension / fig.get_size_inches()[0],
                                 polar_dimension / fig.get_size_inches()[1]], polar=True)
        ax_inset.set_theta_zero_location('N')
        ax_inset.set_theta_direction(-1)
        azimutes = np.linspace(0, 2 * np.pi, len(horizontal_pattern_linear))
        ax_inset.plot(azimutes, horizontal_pattern_linear, linestyle='dashed', label='Padrão E/Emax')
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
    ax_cb.set_title('Nível de Campo [dBµV/m]')
    fig_cb.tight_layout()
    cb_buffer = io.BytesIO()
    fig_cb.savefig(cb_buffer, format='png', transparent=True)
    cb_buffer.seek(0)
    colorbar_base64 = base64.b64encode(cb_buffer.read()).decode('utf-8')
    plt.close(fig_cb)

    return image_base64, colorbar_base64

@bp.route('/calculate-coverage', methods=['POST'])
@login_required
def calculate_coverage():
    data = request.get_json()
    loss      = current_user.total_loss or 0.0
    Ptx_W     = current_user.transmission_power
    Gtx_dbi   = current_user.antenna_gain
    Grx_dBi   = current_user.rx_gain
    long      = current_user.longitude
    lati      = current_user.latitude

    raio_para_adj = data.get('radius')
    new_center_lat, new_center_lon = adjust_center(raio_para_adj, lati, long)

    lon_rt = new_center_lon * u.deg
    lat_rt = new_center_lat * u.deg

    freq_input_mhz = current_user.frequencia or 100.0
    if freq_input_mhz < 100:
        freq_input_mhz = 100.0
    frequency = (freq_input_mhz/1000) * u.GHz

    h_rt = current_user.rx_height * u.m
    h_wt = current_user.tower_height * u.m
    polarization = 1
    version = 16

    min_valu = data.get('minSignalLevel')
    max_valu = data.get('maxSignalLevel')
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

    min_valu = _coerce_optional(min_valu)
    max_valu = _coerce_optional(max_valu)
    radius_km = data.get('radius')*1.26

    if radius_km/1.26 in range(0, 41):
        res = 1
    elif radius_km/1.26 in range(41, 61):
        res = 5
    elif radius_km/1.26 in range(61, 80):
        res = 8
    else:
        res = 10

    map_resolution = res * u.arcsec

    bounds = calculate_geodesic_bounds(new_center_lon, new_center_lat, radius_km)
    km_per_degree = 111.32
    colorbar_height_deg = 0.01 / km_per_degree
    colorbar_height = 0.005
    colorbar_bounds = {
        'north': bounds['north'],
        'south': bounds['north'],
        'east':  bounds['east'],
        'west':  bounds['west']
    }

    temperature = 293.15 * u.K
    pressure    = 1013. * u.hPa
    timepercent = 40 * u.percent
    modelo = current_user.propagation_model
    if modelo == 'modelo1':
        zone_t, zone_r = pathprof.CLUTTER.URBAN, pathprof.CLUTTER.URBAN
    elif modelo == 'modelo2':
        zone_t, zone_r = pathprof.CLUTTER.SUBURBAN, pathprof.CLUTTER.SUBURBAN
    elif modelo == 'modelo3':
        zone_t, zone_r = pathprof.CLUTTER.TROPICAL_FOREST, pathprof.CLUTTER.TROPICAL_FOREST
    elif modelo == 'modelo4':
        zone_t, zone_r = pathprof.CLUTTER.CONIFEROUS_TREES, pathprof.CLUTTER.CONIFEROUS_TREES
    elif modelo == 'modelo5':
        zone_t, zone_r = pathprof.CLUTTER.UNKNOWN, pathprof.CLUTTER.UNKNOWN

    raio_km = data.get('radius')
    circunferencia_terra_km = 40075.0
    extensao_graus = (raio_km / circunferencia_terra_km) * 360
    map_size_lon = map_size_lat = extensao_graus * u.deg

    with pathprof.SrtmConf.set(
        srtm_dir='./SRTM',
        download='missing',
        server='viewpano'
    ):
        hprof_cache = pathprof.height_map_data(
            lon_rt, lat_rt,
            map_size_lon, map_size_lat,
            map_resolution=map_resolution,
            zone_t=zone_t, zone_r=zone_r,
        )

    results = pathprof.atten_map_fast(
        freq=frequency,
        temperature=temperature,
        pressure=pressure,
        h_tg=h_wt,
        h_rg=h_rt,
        timepercent=timepercent * u.percent,
        hprof_data=hprof_cache,
        polarization=polarization,
        version=version,
        base_water_density=7.5 * u.g / u.m**3
    )

    _lons = hprof_cache['xcoords']
    _lats = hprof_cache['ycoords']
    _total_atten = results['L_b']

    lons_deg = _to_degree_array(_lons)
    lats_deg = _to_degree_array(_lats)
    lon_center_deg = float(new_center_lon)
    lat_center_deg = float(new_center_lat)

    gain_components = _compute_gain_components(
        current_user,
        lons_deg,
        lats_deg,
        lon_center_deg,
        lat_center_deg
    )
    horizontal_gain_grid_db = gain_components['horizontal_gain_grid_db']
    vertical_gain_db = gain_components['vertical_gain_db']

    P_dBm = 10 * math.log10(Ptx_W / 0.001)
    Loss_dB = loss
    total_path_loss_db = _total_atten.to(u.dB).value

    effective_gain_db = ganho_pico_dBi + horizontal_gain_grid_db + vertical_gain_db
    received_power_dbm = P_dBm + effective_gain_db - Loss_dB - total_path_loss_db

    field_levels_dbuv = received_power_dbm + 176.284 - 20.0 * np.log10(freq_input_mhz)

    min_val, max_val = _determine_auto_scale(field_levels_dbuv, min_valu, max_valu)

    signal_level_dict = {}
    if field_levels_dbuv.shape == (len(lats_deg), len(lons_deg)):
        for i, lat_val in enumerate(lats_deg):
            for j, lon_val in enumerate(lons_deg):
                value = field_levels_dbuv[i, j]
                if np.isfinite(value):
                    key = f"({lat_val}, {lon_val})"
                    signal_level_dict[key] = float(value)

    image_base64, colorbar_base64 = _render_field_strength_image(
        lons_deg,
        lats_deg,
        field_levels_dbuv,
        radius_km,
        lon_center_deg,
        lat_center_deg,
        min_val,
        max_val,
        gain_components['horizontal_pattern']
    )

    return jsonify({
        "image": image_base64,
        "colorbar": colorbar_base64,
        "bounds": bounds,
        "colorbar_bounds": colorbar_bounds,
        "signal_level_dict": signal_level_dict,
        "field_unit": "dBµV/m",
        "scale": {
            "min": min_val,
            "max": max_val,
        },
        "gain_components": {
            "base_gain_dbi": ganho_pico_dBi,
            "horizontal_adjustment_db_min": float(np.nanmin(horizontal_gain_grid_db)) if np.ndim(horizontal_gain_grid_db) else 0.0,
            "horizontal_adjustment_db_max": float(np.nanmax(horizontal_gain_grid_db)) if np.ndim(horizontal_gain_grid_db) else 0.0,
            "vertical_adjustment_db": vertical_gain_db,
            "horizontal_pattern_linear": gain_components['horizontal_pattern'].tolist() if gain_components['horizontal_pattern'] is not None else None,
            "vertical_pattern_linear": gain_components['vertical_value_linear'].tolist() if gain_components['vertical_value_linear'] is not None else None,
        }
    })

# -------- Dados do usuário --------

@bp.route('/salvar-dados', methods=['POST'])
@login_required
def salvar_dados():
    try:
        data = request.json
        user = User.query.get(current_user.id)
        if not user:
            return jsonify({'error': 'Usuário não encontrado.'}), 404

        user.propagation_model = data.get('propagationModel')
        user.frequencia        = float(data.get('frequency'))
        user.tower_height      = float(data.get('towerHeight'))
        user.rx_height         = float(data.get('rxHeight'))
        user.rx_gain           = float(data.get('rxGain'))
        user.total_loss        = float(data.get('Total_loss'))
        user.transmission_power= float(data.get('transmissionPower'))
        user.antenna_gain      = float(data.get('antennaGain'))
        tilt_val = data.get('antennaTilt')
        if tilt_val is not None and str(tilt_val).strip() != '':
            try:
                user.antenna_tilt = float(tilt_val)
            except ValueError:
                pass
        user.latitude          = float(data.get('latitude'))
        user.longitude         = float(data.get('longitude'))
        user.servico           = data.get('service')

        db.session.commit()
        return jsonify({'message': 'Dados salvos com sucesso!'}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'error': 'Erro ao salvar os dados: ' + str(e)}), 500

@bp.route('/visualizar-dados-salvos')
@login_required
def visualizar_dados_salvos():
    user_id = current_user.id
    dados_salvos = User.query.filter_by(id=user_id).first()
    if dados_salvos:
        image_data = {
            'perfil_img': base64.b64encode(dados_salvos.perfil_img).decode('utf-8') if dados_salvos.perfil_img else None,
            'cobertura_img': base64.b64encode(dados_salvos.cobertura_img).decode('utf-8') if dados_salvos.cobertura_img else None,
            'antenna_pattern_img_dia_H': base64.b64encode(dados_salvos.antenna_pattern_img_dia_H).decode('utf-8') if dados_salvos.antenna_pattern_img_dia_H else None,
            'antenna_pattern_img_dia_V': base64.b64encode(dados_salvos.antenna_pattern_img_dia_V).decode('utf-8') if dados_salvos.antenna_pattern_img_dia_V else None,
        }
    else:
        image_data = {
            'perfil_img': None,
            'cobertura_img': None,
            'antenna_pattern_img_dia_H': None,
            'antenna_pattern_img_dia_V': None,
        }
    return render_template('dados_salvos.html', dados_salvos=dados_salvos, image_data=image_data)

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
            user.antenna_tilt = float(tilt)
        if direction is not None and str(direction).strip() != '':
            user.antenna_direction = float(direction)
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
            'rxGain': user.rx_gain,
            'latitude': user.latitude,
            'longitude': user.longitude,
            'serviceType': user.servico,
            'nomeUsuario': user.username
        }
        return jsonify(user_data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('ui.index'))
