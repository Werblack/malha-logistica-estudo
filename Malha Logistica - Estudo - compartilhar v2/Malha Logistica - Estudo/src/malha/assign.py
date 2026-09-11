"""Motor determinístico do simulador (substitui o MILP na tela principal).

Pergunta: com este raio (km, linha reta) por polo, quais locais o polo alcança? Responde na hora,
sem solver, para os sliders andarem fluido:

- Volume que já é do polo (jul/26) fica com ele — não é redistribuído entre polos.
- Cada local com volume Ógea é 100% capturado (binário) pelo polo habilitado mais próximo cujo
  raio o alcança (regra anti-canibalização: nunca dois polos, nunca conta em dobro). Se nenhum
  polo alcança, o local continua com a proporção real de hoje (ver `share_polo`/`status` abaixo).
- Status/cor do local reflete a proporção REAL de hoje (`share_polo`), não "tem algum polo = polo":
  um local com 1% de share polo (ex.: Assis, ver TEMPLATE) não vira "Território PagResolve" só
  por ter uma OS de polo lá. Só fica 100% polo quando de fato capturado no cenário atual.
- Os 6 bairros da capital (Campo Belo, Casa Verde, Itaquera, Vila Prudente, Vila Romana, Faria
  Lima) só podem ser capturados pelo próprio polo designado (`locais.NODE_POLO_DESIGNADO`) — nunca
  por um vizinho mais central, mesmo que geograficamente mais perto.
- Exceção manual (`Params.override_local`): o usuário pode forçar um local específico para um polo
  escolhido ou para `OGEA_FORCADA` (fica 100% Ógea), independente do raio. Vence qualquer regra
  automática acima, inclusive o território exclusivo da capital.
- Técnicos sugeridos por polo = teto(volume absorvido / produtividade mensal da região do PRÓPRIO
  polo — Capital/Grande SP ou Interior, pela região imediata do IBGE onde ele está sediado).
- Novo CMU do polo = (custo atual + técnicos sugeridos × custo/técnico) / (volume base + absorvido).

Duas camadas:
- `preparar()` faz uma vez só o que não depende dos sliders: agrega as 53 mil OS por local, casa
  a região de cada polo, e — o que mais importava para a velocidade — ordena de uma vez por todas
  as arestas polo→local por (distância, polo). Isso é o que permite o núcleo (`_calcular`) resolver
  "qual o mais perto que alcança" só com máscara booleana + `np.unique`, em numpy puro, sem tocar
  em string nem em DataFrame — é o único jeito de ficar rápido o bastante para um slider (a versão
  em pandas, com `Series.map(função)` a cada chamada, levava ~140 ms; esta ficou < 2 ms, veja
  `tests/test_assign.py::test_simular_e_rapido_o_bastante`).
- `simular()` embrulha esse núcleo em DataFrames (para o Streamlit e a tabela de detalhe).
  `simular_rapido()` devolve só dicionários/listas prontos para virar JSON (para o app desktop,
  que chama isso a cada frame de slider pela ponte JS do PyWebView) — mesma regra, sem duplicar.

`src/malha/optimize.py` (MILP) continua no repositório como ferramenta avançada/offline; não é
mais chamado pela tela principal.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from malha.costs import novo_cmu, novo_custo_polo, produtividade_mensal
from malha.costs import tecnicos_sugeridos as _tecnicos_sugeridos
from malha.locais import NODE_POLO_DESIGNADO

REGIAO_GSP = "São Paulo"  # região imediata do IBGE (metropolitana), não um valor arbitrado


OGEA_FORCADA = "OGEA"  # valor de override_local que força o local a ficar 100% com a Ógea


@dataclass(frozen=True)
class Params:
    raio_km: float                 # raio global (km, linha reta)
    os_dia_gsp: float               # produtividade Capital/Grande SP (OS/técnico/dia)
    os_dia_interior: float          # produtividade Interior (OS/técnico/dia)
    custo_tecnico: float            # R$/técnico novo/mês
    dias_uteis_mes: int = 22
    raio_polo: dict = field(default_factory=dict)     # override {codigo_polo: km} — "ajuste fino"
    override_local: dict = field(default_factory=dict)  # exceção manual {local_id: codigo_polo | OGEA_FORCADA}

    def raio(self, codigo_polo: str) -> float:
        return float(self.raio_polo.get(codigo_polo, self.raio_km))


@dataclass
class Preparado:
    """Tudo o que não muda com os sliders. Calcule uma vez (`preparar`) e reuse em todo `simular*`."""
    base: pd.DataFrame          # index local_id (650 linhas): nome_local, lat, lon, vol_ogea, vol_polo_hoje, vol_total...
    polos: pd.DataFrame         # 1 linha por polo habilitado (48, sem o armazém Ógea), na MESMA ordem dos arrays abaixo
    vol_ogea: np.ndarray        # (n_locais,) — mesma ordem de `base.index`
    vol_polo_hoje: np.ndarray
    vol_total: np.ndarray
    edge_local_idx: np.ndarray  # arestas polo->local com vol_ogea>0, JÁ ordenadas por (d_km, polo_idx)
    edge_polo_idx: np.ndarray
    edge_d_km: np.ndarray
    local_pos: dict            # local_id -> posição em `base` (para aplicar `Params.override_local`)
    polo_pos: dict              # codigo_polo -> posição em `polos`


@dataclass
class Resultado:
    locais: pd.DataFrame    # 1 linha por local: vol_ogea, vol_polo_hoje, vol_total, status, polo_captura, dist_km
    polos: pd.DataFrame     # 1 linha por polo: v0, vol_absorvido, tecnicos_sugeridos, custo_novo, cmu_novo...
    kpis: dict


def _demanda_por_local(os_: pd.DataFrame) -> pd.DataFrame:
    g = os_.groupby(["local_id", "transportadora"]).size().unstack("transportadora", fill_value=0)
    g.columns = [f"vol_{c.lower()}" for c in g.columns]
    for c in ("vol_ogea", "vol_polo"):
        if c not in g.columns:
            g[c] = 0
    return g[["vol_ogea", "vol_polo"]]


def preparar(d, kpis_polos: pd.DataFrame) -> Preparado:
    """d: malha.datasets.Dados. kpis_polos: baseline.polo_kpis(d). Chame uma vez só — é o custo caro
    (agregar 53 mil OS, casar região, ordenar as arestas). Guarde o `Preparado` e reuse a cada slider."""
    locais = d.locais.set_index("local_id")
    dem = _demanda_por_local(d.os)
    base = locais.join(dem, how="left").fillna({"vol_ogea": 0.0, "vol_polo": 0.0})
    base = base.rename(columns={"vol_polo": "vol_polo_hoje"})
    base["vol_total"] = base["vol_ogea"] + base["vol_polo_hoje"]

    # regra de inclusão estrita: só participa quem tem técnico ativo hoje (aba CMU) — sem polo fantasma
    # (na prática já é exatamente `status_bd == "ATIVO"`, mas o critério de negócio é este, não o outro)
    k = kpis_polos[kpis_polos["tec_ativos"].fillna(0).gt(0)].copy()
    mun_regiao = d.municipios.set_index("cod_ibge")["regiao_imediata"]
    k["regiao_imediata"] = k["cod_ibge"].map(mun_regiao)
    k["regiao_gsp"] = k["regiao_imediata"].eq(REGIAO_GSP)
    polos = k[["codigo_polo", "polo_nome", "status_bd", "lat", "lon", "tec_ativos", "volume", "custo_total",
              "regiao_gsp", "alcance_p90_km"]].copy()
    polos = polos.rename(columns={"volume": "v0", "custo_total": "custo_atual", "tec_ativos": "t0"})
    polos["t0"] = polos["t0"].fillna(0.0)
    polos = polos.reset_index(drop=True)

    local_pos = {lid: i for i, lid in enumerate(base.index)}
    polo_pos = {c: i for i, c in enumerate(polos["codigo_polo"])}
    com_demanda = set(base.index[base["vol_ogea"] > 0])

    dist = d.dist_local[d.dist_local["codigo_polo"].isin(polos["codigo_polo"].tolist())
                        & d.dist_local["local_id"].isin(com_demanda)]
    # território exclusivo: os 6 bairros da capital (Campo Belo, Casa Verde, Itaquera, Vila Prudente,
    # Vila Romana, Faria Lima) só podem ser capturados pelo próprio polo, nunca por um vizinho mais
    # perto do centro (sem isso, um polo central "absorvia" bairros que nunca atendeu)
    designado = dist["local_id"].map(NODE_POLO_DESIGNADO)
    dist = dist[designado.isna() | designado.eq(dist["codigo_polo"])]
    edge_local_idx = dist["local_id"].map(local_pos).to_numpy(dtype=np.int64)
    edge_polo_idx = dist["codigo_polo"].map(polo_pos).to_numpy(dtype=np.int64)
    edge_d_km = dist["d_km"].to_numpy(dtype=np.float64)

    # ordena de uma vez por (d_km, polo_idx) — no `simular` só falta filtrar por raio (máscara preserva a ordem)
    ordem = np.lexsort((edge_polo_idx, edge_d_km))
    return Preparado(
        base=base, polos=polos,
        vol_ogea=base["vol_ogea"].to_numpy(dtype=np.float64),
        vol_polo_hoje=base["vol_polo_hoje"].to_numpy(dtype=np.float64),
        vol_total=base["vol_total"].to_numpy(dtype=np.float64),
        edge_local_idx=edge_local_idx[ordem], edge_polo_idx=edge_polo_idx[ordem], edge_d_km=edge_d_km[ordem],
        local_pos=local_pos, polo_pos=polo_pos,
    )


LIMIAR_MAIORIA = 0.999  # acima disso, o local conta como "100% polo" (não é preciso ser exato: dado real)
LIMIAR_MINORIA = 0.001  # abaixo disso, "100% ógea"


@dataclass
class _Nucleo:
    """Saída crua do cálculo (numpy puro) — as duas funções públicas só embrulham isto."""
    polo_captura_idx: np.ndarray     # (n_locais,) índice do polo em `prep.polos`, -1 se não capturado
    dist_captura_km: np.ndarray
    vol_absorvido_local: np.ndarray
    share_polo: np.ndarray           # 0 a 1: fração do local hoje com a PagResolve (proporção real, não binária)
    status: np.ndarray               # "sem_volume" | "polo" | "ogea" | "misto"
    override_manual: np.ndarray      # (n_locais,) bool: local com exceção manual do usuário aplicada
    raio_por_polo: np.ndarray
    produtividade_por_polo: np.ndarray
    vol_absorvido_polo: np.ndarray
    n_locais_polo: np.ndarray
    tecnicos_sugeridos: np.ndarray
    custo_novo: np.ndarray
    volume_novo: np.ndarray
    cmu_novo: np.ndarray
    cmu_hoje: np.ndarray


def _calcular(prep: Preparado, params: Params) -> _Nucleo:
    n_locais, n_polos = len(prep.base), len(prep.polos)
    raio_por_polo = np.fromiter((params.raio(c) for c in prep.polos["codigo_polo"]), dtype=np.float64, count=n_polos)

    raio_edge = raio_por_polo[prep.edge_polo_idx]
    mask = prep.edge_d_km <= raio_edge
    lidx, pidx, dkm = prep.edge_local_idx[mask], prep.edge_polo_idx[mask], prep.edge_d_km[mask]

    polo_captura_idx = np.full(n_locais, -1, dtype=np.int64)
    dist_captura_km = np.full(n_locais, np.nan)
    if lidx.size:
        # arestas já vêm ordenadas por (d_km, polo_idx) desde `preparar` -> 1ª ocorrência = mais perto
        # (empate de distância desempata pelo polo de índice menor, sempre o mesmo -> determinístico)
        uniq_local, primeira = np.unique(lidx, return_index=True)
        polo_captura_idx[uniq_local] = pidx[primeira]
        dist_captura_km[uniq_local] = dkm[primeira]

    # exceção manual do usuário (override_local): vence qualquer regra automática (raio, distância,
    # território exclusivo da capital) — é isso que "exceção manual" quer dizer.
    override_manual = np.zeros(n_locais, dtype=bool)
    for lid, valor in params.override_local.items():
        i = prep.local_pos.get(lid)
        if i is None:
            continue
        override_manual[i] = True
        if valor == OGEA_FORCADA:
            polo_captura_idx[i] = -1
            dist_captura_km[i] = np.nan
        else:
            j = prep.polo_pos.get(valor)
            if j is not None:
                polo_captura_idx[i] = j
                dist_captura_km[i] = np.nan

    capturado = polo_captura_idx >= 0
    vol_absorvido_local = np.where(capturado, prep.vol_ogea, 0.0)

    # proporção real (não é "tem algum polo -> 100% polo"): um local com 1% de share polo não vira
    # "Território PagResolve" só por ter havido uma OS de polo lá; só reflete maioria de fato, e só
    # vira 100% polo quando a regra de negócio manda (capturado no cenário atual).
    vol_total_seguro = np.where(prep.vol_total > 0, prep.vol_total, 1.0)
    share_polo_hoje = prep.vol_polo_hoje / vol_total_seguro
    share_polo = np.where(capturado, 1.0, share_polo_hoje)
    status = np.select(
        [prep.vol_total == 0, share_polo >= LIMIAR_MAIORIA, share_polo <= LIMIAR_MINORIA],
        ["sem_volume", "polo", "ogea"], default="misto")

    if capturado.any():
        vol_absorvido_polo = np.bincount(polo_captura_idx[capturado], weights=vol_absorvido_local[capturado], minlength=n_polos)
        n_locais_polo = np.bincount(polo_captura_idx[capturado], minlength=n_polos)
    else:
        vol_absorvido_polo = np.zeros(n_polos)
        n_locais_polo = np.zeros(n_polos, dtype=np.int64)

    regiao_gsp = prep.polos["regiao_gsp"].to_numpy()
    produtividade_por_polo = np.where(regiao_gsp, produtividade_mensal(params.os_dia_gsp, params.dias_uteis_mes),
                                     produtividade_mensal(params.os_dia_interior, params.dias_uteis_mes))
    tecnicos = _tecnicos_sugeridos(vol_absorvido_polo, produtividade_por_polo)
    custo_atual = prep.polos["custo_atual"].to_numpy()
    v0 = prep.polos["v0"].to_numpy()
    custo_novo = novo_custo_polo(custo_atual, tecnicos, params.custo_tecnico)
    cmu_hoje = np.where(v0 > 0, custo_atual / np.where(v0 > 0, v0, 1.0), np.nan)

    return _Nucleo(
        polo_captura_idx=polo_captura_idx, dist_captura_km=dist_captura_km,
        vol_absorvido_local=vol_absorvido_local, share_polo=share_polo, status=status,
        override_manual=override_manual, raio_por_polo=raio_por_polo,
        produtividade_por_polo=produtividade_por_polo, vol_absorvido_polo=vol_absorvido_polo,
        n_locais_polo=n_locais_polo, tecnicos_sugeridos=tecnicos, custo_novo=custo_novo,
        volume_novo=v0 + vol_absorvido_polo, cmu_novo=novo_cmu(custo_novo, v0, vol_absorvido_polo),
        cmu_hoje=cmu_hoje,
    )


def _kpis(prep: Preparado, nu: _Nucleo, custo_tecnico: float) -> dict:
    total = float(prep.vol_total.sum())
    vol_ogea_hoje = float(prep.vol_ogea.sum())
    vol_absorvido = float(nu.vol_absorvido_polo.sum())
    vol_ogea_cen = vol_ogea_hoje - vol_absorvido
    vol_novo_total = float(nu.volume_novo.sum())
    return {
        "total_os": total,
        "vol_ogea_hoje": vol_ogea_hoje, "share_ogea_hoje": vol_ogea_hoje / total if total else float("nan"),
        "vol_ogea_cenario": vol_ogea_cen, "share_ogea_cenario": vol_ogea_cen / total if total else float("nan"),
        "vol_absorvido": vol_absorvido,
        "locais_capturados": int((nu.vol_absorvido_local > 0).sum()),
        "tecnicos_sugeridos": float(nu.tecnicos_sugeridos.sum()),
        "custo_tecnicos_novo": float((nu.tecnicos_sugeridos * custo_tecnico).sum()),
        "cmu_medio_novo": float(nu.custo_novo.sum() / vol_novo_total) if vol_novo_total else float("nan"),
    }


def simular(prep: Preparado, params: Params) -> Resultado:
    """Para o Streamlit / relatório: embrulha o núcleo em DataFrames (mais confortável de exibir)."""
    nu = _calcular(prep, params)
    codigos = prep.polos["codigo_polo"].to_numpy()
    capturado = nu.polo_captura_idx >= 0
    polo_captura_str = np.where(capturado, codigos[np.clip(nu.polo_captura_idx, 0, None)], None)

    locais_out = prep.base.assign(
        polo_captura=pd.array(polo_captura_str, dtype="string"), dist_captura_km=nu.dist_captura_km,
        vol_absorvido=nu.vol_absorvido_local, vol_ogea_cen=prep.vol_ogea - nu.vol_absorvido_local,
        share_polo=nu.share_polo, status=nu.status, override_manual=nu.override_manual,
    ).reset_index()

    polos_out = prep.polos.assign(
        raio_km=nu.raio_por_polo, produtividade_mensal=nu.produtividade_por_polo,
        vol_absorvido=nu.vol_absorvido_polo, locais_capturados=nu.n_locais_polo,
        tecnicos_sugeridos=nu.tecnicos_sugeridos, custo_novo=nu.custo_novo, volume_novo=nu.volume_novo,
        cmu_novo=nu.cmu_novo, cmu_hoje=nu.cmu_hoje,
    )

    kpis = _kpis(prep, nu, params.custo_tecnico)
    return Resultado(locais_out, polos_out, kpis)


def simular_rapido(prep: Preparado, params: Params) -> dict:
    """Para o app desktop: só numpy -> dict/list prontos para JSON, sem passar por DataFrame nenhum
    (é o que faz a ponte JS do PyWebView responder a tempo de acompanhar o slider em tempo real)."""
    nu = _calcular(prep, params)
    codigos = prep.polos["codigo_polo"].to_numpy()

    locais = [{
        "local_id": str(lid), "status": str(nu.status[i]), "share_polo": float(nu.share_polo[i]),
        "vol_total": float(prep.vol_total[i]), "vol_ogea_cen": float(prep.vol_ogea[i] - nu.vol_absorvido_local[i]),
        "vol_polo_hoje": float(prep.vol_polo_hoje[i]),
        "polo_captura": (str(codigos[nu.polo_captura_idx[i]]) if nu.polo_captura_idx[i] >= 0 else None),
        "override_manual": bool(nu.override_manual[i]),
    } for i, lid in enumerate(prep.base.index)]

    polos = [{
        "codigo_polo": str(r.codigo_polo), "polo_nome": str(r.polo_nome), "status_bd": str(r.status_bd),
        "lat": float(r.lat), "lon": float(r.lon), "raio_km": float(nu.raio_por_polo[i]),
        "t0": float(r.t0), "v0": float(r.v0), "regiao_gsp": bool(r.regiao_gsp),
        "alcance_p90_km": _nanfloat(r.alcance_p90_km),
        "vol_absorvido": float(nu.vol_absorvido_polo[i]), "locais_capturados": int(nu.n_locais_polo[i]),
        "tecnicos_sugeridos": float(nu.tecnicos_sugeridos[i]), "custo_novo": float(nu.custo_novo[i]),
        "volume_novo": float(nu.volume_novo[i]), "cmu_novo": _nanfloat(nu.cmu_novo[i]), "cmu_hoje": _nanfloat(nu.cmu_hoje[i]),
    } for i, r in enumerate(prep.polos.itertuples(index=False))]

    kpis = _kpis(prep, nu, params.custo_tecnico)
    kpis = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in kpis.items()}
    return {"locais": locais, "polos": polos, "kpis": kpis}


def _nanfloat(x):
    x = float(x)
    return None if np.isnan(x) else x
