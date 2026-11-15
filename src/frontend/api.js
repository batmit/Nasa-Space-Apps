// Contrato HTTP da interface. Caminhos relativos mantêm API e página na mesma origem.
export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

export async function requestJson(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 150000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal,
      headers: { Accept: "application/json", ...options.headers } });
    let data;
    try { data = await response.json(); }
    catch { throw new ApiError("O servidor retornou uma resposta inválida. Tente novamente.", response.status); }
    if (!response.ok) {
      const message = typeof data.detail === "string" ? data.detail
        : response.status === 422 ? "Confira os campos informados e tente novamente."
        : "Confira a conexão e tente novamente.";
      throw new ApiError(message, response.status);
    }
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error.name === "AbortError"
      ? "A consulta demorou mais que o esperado. Tente novamente."
      : "Não foi possível conectar ao servidor. Verifique sua conexão e tente novamente.");
  } finally { clearTimeout(timer); }
}

export function buildPayload(formData) {
  const text = (name) => String(formData.get(name) ?? "").trim();
  const number = (name, min, max) => {
    const raw = text(name);
    const value = Number(raw);
    if (!raw || !Number.isFinite(value) || value < min || value > max) {
      throw new Error(`Confira o valor de ${name === "ph" ? "pH" : name}.`);
    }
    return value;
  };
  const payload = {
    regiao_nome: text("regiao_nome"), latitude: number("latitude", -90, 90),
    longitude: number("longitude", -180, 180), cultura_desejada: text("cultura_desejada"),
    tipo_solo: text("tipo_solo"), ph: number("ph", 0, 14),
    forma_irrigacao: text("forma_irrigacao"), historico_area: text("historico_area"),
    objetivo: text("objetivo"), restricoes: text("restricoes"),
  };
  for (const key of ["regiao_nome", "cultura_desejada", "tipo_solo", "forma_irrigacao", "historico_area", "objetivo"]) {
    if (!payload[key]) throw new Error("Preencha todos os campos antes de consultar.");
  }
  if (payload.restricoes.length > 2000) throw new Error("Descreva as restrições em até 2.000 caracteres.");
  if (text("tipo_solo_informado")) payload.tipo_solo_informado = text("tipo_solo_informado");
  if (text("id_cultura")) {
    const id = number("id_cultura", 1, Number.MAX_SAFE_INTEGER);
    if (!Number.isSafeInteger(id)) throw new Error("Selecione uma opção válida de cultura.");
    payload.id_cultura = id;
  }
  return payload;
}

export function recomendar(payload) {
  return requestJson("/api/v1/recomendar", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}

export function buscarOpcoesCultura(payload) {
  const { latitude, longitude, cultura_desejada, forma_irrigacao } = payload;
  return requestJson("/api/v1/culturas/opcoes", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ latitude, longitude, cultura_desejada, forma_irrigacao }),
  });
}

export function buscarLocalizacao(consulta) {
  return requestJson(`/api/v1/localizacao/buscar?${new URLSearchParams({ consulta })}`);
}

export function resolverLocalizacao(latitude, longitude) {
  return requestJson(`/api/v1/localizacao/reversa?${new URLSearchParams({ latitude, longitude })}`);
}
