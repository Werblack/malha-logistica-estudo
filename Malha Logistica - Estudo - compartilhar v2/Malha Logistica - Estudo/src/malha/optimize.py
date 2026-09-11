"""Motor de decisão: localização de instalações com capacidade (MILP em PuLP/HiGHS), nível município.

Pergunta central: quanto do volume da Ógea a PagResolve consegue absorver, com quais polos e quantos técnicos,
e quanto isso custa.

- Volume que um polo já atende fica com ele enquanto estiver aberto (consome capacidade).
- Volume redistribuível de cada cidade = OS Ógea dos tipos absorvíveis + volume de polos que fecharem.
- Um polo só recebe volume novo de cidades dentro do seu raio (linha reta).
- Capacidade = equipe atual (o que ela já prova fazer) + técnicos novos × meta (mediana observada).
- Etapa 1: minimizar o volume que fica na Ógea. Etapa 2: menor custo mantendo esse volume.

Variáveis: z_j (polo aberto), t_j (técnicos, inteiro), q_ij (OS da cidade i para o polo j), g_i (OS na Ógea).
"""
import math
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pulp

from malha.costs import capacidade_atual
from malha.geo.distance import haversine_km
from malha.scenario import Scenario

DESEMPATE_KM = 1e-3   # R$ simbólico por OS·km, só para preferir o polo mais perto entre soluções de mesmo custo
STATUS_OK = ("Base", "Optimal", "Viável")


@dataclass
class Instancia:
    cidades: pd.DataFrame   # index cod_ibge: total, w_polo, w_abs, w_fix, preco, custo_abs, custo_fixo_ogea, regiao
    polos: pd.DataFrame     # index codigo_polo: nome, status, t0, custo_atual, v0, cap0, k, raio_km, lat, lon
    atual: pd.DataFrame     # cod_ibge, codigo_polo, vol  (volume atual dos polos)
    dist: pd.DataFrame      # codigo_polo, cod_ibge, d_km


@dataclass
class Resultado:
    status: str
    mensagem: str
    kpis: dict
    cidades: pd.DataFrame
    polos: pd.DataFrame
    fluxos: pd.DataFrame
    avisos: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in STATUS_OK


# --------------------------------------------------------------------------- montagem da instância

