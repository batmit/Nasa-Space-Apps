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

export function renderResults(data, onChooseCulture) {
  if (!["orientacao_condicional", "dados_insuficientes"].includes(data?.status)
      || !data.municipio || !data.dados_informados
      || !["janelas", "orientacoes", "pendencias", "avisos", "referencias", "fontes", "opcoes_cultura"].every((key) => Array.isArray(data[key]))) {
    throw new Error("O resultado recebido não está no formato esperado. Tente novamente.");
  }
  document.getElementById("resRegionBadge").textContent = `${data.municipio.nome}, ${data.municipio.uf}`;
  document.getElementById("diagTitle").textContent = data.status === "orientacao_condicional"
    ? "Janelas encontradas — confira as condições" : "Precisamos conferir algumas informações";
  document.getElementById("diagText").textContent = data.cultura
    ? `Cultura consultada: ${data.cultura.nome}. As janelas não substituem a avaliação da propriedade.`
    : "A cultura não foi identificada de forma única para as condições informadas.";

  const options = document.getElementById("cultureOptions");
  options.replaceChildren(...data.opcoes_cultura.map((option) => {
    const button = element("button", option.nome, "secondary-button");
    button.type = "button";
    button.addEventListener("click", () => onChooseCulture(option));
    return button;
  }));
  const windows = document.getElementById("plantingWindows");
  windows.replaceChildren(...data.janelas.map((window) => {
    const card = element("article", "", "result-card");
    card.append(element("h4", window.cultura, "font-extrabold"),
      element("p", `${window.dia_inicio}/${window.mes_inicio} a ${window.dia_fim}/${window.mes_fim}`, "window-period"),
      element("p", `Solo: ${window.solo} · Ciclo: ${window.ciclo}`),
      element("p", `Safra: ${window.safra_inicio}/${window.safra_fim} · Nível ZARC: ${window.risco}%`),
      element("p", window.portaria, "text-sm text-slate-600"));
    return card;
  }));
  if (!data.janelas.length) windows.append(element("p", "Nenhuma janela compatível foi retornada. Confira as pendências abaixo."));
  const recommendations = document.getElementById("recommendations");
  recommendations.replaceChildren(...data.orientacoes.map((item) => {
    const section = element("div", "");
    section.append(element("p", item.texto), element("p", `Fonte: ${item.fonte}`, "text-sm text-slate-500"));
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
  document.getElementById("nasaStatus").textContent = data.analise_climatica_realizada
    ? "Esta resposta não contém uma série climática para exibição."
    : "A análise climática ainda não está disponível neste fluxo. Nenhuma métrica climática foi estimada nesta consulta.";
}
