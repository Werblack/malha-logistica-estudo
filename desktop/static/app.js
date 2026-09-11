/* Frontend do simulador. Nenhuma regra de negocio mora aqui: tudo (raio, tecnicos, CMU) e calculado
 * em Python (malha.assign/malha.costs) e chega pronto pela ponte `window.pywebview.api`. Este arquivo
 * so desenha: MapLibre GL (WebGL, GPU) sobre um basemap cartografico claro (OpenStreetMap), com
 * `feature-state` para repintura barata a cada slider (sem reconstruir a fonte inteira), e o poligono
 * do raio (esse sim e reconstruido a cada chamada, porque a geometria muda).
 */
"use strict";
window.onerror = (msg, src, line, col) => { window.__erroBoot = `${msg} @ ${src}:${line}:${col}`; };

const COR_OGEA_HEX = "#2E7D32";
const COR_POLO_HEX = "#FBC02D";
const COR_SEM_VOLUME = "#c6c6c6";
const COR_POLO = "#1f4e8c";
const COR_OGEA = "#b3261e";
const ROTULO_STATUS = { ogea: "Território Ógea", misto: "Território misto", polo: "Território PagResolve", sem_volume: "Sem volume em jul/26" };

let DATA = null;               // payload estático de api.init()
let map = null;
let locaisPorId = new Map();    // local_id -> {estático de DATA.locais, ...dinâmico do último `simular`}
let polosPorId = new Map();     // codigo_polo -> idem + {elSlider, elValor}
let raioPorPolo = {};           // valor atual do slider de cada polo (sempre completo)
let vmaxBairro = 1;
let popup = null;               // popup de hover (polos, informativo, fecha ao tirar o mouse)
let popupSelecao = null;        // popup de clique (município/bairro, com o dropdown de exceção manual)
let popupSelecaoLocalId = null; // local_id mostrado no popupSelecao (p/ atualizar os números após cada slider)
let focoPoloAtual = null;       // codigo_polo selecionado no card flutuante do modo foco (null = raio global)
let overrideLocal = {};         // exceção manual {local_id: codigo_polo | "OGEA"} (ausência = automático)
const OGEA_FORCADA = "OGEA";
let tooltipFlutuanteAtivo = true;   // liga/desliga o tooltip que segue o cursor sobre município/bairro

// ---------------------------------------------------------------- boot

function esperarPywebview() {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve();
    window.addEventListener("pywebviewready", () => resolve(), { once: true });
  });
}

async function boot() {
  await esperarPywebview();
  DATA = await window.pywebview.api.init();
  vmaxBairro = Math.max(1, ...DATA.locais.filter((l) => l.capital_subnode).map((l) => l.vol_total));
  for (const l of DATA.locais) locaisPorId.set(l.local_id, { ...l });
  for (const p of DATA.polos) polosPorId.set(p.codigo_polo, { ...p });

  montarBotaoReset();
  montarSliderMestre();
  montarListaPolos();
  montarSlidersProdutividadeCusto();
  montarBusca();
  montarDrawer();
  montarModoFoco();
  montarBotaoTooltipFlutuante();
  montarTeclaEsc();
  await montarMapa();
  await atualizar();
}
window.addEventListener("DOMContentLoaded", boot);

function fmt(v, casas = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}
function pct(v) { return v === null || v === undefined || Number.isNaN(v) ? "-" : (v * 100).toFixed(0) + "%"; }
function moeda(v) { return v === null || v === undefined || Number.isNaN(v) ? "-" : "R$ " + fmt(v, 2); }
function nomeCurtoPolo(nomeCompleto) {
  return nomeCompleto.replace(/^Polo SP\s*/i, "").replace(/\s*-\s*P\d+$/i, "");
}
function formatarNomePolo(nomeCompleto) {
  // "Polo SP Mogi das Cruzes - P191" -> "Polo SP Mogi das Cruzes (P191)": nunca só o código
  if (!nomeCompleto) return null;
  const m = nomeCompleto.match(/^(.*?)\s*-\s*(P\d+)\s*$/);
  return m ? `${m[1]} (${m[2]})` : nomeCompleto;
}
function nomeCompletoPorCodigo(codigoPolo) {
  const p = polosPorId.get(codigoPolo);
  return p ? formatarNomePolo(p.polo_nome) : codigoPolo;
}

