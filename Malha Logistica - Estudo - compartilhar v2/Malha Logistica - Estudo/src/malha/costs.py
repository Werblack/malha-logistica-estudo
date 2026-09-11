"""Modelo de custo e dimensionamento de técnicos.

Regra de negócio (Especificação de Refatoração): técnico novo rende por produtividade da região
(Capital/Grande SP: mais denso, mais OS/dia; Interior: menos denso) — não pela meta única de antes.
Técnicos sugeridos = teto(volume absorvido / produtividade mensal da região do polo).
Novo CMU = (custo atual do polo + técnicos sugeridos × custo/técnico) / (volume base + volume absorvido).
Sem aviso de prejuízo: o número sai como está, a leitura é gerencial.
"""
import math

import numpy as np
import pandas as pd

DIAS_UTEIS_MES = 22  # convenção de calendário (≈22 dias úteis/mês), não um dado da planilha


def produtividade_mensal(os_por_dia: float, dias_uteis_mes: int = DIAS_UTEIS_MES) -> float:
    return float(os_por_dia) * dias_uteis_mes


def tecnicos_sugeridos(volume_absorvido, produtividade_mensal):
    """Teto(volume absorvido / produtividade mensal). Aceita escalar ou array (produtividade pode variar por linha)."""
    v = np.asarray(volume_absorvido, dtype=float)
    prod = np.asarray(produtividade_mensal, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.ceil(v / prod - 1e-9)
    return np.where((prod > 0) & (v > 0), t, 0.0)


def novo_custo_polo(custo_atual, tecnicos_sugeridos, custo_tecnico: float):
    return np.asarray(custo_atual, dtype=float) + np.asarray(tecnicos_sugeridos, dtype=float) * custo_tecnico


def novo_cmu(custo_novo, volume_base, volume_absorvido):
    total = np.asarray(volume_base, dtype=float) + np.asarray(volume_absorvido, dtype=float)
    custo_novo = np.asarray(custo_novo, dtype=float)
    return np.where(total > 0, custo_novo / np.where(total > 0, total, 1.0), np.nan)


# --------------------------------------------------------------------------------------------------
# Mantido para o motor MILP (src/malha/optimize.py), que continua no repositório como ferramenta
# avançada/offline — só não é mais chamado pela tela principal. Não duplica regra: é outro modelo.

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
