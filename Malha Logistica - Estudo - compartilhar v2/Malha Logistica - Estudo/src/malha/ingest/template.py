"""Aba TEMPLATE: um município por linha, com rótulo de origem e share Ógea × PagResolve.

Usada só como atributo/checagem cruzada: a tabela mestre de municípios é a do IBGE.
"""
import pandas as pd

from malha.ingest.resolve import MunicipioResolver
from malha.textnorm import parse_polo_code, to_num

COLS = ["polo_origem", "municipio_raw", "volume", "polo_resp", "tecs_polo",
        "share_ogea", "share_polo", "lead_time_d", "cmu_polo", "cmu_ogea"]
NUMERICAS = ["volume", "tecs_polo", "share_ogea", "share_polo", "lead_time_d", "cmu_polo", "cmu_ogea"]


def tipo_rotulo(s) -> str:
    if not isinstance(s, str):
        return "Outro"
    if s.startswith("MicroResto"):
        return "MicroResto"
    if s.startswith(("MunMicro", "MunSP")):
        return "Municipio"
    if s.startswith("Micro"):
        return "Micro"
    if s.startswith("TC EXPRESS"):
        return "TC Express"
    if parse_polo_code(s) is not pd.NA:
        return "Polo"
    return "Outro"


def load_template(path, resolver: MunicipioResolver) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="TEMPLATE", dtype=object).iloc[:, :10].set_axis(COLS, axis=1)
    df = raw[["polo_origem", "municipio_raw", "polo_resp"]].astype("string").apply(lambda s: s.str.strip())
    df["polo_resp"] = df["polo_resp"].mask(df["polo_resp"].eq("-").fillna(False))
    df["sem_volume"] = raw["volume"].eq("Sem Volumes")
    for c in NUMERICAS:
        df[c] = to_num(raw[c])
    df["tipo_rotulo"] = df["polo_origem"].map(tipo_rotulo)
    df["codigo_polo_origem"] = df["polo_origem"].map(parse_polo_code).astype("string")
    df["codigo_polo_resp"] = df["polo_resp"].map(parse_polo_code).astype("string")
    return df.join(resolver.resolve(df["municipio_raw"]))
