"""ML 3 — score "HUB estratégico" dos polos ATIVOS (+ tabela separada de polos dormentes).

Cada critério vira um ranking percentual (0-1, 1 = melhor) entre os polos ativos; o score é a média ponderada
(pesos do usuário; padrão = pesos iguais). Classes pelos tercis do score.
Volume Ógea conta só as cidades em que o polo é o ativo mais próximo dentro do raio (sem dupla contagem).
Dormentes não têm operação para ranquear: mostram só o volume Ógea que NENHUM ativo cobre no raio.
"""
import numpy as np
import pandas as pd

from malha.geo.distance import haversine_km

CRITERIOS = {
    # nome: (coluna, maior_é_melhor, descrição)
    "vol_ogea": ("vol_ogea_proximo", True, "OS Ógea em cidades no raio onde este é o polo ativo mais próximo"),
    "competitividade": ("cmu_vs_ogea", False, "CMU do polo ÷ preço médio Ógea nessas cidades (menor = melhor)"),
    "lead_time": ("lt_medio", False, "lead time médio do polo em dias (menor = melhor)"),
    "prazo": ("pct_prazo", True, "% de OS no prazo"),
    "exclusividade": ("dist_vizinho_km", True, "distância ao polo ativo mais próximo (cobre área que ninguém cobre)"),
}


def _ogea(demanda: pd.DataFrame) -> pd.DataFrame:
    return demanda.loc[demanda["vol_ogea"] > 0, ["cod_ibge", "vol_ogea", "custo_ogea"]]


def features(kpis: pd.DataFrame, demanda: pd.DataFrame, dist: pd.DataFrame, raio_km: float) -> pd.DataFrame:
    at = kpis[kpis["status_bd"].eq("ATIVO")].copy()
    dm = dist[dist["codigo_polo"].isin(at["codigo_polo"]) & (dist["d_km"] <= raio_km)].merge(_ogea(demanda), on="cod_ibge")
    prox = dm.sort_values("d_km").drop_duplicates("cod_ibge")
    agg = prox.groupby("codigo_polo").agg(vol_ogea_proximo=("vol_ogea", "sum"), cidades_ogea_proximo=("cod_ibge", "nunique"),
                                          custo_ogea_proximo=("custo_ogea", "sum"))
    at = at.merge(agg, left_on="codigo_polo", right_index=True, how="left")
    at["vol_ogea_no_raio"] = at["codigo_polo"].map(dm.groupby("codigo_polo")["vol_ogea"].sum()).fillna(0)
    at[["vol_ogea_proximo", "cidades_ogea_proximo"]] = at[["vol_ogea_proximo", "cidades_ogea_proximo"]].fillna(0)
    preco = at["custo_ogea_proximo"] / at["vol_ogea_proximo"].where(at["vol_ogea_proximo"] > 0)
    at["cmu_vs_ogea"] = at["cmu_polo"] / preco

    d = haversine_km(at["lat"].to_numpy(float)[:, None], at["lon"].to_numpy(float)[:, None],
                     at["lat"].to_numpy(float)[None, :], at["lon"].to_numpy(float)[None, :])
    np.fill_diagonal(d, np.inf)
    at["dist_vizinho_km"] = d.min(axis=1)
    return at


def score(feat: pd.DataFrame, pesos: dict | None = None) -> pd.DataFrame:
    pesos = pesos or {c: 1.0 for c in CRITERIOS}
    out = feat.copy()
    num = pd.Series(0.0, index=out.index)
    den = pd.Series(0.0, index=out.index)
    for nome, (col, maior_melhor, _) in CRITERIOS.items():
        w = float(pesos.get(nome, 0))
        if w <= 0:
            continue
        r = out[col].rank(pct=True, ascending=maior_melhor)
        out[f"r_{nome}"] = r
        num += r.fillna(0) * w
        den += r.notna() * w
    out["score"] = num / den.where(den > 0)
    t1, t2 = out["score"].quantile([1 / 3, 2 / 3])
    out["classe"] = np.select([out["score"] >= t2, out["score"] >= t1], ["HUB estratégico", "Manter"], "Rever")
    out.loc[out["vol_ogea_proximo"].eq(0) & out["classe"].eq("HUB estratégico"), "classe"] = "Manter"
    return out.sort_values("score", ascending=False).reset_index(drop=True)


def dormentes(kpis: pd.DataFrame, demanda: pd.DataFrame, dist: pd.DataFrame, raio_km: float) -> pd.DataFrame:
    """Para cada polo dormente: volume Ógea no raio e quanto dele nenhum polo ativo alcança."""
    dorm = kpis[kpis["status_bd"].eq("DORMENTE")].copy()
    og = _ogea(demanda)
    ativos = kpis.loc[kpis["status_bd"].eq("ATIVO"), "codigo_polo"]
    coberto = set(dist.loc[dist["codigo_polo"].isin(ativos) & (dist["d_km"] <= raio_km), "cod_ibge"])
    dm = dist[dist["codigo_polo"].isin(dorm["codigo_polo"]) & (dist["d_km"] <= raio_km)].merge(og, on="cod_ibge")
    dm["sem_cobertura"] = ~dm["cod_ibge"].isin(coberto)
    agg = dm.groupby("codigo_polo").agg(vol_ogea_no_raio=("vol_ogea", "sum"))
    agg["vol_ogea_sem_cobertura"] = dm[dm["sem_cobertura"]].groupby("codigo_polo")["vol_ogea"].sum()
    dorm = dorm.merge(agg, left_on="codigo_polo", right_index=True, how="left")
    dorm[["vol_ogea_no_raio", "vol_ogea_sem_cobertura"]] = dorm[["vol_ogea_no_raio", "vol_ogea_sem_cobertura"]].fillna(0)
    at = kpis[kpis["status_bd"].eq("ATIVO")]
    d = haversine_km(dorm["lat"].to_numpy(float)[:, None], dorm["lon"].to_numpy(float)[:, None],
                     at["lat"].to_numpy(float)[None, :], at["lon"].to_numpy(float)[None, :])
    dorm["ativo_mais_proximo"] = at["codigo_polo"].to_numpy()[d.argmin(axis=1)]
    dorm["dist_ativo_km"] = d.min(axis=1)
    return dorm.sort_values("vol_ogea_sem_cobertura", ascending=False).reset_index(drop=True)
