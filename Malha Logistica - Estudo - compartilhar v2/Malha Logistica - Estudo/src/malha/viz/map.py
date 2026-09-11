"""Mapa real (Folium/Leaflet sobre OpenStreetMap) — paleta estrita Verde (Ógea) / Amarelo (PagResolve).

Território é binário (regra de negócio): ou é Ógea (verde) ou é PagResolve (amarelo, seja porque já
era hoje, seja porque entrou no raio de um polo no cenário). Cinza só marca "sem volume" (não é status
de negócio, é ausência de dado). A cor nunca é o único sinal — tooltip sempre traz o rótulo por extenso.
"""
import math

import folium
import numpy as np
import pandas as pd
from folium import plugins

from malha.config import COD_IBGE_SAO_PAULO

CORES = {"ogea": "#2e7d32", "polo": "#f4c20d", "sem_volume": "#c3c2b7"}
ROTULOS = {"ogea": "Território Ógea", "polo": "Território PagResolve", "sem_volume": "Sem volume em jul/26"}
COR_POLO = "#1f4e8c"
COR_OGEA_ARMAZEM = "#b3261e"
CENTRO_SP = (-22.3, -48.6)


def _fmt(v, casas=0, pct=False):
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA:
        return "-"
    return f"{v:.{casas}%}" if pct else f"{v:,.{casas}f}".replace(",", ".")


def _legenda() -> str:
    linhas = "".join(
        f'<div><span style="display:inline-block;width:12px;height:12px;background:{CORES[k]};'
        f'margin-right:6px;border:1px solid #555"></span>{ROTULOS[k]}</div>' for k in CORES)
    linhas += (f'<div style="margin-top:4px"><span style="display:inline-block;width:12px;height:12px;'
              f'border-radius:50%;background:{COR_POLO};margin-right:6px;border:1px solid #fff"></span>'
              f'Polo PagResolve</div>')
    linhas += (f'<div><span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
              f'background:{COR_OGEA_ARMAZEM};margin-right:6px;border:1px solid #fff"></span>Armazém Ógea</div>')
    return (f'<div style="position:fixed;bottom:24px;left:24px;z-index:9999;background:white;padding:8px 10px;'
            f'border:1px solid #999;border-radius:4px;font:12px sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3)">'
            f'<b>Legenda</b>{linhas}</div>')


