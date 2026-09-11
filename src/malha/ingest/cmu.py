"""Aba CMU (layout fixo, sem cabeçalho de tabela):
- colunas A-C: CMU por polo;  H-I: tabela de preço Ógea por serviço;  N-O: técnicos ativos por polo.
"""
import pandas as pd

from malha.textnorm import parse_polo_code, to_num


def _with_code(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    df = df.copy()
    df["codigo_polo"] = df["polo_nome"].map(parse_polo_code)
    df[value_col] = to_num(df[value_col])
    df = df.dropna(subset=["codigo_polo", value_col]).reset_index(drop=True)
    df["polo_nome"] = df["polo_nome"].astype("string").str.strip()
    df["codigo_polo"] = df["codigo_polo"].astype("string")
    return df


def load_cmu(path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Retorna (cmu_polo, preco_ogea, tec_ativos)."""
    raw = pd.read_excel(path, sheet_name="CMU", header=None, dtype=object)

    cmu_polo = _with_code(raw.iloc[2:, [1, 2]].set_axis(["polo_nome", "cmu_polo"], axis=1), "cmu_polo")

    preco = raw.iloc[2:, [7, 8]].set_axis(["tipo_atendimento", "preco_ogea"], axis=1)
    preco = preco[preco["tipo_atendimento"].map(lambda v: isinstance(v, str))].copy()
    preco["preco_ogea"] = to_num(preco["preco_ogea"])
    preco_ogea = preco.dropna().reset_index(drop=True)
    preco_ogea["tipo_atendimento"] = preco_ogea["tipo_atendimento"].astype("string").str.strip()

    tec_ativos = _with_code(raw.iloc[1:, [13, 14]].set_axis(["polo_nome", "tec_ativos"], axis=1), "tec_ativos")
    return cmu_polo, preco_ogea, tec_ativos
