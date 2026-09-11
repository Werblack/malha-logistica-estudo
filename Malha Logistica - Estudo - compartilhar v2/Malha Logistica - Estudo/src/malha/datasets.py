"""Carrega os artefatos gerados por `python -m malha.build`."""
import json
from dataclasses import dataclass

import pandas as pd

from malha import config
from malha.geo import ibge

TABELAS = ["os", "template", "municipios", "polos", "dist_polo_mun", "cmu_polo", "preco_ogea", "tec_ativos",
           "locais", "dist_polo_local"]


@dataclass
class Dados:
    os: pd.DataFrame
    template: pd.DataFrame
    municipios: pd.DataFrame
    polos: pd.DataFrame
    dist: pd.DataFrame
    cmu_polo: pd.DataFrame
    preco_ogea: pd.DataFrame
    tec_ativos: pd.DataFrame
    locais: pd.DataFrame
    dist_local: pd.DataFrame
    qualidade: dict
    malha: dict


def load() -> Dados:
    p = config.PROCESSED
    faltando = [t for t in TABELAS if not (p / f"{t}.parquet").exists()]
    if faltando:
        raise FileNotFoundError(f"Rode `python -m malha.build` antes (faltam: {', '.join(faltando)})")
    t = {n: pd.read_parquet(p / f"{n}.parquet") for n in TABELAS}
    return Dados(
        os=t["os"], template=t["template"], municipios=t["municipios"], polos=t["polos"],
        dist=t["dist_polo_mun"], cmu_polo=t["cmu_polo"], preco_ogea=t["preco_ogea"], tec_ativos=t["tec_ativos"],
        locais=t["locais"], dist_local=t["dist_polo_local"],
        qualidade=json.loads((p / "qualidade.json").read_text(encoding="utf-8")),
        malha=ibge.load_malha(),
    )