def instancia_de_dados(d, kpis_polos: pd.DataFrame, sc: Scenario) -> Instancia:
    os_ = d.os[d.os["status"].isin(sc.status_incluidos)]
    ogea = os_["transportadora"].eq("OGEA")
    absorv = ogea & os_["tipo_atendimento"].isin(sc.tipos_absorviveis)
    mun = d.municipios.set_index("cod_ibge")

    c = pd.DataFrame(index=mun.index)
    c["total"] = os_.groupby("cod_ibge").size()
    c["w_polo"] = os_[~ogea].groupby("cod_ibge").size()
    c["w_abs"] = os_[absorv].groupby("cod_ibge").size()
    c["w_fix"] = os_[ogea & ~absorv].groupby("cod_ibge").size()
    c["custo_abs"] = os_[absorv].groupby("cod_ibge")["cmu_os"].sum()
    c["custo_fixo_ogea"] = os_[ogea & ~absorv].groupby("cod_ibge")["cmu_os"].sum()
    c = c.fillna(0)
    preco_global = float(os_.loc[absorv, "cmu_os"].mean()) if absorv.any() else float(os_.loc[ogea, "cmu_os"].mean())
    c["preco"] = np.where(c["w_abs"] > 0, c["custo_abs"] / c["w_abs"].where(c["w_abs"] > 0, 1), preco_global)
    c["regiao"] = mun["regiao_imediata"]
    c = c[c["total"] > 0]

    atual = os_[~ogea].groupby(["cod_ibge", "codigo_polo"]).size().rename("vol").reset_index()
    custo_atual = os_[~ogea].groupby("codigo_polo")["cmu_os"].sum()
    v0 = atual.groupby("codigo_polo")["vol"].sum()

    kp = kpis_polos[kpis_polos["status_bd"].isin(["ATIVO", "DORMENTE"]) & ~kpis_polos["excluir"]]
    raio = dict(sc.raio_polo)
    rows = []
    for r in kp.itertuples(index=False):
        ativo = r.status_bd == "ATIVO"
        t0 = float(r.tec_ativos) if ativo and pd.notna(r.tec_ativos) else 0.0
        vol0 = float(v0.get(r.codigo_polo, 0.0))
        rows.append({"codigo_polo": r.codigo_polo, "nome": r.polo_nome, "status": r.status_bd, "t0": t0,
                     "custo_atual": float(custo_atual.get(r.codigo_polo, 0.0)), "v0": vol0,
                     "cap0": capacidade_atual(sc.meta_os_tec, vol0, t0, sc.usar_prod_observada),
                     "k": sc.meta_os_tec, "raio_km": float(raio.get(r.codigo_polo, sc.raio_km)),
                     "lat": float(r.lat), "lon": float(r.lon)})
    for cod in sc.candidatos_novos:
        if cod not in mun.index:
            continue
        codigo = f"NOVO-{cod}"
        rows.append({"codigo_polo": codigo, "nome": f"Hub novo {mun.at[cod, 'municipio']}", "status": "NOVO",
                     "t0": 0.0, "custo_atual": 0.0, "v0": 0.0, "cap0": 0.0, "k": sc.meta_os_tec,
                     "raio_km": float(raio.get(codigo, sc.raio_km)),
                     "lat": float(mun.at[cod, "lat"]), "lon": float(mun.at[cod, "lon"])})
    polos = pd.DataFrame(rows).set_index("codigo_polo")

    dist = d.dist[d.dist["codigo_polo"].isin(polos.index)]
    novos = polos[polos["status"].eq("NOVO")]
    if len(novos):
        extra = pd.DataFrame({
            "codigo_polo": np.repeat(novos.index.to_numpy(), len(mun)),
            "cod_ibge": np.tile(mun.index.to_numpy(), len(novos)),
            "d_km": haversine_km(novos["lat"].to_numpy()[:, None], novos["lon"].to_numpy()[:, None],
                                 mun["lat"].to_numpy()[None, :], mun["lon"].to_numpy()[None, :]).ravel()})
        dist = pd.concat([dist, extra], ignore_index=True)
    return Instancia(cidades=c, polos=polos, atual=atual[atual["codigo_polo"].isin(polos.index)], dist=dist)


# --------------------------------------------------------------------------- saída comum

