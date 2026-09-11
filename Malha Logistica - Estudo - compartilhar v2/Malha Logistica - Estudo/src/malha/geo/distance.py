"""Distância em linha reta (haversine). O raio do estudo é um círculo em km, sem API de rota."""
import numpy as np
import pandas as pd

R_TERRA_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """Aceita escalares ou arrays (broadcast numpy)."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * R_TERRA_KM * np.arcsin(np.sqrt(a))


def distance_matrix(orig: pd.DataFrame, dest: pd.DataFrame,
                    orig_id: str = "codigo_polo", dest_id: str = "cod_ibge") -> pd.DataFrame:
    """Formato longo [orig_id, dest_id, d_km] para todos os pares origem × destino."""
    d = haversine_km(orig["lat"].to_numpy()[:, None], orig["lon"].to_numpy()[:, None],
                     dest["lat"].to_numpy()[None, :], dest["lon"].to_numpy()[None, :])
    return pd.DataFrame({
        orig_id: np.repeat(orig[orig_id].to_numpy(), len(dest)),
        dest_id: np.tile(dest[dest_id].to_numpy(), len(orig)),
        "d_km": d.ravel(),
    })