// ---------------------------------------------------------------- reset e slider mestre

function montarBotaoReset() {
  document.getElementById("btn-reset").addEventListener("click", () => {
    aplicarRaioGlobal(DATA.defaults.raio_km.valor);
    if (focoPoloAtual) voltarParaGlobalNoFoco();
    overrideLocal = {};
    const input = document.querySelector(".input-override");
    if (input) input.value = ROTULO_OVERRIDE_AUTO;
    agendarAtualizacao();
  });
}

function montarSliderMestre() {
  const d = DATA.defaults.raio_km;
  const el = document.getElementById("raio_global");
  el.value = d.valor;
  document.getElementById("raio_global_v").textContent = fmt(d.valor);
  document.getElementById("raio_global_origem").textContent = "(" + d.origem + ")";
  el.addEventListener("input", () => aplicarRaioGlobal(+el.value));
}

function aplicarRaioGlobal(valor) {
  document.getElementById("raio_global").value = valor;
  document.getElementById("raio_global_v").textContent = fmt(valor);
  if (!focoPoloAtual) {
    document.getElementById("foco-mini-slider").value = valor;
    document.getElementById("foco-mini-valor").textContent = fmt(valor);
  }
  for (const p of DATA.polos) {
    raioPorPolo[p.codigo_polo] = valor;
    const info = polosPorId.get(p.codigo_polo);
    info.elSlider.value = valor;
    info.elValor.textContent = fmt(valor);
  }
  agendarAtualizacao();
}

function badgeSla(alcanceP90Km) {
  if (alcanceP90Km === null || alcanceP90Km === undefined) {
    return { texto: "sem dado", titulo: "Polo sem OS suficientes para estimar alcance" };
  }
  if (alcanceP90Km > 150) {
    return { texto: "SLA: acima de 150 km",
      titulo: `Hoje esse polo já atende a até ${fmt(alcanceP90Km)} km cumprindo o prazo em 90% das OS (acima do raio máximo do simulador, 150 km).` };
  }
  return { texto: `SLA: ${fmt(alcanceP90Km)} km`,
    titulo: `90% das OS que esse polo já atende hoje, dentro do prazo, estão até ${fmt(alcanceP90Km)} km de distância (dado real, jul/26).` };
}

function montarListaPolos() {
  const cont = document.getElementById("lista-polos");
  const raioDefault = DATA.defaults.raio_km.valor;
  const polos = [...DATA.polos].sort((a, b) => a.polo_nome.localeCompare(b.polo_nome, "pt-BR"));
  document.getElementById("contagem-lista").textContent = polos.length;
  document.getElementById("contagem-polos-sub").textContent = polos.length;
  document.getElementById("contagem-detalhe").textContent = polos.length;

  for (const p of polos) {
    const nomeCurto = nomeCurtoPolo(p.polo_nome);
    const linha = document.createElement("div");
    linha.className = "linha-polo";
    linha.id = "polo-linha-" + p.codigo_polo;
    linha.dataset.codigo = p.codigo_polo;
    linha.dataset.nome = nomeCurto.toLowerCase();
    const badge = badgeSla(p.alcance_p90_km);
    linha.innerHTML = `
      <div class="linha-topo">
        <span class="nome-polo" title="${p.polo_nome}">${nomeCurto}</span>
        <span class="badge-sla" title="${badge.titulo}">${badge.texto}</span>
      </div>
      <div class="linha-slider">
        <input type="range" min="0" max="150" step="1" value="${raioDefault}">
        <output>${fmt(raioDefault)}</output>
      </div>`;
    const elSlider = linha.querySelector("input[type=range]");
    const elValor = linha.querySelector("output");
    elSlider.addEventListener("input", () => {
      elValor.textContent = fmt(elSlider.value);      // zero delay: puro DOM
      raioPorPolo[p.codigo_polo] = +elSlider.value;
      if (focoPoloAtual === p.codigo_polo) {
        document.getElementById("foco-mini-valor").textContent = fmt(elSlider.value);
        document.getElementById("foco-mini-slider").value = elSlider.value;
      }
      agendarAtualizacao();
    });
    Object.assign(polosPorId.get(p.codigo_polo), { elSlider, elValor });
    raioPorPolo[p.codigo_polo] = raioDefault;
    cont.appendChild(linha);
  }
}

