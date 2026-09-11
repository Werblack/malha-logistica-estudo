"""Motor determinístico (assign.py): captura binária pelo polo habilitado mais próximo, sem solver."""
import pandas as pd
import pytest

from malha import assign
from malha.costs import novo_cmu, novo_custo_polo, produtividade_mensal, tecnicos_sugeridos
from malha.locais import FARIA_LIMA_LOCAL_ID


class _D:
    """Stub mínimo de malha.datasets.Dados: só o que assign.simular usa."""
    def __init__(self, os_, locais, dist_local, municipios):
        self.os = os_
        self.locais = locais
        self.dist_local = dist_local
        self.municipios = municipios


@pytest.fixture
def cenario():
    # cidade 1: 10 OS do polo A;  cidade 2: 20 OS Ógea a 30 km de A e 300 km de B;  cidade 3: 5 OS Ógea a 200 km de A e B
    os_ = pd.DataFrame({
        "local_id": ["L1"] * 10 + ["L2"] * 20 + ["L3"] * 5,
        "transportadora": ["POLO"] * 10 + ["OGEA"] * 20 + ["OGEA"] * 5,
    })
    locais = pd.DataFrame({
        "local_id": ["L1", "L2", "L3"], "cod_ibge": [1, 2, 3], "municipio": ["M1", "M2", "M3"],
        "nome_local": ["M1", "M2", "M3"], "lat": [0.0, 0.0, 0.0], "lon": [0.0, 0.0, 0.0],
        "capital_subnode": [False, False, False],
        "regiao_imediata": ["Interior", "Interior", "Interior"],
    })
    dist_local = pd.DataFrame({
        "codigo_polo": ["A", "A", "A", "B", "B", "B", "C", "C", "C"],
        "local_id": ["L1", "L2", "L3", "L1", "L2", "L3", "L1", "L2", "L3"],
        "d_km": [0.0, 30.0, 200.0, 300.0, 300.0, 200.0, 0.0, 30.0, 200.0],
    })
    municipios = pd.DataFrame({"cod_ibge": [1, 2, 3], "regiao_imediata": ["Interior", "Interior", "Interior"]})
    # A: ativo com técnico. B: SEM volume histórico (status DORMENTE) mas COM técnico -> a regra é
    # "tem técnico ativo", não o status; por isso B participa. C: tem volume/status ATIVO mas 0
    # técnicos (polo fantasma) -> tem que ficar de fora da simulação inteira, mesmo estando mais perto.
    kpis_polos = pd.DataFrame({
        "codigo_polo": ["A", "B", "C"], "polo_nome": ["Polo A", "Polo B", "Polo Fantasma C"],
        "status_bd": ["ATIVO", "DORMENTE", "ATIVO"],
        "lat": [0.0, 0.0, 0.0], "lon": [0.0, 0.0, 0.0], "cod_ibge": [1, 1, 1],
        "tec_ativos": [1.0, 1.0, 0.0], "volume": [10.0, 0.0, 3.0], "custo_total": [1500.0, 0.0, 200.0],
        "alcance_p90_km": [30.0, None, 5.0],
    })
    return assign.preparar(_D(os_, locais, dist_local, municipios), kpis_polos)


def _params(**kw):
    base = dict(raio_km=50.0, os_dia_gsp=6.0, os_dia_interior=10.0, custo_tecnico=1000.0)
    base.update(kw)
    return assign.Params(**base)


def test_polo_sem_tecnico_e_expurgado_mesmo_com_volume_e_mais_perto(cenario):
    # C (0 técnicos) não pode aparecer em lugar nenhum, mesmo tendo volume histórico e sendo o mais perto
    assert "C" not in cenario.polos["codigo_polo"].tolist()
    r = assign.simular(cenario, _params())
    assert "C" not in r.polos["codigo_polo"].tolist()
    assert set(r.polos["codigo_polo"]) == {"A", "B"}


def test_absorve_o_que_esta_no_raio_e_ignora_o_resto(cenario):
    r = assign.simular(cenario, _params())
    assert r.kpis["vol_absorvido"] == pytest.approx(20)     # L2 sim, L3 fora do raio de tudo
    assert r.kpis["locais_capturados"] == 1
    a = r.polos.set_index("codigo_polo").loc["A"]
    assert a["vol_absorvido"] == pytest.approx(20)
    # produtividade interior = 10 OS/dia * 22 = 220/mês -> ceil(20/220) = 1 técnico
    assert a["tecnicos_sugeridos"] == pytest.approx(1)
    assert a["custo_novo"] == pytest.approx(1500 + 1000)     # custo atual + 1 técnico novo
    assert a["cmu_novo"] == pytest.approx((1500 + 1000) / (10 + 20))


