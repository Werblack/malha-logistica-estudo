"""Caminhos e constantes do estudo. Parâmetros numéricos NÃO ficam aqui: saem do dado (baseline) ou do usuário."""
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    _exe_root = Path(sys.executable).resolve().parent
    ROOT = _exe_root / "_internal" if (_exe_root / "_internal").is_dir() else _exe_root
else:
    ROOT = Path(__file__).resolve().parents[2]

RAW_XLSX = ROOT / "MALHA INPO TO BE.xlsx"
RAW_PRESTADORES = ROOT / "Prestador de Serviço.csv"

DATA = ROOT / "data"
EXTERNAL = DATA / "external"
CACHE = DATA / "cache"
MANUAL = DATA / "manual"
PROCESSED = DATA / "processed"
OUTPUTS = ROOT / "outputs"

COD_UF_SP = 35
COD_IBGE_SAO_PAULO = 3550308

# Ógea opera a partir do armazém TEFTI (cadastro de prestadores, código PS44)
OGEA_POLO_NOME = "TEFTI ARMAZEM E LOGISTICA LTDA"
OGEA_CEP = "06543320"

for _d in (EXTERNAL, CACHE, MANUAL, PROCESSED, OUTPUTS):
    _d.mkdir(parents=True, exist_ok=True)