function montarBusca() {
  document.getElementById("busca_polo").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    for (const linha of document.querySelectorAll(".linha-polo")) {
      linha.classList.toggle("escondida", q !== "" && !linha.dataset.nome.includes(q));
    }
  });
}

function montarBotaoTooltipFlutuante() {
  const btn = document.getElementById("btn-tooltip-flutuante");
  btn.addEventListener("click", () => {
    tooltipFlutuanteAtivo = !tooltipFlutuanteAtivo;
    btn.textContent = "🖱️ Tooltip Flutuante: " + (tooltipFlutuanteAtivo ? "Ativado" : "Desativado");
    btn.classList.toggle("desativado", !tooltipFlutuanteAtivo);
    if (!tooltipFlutuanteAtivo) esconderTooltipFlutuante();
  });
}

function montarTeclaEsc() {
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && popupSelecao) {
      popupSelecao.remove();
      popupSelecaoLocalId = null;
    }
  });
}

function htmlTooltipRapido(l) {
  const rotulo = ROTULO_STATUS[l.status] || l.status;
  return `<b>${l.nome_local}</b><br>${rotulo} (${pct(l.share_polo)} PagResolve)<br>Total de OS: ${fmt(l.vol_total)}`;
}

function atualizarTooltipFlutuante(camada, feature, point) {
  const el = document.getElementById("tooltip-flutuante");
  if (!tooltipFlutuanteAtivo || popupSelecaoLocalId) { el.hidden = true; return; }
  const l = locaisPorId.get(idDoFeature(camada, feature));
  if (!l || l.status === undefined) { el.hidden = true; return; }
  el.innerHTML = htmlTooltipRapido(l);
  el.style.left = (point.x + 14) + "px";
  el.style.top = (point.y + 14) + "px";
  el.hidden = false;
}

function esconderTooltipFlutuante() {
  document.getElementById("tooltip-flutuante").hidden = true;
}

function montarSlidersProdutividadeCusto() {
  const campos = [
    ["os_dia_gsp", DATA.defaults.os_dia_gsp, 1],
    ["os_dia_interior", DATA.defaults.os_dia_interior, 1],
    ["custo_tecnico", DATA.defaults.custo_tecnico, 0],
  ];
  for (const [id, d, casas] of campos) {
    const el = document.getElementById(id);
    el.value = d.valor;
    document.getElementById(id + "_v").textContent = id === "custo_tecnico" ? moeda(d.valor) : fmt(d.valor, casas);
    el.addEventListener("input", () => {
      document.getElementById(id + "_v").textContent = id === "custo_tecnico" ? moeda(el.value) : fmt(el.value, casas);
      agendarAtualizacao();
    });
  }
}

// ---------------------------------------------------------------- selecionar um polo (clique no mapa)

function selecionarPolo(codigoPolo) {
  if (document.body.classList.contains("foco")) {
    mostrarPoloNoFocoMini(codigoPolo);
    return;
  }
  document.getElementById("busca_polo").value = "";
  for (const linha of document.querySelectorAll(".linha-polo")) linha.classList.remove("escondida");
  const linha = document.getElementById("polo-linha-" + codigoPolo);
  if (!linha) return;
  linha.scrollIntoView({ behavior: "smooth", block: "center" });
  linha.classList.add("destaque");
  setTimeout(() => linha.classList.remove("destaque"), 1800);
}

function mostrarPoloNoFocoMini(codigoPolo) {
  focoPoloAtual = codigoPolo;
  const p = polosPorId.get(codigoPolo);
  document.getElementById("foco-mini-titulo").textContent = nomeCurtoPolo(p.polo_nome);
  document.getElementById("foco-mini-voltar").hidden = false;
  const valor = raioPorPolo[codigoPolo] ?? +document.getElementById("raio_global").value;
  document.getElementById("foco-mini-slider").value = valor;
  document.getElementById("foco-mini-valor").textContent = fmt(valor);
}

