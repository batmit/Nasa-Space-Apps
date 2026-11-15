import { test, expect } from "@playwright/test";

const endpoint = "**/api/v1/recomendar";
const catalogEndpoint = "**/api/v1/culturas/opcoes";
const location = { regiao_nome: "Viçosa, MG", latitude: -20.75, longitude: -42.88 };
const result = (dados, extra = {}) => ({
  status: "dados_insuficientes", dados_informados: dados,
  municipio: { codigo_ibge: 3146107, nome: "Ouro Preto", uf: "MG" },
  janelas: [], orientacoes: [], pendencias: ["Confirme a análise do solo."],
  avisos: [], referencias: [], fontes: ["NASA POWER"], opcoes_cultura: [],
  analise_climatica_realizada: false, resumo_climatico: null, ...extra,
});

test.beforeEach(async ({ page }) => {
  // Keep behavior tests offline. Only supply the layout utilities needed by the
  // wizard; these tests do not assert Tailwind styling or third-party map behavior.
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === "http://127.0.0.1:8765") return route.continue();
    if (url.hostname === "cdn.tailwindcss.com") return route.fulfill({
      contentType: "application/javascript",
      body: `const style = document.createElement('style');
        style.textContent = '.hidden{display:none!important} #agroWizardForm{position:relative;height:80vh}';
        document.head.append(style);`,
    });
    return route.abort();
  });
  await page.goto("/");
  await page.route(catalogEndpoint, (route) => {
    const data = route.request().postDataJSON();
    return route.fulfill({ json: {
      municipio: { codigo_ibge: 3146107, nome: "Ouro Preto", uf: "MG" },
      opcoes: [{ id: 1, nome: `${data.cultura_desejada.toUpperCase()} SEQUEIRO`, cultivo: "SEQUEIRO" }],
    } });
  });
  await expect(page.locator("#screen-1")).toHaveAttribute("aria-hidden", "false");
});

async function next(page) {
  await page.locator("#btnNextToStep2").click();
  await expect(page.locator("#screen-2")).toHaveAttribute("aria-hidden", "false");
}

async function consult(page) {
  await page.locator("#btnSubmitToBackend").click();
  await expect(page.locator("#cultureGate")).toBeVisible();
  await expect(page.locator("#backendResultsWrapper")).toBeHidden();
  await page.locator("#cultureOptions button").first().click();
}

test("navigation and controls preserve the farmer's selections", async ({ page }) => {
  await expect(page.locator('[data-step-target="3"]')).toBeDisabled();
  await expect(page.locator("#manualCoordsBox")).toBeVisible(); // CDN map unavailable
  await next(page);
  await page.locator('[data-crop="soja"]').click();
  await expect(page.locator("#cropSelect")).toHaveValue("soja");
  await page.locator('[data-ph="6.2"]').click();
  await expect(page.locator("#phBadge")).toHaveText("6.2 · Ácido");
  const chip = page.locator(".restriction-chip").first();
  await chip.click();
  const restrictions = await page.locator("#userRestrictions").inputValue();
  expect(restrictions.length).toBeGreaterThan(0);
  await chip.click();
  await expect(page.locator("#userRestrictions")).toHaveValue(restrictions);
  await page.locator("#btnBackToStep1").click();
  await next(page);
  await expect(page.locator("#cropSelect")).toHaveValue("soja");
});

test("sensor demonstration hides manual choices and marks theoretical inputs", async ({ page }) => {
  let catalogPayload;
  let recommendationPayload;
  await page.route(catalogEndpoint, (route) => {
    catalogPayload = route.request().postDataJSON();
    return route.fulfill({ json: { municipio: { nome: "Ouro Preto", uf: "MG" },
      opcoes: [{ id: 12, nome: "MILHO SEQUEIRO", cultivo: "SEQUEIRO" }] } });
  });
  await page.route(endpoint, (route) => {
    recommendationPayload = route.request().postDataJSON();
    return route.fulfill({ json: result(recommendationPayload) });
  });
  await next(page);
  await page.locator('[data-crop="soja"]').click();
  await page.locator("#btnSensorDemo").click();
  await expect(page.locator("#sensorDemoPanel")).toBeVisible();
  await expect(page.locator("#sensorDemoPanel")).toContainText("Cenário teórico");
  await expect(page.locator("#manualPersonalization")).toBeHidden();
  await consult(page);
  expect(catalogPayload).toMatchObject({ cultura_desejada: "milho", forma_irrigacao: "sem_irrigacao" });
  expect(recommendationPayload).toMatchObject({ modo_demonstracao: true, cultura_desejada: "MILHO SEQUEIRO",
    tipo_solo: "textura_media", ph: 6.2, historico_area: "monocultura_pousio",
    objetivo: "recuperar_solo", restricoes: "" });
  await expect(page.locator("#demoResultNotice")).toBeVisible();
  await page.locator("#btnEditInputs").click();
  await page.locator("#btnManualSoil").click();
  await expect(page.locator("#sensorDemoPanel")).toBeHidden();
  await expect(page.locator("#manualPersonalization")).toBeVisible();
  await expect(page.locator("#cropSelect")).toHaveValue("soja");
});

