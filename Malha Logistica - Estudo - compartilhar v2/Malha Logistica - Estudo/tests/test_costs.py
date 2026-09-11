import pytest

from malha.costs import break_even, capacidade_atual, curva_rateio, custo_polo, tecnicos_necessarios


def test_capacidade_atual_usa_observado_quando_maior():
    assert capacidade_atual(200, volume_atual=900, tec_atuais=3) == 900
    assert capacidade_atual(200, volume_atual=300, tec_atuais=3) == 600
    assert capacidade_atual(200, volume_atual=900, tec_atuais=3, usar_prod_observada=False) == 600
    assert capacidade_atual(200, volume_atual=0, tec_atuais=0) == 0


def test_tecnicos_novos_rendem_a_meta():
    # equipe atual (1 téc) já faz 100; +150 OS a 100/téc = 2 contratações
    assert tecnicos_necessarios(250, meta=100, tec_atuais=1, cap_atual=100) == 3
    assert tecnicos_necessarios(50, meta=100, tec_atuais=2, cap_atual=200) == 2
    assert tecnicos_necessarios(250, meta=100) == 3


def test_custo_polo_ativo_e_novo():
    assert custo_polo(3, custo_atual=10_000, tec_atuais=2, custo_tecnico=4_000) == 14_000
    assert custo_polo(2, custo_atual=0, tec_atuais=0, custo_tecnico=4_000, custo_abrir=5_000) == 13_000


def test_curva_reproduz_cmu_atual_e_dilui():
    c = curva_rateio(volume_atual=400, custo_atual=20_000, tec_atuais=2, meta=150, custo_tecnico=6_000, v_max=1_000)
    atual = c[c["volume"] == 400].iloc[0]
    assert atual["cmu"] == pytest.approx(50)          # 20.000 / 400
    assert atual["tecnicos"] == 2                     # equipe atual já faz 400 (> 2 × 150)
    assert c[c["volume"] == c["volume"].max()]["tecnicos"].iloc[0] == 6   # 2 + ceil(600 / 150)
    assert break_even(c, preco_ogea=45) is not None
