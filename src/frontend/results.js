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

export function renderResults(data, onChooseCulture, onReviewSoil) {
  if (!["orientacao_condicional", "dados_insuficientes"].includes(data?.status)
      || !data.municipio || !data.dados_informados
      || !["janelas", "orientacoes", "pendencias", "avisos", "referencias", "fontes", "opcoes_cultura"].every((key) => Array.isArray(data[key]))) {
    throw new Error("O resultado recebido não está no formato esperado. Tente novamente.");
  }
  document.getElementById("resRegionBadge").textContent = `${data.municipio.nome}, ${data.municipio.uf}`;
  const confirmed = data.janelas_confirmadas || data.janelas;
  const ambiguous = data.status_zarc === "cultura_ambigua";
  document.getElementById("diagTitle").textContent = ambiguous ? "Escolha a opção de cultura"
    : confirmed.length ? "Há períodos compatíveis com seus dados"
    : data.status_zarc === "classe_solo_pendente" ? "Falta confirmar a classe do solo"
    : "O plantio ainda precisa ser validado";
  document.getElementById("diagText").textContent = ambiguous
    ? "Escolha a safra e o sistema de cultivo abaixo para ver os períodos de plantio."
    : confirmed.length ? `${data.cultura?.nome || data.dados_informados.cultura_desejada}: confira o período do grupo de ciclo da sua cultivar.`
    : data.status_zarc === "classe_solo_pendente" ? "Informe a classe AD da avaliação técnica. As opções de plantio ainda são condicionais."
    : "Confira o motivo em “Quando plantar?” e as pendências de manejo abaixo.";

  const options = document.getElementById("cultureOptions");
  document.getElementById("cultureSelection").classList.toggle("hidden", !data.opcoes_cultura.length);
  options.replaceChildren(...data.opcoes_cultura.map((option) => {
    const button = element("button", `Consultar ${option.nome}`, "secondary-button");
    button.type = "button";
    button.addEventListener("click", () => onChooseCulture(option));
    return button;
  }));
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
  if (!data.orientacoes.length) recommendations.append(element("p", "Não há orientação conclusiva para esta consulta."));
  list("pendingItems", data.pendencias, "Nenhuma pendência adicional registrada.");
  list("warningItems", data.avisos, "Nenhum aviso adicional retornado.");
  document.getElementById("pendingCount").textContent = String(data.pendencias.length);
  document.getElementById("warningCount").textContent = String(data.avisos.length);
  document.getElementById("pendingDetails").open = data.pendencias.length > 0;
  document.getElementById("warningDetails").open = false;
  list("resultSources", data.fontes, "Nenhuma fonte informada.");
  const references = document.getElementById("technicalReferences");
  references.replaceChildren(...data.referencias.map((item) => {
    const card = element("article", "", "result-card");
    card.append(element("h4", item.pergunta, "font-extrabold"), element("p", item.resposta, "mt-2"),
      element("p", [item.livro, item.capitulo, item.ano].filter(Boolean).join(" · "), "text-sm text-slate-500 mt-2"));
    try {
      const url = new URL(item.url_publicacao);
      if (url.protocol === "https:") {
        const link = element("a", "Consultar publicação", "reference-link");
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        card.append(link);
      }
    } catch { /* Referência sem endereço utilizável: mantém o conteúdo e a origem. */ }
    return card;
  }));
  if (!data.referencias.length) references.append(element("p", "Nenhuma referência foi retornada nesta consulta."));
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
  document.getElementById("aiUnavailable").classList.toggle("hidden",
    data.status_ia !== "indisponivel" && !(data.status_ia === "disponivel" && !available));
  if (!available) return;
  document.getElementById("diagTitle").textContent = "Sua orientação personalizada";
  summary.textContent = output.resumo;
  const addAnalysis = (title, texts) => {
    const section = element("section", "", "result-card");
    section.append(element("h4", title));
    for (const text of texts) section.append(element("p", text));
    personalizacao.append(section);
  };
  if (output.analise_ph) {
    addAnalysis(`pH informado: ${output.analise_ph.valor_informado}`, [
      output.analise_ph.interpretacao, output.analise_ph.orientacao,
    ]);
  }
  if (output.analise_restricoes) {
    addAnalysis("Seus limites e restrições", [
      output.analise_restricoes.texto_informado,
      output.analise_restricoes.impacto, output.analise_restricoes.orientacao,
    ]);
  }
  const evidenceLabel = (id) => id === "usuario" ? "Dados informados"
    : id === "usuario:ph" ? "pH informado"
    : id === "usuario:restricoes" ? "Restrições informadas"
    : id === "nasa:resumo" ? "Histórico NASA"
    : id.startsWith("zarc:condicional:") ? "Período ZARC condicional"
    : id.startsWith("zarc:janela:") ? "Período ZARC compatível"
    : id.startsWith("embrapa:referencia:") ? "Publicação da Embrapa" : "Evidência a conferir";
  actions.replaceChildren(...output.actions.map((action) => {
    const item = element("li", "");
    item.append(element("p", action.description));
    const evidence = element("details", "", "guidance-evidence");
    evidence.append(element("summary", "Dados utilizados"), element("p",
      [...new Set((action.evidencias || []).map(evidenceLabel))].join(" · ")));
    item.append(evidence);
    return item;
  }));
}

