"""Instâncias pequenas com ótimo conhecido à mão."""
import pandas as pd
import pytest

from malha.optimize import Instancia, resolver, resultado_base
from malha.scenario import Scenario


def _sc(**kw):
    base = dict(raio_km=50.0, meta_os_tec=10.0, custo_tecnico=1000.0,
                tipos_absorviveis=("Manutenção",), status_incluidos=("Finalizado",))
    base.update(kw)
    return Scenario(**base)


@pytest.fixture
def inst():
    # cidade 1: 10 OS do polo A;  cidade 2: 20 OS Ógea a 30 km de A;  cidade 3: 5 OS Ógea a 200 km de todos
    cidades = pd.DataFrame({
        "total": [10.0, 20.0, 5.0], "w_polo": [10.0, 0, 0], "w_abs": [0.0, 20.0, 5.0], "w_fix": [0.0, 0, 0],
        "preco": [40.0, 40.0, 40.0], "custo_abs": [0.0, 800.0, 200.0], "custo_fixo_ogea": [0.0, 0, 0],
        "regiao": ["R1", "R1", "R2"],
    }, index=pd.Index([1, 2, 3], name="cod_ibge"))
    polos = pd.DataFrame({
        "nome": ["A", "B"], "status": ["ATIVO", "DORMENTE"], "t0": [1.0, 0.0], "custo_atual": [1500.0, 0.0],
        "v0": [10.0, 0.0], "cap0": [10.0, 0.0], "k": [10.0, 10.0], "raio_km": [50.0, 50.0],
        "lat": [0.0, 0.0], "lon": [0.0, 0.0],
    }, index=pd.Index(["A", "B"], name="codigo_polo"))
    atual = pd.DataFrame({"cod_ibge": [1], "codigo_polo": ["A"], "vol": [10.0]})
    dist = pd.DataFrame({
        "codigo_polo": ["A", "A", "A", "B", "B", "B"],
        "cod_ibge": [1, 2, 3, 1, 2, 3],
        "d_km": [0.0, 30.0, 200.0, 300.0, 300.0, 200.0],
    })
    return Instancia(cidades, polos, atual, dist)


def test_base_reproduz_custo(inst):
    r = resultado_base(inst, _sc())
    assert r.kpis["custo_base"] == pytest.approx(1500 + 800 + 200)
    assert r.kpis["custo_cen"] == pytest.approx(r.kpis["custo_base"])
    assert r.kpis["ogea_cen"] == 25


def test_absorve_o_que_esta_no_raio(inst):
    r = resolver(inst, _sc())
    assert r.status == "Optimal"
    assert r.kpis["absorvido"] == pytest.approx(20)       # cidade 2 sim, cidade 3 fora do raio
    a = r.polos.set_index("codigo_polo").loc["A"]
    assert a["tecnicos"] == 3                            # equipe atual faz 10; +20 OS a 10/téc = +2
    assert a["contratar"] == 2
    assert r.kpis["custo_cen"] == pytest.approx(1500 + 2000 + 200)   # A + 2 técnicos + 5 OS na Ógea


def test_raio_zero_tudo_fica_na_ogea(inst):
    inst.polos["raio_km"] = 0.0
    r = resolver(inst, _sc())
    assert r.kpis["absorvido"] == pytest.approx(0)


def test_otimizar_abre_dormente_quando_alcanca(inst):
    inst.polos.loc["B", "raio_km"] = 250.0
    r = resolver(inst, _sc(modo="otimizar"))
    assert r.kpis["absorvido"] == pytest.approx(25)
    assert r.polos.set_index("codigo_polo").loc["B", "aberto"]


def test_otimizar_nao_fecha_ativo_sem_permissao(inst):
    inst.polos.loc["B", "raio_km"] = 400.0
    r = resolver(inst, _sc(modo="otimizar"))
    assert r.polos.set_index("codigo_polo").loc["A", "aberto"]
    assert r.kpis["polos_fechados"] == 0


def test_simular_nao_abre_dormente_sem_trava(inst):
    inst.polos.loc["B", "raio_km"] = 250.0
    r = resolver(inst, _sc(modo="simular"))
    assert r.kpis["absorvido"] == pytest.approx(20)
    assert not r.polos.set_index("codigo_polo").loc["B", "aberto"]


def test_fechar_polo_pelo_usuario_devolve_volume(inst):
    r = resolver(inst, _sc(travas=(("A", "fechado"),)))
    # sem A, ninguém alcança as cidades 1 e 2: tudo vai para a Ógea
    assert r.kpis["ogea_cen"] == pytest.approx(35)
    assert r.kpis["polos_fechados"] == 1


def test_share_forcado_por_municipio(inst):
    r = resolver(inst, _sc(share_municipio=((2, 0.5),)))
    assert r.cidades.set_index("cod_ibge").loc[2, "ogea_cen"] == pytest.approx(10)


def test_orcamento_limita_absorcao(inst):
    # absorver 10 OS custa +1 técnico (1000) e economiza 400 de Ógea -> 3100 > orçamento 3000
    r = resolver(inst, _sc(orcamento=3000.0))
    assert r.kpis["custo_cen"] <= 3000 + 1e-6
    assert r.kpis["absorvido"] == pytest.approx(0)
