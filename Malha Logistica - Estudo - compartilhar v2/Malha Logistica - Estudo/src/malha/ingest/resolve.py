"""Resolve nomes de cidade das planilhas para o código IBGE do município."""
import logging

import pandas as pd
from rapidfuzz import fuzz, process

from malha.textnorm import norm_nome

log = logging.getLogger(__name__)

FUZZY_MIN_SCORE = 92


class MunicipioResolver:
    """Ordem: distritos da capital -> aliases manuais -> nome IBGE normalizado -> fuzzy (sinalizado)."""

    def __init__(self, municipios: pd.DataFrame, distritos: pd.DataFrame, aliases: pd.DataFrame):
        self._by_norm = dict(zip(municipios["municipio"].map(norm_nome), municipios["cod_ibge"].astype(int)))
        self._nome = dict(zip(municipios["cod_ibge"].astype(int), municipios["municipio"]))
        self._distritos = {
            norm_nome(r.cidade_raw): (int(r.cod_ibge), r.distrito) for r in distritos.itertuples()
        }
        self._aliases = {norm_nome(r.cidade_raw): int(r.cod_ibge) for r in aliases.itertuples()}

    def _resolve_one(self, raw: str) -> tuple:
        key = norm_nome(raw)
        if key in self._distritos:
            cod, distrito = self._distritos[key]
            return cod, distrito, "distrito"
        if key in self._aliases:
            return self._aliases[key], pd.NA, "alias"
        if key in self._by_norm:
            return self._by_norm[key], pd.NA, "exato"
        hit = process.extractOne(key, list(self._by_norm), scorer=fuzz.ratio)
        if hit and hit[1] >= FUZZY_MIN_SCORE:
            log.warning("Cidade '%s' resolvida por similaridade para '%s' (%.0f)", raw, hit[0], hit[1])
            return self._by_norm[hit[0]], pd.NA, "fuzzy"
        return pd.NA, pd.NA, "nao_encontrado"

    def resolve(self, cidade_raw: pd.Series) -> pd.DataFrame:
        """DataFrame alinhado ao índice de entrada: cod_ibge, municipio, distrito_capital, match_municipio."""
        table = {raw: self._resolve_one(raw) for raw in cidade_raw.dropna().unique()}
        rows = cidade_raw.map(lambda v: table.get(v, (pd.NA, pd.NA, "vazio")))
        out = pd.DataFrame(rows.tolist(), index=cidade_raw.index,
                           columns=["cod_ibge", "distrito_capital", "match_municipio"])
        out["cod_ibge"] = out["cod_ibge"].astype("Int64")
        out["municipio"] = out["cod_ibge"].map(self._nome).astype("string")
        out["distrito_capital"] = out["distrito_capital"].astype("string")
        return out[["cod_ibge", "municipio", "distrito_capital", "match_municipio"]]
