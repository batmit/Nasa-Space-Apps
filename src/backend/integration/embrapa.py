"""Cliente independente para a API Agritec v2 da Embrapa.

Configure EMBRAPA_ACCESS_TOKEN com um token de uma aplicação inscrita na Agritec.
O token também pode ser passado ao construtor; nunca deve vir do frontend.
Não há chamadas externas durante a importação nem dependência da integração NASA.

Exemplo (chamada síncrona, para uso em rota ``def`` do FastAPI)::

    cliente = EmbrapaClient()
    culturas = cliente.listar_culturas()  # IDs reais; não inferir pelo nome.
    dados = cliente.consultar_zoneamento(
        ConsultaZoneamento(codigo_ibge=3502804, id_cultura=60)
    )
    payload = dados.model_dump(mode="json")

O município deve ser identificado previamente a partir do mapa. Coordenadas
não são parâmetros do ZARC. Janelas são específicas de solo, ciclo e safra;
lista vazia indica ausência de dados, não uma recomendação de não plantar.
Este módulo fornece evidências agronômicas, não decide a rotação de culturas.
O risco de consulta é fixado internamente em 20%; o agricultor não o informa.

Contrato: https://www.agroapi.cnptia.embrapa.br/store/api-docs/agroapi/Agritec/v2
"""

import gzip
import json
import math
import os
import re
import zlib
from html import unescape
from html.parser import HTMLParser
from typing import Generic, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, ValidationError

from ..models.embrapa import (
    ConsultaZoneamento, CulturaEmbrapa, EmbrapaError, JanelaPlantio, ResultadoZoneamento,
)
from ..models.recomendacao import ReferenciaTecnica


_Item = TypeVar("_Item")


class _ListaEmbrapa(BaseModel, Generic[_Item]):
    # Campo obrigatório: uma resposta sem data é inválida, não uma lista vazia.
    data: list[_Item]


class _AgroAPIClient:
    """Transporte autenticado compartilhado pelas APIs da plataforma AgroAPI."""

    BASE_URL: str
    TOKEN_ENV = "EMBRAPA_ACCESS_TOKEN"

    def __init__(self, token: str | None = None, *, timeout: float = 15.0):
        access_token = token if token is not None else os.getenv(self.TOKEN_ENV, "")
        access_token = access_token.strip()
        if not access_token or any(c.isspace() for c in access_token):
            raise ValueError(f"Configure um token válido em {self.TOKEN_ENV}.")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("O timeout deve ser um número positivo e finito.")
        self._token = access_token
        self._timeout = timeout

    def _get(self, recurso: str, parametros: dict[str, str | int] | None = None) -> object:
        return self._request(recurso, parametros=parametros)

    def _request(
        self, recurso: str, *, parametros: dict[str, str | int] | None = None,
        payload: dict | None = None,
    ) -> object:
        url = f"{self.BASE_URL}/{recurso}"
        if parametros:
            url += "?" + urlencode(parametros)
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "Accept": "application/json", "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                body = response.read()
                encoding = getattr(response, "headers", {}).get("Content-Encoding", "").strip().lower()
                if encoding == "gzip":
                    body = gzip.decompress(body)
                elif encoding not in ("", "identity"):
                    raise EmbrapaError("A Embrapa retornou compactação não suportada.", categoria="resposta_invalida")
                return json.loads(body)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status in (401, 403):
                mensagem = "Acesso à AgroAPI negado: verifique o token e a inscrição da aplicação."
            elif status == 429:
                mensagem = "Limite de requisições da Embrapa atingido. Tente novamente mais tarde."
            else:
                mensagem = f"A API da Embrapa retornou HTTP {status}."
            raise EmbrapaError(mensagem, status) from None
        except (ValueError, gzip.BadGzipFile, EOFError, zlib.error):
            raise EmbrapaError("A API da Embrapa retornou JSON ou gzip inválido.", categoria="resposta_invalida") from None
        except (URLError, TimeoutError, OSError):
            raise EmbrapaError("Não foi possível conectar à API da Embrapa.", categoria="conexao") from None