test("location search waits for resolution and submits the selected coordinates", async ({ page }) => {
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/v1/localizacao/buscar?*", async (route) => {
    expect(new URL(route.request().url()).searchParams.get("consulta")).toBe("Viçosa MG");
    await waiting;
    await route.fulfill({ json: location });
  });
  await page.locator("#locationSearch").fill("Viçosa MG");
  await page.locator("#btnSearchPlace").click();
  await expect(page.locator("#btnNextToStep2")).toBeDisabled();
  release();
  await expect(page.locator("#regionLabel")).toHaveText(location.regiao_nome);
  await expect(page.locator("#inputLat")).toHaveValue(String(location.latitude));
  await page.route(endpoint, (route) => {
    const data = route.request().postDataJSON();
    expect(data).toMatchObject(location);
    return route.fulfill({ json: result(data) });
  });
  await next(page);
  await consult(page);
  await expect(page.locator("#backendResultsWrapper")).toBeVisible();
});

test("invalid input stays on the form without sending a request", async ({ page }) => {
  let requests = 0;
  await page.route(endpoint, (route) => { requests++; return route.abort(); });
  await page.locator("#inputLat").fill("");
  await next(page);
  await page.locator("#btnSubmitToBackend").click();
  await expect(page.locator("#formFeedback")).toContainText("latitude");
  await expect(page.locator("#screen-2")).toHaveAttribute("aria-hidden", "false");
  expect(requests).toBe(0);
});

