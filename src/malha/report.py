"""Exporta um cenário para Excel (várias abas) — para levar o estudo para fora do app."""
import io
import json

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
