"""Mapa real (Folium/Leaflet sobre OpenStreetMap/CartoDB) com camadas liga/desliga."""
import math

import folium
import numpy as np
import pandas as pd
from folium import plugins

# Paleta validada (colorblind-safe) do skill dataviz: status = estado de dependência da cidade,
# categórica = identidade do polo. Nunca a cor sozinha carrega o significado — sempre com rótulo/tooltip.
CORES_STATUS = {
    "100_ogea": "#d03b3b",    # status "critical" — 100% dependente da Ógea
    "misto": "#fab219",       # status "warning" — parcialmente dependente
    "100_polo": "#2a78d6",    # categórico slot 1 (azul) — já é 100% PagResolve
    "sem_volume": "#c3c2b7",  # neutro
    "absorvido": "#0ca30c",   # status "good" — passou a ser atendido pelo polo no cenário
}
ROTULO_STATUS = {
    "100_ogea": "100% Ógea", "misto": "Misto Ógea + Polo", "100_polo": "100% Polo",
    "sem_volume": "Sem volume", "absorvido": "Absorvido no cenário",
}
CORES_POLO = {"ATIVO": "#2a78d6", "DORMENTE": "#eb6834", "NOVO": "#0ca30c", "FECHADO": "#898781"}
CENTRO_SP = (-22.3, -48.6)


def _fmt(v, casas=0, pct=False):
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA:
        return "-"
    return f"{v:.{casas}%}" if pct else f"{v:,.{casas}f}".replace(",", ".")


def _legenda(itens: dict, titulo: str) -> str:
    linhas = "".join(
        f'<div><span style="display:inline-block;width:12px;height:12px;background:{cor};'
        f'margin-right:6px;border:1px solid #555"></span>{rotulo}</div>' for rotulo, cor in itens.items())
    return (f'<div style="position:fixed;bottom:24px;left:24px;z-index:9999;background:white;padding:8px 10px;'
            f'border:1px solid #999;border-radius:4px;font:12px sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3)">'
            f'<b>{titulo}</b>{linhas}</div>')


