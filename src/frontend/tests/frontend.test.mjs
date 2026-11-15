import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ApiError, buildPayload, buscarOpcoesCultura, recomendar, requestJson } from "../api.js";
import { renderClimate, renderResults, renderZarc, renderGemini } from "../results.js";

const input = {
  regiao_nome: "Ouro Preto, MG", latitude: "-20.3856", longitude: "-43.5035",
  cultura_desejada: "milho", tipo_solo: "textura_media", ph: "5.5",
  forma_irrigacao: "sem_irrigacao", historico_area: "monocultura_pousio",
  objetivo: "recuperar_solo", restricoes: " Pouca água. ",
};
const form = (values) => new Map(Object.entries(values));

test("payload contém os dez campos, números e restrições normalizadas", () => {
  const payload = buildPayload(form(input));
  assert.equal(Object.keys(payload).length, 10);
  assert.equal(payload.latitude, -20.3856);
  assert.equal(payload.ph, 5.5);
  assert.equal(payload.restricoes, "Pouca água.");
  assert.equal(buildPayload(form({ ...input, latitude: "0", longitude: "0" })).latitude, 0);
});

test("coordenadas ausentes, inválidas e restrições longas não são enviadas", () => {
  for (const values of [{ latitude: "" }, { latitude: "100" }, { longitude: "NaN" }, { ph: "" }, { restricoes: "x".repeat(2001) }]) {
    assert.throws(() => buildPayload(form({ ...input, ...values })));
  }
});

test("ID opcional da escolha de cultura é inteiro e não é adicionado ao envio inicial", () => {
  assert.equal(buildPayload(form({ ...input, id_cultura: "20" })).id_cultura, 20);
  assert.equal("id_cultura" in buildPayload(form(input)), false);
  for (const id of ["0", "1.5", "NaN", "-1"]) assert.throws(() => buildPayload(form({ ...input, id_cultura: id })));
});

test("chamada usa a rota real, mesma origem e JSON", async (context) => {
  context.mock.method(globalThis, "fetch", async (path, options) => {
    assert.equal(path, "/api/v1/recomendar");
    assert.equal(options.method, "POST");
    assert.equal(JSON.parse(options.body).cultura_desejada, "milho");
    return { ok: true, json: async () => ({ status: "dados_insuficientes" }) };
  });
  assert.equal((await recomendar(buildPayload(form(input)))).status, "dados_insuficientes");
});

test("catálogo consulta apenas localização, cultura e irrigação antes da recomendação", async (context) => {
  context.mock.method(globalThis, "fetch", async (path, options) => {
    assert.equal(path, "/api/v1/culturas/opcoes");
    assert.deepEqual(JSON.parse(options.body), {
      latitude: -20.3856, longitude: -43.5035,
      cultura_desejada: "milho", forma_irrigacao: "sem_irrigacao",
    });
    return { ok: true, json: async () => ({ municipio: { nome: "Ouro Preto", uf: "MG" }, opcoes: [] }) };
  });
  assert.deepEqual((await buscarOpcoesCultura(buildPayload(form(input)))).opcoes, []);
});

test("erros HTTP, JSON inválido e rede são informados sem resposta fictícia", async (context) => {
  context.mock.method(globalThis, "fetch", async () => ({ ok: false, status: 503, json: async () => ({ detail: "Integrações não configuradas." }) }));
  await assert.rejects(requestJson("/api/v1/recomendar"), (error) => error instanceof ApiError && error.status === 503);
  globalThis.fetch = async () => { throw new TypeError("offline"); };
  await assert.rejects(requestJson("/api/v1/recomendar"), /conectar/);
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => { throw new Error("html"); } });
  await assert.rejects(requestJson("/api/v1/recomendar"), /inválida/);
});

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ""; this.style = {}; this.attributes = {}; this.classList = { toggle: (name, enabled) => { this[name] = enabled; } }; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) {
    this.listeners ??= {};
    this.listeners[name] = callback;
    this[name] = callback;
  }
  set innerHTML(_) { throw new Error("Conteúdo externo não deve ser renderizado como HTML"); }
}

