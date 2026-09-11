"""Cenário = todos os parâmetros do simulador (inputs do usuário + defaults derivados do dado).

Imutável e serializável em JSON, para salvar/comparar cenários e servir de chave de cache.
"""
import hashlib
import json
from dataclasses import asdict, dataclass, replace

_TUPLAS = ("tipos_absorviveis", "status_incluidos", "candidatos_novos")
_PARES = ("raio_polo", "travas", "share_municipio", "share_regiao")


@dataclass(frozen=True, kw_only=True)
class Scenario:
    # sem default: vêm de baseline.defaults() (dado) ou do usuário
    raio_km: float
    meta_os_tec: float
    custo_tecnico: float
    tipos_absorviveis: tuple[str, ...]
    status_incluidos: tuple[str, ...]

    nome: str = "Cenário"
    modo: str = "simular"                # simular: polos abertos = os de hoje + travas | otimizar: modelo escolhe
    permitir_fechar_ativos: bool = False  # no modo otimizar, o modelo pode fechar polo ativo (senão só o usuário)
    usar_prod_observada: bool = True
    custo_abrir: float = 0.0
    custo_km: float = 0.0
    orcamento: float | None = None
    vol_min_polo: float = 0.0
    sem_demissao: bool = True
    nao_devolver: bool = True            # volume de polo não volta para a Ógea (exceto de polo fechado pelo usuário)
    raio_polo: tuple[tuple[str, float], ...] = ()          # (codigo_polo, km)
    travas: tuple[tuple[str, str], ...] = ()               # (codigo_polo, "aberto"|"fechado")
    share_municipio: tuple[tuple[int, float], ...] = ()    # (cod_ibge, share Ógea alvo 0-1)
    share_regiao: tuple[tuple[str, float], ...] = ()       # (regiao_imediata, share Ógea alvo 0-1)
    candidatos_novos: tuple[int, ...] = ()                 # cod_ibge de hubs novos (sede do município)

    def with_(self, **kw) -> "Scenario":
        return replace(self, **kw)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, s: str) -> "Scenario":
        d = json.loads(s)
        for k in _TUPLAS:
            d[k] = tuple(d.get(k, ()))
        for k in _PARES:
            d[k] = tuple(tuple(x) for x in d.get(k, ()))
        return cls(**d)

    def chave(self) -> str:
        return hashlib.sha1(self.to_json().encode("utf-8")).hexdigest()[:12]


def cenario_padrao(defaults: dict, tipos: list[str], status: list[str], **kw) -> Scenario:
    """Cenário inicial: parâmetros do dado, todos os tipos e status incluídos, polos de hoje."""
    return Scenario(
        raio_km=defaults["raio_km"]["valor"],
        meta_os_tec=defaults["meta_os_tec"]["valor"],
        custo_tecnico=defaults["custo_tecnico"]["valor"],
        custo_abrir=defaults["custo_abrir"]["valor"],
        custo_km=defaults["custo_km"]["valor"],
        tipos_absorviveis=tuple(sorted(tipos)),
        status_incluidos=tuple(sorted(status)),
        **kw,
    )
