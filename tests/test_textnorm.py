import pandas as pd

from malha.geo.distance import haversine_km
from malha.textnorm import fix_cep, norm_nome, parse_polo_code, strip_excel_formula, to_num


def test_norm_nome_ignora_caixa_e_acento():
    assert norm_nome("Mogi Das Cruzes") == norm_nome("Mogi das Cruzes") == "mogi das cruzes"
    assert norm_nome("São José dos Campos") == "sao jose dos campos"
    assert norm_nome("Santa Bárbara D'Oeste") == norm_nome("Santa Bárbara d'Oeste")
    assert norm_nome(None) == ""


def test_strip_excel_formula():
    assert strip_excel_formula('="09911630"') == "09911630"
    assert strip_excel_formula('="Falso"') == "Falso"
    assert strip_excel_formula("PAGSEGURO - Matriz") == "PAGSEGURO - Matriz"
    assert strip_excel_formula("=") is pd.NA
    assert strip_excel_formula('=""') is pd.NA


def test_fix_cep_recupera_zero():
    assert fix_cep(9911630) == "09911630"
    assert fix_cep(9911630.0) == "09911630"
    assert fix_cep("04604902") == "04604902"
    assert fix_cep("04604-902") == "04604902"
    assert fix_cep("-") is pd.NA
    assert fix_cep(123) is pd.NA


def test_parse_polo_code():
    assert parse_polo_code("Polo SP São Bernado Do Campo - P313") == "P313"
    assert parse_polo_code("SP Ribeirão Botanico LT - P287") == "P287"
    assert parse_polo_code("TEFTI ARMAZEM E LOGISTICA LTDA") is pd.NA
    assert parse_polo_code("Micro Adamantina") is pd.NA


def test_to_num_marcadores_viram_na():
    s = to_num(pd.Series([1, "-", "Sem Volumes", 2.5], dtype=object))
    assert s.isna().tolist() == [False, True, True, False]
    assert s.iloc[3] == 2.5


def test_haversine_sp_campinas():
    # Praça da Sé -> centro de Campinas ≈ 84 km em linha reta
    d = haversine_km(-23.5505, -46.6333, -22.9056, -47.0608)
    assert 80 < d < 90