function voltarParaGlobalNoFoco() {
  focoPoloAtual = null;
  document.getElementById("foco-mini-titulo").textContent = "Raio Global";
  document.getElementById("foco-mini-voltar").hidden = true;
  const valor = +document.getElementById("raio_global").value;
  document.getElementById("foco-mini-slider").value = valor;
  document.getElementById("foco-mini-valor").textContent = fmt(valor);
}

// ---------------------------------------------------------------- laço de atualização (1 chamada Python "em voo")

let pendente = false;

function coletarParams() {
  return {
    raio_km: +document.getElementById("raio_global").value,
    os_dia_gsp: +document.getElementById("os_dia_gsp").value,
    os_dia_interior: +document.getElementById("os_dia_interior").value,
    custo_tecnico: +document.getElementById("custo_tecnico").value,
    raio_polo: raioPorPolo,
    override_local: overrideLocal,
  };
}

function agendarAtualizacao() {
  if (pendente) return;
  pendente = true;
  requestAnimationFrame(async () => {
    await atualizar();
    pendente = false;
  });
}

let ultimoResultado = null;
async function atualizar() {
  const r = await window.pywebview.api.simular(coletarParams());
  ultimoResultado = r;
  aplicarResultado(r);
}

// ---------------------------------------------------------------- mapa (MapLibre GL, WebGL/GPU + basemap OSM)

