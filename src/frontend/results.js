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
  document.getElementById("diagTitle").textContent = data.status === "orientacao_condicional"
    ? "Orientações disponíveis — confira as condições" : "Precisamos conferir algumas informações";
  document.getElementById("diagText").textContent = data.cultura
    ? `Cultura consultada: ${data.cultura.nome}. As janelas não substituem a avaliação da propriedade.`
    : "A janela da cultura desejada não foi validada. Confira as orientações disponíveis e as pendências.";

  const options = document.getElementById("cultureOptions");
  options.replaceChildren(...data.opcoes_cultura.map((option) => {
    const button = element("button", `${option.nome} · ${option.cultivo || "modalidade a conferir"}`, "secondary-button");
    button.type = "button";
    button.addEventListener("click", () => onChooseCulture(option));
    return button;
  }));
  renderZarc(data, onReviewSoil);
  const recommendations = document.getElementById("recommendations");
  recommendations.replaceChildren(...data.orientacoes.map((item) => {
    const section = element("div", "");
    section.append(element("p", item.texto), element("p", `Fonte: ${item.fonte}`, "text-sm text-slate-500"));
    for (const evidence of item.evidencias || []) section.append(element("p", evidence, "text-sm text-slate-600 mt-1"));
    try {
      const url = new URL(item.url_fonte);
      if (url.protocol === "https:") {
        const link = element("a", "Fundamentação da orientação", "reference-link");
        link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
        section.append(link);
      }
    } catch { /* Fonte sem link público. */ }
    return section;
  }));
  if (!data.orientacoes.length) recommendations.append(element("p", "Não há orientação conclusiva para esta consulta."));
  list("pendingItems", data.pendencias, "Nenhuma pendência adicional registrada.");
  list("warningItems", data.avisos, "Nenhum aviso adicional retornado.");
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
    const article = element("article", "", conditional ? "result-card conditional-window" : "result-card");
    article.append(element("h4", window.cultura, "font-extrabold"),
      element("p", `${window.dia_inicio}/${window.mes_inicio} a ${window.dia_fim}/${window.mes_fim}`, "window-period"),
      element("p", `Solo: ${window.solo} · Ciclo: ${window.ciclo}`),
      element("p", `Safra: ${window.safra_inicio}/${window.safra_fim} · Nível ZARC: ${window.risco}%`),
      element("p", window.portaria, "text-sm text-slate-600"));
    if (conditional) article.append(element("p", window.condicao, "font-bold text-amber-900 mt-3"));
    return article;
  };
  const confirmed = data.janelas_confirmadas || data.janelas || [];
  const conditional = data.janelas_condicionais || [];
  const windows = document.getElementById("plantingWindows");
  windows.replaceChildren(...confirmed.map((window) => card(window, false)));
  if (!confirmed.length) windows.append(element("p", "Nenhuma janela foi confirmada para os filtros informados."));
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
}