def test_raio_zero_nao_absorve_nada(cenario):
    r = assign.simular(cenario, _params(raio_km=0.0))
    assert r.kpis["vol_absorvido"] == pytest.approx(0)
    assert r.kpis["share_ogea_cenario"] == pytest.approx(r.kpis["share_ogea_hoje"])


def test_polo_sem_volume_historico_mas_com_tecnico_participa_normalmente(cenario):
    # B (DORMENTE no BD, mas tem técnico) — com raio suficiente, também captura
    r = assign.simular(cenario, _params(raio_km=50.0, raio_polo={"B": 250.0}))
    # L3 (200km de B) passa a ser alcançado só por B; L2 continua com A (mais perto)
    assert r.kpis["vol_absorvido"] == pytest.approx(25)
    b = r.polos.set_index("codigo_polo").loc["B"]
    assert b["vol_absorvido"] == pytest.approx(5)


def test_anti_canibalizacao_pega_o_mais_perto(cenario):
    r = assign.simular(cenario, _params(raio_km=310.0))   # A e B alcançam L2 e L3 (C nem existe na instância)
    loc = r.locais.set_index("local_id")
    assert loc.loc["L2", "polo_captura"] == "A"   # 30 km < 300 km
    assert loc.loc["L3", "polo_captura"] == "A"   # empate 200/200 -> desempate determinístico (A antes de B)
    # nunca conta em dobro: soma dos absorvidos por polo == absorvido total
    assert r.polos["vol_absorvido"].sum() == pytest.approx(r.kpis["vol_absorvido"])


def test_produtividade_gsp_dá_menos_tecnicos_que_interior():
    # mesma demanda absorvida, região GSP (6 OS/dia) precisa de menos técnicos que interior (3 OS/dia)
    gsp = tecnicos_sugeridos(132, produtividade_mensal(6.0))       # 132/mês -> 1 técnico
    interior = tecnicos_sugeridos(132, produtividade_mensal(3.0))  # 66/mês -> 2 técnicos
    assert gsp == 1
    assert interior == 2


def test_novo_cmu_sem_absorcao_reproduz_cmu_hoje():
    custo = novo_custo_polo(custo_atual=2000.0, tecnicos_sugeridos=0, custo_tecnico=1000.0)
    assert novo_cmu(custo, volume_base=100.0, volume_absorvido=0.0) == pytest.approx(20.0)


@pytest.fixture
def cenario_capital():
    """Nó da capital (Faria Lima) com dois polos candidatos: o designado (P015, mais longe) e um
    "central" (P999, mais perto, sem relação nenhuma com aquele bairro) — o central não pode roubar."""
    os_ = pd.DataFrame({"local_id": [FARIA_LIMA_LOCAL_ID] * 10, "transportadora": ["OGEA"] * 10})
    locais = pd.DataFrame({
        "local_id": [FARIA_LIMA_LOCAL_ID], "cod_ibge": [3550308], "municipio": ["São Paulo"],
        "nome_local": ["São Paulo (Faria Lima e demais bairros)"], "lat": [0.0], "lon": [0.0],
        "capital_subnode": [True], "regiao_imediata": ["São Paulo"],
    })
    dist_local = pd.DataFrame({
        "codigo_polo": ["P015", "P999"], "local_id": [FARIA_LIMA_LOCAL_ID, FARIA_LIMA_LOCAL_ID],
        "d_km": [20.0, 2.0],   # P999 está bem mais perto
    })
    municipios = pd.DataFrame({"cod_ibge": [3550308], "regiao_imediata": ["São Paulo"]})
    kpis_polos = pd.DataFrame({
        "codigo_polo": ["P015", "P999"], "polo_nome": ["Polo SP Faria Lima - P015", "Polo Central Fictício"],
        "status_bd": ["ATIVO", "ATIVO"], "lat": [0.0, 0.0], "lon": [0.0, 0.0], "cod_ibge": [3550308, 3550308],
        "tec_ativos": [5.0, 5.0], "volume": [1298.0, 5000.0], "custo_total": [40000.0, 100000.0],
        "alcance_p90_km": [10.0, 10.0],
    })
    return assign.preparar(_D(os_, locais, dist_local, municipios), kpis_polos)


def test_bairro_da_capital_so_pode_ser_capturado_pelo_proprio_polo(cenario_capital):
    r = assign.simular(cenario_capital, _params(raio_km=100.0))
    loc = r.locais.set_index("local_id").loc[FARIA_LIMA_LOCAL_ID]
    assert loc["polo_captura"] == "P015"          # não "P999", mesmo estando 10x mais perto
    p999 = r.polos.set_index("codigo_polo").loc["P999"]
    assert p999["vol_absorvido"] == pytest.approx(0)


