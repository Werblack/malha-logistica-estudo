"""Nó de demanda (o grão do mapa e do motor de atribuição).

Fora da capital, o dado não distingue bairro: o nó é o município inteiro (como sempre foi).
Em São Paulo capital a própria BD já registra `Cidade` como bairro para 5 polos (Campo Belo,
Casa Verde, Itaquera, Vila Prudente, Vila Romana; ver `data/manual/distritos_capital.csv`).
O 6º polo da capital, Faria Lima, tem `Cidade = "São Paulo"` na BD (não um bairro próprio).

As 2.838 OS da Ógea que também caem em `Cidade = "São Paulo"` (sem bairro) NÃO ficam todas num
bucket único: o CEP real de cada uma bate, uma a uma, com uma das 6 zonas postais da capital
(ver `ZONA_CEP_CAPITAL` — conferido direto na BD: 670/503/246/544/464/411, soma 2.838, exato),
cada zona já vinculada ao polo que a atende. Sem isso, um polo central (o que geograficamente
calha de estar mais perto do centróide do município) "herdava" as 2.838 de uma vez.

Importante: essa divisão por CEP vale só para a Ógea. O próprio histórico de OS do Polo Faria
Lima (1.298, que também usa `Cidade = "São Paulo"`) fica como está — checado na BD, é 100% CEP
05xxx (a Zona Oeste dessa mesma tabela), e não faz sentido nenhum "mover" o histórico real de um
polo para outro só por causa de uma regra pensada para dividir demanda nova da Ógea.

Cada um desses 6 nós só pode ser capturado pelo seu próprio polo (ver `NODE_POLO_DESIGNADO`, usado
em `assign.preparar`) — sem essa regra, um polo geograficamente central (ex.: Casa Verde) podia
"roubar" o nó de outro bairro da capital, mesmo sem nenhuma relação histórica com ele.
"""
import logging
import re

import pandas as pd

from malha.config import COD_IBGE_SAO_PAULO
from malha.geo.distance import haversine_km

log = logging.getLogger(__name__)
RAIO_SANIDADE_KM = 30.0  # um bairro de SP não pode geocodificar a mais que isto da sede do município

# bairro (valor exato de `distrito_capital`, vindo de data/manual/distritos_capital.csv) -> texto de busca
BAIRROS_CAPITAL = {
    "Campo Belo": "Campo Belo, São Paulo, SP, Brasil",
    "Casa Verde": "Casa Verde, São Paulo, SP, Brasil",
    "Itaquera": "Itaquera, São Paulo, SP, Brasil",
    "Vila Prudente": "Vila Prudente, São Paulo, SP, Brasil",
    "Vila Romana": "Vila Romana, São Paulo, SP, Brasil",
}
FARIA_LIMA_LOCAL_ID = f"{COD_IBGE_SAO_PAULO}:FARIA_LIMA"

# os 6 nós da capital e o único polo autorizado a capturar cada um (regra de território exclusivo)
NODE_POLO_DESIGNADO = {
    f"{COD_IBGE_SAO_PAULO}:CAMPO_BELO": "P310",
    f"{COD_IBGE_SAO_PAULO}:CASA_VERDE": "P007",
    f"{COD_IBGE_SAO_PAULO}:ITAQUERA": "P018",
    f"{COD_IBGE_SAO_PAULO}:VILA_PRUDENTE": "P016",
    f"{COD_IBGE_SAO_PAULO}:VILA_ROMANA": "P082",
    FARIA_LIMA_LOCAL_ID: "P015",
}

# 2 primeiros dígitos do CEP -> (nó da capital, nome da zona, nome do bairro) — só para OS da Ógea
# sem bairro próprio na BD. Conferido contra a BD real (jul/26): 01=670, 04=544, 02=503, 05=464,
# 08=411, 03=246 OS — soma 2.838, bate exato com o total do bucket genérico "São Paulo".
ZONA_CEP_CAPITAL = {
    "01": (FARIA_LIMA_LOCAL_ID, "Centro", "Faria Lima"),
    "04": (f"{COD_IBGE_SAO_PAULO}:CAMPO_BELO", "Zona Sul", "Campo Belo"),
    "02": (f"{COD_IBGE_SAO_PAULO}:CASA_VERDE", "Zona Norte", "Casa Verde"),
    "05": (f"{COD_IBGE_SAO_PAULO}:VILA_ROMANA", "Zona Oeste", "Vila Romana"),
    "08": (f"{COD_IBGE_SAO_PAULO}:ITAQUERA", "Zona Leste 2", "Itaquera"),
    "03": (f"{COD_IBGE_SAO_PAULO}:VILA_PRUDENTE", "Zona Leste 1", "Vila Prudente"),
}
NOME_ZONA_POR_LOCAL = {lid: f"{zona} / {bairro}" for lid, zona, bairro in ZONA_CEP_CAPITAL.values()}