def mapa(malha: dict, municipios: pd.DataFrame, polos: pd.DataFrame, *, fluxos: pd.DataFrame | None = None,
         ogea: tuple | None = None, mostrar_circulos: bool = True, max_fluxos: int = 300,
         novos_hubs: pd.DataFrame | None = None, zoom: int = 7) -> folium.Map:
    """municipios: cod_ibge, municipio, cor_status, e colunas de tooltip (vol_total, share_ogea, ...).
    polos: codigo_polo, nome, lat, lon, status_mapa (ATIVO/DORMENTE/NOVO/FECHADO), raio_km, tecnicos, volume."""
    m = folium.Map(location=CENTRO_SP, zoom_start=zoom, tiles="OpenStreetMap", control_scale=True)

    # --- municípios coloridos
    info = municipios.set_index("cod_ibge")
    feats = []
    for f in malha["features"]:
        cod = f["properties"]["cod_ibge"]
        if cod not in info.index:
            continue
        r = info.loc[cod]
        props = {
            "cod_ibge": cod, "cor": r["cor_status"], "municipio": r["municipio"],
            "status": ROTULO_STATUS.get(r["status_mapa"], r["status_mapa"]),
            "volume": _fmt(r.get("vol_total")), "ogea": _fmt(r.get("vol_ogea")), "polo": _fmt(r.get("vol_polo")),
            "share_ogea": _fmt(r.get("share_ogea"), 0, pct=True),
            "share_cen": _fmt(r.get("share_ogea_cen"), 0, pct=True),
            "lt_ogea": _fmt(r.get("lt_ogea"), 1), "lt_polo": _fmt(r.get("lt_polo"), 1),
            "polo_resp": r.get("polo_resp") if isinstance(r.get("polo_resp"), str) else "-",
            "dist_polo": _fmt(r.get("dist_polo_mais_proximo_km"), 0),
        }
        feats.append({"type": "Feature", "geometry": f["geometry"], "properties": props})
    campos = ["municipio", "status", "volume", "ogea", "polo", "share_ogea", "share_cen", "lt_ogea", "lt_polo",
              "polo_resp", "dist_polo"]
    aliases = ["Município", "Status", "OS jul/26", "OS Ógea", "OS Polo", "Share Ógea hoje", "Share Ógea cenário",
               "LT Ógea (d)", "LT Polo (d)", "Polo responsável", "Polo mais próximo (km)"]
    folium.GeoJson(
        {"type": "FeatureCollection", "features": feats}, name="Municípios (status)",
        style_function=lambda f: {"fillColor": f["properties"]["cor"], "color": "#555", "weight": 0.3,
                                  "fillOpacity": 0.65},
        highlight_function=lambda f: {"weight": 2, "color": "#000"},
        tooltip=folium.GeoJsonTooltip(fields=campos, aliases=aliases, sticky=True),
    ).add_to(m)

    # --- raio dos polos
    abertos = polos[polos["status_mapa"].isin(["ATIVO", "NOVO"])]
    if mostrar_circulos:
        fg = folium.FeatureGroup(name="Raio de atendimento (km)")
        for r in abertos.itertuples():
            cor = CORES_POLO[r.status_mapa]
            folium.Circle((r.lat, r.lon), radius=float(r.raio_km) * 1000, color=cor, weight=1.2, fill=True,
                          fill_opacity=0.04, dash_array="6 4",
                          tooltip=f"{r.nome}: raio {r.raio_km:.0f} km").add_to(fg)
        fg.add_to(m)

    # --- fluxos polo → cidade
    if fluxos is not None and len(fluxos):
        fg = folium.FeatureGroup(name="Fluxos absorvidos (polo → cidade)")
        sede = info[["lat", "lon"]]
        pos = polos.set_index("codigo_polo")[["lat", "lon"]]
        fl = fluxos[fluxos["tipo"].eq("absorvido")].nlargest(max_fluxos, "vol")
        vmax = max(float(fl["vol"].max()), 1.0) if len(fl) else 1.0
        for r in fl.itertuples():
            if r.codigo_polo not in pos.index or r.cod_ibge not in sede.index:
                continue
            a, b = pos.loc[r.codigo_polo], sede.loc[r.cod_ibge]
            folium.PolyLine([(a["lat"], a["lon"]), (b["lat"], b["lon"])], color="#2ca02c",
                            weight=1 + 5 * math.sqrt(r.vol / vmax), opacity=0.7,
                            tooltip=f"{r.codigo_polo} → {info.at[r.cod_ibge, 'municipio']}: {r.vol:.0f} OS").add_to(fg)
        fg.add_to(m)

    # --- polos
    fg = folium.FeatureGroup(name="Polos")
    for r in polos.itertuples():
        tec = float(r.tecnicos) if pd.notna(r.tecnicos) else 0.0
        folium.CircleMarker(
            (r.lat, r.lon), radius=4 + 2.2 * math.sqrt(max(tec, 0)), color="white", weight=1.5,
            fill=True, fill_color=CORES_POLO.get(r.status_mapa, "#333"), fill_opacity=0.95,
            tooltip=(f"<b>{r.nome}</b> ({r.codigo_polo})<br>{r.status_mapa}<br>Técnicos: {tec:.0f}"
                     f"<br>Volume: {_fmt(getattr(r, 'volume', None))} OS<br>Raio: {r.raio_km:.0f} km"),
        ).add_to(fg)
    fg.add_to(m)

    if novos_hubs is not None and len(novos_hubs):
        fg = folium.FeatureGroup(name="Hubs novos sugeridos (ML)")
        for r in novos_hubs.itertuples():
            folium.Marker((r.lat, r.lon), icon=folium.Icon(color="green", icon="star"),
                          tooltip=f"Hub sugerido: {r.hub_sugerido} — {r.vol_ogea:.0f} OS Ógea órfãs em {r.n_cidades} cidades").add_to(fg)
        fg.add_to(m)

    if ogea is not None:
        folium.Marker(ogea, icon=folium.Icon(color="red", icon="home"),
                      tooltip="Armazém Ógea (TEFTI, Santana de Parnaíba)").add_to(m)

    plugins.Fullscreen().add_to(m)
    plugins.MeasureControl(primary_length_unit="kilometers", secondary_length_unit=None).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    itens = {ROTULO_STATUS[k]: v for k, v in CORES_STATUS.items()}
    itens.update({"Polo ativo": CORES_POLO["ATIVO"], "Polo dormente": CORES_POLO["DORMENTE"],
                  "Hub novo": CORES_POLO["NOVO"], "Polo fechado": CORES_POLO["FECHADO"]})
    m.get_root().html.add_child(folium.Element(_legenda(itens, "Legenda")))
    return m


def cor_municipios(demanda: pd.DataFrame, cenario: pd.DataFrame | None = None) -> pd.DataFrame:
    """Junta o status atual (e do cenário, se houver) e define a cor de cada município."""
    df = demanda.copy()
    df["status_mapa"] = df["status"]
    if cenario is not None:
        c = cenario.set_index("cod_ibge")
        df["share_ogea_cen"] = df["cod_ibge"].map(c["share_ogea_cen"])
        absorv = df["cod_ibge"].map(c["absorvido"]).fillna(0) > 0.5
        df.loc[absorv, "status_mapa"] = "absorvido"
        muda = df["cod_ibge"].map(c["status_cen"])
        sem_abs = ~absorv & muda.notna()
        df.loc[sem_abs, "status_mapa"] = muda[sem_abs]
    df["cor_status"] = df["status_mapa"].map(CORES_STATUS).fillna("#d9d9d9")
    return df


def status_polos(polos: pd.DataFrame) -> pd.Series:
    """ATIVO/DORMENTE/NOVO para a situação atual; FECHADO para ativos fechados no cenário."""
    if "aberto" not in polos:
        return polos["status_bd"].where(polos["status_bd"].isin(["ATIVO", "DORMENTE"]), "DORMENTE")
    s = polos["status"].copy()
    s[(s == "ATIVO") & ~polos["aberto"]] = "FECHADO"
    s[(s == "DORMENTE") & polos["aberto"]] = "NOVO"
    return s


def html_bytes(m: folium.Map) -> bytes:
    return m.get_root().render().encode("utf-8")
