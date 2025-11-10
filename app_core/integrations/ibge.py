from __future__ import annotations

import logging
import unicodedata
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlencode

import requests
from flask import current_app


# -------------------------------
# Endpoints base (v3 Agregados)
# -------------------------------
IBGE_LOCATIONS_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
# variável 93 (População residente), Censo 2022
IBGE_DEMOGRAPHICS_BASE = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/9514/periodos/2022/variaveis/93"
)
# Fallback "legacy" para população total
IBGE_POPULATION_URL = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/2022/variaveis/9324?localidades=N6[{code}]"
)

# -------------------------------
# Classificações (IDs conforme metadado da 9514)
# -------------------------------
# Sexo (id da classificação = 2)
SEX_CLASS_ID = 2
SEX_IDS = [4, 5]  # 4 = Homens, 5 = Mulheres

# Idade (id da classificação = 287)
AGE_CLASS_ID = 287
# Faixas "nível 1" (consolidadas) + "100 anos ou mais"
AGE_BAND_IDS = [
    93070,  # 0 a 4
    93084,  # 5 a 9
    93085,  # 10 a 14
    93086,  # 15 a 19
    93087,  # 20 a 24
    93088,  # 25 a 29
    93089,  # 30 a 34
    93090,  # 35 a 39
    93091,  # 40 a 44
    93092,  # 45 a 49
    93093,  # 50 a 54
    93094,  # 55 a 59
    93095,  # 60 a 64
    93096,  # 65 a 69
    93097,  # 70 a 74
    93098,  # 75 a 79
    49108,  # 80 a 84
    49109,  # 85 a 89
    60040,  # 90 a 94
    60041,  # 95 a 99
    6653,   # 100 anos ou mais
]

# Forma de declaração da idade (id = 286)
# Quando omitida, a API costuma retornar "Total". Mantemos sem filtrar.


STATE_ALIASES = {
    "acre": "AC",
    "alagoas": "AL",
    "amapa": "AP",
    "amazonas": "AM",
    "bahia": "BA",
    "ceara": "CE",
    "distrito federal": "DF",
    "espirito santo": "ES",
    "goias": "GO",
    "maranhao": "MA",
    "mato grosso": "MT",
    "mato grosso do sul": "MS",
    "minas gerais": "MG",
    "para": "PA",
    "paraiba": "PB",
    "parana": "PR",
    "pernambuco": "PE",
    "piaui": "PI",
    "rio de janeiro": "RJ",
    "rio grande do norte": "RN",
    "rio grande do sul": "RS",
    "rondonia": "RO",
    "roraima": "RR",
    "santa catarina": "SC",
    "sao paulo": "SP",
    "sergipe": "SE",
    "tocantins": "TO",
}


def _log(event: str, **extra):
    """Logger seguro (funciona dentro/fora do contexto Flask)."""
    print("logger")
    try:
        current_app.logger.warning(event, extra=extra)
    except Exception:
        logging.getLogger("ibge_service").warning("%s %s", event, extra)


def _slugify(value: str) -> str:
    print("slugify")
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    for old, new in (("state of ", ""), ("estado de ", "")):
        ascii_text = ascii_text.replace(old, new)
    ascii_text = ascii_text.replace("-", " ").replace("_", " ")
    return " ".join(ascii_text.split())


def normalize_state_code(value: str | None) -> str | None:
    print("normalize_state_code")

    if not value:
        return None
    v = value.strip()
    if len(v) == 2 and v.isalpha():
        return v.upper()
    slug = _slugify(v)
    return STATE_ALIASES.get(slug)


