"""Exporta um cenário para Excel (várias abas) — para levar o estudo para fora do app."""
import io
import json

import numpy as np
import pandas as pd

from malha.optimize import Resultado
from malha.scenario import Scenario

ROTULOS_KPI = {
    "total_os": "OS no escopo", "ogea_base": "OS Ógea hoje", "ogea_cen": "OS Ógea no cenário",
    "share_ogea_base": "Share Ógea hoje", "share_ogea_cen": "Share Ógea no cenário",
    "absorvido": "OS absorvidas pela PagResolve", "ogea_fixo_tipos": "OS Ógea de tipos não absorvíveis",
    "custo_base": "Custo total hoje (R$)", "custo_cen": "Custo total no cenário (R$)",
    "delta_custo": "Diferença de custo (R$)", "tec_base": "Técnicos ativos hoje", "tec_cen": "Técnicos no cenário",
    "tec_contratar": "Técnicos a contratar", "polos_abertos": "Polos abertos",
    "polos_reabertos": "Polos dormentes reabertos", "hubs_novos": "Hubs novos abertos",
    "polos_fechados": "Polos ativos fechados", "cidades_absorvidas": "Cidades com volume absorvido",
    "tempo_s": "Tempo de cálculo (s)",
}


def excel_cenario(res: Resultado, base: Resultado, sc: Scenario, municipios: pd.DataFrame) -> bytes:
    nomes = municipios.set_index("cod_ibge")["municipio"]
    resumo = pd.DataFrame({
        "indicador": [ROTULOS_KPI.get(k, k) for k in res.kpis],
        "hoje": [base.kpis.get(k) for k in res.kpis],
        "cenario": list(res.kpis.values()),
    })
    params = pd.DataFrame(list(json.loads(sc.to_json()).items()), columns=["parametro", "valor"])
    params["valor"] = params["valor"].map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
    cid = res.cidades.assign(municipio=res.cidades["cod_ibge"].map(nomes))
    fl = res.fluxos.assign(municipio=res.fluxos["cod_ibge"].map(nomes))

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        resumo.to_excel(xw, sheet_name="Resumo", index=False)
        params.to_excel(xw, sheet_name="Parametros", index=False)
        res.polos.drop(columns=["lat", "lon"], errors="ignore").to_excel(xw, sheet_name="Polos", index=False)
        cid.to_excel(xw, sheet_name="Municipios", index=False)
        fl.to_excel(xw, sheet_name="Fluxos", index=False)
        if res.avisos:
            pd.DataFrame({"aviso": res.avisos}).to_excel(xw, sheet_name="Avisos", index=False)
    return buf.getvalue()


def export_cenario_assign(resultado, path) -> None:
    """Exporta o cenário do motor determinístico (`malha.assign`, o do app desktop e do Streamlit atual):
    município/bairro com polo atribuído, e cada polo com técnicos dimensionados e CMU resultante."""
    kpis = pd.DataFrame({"indicador": list(resultado.kpis.keys()), "valor": list(resultado.kpis.values())})
    locais = resultado.locais.rename(columns={
        "nome_local": "local", "vol_total": "os_jul26", "vol_ogea_cen": "os_ogea_cenario",
        "vol_polo_hoje": "os_polo_hoje", "vol_absorvido": "os_absorvido_da_ogea",
        "polo_captura": "polo_atribuido", "dist_captura_km": "distancia_km",
    })
    locais["atribuicao"] = np.where(
        locais["override_manual"], "Exceção manual do usuário", "Automática (raio)")
    locais = locais[["local_id", "local", "cod_ibge", "status", "polo_atribuido", "atribuicao", "distancia_km",
        "os_jul26", "os_ogea_cenario", "os_polo_hoje", "os_absorvido_da_ogea"]].sort_values("os_jul26", ascending=False)
    polos = resultado.polos.drop(columns=["lat", "lon"], errors="ignore").rename(columns={
        "polo_nome": "polo", "t0": "tecnicos_hoje", "v0": "volume_hoje", "vol_absorvido": "os_absorvido_da_ogea",
        "tecnicos_sugeridos": "tecnicos_novos", "volume_novo": "volume_cenario", "cmu_hoje": "cmu_hoje_rs",
        "cmu_novo": "cmu_cenario_rs", "custo_novo": "custo_total_cenario_rs", "raio_km": "raio_usado_km",
    }).sort_values("os_absorvido_da_ogea", ascending=False)

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        kpis.to_excel(xw, sheet_name="Resumo", index=False)
        polos.to_excel(xw, sheet_name="Polos", index=False)
        locais.to_excel(xw, sheet_name="Municipios e bairros", index=False)