test("submission shows loading, prevents duplicate requests, and exports the response", async ({ page }) => {
  let release;
  let requests = 0;
  let response;
  const waiting = new Promise((resolve) => { release = resolve; });
  await page.route(endpoint, async (route) => {
    requests++;
    expect(route.request().method()).toBe("POST");
    const data = route.request().postDataJSON();
    expect(data).toMatchObject({ cultura_desejada: "SOJA SEQUEIRO", id_cultura: 1, ph: 5.5, restricoes: "Pouca água" });
    expect(Object.keys(data)).toHaveLength(11);
    response = result(data);
    await waiting;
    await route.fulfill({ json: response });
  });
  await next(page);
  await page.locator("#cropSelect").selectOption("soja");
  await page.locator("#userRestrictions").fill(" Pouca água ");
  await page.locator("#btnSubmitToBackend").click();
  await expect(page.locator("#cultureGate")).toBeVisible();
  expect(requests).toBe(0);
  await page.locator("#cultureOptions button").first().click();
  await expect(page.locator("#loadingIndicator")).toBeVisible();
  expect(await page.locator("#loadingIndicator").evaluate((node) => ({
    textAlign: getComputedStyle(node).textAlign,
    alignItems: getComputedStyle(node).alignItems,
    justifyContent: getComputedStyle(node).justifyContent,
  }))).toEqual({ textAlign: "center", alignItems: "center", justifyContent: "center" });
  await expect(page.locator("#screen-3")).toHaveAttribute("aria-busy", "true");
  await expect(page.locator("#btnSubmitToBackend")).toBeDisabled();
  // A second submit event must also be ignored, even if triggered programmatically.
  await page.locator("#agroWizardForm").dispatchEvent("submit");
  release();
  await expect(page.locator("#backendResultsWrapper")).toBeVisible();
  expect(requests).toBe(1);
  await expect(page.locator("#loadingIndicator")).toBeHidden();
  await expect(page.locator("#screen-3")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator("#pendingItems")).toContainText("Confirme a análise do solo.");
  await expect(page.locator("#climateMetrics")).toBeEmpty();
  await page.locator("#btnViewData").click();
  await expect(page.locator("#technicalDetails")).toHaveAttribute("open", "");
  await page.getByText("Fontes e arquivo da consulta", { exact: true }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#btnExportJson").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("agroorbit-consulta.json");
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  expect(JSON.parse(Buffer.concat(chunks).toString())).toEqual(response);
});

for (const failure of ["http", "network", "malformed"]) {
  test(`${failure} failure can be retried without retaining old results`, async ({ page }) => {
    let calls = 0;
    await page.route(endpoint, (route) => {
      calls++;
      if (calls === 2) {
        if (failure === "network") return route.abort("failed");
        if (failure === "malformed") return route.fulfill({ json: {} });
        return route.fulfill({ status: 503, json: { detail: "Fonte indisponível." } });
      }
      return route.fulfill({ json: result(route.request().postDataJSON()) });
    });
    await next(page);
    await consult(page);
    await expect(page.locator("#backendResultsWrapper")).toBeVisible();
    await page.locator("#btnEditInputs").click();
    await consult(page);
    await expect(page.locator("#requestError")).toBeVisible();
    await expect(page.locator("#requestErrorText")).toContainText("Confira sua conexão e tente novamente.");
    await expect(page.locator("#backendResultsWrapper")).toBeHidden();
    await expect(page.locator("#btnExportJson")).toBeDisabled();
    await expect(page.locator("#loadingIndicator")).toBeHidden();
    await page.locator("#btnRetry").click();
    await expect(page.locator("#backendResultsWrapper")).toBeVisible();
    await expect(page.locator("#requestError")).toBeHidden();
    expect(calls).toBe(3);
  });
}

test("culture is chosen before any recommendation request", async ({ page }) => {
  let calls = 0;
  await page.route(catalogEndpoint, (route) => route.fulfill({ json: {
    municipio: { codigo_ibge: 3146107, nome: "Ouro Preto", uf: "MG" },
    opcoes: [{ id: 1, nome: "MILHO 1ª SAFRA SEQUEIRO", cultivo: "SEQUEIRO" },
      { id: 2, nome: "MILHO 2ª SAFRA SEQUEIRO", cultivo: "SEQUEIRO" }],
  } }));
  await page.route(endpoint, (route) => {
    calls++;
    const data = route.request().postDataJSON();
    expect(data).toMatchObject({ cultura_desejada: "MILHO 1ª SAFRA SEQUEIRO", id_cultura: 1 });
    return route.fulfill({ json: result(data) });
  });
  await next(page);
  await page.locator("#btnSubmitToBackend").click();
  await expect(page.locator("#cultureGate")).toBeVisible();
  await expect(page.locator("#backendResultsWrapper")).toBeHidden();
  expect(calls).toBe(0);
  await page.locator("#cultureOptions").getByRole("button", { name: "Consultar MILHO 1ª SAFRA SEQUEIRO", exact: true }).click();
  await expect(page.locator("#screen-3")).toHaveAttribute("aria-hidden", "false");
  await expect(page.locator("#cropSelect")).toHaveValue("agritec:1");
  await expect(page.locator("#backendResultsWrapper")).toBeVisible();
  await expect(page.locator("#cultureGate")).toBeHidden();
  expect(calls).toBe(1);
});

test("sem opção ZARC, a escolha pede revisão sem abrir resultados", async ({ page }) => {
  let calls = 0;
  await page.route(catalogEndpoint, (route) => route.fulfill({ json: {
    municipio: { codigo_ibge: 3146107, nome: "Ouro Preto", uf: "MG" }, opcoes: [],
  } }));
  await page.route(endpoint, (route) => { calls++; return route.abort(); });
  await next(page);
  await page.locator("#btnSubmitToBackend").click();
  await expect(page.locator("#cultureGate")).toBeVisible();
  await expect(page.locator("#cultureGateFeedback")).toContainText("Revise a cultura");
  await expect(page.locator("#backendResultsWrapper")).toBeHidden();
  expect(calls).toBe(0);
  await page.locator("#btnCultureEdit").click();
  await expect(page.locator("#screen-2")).toHaveAttribute("aria-hidden", "false");
});

test("results display planting windows and climate, escape external text, and clear stale metrics", async ({ page }) => {
  let calls = 0;
  await page.route(endpoint, (route) => {
    calls++;
    const extra = calls === 1 ? {
      status: "orientacao_condicional", analise_climatica_realizada: true,
      janelas: [{ cultura: "MILHO", solo: "ARGILOSO", ciclo: "GRUPO I",
        dia_inicio: 1, mes_inicio: 11, dia_fim: 30, mes_fim: 11,
        safra_inicio: 2026, safra_fim: 2027, risco: 20, portaria: "Portaria de teste" }],
      resumo_climatico: { data_inicio: "2023-01-01", data_fim: "2025-12-31",
        precipitacao_media_anual_mm: 1000, temperatura_media_c: 20,
        umidade_relativa_ar_pct: 70, radiacao_media_mj_m2_dia: 14.4,
        maior_sequencia_dias_sem_chuva: 15, meses: [
          { mes: 1, precipitacao_media_mm: 120, temperatura_media_c: 23, anos_chuva_completos: 3 },
          { mes: 2, precipitacao_media_mm: 60, temperatura_media_c: 24, anos_chuva_completos: 3 },
        ], projecao_chuva: { total_estimado_mm: 300, aviso: "Estimativa sazonal exploratória.", meses: [
          { ano: 2026, mes: 12, precipitacao_estimada_mm: 90, meses_historicos_utilizados: 1 },
          { ano: 2027, mes: 1, precipitacao_estimada_mm: 210, meses_historicos_utilizados: 1 },
        ] } },
    } : {};
    return route.fulfill({ json: result(route.request().postDataJSON(), extra) });
  });
  await next(page);
  await consult(page);
  await expect(page.locator("#diagTitle")).toContainText("Há períodos compatíveis");
  await expect(page.locator("#plantingWindows")).toContainText("01/11 – 30/11");
  await expect(page.locator("#climateMetrics")).toContainText("MJ/m²/dia");
  await expect(page.locator("#nasaPanel")).toBeVisible();
  await expect(page.locator("#forecastPanel")).toBeVisible();
  await expect(page.locator("#forecastTotal")).toContainText("300 mm");
  await expect(page.locator("#forecastMonths")).toContainText("Dez/2026");
  await expect(page.locator("#climateChart .climate-bar")).toHaveCount(2);
  await expect(page.locator("#climateChart")).toContainText("120 mm");
  await expect(page.locator("#climateChart")).toContainText("23 °C");
  await page.getByText("Ver tabela mês a mês").click();
  await expect(page.locator("#climateMonthly")).toContainText("Chuva média (mm/mês)");
  await expect(page.locator("#climateMonthly tbody tr:first-child")).toContainText("120");
  await expect(page.getByText("Publicações da Embrapa")).toHaveCount(0);
  await page.locator("#btnEditInputs").click();
  await consult(page);
  await expect(page.locator("#diagTitle")).toContainText("Confira os dados de plantio");
  await expect(page.locator("#climateMetrics")).toBeEmpty();
  await expect(page.locator("#climateChart")).toBeEmpty();
  await expect(page.locator("#climateMonthly")).toBeEmpty();
  await expect(page.locator("#forecastPanel")).toBeHidden();
  await expect(page.locator("#plantingWindows article")).toHaveCount(0);
});

test("Gemini interpretation is optional and a failure preserves source results", async ({ page }) => {
  let calls = 0;
  await page.route(endpoint, (route) => {
    calls++;
    return route.fulfill({ json: result(route.request().postDataJSON(), calls === 1 ? {
      status_ia: "disponivel", explicacao_ia: { resumo: "Confira o solo antes de plantar.",
        actions: [{ description: "Confirme a classe AD.", evidencias: ["usuario"] }],
        sugestao_rotacao: { orientacao: "Planeje cobertura antes da próxima cultura.",
          probabilidade_estabelecimento_pct: 68, justificativa: "Depende do manejo e do solo.", evidencias: ["usuario", "previsao:chuva"] } },
    } : { status_ia: "indisponivel", explicacao_ia: null }) });
  });
  await next(page);
  await consult(page);
  await expect(page.locator("#aiGuidance")).toBeVisible();
  await expect(page.locator("#aiSummary")).toHaveText("Confira o solo antes de plantar.");
  await expect(page.locator("#fallbackGuidance")).toBeHidden();
  await expect(page.locator("#aiActions")).toContainText("Confirme a classe AD.");
  await expect(page.locator("#rotationSuggestion")).toHaveText("Planeje cobertura antes da próxima cultura.");
  await expect(page.locator("#rotationEstimate")).toBeVisible();
  await expect(page.locator("#rotationProbabilityValue")).toHaveText("68%");
  await expect(page.locator("#rotationEstimateNote")).toHaveText("Estimativa exploratória pelo Gemini");
  await page.setViewportSize({ width: 375, height: 812 });
  const estimateLayout = await page.locator("#rotationEstimate").evaluate((node) => ({
    right: node.getBoundingClientRect().right,
    fontSize: parseFloat(getComputedStyle(node.querySelector("#rotationProbabilityValue")).fontSize),
  }));
  expect(estimateLayout.right).toBeLessThanOrEqual(375);
  expect(estimateLayout.fontSize).toBeGreaterThanOrEqual(44);
  await page.locator("#btnEditInputs").click();
  await consult(page);
  await expect(page.locator("#aiGuidance")).toBeHidden();
  await expect(page.locator("#aiSummary")).toBeEmpty();
  await expect(page.locator("#rotationSuggestion")).toContainText("não foi gerada nesta consulta");
  await expect(page.locator("#rotationEstimate")).toBeHidden();
  await expect(page.locator("#fallbackGuidance")).toBeVisible();
  await expect(page.locator("#pendingItems")).toContainText("Confirme a análise do solo.");
});
