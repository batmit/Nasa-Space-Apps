"""Regras explicáveis de manejo; sem chamadas HTTP ou prescrições de insumos."""

from ..models.recomendacao import DadosAgricultor, FormaIrrigacao, Orientacao, RecomendacaoResponse


EMBRAPA_MANEJO = "https://www.embrapa.br/web/agencia-de-informacao-tecnologica/cultivos/milho/producao/rotacao-de-culturas"
NASA_METODO = "https://power.larc.nasa.gov/docs/services/api/temporal/daily/"


def gerar_orientacoes(dados: DadosAgricultor, resultado: RecomendacaoResponse) -> list[Orientacao]:
    orientacoes = []
    if resultado.janelas:
        orientacoes.append(Orientacao(
            tema="epoca_plantio", fonte="Embrapa Agritec v2 / ZARC",
            texto="Planeje o plantio dentro de uma das janelas listadas, conferindo solo, ciclo, modalidade e safra. Confirme as condições atuais antes de executar o plantio.",
            evidencias=[f"{len(resultado.janelas)} janela(s) compatível(is) com os filtros informados; risco ZARC de 20%."],
        ))
    if resultado.janelas_condicionais:
        orientacoes.append(Orientacao(
            tema="validar_solo_zarc", fonte="Embrapa Agritec v2 / ZARC",
            texto="Confirme tecnicamente a classificação do solo antes de utilizar qualquer janela condicional. A textura ou a profundidade informada não estabelece equivalência automática com uma classe AD.",
            evidencias=[f"{len(resultado.janelas_condicionais)} janela(s) dependem de confirmação do solo.",
                        "Classificações retornadas: " + ", ".join(resultado.diagnostico_zarc.solos_disponiveis)],
        ))
    clima = resultado.resumo_climatico
    if clima:
        secos = clima.maior_sequencia_dias_sem_chuva
        if secos:
            sequeiro = dados.forma_irrigacao == FormaIrrigacao.SEM_IRRIGACAO
            orientacoes.append(Orientacao(
                tema="conservacao_agua", fonte="NASA POWER + Embrapa — manejo do solo",
                url_fonte=EMBRAPA_MANEJO,
                texto=("Mantenha os resíduos vegetais cobrindo o solo para reduzir a evaporação. "
                       + ("Como o cultivo é de sequeiro, confirme a disponibilidade de água no solo e o estabelecimento das chuvas antes de plantar; o histórico não prevê a próxima chuva."
                          if sequeiro else "Confira a disponibilidade da fonte de água e o manejo da irrigação; a série histórica não determina a lâmina necessária.")),
                evidencias=[f"Maior sequência observada no período: {secos} dias com precipitação inferior a 1 mm/dia.",
                            f"Período analisado: {clima.data_inicio} a {clima.data_fim}."],
            ))
        meses = [mes for mes in clima.meses if mes.precipitacao_media_mm is not None]
        if len(meses) == 12 and all(mes.anos_chuva_completos >= 2 for mes in meses):
            menor = min(meses, key=lambda mes: mes.precipitacao_media_mm)
            maior = max(meses, key=lambda mes: mes.precipitacao_media_mm)
            orientacoes.append(Orientacao(
                tema="planejamento_climatico", fonte="NASA POWER + Embrapa Agritec / ZARC" if resultado.janelas else "NASA POWER",
                url_fonte=NASA_METODO,
                texto=(f"No histórico analisado, o mês {maior.mes:02d} teve a maior média mensal de chuva e o mês {menor.mes:02d}, a menor. "
                       + ("Use essa sazonalidade para avaliar as janelas ZARC apresentadas; não amplie a janela oficial com base nas médias."
                          if resultado.janelas else "Use essa sazonalidade para planejar a disponibilidade de água. Aguarde a confirmação de uma janela ZARC antes de definir a época de plantio.")),
                evidencias=[f"Mês {maior.mes:02d}: {maior.precipitacao_media_mm:.1f} mm; mês {menor.mes:02d}: {menor.precipitacao_media_mm:.1f} mm.",
                            "Médias calculadas somente com meses de chuva completos; não representam previsão."],
            ))
    if dados.objetivo in ("recuperar_solo", "conservar_agua"):
        orientacoes.append(Orientacao(
            tema="cobertura_solo", fonte="Embrapa — princípios de rotação e cobertura",
            url_fonte=EMBRAPA_MANEJO,
            texto="Planeje a manutenção de cobertura vegetal e a diversificação da área. Escolha espécies de cobertura com assistência técnica, considerando água disponível, janela local e as restrições registradas; não há espécie de sucessão validada automaticamente nesta consulta.",
            evidencias=[f"Objetivo informado: {dados.objetivo.replace('_', ' ')}.",
                        f"Histórico resumido: {dados.historico_area.replace('_', ' ')}."],
        ))
    return orientacoes
