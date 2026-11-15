// Apresentação do contrato RecomendacaoResponse; todo conteúdo externo é texto.
function element(tag, text, className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
}

function list(id, values, emptyText) {
  const container = document.getElementById(id);
  container.replaceChildren(...(values.length ? values : [emptyText]).map((value) => element("li", value)));
}

function noticeForFarmer(message) {
  if (/orientação por ia|respondeagro/i.test(message) && /indisponível|não configurad/i.test(message)) return null;
  if (/análise climática|fonte climática/i.test(message) && /indisponível|não configurad/i.test(message)) {
    return "Consulte novamente para ver o histórico climático.";
  }
  if (/zoneamento|zarc|agritec/i.test(message) && /indisponível|não configurad|falha/i.test(message)) {
    return "Consulte novamente o zoneamento antes de definir a data de plantio.";
  }
  if (/época de plantio.*não foi validada/i.test(message)) return "Confira os períodos de plantio antes de definir a data.";
  return message;
}

export function renderCultureOptions(options, onChooseCulture) {
  const container = document.getElementById("cultureOptions");
  document.getElementById("cultureSelection").classList.toggle("hidden", !options.length);
  container.replaceChildren(...options.map((option) => {
    const button = element("button", `Consultar ${option.nome}`, "secondary-button");
    button.type = "button";
    button.addEventListener("click", () => onChooseCulture(option));
    return button;
  }));
}

export function renderResults(data, onChooseCulture, onReviewSoil) {
  if (!["orientacao_condicional", "dados_insuficientes"].includes(data?.status)
      || !data.municipio || !data.dados_informados
      || !["janelas", "orientacoes", "pendencias", "avisos", "referencias", "fontes", "opcoes_cultura"].every((key) => Array.isArray(data[key]))) {
    throw new Error("O resultado recebido não está no formato esperado. Tente novamente.");
  }
  const informed = data.dados_informados;
  const crop = informed.cultura_desejada?.replaceAll("_", " ") || "Cultura não informada";
  const irrigation = informed.forma_irrigacao === "sem_irrigacao" ? "de sequeiro" : "irrigada";
  const soil = informed.tipo_solo?.toUpperCase().match(/^AD[1-6]$/)
    ? `Solo ${informed.tipo_solo.toUpperCase()}` : null;
  document.getElementById("resRegionBadge").textContent = [
    `${data.municipio.nome}, ${data.municipio.uf}`, `${crop} ${irrigation}`, soil,
  ].filter(Boolean).join(" · ");
  const confirmed = data.janelas_confirmadas || data.janelas;
  const ambiguous = data.status_zarc === "cultura_ambigua";
  document.getElementById("diagTitle").textContent = ambiguous ? "Escolha a opção de cultura"
    : confirmed.length ? "Há períodos compatíveis com seus dados"
    : data.status_zarc === "classe_solo_pendente" ? "Falta confirmar a classe do solo"
    : "Confira os dados de plantio";
  document.getElementById("diagText").textContent = ambiguous
    ? "Escolha a safra e o sistema de cultivo abaixo para ver os períodos de plantio."
    : confirmed.length ? `${data.cultura?.nome || data.dados_informados.cultura_desejada}: confira o período do grupo de ciclo da sua cultivar.`
    : data.status_zarc === "classe_solo_pendente" ? "Informe a classe AD da avaliação técnica. As opções de plantio ainda são condicionais."
    : "Confira os períodos e condições em “Quando plantar?”.";

  renderCultureOptions(data.opcoes_cultura, onChooseCulture);
  renderZarc(data, onReviewSoil);
  renderGemini(data);
  const titles = {
    conservacao_agua: "Conservar água", planejamento_climatico: "Planejar com o histórico climático",
    cobertura_solo: "Proteger e diversificar o solo", epoca_plantio: "Conferir a época de plantio",
    validar_solo_zarc: "Confirmar a classe do solo",
  };
  const recommendations = document.getElementById("recommendations");
  recommendations.replaceChildren(...data.orientacoes.map((item, index) => {
    const section = element("article", "", "guidance-item");
    section.append(element("h4", titles[item.tema] || `Orientação ${index + 1}`, "guidance-title"),
      element("p", item.texto, "guidance-text"));
    const details = element("details", "", "guidance-evidence");
    details.append(element("summary", "Fontes e dados utilizados"),
      element("p", `Fonte: ${item.fonte}`, "guidance-source"));
    for (const evidence of item.evidencias || []) details.append(element("p", evidence, "guidance-source"));
    try {
      const url = new URL(item.url_fonte);
      if (url.protocol === "https:") {
        const link = element("a", "Fundamentação da orientação", "reference-link");
        link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
        details.append(link);
      }
    } catch { /* Fonte sem link público. */ }
    section.append(details);
    return section;
  }));
  if (!data.orientacoes.length) recommendations.append(element("p", "Confira os dados da área e os períodos de plantio."));
  const pending = data.pendencias.map(noticeForFarmer).filter(Boolean);
  const warnings = data.avisos.map(noticeForFarmer).filter(Boolean);
  list("pendingItems", pending, "Nenhuma etapa adicional registrada.");
  list("warningItems", warnings, "Nenhum aviso adicional registrado.");
  document.getElementById("pendingCount").textContent = String(pending.length);
  document.getElementById("warningCount").textContent = String(warnings.length);
  document.getElementById("pendingDetails").open = pending.length > 0;
  document.getElementById("warningDetails").open = false;
  document.getElementById("technicalDetails").open = false;
  list("resultSources", data.fontes, "Nenhuma fonte informada.");
  renderClimate(data.resumo_climatico, data.analise_climatica_realizada);
}

