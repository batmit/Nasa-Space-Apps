"""Converte séries brutas NASA em indicadores históricos com cobertura explícita."""

import math
from datetime import date, timedelta
from statistics import mean

from ..integration.nasa_power import NasaPowerError, request_NASA_API
from ..models.clima import ClimaError, MesClimatico, MesProjetado, ProjecaoChuva, ResumoClimatico


def _media(values: list[float]) -> float | None:
    return round(mean(values), 2) if values else None


def resumir_clima(payload: dict, inicio: date, fim: date) -> ResumoClimatico:
    """Não preenche lacunas; totais de chuva exigem todos os dias do mês/ano."""
    if inicio > fim:
        raise ClimaError("Período climático inválido.")
    properties = payload.get("properties", {})
    series = properties.get("parameter", {}) if isinstance(properties, dict) else {}
    metadata = payload.get("parameters", {})
    if not isinstance(series, dict) or not isinstance(metadata, dict):
        raise ClimaError("Resposta NASA incompatível com o resumo climático.")
    unidades = {key: value.get("units", "") for key, value in metadata.items() if isinstance(value, dict)}
    if unidades.get("T2M") not in ("C", "°C", "degC") or unidades.get("PRECTOTCORR") != "mm/day":
        raise ClimaError("Unidades de temperatura ou chuva da NASA ausentes ou incompatíveis.")
    datas = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
    header = payload.get("header", {})
    fill_value = header.get("fill_value", -999) if isinstance(header, dict) else -999
    parametros = ("T2M", "T2M_MIN", "T2M_MAX", "PRECTOTCORR", "RH2M", "ALLSKY_SFC_SW_DWN")
    limpos: dict[str, dict[date, float]] = {key: {} for key in parametros}
    avisos = [
        f"O resumo descreve o histórico de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}; "
        "não é previsão meteorológica nem projeção de mudança climática.",
        "Os dados NASA representam uma célula de grade, não uma medição no talhão.",
        "RH2M é umidade relativa do ar a 2 m; não representa umidade do solo ou das raízes.",
    ]
    fatores_solar = {"MJ/m^2/day": 1.0, "kW-hr/m^2/day": 3.6, "kWh/m^2/day": 3.6}
    for parametro in parametros:
        unidade = unidades.get(parametro)
        fator = 1.0
        if parametro.startswith("T2M") and unidade not in ("C", "°C", "degC"):
            continue
        if parametro == "RH2M" and unidade != "%":
            continue
        if parametro == "ALLSKY_SFC_SW_DWN":
            if unidade not in fatores_solar:
                avisos.append("Radiação solar omitida por unidade desconhecida nos metadados NASA.")
                continue
            fator = fatores_solar[unidade]
        raw = series.get(parametro, {})
        if not isinstance(raw, dict):
            continue
        for dia in datas:
            value = raw.get(dia.strftime("%Y%m%d"))
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                continue
            if value == fill_value or value in (-999, -9999):
                continue
            if parametro in ("PRECTOTCORR", "ALLSKY_SFC_SW_DWN") and value < 0:
                continue
            if parametro == "RH2M" and not 0 <= value <= 100:
                continue
            limpos[parametro][dia] = value * fator
    cobertura = {key: round(len(values) / len(datas) * 100, 2) for key, values in limpos.items()}
    if any(len(limpos[key]) / len(datas) < 0.9 for key in ("T2M", "PRECTOTCORR")):
        raise ClimaError("Cobertura NASA insuficiente: temperatura e chuva exigem ao menos 90% dos dias válidos.")
    for key, value in cobertura.items():
        if value < 100:
            avisos.append(f"Cobertura de {key}: {value}%. Lacunas não foram preenchidas.")

    def valores(key: str, dias: list[date]) -> list[float]:
        return [limpos[key][dia] for dia in dias if dia in limpos[key]]

    def media_coberta(key: str, dias: list[date]) -> float | None:
        values = valores(key, dias)
        return _media(values) if len(values) / len(dias) >= 0.9 else None

    anos = range(inicio.year, fim.year + 1)
    anuais = []
    for ano in anos:
        dias_ano = [dia for dia in datas if dia.year == ano]
        ano_completo = len(dias_ano) == (date(ano + 1, 1, 1) - date(ano, 1, 1)).days
        if ano_completo and all(dia in limpos["PRECTOTCORR"] for dia in dias_ano):
            anuais.append(sum(valores("PRECTOTCORR", dias_ano)))
    meses = []
    for mes in range(1, 13):
        dias_mes = [dia for dia in datas if dia.month == mes]
        if not dias_mes:
            continue
        totais_mes = []
        for ano in anos:
            dias = [dia for dia in dias_mes if dia.year == ano]
            seguinte = date(ano + (mes == 12), mes % 12 + 1, 1)
            if len(dias) == (seguinte - date(ano, mes, 1)).days and all(dia in limpos["PRECTOTCORR"] for dia in dias):
                totais_mes.append(sum(valores("PRECTOTCORR", dias)))
        meses.append(MesClimatico(
            mes=mes, precipitacao_media_mm=_media(totais_mes), anos_chuva_completos=len(totais_mes),
            temperatura_media_c=media_coberta("T2M", dias_mes),
            umidade_relativa_ar_pct=media_coberta("RH2M", dias_mes),
            radiacao_media_mj_m2_dia=media_coberta("ALLSKY_SFC_SW_DWN", dias_mes),
        ))
    if not anuais:
        avisos.append("Não há ano civil com chuva diária completa no período; a média anual não foi calculada.")
    if any(mes.anos_chuva_completos < 2 for mes in meses):
        avisos.append(
            "Alguns meses têm menos de duas observações completas de chuva; "
            "o histórico é insuficiente para a orientação de sazonalidade."
        )
    maior = atual = 0
    for dia in datas:
        chuva = limpos["PRECTOTCORR"].get(dia)
        atual = atual + 1 if chuva is not None and chuva < 1.0 else 0
        maior = max(maior, atual)
    minimas = valores("T2M_MIN", datas)
    maximas = valores("T2M_MAX", datas)
    return ResumoClimatico(
        data_inicio=inicio, data_fim=fim, dias_esperados=len(datas), cobertura_pct=cobertura,
        precipitacao_media_anual_mm=_media(anuais), anos_chuva_completos=len(anuais),
        temperatura_media_c=media_coberta("T2M", datas),
        temperatura_minima_c=round(min(minimas), 2) if cobertura["T2M_MIN"] >= 90 else None,
        temperatura_maxima_c=round(max(maximas), 2) if cobertura["T2M_MAX"] >= 90 else None,
        umidade_relativa_ar_pct=media_coberta("RH2M", datas),
        radiacao_media_mj_m2_dia=media_coberta("ALLSKY_SFC_SW_DWN", datas),
        maior_sequencia_dias_sem_chuva=maior, meses=meses, avisos=avisos,
    )


