"""Trava de performance: o app desktop chama `simular_rapido` a cada movimento de slider — se isso
voltar a ficar lento (ex.: alguém reintroduzir `Series.map(função)` no caminho quente), tem que quebrar
aqui, não só ser percebido como "o app ficou pesado" depois.
"""
import time

import pytest

from malha import assign, baseline
from malha.config import PROCESSED
from malha.datasets import load

pytestmark = pytest.mark.slow

LIMITE_MS = 30.0  # bem acima da média observada (~12 ms) — margem para máquinas mais lentas


@pytest.fixture(scope="module")
def prep():
    if not (PROCESSED / "os.parquet").exists():
        pytest.skip("rode `python -m malha.build` antes deste teste")
    d = load()
    k = baseline.polo_kpis(d)
    return assign.preparar(d, k)


def test_simular_e_rapido_o_bastante(prep):
    p = assign.Params(raio_km=41.0, os_dia_gsp=6.0, os_dia_interior=3.5, custo_tecnico=15000.0)
    assign.simular_rapido(prep, p)  # warmup (1ª chamada paga custo de JIT/caches do numpy)

    n = 50
    t0 = time.perf_counter()
    for i in range(n):
        assign.simular_rapido(prep, assign.Params(raio_km=10 + i, os_dia_gsp=6.0, os_dia_interior=3.5,
                                                   custo_tecnico=15000.0))
    ms_por_chamada = (time.perf_counter() - t0) / n * 1000
    assert ms_por_chamada < LIMITE_MS, f"simular_rapido ficou em {ms_por_chamada:.1f} ms/chamada (limite {LIMITE_MS})"


def test_simular_e_simular_rapido_concordam(prep):
    p = assign.Params(raio_km=60.0, os_dia_gsp=6.0, os_dia_interior=3.5, custo_tecnico=15000.0,
                      raio_polo={"P014": 120.0})
    r1 = assign.simular(prep, p).kpis
    r2 = assign.simular_rapido(prep, p)["kpis"]
    for chave in r1:
        assert r1[chave] == pytest.approx(r2[chave], rel=1e-9), chave