def _montar(inst: Instancia, sc: Scenario, zv: dict, tv: dict, qv: dict, gv: dict,
            status: str, mensagem: str, avisos: list, tempo: float) -> Resultado:
    cid, pol = inst.cidades, inst.polos
    orf = inst.atual.assign(aberto=inst.atual["codigo_polo"].map(zv).fillna(0))

    c = cid[["total", "w_polo", "w_abs", "w_fix", "preco", "regiao"]].copy()
    c["ogea_base"] = c["w_abs"] + c["w_fix"]
    c["g"] = pd.Series(gv, dtype=float).reindex(c.index).fillna(c["w_abs"])
    c["ogea_cen"] = c["w_fix"] + c["g"]
    c["polo_cen"] = c["total"] - c["ogea_cen"]
    c["share_ogea_base"] = c["ogea_base"] / c["total"]
    c["share_ogea_cen"] = c["ogea_cen"] / c["total"]
    c["absorvido"] = c["ogea_base"] - c["ogea_cen"]
    c["status_cen"] = np.select([c["polo_cen"].le(0.5), c["ogea_cen"].le(0.5)], ["100_ogea", "100_polo"], "misto")

    fl = [{"cod_ibge": i, "codigo_polo": j, "vol": v, "tipo": "absorvido"} for (i, j), v in qv.items() if v > 1e-6]
    fl += [{"cod_ibge": r.cod_ibge, "codigo_polo": r.codigo_polo, "vol": r.vol, "tipo": "atual"}
           for r in orf[orf["aberto"] > 0.5].itertuples()]
    fluxos = pd.DataFrame(fl, columns=["cod_ibge", "codigo_polo", "vol", "tipo"])
    fluxos = fluxos.merge(inst.dist, on=["codigo_polo", "cod_ibge"], how="left")
    if len(fluxos):
        principal = (fluxos.groupby(["cod_ibge", "codigo_polo"])["vol"].sum().reset_index()
                     .sort_values("vol").drop_duplicates("cod_ibge", keep="last").set_index("cod_ibge")["codigo_polo"])
        c["polo_principal_cen"] = principal.reindex(c.index)
    else:
        c["polo_principal_cen"] = pd.NA

    p = pol[["nome", "status", "t0", "v0", "cap0", "k", "raio_km", "custo_atual", "lat", "lon"]].copy()
    p["aberto"] = pd.Series(zv, dtype=float).reindex(p.index).fillna(0).round().astype(bool)
    p["tecnicos"] = pd.Series(tv, dtype=float).reindex(p.index).fillna(0).round()
    p.loc[~p["aberto"], "tecnicos"] = 0
    p["contratar"] = (p["tecnicos"] - p["t0"]).where(p["aberto"], -p["t0"])
    absorv = fluxos[fluxos["tipo"].eq("absorvido")]
    p["vol_absorvido"] = absorv.groupby("codigo_polo")["vol"].sum().reindex(p.index).fillna(0)
    p["cidades_absorvidas"] = absorv.groupby("codigo_polo")["cod_ibge"].nunique().reindex(p.index).fillna(0)
    p["volume"] = np.where(p["aberto"], p["v0"] + p["vol_absorvido"], 0.0)
    p["capacidade"] = np.where(p["aberto"], p["cap0"] + p["k"] * (p["tecnicos"] - p["t0"]), 0.0)
    p["utilizacao"] = p["volume"] / p["capacidade"].where(p["capacidade"] > 0)
    base = np.where(p["t0"] > 0, p["custo_atual"], sc.custo_abrir)
    p["custo"] = np.where(p["aberto"], base + sc.custo_tecnico * (p["tecnicos"] - p["t0"]), 0.0)
    p["cmu_base"] = p["custo_atual"] / p["v0"].where(p["v0"] > 0)
    p["cmu_cen"] = p["custo"] / p["volume"].where(p["volume"] > 0)

    custo_base = float(pol.loc[pol["t0"] > 0, "custo_atual"].sum() + cid["custo_abs"].sum() + cid["custo_fixo_ogea"].sum())
    custo_ogea_cen = float((c["g"] * c["preco"]).sum() + cid["custo_fixo_ogea"].sum())
    custo_desloc = sc.custo_km * float((absorv["vol"] * absorv["d_km"]).sum()) if sc.custo_km else 0.0
    custo_cen = float(p["custo"].sum()) + custo_ogea_cen + custo_desloc
    total = float(c["total"].sum())
    kpis = {
        "total_os": total,
        "ogea_base": float(c["ogea_base"].sum()), "ogea_cen": float(c["ogea_cen"].sum()),
        "share_ogea_base": float(c["ogea_base"].sum() / total), "share_ogea_cen": float(c["ogea_cen"].sum() / total),
        "absorvido": float(c["absorvido"].sum()),
        "ogea_fixo_tipos": float(c["w_fix"].sum()),
        "custo_base": custo_base, "custo_cen": custo_cen, "delta_custo": custo_cen - custo_base,
        "tec_base": float(pol["t0"].sum()), "tec_cen": float(p["tecnicos"].sum()),
        "tec_contratar": float(p.loc[p["aberto"], "contratar"].clip(lower=0).sum()),
        "polos_abertos": int(p["aberto"].sum()),
        "polos_reabertos": int((p["aberto"] & p["status"].eq("DORMENTE")).sum()),
        "hubs_novos": int((p["aberto"] & p["status"].eq("NOVO")).sum()),
        "polos_fechados": int((~p["aberto"] & p["status"].eq("ATIVO")).sum()),
        "cidades_absorvidas": int((c["absorvido"] > 0.5).sum()),
        "tempo_s": round(tempo, 2),
    }
    return Resultado(status, mensagem, kpis, c.reset_index(), p.reset_index(), fluxos, avisos)


