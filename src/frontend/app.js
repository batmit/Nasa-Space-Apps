import { buildPayload, recomendar, buscarLocalizacao, resolverLocalizacao } from "./api.js?v=20261114-results-4";
import { renderResults } from "./results.js?v=20261114-results-4";

const state = {
  lat: -20.3856, lon: -43.5035, regionName: "Ouro Preto, MG", map: null, marker: null,
  submitting: false, locating: false, locationRevision: 0, lastResponse: null,
};
const byId = (id) => document.getElementById(id);
const show = (id, visible) => byId(id).classList.toggle("hidden", !visible);

function feedback(id, message) {
  byId(id).textContent = message;
  show(id, Boolean(message));
}

function goToScreen(target) {
  for (const step of [1, 2, 3]) {
    const screen = byId(`screen-${step}`);
    screen.classList.remove("active-screen", "screen-above", "screen-below");
    screen.classList.add(step < target ? "screen-above" : step === target ? "active-screen" : "screen-below");
    screen.inert = step !== target;
    screen.setAttribute("aria-hidden", String(step !== target));
    if (step === target) screen.scrollTop = 0;
  }
  document.querySelectorAll(".step-indicator").forEach((button) => {
    const step = Number(button.dataset.stepTarget);
    button.classList.toggle("active-step", step === target);
    button.classList.toggle("completed-step", step < target);
    button.disabled = state.submitting || (step === 3 && !state.lastResponse);
    if (step === target) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
  if (target === 1 && state.map) setTimeout(() => state.map.invalidateSize(), 350);
}

function setLocationBusy(busy) {
  state.locating = busy;
  byId("btnSearchPlace").disabled = busy;
  byId("btnNextToStep2").disabled = busy;
}

function writeCoordinates(lat, lon) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
    throw new Error("Informe latitude entre -90 e 90 e longitude entre -180 e 180.");
  }
  state.lat = Number(lat.toFixed(4));
  state.lon = Number(lon.toFixed(4));
  byId("inputLat").value = state.lat;
  byId("inputLon").value = state.lon;
  state.marker?.setLatLng([state.lat, state.lon]);
  state.map?.panTo([state.lat, state.lon]);
}

function writeRegion(name) {
  state.regionName = name;
  byId("regionLabel").textContent = name;
  byId("inputRegionName").value = name;
}

async function updateCoordinates(lat, lon) {
  try { writeCoordinates(lat, lon); }
  catch (error) { feedback("searchFeedback", error.message); return; }
  const revision = ++state.locationRevision;
  writeRegion(`${state.lat}, ${state.lon}`);
  setLocationBusy(true);
  feedback("searchFeedback", "Identificando o município...");
  try {
    const location = await resolverLocalizacao(state.lat, state.lon);
    if (revision !== state.locationRevision) return;
    writeRegion(location.regiao_nome);
    feedback("searchFeedback", `Local selecionado: ${location.regiao_nome}`);
  } catch (error) {
    if (revision === state.locationRevision) feedback("searchFeedback", error.message);
  } finally {
    if (revision === state.locationRevision) setLocationBusy(false);
  }
}

async function searchPlace() {
  const query = byId("locationSearch").value.trim();
  if (query.length < 2) { feedback("searchFeedback", "Digite o município e a UF."); return; }
  const revision = ++state.locationRevision;
  setLocationBusy(true);
  feedback("searchFeedback", "Buscando localização...");
  try {
    const location = await buscarLocalizacao(query);
    if (revision !== state.locationRevision) return;
    writeCoordinates(location.latitude, location.longitude);
    writeRegion(location.regiao_nome);
    feedback("searchFeedback", `Local encontrado: ${location.regiao_nome}`);
  } catch (error) {
    if (revision === state.locationRevision) feedback("searchFeedback", error.message);
  } finally {
    if (revision === state.locationRevision) setLocationBusy(false);
  }
}

function initMap() {
  if (!globalThis.L) {
    feedback("searchFeedback", "O mapa não carregou. Você pode buscar o município ou informar as coordenadas.");
    show("manualCoordsBox", true);
    return;
  }
  const L = globalThis.L;
  state.map = L.map(byId("mapContainer")).setView([state.lat, state.lon], 10);
  const street = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
    maxZoom: 19,
  }).addTo(state.map);
  const satellite = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Imagery &copy; Esri", maxZoom: 18,
  });
  L.control.layers({ "Mapa OpenStreetMap": street, "Satélite": satellite }).addTo(state.map);
  state.marker = L.marker([state.lat, state.lon], { draggable: true }).addTo(state.map);
  state.marker.on("dragend", (event) => {
    const position = event.target.getLatLng();
    updateCoordinates(position.lat, position.lng);
  });
  state.map.on("click", (event) => updateCoordinates(event.latlng.lat, event.latlng.lng));
}

function updatePhBadge() {
  const value = Number(byId("soilPh").value);
  byId("phBadge").textContent = `${value.toFixed(1)} · ${value < 7 ? "Ácido" : value > 7 ? "Alcalino" : "Neutro"}`;
  document.querySelectorAll(".ph-preset-btn").forEach((button) => {
    button.classList.toggle("active-ph", Number(button.dataset.ph) === value);
  });
}