export function renderZarc(data, onReviewSoil) {
  const labels = {
    disponivel: "ZARC: janelas compatíveis com os filtros",
    parcial: "ZARC: há janelas compatíveis e outras condicionais",
    classe_solo_pendente: "ZARC: classificação do solo pendente",
    cultura_ambigua: "ZARC: selecione a opção de cultura",
    cultura_nao_encontrada: "ZARC: cultura não encontrada no município",
    cultura_invalida: "ZARC: selecione novamente a cultura",
    modalidade_indisponivel: "ZARC: modalidade indisponível",
    sem_dados: "ZARC: consulta sem dados",
    sem_dados_compativeis: "ZARC: janelas retornadas não atendem aos filtros",
    nao_configurado: "ZARC: fonte não configurada",
    falha_autenticacao: "ZARC: acesso à Embrapa recusado",
    limite_consultas: "ZARC: limite de consultas atingido",
    falha_conexao: "ZARC: falha de conexão",
    resposta_invalida: "ZARC: resposta incompatível",
    falha_api: "ZARC: falha na consulta",
  };
  document.getElementById("zarcStatus").textContent = labels[data.status_zarc] || "ZARC: confira o resultado da consulta";
  document.getElementById("zarcMessage").textContent = data.mensagem_zarc || "Confira as pendências e as condições de cada período.";
  const card = (window, conditional) => {
    const article = element("article", "", conditional ? "planting-item conditional-window" : "planting-item");
    article.append(element("h4", window.ciclo, "result-subtitle"),
      element("p", `${window.dia_inicio}/${window.mes_inicio} a ${window.dia_fim}/${window.mes_fim}`, "window-period"),
      element("p", `Solo ${window.solo} · Safra ${window.safra_inicio}/${window.safra_fim} · Risco ${window.risco}%`, "planting-meta"));
    const source = element("details", "", "guidance-evidence");
    source.append(element("summary", "Cultura e portaria"), element("p", window.cultura), element("p", window.portaria));
    article.append(source);
    if (conditional) article.append(element("p", window.condicao, "font-bold text-amber-900 mt-3"));
    return article;
  };
  const confirmed = data.janelas_confirmadas || data.janelas || [];
  const conditional = data.janelas_condicionais || [];
  const windows = document.getElementById("plantingWindows");
  document.getElementById("confirmedWindowsSection").classList.toggle("hidden", !confirmed.length);
  document.getElementById("confirmedWindowsSection").open = false;
  windows.replaceChildren(...confirmed.map((window) => card(window, false)));
  if (!confirmed.length) windows.append(element("p", data.status_zarc === "cultura_ambigua"
    ? "Aguardando sua escolha de cultura acima para consultar as janelas."
    : "Nenhuma janela foi confirmada para os filtros informados."));
  document.getElementById("conditionalWindows").replaceChildren(...conditional.map((window) => card(window, true)));
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
  metrics.replaceChildren();
  monthly.replaceChildren();
  if (!available || !climate) {
    document.getElementById("nasaStatus").textContent = "Análise climática indisponível nesta consulta. Nenhuma métrica foi inventada; confira os avisos.";
    return;
  }
  document.getElementById("nasaStatus").textContent = `NASA POWER · ${climate.data_inicio} a ${climate.data_fim}. Histórico recente, não uma previsão.`;
  const format = (value, unit) => typeof value === "number" && Number.isFinite(value)
    ? `${value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} ${unit}` : "Dados insuficientes";
  for (const [label, value] of [
    ["Chuva média anual (anos completos)", format(climate.precipitacao_media_anual_mm, "mm/ano")],
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
  for (const month of climate.meses || []) {
    const row = element("tr", "");
    for (const value of [names[month.mes - 1] || month.mes, format(month.precipitacao_media_mm, ""),
      format(month.temperatura_media_c, ""), month.anos_chuva_completos]) row.append(element("td", value));
    body.append(row);
  }
  table.append(head, body);
  monthly.append(table);
  const projection = climate.projecao_chuva;
  if (projection && Array.isArray(projection.meses) && projection.meses.length) {
    const card = element("div", "", "result-card");
    card.append(element("h4", "Chuva estimada nos próximos 12 meses", "text-sm font-extrabold"),
      element("p", format(projection.total_estimado_mm, "mm"), "window-period"));
    metrics.append(card);
    monthly.append(element("h3", "Projeção de chuva — próximos 12 meses", "climate-chart-title"),
      element("p", projection.aviso || "Estimativa sazonal baseada no histórico recente.", "climate-chart-help"));
    const projectedTable = element("table", "", "climate-table");
    const projectedHead = element("thead", "");
    const projectedHeader = element("tr", "");
    for (const label of ["Mês/ano", "Chuva estimada (mm)", "Meses históricos utilizados"]) {
      const th = element("th", label); th.scope = "col"; projectedHeader.append(th);
    }
    projectedHead.append(projectedHeader);
    const projectedBody = element("tbody", "");
    for (const month of projection.meses) {
      const row = element("tr", "");
      for (const value of [`${names[month.mes - 1] || month.mes}/${month.ano}`,
        format(month.precipitacao_estimada_mm, ""), month.meses_historicos_utilizados]) {
        row.append(element("td", value));
      }
      projectedBody.append(row);
    }
    projectedTable.append(projectedHead, projectedBody);
    monthly.append(projectedTable);
  }
}