def resultado_base(inst: Instancia, sc: Scenario) -> Resultado:
    """Situação de hoje, sem otimizar (reproduz o custo total da BD)."""
    pol = inst.polos
    zv = {j: float(pol.at[j, "status"] == "ATIVO") for j in pol.index}
    tv = {j: pol.at[j, "t0"] for j in pol.index}
    gv = inst.cidades["w_abs"].to_dict()
    return _montar(inst, sc, zv, tv, {}, gv, "Base", "Situação atual (jul/26)", [], 0.0)


# --------------------------------------------------------------------------- MILP

def _solver(time_limit: int):
    highs = pulp.HiGHS(msg=False, timeLimit=time_limit, gapRel=1e-4)
    if highs.available():
        return highs
    return pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit)


def _status(prob) -> str:
    st = pulp.LpStatus[prob.status]
    if st == "Optimal" and getattr(prob, "sol_status", None) == pulp.LpSolutionIntegerFeasible:
        return "Viável"   # parou no limite de tempo com solução boa, sem prova de ótimo
    return st


def resolver(inst: Instancia, sc: Scenario, time_limit: int = 60) -> Resultado:
    t_ini = time.time()
    cid, pol = inst.cidades, inst.polos
    avisos: list[str] = []
    trava = dict(sc.travas)
    fechados_usuario = {j for j, v in trava.items() if v == "fechado"}

    orf: dict = {}
    for r in inst.atual.itertuples(index=False):
        orf.setdefault(r.cod_ibge, []).append((r.codigo_polo, float(r.vol)))
    v0 = inst.atual.groupby("codigo_polo")["vol"].sum().reindex(pol.index, fill_value=0.0)
    redis_max = cid["w_abs"].add(inst.atual.groupby("cod_ibge")["vol"].sum(), fill_value=0).reindex(cid.index).fillna(0)

    arcs = inst.dist.merge(pol[["raio_km"]], left_on="codigo_polo", right_index=True)
    arcs = arcs[(arcs["d_km"] <= arcs["raio_km"]) & arcs["cod_ibge"].isin(redis_max.index[redis_max > 0])]
    arc_d = {(i, j): d for i, j, d in zip(arcs["cod_ibge"], arcs["codigo_polo"], arcs["d_km"])}
    por_cidade: dict = {}
    por_polo: dict = {}
    for i, j in arc_d:
        por_cidade.setdefault(i, []).append(j)
        por_polo.setdefault(j, []).append(i)

    P, I = list(pol.index), list(cid.index)
    prob = pulp.LpProblem("malha", pulp.LpMinimize)
    z = {j: pulp.LpVariable(f"z{n}", cat="Binary") for n, j in enumerate(P)}
    t = {j: pulp.LpVariable(f"t{n}", lowBound=0, cat="Integer") for n, j in enumerate(P)}
    q = {a: pulp.LpVariable(f"q{n}", lowBound=0) for n, a in enumerate(arc_d)}
    g = {i: pulp.LpVariable(f"g{n}", lowBound=0) for n, i in enumerate(I)}

    # polos abertos/fechados
    for j in P:
        st = pol.at[j, "status"]
        if j in trava:
            val = 1 if trava[j] == "aberto" else 0
        elif sc.modo == "simular":
            val = 1 if st == "ATIVO" else 0
        elif st == "ATIVO" and not sc.permitir_fechar_ativos:
            val = 1
        else:
            val = None
        if val is not None:
            z[j].lowBound = z[j].upBound = val

    # balanço de cada cidade
    for i in I:
        orfao = pulp.lpSum(v * (1 - z[j0]) for j0, v in orf.get(i, []))
        prob += pulp.lpSum(q[i, j] for j in por_cidade.get(i, [])) + g[i] == cid.at[i, "w_abs"] + orfao
        if sc.nao_devolver:
            devolvivel = cid.at[i, "w_abs"] + sum(v for j0, v in orf.get(i, []) if j0 in fechados_usuario)
            prob += g[i] <= devolvivel

    # capacidade e técnicos
    for j in P:
        k, t0, cap0 = pol.at[j, "k"], pol.at[j, "t0"], pol.at[j, "cap0"]
        recebido = pulp.lpSum(q[i, j] for i in por_polo.get(j, []))
        prob += recebido + v0[j] * z[j] <= cap0 * z[j] + k * (t[j] - t0 * z[j])
        tmax = t0 + math.ceil((v0[j] + sum(redis_max[i] for i in por_polo.get(j, []))) / k) + 1
        prob += t[j] <= tmax * z[j]
        prob += t[j] >= z[j]
        if sc.sem_demissao and t0 > 0:
            prob += t[j] >= t0 * z[j]
        if sc.vol_min_polo > 0:
            prob += recebido + v0[j] * z[j] >= sc.vol_min_polo * z[j]

    # share forçado por município / região (faceta "divisão de share")
    for cod, s in sc.share_municipio:
        if cod not in cid.index:
            continue
        alvo = s * cid.at[cod, "total"] - cid.at[cod, "w_fix"]
        val = min(max(alvo, 0.0), cid.at[cod, "w_abs"])
        if abs(val - alvo) > 0.5:
            avisos.append(f"Share alvo do município {cod} ajustado: só dá para mover o volume Ógea absorvível da cidade.")
        if val < cid.at[cod, "w_abs"] - 1e-6 and not por_cidade.get(cod):
            avisos.append(f"Share alvo do município {cod} ignorado: nenhum polo no raio.")
            continue
        prob += g[cod] == val
    for reg, s in sc.share_regiao:
        idx = [i for i in I if cid.at[i, "regiao"] == reg]
        if idx:
            prob += (pulp.lpSum(g[i] for i in idx) + float(cid.loc[idx, "w_fix"].sum())
                     == s * float(cid.loc[idx, "total"].sum()))

    dist_term = pulp.lpSum(d * q[a] for a, d in arc_d.items())
    custo = (
        pulp.lpSum((pol.at[j, "custo_atual"] if pol.at[j, "t0"] > 0 else sc.custo_abrir) * z[j]
                   + sc.custo_tecnico * (t[j] - pol.at[j, "t0"] * z[j]) for j in P)
        + pulp.lpSum(float(cid.at[i, "preco"]) * g[i] for i in I)
        + float(cid["custo_fixo_ogea"].sum())
        + sc.custo_km * dist_term
    )
    if sc.orcamento:
        prob += custo <= sc.orcamento

    solver = _solver(time_limit)
    # etapa 1: mínimo volume na Ógea
    prob.setObjective(pulp.lpSum(g.values()))
    prob.solve(solver)
    st1 = _status(prob)
    if st1 not in STATUS_OK:
        base = resultado_base(inst, sc)
        msg = ("Cenário inviável: verifique travas, shares forçados e orçamento." if st1 == "Infeasible"
               else f"Solver terminou com status {st1}.")
        return Resultado(st1, msg, base.kpis, base.cidades, base.polos, base.fluxos, avisos)
    g_star = pulp.value(pulp.lpSum(g.values()))

    # etapa 2: menor custo mantendo o volume absorvido
    prob += pulp.lpSum(g.values()) <= g_star + 1e-6
    prob.setObjective(custo + DESEMPATE_KM * dist_term)
    prob.solve(solver)
    st2 = _status(prob)
    if st2 not in STATUS_OK:
        return Resultado(st2, f"Etapa de custo terminou com status {st2}.", *_vazio(inst, sc), avisos)

    val = lambda v: v.value() or 0.0
    zv = {j: val(z[j]) for j in P}
    tv = {j: val(t[j]) for j in P}
    qv = {a: val(q[a]) for a in q}
    gv = {i: val(g[i]) for i in I}
    msg = {"Optimal": "Ótimo encontrado.",
           "Viável": f"Solução viável no limite de {time_limit}s (sem prova de ótimo)."}.get(st2, st2)
    if st1 == "Viável":
        msg += " Etapa 1 também parou no limite de tempo."
    return _montar(inst, sc, zv, tv, qv, gv, st2, msg, avisos, time.time() - t_ini)


def _vazio(inst, sc):
    b = resultado_base(inst, sc)
    return b.kpis, b.cidades, b.polos, b.fluxos
