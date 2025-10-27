# ATXCOVER

**Microwave and RF Synthesis, Analysis, and Design Tools**

---

## 📡 Project Overview

**ATXCOVER** is a comprehensive suite of tools designed for the synthesis, analysis, and design of microwave and RF systems. It integrates various modules to facilitate the development and management of RF components and systems, providing engineers with a robust platform for their projects.

---

## 🧰 Features

- **Antenna Design and Analysis**: Tools for designing and simulating various antenna configurations.
- **RF Component Simulation**: Modules for simulating RF components such as filters, amplifiers, and mixers.
- **Signal Processing Utilities**: Functions for analyzing and processing RF signals.
- **Data Visualization**: Interactive charts and graphs for visualizing simulation results.
- **SNMP Management**: Integration with SNMP for monitoring and managing networked RF devices.
- **Coverage Planner**: Dual-overlay (dBµV/m & dBm) map with ITU-R P.452 loss breakdown, tilt-aware antenna gains and receiver management.
- **Automatic Context Data**: TX municipality/elevation discovery (SRTM + reverse geocoding) and climate snapshots agregated from the last 360 days via Open-Meteo.
- **Professional UX**: Sticky navigation, polished control panel, live spinners and climate/location warnings to highlight pending updates.

---

## 📍 Planejamento de Cobertura

- Painel lateral profissional com cartões para TX, tilt, RXs, ganhos, perdas P.452, indicadores centrais e ligação TX↔RX sincronizados com o mapa Google.
- Camadas de cobertura comutáveis entre campo elétrico (dBµV/m) e potência recebida (dBm), respeitando a escala padrão 10–60 dBµV/m e autoajustando o histograma por percentis.
- Máscara circular respeitando o raio solicitado, com feathering para transição suave e supressão de artefatos fora da mancha.
- Lista de RX com resumo imediato (distância, rumo, nível estimado, obstáculos e terreno) e ação direta para gerar perfis profissionais com Fresnel, torres escalonadas e orçamento de enlace.
- Indicadores do ponto central realçam a perda combinada, ganho efetivo, campo e classificação da trajetória (LOS/NLOS/difração/troposcatter).

## 🌦️ Dados Climáticos Automatizados

- Integração com a API [Open-Meteo](https://open-meteo.com/) usando médias horárias dos últimos 360 dias para extrair temperatura, pressão, umidade relativa e densidade absoluta de vapor d'água.
- Persistência de latitude/longitude, município e altitude do site TX para detectar mudanças de localização e solicitar novo ajuste climático quando necessário.
- Os valores persistidos alimentam automaticamente o cálculo com pycraf (tempo %, polarização, versão P.452, temperatura, pressão, densidade de vapor), mantendo coerência entre formulários e backend.

## 📚 Documentação Complementar

- **Arquitetura detalhada**: consulte `docs/ARCHITECTURE.md` para fluxos de backend/front-end e integrações.
- **Referência pycraf**: o arquivo `pycraf.md` descreve os modelos UIT-R implementados e destaca os parâmetros utilizados nas novas métricas de cobertura.

---

## 🗂️ Project Structure

```
ATXCOVER/
├── antenna/                 # Antenna design modules
├── Arduino_SNMP_Manager/    # SNMP management tools
├── gauge-chart/             # Visualization components
├── static/                  # Static files (CSS, JS, images)
├── templates/               # HTML templates for the web interface
├── app.py                   # Main application script
├── requirements.txt         # Python dependencies
├── Dockerfile               # Docker configuration
├── README.md                # Project documentation
└── ...
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.8 or higher
- Git
- Docker (optional, for containerized deployment)

### Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/Gecesars/ATXCOVER.git
   cd ATXCOVER
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application:**

   ```bash
   python app.py
   ```

   The application will be accessible at `http://localhost:5000`.

4. **Apply database migrations (when schema changes are shipped):**

   ```bash
   flask db upgrade
   ```

5. **Restart the managed service (production environments):**

   ```bash
   sudo systemctl restart atxcover
   ```

---

## 🐳 Docker Deployment

To run the application in a Docker container:

```bash
docker build -t atxcover .
docker run -p 5000:5000 atxcover
```

---

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](https://github.com/Gecesars/ATXCOVER/blob/main/LICENSE) file for details.

---

## 🤝 Contributing

Contributions are welcome! Please fork the repository and submit a pull request for any enhancements or bug fixes.

---

## 📬 Contact

For questions or suggestions, please open an issue on the [GitHub repository](https://github.com/Gecesars/ATXCOVER/issues).