def mapa(malha: dict, locais: pd.DataFrame, polos: pd.DataFrame, *, ogea_latlon: tuple | None = None,
        mostrar_circulos: bool = True, zoom: int = 7) -> folium.Map:
    """locais: local_id, nome_local, cod_ibge, lat, lon, capital_subnode, status, vol_total, vol_ogea,
    vol_polo_hoje, vol_ogea_cen, polo_captura, dist_captura_km (saída de `assign.simular`, já com `.status`).
    polos: codigo_polo, polo_nome/nome, lat, lon, raio_km, t0, tecnicos_sugeridos, vol_absorvido, v0."""
    m = folium.Map(location=CENTRO_SP, zoom_start=zoom, tiles="OpenStreetMap", control_scale=True)
    info = locais.set_index("local_id")
    municipio_de = info[~info["capital_subnode"]]  # 1 local == 1 polígono de município

    # --- polígonos de município (verde/amarelo/cinza) — São Paulo capital fica neutra (some abaixo em pontos)
    feats = []
    for f in malha["features"]:
        cod = f["properties"]["cod_ibge"]
        if cod == COD_IBGE_SAO_PAULO:
            props = {"cod_ibge": cod, "cor": "#e8e6da", "nome": "São Paulo (ver bairros)", "status": "Dividida em bairros",
                     "volume": "-", "ogea": "-", "polo": "-", "share_cen": "-"}
            feats.append({"type": "Feature", "geometry": f["geometry"], "properties": props})
            continue
        r = municipio_de.loc[str(cod)] if str(cod) in municipio_de.index else None
        if r is None:
            continue
        props = {
            "cod_ibge": cod, "cor": CORES.get(r["status"], "#d9d9d9"), "nome": r["nome_local"],
            "status": ROTULOS.get(r["status"], r["status"]),
            "volume": _fmt(r.get("vol_total")), "ogea": _fmt(r.get("vol_ogea_cen")), "polo": _fmt(r.get("vol_polo_hoje")),
            "share_cen": _fmt(r["vol_ogea_cen"] / r["vol_total"], 0, pct=True) if r.get("vol_total") else "-",
            "polo_resp": r.get("polo_captura") if isinstance(r.get("polo_captura"), str) else "-",
        }
        feats.append({"type": "Feature", "geometry": f["geometry"], "properties": props})
    campos = ["nome", "status", "volume", "ogea", "polo", "share_cen", "polo_resp"]
    aliases = ["Município", "Status", "OS jul/26", "OS Ógea (cenário)", "OS Polo (hoje)", "Share Ógea (cenário)", "Polo responsável"]
    folium.GeoJson(
        {"type": "FeatureCollection", "features": feats}, name="Municípios (interior e Grande SP)",
        style_function=lambda f: {"fillColor": f["properties"]["cor"], "color": "#555", "weight": 0.3, "fillOpacity": 0.65},
        highlight_function=lambda f: {"weight": 2, "color": "#000"},
        tooltip=folium.GeoJsonTooltip(fields=campos, aliases=aliases, sticky=True),
    ).add_to(m)

    # --- São Paulo capital: bairros como círculos (evita o bloco único da cidade toda)
    cap = info[info["capital_subnode"]]
    if len(cap):
        fg = folium.FeatureGroup(name="São Paulo — bairros")
        vmax = max(float(cap["vol_total"].max()), 1.0)
        for lid, r in cap.iterrows():
            share_txt = _fmt(r["vol_ogea_cen"] / r["vol_total"], 0, pct=True) if r["vol_total"] else "-"
            folium.CircleMarker(
                (r["lat"], r["lon"]), radius=6 + 16 * math.sqrt(max(r["vol_total"], 0) / vmax),
                color="#333", weight=1, fill=True, fill_color=CORES.get(r["status"], "#d9d9d9"), fill_opacity=0.8,
                tooltip=(f"<b>{r['nome_local']}</b><br>{ROTULOS.get(r['status'], r['status'])}<br>"
                        f"OS jul/26: {_fmt(r['vol_total'])}<br>Ógea (cenário): {_fmt(r['vol_ogea_cen'])} ({share_txt})<br>"
                        f"Polo (hoje): {_fmt(r['vol_polo_hoje'])}"
                        + (f"<br>Capturado por: {r['polo_captura']}" if isinstance(r.get("polo_captura"), str) else "")),
            ).add_to(fg)
        fg.add_to(m)

    # --- raio dos polos
    if mostrar_circulos:
        fg = folium.FeatureGroup(name="Raio de atendimento (km)")
        for r in polos.itertuples():
            if r.raio_km <= 0:
                continue
            folium.Circle((r.lat, r.lon), radius=float(r.raio_km) * 1000, color=COR_POLO, weight=1.2, fill=True,
                          fill_opacity=0.04, dash_array="6 4", tooltip=f"{r.polo_nome}: raio {r.raio_km:.0f} km").add_to(fg)
        fg.add_to(m)

    # --- polos
    fg = folium.FeatureGroup(name="Polos PagResolve")
    for r in polos.itertuples():
        tec = float(r.t0) + float(r.tecnicos_sugeridos)
        folium.CircleMarker(
            (r.lat, r.lon), radius=4 + 2.2 * math.sqrt(max(tec, 0)), color="white", weight=1.5,
            fill=True, fill_color=COR_POLO, fill_opacity=0.95,
            tooltip=(f"<b>{r.polo_nome}</b> ({r.codigo_polo})<br>Raio: {r.raio_km:.0f} km"
                    f"<br>Técnicos hoje: {r.t0:.0f} · sugeridos p/ absorver: +{r.tecnicos_sugeridos:.0f}"
                    f"<br>Volume hoje: {_fmt(r.v0)} · absorvido da Ógea: {_fmt(r.vol_absorvido)}"
                    f"<br>CMU hoje: R$ {_fmt(r.cmu_hoje, 2)} · CMU novo: R$ {_fmt(r.cmu_novo, 2)}"),
        ).add_to(fg)
    fg.add_to(m)

    if ogea_latlon is not None:
        folium.Marker(ogea_latlon, icon=folium.Icon(color="red", icon="home"),
                      tooltip="Armazém Ógea (TEFTI, Santana de Parnaíba)").add_to(m)

    plugins.Fullscreen().add_to(m)
    plugins.MeasureControl(primary_length_unit="kilometers", secondary_length_unit=None).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    m.get_root().html.add_child(folium.Element(_legenda()))
    return m


def html_bytes(m: folium.Map) -> bytes:
    return m.get_root().render().encode("utf-8")
