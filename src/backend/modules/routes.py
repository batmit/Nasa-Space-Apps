from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..integration.embrapa import EmbrapaClient, EmbrapaError, RespondeAgroClient
from ..integration.localizacao import LocalizacaoClient, LocalizacaoError
from ..models.recomendacao import DadosAgricultor, LocalizacaoSelecionada, RecomendacaoResponse
from ..services.recomendacao import RecomendacaoService

router = APIRouter()


@lru_cache(maxsize=1)
def obter_localizador() -> LocalizacaoClient:
    try:
        return LocalizacaoClient()
    except ValueError:
        raise HTTPException(status_code=503, detail="Localização não configurada no servidor.") from None


@lru_cache(maxsize=1)
def obter_servico_recomendacao() -> RecomendacaoService:
    """Composição dos adaptadores; substituível em testes via dependency_overrides."""
    try:
        return RecomendacaoService(
            zoneamento=EmbrapaClient(), referencias=RespondeAgroClient(),
            localizador=obter_localizador(),
        )
    except ValueError:
        raise HTTPException(status_code=503, detail="Integrações não configuradas no servidor.") from None


@router.get("/health", tags=["Status"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/localizacao/buscar", response_model=LocalizacaoSelecionada, tags=["Localização"])
def buscar_localizacao(
    consulta: Annotated[str, Query(min_length=2, max_length=200)],
    localizador: Annotated[LocalizacaoClient, Depends(obter_localizador)],
) -> LocalizacaoSelecionada:
    try:
        return localizador.buscar_localizacao(consulta.strip())
    except LocalizacaoError as exc:
        raise HTTPException(status_code=422 if exc.entrada_invalida else 502, detail=str(exc)) from None


@router.get("/localizacao/reversa", response_model=LocalizacaoSelecionada, tags=["Localização"])
def resolver_localizacao(
    latitude: Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False)],
    longitude: Annotated[float, Query(ge=-180, le=180, allow_inf_nan=False)],
    localizador: Annotated[LocalizacaoClient, Depends(obter_localizador)],
) -> LocalizacaoSelecionada:
    try:
        return localizador.resolver_localizacao(latitude, longitude)
    except LocalizacaoError as exc:
        raise HTTPException(status_code=422 if exc.entrada_invalida else 502, detail=str(exc)) from None


@router.post(
    "/recomendar",
    tags=["Rotações"],
    response_model=RecomendacaoResponse,
    summary="Obter orientações condicionais com fontes da Embrapa",
    description=(
        "Consulta município, catálogo, janelas ZARC e referências técnicas. "
        "A análise NASA ainda não está integrada. Restrições livres exigem avaliação técnica."
    ),
)
def recomendar(
    dados: DadosAgricultor,
    servico: Annotated[RecomendacaoService, Depends(obter_servico_recomendacao)],
) -> RecomendacaoResponse:
    try:
        return servico.recomendar(dados)
    except LocalizacaoError as exc:
        raise HTTPException(status_code=422 if exc.entrada_invalida else 502, detail=str(exc)) from None
    except EmbrapaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
