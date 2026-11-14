import { test, expect } from "@playwright/test";

const endpoint = "**/api/v1/recomendar";
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
  await expect(page.locator("#screen-1")).toHaveAttribute("aria-hidden", "false");
});

async function next(page) {
  await page.locator("#btnNextToStep2").click();
  await expect(page.locator("#screen-2")).toHaveAttribute("aria-hidden", "false");
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
  await page.locator("#btnSubmitToBackend").click();
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
    expect(data).toMatchObject({ cultura_desejada: "soja", ph: 5.5, restricoes: "Pouca água" });
    expect(Object.keys(data)).toHaveLength(10);
    response = result(data);
    await waiting;
    await route.fulfill({ json: response });
  });
  await next(page);
  await page.locator("#cropSelect").selectOption("soja");
  await page.locator("#userRestrictions").fill(" Pouca água ");
  await page.locator("#btnSubmitToBackend").click();
  await expect(page.locator("#loadingIndicator")).toBeVisible();
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
    await page.locator("#btnSubmitToBackend").click();
    await expect(page.locator("#backendResultsWrapper")).toBeVisible();
    await page.locator("#btnEditInputs").click();
    await page.locator("#btnSubmitToBackend").click();
    await expect(page.locator("#requestError")).toBeVisible();
    await expect(page.locator("#requestErrorText")).toContainText(
      failure === "http" ? "Fonte indisponível" : failure === "network" ? "conectar" : "formato",
    );
    await expect(page.locator("#backendResultsWrapper")).toBeHidden();
    await expect(page.locator("#btnExportJson")).toBeDisabled();
    await expect(page.locator("#loadingIndicator")).toBeHidden();
    await page.locator("#btnRetry").click();
    await expect(page.locator("#backendResultsWrapper")).toBeVisible();
    await expect(page.locator("#requestError")).toBeHidden();
    expect(calls).toBe(3);
  });
}

test("ambiguous culture choices return to the form and are used on resubmission", async ({ page }) => {
  await page.route(endpoint, (route) => route.fulfill({ json: result(route.request().postDataJSON(), {
    opcoes_cultura: [{ id: 1, nome: "MILHO SEQUEIRO" }, { id: 2, nome: "MILHO IRRIGADO", cultivo: "IRRIGADO" }],
  }) }));
  await next(page);
  await page.locator("#btnSubmitToBackend").click();
  await page.locator("#cultureOptions").getByRole("button", { name: "MILHO SEQUEIRO · modalidade a conferir", exact: true }).click();
  await expect(page.locator("#screen-2")).toHaveAttribute("aria-hidden", "false");
  await expect(page.locator("#cropSelect")).toHaveValue("agritec:1");
  await page.route(endpoint, (route) => {
    expect(route.request().postDataJSON()).toMatchObject({ cultura_desejada: "MILHO SEQUEIRO", id_cultura: 1 });
    return route.fulfill({ json: result(route.request().postDataJSON()) });
  });
  await page.locator("#btnSubmitToBackend").click();
  await expect(page.locator("#backendResultsWrapper")).toBeVisible();
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
      referencias: [{ pergunta: "<img src=x onerror=alert(1)>", resposta: "Texto técnico", livro: "Milho",
        url_publicacao: "javascript:alert(1)" }],
      resumo_climatico: { data_inicio: "2023-01-01", data_fim: "2025-12-31",
        precipitacao_media_anual_mm: 1000, temperatura_media_c: 20,
        umidade_relativa_ar_pct: 70, radiacao_media_mj_m2_dia: 14.4,
        maior_sequencia_dias_sem_chuva: 15, meses: [] },
    } : {};
    return route.fulfill({ json: result(route.request().postDataJSON(), extra) });
  });
  await next(page);
  await page.locator("#btnSubmitToBackend").click();
  await expect(page.locator("#diagTitle")).toContainText("Orientações disponíveis");
  await expect(page.locator("#plantingWindows")).toContainText("1/11 a 30/11");
  await expect(page.locator("#climateMetrics")).toContainText("MJ/m²/dia");
  await expect(page.locator("#technicalReferences")).toContainText("<img src=x onerror=alert(1)>");
  await expect(page.locator("#technicalReferences img, #technicalReferences a")).toHaveCount(0);
  await page.locator("#btnEditInputs").click();
  await page.locator("#btnSubmitToBackend").click();
  await expect(page.locator("#diagTitle")).toContainText("Precisamos conferir");
  await expect(page.locator("#climateMetrics")).toBeEmpty();
  await expect(page.locator("#climateMonthly")).toBeEmpty();
  await expect(page.locator("#technicalReferences")).toContainText("Nenhuma referência");
  await expect(page.locator("#plantingWindows article")).toHaveCount(0);
});