def _safe_parse_numeric(value) -> int | None:
    if value in (None, "", "-", "NA"):
        return None
    try:
        # a API retorna inteiros; isto garante robustez se vier "1234,0"
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _build_demographics_url(code: str, classificacoes: Optional[dict[int, Iterable[int]]] = None) -> str:
    print("build_demographics_url")

    """
    Monta a URL da variável 93 para um município N6[code], opcionalmente
    adicionando parâmetros de classificação, e.g.:
      classificacoes = { 2: [4,5], 287: [93087,93088,...] }
    vira:
      &classificacao=2[4,5]&classificacao=287[93087,93088,...]
    """
    base = IBGE_DEMOGRAPHICS_BASE
    params = {"localidades": f"N6[{code}]"}
    qs = "?" + urlencode(params)

    if classificacoes:
        # a API aceita repetir 'classificacao='
        parts = [f"classificacao={cid}[{','.join(str(x) for x in values)}]"
                 for cid, values in classificacoes.items()
                 if values]
        if parts:
            qs += "&" + "&".join(parts)

    return base + qs


@lru_cache(maxsize=2048)
def resolve_municipality_code(city: str | None, state: str | None = None) -> str | None:
    print("resolve_municipality_code")

    if not city:
        return None
    # normaliza a consulta para melhor acerto/cache
    params = {"nome": _slugify(city)}
    try:
        resp = requests.get(IBGE_LOCATIONS_URL, params=params, timeout=10)
        resp.raise_for_status()
        candidates = resp.json()
    except Exception as exc:
        _log("ibge.lookup_failed", city=city, state=state, error=str(exc))
        return None

    if not candidates:
        return None

    normalized_state = normalize_state_code(state) if state else None

    def _candidate_state(item):
        uf_info = (((item.get("microrregiao") or {}).get("mesorregiao") or {}).get("UF") or {})
        sigla = uf_info.get("sigla")
        nome = uf_info.get("nome")
        return normalize_state_code(sigla) or normalize_state_code(nome)

    for item in candidates:
        candidate_state = _candidate_state(item)
        if not normalized_state or candidate_state == normalized_state:
            code = item.get("id")
            if code:
                return str(code)

    code = candidates[0].get("id")
    return str(code) if code else None


def _parse_total_from_payload(payload) -> Optional[int]:
    print("parse_total_from_payload")

    """
    Lê o 'total' (sem classificação) quando presente no payload padrão da 9514.
    """
    if not isinstance(payload, list) or not payload:
        return None
    resultados = payload[0].get("resultados", []) if isinstance(payload[0], dict) else []
    for resultado in resultados:
        series = resultado.get("series") or []
        for serie in series:
            classes = serie.get("classificacoes") or []
            # total típico: sem classificações
            if not classes:
                val = None
                for raw in (serie.get("serie") or {}).values():
                    val = _safe_parse_numeric(raw)
                    if val is not None:
                        print("returning total:", val)
                        return val
    return None


def _parse_breakdown(payload, target_class_name: str) -> Dict[str, int]:
    """
    Soma valores por rótulo de classe desejada (e.g. 'sexo' OU 'idade'),
    assumindo que a outra(s) dimensão(ões) não foram pedidas (para evitar dupla contagem).
    """
    out: Dict[str, int] = {}
    if not isinstance(payload, list) or not payload:
        return out

    resultados = payload[0].get("resultados", []) if isinstance(payload[0], dict) else []
    for resultado in resultados:
        # mapeia metadados das classificações deste bloco
        klasses = resultado.get("classificacoes") or []
        classes_meta: dict[str, dict[str, Any]] = {}
        for klass in klasses:
            categories = {
                (categoria.get("id")): categoria.get("nome")
                for categoria in (klass.get("categorias") or [])
            }
            classes_meta[klass.get("id")] = {
                "name": (klass.get("nome") or ""),
                "categories": categories,
            }

        for serie in (resultado.get("series") or []):
            value = None
            for raw_value in (serie.get("serie") or {}).values():
                value = _safe_parse_numeric(raw_value)
                if value is not None:
                    break
            if value is None:
                continue

            serie_classes = serie.get("classificacoes") or []
            # esperamos exatamente 1 classificação (sexo OU idade),
            # pois pedimos separadamente para evitar soma duplicada
            if len(serie_classes) != 1:
                # se vier mais de uma por alguma razão, pulamos para não enviesar
                continue

            sc = serie_classes[0]
            class_id = sc.get("id")
            category_id = sc.get("categoria")
            meta = classes_meta.get(class_id) or {}
            class_name = (meta.get("name") or "").lower()
            if target_class_name not in class_name:
                continue
            label = (meta.get("categories") or {}).get(category_id, str(category_id))
            out[label] = out.get(label, 0) + value
    print("breakdown:", out)
    return out