def projetar_chuva(resumo: ResumoClimatico, hoje: date) -> ProjecaoChuva:
    """Repete a média de cada mês do ano nos próximos 12 meses completos."""
    historico = {mes.mes: mes for mes in resumo.meses}
    meses = []
    for deslocamento in range(1, 13):
        ano, mes_zero = divmod(hoje.year * 12 + hoje.month - 1 + deslocamento, 12)
        mes = mes_zero + 1
        observado = historico.get(mes)
        meses.append(MesProjetado(
            ano=ano, mes=mes,
            precipitacao_estimada_mm=observado.precipitacao_media_mm if observado else None,
            meses_historicos_utilizados=observado.anos_chuva_completos if observado else 0,
        ))
    total = (
        round(sum(mes.precipitacao_estimada_mm for mes in meses), 2)
        if all(mes.precipitacao_estimada_mm is not None for mes in meses) else None
    )
    return ProjecaoChuva(meses=meses, total_estimado_mm=total)


class NasaClimaService:
    """Consulta os últimos 18 meses completos, sem incluir o mês em andamento."""

    def __init__(self, *, hoje: date | None = None):
        self._hoje = hoje

    def obter_resumo(self, latitude: float, longitude: float) -> ResumoClimatico:
        hoje = self._hoje or date.today()
        ano_inicio, mes_inicio = divmod(hoje.year * 12 + hoje.month - 1 - 18, 12)
        inicio = date(ano_inicio, mes_inicio + 1, 1)
        fim = hoje.replace(day=1) - timedelta(days=1)
        try:
            payload = request_NASA_API(latitude, longitude, inicio.strftime("%Y%m%d"), fim.strftime("%Y%m%d"))
        except (NasaPowerError, OSError) as exc:
            raise ClimaError("Não foi possível obter ou armazenar os dados NASA POWER.") from exc
        resumo = resumir_clima(payload, inicio, fim)
        resumo.projecao_chuva = projetar_chuva(resumo, hoje)
        return resumo