function chooseCulture(option) {
  const select = byId("cropSelect");
  let entry = [...select.options].find((item) => item.dataset.culturaId === String(option.id));
  if (!entry) {
    entry = document.createElement("option");
    entry.value = `agritec:${option.id}`;
    entry.textContent = `${option.nome} · ${option.cultivo || "modalidade a conferir"} · opção ${option.id}`;
    entry.dataset.culturaId = String(option.id);
    entry.dataset.culturaNome = option.nome;
    select.append(entry);
  }
  select.value = entry.value;
  select.dispatchEvent(new Event("change"));
  submitForm();
}

async function submitForm(event) {
  event?.preventDefault();
  if (state.submitting) return;
  if (state.locating) { feedback("formFeedback", "Aguarde a identificação do município."); return; }
  let payload;
  try {
    const formData = new FormData(byId("agroWizardForm"));
    const selected = byId("cropSelect").selectedOptions[0];
    if (selected?.dataset.culturaId) {
      formData.set("id_cultura", selected.dataset.culturaId);
      formData.set("cultura_desejada", selected.dataset.culturaNome);
    }
    const classe = byId("zarcSoilClass").value;
    if (classe) formData.set("tipo_solo", classe);
    payload = buildPayload(formData);
  }
  catch (error) { goToScreen(2); feedback("formFeedback", error.message); return; }
  feedback("formFeedback", "");
  state.submitting = true;
  state.lastResponse = null;
  byId("btnSubmitToBackend").disabled = true;
  byId("btnExportJson").disabled = true;
  goToScreen(3);
  show("requestError", false);
  show("backendResultsWrapper", false);
  show("loadingIndicator", true);
  byId("screen-3").setAttribute("aria-busy", "true");
  try {
    const data = await recomendar(payload);
    renderResults(data, chooseCulture, () => {
      goToScreen(2);
      byId("zarcSoilDetails").open = true;
      byId("zarcSoilClass").focus();
    });
    state.lastResponse = data;
    byId("btnExportJson").disabled = false;
    show("backendResultsWrapper", true);
  } catch (error) {
    feedback("requestErrorText", error.message);
    show("requestError", true);
  } finally {
    state.submitting = false;
    byId("btnSubmitToBackend").disabled = false;
    byId("screen-3").setAttribute("aria-busy", "false");
    show("loadingIndicator", false);
    goToScreen(3);
  }
}

function exportResult() {
  if (!state.lastResponse) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(state.lastResponse, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "agroorbit-consulta.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function init() {
  globalThis.lucide?.createIcons();
  initMap();
  goToScreen(1);
  updatePhBadge();
  byId("btnNextToStep2").addEventListener("click", () => {
    if (!state.locating) goToScreen(2);
  });
  for (const id of ["btnBackToStep1", "btnBackToStep1Bottom"]) byId(id).addEventListener("click", () => goToScreen(1));
  for (const id of ["btnEditInputs", "btnErrorEdit"]) byId(id).addEventListener("click", () => goToScreen(2));
  document.querySelectorAll(".step-indicator").forEach((button) => button.addEventListener("click", () => {
    if (!button.disabled) goToScreen(Number(button.dataset.stepTarget));
  }));
  byId("btnToggleCoords").addEventListener("click", () => byId("manualCoordsBox").classList.toggle("hidden"));
  byId("btnSearchPlace").addEventListener("click", searchPlace);
  byId("locationSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); if (!state.locating) searchPlace(); }
  });
  byId("btnMyLocation").addEventListener("click", () => {
    if (!navigator.geolocation) { feedback("searchFeedback", "GPS indisponível neste navegador."); return; }
    navigator.geolocation.getCurrentPosition(
      (position) => updateCoordinates(position.coords.latitude, position.coords.longitude),
      () => feedback("searchFeedback", "Não foi possível acessar o GPS. Busque o município ou informe as coordenadas."),
      { timeout: 15000 },
    );
  });
  for (const id of ["inputLat", "inputLon"]) byId(id).addEventListener("change", () => {
    const lat = byId("inputLat").value.trim();
    const lon = byId("inputLon").value.trim();
    if (!lat || !lon) { feedback("searchFeedback", "Informe latitude e longitude."); return; }
    updateCoordinates(Number(lat), Number(lon));
  });
  document.querySelectorAll(".crop-pill").forEach((button) => button.addEventListener("click", () => {
    byId("cropSelect").value = button.dataset.crop;
    byId("cropSelect").dispatchEvent(new Event("change"));
  }));
  byId("cropSelect").addEventListener("change", () => document.querySelectorAll(".crop-pill").forEach((button) => {
    button.classList.toggle("active-pill", button.dataset.crop === byId("cropSelect").value);
  }));
  byId("soilPh").addEventListener("input", updatePhBadge);
  document.querySelectorAll(".ph-preset-btn").forEach((button) => button.addEventListener("click", () => {
    byId("soilPh").value = button.dataset.ph;
    updatePhBadge();
  }));
  document.querySelectorAll(".restriction-chip").forEach((button) => button.addEventListener("click", () => {
    const input = byId("userRestrictions");
    if (!input.value.includes(button.dataset.restriction)) {
      input.value = `${input.value.trim()} ${button.dataset.restriction}`.trim().slice(0, 2000);
    }
    input.focus();
  }));
  byId("agroWizardForm").addEventListener("submit", submitForm);
  byId("btnRetry").addEventListener("click", submitForm);
  byId("btnExportJson").addEventListener("click", exportResult);
}

document.addEventListener("DOMContentLoaded", init);
