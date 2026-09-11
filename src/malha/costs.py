"""Modelo de custo e rateio (faceta "rateio de custo fixo").

Polo ativo: custo observado (CMU × volume de jul/26) + custo de cada técnico ADICIONAL.
Polo dormente/novo: custo de abertura (input) + custo por técnico.
Logo, absorver volume dilui o custo atual do polo (CMU cai) até o degrau de uma nova contratação.
"""
import math

import numpy as np
import pandas as pd


def capacidade_atual(meta: float, volume_atual: float, tec_atuais: float, usar_prod_observada: bool = True) -> float:
    """OS/mês que a equipe ATUAL do polo consegue fazer.

    Se a equipe já produz mais que a meta, vale o observado (o dado prova que é possível).
    Técnico NOVO rende a meta (mediana observada) — não se assume que repete o recorde de um polo.
    """
    base = meta * (tec_atuais or 0)
    return max(volume_atual, base) if usar_prod_observada else base


def tecnicos_necessarios(volume, meta: float, tec_atuais: float = 0, cap_atual: float = 0):
    """Técnicos para atender `volume`: equipe atual + contratações a `meta` OS/técnico, sem demitir."""
    extra = np.ceil(np.maximum(np.asarray(volume, dtype=float) - cap_atual, 0) / meta - 1e-9)
    return (tec_atuais or 0) + np.maximum(extra, 0)


def custo_polo(tecnicos, custo_atual: float, tec_atuais: float, custo_tecnico: float, custo_abrir: float = 0.0):
    base = custo_atual if tec_atuais and tec_atuais > 0 else custo_abrir
    return base + custo_tecnico * (np.asarray(tecnicos, dtype=float) - (tec_atuais or 0))


def curva_rateio(volume_atual: float, custo_atual: float, tec_atuais: float, meta: float, custo_tecnico: float,
                 v_max: float, usar_prod_observada: bool = True, custo_abrir: float = 0.0, n: int = 80) -> pd.DataFrame:
    """CMU do polo em função do volume total atendido (degraus = contratações)."""
    cap0 = capacidade_atual(meta, volume_atual, tec_atuais, usar_prod_observada)
    v = np.unique(np.concatenate([np.linspace(1, max(v_max, volume_atual + 1), n), [volume_atual]]))
    v = v[v > 0]
    tec = tecnicos_necessarios(v, meta, tec_atuais, cap0)
    custo = custo_polo(tec, custo_atual, tec_atuais, custo_tecnico, custo_abrir)
    return pd.DataFrame({"volume": v, "tecnicos": tec, "custo": custo, "cmu": custo / v})


def break_even(curva: pd.DataFrame, preco_ogea: float) -> float | None:
    """Menor volume a partir do qual o CMU do polo fica abaixo do preço médio da Ógea."""
    ok = curva[curva["cmu"] <= preco_ogea]
    return None if ok.empty else float(ok["volume"].iloc[0])


def ceil_int(x: float) -> int:
    return int(math.ceil(x - 1e-9))