@lru_cache(maxsize=4096)
def fetch_demographics_by_code(code: str | None) -> Dict[str, Any] | None:
    if not code:
        return None

    payload_total = None
    payload_sex = None
    payload_age = None

    # 1) TOTAL (sem classificação) — preferível para obter 'total' diretamente
    try:
        url_total = _build_demographics_url(code, classificacoes=None)
        r_total = requests.get(url_total, timeout=15)
        r_total.raise_for_status()
        payload_total = r_total.json()
    except Exception as exc:
        _log("ibge.demographics_total_failed", code=code, error=str(exc))
        payload_total = None

    # 2) SEXO (apenas sexo; sem idade)
    try:
        url_sex = _build_demographics_url(code, classificacoes={SEX_CLASS_ID: SEX_IDS})
        r_sex = requests.get(url_sex, timeout=15)
        r_sex.raise_for_status()
        payload_sex = r_sex.json()
    except Exception as exc:
        _log("ibge.demographics_sex_failed", code=code, error=str(exc))
        payload_sex = None

    # 3) IDADE (apenas faixas etárias consolidadas; sem sexo)
    try:
        url_age = _build_demographics_url(code, classificacoes={AGE_CLASS_ID: AGE_BAND_IDS})
        r_age = requests.get(url_age, timeout=15)
        r_age.raise_for_status()
        payload_age = r_age.json()
    except Exception as exc:
        _log("ibge.demographics_age_failed", code=code, error=str(exc))
        payload_age = None

    # ---- Parse dos dados
    total = _parse_total_from_payload(payload_total)

    sex_breakdown: Dict[str, int] = _parse_breakdown(payload_sex, target_class_name="sexo") if payload_sex else {}
    age_breakdown: Dict[str, int] = _parse_breakdown(payload_age, target_class_name="idade") if payload_age else {}

    # fallback total (tabela legacy) se necessário
    if total is None:
        total = fetch_population_legacy(code)

    # Se nada deu certo:
    if total is None and not sex_breakdown and not age_breakdown:
        return None
    print("returning demographics for code:", code)
    print("total:", total)
    print("sex:", sex_breakdown)
    print("age:", age_breakdown)
    return {
        "code": code,
        "total": total,
        "sex": sex_breakdown,
        "age": age_breakdown,
        "raw": {
            "total": payload_total,
            "sex": payload_sex,
            "age": payload_age,
        },
    }


@lru_cache(maxsize=4096)
def fetch_population_legacy(code: str | None) -> int | None:
    if not code:
        return None
    try:
        resp = requests.get(IBGE_POPULATION_URL.format(code=code), timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        _log("ibge.population_failed", code=code, error=str(exc))
        return None

    serie = (
        payload[0]
        .get("resultados", [{}])[0]
        .get("series", [{}])[0]
        .get("serie", {})
    )
    values = [
        _safe_parse_numeric(value)
        for value in serie.values()
        if value not in (None, "")
    ]
    values = [v for v in values if v is not None]
    print("legacy population values:", values)
    return values[-1] if values else None


def fetch_demographics_by_city(city: str | None, state: str | None = None) -> Dict[str, Any] | None:
    code = resolve_municipality_code(city, state)
    if not code:
        return None
    data = fetch_demographics_by_code(code)
    if data:
        return data
    total = fetch_population_legacy(code)
    if total is None:
        return None
    print("returning demographics for city:", city, state)
    print("total:", total)
    return {"code": code, "total": total, "sex": {}, "age": {}, "raw": None}