function montarMapa() {
  return new Promise((resolve) => {
    map = new maplibregl.Map({
      container: "map",
      style: {
        version: 8,
        sources: {
          // tiles padrão do OpenStreetMap: gratuitos, sem chave de API
          "osm": {
            type: "raster",
            tiles: ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
                    "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
                    "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          },
        },
        layers: [{ id: "osm-base", type: "raster", source: "osm" }],
      },
      center: [-48.6, -22.3], zoom: 6, attributionControl: true,
    });
    map.on("load", () => {
      // cor proporcional real (verde = 100% Ógea, amarelo = 100% PagResolve, meio do caminho = misto de
      // verdade); "sv" marca sem volume, que fica cinza independente da proporção
      const expressaoCor = [
        "case", ["==", ["feature-state", "sv"], true], COR_SEM_VOLUME,
        ["interpolate", ["linear"], ["coalesce", ["feature-state", "sp"], 0], 0, COR_OGEA_HEX, 1, COR_POLO_HEX],
      ];

      map.addSource("municipios", { type: "geojson", data: DATA.malha, promoteId: "cod_ibge" });
      map.addLayer({
        id: "municipios-fill", type: "fill", source: "municipios",
        paint: {
          "fill-color": expressaoCor,
          "fill-opacity": ["case", ["boolean", ["get", "is_sp_capital"], false], 0.18, 0.55],
        },
      });
      const selecionado = ["==", ["feature-state", "selecionado"], true];
      map.addLayer({ id: "municipios-line", type: "line", source: "municipios",
        paint: {
          "line-color": ["case", selecionado, "#111", "#555"],
          "line-width": ["case", selecionado, 2.5, 0.5],
          "line-opacity": ["case", selecionado, 1, 0.6],
        } });

      const bairros = {
        type: "FeatureCollection",
        features: DATA.locais.filter((l) => l.capital_subnode).map((l) => ({
          type: "Feature",
          properties: { local_id: l.local_id, nome_local: l.nome_local, vol_total: l.vol_total },
          geometry: { type: "Point", coordinates: [l.lon, l.lat] },
        })),
      };
      map.addSource("bairros", { type: "geojson", data: bairros, promoteId: "local_id" });
      map.addLayer({
        id: "bairros-circle", type: "circle", source: "bairros",
        paint: {
          "circle-radius": ["+", 7, ["*", 17, ["sqrt", ["/", ["max", ["get", "vol_total"], 1], vmaxBairro]]]],
          "circle-color": expressaoCor,
          "circle-stroke-color": ["case", selecionado, "#111", "#fff"],
          "circle-stroke-width": ["case", selecionado, 3, 1.5], "circle-opacity": 0.88,
        },
      });

      const polosFC = {
        type: "FeatureCollection",
        features: DATA.polos.map((p) => ({
          type: "Feature",
          properties: { codigo_polo: p.codigo_polo, polo_nome: p.polo_nome, status_bd: p.status_bd, t0: p.t0 },
          geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        })),
      };
      map.addSource("polos", { type: "geojson", data: polosFC, promoteId: "codigo_polo" });
      map.addSource("raios", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "raios-fill", type: "fill", source: "raios",
        paint: { "fill-color": COR_POLO, "fill-opacity": 0.07 } });
      map.addLayer({ id: "raios-line", type: "line", source: "raios",
        paint: { "line-color": COR_POLO, "line-width": 1.3, "line-dasharray": [2, 2], "line-opacity": 0.6 } });
      map.addLayer({
        id: "polos-circle", type: "circle", source: "polos",
        paint: {
          "circle-radius": ["+", 5, ["*", 2.3, ["sqrt", ["max", ["feature-state", "tec"], 0]]]],
          "circle-color": COR_POLO, "circle-stroke-color": "#fff", "circle-stroke-width": 2,
        },
      });

      if (DATA.ogea_latlon) {
        new maplibregl.Marker({ color: COR_OGEA })
          .setLngLat([DATA.ogea_latlon[1], DATA.ogea_latlon[0]])
          .setPopup(new maplibregl.Popup().setHTML("<div class='popup'><b>Armazém Ógea</b><br>TEFTI, Santana de Parnaíba</div>"))
          .addTo(map);
      }

      popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
      ligarPopupHoverPolo();
      for (const camada of ["polos-circle", "raios-fill", "raios-line"]) {
        map.on("click", camada, (e) => selecionarPolo(e.features[0].properties.codigo_polo));
      }
      for (const camada of ["municipios-fill", "bairros-circle"]) {
        map.on("mousemove", camada, (e) => {
          map.getCanvas().style.cursor = "pointer";
          if (tooltipFlutuanteAtivo) atualizarTooltipFlutuante(camada, e.features[0], e.point);
        });
        map.on("mouseleave", camada, () => { map.getCanvas().style.cursor = ""; esconderTooltipFlutuante(); });
        // Tooltip Flutuante ATIVADO: 1 clique só seleciona (destaca); 2 cliques trava o painel completo.
        // Tooltip Flutuante DESATIVADO: sem hover contínuo; 1 clique já mostra o painel completo.
        map.on("click", camada, (e) => {
          const id = idDoFeature(camada, e.features[0]);
          selecionarLocal(id);
          if (!tooltipFlutuanteAtivo) abrirPainelLocal(id, e.lngLat);
        });
        map.on("dblclick", camada, (e) => {
          e.preventDefault();   // não deixa o duplo clique dar zoom (comportamento padrão do MapLibre)
          const id = idDoFeature(camada, e.features[0]);
          selecionarLocal(id);
          abrirPainelLocal(id, e.lngLat);
        });
      }
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      resolve();
    });
  });
}

function ligarPopupHoverPolo() {
  map.on("mousemove", "polos-circle", (e) => {
    map.getCanvas().style.cursor = "pointer";
    const p = polosPorId.get(e.features[0].properties.codigo_polo);
    if (!p) return;
    popup.setLngLat(e.lngLat).setHTML(`<div class="popup"><b>${formatarNomePolo(p.polo_nome)}</b>
      <div class="linha"><span>Raio</span><b>${fmt(p.raio_km)} km</b></div>
      <div class="linha"><span>Técnicos hoje</span><b>${fmt(p.t0)}</b></div>
      <div class="linha"><span>Sugeridos para absorver</span><b>+${fmt(p.tecnicos_sugeridos)}</b></div>
      <div class="linha"><span>Volume hoje</span><b>${fmt(p.v0)}</b></div>
      <div class="linha"><span>Absorvido da Ógea</span><b>${fmt(p.vol_absorvido)}</b></div>
      <div class="linha"><span>CMU hoje / novo</span><b>${moeda(p.cmu_hoje)} / ${moeda(p.cmu_novo)}</b></div>
      <div class="popup-dica">Clique para ajustar o raio deste polo.</div>
    </div>`).addTo(map);
  });
  map.on("mouseleave", "polos-circle", () => { map.getCanvas().style.cursor = ""; popup.remove(); });
}

