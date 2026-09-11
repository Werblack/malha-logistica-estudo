"""Situação atual (jul/26) por município e por polo, e os defaults dos parâmetros — todos derivados do dado."""
import numpy as np
import pandas as pd

from malha.datasets import Dados

STATUS_LABEL = {
    "100_ogea": "100% Ógea",
    "misto": "Misto",
    "100_polo": "100% Polo",
    "sem_volume": "Sem volume",
}


def pares_atendidos(d: Dados) -> pd.DataFrame:
    """Pares (polo, município) com OS em jul/26 e a distância em linha reta da base do polo à sede."""
    p = d.os[d.os["transportadora"].eq("POLO")]
    pares = p.groupby(["codigo_polo", "cod_ibge"]).size().rename("vol").reset_index()
    return pares.merge(d.dist, on=["codigo_polo", "cod_ibge"], how="left")


def demanda_municipio(d: Dados) -> pd.DataFrame:
    """Uma linha por município IBGE (645), com volume, share, LT, prazo e custo por transportadora."""
    g = (d.os.groupby(["cod_ibge", "transportadora"])
         .agg(vol=("id_workfinity", "size"), lt=("lead_time_d", "mean"),
              prazo=("no_prazo", "mean"), custo=("cmu_os", "sum"))
         .unstack("transportadora"))
    g.columns = [f"{a}_{b.lower()}" for a, b in g.columns]
    mun = d.municipios.merge(g, left_on="cod_ibge", right_index=True, how="left")
    for c in ["vol_ogea", "vol_polo", "custo_ogea", "custo_polo"]:
        mun[c] = mun[c].fillna(0)
    mun["vol_total"] = mun["vol_ogea"] + mun["vol_polo"]
    mun["share_ogea"] = mun["vol_ogea"] / mun["vol_total"].where(mun["vol_total"] > 0)
    mun["preco_ogea_medio"] = mun["custo_ogea"] / mun["vol_ogea"].where(mun["vol_ogea"] > 0)
    mun["status"] = np.select(
        [mun["vol_total"].eq(0), mun["vol_polo"].eq(0), mun["vol_ogea"].eq(0)],
        ["sem_volume", "100_ogea", "100_polo"], "misto")

    principal = (d.os[d.os["transportadora"].eq("POLO")].groupby(["cod_ibge", "codigo_polo"]).size()
                 .reset_index(name="n").sort_values("n").drop_duplicates("cod_ibge", keep="last"))
    mun = mun.merge(principal[["cod_ibge", "codigo_polo"]].rename(columns={"codigo_polo": "polo_principal"}),
                    on="cod_ibge", how="left")

    ativos = d.polos.loc[d.polos["status_bd"].eq("ATIVO"), "codigo_polo"]
    dmin = (d.dist[d.dist["codigo_polo"].isin(ativos)].sort_values("d_km").drop_duplicates("cod_ibge")
            .rename(columns={"codigo_polo": "polo_mais_proximo", "d_km": "dist_polo_mais_proximo_km"}))
    return mun.merge(dmin, on="cod_ibge", how="left")


def polo_kpis(d: Dados) -> pd.DataFrame:
    """Uma linha por polo cadastrado (ativos, dormentes, armazém Ógea) com desempenho de jul/26."""
    p = d.os[d.os["transportadora"].eq("POLO")]
    g = p.groupby("codigo_polo").agg(
        volume=("id_workfinity", "size"), n_cidades=("cod_ibge", "nunique"),
        lt_medio=("lead_time_d", "mean"), pct_prazo=("no_prazo", "mean"),
        pct_improdutivo=("status", lambda s: s.eq("Improdutivo").mean()), custo_total=("cmu_os", "sum"))
    k = d.polos.merge(g, left_on="codigo_polo", right_index=True, how="left")
    k = k.merge(d.cmu_polo[["codigo_polo", "cmu_polo"]], on="codigo_polo", how="left")
    for c in ["volume", "custo_total"]:
        k[c] = k[c].fillna(0)
    k["os_por_tec"] = k["volume"] / k["tec_ativos"].where(k["tec_ativos"] > 0)
    k["custo_por_tec"] = k["custo_total"] / k["tec_ativos"].where(k["tec_ativos"] > 0)

    pares = pares_atendidos(d)
    alcance = pares.groupby("codigo_polo").agg(
        alcance_max_km=("d_km", "max"),
        alcance_p90_km=("d_km", lambda s: float(np.percentile(s, 90))))
    return k.merge(alcance, left_on="codigo_polo", right_index=True, how="left")


def custo_base(d: Dados) -> float:
    return float(d.os["cmu_os"].sum())


def defaults(d: Dados, kpis: pd.DataFrame | None = None) -> dict:
    """Valor inicial de cada parâmetro e de onde ele saiu. Nada é arbitrado: é dado observado ou neutro (0)."""
    kpis = polo_kpis(d) if kpis is None else kpis
    at = kpis[kpis["status_bd"].eq("ATIVO") & kpis["tec_ativos"].gt(0)]
    pares = pares_atendidos(d)
    polo_os = d.os[d.os["transportadora"].eq("POLO")]
    return {
        "raio_km": {
            "valor": round(float(np.percentile(pares["d_km"], 90)), 1),
            "origem": "dado: 90% dos pares polo→cidade já atendidos em jul/26 estão até esta distância (linha reta)"},
        "meta_os_tec": {
            "valor": round(float(at["os_por_tec"].median()), 1),
            "origem": "dado: mediana de OS/técnico ativo/mês dos polos em jul/26"},
        "custo_tecnico": {
            "valor": round(float(at["custo_por_tec"].median()), 2),
            "origem": "dado: mediana de (CMU x volume) / técnicos ativos (custo total observado por técnico/mês)"},
        "sla_alvo": {
            "valor": round(float(polo_os["no_prazo"].mean()), 4),
            "origem": "dado: % de OS no prazo dos polos em jul/26"},
        "custo_abrir": {"valor": 0.0, "origem": "input: custo fixo extra para abrir polo dormente/novo (sem dado)"},
        "custo_km": {"valor": 0.0, "origem": "input: R$ por OS·km de deslocamento (sem dado)"},
        "os_dia_gsp": {"valor": 6.0, "origem": "input: regra de negócio (produtividade Capital/Grande SP, OS/técnico/dia)"},
        "os_dia_interior": {"valor": 3.5, "origem": "input: regra de negócio (produtividade Interior, 3 a 4 OS/técnico/dia)"},
    }
