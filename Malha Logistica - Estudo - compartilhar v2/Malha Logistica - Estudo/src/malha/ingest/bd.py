"""Aba BD: uma linha por OS (jul/26, SP). Limpeza e resolução de município."""
import pandas as pd

from malha.ingest.resolve import MunicipioResolver
from malha.textnorm import fix_cep, parse_polo_code, to_num

OGEA_DATE_FMT = "%d/%m/%Y %H:%M:%S"


def parse_mixed_dates(s: pd.Series) -> pd.Series:
    """Linhas Polo vêm como datetime; linhas Ógea como texto dd/mm/aaaa hh:mm:ss."""
    is_text = s.map(lambda v: isinstance(v, str))
    native = pd.to_datetime(s.mask(is_text), errors="coerce")
    text = pd.to_datetime(s.where(is_text), format=OGEA_DATE_FMT, errors="coerce")
    return native.fillna(text)


def _txt(s: pd.Series) -> pd.Series:
    """Texto com '-' como marcador de vazio."""
    s = s.astype("string").str.strip()
    return s.mask(s.eq("-").fillna(False))


def read_bd_raw(path) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name="BD", dtype=object)


def clean_bd(raw: pd.DataFrame, resolver: MunicipioResolver) -> pd.DataFrame:
    transp = raw["Transportadora"].astype("string").str.strip().str.upper()
    df = pd.DataFrame({
        "id_workfinity": raw["ID WorkFinity"].astype("string"),
        "transportadora": transp,
        "polo_nome": _txt(raw["Polo"]),
        "status": _txt(raw["Status"]),
        "tipo_atendimento": _txt(raw["Tipo Atendimento"]),
        "dt_abertura": parse_mixed_dates(raw["Data Abertura"]),
        "dt_fechamento": parse_mixed_dates(raw["Data Fechamento"]),
        "dt_limite": parse_mixed_dates(raw["Data Limit Atendimento"]),
        "cep": raw["CEP"].map(fix_cep).astype("string"),
        "cidade_raw": _txt(raw["Cidade"]),
        "tecnico": _txt(raw["Tecnico"]),
        "no_prazo": raw["Dentro ou Fora do Prazo"].eq("Dentro do Prazo"),
        "lead_time_d": to_num(raw["Lead Time"]),
        "cmu_os": to_num(raw["CMU"]),
        "carteira": _txt(raw["Carteira"]),
        "qtde_tec_ativos": to_num(raw["Qtde de Técnico"]),
    })
    is_polo = transp.eq("POLO").fillna(False)
    df["codigo_polo"] = df["polo_nome"].map(parse_polo_code).astype("string").where(is_polo)
    df["codigo_polo_bd"] = _txt(raw["Codigo Polo"])  # coluna original, só para checagem de qualidade
    return df.join(resolver.resolve(df["cidade_raw"]))
