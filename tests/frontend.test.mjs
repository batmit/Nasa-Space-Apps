import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ApiError, buildPayload, recomendar, requestJson } from "../src/frontend/api.js";
import { renderResults } from "../src/frontend/results.js";

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

test("chamada usa a rota real, mesma origem e JSON", async (context) => {
  context.mock.method(globalThis, "fetch", async (path, options) => {
    assert.equal(path, "/api/v1/recomendar");
    assert.equal(options.method, "POST");
    assert.equal(JSON.parse(options.body).cultura_desejada, "milho");
    return { ok: true, json: async () => ({ status: "dados_insuficientes" }) };
  });
  assert.equal((await recomendar(buildPayload(form(input)))).status, "dados_insuficientes");
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
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ""; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener() {}
  set innerHTML(_) { throw new Error("Conteúdo externo não deve ser renderizado como HTML"); }
}

test("resultado renderiza fontes reais como texto e limpa dados da consulta anterior", (context) => {
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
  assert.equal(nodes.get("technicalReferences").children[0].children[0].textContent, "<img src=x onerror=alert(1)>");
  assert.equal(nodes.get("technicalReferences").children[0].children.filter((node) => node.tag === "a").length, 0);
  renderResults({ ...data, referencias: [] }, () => {});
  assert.equal(nodes.get("technicalReferences").children[0].tag, "p");
  assert.throws(() => renderResults({}, () => {}), /formato/);
});

test("interface não contém simulador nem uma rota paralela de recomendação", () => {
  const app = readFileSync(new URL("../src/frontend/app.js", import.meta.url), "utf8");
  const html = readFileSync(new URL("../src/frontend/index.html", import.meta.url), "utf8");
  assert.doesNotMatch(app, /buildMockBackendResponse|localhost:8000\/api\/recomendacao|nominatim\.openstreetmap\.org/);
  assert.match(app, /https:\/\/tile\.openstreetmap\.org\/\{z\}\/\{x\}\/\{y\}\.png/);
  assert.doesNotMatch(app, /basemaps\.cartocdn\.com/);
  assert.match(html, /value="textura_media"/);
  assert.doesNotMatch(html, /value="misto"|Precisa calcário|Impacto Esperado/);
});
