from flask_login import UserMixin
from extensions import db  # Certifique-se de que db está corretamente importado de seu app Flask
from passlib.hash import argon2

class User(UserMixin, db.Model):
    __tablename__ = 'users'  # Nome da tabela no banco de dados

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(), unique=True, nullable=False)
    email = db.Column(db.String(), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    # Demais campos...
    propagation_model = db.Column(db.String(), nullable=True)  # Modelo de Propagação
    frequencia = db.Column(db.Float, nullable=True)  # Frequência em MHz
    tower_height = db.Column(db.Float, nullable=True)
    rx_height = db.Column(db.Float, nullable=True)  # Altura rx em Metros
    total_loss = db.Column(db.Float, nullable=True)  # Total de perdas
    transmission_power = db.Column(db.Float, nullable=True)  # Potência de Transmissão em Watts
    antenna_gain = db.Column(db.Float, nullable=True)
    rx_gain = db.Column(db.Float, nullable=True)
    antenna_direction= db.Column(db.Float, nullable=True)
    antenna_tilt = db.Column(db.Float, nullable=True)  # Ganho da Antena em dBi
    latitude = db.Column(db.Float, nullable=True)  # Latitude
    longitude = db.Column(db.Float, nullable=True)  # Longitude
    servico = db.Column(db.String(), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    antenna_pattern = db.Column(db.LargeBinary, nullable=True)
    antenna_pattern_img_dia_H = db.Column(db.LargeBinary, nullable=True)
    antenna_pattern_img_dia_V = db.Column(db.LargeBinary, nullable=True)
    antenna_pattern_data_h = db.Column(db.Text, nullable=True)
    antenna_pattern_data_v = db.Column(db.Text, nullable=True)
    # Colunas para os dados de diagramas horizontais e verticais modificados
    antenna_pattern_data_h_modified = db.Column(db.Text, nullable=True)
    antenna_pattern_data_v_modified = db.Column(db.Text, nullable=True)

    cobertura_img= db.Column(db.LargeBinary, nullable=True)
    perfil_img = db.Column(db.LargeBinary, nullable=True)

    time_percentage = db.Column(db.Float, nullable=True)
    polarization = db.Column(db.String(), nullable=True)
    temperature_k = db.Column(db.Float, nullable=True)
    pressure_hpa = db.Column(db.Float, nullable=True)
    water_density = db.Column(db.Float, nullable=True)
    p452_version = db.Column(db.Integer, nullable=True)
    tx_location_name = db.Column(db.String(), nullable=True)
    tx_site_elevation = db.Column(db.Float, nullable=True)
    climate_lat = db.Column(db.Float, nullable=True)
    climate_lon = db.Column(db.Float, nullable=True)
    climate_updated_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        """Cria uma hash de senha para armazenar no banco de dados usando argon2."""
        self.password_hash = argon2.hash(password)

    def check_password(self, password):
        """Verifica se a senha fornecida corresponde à hash armazenada usando argon2."""
        return argon2.verify(password, self.password_hash)
