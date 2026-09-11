"""local_id: um município = um nó, exceto São Paulo capital (6 bairros, cada um com seu polo).

Sem `cep`/`e_ogea`, o comportamento é o de antes (fallback para o nó do Faria Lima) — os dois
parâmetros são opcionais para não quebrar o chamador de `api.py` (TEMPLATE não tem CEP por linha).
"""
import pandas as pd

from malha.locais import FARIA_LIMA_LOCAL_ID, NODE_POLO_DESIGNADO, ZONA_CEP_CAPITAL, local_id


def test_municipio_fora_da_capital_fica_por_municipio():
    cod = pd.Series([3509502, 3550308, 3550308], dtype="Int64")
    distrito = pd.Series([pd.NA, "Campo Belo", pd.NA], dtype="string")
    out = local_id(cod, distrito)
    assert out.tolist() == ["3509502", "3550308:CAMPO_BELO", FARIA_LIMA_LOCAL_ID]


def test_sem_cep_bairro_desconhecido_cai_no_faria_lima():
    # comportamento de fallback (usado por api.py ao resolver a TEMPLATE, que não tem CEP por linha)
    cod = pd.Series([3550308, 3550308], dtype="Int64")
    distrito = pd.Series(["Bairro que a BD não usa", pd.NA], dtype="string")
    assert local_id(cod, distrito).tolist() == [FARIA_LIMA_LOCAL_ID, FARIA_LIMA_LOCAL_ID]


def test_ogea_generico_e_dividido_pelo_cep_real_da_zona():
    cod = pd.Series([3550308] * 6, dtype="Int64")
    distrito = pd.Series([pd.NA] * 6, dtype="string")
    cep = pd.Series(["01310100", "04538132", "02071000", "05426100", "08210090", "03221000"], dtype="string")
    e_ogea = pd.Series([True] * 6)
    esperado = [ZONA_CEP_CAPITAL[c[:2]][0] for c in cep]
    assert local_id(cod, distrito, cep=cep, e_ogea=e_ogea).tolist() == esperado
    assert esperado == ["3550308:FARIA_LIMA", "3550308:CAMPO_BELO", "3550308:CASA_VERDE",
                        "3550308:VILA_ROMANA", "3550308:ITAQUERA", "3550308:VILA_PRUDENTE"]


def test_ogea_generico_com_cep_fora_das_6_zonas_cai_no_faria_lima():
    cod = pd.Series([3550308], dtype="Int64")
    distrito = pd.Series([pd.NA], dtype="string")
    cep = pd.Series(["09911630"], dtype="string")  # "09" não é nenhuma das 6 zonas mapeadas
    assert local_id(cod, distrito, cep=cep, e_ogea=pd.Series([True])).tolist() == [FARIA_LIMA_LOCAL_ID]


def test_cep_so_se_aplica_a_ogea_nao_ao_historico_do_polo():
    # o mesmo CEP (05xxx, Zona Oeste/Vila Romana) NÃO move uma OS de Polo para outro nó: o
    # histórico do Faria Lima (P015) é 100% CEP 05xxx na BD real e tem que continuar no Faria Lima
    cod = pd.Series([3550308], dtype="Int64")
    distrito = pd.Series([pd.NA], dtype="string")
    cep = pd.Series(["05426100"], dtype="string")
    assert local_id(cod, distrito, cep=cep, e_ogea=pd.Series([False])).tolist() == [FARIA_LIMA_LOCAL_ID]


def test_todos_os_6_bairros_da_capital_tem_polo_designado():
    assert set(NODE_POLO_DESIGNADO.values()) == {"P310", "P007", "P018", "P016", "P082", "P015"}
    assert NODE_POLO_DESIGNADO[FARIA_LIMA_LOCAL_ID] == "P015"


def test_zona_cep_capital_bate_com_node_polo_designado():
    # cada zona aponta pro mesmo par (nó, polo) que a regra de território exclusivo já usa
    for cep2, (lid, _zona, _bairro) in ZONA_CEP_CAPITAL.items():
        assert lid in NODE_POLO_DESIGNADO
