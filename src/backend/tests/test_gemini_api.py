"""Contratos de contexto e geração: nenhum acesso à rede ou chave real."""
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from src.backend.integration.gemini_api import GeminiClient
from src.backend.models.gemini import OrientacaoIAError, StructuredGeminiOutput
from src.backend.models.clima import ResumoClimatico
from src.backend.models.recomendacao import (
    DadosAgricultor, Municipio, RecomendacaoResponse, ReferenciaTecnica,
)
from src.backend.services.recomendacao import RecomendacaoService, montar_contexto_ia
from src.backend.modules.routes import obter_orientador_ia, recomendar


def saida_personalizada():
    return {
        "resumo": "Considere o maquinário disponível e confirme a interpretação do pH para soja.",
        "actions": [],
        "analise_ph": {
            "valor_informado": 6.2,
            "interpretacao": "pH 6,2 informado; sem método de medição e referência aplicável não é possível confirmar adequação para soja.",
            "orientacao": "Informe o método usado para medir o pH 6,2 e confronte com a referência da cultura.",
            "evidencias": ["usuario:ph"],
        },
        "analise_restricoes": {
            "texto_informado": "Não tenho maquinário para hortaliças/cenoura.",
            "impacto": "Uma opção que exija mecanização de cenoura depende de equipamento não disponível.",
            "orientacao": "Não planeje cenoura dependente desse equipamento sem confirmar acesso a serviço contratado e seu custo.",
            "evidencias": ["usuario:restricoes"],
        },
    }


@pytest.fixture
def dados():
    return DadosAgricultor(
        regiao_nome="Ouro Preto, MG", latitude=-20.38, longitude=-43.5,
        cultura_desejada="Soja", tipo_solo="AD1", tipo_solo_informado="raso", ph=6.2,
        historico_area="monocultura_pousio", forma_irrigacao="sem_irrigacao",
        objetivo="colher_mais", restricoes="Não tenho maquinário para hortaliças/cenoura.",
    )


@pytest.fixture
def resposta(dados):
    return RecomendacaoResponse(
        status="orientacao_condicional", dados_informados=dados,
        municipio=Municipio(codigo_ibge=3146107, nome="Ouro Preto", uf="MG"),
        resumo_climatico=ResumoClimatico(
            data_inicio=date(2023, 1, 1), data_fim=date(2025, 12, 31),
            dias_esperados=1096, cobertura_pct={"T2M": 100}, meses=[],
            temperatura_media_c=20, avisos=["Histórico, não previsão."],
        ),
        referencias=[ReferenciaTecnica(
            id="soja_1", pergunta="Como manejar?", resposta="Manter cobertura.", livro="Soja",
        )],
    )


def test_contexto_preserva_todos_campos_e_fontes_sem_alterar_resposta(resposta, dados):
    antes = resposta.model_dump_json()
    contexto = montar_contexto_ia(resposta)
    assert contexto["dados_informados"] == dados.model_dump(mode="json")
    assert contexto["dados_informados"]["tipo_solo_informado"] == "raso"
    assert contexto["resumo_climatico"]["data_inicio"] == "2023-01-01"
    assert contexto["referencias"][0]["resposta"] == "Manter cobertura."
    assert "nasa:resumo" in contexto["evidencias_contexto"]
    assert "embrapa:referencia:0" in contexto["evidencias_contexto"]
    assert "explicacao_ia" not in contexto
    assert resposta.model_dump_json() == antes


def test_adapter_envia_json_schema_e_retorna_saida_validada(resposta):
    client = Mock()
    client.interactions.create.return_value = SimpleNamespace(output_text=json.dumps({
        **saida_personalizada(), "resumo": "Confira as limitações.", "actions": [
            {"description": "Confira o manejo.", "evidencias": ["embrapa:referencia:0"]},
        ],
    }))
    resultado = GeminiClient(client).gerar(montar_contexto_ia(resposta))
    assert resultado.actions[0].description == "Confira o manejo."
    params = client.interactions.create.call_args.kwargs
    enviado = json.loads(params["input"].split("\n", 1)[1])
    assert enviado["dados_informados"]["ph"] == 6.2
    assert enviado["dados_informados"]["restricoes"] == resposta.dados_informados.restricoes
    assert params["response_format"]["schema"] == StructuredGeminiOutput.model_json_schema()
    assert params["store"] is False


@pytest.mark.parametrize("texto", ["", "não é JSON", '{}', json.dumps({
    "resumo": "Teste", "actions": [{"description": "Ação", "evidencias": ["inventada"]}],
})])
def test_adapter_rejeita_saida_invalida(resposta, texto):
    client = Mock()
    client.interactions.create.return_value = SimpleNamespace(output_text=texto)
    with pytest.raises(OrientacaoIAError):
        GeminiClient(client).gerar(montar_contexto_ia(resposta))


def test_adapter_converte_falha_provedor(resposta):
    client = Mock()
    client.interactions.create.side_effect = TimeoutError("detalhe privado")
    with pytest.raises(OrientacaoIAError, match="personalizada indisponível"):
        GeminiClient(client).gerar(montar_contexto_ia(resposta))


