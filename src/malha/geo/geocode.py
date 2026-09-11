"""Geocodificação dos polos (≈48 pontos) com cache em disco.

Nenhuma coordenada é inventada: cada ponto registra a fonte e a confiança. Ordem:
override manual (data/manual/polos_overrides.csv) -> AwesomeAPI (CEP) -> Nominatim (endereço) -> sede do município.
Todo ponto de API precisa cair dentro do polígono IBGE do município cadastrado (folga ~2 km).
BrasilAPI não é usada: devolve o mesmo ponto genérico para CEPs diferentes da mesma cidade.
"""
import json
import logging
import time
from dataclasses import asdict, dataclass

import requests
from shapely.geometry import Point

from malha.config import CACHE

log = logging.getLogger(__name__)

F_CACHE = CACHE / "geocode_cep.json"
USER_AGENT = "malha-logistica-estudo/0.1 (estudo de malha logistica)"
BUFFER_GRAUS = 0.02   # ~2 km de folga na checagem ponto-no-polígono


@dataclass
class GeoHit:
    lat: float
    lon: float
    fonte: str
    confianca: str  # alta | baixa


_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def _awesome(cep, **_):
    r = _session.get(f"https://cep.awesomeapi.com.br/json/{cep}", timeout=20)
    if r.ok:
        j = r.json()
        if j.get("lat") and j.get("lng"):
            return float(j["lat"]), float(j["lng"])
    return None


def _nominatim(cep, endereco=None, numero=None, cidade=None, **_):
    if not endereco or not cidade:
        return None
    street = f"{numero} {endereco}" if numero else endereco
    params = {"street": street, "city": cidade, "state": "São Paulo", "country": "Brasil",
              "format": "json", "limit": 1}
    time.sleep(1.1)  # política Nominatim: máx 1 req/s
    r = _session.get("https://nominatim.openstreetmap.org/search", params=params, timeout=30)
    if r.ok and r.json():
        j = r.json()[0]
        return float(j["lat"]), float(j["lon"])
    return None


_CHAIN = [("awesomeapi", _awesome), ("nominatim", _nominatim)]


class Geocoder:
    def __init__(self, offline: bool = False):
        self.offline = offline
        self.cache = json.loads(F_CACHE.read_text(encoding="utf-8")) if F_CACHE.exists() else {}

    def save(self):
        F_CACHE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

    @staticmethod
    def _dentro(lat, lon, poligono) -> bool:
        return poligono is None or poligono.buffer(BUFFER_GRAUS).contains(Point(lon, lat))

    def geocode(self, key: str, cep, endereco=None, numero=None, cidade=None,
                poligono=None, sede: tuple | None = None, override: tuple | None = None) -> GeoHit:
        """key identifica o ponto no cache (ex.: código do polo). sede = (lat, lon) do município."""
        if override is not None:
            return GeoHit(override[0], override[1], "override_manual", "alta")
        if key in self.cache and self.cache[key]["fonte"] in dict(_CHAIN):
            return GeoHit(**self.cache[key])
        hit = None
        if not self.offline and cep:
            for fonte, fn in _CHAIN:
                try:
                    res = fn(cep, endereco=endereco, numero=numero, cidade=cidade)
                except requests.RequestException as e:
                    log.warning("  %s falhou para %s: %s", fonte, key, e)
                    res = None
                if res and self._dentro(res[0], res[1], poligono):
                    hit = GeoHit(res[0], res[1], fonte, "alta")
                    break
                if res:
                    log.info("  %s descartado para %s: fora do município", fonte, key)
        if hit is None:
            if sede is None:
                raise ValueError(f"Sem coordenada para {key} e sem sede do município")
            return GeoHit(sede[0], sede[1], "sede_municipio", "baixa")
        self.cache[key] = asdict(hit)
        return hit