// ---------------------------------------------------------------- seleção (1 clique) e painel (2 cliques)

let localSelecionado = null;   // local_id com destaque no mapa (1 clique) — só um por vez

function idDoFeature(camada, feature) {
  return camada === "bairros-circle" ? feature.properties.local_id : String(feature.properties.cod_ibge ?? "");
}

function marcarSelecaoNoMapa(id, valor) {
  const info = locaisPorId.get(id);
  if (!info) return;
  const source = info.capital_subnode ? "bairros" : "municipios";
  const featId = info.capital_subnode ? id : info.cod_ibge;
  map.setFeatureState({ source, id: featId }, { selecionado: valor });
}

function selecionarLocal(id) {
  if (localSelecionado === id) return;
  if (localSelecionado) marcarSelecaoNoMapa(localSelecionado, false);
  localSelecionado = id;
  marcarSelecaoNoMapa(id, true);
}

// ---------------------------------------------------------------- painel de município/bairro (com exceção manual)

const ROTULO_OVERRIDE_AUTO = "Automático pelo raio";
const ROTULO_OVERRIDE_OGEA = "Forçar Ógea (100%)";

function rotuloDoOverride(valor) {
  if (!valor || valor === "auto") return ROTULO_OVERRIDE_AUTO;
  if (valor === OGEA_FORCADA) return ROTULO_OVERRIDE_OGEA;
  return nomeCompletoPorCodigo(valor);
}

function valorDoRotulo(rotulo) {
  const r = rotulo.trim();
  if (r === ROTULO_OVERRIDE_AUTO) return "auto";
  if (r === ROTULO_OVERRIDE_OGEA) return OGEA_FORCADA;
  const p = DATA.polos.find((p) => formatarNomePolo(p.polo_nome) === r);
  return p ? p.codigo_polo : null;   // null = texto digitado não corresponde a nenhuma opção válida
}

function datalistOverride(id) {
  const opcoes = [ROTULO_OVERRIDE_AUTO, ROTULO_OVERRIDE_OGEA, ...DATA.polos.map((p) => formatarNomePolo(p.polo_nome))];
  return `<datalist id="datalist-override-${id}">${opcoes.map((o) => `<option value="${o}">`).join("")}</datalist>`;
}

function htmlPainelLocal(l) {
  const rotulo = ROTULO_STATUS[l.status] || l.status;
  const volPolo = Math.max(0, l.vol_total - l.vol_ogea_cen);
  const responsavel = l.polo_resp ? formatarNomePolo(l.polo_resp) : "Polo base: 100% Ógea (sem polo anterior)";
  const capturado = l.polo_captura ? nomeCompletoPorCodigo(l.polo_captura) : "Nenhum (fica com a Ógea)";
  const valorAtual = overrideLocal[l.local_id] || "auto";
  return `<div class="popup">
    <b>${l.nome_local}</b><br>${rotulo} (${pct(l.share_polo)} PagResolve)
    <div class="linha"><span>Total de OS</span><b>${fmt(l.vol_total)}</b></div>
    <div class="linha"><span>Volume Ógea</span><b>${fmt(l.vol_ogea_cen)}</b></div>
    <div class="linha"><span>Volume PagResolve</span><b>${fmt(volPolo)}</b></div>
    <div class="linha"><span>Polo PagResolve responsável</span><b>${responsavel}</b></div>
    <div class="linha"><span>Capturado no cenário por</span><b>${capturado}</b></div>
    ${l.override_manual ? '<div class="popup-dica">Exceção manual ativa nesta localidade.</div>' : ""}
    <div class="override-bloco">
      <label for="input-override-${l.local_id}">Exceção manual de atribuição</label>
      <input type="text" id="input-override-${l.local_id}" class="input-override" data-local-id="${l.local_id}"
             list="datalist-override-${l.local_id}" value="${rotuloDoOverride(valorAtual)}"
             placeholder="Digite para buscar um polo...">
      ${datalistOverride(l.local_id)}
      <small>Automático pelo raio, Forçar Ógea (100%), ou digite o nome de um polo.</small>
    </div>
  </div>`;
}