@pytest.mark.parametrize("falha", [False, True])
def test_fluxo_coleta_fontes_antes_da_ia_e_preserva_fallback(dados, resposta, falha):
    localizador, clima, referencias, ia = Mock(), Mock(), Mock(), Mock()
    localizador.resolver_municipio.return_value = resposta.municipio
    clima.obter_resumo.return_value = resposta.resumo_climatico
    referencias.buscar_referencias.return_value = resposta.referencias
    if falha:
        ia.gerar.side_effect = OrientacaoIAError()
    else:
        ia.gerar.return_value = StructuredGeminiOutput(**saida_personalizada())
    servico = RecomendacaoService(None, referencias, localizador, clima, ia)
    resultado = recomendar(dados, servico).model_dump(mode="json")
    contexto = ia.gerar.call_args.args[0]
    assert contexto["analise_climatica_realizada"] is True
    assert contexto["referencias"][0]["id"] == "soja_1"
    assert contexto["pendencias"]
    assert contexto["status_zarc"] == "nao_configurado"
    assert resultado["restricoes_avaliadas"] is False
    assert not any("As restrições em texto foram registradas" in p for p in resultado["pendencias"])
    assert any(dados.restricoes in p for p in resultado["pendencias"]) == falha
    assert resultado["status_ia"] == ("indisponivel" if falha else "disponivel")
    assert resultado["resumo_climatico"] is not None
    assert (resultado["explicacao_ia"] is None) == falha


def test_sem_chave_nao_inicializa_sdk():
    with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
        assert obter_orientador_ia() is None


def test_configuracao_usa_chave_explicita_modelo_e_timeout():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "teste", "GEMINI_MODEL": "modelo-teste"}), patch("google.genai.Client") as client:
        adapter = obter_orientador_ia()
    assert adapter._model == "modelo-teste"
    client.assert_called_once_with(api_key="teste", http_options={"timeout": 30000})


def test_contexto_sem_fontes_nao_fabrica_evidencias(resposta):
    resposta.resumo_climatico = None
    resposta.referencias = []
    contexto = montar_contexto_ia(resposta)
    assert contexto["resumo_climatico"] is None
    assert contexto["referencias"] == []
    assert contexto["evidencias_contexto"] == {
        "usuario": "/dados_informados", "usuario:ph": "/dados_informados/ph",
        "usuario:restricoes": "/dados_informados/restricoes",
    }


def test_sdk_instalado_aceita_parametros_sem_rede(resposta):
    from google import genai
    client = genai.Client(api_key="teste")
    try:
        with patch.object(client.interactions, "_send_create_once", return_value=Mock(
            output_text=json.dumps(saida_personalizada()),
        )) as enviar:
            resultado = GeminiClient(client).gerar(montar_contexto_ia(resposta))
        assert resultado.analise_ph.valor_informado == 6.2
        enviar.assert_called_once()
    finally:
        client.close()


@pytest.mark.parametrize("resumo,descricao,quantidade", [
    ("r" * 361, "Ação", 1), ("Resumo", "a" * 221, 1), ("Resumo", "Ação", 4),
])
def test_saida_personalizada_rejeita_textos_e_listas_extensos(resumo, descricao, quantidade):
    with pytest.raises(ValidationError):
        StructuredGeminiOutput(**dict(saida_personalizada(), resumo=resumo, actions=[
            {"description": descricao, "evidencias": ["usuario"]} for _ in range(quantidade)
        ]))


def test_saida_curta_preserva_acao_e_evidencias_no_limite():
    resultado = StructuredGeminiOutput(**dict(saida_personalizada(), resumo="r" * 360, actions=[
        {"description": "a" * 220, "evidencias": ["usuario"]} for _ in range(3)
    ]))
    assert len(resultado.actions) == 3
    assert resultado.actions[0].evidencias == ["usuario"]


@pytest.mark.parametrize("caso", ["sem_ph", "ph_trocado", "sem_restricoes", "restricoes_trocadas", "evidencia_ph", "evidencia_restricoes", "evidencia_inventada"])
def test_rejeita_analise_que_omite_ou_troca_dados_do_produtor(resposta, caso):
    output = saida_personalizada()
    if caso == "sem_ph":
        del output["analise_ph"]
    elif caso == "ph_trocado":
        output["analise_ph"]["valor_informado"] = 4.1
    elif caso == "sem_restricoes":
        output["analise_restricoes"] = None
    elif caso == "restricoes_trocadas":
        output["analise_restricoes"]["texto_informado"] = "Tenho todos os equipamentos."
    elif caso == "evidencia_ph":
        output["analise_ph"]["evidencias"] = ["usuario"]
    elif caso == "evidencia_restricoes":
        output["analise_restricoes"]["evidencias"] = ["usuario"]
    else:
        output["analise_restricoes"]["evidencias"].append("inventada")
    client = Mock()
    client.interactions.create.return_value = SimpleNamespace(output_text=json.dumps(output))
    with pytest.raises(OrientacaoIAError):
        GeminiClient(client).gerar(montar_contexto_ia(resposta))


def test_sem_restricoes_exige_analise_nula(resposta):
    resposta.dados_informados.restricoes = ""
    output = saida_personalizada()
    output["analise_restricoes"] = None
    client = Mock()
    client.interactions.create.return_value = SimpleNamespace(output_text=json.dumps(output))
    assert GeminiClient(client).gerar(montar_contexto_ia(resposta)).analise_restricoes is None
    output["analise_restricoes"] = saida_personalizada()["analise_restricoes"]
    client.interactions.create.return_value.output_text = json.dumps(output)
    with pytest.raises(OrientacaoIAError):
        GeminiClient(client).gerar(montar_contexto_ia(resposta))
