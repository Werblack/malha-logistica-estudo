"""ML 1 — raio de SLA: como o lead time (P90) e a chance de cumprir o prazo mudam com a distância em linha reta.

Amostra: cada OS com a distância da origem (base do polo, ou armazém da Ógea) até a sede do município.
- Ógea sai de um só armazém para ~580 cidades: dá a curva longa (mecanismo de transportadora).
- Polos: só OS FORA do município-base do polo. Dentro da própria cidade (ex.: capital inteira é um ponto só)
  a distância até a sede não mede deslocamento real e contaminaria a curva.
- A faixa de distância vai do P1 ao P99 observado (sem extrapolar, sem outliers como Guarulhos→Assis).
Modelos com restrição monotônica na distância (mais longe nunca melhora). Validação agrupada por município.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import brier_score_loss, mean_pinball_loss
from sklearn.model_selection import GroupKFold

QUANTIL = 0.9
CATEGORICAS = [False, True, False, False]   # d_km, tipo, hora, dia_semana
BIN_KM = 10


@dataclass
class ModeloSLA:
    transportadora: str
    reg: HistGradientBoostingRegressor
    clf: HistGradientBoostingClassifier
    tipos: list
    metricas: dict
    d_min_obs: float
    d_max_obs: float
    amostra: pd.DataFrame


def amostra(d) -> pd.DataFrame:
    """OS não canceladas com distância origem→sede, tipo, hora/dia da abertura e se é fora da cidade-base."""
    os_ = d.os[d.os["status"].ne("Cancelado") & d.os["lead_time_d"].notna() & d.os["dt_abertura"].notna()].copy()
    os_["origem"] = os_["codigo_polo"].where(os_["transportadora"].eq("POLO"), "OGEA")
    os_ = os_.merge(d.dist.rename(columns={"codigo_polo": "origem"}), on=["origem", "cod_ibge"], how="inner")
    base = d.polos.set_index("codigo_polo")["cod_ibge"].astype("Int64")
    os_["fora_da_base"] = os_["cod_ibge"].ne(os_["origem"].map(base)).fillna(True).astype(bool)
    os_["hora"] = os_["dt_abertura"].dt.hour
    os_["dia_semana"] = os_["dt_abertura"].dt.dayofweek
    return os_[["transportadora", "origem", "cod_ibge", "tipo_atendimento", "d_km", "fora_da_base", "hora",
                "dia_semana", "lead_time_d", "no_prazo"]].reset_index(drop=True)


def _X(df: pd.DataFrame, tipos: list) -> np.ndarray:
    tipo = pd.Categorical(df["tipo_atendimento"], categories=tipos).codes.astype(float)
    tipo[tipo < 0] = np.nan
    return np.column_stack([df["d_km"].to_numpy(float), tipo, df["hora"].to_numpy(float),
                            df["dia_semana"].to_numpy(float)])


def _modelos(random_state: int):
    reg = HistGradientBoostingRegressor(loss="quantile", quantile=QUANTIL, monotonic_cst=[1, 0, 0, 0],
                                        categorical_features=CATEGORICAS, max_iter=200, learning_rate=0.08,
                                        random_state=random_state)
    clf = HistGradientBoostingClassifier(monotonic_cst=[-1, 0, 0, 0], categorical_features=CATEGORICAS,
                                         max_iter=200, learning_rate=0.08, random_state=random_state)
    return reg, clf


def _referencia(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Referência ingênua: quantil do LT e % no prazo por faixa de 10 km."""
    b_tr = (train["d_km"] // BIN_KM).astype(int)
    b_te = (test["d_km"] // BIN_KM).astype(int)
    q = train.groupby(b_tr)["lead_time_d"].quantile(QUANTIL)
    p = train.groupby(b_tr)["no_prazo"].mean()
    lt = b_te.map(q).fillna(train["lead_time_d"].quantile(QUANTIL)).to_numpy()
    pr = b_te.map(p).fillna(train["no_prazo"].mean()).to_numpy()
    return lt, pr


def ajustar(am: pd.DataFrame, transportadora: str, n_splits: int = 5, random_state: int = 0) -> ModeloSLA:
    df = am[am["transportadora"].eq(transportadora)]
    if transportadora == "POLO":
        df = df[df["fora_da_base"]]
    lo, hi = df["d_km"].quantile([0.01, 0.99])
    df = df[df["d_km"].between(lo, hi)].reset_index(drop=True)
    tipos = sorted(df["tipo_atendimento"].dropna().unique().tolist())
    X = _X(df, tipos)
    y_lt, y_ok, grupos = df["lead_time_d"].to_numpy(), df["no_prazo"].astype(int).to_numpy(), df["cod_ibge"]

    n_splits = min(n_splits, grupos.nunique())
    pin_m, pin_b, bri_m, bri_b = [], [], [], []
    for tr, te in GroupKFold(n_splits=n_splits).split(X, y_lt, grupos):
        reg, clf = _modelos(random_state)
        reg.fit(X[tr], y_lt[tr])
        clf.fit(X[tr], y_ok[tr])
        lt_ref, pr_ref = _referencia(df.iloc[tr], df.iloc[te])
        pin_m.append(mean_pinball_loss(y_lt[te], reg.predict(X[te]), alpha=QUANTIL))
        pin_b.append(mean_pinball_loss(y_lt[te], lt_ref, alpha=QUANTIL))
        if len(np.unique(y_ok[tr])) > 1:
            bri_m.append(brier_score_loss(y_ok[te], clf.predict_proba(X[te])[:, 1]))
            bri_b.append(brier_score_loss(y_ok[te], pr_ref))

    reg, clf = _modelos(random_state)
    reg.fit(X, y_lt)
    clf.fit(X, y_ok)
    metricas = {
        "n_os": int(len(df)), "n_municipios": int(grupos.nunique()), "folds": n_splits,
        "pinball_modelo": float(np.mean(pin_m)), "pinball_referencia": float(np.mean(pin_b)),
        "brier_modelo": float(np.mean(bri_m)) if bri_m else None,
        "brier_referencia": float(np.mean(bri_b)) if bri_b else None,
        "pct_prazo_observado": float(df["no_prazo"].mean()),
    }
    return ModeloSLA(transportadora, reg, clf, tipos, metricas, float(lo), float(hi), df)


def curva(m: ModeloSLA, n_pontos: int = 60, n_amostra: int = 1500, random_state: int = 0) -> pd.DataFrame:
    """Dependência parcial: para cada distância, média das previsões sobre OS reais (mix real de tipo/hora/dia)."""
    grid = np.linspace(m.d_min_obs, m.d_max_obs, n_pontos)
    base = m.amostra.sample(min(n_amostra, len(m.amostra)), random_state=random_state)
    X = _X(base, m.tipos)
    lt, pr = [], []
    for dk in grid:
        X[:, 0] = dk
        lt.append(float(np.mean(m.reg.predict(X))))
        pr.append(float(np.mean(m.clf.predict_proba(X)[:, 1])))
    return pd.DataFrame({"d_km": grid, "lt_p90_d": lt, "p_prazo": pr, "transportadora": m.transportadora})


def raio_sugerido(c: pd.DataFrame, alvo: float) -> dict:
    """Maior distância (dentro da faixa observada) em que a chance prevista de cumprir o prazo fica ≥ alvo."""
    abaixo = c[c["p_prazo"] < alvo]
    if abaixo.empty:
        return {"km": float(c["d_km"].max()), "limitado_pelo_dado": True,
                "texto": f"Em toda a faixa observada (até {c['d_km'].max():.0f} km) a chance prevista fica acima "
                         "do alvo; além disso não há evidência nos dados."}
    if abaixo.index[0] == c.index[0]:
        return {"km": 0.0, "limitado_pelo_dado": False,
                "texto": f"Já na menor distância observada ({c['d_km'].min():.0f} km) a chance fica abaixo do alvo."}
    ok = c.loc[: abaixo.index[0] - 1]
    km = float(ok["d_km"].max())
    return {"km": km, "limitado_pelo_dado": False,
            "texto": f"Até ~{km:.0f} km a chance prevista de cumprir o prazo fica acima do alvo."}


def comparacao_mistas(d) -> pd.DataFrame:
    """Nas cidades onde Ógea e polo atuam juntos: mesma cidade, dois operadores (controla o efeito cidade)."""
    g = (d.os.groupby(["cod_ibge", "transportadora"])
         .agg(vol=("id_workfinity", "size"), lt=("lead_time_d", "mean"), prazo=("no_prazo", "mean"))
         .unstack("transportadora"))
    g.columns = [f"{a}_{b.lower()}" for a, b in g.columns]
    g = g.dropna(subset=["vol_ogea", "vol_polo"]).reset_index()
    return g.merge(d.municipios[["cod_ibge", "municipio"]], on="cod_ibge")
