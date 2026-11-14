"""Adapta geocodificação OpenStreetMap e catálogo IBGE ao município da consulta.

Instância compartilhada por processo, cache e limite de uma consulta por segundo.
O servidor público Nominatim é adequado somente ao MVP com um worker; para
escalar, configure NOMINATIM_BASE_URL com um provedor próprio/contratado.
"""

import gzip
import json
import os
import socket
import ssl
import time
import unicodedata
import zlib
from functools import lru_cache
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from pydantic import ValidationError

from ..models.recomendacao import LocalizacaoSelecionada, Municipio


class LocalizacaoError(RuntimeError):
    def __init__(self, mensagem: str, *, entrada_invalida: bool = False):
        super().__init__(mensagem)
        self.entrada_invalida = entrada_invalida


def _normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto.casefold())
                   if not unicodedata.combining(c)).strip()


class LocalizacaoClient:
    _lock = Lock()
    _ultima_consulta = 0.0

    def __init__(self, *, timeout: float = 15.0):
        self._base_url = os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org").rstrip("/")
        if not self._base_url.startswith("https://"):
            raise ValueError("NOMINATIM_BASE_URL deve utilizar HTTPS.")
        self._user_agent = os.getenv("NOMINATIM_USER_AGENT", "AgroOrbit/0.1")
        self._timeout = timeout

    def _get(self, url: str) -> object:
        servico = "IBGE" if urlsplit(url).hostname == "servicodados.ibge.gov.br" else "Nominatim"
        request = Request(url, headers={
            "User-Agent": self._user_agent, "Accept": "application/json", "Accept-Encoding": "gzip",
        })
        try:
            with urlopen(request, timeout=self._timeout) as response:
                # urllib não descompacta automaticamente Content-Encoding: gzip.
                body = response.read()
                encoding = response.headers.get("Content-Encoding", "").strip().lower()
                if encoding == "gzip":
                    body = gzip.decompress(body)
                elif encoding not in ("", "identity"):
                    raise LocalizacaoError(f"O serviço {servico} retornou uma compactação não suportada.")
                return json.loads(body)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status == 429:
                mensagem = f"Limite de consultas do serviço {servico} atingido. Aguarde e tente novamente."
            elif status in (401, 403):
                mensagem = f"O serviço {servico} recusou o acesso (HTTP {status}). Verifique a configuração do provedor."
            else:
                mensagem = f"O serviço {servico} retornou HTTP {status}. Tente novamente mais tarde."
            raise LocalizacaoError(mensagem) from None
        except URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                mensagem = f"Falha na verificação do certificado HTTPS do serviço {servico}."
            elif isinstance(exc.reason, socket.gaierror):
                mensagem = f"Não foi possível resolver o endereço do serviço {servico}. Verifique a conexão e o DNS."
            elif isinstance(exc.reason, TimeoutError):
                mensagem = f"O serviço {servico} excedeu o tempo de resposta. Tente novamente."
            else:
                mensagem = f"Não foi possível conectar ao serviço {servico}. Verifique a conexão."
            raise LocalizacaoError(mensagem) from None
        except TimeoutError:
            raise LocalizacaoError(f"O serviço {servico} excedeu o tempo de resposta. Tente novamente.") from None
        except (ValueError, gzip.BadGzipFile, EOFError, zlib.error):
            raise LocalizacaoError(f"O serviço {servico} retornou uma resposta JSON ou gzip inválida.") from None
        except OSError:
            raise LocalizacaoError(f"Não foi possível ler a resposta do serviço {servico}.") from None

    @lru_cache(maxsize=27)
    def _municipios(self, uf: str) -> list:
        payload = self._get(f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios")
        if not isinstance(payload, list):
            raise LocalizacaoError("Resposta inválida do catálogo de municípios IBGE.")
        return payload

    @lru_cache(maxsize=1024)
    def _nominatim(self, recurso: str, parametros: str) -> object:
        with self._lock:
            espera = max(0.0, 1.0 - (time.monotonic() - self._ultima_consulta))
            if espera:
                time.sleep(espera)
            LocalizacaoClient._ultima_consulta = time.monotonic()
            return self._get(f"{self._base_url}/{recurso}?{parametros}")

    def buscar_localizacao(self, consulta: str) -> LocalizacaoSelecionada:
        payload = self._nominatim("search", urlencode({
            "q": consulta, "format": "jsonv2", "countrycodes": "br", "limit": 1,
        }))
        if not isinstance(payload, list):
            raise LocalizacaoError("Resposta inválida da busca de localização.")
        if not payload:
            raise LocalizacaoError("Local não encontrado. Tente informar município e UF.", entrada_invalida=True)
        try:
            ponto = LocalizacaoSelecionada.model_validate({
                "regiao_nome": "", "latitude": payload[0]["lat"], "longitude": payload[0]["lon"],
            })
        except (ValidationError, KeyError, TypeError):
            raise LocalizacaoError("Coordenadas inválidas no retorno da busca.") from None
        return self.resolver_localizacao(ponto.latitude, ponto.longitude)

    def resolver_localizacao(self, latitude: float, longitude: float) -> LocalizacaoSelecionada:
        municipio = self.resolver_municipio(latitude, longitude)
        return LocalizacaoSelecionada(
            regiao_nome=f"{municipio.nome}, {municipio.uf}", latitude=latitude, longitude=longitude,
        )

    @lru_cache(maxsize=1024)
    def resolver_municipio(self, latitude: float, longitude: float) -> Municipio:
        payload = self._nominatim("reverse", urlencode({
            "lat": latitude, "lon": longitude, "format": "jsonv2",
            "zoom": 10, "addressdetails": 1, "accept-language": "pt-BR",
        }))
        if not isinstance(payload, dict) or not isinstance(payload.get("address"), dict):
            raise LocalizacaoError("Não foi possível identificar o município dessas coordenadas.", entrada_invalida=True)
        endereco = payload["address"]
        if endereco.get("country_code") != "br":
            raise LocalizacaoError("As consultas Agritec deste serviço atendem municípios brasileiros.", entrada_invalida=True)
        uf_iso = endereco.get("ISO3166-2-lvl4", "")
        if not isinstance(uf_iso, str) or not uf_iso.startswith("BR-") or len(uf_iso) != 5:
            raise LocalizacaoError("Não foi possível identificar a UF das coordenadas.", entrada_invalida=True)
        uf = uf_iso[3:]
        nomes = [endereco.get(campo) for campo in ("municipality", "city", "town", "county")]
        nomes = {_normalizar(nome) for nome in nomes if isinstance(nome, str)}
        candidatos = []
        for municipio in self._municipios(uf):
            if not isinstance(municipio, dict) or not isinstance(municipio.get("nome"), str):
                raise LocalizacaoError("Resposta inválida do catálogo de municípios IBGE.")
            if _normalizar(municipio["nome"]) in nomes:
                candidatos.append(municipio)
        if len(candidatos) != 1:
            raise LocalizacaoError("Município não identificado de forma unívoca no IBGE.", entrada_invalida=True)
        municipio = candidatos[0]
        codigo = municipio.get("id")
        if not isinstance(codigo, int) or not 1000000 <= codigo <= 9999999:
            raise LocalizacaoError("Código de município inválido no retorno IBGE.")
        return Municipio(codigo_ibge=codigo, nome=municipio["nome"], uf=uf)
