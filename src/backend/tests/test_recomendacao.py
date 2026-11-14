"""Verificações sem rede: python -m pytest src/backend/tests -q.

Os testes HTTP requerem httpx no ambiente de desenvolvimento.
"""

import gzip
import io
import json
import socket
import ssl
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.backend.integration.embrapa import (
    ConsultaZoneamento, CulturaEmbrapa, EmbrapaClient, EmbrapaError,
    JanelaPlantio, RespondeAgroClient, ResultadoZoneamento,
)
from src.backend.integration.localizacao import LocalizacaoClient, LocalizacaoError
from src.backend.main import app
from src.backend.models.recomendacao import DadosAgricultor, LocalizacaoSelecionada, Municipio
from src.backend.modules.routes import obter_localizador, obter_servico_recomendacao
from src.backend.services.recomendacao import RecomendacaoService


ENTRADA = dict(
    regiao_nome="Ouro Preto, MG", historico_area="monocultura_pousio", objetivo="recuperar_solo",
    latitude=-21.2, longitude=-50.4, cultura_desejada="milho",
    tipo_solo="argiloso", ph=5.5, forma_irrigacao="sem_irrigacao",
    restricoes="Pouca água disponível.",
)


def cultura(id=1, **campos):
    return CulturaEmbrapa.model_validate(dict(
        id=id, nome="MILHO SEQUEIRO", cultivo="SEQUEIRO", hasZoneamento=True, **campos,
    ))


def janela(**campos):
    valores = dict(
        municipio="ARAÇATUBA", uf="SP", cultura="MILHO", culturaNomeCompleto="MILHO SEQUEIRO",
        culturaSafra="não informado", culturaCultivo="SEQUEIRO", culturaClima="Não se aplica",
        ciclo="GRUPO I", solo="ARGILOSO", diaIni=21, mesIni=11, diaFim=30, mesFim=11,
        safraIni=2026, safraFim=2027, risco=20, portaria="Portaria de teste",
    )
    valores.update(campos)
    return JanelaPlantio.model_validate(valores)