test("resultado renderiza orientações como texto e limpa dados da consulta anterior", (context) => {
  const nodes = new Map();
  globalThis.document = {
    createElement: (tag) => new Element(tag),
    getElementById: (id) => {
      if (!nodes.has(id)) nodes.set(id, new Element("div"));
      return nodes.get(id);
    },
  };
  context.after(() => { delete globalThis.document; });
  const data = {
    status: "dados_insuficientes", municipio: { nome: "Ouro Preto", uf: "MG" }, dados_informados: input,
    janelas: [], orientacoes: [], pendencias: ["Confira o solo"], avisos: [], fontes: ["Embrapa"], opcoes_cultura: [],
    referencias: [{ pergunta: "<img src=x onerror=alert(1)>", resposta: "Texto técnico", livro: "Milho", url_publicacao: "javascript:alert(1)" }],
  };
  renderResults(data, () => {});
  assert.equal(nodes.get("pendingDetails").open, true);
  assert.equal(nodes.get("warningDetails").open, false);
  assert.equal(nodes.get("pendingCount").textContent, "1");
  renderResults({ ...data,
    pendencias: ["Zoneamento Embrapa indisponível: erro externo."],
    avisos: ["Análise climática indisponível.", "Orientação por IA indisponível."],
  }, () => {});
  assert.equal(nodes.get("warningCount").textContent, "1");
  assert.match(nodes.get("pendingItems").children[0].textContent, /Consulte novamente o ZARC/);
  assert.doesNotMatch(nodes.get("warningItems").children[0].textContent, /indisponível/i);
  renderResults({ ...data, referencias: [] }, () => {});
  assert.throws(() => renderResults({}, () => {}), /formato/);
  renderResults({ ...data, pendencias: [], orientacoes: [{ tema: "conservacao_agua", texto: "Manter cobertura.",
    fonte: "Embrapa", evidencias: ["Dado preservado"], url_fonte: "https://www.embrapa.br/" }] }, () => {});
  const guidance = nodes.get("recommendations").children[0];
  assert.equal(guidance.tag, "article");
  assert.equal(guidance.children[0].textContent, "Conservar água");
  assert.equal(guidance.children[1].textContent, "Manter cobertura.");
  assert.equal(guidance.children[2].tag, "details");
  assert.ok(guidance.children[2].children.some((node) => node.textContent === "Dado preservado"));
  assert.equal(nodes.get("pendingDetails").open, false);
  assert.equal(nodes.get("pendingCount").textContent, "0");
});

test("ambiguidade oferece escolha junto ao ZARC e limpa opções após resolver", (context) => {
  const nodes = new Map();
  globalThis.document = {
    createElement: (tag) => new Element(tag),
    getElementById: (id) => {
      if (!nodes.has(id)) nodes.set(id, new Element("div"));
      return nodes.get(id);
    },
  };
  context.after(() => { delete globalThis.document; });
  const option = { id: 57, nome: "MILHO 2ª SAFRA SEQUEIRO", cultivo: "SEQUEIRO" };
  const data = {
    status: "dados_insuficientes", status_zarc: "cultura_ambigua",
    municipio: { nome: "Ouro Preto", uf: "MG" }, dados_informados: input,
    janelas: [], orientacoes: [], pendencias: [], avisos: [], fontes: [], referencias: [],
    opcoes_cultura: [option],
  };
  let chosen;
  renderResults(data, (value) => { chosen = value; });
  assert.equal(nodes.get("diagTitle").textContent, "Escolha a opção de cultura");
  assert.equal(nodes.get("confirmedWindowsSection").hidden, true);
  assert.equal(nodes.get("cultureSelection").hidden, false);
  assert.match(nodes.get("plantingWindows").children[0].textContent, /Aguardando sua escolha/);
  nodes.get("cultureOptions").children[0].click();
  assert.equal(chosen, option);
  renderResults({ ...data, status_zarc: "sem_dados", opcoes_cultura: [] }, () => {});
  assert.equal(nodes.get("cultureSelection").hidden, true);
  assert.equal(nodes.get("cultureOptions").children.length, 0);
});

