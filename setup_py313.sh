#!/usr/bin/env bash
set -euo pipefail

# ===== Config =====
REPO_DIR="${REPO_DIR:-/mnt/d/dev/ATXV2/atxcover}"
REQS_PATH="${REQS_PATH:-$REPO_DIR/requirements.txt}"
REQS_PY313="${REQS_PY313:-$REPO_DIR/requirements-py313.txt}"
VENV_DIR="${VENV_DIR:-$HOME/venv-atxcover-py313}"

APT_DEPS=(
  build-essential python3.13-dev
  libffi-dev libssl-dev
  libatlas-base-dev gfortran
  libxml2-dev libxslt1-dev
  libjpeg-dev zlib1g-dev
  libgeos-dev
)

log(){ printf "\n\033[1;34m[ATXCOVER]\033[0m %s\n" "$*"; }
err(){ printf "\n\033[1;31m[ERROR]\033[0m %s\n" "$*" >&2; exit 1; }

# ===== Checagens =====
[ -f "$REQS_PATH" ] || err "requirements.txt não encontrado em: $REQS_PATH"
if ! command -v lsb_release >/dev/null 2>&1; then
  log "Aviso: lsb_release não encontrado; prosseguindo mesmo assim (ambiente não-padrão)."
fi

# ===== Python 3.13 =====
if ! command -v python3.13 >/dev/null 2>&1; then
  log "Instalando Python 3.13 (deadsnakes PPA) ..."
  sudo apt update
  sudo apt install -y software-properties-common
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt update
  sudo apt install -y python3.13 python3.13-venv python3.13-dev
else
  log "Python 3.13 encontrado: $(python3.13 -V)"
fi

# ===== venv =====
if [ -z "${VIRTUAL_ENV:-}" ]; then
  log "Criando venv 3.13 em: $VENV_DIR"
  python3.13 -m venv "$VENV_DIR"
  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"
else
  PYV="$(python -c 'import sys;print(".".join(map(str,sys.version_info[:2])))' 2>/dev/null || echo '')"
  if [ "$PYV" != "3.13" ]; then
    log "VIRTUAL_ENV atual não é 3.13. Ativando/gerando venv em: $VENV_DIR"
    # shellcheck disable=SC1090
    source "$VENV_DIR/bin/activate" 2>/dev/null || {
      python3.13 -m venv "$VENV_DIR"
      source "$VENV_DIR/bin/activate"
    }
  else
    log "Usando venv atual (3.13)."
  fi
fi

# ===== Deps de sistema =====
log "Instalando toolchain/headers necessários ..."
sudo apt update
sudo apt install -y "${APT_DEPS[@]}"

# ===== pip toolchain =====
log "Atualizando pip/wheel/setuptools ..."
python -m pip install -U pip wheel setuptools

# ===== requirements-py313.txt com patch =====
log "Gerando $REQS_PY313 (compat 3.13) ..."
# Regras:
# 1) Remover linhas com 'bcc==...' (bcc quebra em 3.13 no WSL e não é usado no ATXCOVER).
# 2) Opcional: converter pinos muito agressivos para >= (só se necessário).
awk '
  BEGIN{IGNORECASE=1}
  /^[[:space:]]*#/ {print; next}
  /^[[:space:]]*$/ {print; next}
  # Remove bcc fixo (ex.: bcc==0.30.0)
  tolower($0) ~ /^[[:space:]]*bcc==/ { next }
  # Caso queira só ignorar bcc (mantendo comentários)
  {print}
' "$REQS_PATH" > "$REQS_PY313"

log "Preview das diferenças (se houver):"
( command -v diff >/dev/null 2>&1 && diff -u "$REQS_PATH" "$REQS_PY313" ) || true

# ===== Instalação =====
log "Instalando requirements (py3.13) ..."
pip install -r "$REQS_PY313"

# ===== Smoke test =====
log "Smoke test (versões/imports básicos) ..."
python - <<'PY'
import sys
print("Python:", sys.version)
mods = ["flask","fastapi","uvicorn","numpy","pandas","shapely","requests","twisted"]
for m in mods:
    try:
        mod = __import__(m)
        print(f"[OK] {m}", getattr(mod,"__version__", ""))
    except Exception as e:
        print(f"[WARN] {m} import falhou: {e}")
PY

# ===== Dicas =====
log "Setup 3.13 concluído."
echo "Venv: $VENV_DIR"
echo "Repo: $REPO_DIR"
echo
echo "Ativação:"
echo "  source \"$VENV_DIR/bin/activate\""
echo "Rodar ATXCOVER:"
echo "  cd \"$REPO_DIR\""
echo "  python app.py   # ou o entrypoint que você usa"
