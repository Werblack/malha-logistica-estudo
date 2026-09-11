"""Municípios de SP: nomes e regiões (IBGE localidades), sede (kelvins) e polígonos (IBGE malhas).

Baixa uma vez e guarda em data/external; depois roda offline.
"""
import gzip
import json

import pandas as pd
import requests
from shapely.geometry import shape

from malha.config import COD_UF_SP, EXTERNAL

URL_LOCALIDADES = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{COD_UF_SP}/municipios"
URL_KELVINS = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"

F_LOCALIDADES = EXTERNAL / "ibge_municipios_sp.json"
F_KELVINS = EXTERNAL / "kelvins_municipios.csv"

# "minima" é leve mas distorce municípios pequenos (a sede de Taboão da Serra cai fora do próprio contorno)
QUALIDADE_MALHA = "intermediaria"


def _url_malha(qualidade: str) -> str:
    return (f"https://servicodados.ibge.gov.br/api/v3/malhas/estados/{COD_UF_SP}"
            f"?intrarregiao=municipio&formato=application/vnd.geo+json&qualidade={qualidade}")


def _download(url: str, dest, refresh: bool = False):
    if dest.exists() and not refresh:
        return dest
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    content = r.content
    if content[:2] == b"\x1f\x8b":  # IBGE às vezes responde gzip sem Content-Encoding
        content = gzip.decompress(content)
    dest.write_bytes(content)
    return dest


def _read_json(path):
    content = path.read_bytes()
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    return json.loads(content.decode("utf-8"))


def load_malha(refresh: bool = False, qualidade: str = QUALIDADE_MALHA) -> dict:
    """GeoJSON dos 645 municípios, com properties.cod_ibge (int)."""
    gj = _read_json(_download(_url_malha(qualidade), EXTERNAL / f"ibge_malha_sp_{qualidade}.geojson", refresh))
    for f in gj["features"]:
        f["properties"]["cod_ibge"] = int(f["properties"]["codarea"])
    return gj


def poligonos(malha: dict) -> dict:
    """cod_ibge -> geometria shapely."""
    return {f["properties"]["cod_ibge"]: shape(f["geometry"]) for f in malha["features"]}


def load_municipios(malha: dict | None = None, refresh: bool = False) -> pd.DataFrame:
    """Municípios SP: cod_ibge, municipio, regiões IBGE e lat/lon da sede (fonte registrada em coord_fonte)."""
    raw = _read_json(_download(URL_LOCALIDADES, F_LOCALIDADES, refresh))
    rows = []
    for m in raw:
        micro = m.get("microrregiao") or {}
        ri = m.get("regiao-imediata") or {}
        rows.append({
            "cod_ibge": int(m["id"]),
            "municipio": m["nome"],
            "microrregiao": micro.get("nome"),
            "mesorregiao": (micro.get("mesorregiao") or {}).get("nome"),
            "regiao_imediata": ri.get("nome"),
            "regiao_intermediaria": (ri.get("regiao-intermediaria") or {}).get("nome"),
        })
    mun = pd.DataFrame(rows)

    kel = pd.read_csv(_download(URL_KELVINS, F_KELVINS, refresh))
    kel = kel.loc[kel["codigo_uf"] == COD_UF_SP, ["codigo_ibge", "latitude", "longitude"]]
    kel.columns = ["cod_ibge", "lat", "lon"]
    mun = mun.merge(kel, on="cod_ibge", how="left")
    mun["coord_fonte"] = mun["lat"].notna().map({True: "kelvins_sede", False: pd.NA})

    if malha is not None and mun["lat"].isna().any():
        polys = poligonos(malha)
        for idx in mun.index[mun["lat"].isna()]:
            geom = polys.get(mun.at[idx, "cod_ibge"])
            if geom is not None:
                p = geom.representative_point()
                mun.loc[idx, ["lat", "lon", "coord_fonte"]] = [p.y, p.x, "ibge_poligono"]
    for c in ["municipio", "microrregiao", "mesorregiao", "regiao_imediata", "regiao_intermediaria", "coord_fonte"]:
        mun[c] = mun[c].astype("string")
    return mun