test("interface não contém simulador nem uma rota paralela de recomendação", () => {
  const app = readFileSync(new URL("../app.js", import.meta.url), "utf8");
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  assert.doesNotMatch(app, /buildMockBackendResponse|localhost:8000\/api\/recomendacao|nominatim\.openstreetmap\.org/);
  assert.match(app, /https:\/\/tile\.openstreetmap\.org\/\{z\}\/\{x\}\/\{y\}\.png/);
  assert.doesNotMatch(app, /basemaps\.cartocdn\.com/);
  assert.match(html, /value="textura_media"/);
  assert.doesNotMatch(html, /value="misto"|Precisa calcário|Impacto Esperado/);
});

test("resumo NASA exibe unidades corretas e limpa métricas quando indisponível", (context) => {
  const nodes = new Map();
  globalThis.document = {
    createElement: (tag) => new Element(tag),
    getElementById: (id) => {
      if (!nodes.has(id)) nodes.set(id, new Element("div"));
      return nodes.get(id);
    },
  };
  context.after(() => { delete globalThis.document; });
  renderClimate({
    data_inicio: "2023-01-01", data_fim: "2025-12-31", precipitacao_media_anual_mm: 1000,
    temperatura_media_c: 20, umidade_relativa_ar_pct: 70, radiacao_media_mj_m2_dia: 14.4,
    maior_sequencia_dias_sem_chuva: 20, meses: [{ mes: 1, precipitacao_media_mm: 100, temperatura_media_c: 20, anos_chuva_completos: 3 }],
  }, true);
  assert.match(nodes.get("nasaStatus").textContent, /2023-01-01/);
  assert.equal(nodes.get("climateMetrics").children[2].children[0].textContent, "Umidade relativa do ar a 2 m");
  assert.match(nodes.get("climateMetrics").children[3].children[1].textContent, /MJ\/m²\/dia/);
  assert.equal(nodes.get("climateChart").children[0].tag, "figure");
  const bar = nodes.get("climateChart").children[0].children[2].children[0].children[0].children[1].children[0];
  assert.equal(bar.style.height, "100%");
  assert.match(nodes.get("climateChart").children[0].children[2].children[0].children[0].attributes["aria-label"], /Jan: chuva 100 mm; temperatura 20 °C/);
  renderClimate(null, false);
  assert.equal(nodes.get("climateMetrics").children.length, 0);
  assert.equal(nodes.get("climateChart").children.length, 0);
  assert.equal(nodes.get("climateMonthly").children.length, 0);
  assert.match(nodes.get("nasaStatus").textContent, /Consulte novamente/);
});