function abrirPainelLocal(id, lngLat) {
  const l = locaisPorId.get(id);
  if (!l || l.status === undefined) return;
  if (popupSelecao) popupSelecao.remove();
  esconderTooltipFlutuante();
  popupSelecaoLocalId = id;
  // closeOnClick: clicar fora destrava (some ligado ao próprio popup de tooltip flutuante travado)
  popupSelecao = new maplibregl.Popup({ closeButton: true, closeOnClick: true, maxWidth: "280px" })
    .setLngLat(lngLat).setHTML(htmlPainelLocal(l)).addTo(map)
    .on("close", () => { popupSelecaoLocalId = null; });
}

// delegação: o <input> é inserido dinamicamente dentro do popup, então o listener fica no document
document.addEventListener("change", (e) => {
  if (!e.target.classList.contains("input-override")) return;
  const localId = e.target.dataset.localId;
  const valor = valorDoRotulo(e.target.value);
  if (valor === null) {
    // texto digitado não bate com nenhuma opção válida: não aplica, devolve pro que já estava
    e.target.value = rotuloDoOverride(overrideLocal[localId]);
    return;
  }
  if (valor === "auto") delete overrideLocal[localId];
  else overrideLocal[localId] = valor;
  agendarAtualizacao();
});

// ---------------------------------------------------------------- aplicar resultado (feature-state = repintura barata)

function circuloGeoJSON(lat, lon, raioKm, pontos = 48) {
  const R = 6371.0088;
  const latR = (lat * Math.PI) / 180, lonR = (lon * Math.PI) / 180, d = raioKm / R;
  const coords = [];
  for (let i = 0; i <= pontos; i++) {
    const brng = (i / pontos) * 2 * Math.PI;
    const lat2 = Math.asin(Math.sin(latR) * Math.cos(d) + Math.cos(latR) * Math.sin(d) * Math.cos(brng));
    const lon2 = lonR + Math.atan2(Math.sin(brng) * Math.sin(d) * Math.cos(latR), Math.cos(d) - Math.sin(latR) * Math.sin(lat2));
    coords.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }
  return coords;
}

function aplicarResultado(r) {
  for (const l of r.locais) {
    Object.assign(locaisPorId.get(l.local_id), l);
    const estatico = locaisPorId.get(l.local_id);
    const source = estatico.capital_subnode ? "bairros" : "municipios";
    const id = estatico.capital_subnode ? l.local_id : estatico.cod_ibge;
    map.setFeatureState({ source, id }, { sp: l.share_polo, sv: l.status === "sem_volume" });
  }
  for (const p of r.polos) {
    Object.assign(polosPorId.get(p.codigo_polo), p);
    map.setFeatureState({ source: "polos", id: p.codigo_polo }, { tec: (p.t0 || 0) + (p.tecnicos_sugeridos || 0) });
  }
  const feats = r.polos.filter((p) => p.raio_km > 0).map((p) => ({
    type: "Feature", properties: { codigo_polo: p.codigo_polo },
    geometry: { type: "Polygon", coordinates: [circuloGeoJSON(p.lat, p.lon, p.raio_km)] },
  }));
  map.getSource("raios").setData({ type: "FeatureCollection", features: feats });

  if (popupSelecaoLocalId) {
    popupSelecao.setHTML(htmlPainelLocal(locaisPorId.get(popupSelecaoLocalId)));
  }

  atualizarKpis(r.kpis);
  atualizarTabela(r.polos);
}

// ---------------------------------------------------------------- KPIs (compactos) + tabela

