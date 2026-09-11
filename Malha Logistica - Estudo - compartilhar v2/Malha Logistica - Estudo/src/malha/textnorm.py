"""Normalização de textos, CEPs e códigos vindos das planilhas."""
import numbers
import re
import unicodedata

import pandas as pd

_POLO_CODE = re.compile(r"-\s*(P\d{3})\s*$")
_EXCEL_FORMULA = re.compile(r'^=?"?(.*?)"?$', re.DOTALL)


def is_missing(v) -> bool:
    return v is None or (not isinstance(v, str) and pd.isna(v))


def norm_nome(s) -> str:
    """Chave de comparação de nomes: 'Mogi Das Cruzes' e 'Mogi das Cruzes' -> 'mogi das cruzes'."""
    if is_missing(s):
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", s.casefold()).strip()


def strip_excel_formula(v):
    """Célula exportada como fórmula: '="09911630"' -> '09911630'; '=' e '=""' -> NA."""
    if is_missing(v):
        return pd.NA
    s = _EXCEL_FORMULA.match(str(v)).group(1).strip()
    return s if s else pd.NA


def fix_cep(v):
    """CEP numérico que perdeu o zero à esquerda (9911630) -> '09911630'. Inválido -> NA.

    CEPs de SP vão de 01000-000 a 19999-999, então no máximo um zero se perde (7 ou 8 dígitos).
    """
    if is_missing(v):
        return pd.NA
    if isinstance(v, numbers.Number):
        v = str(int(v))
    digits = re.sub(r"\D", "", str(v))
    if len(digits) not in (7, 8):
        return pd.NA
    return digits.zfill(8)


def parse_polo_code(nome):
    """'Polo SP São Bernado Do Campo - P313' -> 'P313'."""
    if is_missing(nome):
        return pd.NA
    m = _POLO_CODE.search(str(nome))
    return m.group(1) if m else pd.NA


def to_num(s: pd.Series) -> pd.Series:
    """Coluna numérica com marcadores de texto ('-', 'Sem Volumes') -> float com NA."""
    s = s.replace({"-": pd.NA, "Sem Volumes": pd.NA})
    return pd.to_numeric(s, errors="coerce")