test("janelas condicionais ficam separadas das confirmadas e são limpas ao repetir consulta", (context) => {
  const nodes = new Map();
  globalThis.document = {
    createElement: (tag) => new Element(tag),
    getElementById: (id) => {
      if (!nodes.has(id)) nodes.set(id, new Element("div"));
      return nodes.get(id);
    },
  };
  context.after(() => { delete globalThis.document; });
  const window = { cultura: "MILHO", solo: "AD3", ciclo: "I", dia_inicio: 1, mes_inicio: 11,
    dia_fim: 30, mes_fim: 11, safra_inicio: 2026, safra_fim: 2027, risco: 20,
    portaria: "Portaria", condicao: "Confirmar AD3 antes do plantio." };
  const review = () => {};
  renderZarc({ status_zarc: "classe_solo_pendente", mensagem_zarc: "Confirme o solo",
    janelas_confirmadas: [], janelas_condicionais: [window] }, review);
  assert.equal(nodes.get("plantingWindows").children[0].tag, "p");
  assert.equal(nodes.get("conditionalWindows").children.length, 1);
  assert.equal(nodes.get("conditionalWindowsSection").hidden, false);
  assert.equal(nodes.get("confirmedWindowsSection").hidden, true);
  assert.equal(nodes.get("btnReviewSoil").onclick, review);
  assert.match(nodes.get("zarcStatus").textContent, /confirme/);
  renderZarc({ status_zarc: "disponivel", janelas_confirmadas: [window,
    { ...window, dia_inicio: 1, mes_inicio: 12, dia_fim: 20, mes_fim: 12 }], janelas_condicionais: [] });
  assert.equal(nodes.get("plantingWindows").children[0].tag, "article");
  assert.equal(nodes.get("plantingWindows").children.length, 1);
  assert.equal(nodes.get("zarcCount").textContent, "2 períodos compatíveis");
  assert.match(nodes.get("plantingWindows").children[0].children[2].textContent, /01\/12 – 20\/12/);
  assert.equal(nodes.get("confirmedWindowsSection").hidden, false);
  assert.equal(nodes.get("conditionalWindows").children.length, 0);
  assert.equal(nodes.get("conditionalWindowsSection").hidden, true);
  renderZarc({ status_zarc: "falha_autenticacao", janelas: [], janelas_condicionais: [] });
  assert.match(nodes.get("zarcStatus").textContent, /acesso/);
  assert.equal(nodes.get("confirmedWindowsSection").hidden, true);
});

test("terceira tela mantém IDs únicos e controles essenciais fora de blocos recolhidos", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(ids.length, new Set(ids).size, "IDs duplicados podem deixar dados invisíveis ou desatualizados");
  const third = html.slice(html.indexOf('<section id="screen-3"'));
  assert.match(third, /Quando plantar\?/);
  assert.match(third, /Orientação para sua área/);
  assert.match(third, /id="btnViewData"/);
  assert.match(third, /<div id="confirmedWindowsSection"/);
  assert.match(third, /<section[^>]*id="nasaPanel"/);
  assert.ok(third.indexOf('id="nasaPanel"') > third.indexOf('id="confirmedWindowsSection"'));
  assert.ok(third.indexOf('id="nasaPanel"') < third.indexOf('id="technicalDetails"'));
  assert.doesNotMatch(third, /Publicações da Embrapa|technicalReferences/);
  assert.doesNotMatch(third.match(/<div id="cultureSelection"[\s\S]*?<\/div>/)[0], /<details/);
});

test("resumo diferencia compatibilidade de confirmação agronômica e mantém falhas explícitas", (context) => {
  const nodes = new Map();
  globalThis.document = {
    createElement: (tag) => new Element(tag),
    getElementById: (id) => {
      if (!nodes.has(id)) nodes.set(id, new Element("div"));
      return nodes.get(id);
    },
  };
  context.after(() => { delete globalThis.document; });
  const data = { status: "orientacao_condicional", dados_informados: input,
    municipio: { nome: "Ouro Preto", uf: "MG" }, janelas: [], orientacoes: [],
    pendencias: [], avisos: [], fontes: [], referencias: [], opcoes_cultura: [] };
  renderResults({ ...data, status_zarc: "classe_solo_pendente" }, () => {});
  assert.match(nodes.get("diagTitle").textContent, /Falta confirmar/);
  renderResults({ ...data, status_zarc: "disponivel", janelas: [{ ciclo: "I", solo: "AD3", risco: 20 }] }, () => {});
  assert.match(nodes.get("diagTitle").textContent, /compatíveis/);
  renderResults({ ...data, status_zarc: "falha_autenticacao" }, () => {});
  assert.match(nodes.get("diagTitle").textContent, /Confira os dados/);
  assert.match(nodes.get("zarcStatus").textContent, /acesso/);
});

test("payload preserva descrição do solo separada da classe ZARC", () => {
  const payload = buildPayload(form({ ...input, tipo_solo: "AD1", tipo_solo_informado: "raso" }));
  assert.equal(payload.tipo_solo, "AD1");
  assert.equal(payload.tipo_solo_informado, "raso");
});