def test_status_reflete_maioria_real_nao_qualquer_presenca_de_polo():
    # local com share polo pequeno (tipo Assis: ~1% polo) e NÃO capturado no cenário -> continua "ogea"
    # (misto de verdade, perto de 0), nunca "polo" só porque houve 1 OS de polo lá alguma vez
    os_ = pd.DataFrame({
        "local_id": ["L1"] * 111 + ["L1"] + ["L2"] * 5 + ["L2"] * 5,
        "transportadora": ["OGEA"] * 111 + ["POLO"] + ["OGEA"] * 5 + ["POLO"] * 5,
    })
    locais = pd.DataFrame({
        "local_id": ["L1", "L2"], "cod_ibge": [1, 2], "municipio": ["M1", "M2"], "nome_local": ["M1", "M2"],
        "lat": [0.0, 0.0], "lon": [0.0, 0.0], "capital_subnode": [False, False],
        "regiao_imediata": ["Interior", "Interior"],
    })
    dist_local = pd.DataFrame({"codigo_polo": [], "local_id": [], "d_km": []})   # nenhum polo alcança nada
    municipios = pd.DataFrame({"cod_ibge": [1, 2], "regiao_imediata": ["Interior", "Interior"]})
    kpis_polos = pd.DataFrame({
        "codigo_polo": ["A"], "polo_nome": ["Polo A"], "status_bd": ["ATIVO"], "lat": [0.0], "lon": [0.0],
        "cod_ibge": [1], "tec_ativos": [1.0], "volume": [1.0], "custo_total": [100.0], "alcance_p90_km": [5.0],
    })
    prep = assign.preparar(_D(os_, locais, dist_local, municipios), kpis_polos)
    r = assign.simular(prep, _params(raio_km=0.0))
    loc = r.locais.set_index("local_id")
    assert loc.loc["L1", "share_polo"] == pytest.approx(1 / 112)
    assert loc.loc["L1", "status"] != "polo"        # ~0,9% polo (caso real: Assis) -> nunca "Território PagResolve"
    assert loc.loc["L2", "share_polo"] == pytest.approx(0.5)
    assert loc.loc["L2", "status"] == "misto"       # 50/50 de verdade -> categoria própria, nem ogea nem polo


def test_override_manual_forca_polo_mesmo_fora_do_raio(cenario):
    # L3 está a 200 km de A e B (fora do raio de 50 km) -> sem override, ninguém captura
    r0 = assign.simular(cenario, _params(raio_km=50.0))
    assert pd.isna(r0.locais.set_index("local_id").loc["L3", "polo_captura"])
    # com exceção manual, L3 vai para B mesmo estando fora do raio de qualquer um
    r1 = assign.simular(cenario, _params(raio_km=50.0, override_local={"L3": "B"}))
    loc = r1.locais.set_index("local_id")
    assert loc.loc["L3", "polo_captura"] == "B"
    assert bool(loc.loc["L3", "override_manual"]) is True
    assert bool(loc.loc["L1", "override_manual"]) is False
    b = r1.polos.set_index("codigo_polo").loc["B"]
    assert b["vol_absorvido"] == pytest.approx(5)          # técnicos/CMU de B recalculados com o volume de L3


def test_override_manual_forca_ogea_mesmo_dentro_do_raio(cenario):
    # sem override, L2 (30 km de A, raio 50) é capturado por A
    r0 = assign.simular(cenario, _params(raio_km=50.0))
    assert r0.locais.set_index("local_id").loc["L2", "polo_captura"] == "A"
    # forçando Ógea, L2 fica de fora mesmo dentro do raio de A
    r1 = assign.simular(cenario, _params(raio_km=50.0, override_local={"L2": assign.OGEA_FORCADA}))
    loc = r1.locais.set_index("local_id")
    assert pd.isna(loc.loc["L2", "polo_captura"])
    assert loc.loc["L2", "status"] == "ogea"
    a = r1.polos.set_index("codigo_polo").loc["A"]
    assert a["vol_absorvido"] == pytest.approx(0)


def test_override_manual_ignora_territorio_exclusivo_da_capital(cenario_capital):
    # sem override, só o polo designado (P015) pode capturar o nó da capital (já testado em outro lugar);
    # com exceção manual, o usuário PODE atribuir a um polo diferente do designado
    r = assign.simular(cenario_capital, _params(
        raio_km=100.0, override_local={FARIA_LIMA_LOCAL_ID: "P999"}))
    loc = r.locais.set_index("local_id").loc[FARIA_LIMA_LOCAL_ID]
    assert loc["polo_captura"] == "P999"
    assert bool(loc["override_manual"]) is True
