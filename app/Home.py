"""Simulador de malha logística SP — Ógea × PagResolve. Tela única, resposta instantânea aos sliders.

    streamlit run app/Home.py
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from malha import assign, baseline
from malha.datasets import load
from malha.viz import map as vmap

st.set_page_config(page_title="Malha Logística SP — Ógea × PagResolve", layout="wide")


@st.cache_resource
def _dados():
    return load()


@st.cache_data
def _kpis_polos(_d):
    return baseline.polo_kpis(_d)


@st.cache_data
def _defaults(_d, _k):
    return baseline.defaults(_d, _k)


@st.cache_resource
def _preparado(_d, _k):
    return assign.preparar(_d, _k)


try:
    d = _dados()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

k = _kpis_polos(d)
dfl = _defaults(d, k)
prep = _preparado(d, k)
polos_habilitados = k[k["tec_ativos"].fillna(0).gt(0)].sort_values("polo_nome")  # só os 31 com técnico ativo

st.title("🗺️ Malha Logística SP — Ógea × PagResolve")
st.caption("Cada polo Habilitado da PagResolve (ativo ou hoje sem volume) tem um raio de atendimento em km. "
          "Ao mexer no raio, o mapa e os cartões abaixo recalculam na hora: território dentro do raio de "
          "algum polo vira PagResolve (amarelo); o resto continua Ógea (verde).")


# --------------------------------------------------------------------------- barra lateral: sliders

def _origem(nome):
    st.caption(f"↳ {dfl[nome]['origem']}")


with st.sidebar:
    st.header("⚙️ Parâmetros")
    raio_km = st.slider("Raio de atendimento (km, linha reta)", 5.0, 250.0, float(dfl["raio_km"]["valor"]), 1.0)
    _origem("raio_km")

    st.subheader("Produtividade (técnico novo)")
    os_dia_gsp = st.slider("Capital / Grande SP (OS/técnico/dia)", 2.0, 10.0, float(dfl["os_dia_gsp"]["valor"]), 0.5)
    _origem("os_dia_gsp")
    os_dia_interior = st.slider("Interior (OS/técnico/dia)", 1.0, 8.0, float(dfl["os_dia_interior"]["valor"]), 0.5)
    _origem("os_dia_interior")

    st.subheader("Custo")
    custo_tecnico = st.number_input("Custo por técnico novo (R$/mês)", 0.0, value=float(dfl["custo_tecnico"]["valor"]), step=500.0)
    _origem("custo_tecnico")

    with st.expander("🔧 Ajuste fino do raio por polo"):
        st.caption("Deixe em branco para usar o raio global acima. Raio 0 = polo não captura nada (\"fechado\").")
        tabela_raio = pd.DataFrame({"codigo_polo": polos_habilitados["codigo_polo"],
                                    "polo": polos_habilitados["polo_nome"], "raio_km_proprio": pd.NA})
        ed = st.data_editor(tabela_raio, hide_index=True, width="stretch", key="raio_editor",
                            disabled=["codigo_polo", "polo"])
        raio_polo = {r.codigo_polo: float(r.raio_km_proprio) for r in ed.itertuples()
                    if pd.notna(r.raio_km_proprio)}

    mostrar_circulos = st.checkbox("Mostrar raio no mapa (círculo)", value=True)

params = assign.Params(raio_km=raio_km, os_dia_gsp=os_dia_gsp, os_dia_interior=os_dia_interior,
                       custo_tecnico=custo_tecnico, raio_polo=raio_polo)


# --------------------------------------------------------------------------- motor (instantâneo)

resultado = assign.simular(prep, params)
kp = resultado.kpis


# --------------------------------------------------------------------------- KPIs

c1, c2, c3, c4 = st.columns(4)
c1.metric("Volume absorvido da Ógea", f"{kp['vol_absorvido']:,.0f} OS/mês".replace(",", "."),
         f"{kp['locais_capturados']} locais capturados")
c2.metric("Share Ógea no cenário", f"{kp['share_ogea_cenario']:.0%}",
         f"{(kp['share_ogea_cenario'] - kp['share_ogea_hoje']):+.0%} vs. hoje")
c3.metric("Técnicos sugeridos (novos)", f"{kp['tecnicos_sugeridos']:,.0f}".replace(",", "."),
         f"R$ {kp['custo_tecnicos_novo']:,.0f}/mês".replace(",", "."))
c4.metric("CMU médio do cenário", f"R$ {kp['cmu_medio_novo']:.2f}" if pd.notna(kp["cmu_medio_novo"]) else "-")

st.caption(f"Hoje (jul/26): Ógea atende {kp['share_ogea_hoje']:.0%} das {kp['total_os']:,.0f} OS de SP."
          .replace(",", "."))


# --------------------------------------------------------------------------- mapa

ogea_ll = tuple(k.loc[k["codigo_polo"].eq("OGEA"), ["lat", "lon"]].iloc[0])
m = vmap.mapa(d.malha, resultado.locais, resultado.polos, ogea_latlon=ogea_ll, mostrar_circulos=mostrar_circulos)
st_folium(m, height=640, width="stretch", returned_objects=[])


# --------------------------------------------------------------------------- detalhe por polo (recolhido)

with st.expander("📋 Detalhe por polo"):
    cols = ["codigo_polo", "polo_nome", "raio_km", "regiao_gsp", "t0", "v0", "vol_absorvido", "tecnicos_sugeridos",
            "volume_novo", "cmu_hoje", "cmu_novo", "locais_capturados"]
    show = resultado.polos[cols].rename(columns={
        "polo_nome": "polo", "t0": "técnicos hoje", "v0": "volume hoje", "vol_absorvido": "absorvido da Ógea",
        "tecnicos_sugeridos": "técnicos sugeridos", "volume_novo": "volume no cenário",
        "regiao_gsp": "Capital/Grande SP", "locais_capturados": "locais capturados",
    }).sort_values("absorvido da Ógea", ascending=False)
    st.dataframe(show.style.format({
        "raio_km": "{:.0f} km", "cmu_hoje": "R$ {:.2f}", "cmu_novo": "R$ {:.2f}",
        "volume hoje": "{:.0f}", "absorvido da Ógea": "{:.0f}", "volume no cenário": "{:.0f}",
        "técnicos sugeridos": "{:.0f}", "técnicos hoje": "{:.0f}",
    }), width="stretch", hide_index=True)