class RecomendacaoTests(unittest.TestCase):
    def setUp(self):
        self.zoneamento, self.referencias, self.localizador = Mock(), Mock(), Mock()
        self.localizador.resolver_municipio.return_value = Municipio(
            codigo_ibge=3502804, nome="Araçatuba", uf="SP",
        )
        self.zoneamento.listar_culturas_municipio.return_value = [cultura()]
        self.zoneamento.consultar_zoneamento.return_value = ResultadoZoneamento(
            consulta=ConsultaZoneamento(codigo_ibge=3502804, id_cultura=1),
            janelas=[janela(), janela(solo="AD1"), janela(risco=30), janela(culturaCultivo="IRRIGADO")],
        )
        self.referencias.buscar_referencias.return_value = []
        self.servico = RecomendacaoService(self.zoneamento, self.referencias, self.localizador)
        app.dependency_overrides[obter_servico_recomendacao] = lambda: self.servico
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_rota_filtra_solo_irrigacao_e_risco(self):
        response = self.client.post("/api/v1/recomendar", json=ENTRADA)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "orientacao_condicional")
        self.assertEqual(len(payload["janelas"]), 1)
        self.assertFalse(payload["restricoes_avaliadas"])
        self.assertFalse(payload["analise_climatica_realizada"])
        self.assertTrue(payload["pendencias"])

    def test_contrato_frontend_preserva_contexto_e_avisa_divergencia(self):
        payload = self.client.post("/api/v1/recomendar", json=ENTRADA).json()
        self.assertEqual(payload["dados_informados"], dict(ENTRADA, id_cultura=None))
        self.assertEqual(payload["municipio"]["codigo_ibge"], 3502804)
        self.assertTrue(any("difere" in aviso for aviso in payload["avisos"]))
        self.assertIn("recuperar solo", self.referencias.buscar_referencias.call_args.args[0])
        self.assertIn("monocultura pousio", self.referencias.buscar_referencias.call_args.args[0])

    def test_nome_regiao_compativel_nao_avisa_divergencia(self):
        entrada = dict(ENTRADA, regiao_nome="Aracatuba, SP")
        payload = self.client.post("/api/v1/recomendar", json=entrada).json()
        self.assertFalse(any("difere" in aviso for aviso in payload["avisos"]))

    def test_cultura_ambigua_nao_escolhe_id_arbitrario(self):
        self.zoneamento.listar_culturas_municipio.return_value = [cultura(), cultura(id=2)]
        result = self.servico.recomendar(DadosAgricultor(**ENTRADA))
        self.assertEqual(result.status, "dados_insuficientes")
        self.assertEqual(len(result.opcoes_cultura), 2)
        self.zoneamento.consultar_zoneamento.assert_not_called()

    def test_irrigacao_nao_reutiliza_cultura_sequeiro(self):
        result = self.servico.recomendar(DadosAgricultor(**dict(ENTRADA, forma_irrigacao="gotejamento")))
        self.assertIsNone(result.cultura)
        self.zoneamento.consultar_zoneamento.assert_not_called()

    def test_solo_sem_janela_nao_inventa_classe_ad(self):
        result = self.servico.recomendar(DadosAgricultor(**dict(ENTRADA, tipo_solo="arenoso")))
        self.assertEqual(result.janelas, [])
        self.assertEqual(result.status_zarc, "classe_solo_pendente")
        self.assertEqual(result.janelas_condicionais[0].solo, "AD1")

    def test_falha_referencias_preserva_zoneamento(self):
        self.referencias.buscar_referencias.side_effect = EmbrapaError("offline")
        result = self.servico.recomendar(DadosAgricultor(**ENTRADA))
        self.assertEqual(len(result.janelas), 1)
        self.assertTrue(any("indisponível" in aviso for aviso in result.avisos))

    def test_validacao_contrato_publico(self):
        for campos in ({"ph": 15}, {"latitude": 100}, {"cultura_desejada": " "},
                       {"prioridade": "lucro"}, {"historico": ["soja"]}, {"risco": "40"},
                       {"regiao_nome": " "}, {"historico_area": ""}, {"objetivo": " "}):
            with self.subTest(campos=campos):
                self.assertEqual(self.client.post("/api/v1/recomendar", json=dict(ENTRADA, **campos)).status_code, 422)
        self.assertNotIn("risco", ConsultaZoneamento.model_fields)

    def test_falhas_externas_e_localizacao(self):
        self.zoneamento.listar_culturas_municipio.side_effect = EmbrapaError("Falha externa", 401)
        response = self.client.post("/api/v1/recomendar", json=ENTRADA)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "dados_insuficientes")
        self.assertTrue(any("indisponível" in item for item in response.json()["pendencias"]))
        self.localizador.resolver_municipio.side_effect = LocalizacaoError("Fora do Brasil", entrada_invalida=True)
        self.assertEqual(self.client.post("/api/v1/recomendar", json=ENTRADA).status_code, 422)

    def test_health_nao_exige_credenciais(self):
        self.assertEqual(self.client.get("/api/v1/health").json(), {"status": "ok"})

    def test_frontend_e_api_compartilham_origem(self):
        self.assertIn("AgroOrbit", self.client.get("/").text)
        for asset in ("app.js", "api.js", "results.js", "styles.css"):
            self.assertEqual(self.client.get("/" + asset).status_code, 200)
        self.assertIn("/api/v1/recomendar", self.client.get("/api.js").text)
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_localizacao_independe_de_token_embrapa(self):
        self.localizador.buscar_localizacao.return_value = LocalizacaoSelecionada(
            regiao_nome="Ouro Preto, MG", latitude=-20.3856, longitude=-43.5035,
        )
        self.localizador.resolver_localizacao.return_value = self.localizador.buscar_localizacao.return_value
        app.dependency_overrides[obter_localizador] = lambda: self.localizador
        response = self.client.get("/api/v1/localizacao/buscar", params={"consulta": "Ouro Preto MG"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["regiao_nome"], "Ouro Preto, MG")
        response = self.client.get("/api/v1/localizacao/reversa", params={"latitude": -20.3856, "longitude": -43.5035})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/localizacao/reversa", params={"latitude": 999, "longitude": 1}).status_code, 422)

    def test_valores_solo_da_interface_sao_aceitos_sem_falsa_equivalencia(self):
        for solo in ("textura_media", "arenoso", "argiloso", "raso"):
            response = self.client.post("/api/v1/recomendar", json=dict(ENTRADA, tipo_solo=solo))
            self.assertEqual(response.status_code, 200)
            if solo != "argiloso":
                self.assertEqual(response.json()["janelas"], [])


class AdaptadoresTests(unittest.TestCase):
    def setUp(self):
        # O relógio/rate limiter não precisa aguardar em testes sem rede.
        self.sleep_patch = patch("src.backend.integration.localizacao.time.sleep")
        self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)

    def test_localizacao_le_json_gzip_e_sem_compactacao(self):
        payload = [{"id": 3146107, "nome": "Ouro Preto"}]
        for encoding in ("", "gzip"):
            body = json.dumps(payload).encode("utf-8")
            if encoding:
                body = gzip.compress(body)
            response = io.BytesIO(body)
            response.headers = {"Content-Encoding": encoding}
            with self.subTest(encoding=encoding), patch("src.backend.integration.localizacao.urlopen", return_value=response):
                result = LocalizacaoClient()._get("https://servicodados.ibge.gov.br/api/v1/localidades/estados/MG/municipios")
                self.assertEqual(result, payload)

    def test_localizacao_identifica_servico_e_tipo_de_falha(self):
        errors = [
            (HTTPError("https://example.org", 403, "Forbidden", {}, None), "HTTP 403"),
            (HTTPError("https://example.org", 429, "Limit", {}, None), "Limite"),
            (URLError(socket.gaierror("DNS")), "DNS"),
            (URLError(ssl.SSLCertVerificationError("certificate")), "certificado"),
            (URLError(TimeoutError()), "tempo de resposta"),
            (TimeoutError(), "tempo de resposta"),
        ]
        for error, text in errors:
            with self.subTest(error=text), patch("src.backend.integration.localizacao.urlopen", side_effect=error):
                with self.assertRaises(LocalizacaoError) as result:
                    LocalizacaoClient()._get("https://nominatim.openstreetmap.org/reverse")
                self.assertIn("Nominatim", str(result.exception))
                self.assertIn(text, str(result.exception))

    def test_localizacao_recusa_json_e_gzip_invalidos(self):
        for encoding, body in (("", b"<html>erro</html>"), ("gzip", b"gzip invalido")):
            response = io.BytesIO(body)
            response.headers = {"Content-Encoding": encoding}
            with self.subTest(encoding=encoding), patch("src.backend.integration.localizacao.urlopen", return_value=response):
                with self.assertRaises(LocalizacaoError) as result:
                    LocalizacaoClient()._get("https://servicodados.ibge.gov.br/api/v1/localidades/estados/MG/municipios")
                self.assertIn("IBGE", str(result.exception))
                self.assertIn("inválida", str(result.exception))

    def test_agritec_envia_risco_padrao(self):
        with patch("src.backend.integration.embrapa.urlopen", return_value=io.BytesIO(b'{"data":[]}')) as request:
            result = EmbrapaClient("teste").consultar_zoneamento(ConsultaZoneamento(codigo_ibge=3502804, id_cultura=1))
            self.assertEqual(result.janelas, [])
            self.assertIn("risco=20", request.call_args.args[0].full_url)

    def test_agritec_nao_trata_json_invalido_como_lista_vazia(self):
        for payload in (b"{}", b"<html>erro</html>"):
            with patch("src.backend.integration.embrapa.urlopen", return_value=io.BytesIO(payload)):
                with self.assertRaises(EmbrapaError):
                    EmbrapaClient("teste").listar_culturas()

    def test_agritec_trata_http_e_rede(self):
        for error in (HTTPError("https://example.org", 429, "limit", {}, None), URLError("offline")):
            with patch("src.backend.integration.embrapa.urlopen", side_effect=error):
                with self.assertRaises(EmbrapaError):
                    EmbrapaClient("teste").listar_culturas()

    def test_respondeagro_post_extrai_referencia_e_remove_html(self):
        payload = {"hits": {"hits": [{"_id": "milho_1", "_source": {
            "question": "Como manejar?", "answer": "<p>Resposta <b>técnica</b>.</p>",
            "book": "Milho", "year": 2020, "pdf": "javascript:alert(1)",
        }}]}}
        with patch("src.backend.integration.embrapa.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            result = RespondeAgroClient("teste").buscar_referencias(['milho" OR *', "solo"])
            sent = request.call_args.args[0]
            self.assertEqual(sent.get_method(), "POST")
            query = json.loads(sent.data)["params"]["query_string"]
            self.assertIn('\\"', query)
            self.assertIn(" AND ", query)
            self.assertNotIn("<", result[0].resposta)
            self.assertIsNone(result[0].url_publicacao)

    def test_geocodificacao_resolve_ibge_com_cache(self):
        client = LocalizacaoClient()
        with patch.object(client, "_get", side_effect=[
            {"address": {"country_code": "br", "ISO3166-2-lvl4": "BR-SP", "city": "Araçatuba"}},
            [{"id": 3502804, "nome": "Araçatuba"}],
        ]) as request:
            result = client.resolver_municipio(-21.2, -50.4)
            self.assertEqual(result.codigo_ibge, 3502804)
            client.resolver_municipio(-21.2, -50.4)
            self.assertEqual(request.call_count, 2)

    def test_geocodificacao_recusa_municipio_ambiguo_e_exterior(self):
        for address in (
            {"country_code": "ar"},
            {"country_code": "br", "ISO3166-2-lvl4": "BR-SP", "city": "Desconhecido"},
        ):
            client = LocalizacaoClient()
            with patch.object(client, "_get", side_effect=[{"address": address}, []]):
                with self.assertRaises(LocalizacaoError):
                    client.resolver_municipio(-21.2, -50.4)

    def test_busca_localizacao_valida_coordenadas_e_reutiliza_cache(self):
        client = LocalizacaoClient()
        with patch.object(client, "_get", side_effect=[
            [{"lat": "-20.3856", "lon": "-43.5035"}],
            {"address": {"country_code": "br", "ISO3166-2-lvl4": "BR-MG", "city": "Ouro Preto"}},
            [{"id": 3146107, "nome": "Ouro Preto"}],
        ]) as request:
            result = client.buscar_localizacao("Ouro Preto MG")
            self.assertEqual(result.regiao_nome, "Ouro Preto, MG")
            client.buscar_localizacao("Ouro Preto MG")
            self.assertEqual(request.call_count, 3)
        with patch.object(client, "_nominatim", return_value=[{"lat": 999, "lon": 0}]):
            with self.assertRaises(LocalizacaoError):
                client.buscar_localizacao("outra cidade")


if __name__ == "__main__":
    unittest.main()