export function renderGemini(data) {
  const summary = document.getElementById("aiSummary");
  const actions = document.getElementById("aiActions");
  summary.textContent = "";
  actions.replaceChildren();
  const personalizacao = document.getElementById("aiPersonalizacao");
  personalizacao.replaceChildren();
  const output = data.explicacao_ia;
  const available = data.status_ia === "disponivel" && typeof output?.resumo === "string"
    && Array.isArray(output.actions);
  const panel = document.getElementById("aiGuidance");
  panel.classList.toggle("hidden", !available);
  document.getElementById("fallbackGuidance").classList.toggle("hidden", available);
  document.getElementById("diagText").classList.toggle("hidden", available);
  if (!available) return;
  document.getElementById("diagTitle").textContent = "Resumo da sua área";
  summary.textContent = output.resumo;
  actions.replaceChildren(...output.actions.map((action) =>
    element("p", action.description, "ai-action-paragraph")));
}

export function renderZarc(data, onReviewSoil) {
  const labels = {
    disponivel: "Períodos compatíveis com os dados informados",
    parcial: "Há períodos compatíveis e outros condicionais",
    classe_solo_pendente: "",
    cultura_ambigua: "Selecione a opção de cultura",
    cultura_nao_encontrada: "Cultura não encontrada no município",
    cultura_invalida: "Selecione novamente a cultura",
    modalidade_indisponivel: "Revise a forma de irrigação",
    sem_dados: "Confira outra opção de cultura",
    sem_dados_compativeis: "Os períodos não atendem aos filtros",
    nao_configurado: "Consulte novamente",
    falha_autenticacao: "Confira o acesso ao catálogo",
    limite_consultas: "Tente consultar novamente",
    falha_conexao: "Tente consultar novamente",
    resposta_invalida: "Tente consultar novamente",
    falha_api: "Tente consultar novamente",
  };
  document.getElementById("zarcStatus").textContent = labels[data.status_zarc] ?? "Confira o resultado da consulta";
  const retryZarc = ["nao_configurado", "falha_autenticacao", "limite_consultas", "falha_conexao", "resposta_invalida", "falha_api"];
  document.getElementById("zarcMessage").textContent = noticeForFarmer(retryZarc.includes(data.status_zarc)
    ? "Consulte novamente o zoneamento antes de definir a data de plantio."
    : data.mensagem_zarc || "Confira as condições de cada período.")
    || "Confira as condições de cada período.";
  const groupWindows = (windows) => {
    const groups = new Map();
    for (const window of windows) {
      const key = [window.cultura, window.solo, window.ciclo, window.safra_inicio,
        window.safra_fim, window.risco, window.condicao || ""].join("|");
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(window);
    }
    return [...groups.values()];
  };
  const card = (group, conditional) => {
    const window = group[0];
    const article = element("article", "", conditional ? "planting-item conditional-window" : "planting-item");
    article.append(element("h4", window.ciclo || "Ciclo não informado", "result-subtitle"));
    for (const period of group) article.append(element("p",
      `${String(period.dia_inicio).padStart(2, "0")}/${String(period.mes_inicio).padStart(2, "0")} – ${String(period.dia_fim).padStart(2, "0")}/${String(period.mes_fim).padStart(2, "0")}`,
      "window-period"));
    article.append(element("p", `Safra ${window.safra_inicio}/${window.safra_fim} · Solo ${window.solo} · Risco ${window.risco}%`, "planting-meta"));
    const source = element("details", "", "guidance-evidence");
    source.append(element("summary", "Cultura e portaria"), element("p", window.cultura));
    for (const portaria of [...new Set(group.map((period) => period.portaria).filter(Boolean))]) {
      source.append(element("p", portaria));
    }
    article.append(source);
    if (conditional) article.append(element("p", window.condicao, "font-bold text-amber-900 mt-3"));
    return article;
  };
  const confirmed = data.janelas_confirmadas || data.janelas || [];
  const conditional = data.janelas_condicionais || [];
  const count = document.getElementById("zarcCount");
  count.textContent = confirmed.length ? `${confirmed.length} ${confirmed.length === 1 ? "período compatível" : "períodos compatíveis"}`
    : conditional.length ? `${conditional.length} ${conditional.length === 1 ? "período condicional" : "períodos condicionais"}`
    : "Confira os períodos";
  count.classList.toggle("result-count-pending", !confirmed.length);
  const windows = document.getElementById("plantingWindows");
  document.getElementById("confirmedWindowsSection").classList.toggle("hidden", !confirmed.length);
  windows.replaceChildren(...groupWindows(confirmed).map((group) => card(group, false)));
  if (!confirmed.length) windows.append(element("p", data.status_zarc === "cultura_ambigua"
    ? "Aguardando sua escolha de cultura acima para consultar as janelas."
    : "Confira outra opção de cultura ou consulte novamente."));
  document.getElementById("conditionalWindows").replaceChildren(...groupWindows(conditional).map((group) => card(group, true)));
  document.getElementById("conditionalWindowsSection").classList.toggle("hidden", !conditional.length);
  const button = document.getElementById("btnReviewSoil");
  button.disabled = typeof onReviewSoil !== "function";
  button.onclick = typeof onReviewSoil === "function" ? onReviewSoil : null;
  const diag = data.diagnostico_zarc;
  list("zarcDiagnostics", diag ? [
    `Etapa: ${diag.etapa} · Risco consultado: ${diag.risco_consultado}%`,
    `Janelas recebidas: ${diag.total_recebidas} · Compatíveis: ${confirmed.length} · Condicionais: ${conditional.length}`,
    `Descartadas por risco: ${diag.descartadas_risco} · Modalidade: ${diag.descartadas_modalidade} · Solo: ${diag.descartadas_solo}`,
    `Classificações retornadas: ${diag.solos_disponiveis.join(", ") || "nenhuma"}`,
  ] : [], "Diagnóstico detalhado não informado.");
}