def _slug(nome: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", nome.upper()).strip("_")


def _um(cod_ibge, distrito_capital, cep, e_ogea) -> str | float:
    if pd.isna(cod_ibge):
        return pd.NA
    cod = int(cod_ibge)
    if cod != COD_IBGE_SAO_PAULO:
        return str(cod)
    if isinstance(distrito_capital, str) and distrito_capital in BAIRROS_CAPITAL:
        return f"{cod}:{_slug(distrito_capital)}"
    if e_ogea and isinstance(cep, str) and len(cep) >= 2:
        zona = ZONA_CEP_CAPITAL.get(cep[:2])
        if zona is not None:
            return zona[0]
    return FARIA_LIMA_LOCAL_ID


def local_id(cod_ibge: pd.Series, distrito_capital: pd.Series, cep: pd.Series | None = None,
            e_ogea: pd.Series | None = None) -> pd.Series:
    """Um local por linha: município (padrão), bairro da capital (quando a BD distingue), ou zona
    postal da capital (`cep`/`e_ogea`: só OS da Ógea sem bairro próprio são divididas por CEP)."""
    if cep is None:
        cep = pd.Series(pd.NA, index=cod_ibge.index)
    if e_ogea is None:
        e_ogea = pd.Series(False, index=cod_ibge.index)
    vals = [_um(c, b, k, o) for c, b, k, o in zip(cod_ibge, distrito_capital, cep, e_ogea)]
    return pd.Series(vals, index=cod_ibge.index, dtype="string")


def build_locais(mun: pd.DataFrame, geocoder, bbox: tuple | None = None) -> pd.DataFrame:
    """Um local por município do IBGE, exceto São Paulo (capital): 6 bairros, cada um com seu polo
    e sua zona postal (ver `ZONA_CEP_CAPITAL`).

    `bbox` (min_lon, min_lat, max_lon, max_lat) do polígono de São Paulo restringe a busca por nome
    (sem isso, "Vila Romana", nome comum, geocodificou no interior do estado, a mais de 300 km da capital).

    Colunas: local_id, cod_ibge, municipio, nome_local, lat, lon, capital_subnode,
    regiao_imediata, coord_fonte, coord_confianca.
    """
    campos_regiao = ["microrregiao", "mesorregiao", "regiao_imediata", "regiao_intermediaria"]
    sp = mun.loc[mun["cod_ibge"].eq(COD_IBGE_SAO_PAULO)].iloc[0]
    sede = (float(sp["lat"]), float(sp["lon"]))

    fora = mun[mun["cod_ibge"].ne(COD_IBGE_SAO_PAULO)].copy()
    fora["local_id"] = fora["cod_ibge"].astype("string")
    fora["nome_local"] = fora["municipio"]
    fora["capital_subnode"] = False
    fora["coord_fonte"] = fora.get("coord_fonte", pd.Series(pd.NA, index=fora.index)).astype("string")
    fora["coord_confianca"] = pd.Series(pd.NA, index=fora.index, dtype="string")

    linhas = []
    for bairro, consulta in BAIRROS_CAPITAL.items():
        hit = geocoder.geocode_bairro(f"BAIRRO:{bairro}", consulta, sede=sede, viewbox=bbox)
        if haversine_km(hit.lat, hit.lon, sede[0], sede[1]) > RAIO_SANIDADE_KM:
            log.warning("Bairro '%s' geocodificado a mais de %.0f km da sede de São Paulo (%.4f,%.4f); usando a sede.",
                       bairro, RAIO_SANIDADE_KM, hit.lat, hit.lon)
            hit = type(hit)(sede[0], sede[1], "sede_municipio", "baixa")
        lid = f"{COD_IBGE_SAO_PAULO}:{_slug(bairro)}"
        linhas.append({
            "local_id": lid, "cod_ibge": COD_IBGE_SAO_PAULO,
            "municipio": sp["municipio"], "nome_local": f"São Paulo ({NOME_ZONA_POR_LOCAL[lid]})",
            "lat": hit.lat, "lon": hit.lon, "coord_fonte": hit.fonte, "coord_confianca": hit.confianca,
            "capital_subnode": True,
        })
    linhas.append({
        "local_id": FARIA_LIMA_LOCAL_ID, "cod_ibge": COD_IBGE_SAO_PAULO,
        "municipio": sp["municipio"], "nome_local": f"São Paulo ({NOME_ZONA_POR_LOCAL[FARIA_LIMA_LOCAL_ID]})",
        "lat": float(sp["lat"]), "lon": float(sp["lon"]), "coord_fonte": "sede_municipio",
        "coord_confianca": "alta", "capital_subnode": True,
    })
    cap = pd.DataFrame(linhas)
    for c in campos_regiao:
        cap[c] = sp[c]

    cols = ["local_id", "cod_ibge", "municipio", "nome_local", "lat", "lon", "capital_subnode",
            "coord_fonte", "coord_confianca", *campos_regiao]
    out = pd.concat([fora[cols], cap[cols]], ignore_index=True)
    for c in ["local_id", "municipio", "nome_local", "coord_fonte", "coord_confianca", *campos_regiao]:
        out[c] = out[c].astype("string")
    return out
