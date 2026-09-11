"""Ponte Python <-> JS do PyWebView. Usa exatamente os mesmos cálculos do Streamlit
(`malha.assign`, `malha.costs`, `malha.baseline`) — nada é recalculado ou duplicado aqui,
só é embrulhado num formato leve (dict/list) para JSON, sem passar por pandas em cada chamada
(é isso que deixa o slider instantâneo — ver `simular_rapido` em `src/malha/assign.py`).
"""
import logging

import pandas as pd
import webview
from webview import FileDialog

from malha import assign, baseline, locais as locais_mod, report
from malha.config import COD_IBGE_SAO_PAULO
from malha.datasets import load

log = logging.getLogger(__name__)


def _params(d: dict) -> assign.Params:
    return assign.Params(
        raio_km=float(d["raio_km"]),
        os_dia_gsp=float(d["os_dia_gsp"]),
        os_dia_interior=float(d["os_dia_interior"]),
        custo_tecnico=float(d["custo_tecnico"]),
        raio_polo={k: float(v) for k, v in (d.get("raio_polo") or {}).items()},
        override_local={k: str(v) for k, v in (d.get("override_local") or {}).items()},
    )


class Api:
    def __init__(self):
        self._d = None
        self._k = None
        self._prep = None

    # -------------------------------------------------------------- carregado uma vez, ao abrir a janela

    def _carregar(self):
        if self._prep is not None:
            return
        log.info("Carregando dados (python -m malha.build já deve ter rodado)...")
        self._d = load()
        self._k = baseline.polo_kpis(self._d)
        self._prep = assign.preparar(self._d, self._k)
        log.info("OK: %d locais, %d polos ativos (com técnico)", len(self._prep.base), len(self._prep.polos))

    # -------------------------------------------------------------- chamado 1x pelo app.js ao iniciar

    def init(self) -> dict:
        self._carregar()
        d, k, prep = self._d, self._k, self._prep
        dfl = baseline.defaults(d, k)

        malha = d.malha
        for f in malha["features"]:
            f["properties"]["is_sp_capital"] = f["properties"]["cod_ibge"] == COD_IBGE_SAO_PAULO

        # polo PagResolve responsável por cada local, direto da coluna "POLO PAGRESOLVE RESP." da aba
        # TEMPLATE (não é o polo que captura no cenário atual: é a atribuição de negócio já existente)
        tpl = d.template.copy()
        tpl["local_id"] = locais_mod.local_id(tpl["cod_ibge"], tpl["distrito_capital"])
        polo_resp_por_local = (tpl.dropna(subset=["local_id"]).drop_duplicates("local_id")
                               .set_index("local_id")["polo_resp"])

        locais = [{
            "local_id": lid, "nome_local": r.nome_local, "cod_ibge": int(r.cod_ibge),
            "lat": float(r.lat), "lon": float(r.lon), "capital_subnode": bool(r.capital_subnode),
            "vol_ogea": float(r.vol_ogea), "vol_polo_hoje": float(r.vol_polo_hoje), "vol_total": float(r.vol_total),
            "polo_resp": polo_resp_por_local.get(lid) if pd.notna(polo_resp_por_local.get(lid, None)) else None,
        } for lid, r in prep.base.iterrows()]

        polos = [{
            "codigo_polo": r.codigo_polo, "polo_nome": r.polo_nome, "status_bd": r.status_bd,
            "lat": float(r.lat), "lon": float(r.lon), "t0": float(r.t0), "v0": float(r.v0),
            "regiao_gsp": bool(r.regiao_gsp),
            # SLA "ótimo" por polo: P90 das distâncias que ele já atende hoje dentro do prazo real (dado,
            # não um modelo ajustado por polo — poucos polos têm alcance suficiente para isso).
            "alcance_p90_km": (None if r.alcance_p90_km != r.alcance_p90_km else float(r.alcance_p90_km)),
        } for r in prep.polos.itertuples(index=False)]

        ogea = k.loc[k["codigo_polo"].eq("OGEA")].iloc[0]

        return {
            "malha": malha,
            "locais": locais,
            "polos": polos,
            "ogea_latlon": [float(ogea["lat"]), float(ogea["lon"])],
            "defaults": {nome: {"valor": v["valor"], "origem": v["origem"]} for nome, v in dfl.items()},
        }

    # -------------------------------------------------------------- chamado a cada slider

    def simular(self, params: dict) -> dict:
        self._carregar()
        return assign.simular_rapido(self._prep, _params(params))

    # -------------------------------------------------------------- botão "Exportar Cenário (.xlsx)"

    def exportar_cenario(self, params: dict) -> dict:
        self._carregar()
        resultado = assign.simular(self._prep, _params(params))
        try:
            destino = webview.windows[0].create_file_dialog(
                FileDialog.SAVE, save_filename="cenario_malha.xlsx",
                file_types=("Planilha Excel (*.xlsx)",))
        except Exception as e:
            log.warning("Falha ao abrir o diálogo de salvar: %s", e)
            return {"ok": False, "mensagem": f"Não foi possível abrir o diálogo: {e}"}
        if not destino:
            return {"ok": False, "mensagem": "cancelado"}
        caminho = destino[0] if isinstance(destino, (list, tuple)) else destino
        if not str(caminho).lower().endswith(".xlsx"):
            caminho = str(caminho) + ".xlsx"
        report.export_cenario_assign(resultado, caminho)
        return {"ok": True, "caminho": str(caminho)}
