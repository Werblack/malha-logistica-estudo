"""Pipeline: planilhas brutas -> parquets limpos + geodados. Único módulo que lê o xlsx (~1 min).

    python -m malha.build              # usa o cache de geocodificação; consulta APIs só para pontos novos
    python -m malha.build --offline    # sem internet: cache ou sede do município
    python -m malha.build --refresh-geo
"""
import argparse
import json
import logging

import numpy as np
import pandas as pd

from malha import config
from malha.geo import ibge
from malha.geo.distance import distance_matrix
from malha.geo.geocode import Geocoder
from malha.ingest.bd import clean_bd, read_bd_raw
from malha.ingest.cmu import load_cmu
from malha.ingest.prestadores import armazem_ogea, load_prestadores, polos_sp
from malha.ingest.resolve import MunicipioResolver
from malha.ingest.template import load_template

log = logging.getLogger("malha.build")


def read_manual(name: str) -> pd.DataFrame:
    df = pd.read_csv(config.MANUAL / name, dtype=str, keep_default_na=False, encoding="utf-8")
    return df.replace("", pd.NA)


def _none(v):
    return None if pd.isna(v) else v


def _as_string(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        if pd.api.types.is_object_dtype(df[c]):
            df[c] = df[c].astype("string")
    return df


def build_polos(prest, os_, tec_ativos, mun, polys, resolver, geocoder) -> pd.DataFrame:
    """47 polos cadastrados em SP (ativos + dormentes) + armazém Ógea, com coordenada e fonte."""
    cad = polos_sp(prest)
    dup = cad["codigo_polo"][cad["codigo_polo"].duplicated()]
    if len(dup):
        log.warning("Códigos de polo duplicados no cadastro (mantido o 1º): %s", dup.tolist())
        cad = cad.drop_duplicates("codigo_polo")
    ativos = set(os_.loc[os_["transportadora"].eq("POLO"), "codigo_polo"].dropna())
    faltando = ativos - set(cad["codigo_polo"])
    if faltando:
        raise SystemExit(f"Polos com volume na BD sem cadastro em Prestador de Serviço.csv: {sorted(faltando)}")

    wh = armazem_ogea(prest, config.OGEA_POLO_NOME).to_dict()
    wh["codigo_polo"] = "OGEA"
    df = pd.concat([cad, pd.DataFrame([wh]).astype("string")], ignore_index=True)
    df["status_bd"] = np.select([df["codigo_polo"].eq("OGEA"), df["codigo_polo"].isin(ativos)],
                                ["ARMAZEM_OGEA", "ATIVO"], "DORMENTE")

    ov = read_manual("polos_overrides.csv").rename(columns={"lat": "lat_override", "lon": "lon_override"})
    df = df.merge(ov, on="codigo_polo", how="left")
    df["excluir"] = df["excluir"].fillna("0").eq("1").astype(bool)

    df = df.merge(tec_ativos[["codigo_polo", "tec_ativos"]], on="codigo_polo", how="left")
    distintos = (os_[os_["transportadora"].eq("POLO")].groupby("codigo_polo")["tecnico"].nunique()
                 .rename("tec_distintos_bd"))
    df = df.merge(distintos, left_on="codigo_polo", right_index=True, how="left")
    df = df.join(resolver.resolve(df["cidade"]))

    sede = mun.set_index("cod_ibge")[["lat", "lon"]]
    coords = []
    for r in df.itertuples(index=False):
        cod = None if pd.isna(r.cod_ibge) else int(r.cod_ibge)
        override = None
        if pd.notna(r.lat_override) and pd.notna(r.lon_override):
            override = (float(r.lat_override), float(r.lon_override))
        hit = geocoder.geocode(
            r.codigo_polo, _none(r.cep), _none(r.endereco), _none(r.numero), _none(r.cidade),
            poligono=polys.get(cod), sede=tuple(sede.loc[cod]) if cod in sede.index else None,
            override=override)
        log.info("  %-5s %-40s %s (%s)", r.codigo_polo, r.polo_nome, hit.fonte, hit.confianca)
        coords.append((hit.lat, hit.lon, hit.fonte, hit.confianca))
    geocoder.save()
    df[["lat", "lon", "coord_fonte", "coord_confianca"]] = pd.DataFrame(coords, index=df.index)
    return _as_string(df.drop(columns=["lat_override", "lon_override"]))


def _vc(s: pd.Series) -> dict:
    return {str(k): int(v) for k, v in s.value_counts(dropna=False).items()}


def _records(df: pd.DataFrame) -> list:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def relatorio_qualidade(os_, template, mun, polos, cmu_polo, preco_ogea) -> dict:
    p = os_[os_["transportadora"].eq("POLO")]
    o = os_[os_["transportadora"].eq("OGEA")]

    cmu_bd = p.groupby("codigo_polo")["cmu_os"].agg(["min", "max"]).join(cmu_polo.set_index("codigo_polo")["cmu_polo"])
    cmu_div = cmu_bd[(cmu_bd["min"] - cmu_bd["cmu_polo"]).abs().gt(0.01) | (cmu_bd["max"] - cmu_bd["cmu_polo"]).abs().gt(0.01)]
    preco_bd = (o.groupby("tipo_atendimento")["cmu_os"].agg(["min", "max", "size"])
                .join(preco_ogea.set_index("tipo_atendimento")["preco_ogea"]))
    cod_div = p[p["codigo_polo_bd"].notna() & p["codigo_polo_bd"].ne(p["codigo_polo"]).fillna(False)]
    ausentes = mun[~mun["cod_ibge"].isin(template["cod_ibge"].dropna().astype(int))]

    return {
        "os_total": int(len(os_)),
        "os_por_transportadora": _vc(os_["transportadora"]),
        "status_os": _vc(os_["status"]),
        "match_municipio": _vc(os_["match_municipio"]),
        "os_por_distrito_capital": _vc(os_.loc[os_["match_municipio"].eq("distrito"), "distrito_capital"]),
        "cidades_fuzzy": _records(os_.loc[os_["match_municipio"].eq("fuzzy"), ["cidade_raw", "municipio"]].drop_duplicates()),
        "cep_invalido": int(os_["cep"].isna().sum()),
        "dt_abertura_nula": int(os_["dt_abertura"].isna().sum()),
        "meses_abertura": _vc(os_["dt_abertura"].dt.month),
        "lead_time_negativo": int((os_["lead_time_d"] < 0).sum()),
        "template_linhas": int(len(template)),
        "template_sem_volume": int(template["sem_volume"].sum()),
        "template_nao_resolvido": template.loc[template["cod_ibge"].isna(), "municipio_raw"].tolist(),
        "template_pseudo_municipios": template.loc[template["match_municipio"].eq("distrito"), "municipio_raw"].tolist(),
        "ibge_ausentes_no_template": ausentes["municipio"].tolist(),
        "cmu_polo_divergente_bd_vs_aba": _records(cmu_div.reset_index()),
        "preco_ogea_bd_vs_aba": _records(preco_bd.reset_index()),
        "codigo_polo_bd_divergente": _records(cod_div.groupby(["polo_nome", "codigo_polo_bd"]).size().rename("os").reset_index()),
        "tecnicos_ativos_vs_distintos": _records(polos.loc[polos["status_bd"].eq("ATIVO"),
                                                       ["codigo_polo", "polo_nome", "tec_ativos", "tec_distintos_bd"]]),
        "polos_cadastro": _vc(polos["status_bd"]),
        "geocode": _records(polos[["codigo_polo", "polo_nome", "status_bd", "coord_fonte", "coord_confianca"]]),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="não chama APIs; usa cache ou sede do município")
    ap.add_argument("--refresh-geo", action="store_true", help="baixa de novo IBGE/kelvins e refaz a geocodificação")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    log.info("Geodados IBGE/kelvins")
    malha = ibge.load_malha(refresh=args.refresh_geo)
    mun = ibge.load_municipios(malha, refresh=args.refresh_geo)
    polys = ibge.poligonos(malha)
    resolver = MunicipioResolver(mun, read_manual("distritos_capital.csv"), read_manual("aliases_municipios.csv"))

    log.info("Lendo aba BD (~1 min)")
    os_ = clean_bd(read_bd_raw(config.RAW_XLSX), resolver)
    nao = os_.loc[os_["cod_ibge"].isna(), "cidade_raw"].value_counts(dropna=False)
    if len(nao):
        raise SystemExit("Cidades da BD sem código IBGE (cadastre em data/manual/aliases_municipios.csv):\n"
                         + nao.to_string())
    os_["cod_ibge"] = os_["cod_ibge"].astype("int64")
    os_["match_municipio"] = os_["match_municipio"].astype("string")

    log.info("Lendo TEMPLATE, CMU e cadastro de prestadores")
    template = _as_string(load_template(config.RAW_XLSX, resolver))
    cmu_polo, preco_ogea, tec_ativos = load_cmu(config.RAW_XLSX)
    prest = load_prestadores(config.RAW_PRESTADORES)

    log.info("Geocodificando polos")
    geocoder = Geocoder(offline=args.offline)
    if args.refresh_geo:
        geocoder.cache = {}
    polos = build_polos(prest, os_, tec_ativos, mun, polys, resolver, geocoder)
    dist = distance_matrix(polos[["codigo_polo", "lat", "lon"]], mun[["cod_ibge", "lat", "lon"]])

    qualidade = relatorio_qualidade(os_, template, mun, polos, cmu_polo, preco_ogea)
    out = config.PROCESSED
    tabelas = {"os": os_, "template": template, "municipios": mun, "polos": polos, "dist_polo_mun": dist,
               "cmu_polo": cmu_polo, "preco_ogea": preco_ogea, "tec_ativos": tec_ativos}
    for nome, df in tabelas.items():
        df.to_parquet(out / f"{nome}.parquet", index=False)
    (out / "qualidade.json").write_text(json.dumps(qualidade, ensure_ascii=False, indent=1, default=str),
                                        encoding="utf-8")
    log.info("OK: %d OS, %d municípios, %d polos -> %s", len(os_), len(mun), len(polos), out)


if __name__ == "__main__":
    main()