class EmbrapaClient(_AgroAPIClient):
    """Catálogo e zoneamento Agritec, sem regras de recomendação."""

    BASE_URL = "https://api.cnptia.embrapa.br/agritec/v2"
    _RISCO_PADRAO = "20"

    def listar_culturas(self) -> list[CulturaEmbrapa]:
        """Obtém o catálogo para seleção explícita da cultura e do cultivo."""
        payload = self._get("culturas")
        try:
            return _ListaEmbrapa[CulturaEmbrapa].model_validate(payload).data
        except ValidationError:
            raise EmbrapaError("Resposta de culturas incompatível com o contrato Agritec v2.", categoria="resposta_invalida") from None

    def listar_culturas_municipio(self, codigo_ibge: int) -> list[CulturaEmbrapa]:
        """Catálogo ZARC do município, evitando IDs de culturas sem cobertura local."""
        if type(codigo_ibge) is not int or not 1000000 <= codigo_ibge <= 9999999:
            raise ValueError("Informe um código IBGE municipal de sete dígitos.")
        payload = self._get(f"municipios/{codigo_ibge}/culturas")
        try:
            return _ListaEmbrapa[CulturaEmbrapa].model_validate(payload).data
        except ValidationError:
            raise EmbrapaError("Catálogo municipal incompatível com a Agritec v2.", categoria="resposta_invalida") from None

    def consultar_zoneamento(self, consulta: ConsultaZoneamento) -> ResultadoZoneamento:
        """Obtém todas as janelas retornadas, mantendo seus solos e ciclos."""
        payload = self._get(
            "zoneamento",
            {
                "codigoIBGE": consulta.codigo_ibge,
                "idCultura": consulta.id_cultura,
                "risco": self._RISCO_PADRAO,
            },
        )
        try:
            janelas = _ListaEmbrapa[JanelaPlantio].model_validate(payload).data
        except ValidationError:
            raise EmbrapaError("Resposta de zoneamento incompatível com o contrato Agritec v2.", categoria="resposta_invalida") from None
        return ResultadoZoneamento(consulta=consulta, janelas=janelas)


class _TextoHTML(HTMLParser):
    """Converte respostas editoriais em texto; não entrega HTML à interface."""

    def __init__(self):
        super().__init__()
        self.partes: list[str] = []

    def handle_data(self, data: str):
        self.partes.append(data)


class _DocumentoRespondeAgro(BaseModel):
    question: str
    answer: str
    book: str
    chapter: str | None = None
    year: int | None = None
    pdf: str | None = None


class _HitRespondeAgro(BaseModel):
    id: str = Field(alias="_id")
    source: _DocumentoRespondeAgro = Field(alias="_source")


class _HitsRespondeAgro(BaseModel):
    hits: list[_HitRespondeAgro]


class _BuscaRespondeAgro(BaseModel):
    hits: _HitsRespondeAgro


class RespondeAgroClient(_AgroAPIClient):
    """Busca referências; resultados não são prescrições para a propriedade."""

    BASE_URL = "https://api.cnptia.embrapa.br/respondeagro/v1"
    TOKEN_ENV = "EMBRAPA_RESPONDEAGRO_TOKEN"

    def __init__(self, token: str | None = None, *, timeout: float = 15.0):
        # A mesma aplicação pode ter ambas as APIs inscritas, ou tokens distintos.
        if token is None:
            token = os.getenv(self.TOKEN_ENV) or os.getenv("EMBRAPA_ACCESS_TOKEN")
        super().__init__(token, timeout=timeout)

    def buscar_referencias(self, termos: list[str]) -> list[ReferenciaTecnica]:
        # O backend controla a sintaxe Lucene; texto do usuário é sempre literal.
        def literal(termo: str) -> str:
            return '"' + termo.replace('\\', '\\\\').replace('"', '\\"') + '"'

        termos = [t for t in termos if t.strip()]
        if not termos:
            raise ValueError("Informe ao menos uma cultura para a busca.")
        query = literal(termos[0])
        if len(termos) > 1:
            query += " AND (" + " OR ".join(literal(t) for t in termos[1:]) + ")"
        payload = self._request("_search/template", payload={
            "id": "query_all", "params": {"query_string": query, "from": 0, "size": 5},
        })
        try:
            hits = _BuscaRespondeAgro.model_validate(payload).hits.hits
        except ValidationError:
            raise EmbrapaError("Resposta de referências incompatível com a RespondeAgro.") from None
        referencias = []
        for hit in hits:
            documento = hit.source
            parser = _TextoHTML()
            parser.feed(documento.answer)
            texto = re.sub(r"\s+", " ", unescape(" ".join(parser.partes))).strip()
            url = documento.pdf
            if url and not url.startswith("https://"):
                url = None
            referencias.append(ReferenciaTecnica(
                id=hit.id, pergunta=documento.question, resposta=texto,
                livro=documento.book, capitulo=documento.chapter, ano=documento.year,
                url_publicacao=url,
            ))
        return referencias
