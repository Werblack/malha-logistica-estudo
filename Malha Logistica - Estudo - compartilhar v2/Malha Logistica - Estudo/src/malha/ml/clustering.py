"""ML 2 — demanda órfã → hubs novos.

Demanda órfã = volume Ógea em cidades fora do raio de qualquer polo aberto.
Agrupamento ponderado por volume (KMeans em coordenadas locais em km); o hub proposto é o medoide
(município do grupo que minimiza Σ volume × distância). Quantos hubs: o menor número em que a cobertura
(fração do volume órfão a até R km do hub do seu grupo) atinge o alvo — mesmo critério de 90% do raio padrão.
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from malha.geo.distance import R_TERRA_KM, haversine_km


def _xy_km(lat, lon, lat0):
    return np.column_stack([np.radians(lon) * R_TERRA_KM * np.cos(np.radians(lat0)), np.radians(lat) * R_TERRA_KM])


def demanda_orfa(demanda: pd.DataFrame, polos_abertos: pd.DataFrame) -> pd.DataFrame:
    """demanda: municípios com lat, lon, vol_ogea. polos_abertos: lat, lon, raio_km."""
    dem = demanda[demanda["vol_ogea"] > 0].copy()
    if polos_abertos.empty:
        dem["dist_polo_km"] = np.inf
        return dem
    d = haversine_km(dem["lat"].to_numpy()[:, None], dem["lon"].to_numpy()[:, None],
                     polos_abertos["lat"].to_numpy(float)[None, :], polos_abertos["lon"].to_numpy(float)[None, :])
    dem["dist_polo_km"] = d.min(axis=1)
    coberta = (d <= polos_abertos["raio_km"].to_numpy(float)[None, :]).any(axis=1)
    return dem[~coberta]


def _medoide_idx(g: pd.DataFrame) -> int:
    lat, lon, w = g["lat"].to_numpy(), g["lon"].to_numpy(), g["vol_ogea"].to_numpy()
    d = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    return int(np.argmin((d * w[None, :]).sum(axis=1)))


def _agrupar(orfa: pd.DataFrame, k: int, random_state: int) -> np.ndarray:
    xy = _xy_km(orfa["lat"].to_numpy(), orfa["lon"].to_numpy(), float(orfa["lat"].mean()))
    km = KMeans(n_clusters=k, n_init=10, random_state=random_state)
    return km.fit(xy, sample_weight=orfa["vol_ogea"].to_numpy()).labels_


def _dist_ao_hub(orfa: pd.DataFrame, labels: np.ndarray) -> np.ndarray:
    out = np.zeros(len(orfa))
    for c in np.unique(labels):
        idx = np.flatnonzero(labels == c)
        g = orfa.iloc[idx]
        m = g.iloc[_medoide_idx(g)]
        out[idx] = haversine_km(m["lat"], m["lon"], g["lat"].to_numpy(), g["lon"].to_numpy())
    return out


def k_por_cobertura(orfa: pd.DataFrame, raio_km: float, cobertura: float = 0.9, k_max: int = 40,
                    random_state: int = 0) -> tuple[int, pd.DataFrame]:
    """Menor k em que ≥ `cobertura` do volume órfão fica a até raio_km do hub do seu grupo."""
    w = orfa["vol_ogea"].to_numpy()
    rows = []
    k = 1
    for k in range(1, min(k_max, len(orfa)) + 1):
        d = _dist_ao_hub(orfa, _agrupar(orfa, k, random_state))
        cov = float(w[d <= raio_km].sum() / w.sum())
        rows.append({"k": k, "cobertura": cov})
        if cov >= cobertura:
            break
    return k, pd.DataFrame(rows)


def hubs(orfa: pd.DataFrame, k: int, raio_km: float, polos_cadastro: pd.DataFrame, vol_min: float,
         random_state: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resumo por grupo (hub sugerido = medoide) e a demanda órfã rotulada."""
    k = max(1, min(k, len(orfa)))
    labels = _agrupar(orfa, k, random_state)
    orfa = orfa.assign(cluster=labels, dist_hub_km=_dist_ao_hub(orfa, labels))
    dorm = polos_cadastro[polos_cadastro["status_bd"].eq("DORMENTE")]
    rows = []
    for c, g in orfa.groupby("cluster"):
        m = g.iloc[_medoide_idx(g)]
        dentro = g["dist_hub_km"] <= raio_km
        dorm_mesmo = dorm[dorm["cod_ibge"].eq(m["cod_ibge"])]
        vol = float(g["vol_ogea"].sum())
        rows.append({
            "cluster": int(c), "cod_ibge": int(m["cod_ibge"]), "hub_sugerido": m["municipio"],
            "lat": float(m["lat"]), "lon": float(m["lon"]), "n_cidades": int(len(g)), "vol_ogea": vol,
            "vol_no_raio": float(g.loc[dentro, "vol_ogea"].sum()),
            "dist_media_km": float(np.average(g["dist_hub_km"], weights=g["vol_ogea"])),
            "dist_polo_atual_km": float(m["dist_polo_km"]),
            "viavel": vol >= vol_min,
            "polo_dormente_no_municipio": ", ".join(dorm_mesmo["codigo_polo"]) if len(dorm_mesmo) else "",
            "cidades": ", ".join(g.sort_values("vol_ogea", ascending=False)["municipio"].head(8)),
        })
    return pd.DataFrame(rows).sort_values("vol_ogea", ascending=False).reset_index(drop=True), orfa
