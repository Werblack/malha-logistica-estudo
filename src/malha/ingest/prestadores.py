"""Cadastro de prestadores (CSV exportado com células ="..."): endereço/CEP dos polos SP e do armazém Ógea."""
import pandas as pd

from malha.textnorm import fix_cep, parse_polo_code, strip_excel_formula


def load_prestadores(path) -> pd.DataFrame:
    raw = pd.read_csv(path, sep=";", encoding="latin-1", dtype=str, keep_default_na=False)
    raw.columns = [strip_excel_formula(c) for c in raw.columns]
    return raw.map(strip_excel_formula)


def _local(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "polo_nome": df["Nome"],
        "codigo_ps": df["Código"],
        "cep": df["CEP"].map(fix_cep),
        "endereco": df["Endereço"],
        "numero": df["Número"],
        "distrito": df["Distrito"],
        "cidade": df["Cidade"],
        "status_cadastro": df["Status"],
    }).astype("string")


def polos_sp(prest: pd.DataFrame) -> pd.DataFrame:
    """Um registro por polo 'Pnnn' cadastrado em SP."""
    df = prest[prest["Estado"].isin(["São Paulo"])].copy()
    codigo = df["Nome"].map(parse_polo_code)
    df = df[codigo.notna()]
    out = _local(df)
    out.insert(0, "codigo_polo", codigo[codigo.notna()].astype("string").values)
    return out.reset_index(drop=True)


def armazem_ogea(prest: pd.DataFrame, nome: str) -> pd.Series:
    """Linha do cadastro do armazém de onde a Ógea opera."""
    df = prest[prest["Nome"].isin([nome])]
    if df.empty:
        raise ValueError(f"Armazém '{nome}' não encontrado no cadastro de prestadores")
    return _local(df).iloc[0]