export function renderClimate(climate, available) {
  const metrics = document.getElementById("climateMetrics");
  const monthly = document.getElementById("climateMonthly");
  const chart = document.getElementById("climateChart");
  metrics.replaceChildren();
  monthly.replaceChildren();
  chart.replaceChildren();
  if (!available || !climate) {
    document.getElementById("nasaStatus").textContent = "Consulte novamente para ver o histórico climático deste local.";
    return;
  }
  document.getElementById("nasaStatus").textContent = "";
  const format = (value, unit) => typeof value === "number" && Number.isFinite(value)
    ? `${value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} ${unit}` : "Dados insuficientes";
  for (const [label, value] of [
    ["Chuva média anual (anos completos)", climate.anos_chuva_completos === 0
      ? "Sem ano civil completo no período" : format(climate.precipitacao_media_anual_mm, "mm/ano")],
    ["Temperatura média", format(climate.temperatura_media_c, "°C")],
    ["Umidade relativa do ar a 2 m", format(climate.umidade_relativa_ar_pct, "%")],
    ["Radiação solar média", format(climate.radiacao_media_mj_m2_dia, "MJ/m²/dia")],
    ["Maior sequência com chuva inferior a 1 mm/dia", format(climate.maior_sequencia_dias_sem_chuva, "dias")],
  ]) {
    const card = element("div", "", "result-card");
    card.append(element("h4", label, "text-sm font-extrabold"), element("p", value, "window-period"));
    metrics.append(card);
  }
  const table = element("table", "", "climate-table");
  const head = element("thead", "");
  const header = element("tr", "");
  for (const label of ["Mês", "Chuva média (mm/mês)", "Temperatura média (°C)", "Anos com chuva completa"]) {
    const th = element("th", label); th.scope = "col"; header.append(th);
  }
  head.append(header);
  const body = element("tbody", "");
  const names = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  const months = Array.isArray(climate.meses) ? climate.meses : [];
  const rainfall = months.map((month) => month.precipitacao_media_mm)
    .filter((value) => typeof value === "number" && Number.isFinite(value) && value >= 0);
  if (months.length && rainfall.length) {
    const figure = element("figure", "", "climate-figure");
    figure.append(element("figcaption", "Chuva média por mês", "climate-chart-title"),
      element("p", "Barras mostram chuva em mm/mês. A temperatura média aparece abaixo de cada mês.", "climate-chart-help"));
    const scroll = element("div", "", "climate-chart-scroll");
    const bars = element("div", "", "climate-bars");
    const maximum = Math.max(...rainfall, 1);
    for (const month of months) {
      const rain = month.precipitacao_media_mm;
      const validRain = typeof rain === "number" && Number.isFinite(rain) && rain >= 0;
      const temperature = month.temperatura_media_c;
      const validTemperature = typeof temperature === "number" && Number.isFinite(temperature);
      const column = element("div", "", "climate-month");
      const rainLabel = validRain ? `${rain.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mm` : "Sem dados";
      const temperatureLabel = validTemperature
        ? `${temperature.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} °C` : "Temp. sem dados";
      column.setAttribute("aria-label", `${names[month.mes - 1] || month.mes}: chuva ${rainLabel}; temperatura ${temperatureLabel}`);
      column.append(element("span", rainLabel, "climate-rain-value"));
      const track = element("div", "", "climate-bar-track");
      if (validRain) {
        const bar = element("div", "", "climate-bar");
        bar.style.height = `${(rain / maximum) * 100}%`;
        bar.setAttribute("aria-hidden", "true");
        track.append(bar);
      }
      column.append(track, element("span", names[month.mes - 1] || String(month.mes), "climate-month-name"),
        element("span", temperatureLabel, "climate-temperature"));
      bars.append(column);
    }
    scroll.append(bars);
    figure.append(scroll);
    chart.append(figure);
  } else {
    chart.append(element("p", "Não há médias mensais de chuva suficientes para o gráfico.", "climate-chart-help"));
  }
  for (const month of months) {
    const row = element("tr", "");
    for (const value of [names[month.mes - 1] || month.mes, format(month.precipitacao_media_mm, ""),
      format(month.temperatura_media_c, ""), month.anos_chuva_completos]) row.append(element("td", value));
    body.append(row);
  }
  table.append(head, body);
  monthly.append(table);
}