test("opções de cultura exibem modalidade e preservam o ID no callback", (context) => {
  const nodes = new Map();
  globalThis.document = {
    createElement: (tag) => new Element(tag),
    getElementById: (id) => {
      if (!nodes.has(id)) nodes.set(id, new Element("div"));
      return nodes.get(id);
    },
  };
  context.after(() => { delete globalThis.document; });
  const choices = [
    { id: 1, nome: "MILHO SEQUEIRO" },
    { id: 2, nome: "MILHO IRRIGADO", cultivo: "IRRIGADO" },
  ];
  let selected;
  renderResults({
    status: "dados_insuficientes", municipio: { nome: "Ouro Preto", uf: "MG" },
    dados_informados: input, janelas: [], orientacoes: [], pendencias: [],
    avisos: [], referencias: [], fontes: [], opcoes_cultura: choices,
  }, (option) => { selected = option; });
  const buttons = nodes.get("cultureOptions").children;
  assert.equal(buttons[0].textContent, "Consultar MILHO SEQUEIRO");
  assert.equal(buttons[1].textContent, "Consultar MILHO IRRIGADO");
  buttons[0].listeners.click();
  assert.equal(selected, choices[0]);
  buttons[1].listeners.click();
  assert.equal(selected, choices[1]);
});

test("Gemini aparece como interpretação, preserva evidências e limpa dados antigos em falhas", (context) => {
  const nodes = new Map();
  globalThis.document = {
    createElement: (tag) => new Element(tag),
    getElementById: (id) => {
      if (!nodes.has(id)) nodes.set(id, new Element("div"));
      return nodes.get(id);
    },
  };
  context.after(() => { delete globalThis.document; });
  renderGemini({ status_ia: "disponivel", explicacao_ia: {
    resumo: "<img src=x onerror=alert(1)>", actions: [{ description: "Confirme a classe AD.",
      evidencias: ["usuario:ph", "usuario:restricoes", "zarc:condicional:0"] }],
    analise_ph: { valor_informado: 5.5, interpretacao: "pH ácido", orientacao: "Avalie correção." },
    analise_restricoes: { texto_informado: "Pouca água", impacto: "Limita irrigação", orientacao: "Planeje a água." },
  } });
  assert.equal(nodes.get("aiGuidance").hidden, false);
  assert.equal(nodes.get("fallbackGuidance").hidden, true);
  assert.equal(nodes.get("diagText").hidden, true);
  assert.equal(nodes.get("diagTitle").textContent, "Seu próximo passo");
  assert.equal(nodes.get("aiAttribution").hidden, false);
  assert.equal(nodes.get("aiSummary").textContent, "<img src=x onerror=alert(1)>");
  const action = nodes.get("aiActions").children[0];
  assert.equal(action.children[0].textContent, "Confirme a classe AD.");
  assert.match(action.children[1].children[1].textContent, /condicional/);
  assert.equal(nodes.get("aiPersonalizacaoConteudo").children.length, 2);
  assert.match(nodes.get("aiPersonalizacaoConteudo").children[0].children[0].textContent, /5.5/);
  assert.equal(nodes.get("aiPersonalizacaoConteudo").children[1].children[1].textContent, "Pouca água");
  renderGemini({ status_ia: "indisponivel", explicacao_ia: null });
  assert.equal(nodes.get("aiGuidance").hidden, true);
  assert.equal(nodes.get("aiSummary").textContent, "");
  assert.equal(nodes.get("aiActions").children.length, 0);
  assert.equal(nodes.get("aiPersonalizacaoConteudo").children.length, 0);
  assert.equal(nodes.get("fallbackGuidance").hidden, false);
  assert.equal(nodes.get("diagText").hidden, false);
  assert.equal(nodes.get("aiAttribution").hidden, true);
  renderGemini({ status_ia: "nao_configurado" });
  renderGemini({ status_ia: "disponivel", explicacao_ia: {} });
  assert.equal(nodes.get("aiGuidance").hidden, true);
  assert.equal(nodes.get("fallbackGuidance").hidden, false);
});