function atualizarKpis(k) {
  document.getElementById("kpi-absorvido").textContent = fmt(k.vol_absorvido) + " OS/mês";
  document.getElementById("kpi-locais").textContent = `${k.locais_capturados} locais capturados`;

  document.getElementById("kpi-share").innerHTML =
    `<b>${pct(k.share_ogea_cenario)}</b> <span style="color:var(--muted);font-weight:400">/</span> <b>${pct(1 - k.share_ogea_cenario)}</b>`;
  const delta = (k.share_ogea_cenario - k.share_ogea_hoje) * 100;
  document.getElementById("kpi-share-extra").innerHTML =
    `Ógea / PagResolve · <b>${delta >= 0 ? "+" : ""}${delta.toFixed(0)}%</b> vs. hoje`;

  document.getElementById("kpi-tec").textContent = fmt(k.tecnicos_sugeridos);
  document.getElementById("kpi-tec-custo").innerHTML = `Impacto em folha: <b>${moeda(k.custo_tecnicos_novo)}</b>/mês`;

  document.getElementById("kpi-cmu").textContent = moeda(k.cmu_medio_novo);
  document.getElementById("kpi-hoje").textContent = `Hoje: Ógea atende ${pct(k.share_ogea_hoje)} das ${fmt(k.total_os)} OS`;
}

function atualizarTabela(polos) {
  const tbody = document.querySelector("#tabela-polos tbody");
  tbody.innerHTML = "";
  const ordenado = [...polos].sort((a, b) => b.vol_absorvido - a.vol_absorvido);
  for (const p of ordenado) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${p.polo_nome}</td><td>${p.regiao_gsp ? "Capital/GSP" : "Interior"}</td>
      <td>${fmt(p.raio_km)} km</td><td>${fmt(p.t0)}</td><td>${fmt(p.vol_absorvido)}</td>
      <td>${fmt(p.tecnicos_sugeridos)}</td><td>${fmt(p.volume_novo)}</td>
      <td>${moeda(p.cmu_hoje)}</td><td>${moeda(p.cmu_novo)}</td>`;
    tbody.appendChild(tr);
  }
}

// ---------------------------------------------------------------- drawer de detalhe + exportação

function montarDrawer() {
  const overlay = document.getElementById("drawer-overlay");
  const drawer = document.getElementById("drawer-detalhe");
  const abrir = () => { overlay.hidden = false; drawer.hidden = false; };
  const fechar = () => { overlay.hidden = true; drawer.hidden = true; };
  document.getElementById("btn-abrir-detalhe").addEventListener("click", abrir);
  document.getElementById("btn-fechar-drawer").addEventListener("click", fechar);
  overlay.addEventListener("click", fechar);

  document.getElementById("btn-exportar").addEventListener("click", async () => {
    const status = document.getElementById("export-status");
    status.hidden = false; status.className = ""; status.textContent = "Exportando...";
    try {
      const r = await window.pywebview.api.exportar_cenario(coletarParams());
      if (r.ok) {
        status.className = "ok"; status.textContent = `Salvo em: ${r.caminho}`;
      } else if (r.mensagem === "cancelado") {
        status.hidden = true;
      } else {
        status.className = "erro"; status.textContent = `Erro: ${r.mensagem}`;
      }
    } catch (e) {
      status.className = "erro"; status.textContent = `Erro: ${e}`;
    }
  });
}

// ---------------------------------------------------------------- modo foco

function montarModoFoco() {
  const btn = document.getElementById("btn-foco");
  btn.addEventListener("click", () => {
    const ligado = document.body.classList.toggle("foco");
    btn.textContent = ligado ? "Sair do modo foco" : "Expandir mapa";
    document.getElementById("foco-mini").hidden = !ligado;
    if (!ligado) voltarParaGlobalNoFoco();
    requestAnimationFrame(() => map && map.resize());
  });

  document.getElementById("foco-mini-voltar").addEventListener("click", voltarParaGlobalNoFoco);
  document.getElementById("foco-mini-slider").addEventListener("input", (e) => {
    const valor = +e.target.value;
    document.getElementById("foco-mini-valor").textContent = fmt(valor);
    if (focoPoloAtual) {
      const info = polosPorId.get(focoPoloAtual);
      raioPorPolo[focoPoloAtual] = valor;
      info.elSlider.value = valor;
      info.elValor.textContent = fmt(valor);
      agendarAtualizacao();
    } else {
      aplicarRaioGlobal(valor);
    }
  });
  voltarParaGlobalNoFoco();
}
