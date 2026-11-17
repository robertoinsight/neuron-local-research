/* Neuron Local Research — interface web (sem dependências externas em tempo de execução). */
(() => {
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const S = { idioma: localStorage.getItem("nlr.idioma") || "pt", tema: localStorage.getItem("nlr.tema") || "dark",
  T: {}, chat: null, chats: [], gerando: null, anexos: [], imagens: [], visao: null, modelos: null, view: "chat" };
const MODOS = ["auto", "conversa", "biblioteca", "web", "ambos", "agente", "profunda", "projeto"];
const t = (k) => S.T[k] || k;

async function api(caminho, op = {}) {
  const r = await fetch(caminho, { headers: { "Content-Type": "application/json" }, ...op,
    body: op.body && typeof op.body !== "string" ? JSON.stringify(op.body) : op.body });
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) {} throw new Error(m); }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r.text();
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------------- i18n e tema ---------------- */
function atualizarRodape() {
  api("/api/saude").then((s) => ($("#rodape").textContent = `Neuron Local Research ${s.versao} · ${S.idioma === "en" ? "runs 100% on your computer" : "roda 100% no seu computador"}`)).catch(() => {});
}
async function aplicarIdioma(id, avisarServidor = true) {
  setTimeout(atualizarRodape, 300);
  S.idioma = id; localStorage.setItem("nlr.idioma", id);
  S.T = await api(`/api/i18n/${id}`);
  document.documentElement.lang = id === "en" ? "en" : "pt-BR";
  $$("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  $$("[data-i18n-ph]").forEach((el) => (el.placeholder = t(el.dataset.i18nPh)));
  $$("[data-i18n-title]").forEach((el) => (el.title = t(el.dataset.i18nTitle)));
  $("#btn-idioma").textContent = id.toUpperCase();
  const m = $("#modo"), atual = m.value || "auto";
  m.innerHTML = MODOS.map((x) => `<option value="${x}">${esc(t("modo_" + x))}</option>`).join("");
  m.value = atual;
  if (avisarServidor) api("/api/idioma", { method: "PUT", body: { idioma: id } }).catch(() => {});
  renderModeloInfo(); renderChats();
  if (S.view !== "chat") abrirView(S.view);
}
function aplicarTema(tm) {
  S.tema = tm; localStorage.setItem("nlr.tema", tm);
  document.documentElement.dataset.theme = tm;
  $("#hl-dark").disabled = tm !== "dark"; $("#hl-light").disabled = tm === "dark";
}

/* ---------------- markdown ---------------- */
marked.setOptions({ gfm: true, breaks: false });
function md(texto, fontes) {
  let html = DOMPurify.sanitize(marked.parse(texto || ""), { ADD_ATTR: ["target"] });
  const div = document.createElement("div"); div.innerHTML = html;
  div.querySelectorAll("pre > code").forEach((code) => {
    const lang = (code.className.match(/language-(\S+)/) || [])[1] || "";
    try { if (lang && hljs.getLanguage(lang)) hljs.highlightElement(code); else hljs.highlightElement(code); } catch (e) {}
    const pre = code.parentElement, box = document.createElement("div");
    box.className = "bloco-codigo";
    box.innerHTML = `<div class="cab"><span>${esc(lang || "code")}</span><button class="copiar">${esc(t("copiar"))}</button></div>`;
    pre.replaceWith(box); box.appendChild(pre);
  });
  div.querySelectorAll("a").forEach((a) => { a.target = "_blank"; a.rel = "noopener"; });
  if (fontes && fontes.length) {
    const nums = new Set(fontes.map((f) => f.n));
    const walker = document.createTreeWalker(div, NodeFilter.SHOW_TEXT);
    const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((n) => {
      if (n.parentElement.closest("code,pre")) return;
      if (!/\[\d+\]/.test(n.nodeValue)) return;
      const frag = document.createElement("span");
      frag.innerHTML = esc(n.nodeValue).replace(/\[(\d+)\]/g, (m, k) => nums.has(+k) ? `<a class="cit" data-n="${k}">${k}</a>` : m);
      n.replaceWith(...frag.childNodes);
    });
  }
  return div.innerHTML;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest(".copiar");
  if (b) {
    const code = b.closest(".bloco-codigo")?.querySelector("code");
    const txt = code ? code.innerText : b.dataset.texto || "";
    navigator.clipboard?.writeText(txt).catch(() => {});
    const o = b.textContent; b.textContent = t("copiado"); setTimeout(() => (b.textContent = o), 1200);
  }
  const c = e.target.closest(".cit");
  if (c) {
    const f = c.closest(".corpo")?.querySelector(`.fonte[data-n="${c.dataset.n}"]`);
    if (f) { f.classList.add("destaque"); f.scrollIntoView({ block: "nearest", behavior: "smooth" }); setTimeout(() => f.classList.remove("destaque"), 1500); }
  }
});

/* ---------------- modelos ---------------- */
async function carregarModelos() {
  try { S.modelos = await api("/api/modelos"); } catch (e) { S.modelos = { erro: e.message }; }
  renderModeloInfo();
}
function renderModeloInfo() {
  const m = S.modelos, info = $("#modelo-info");
  if (!m) return;
  if (m.erro) { $("#modelo-nome").textContent = "NLR"; info.innerHTML = `<span class="chip mau">● ${esc(t("servidor_fora"))}</span>`; return; }
  $("#modelo-nome").textContent = m.modelo_chat;
  const atual = (m.modelos || []).find((x) => x.id === m.modelo_chat);
  const perfil = m.perfil ? t("perfil_" + m.perfil.nome) : "";
  const semPs = !["ollama", "lmstudio"].includes(m.backend);  // sem /api/ps: "respondeu há pouco" = carregado
  const ativo = atual && (atual.carregado || (semPs && m.ultima_resposta && Date.now() / 1000 - m.ultima_resposta < 300));
  const estado = ativo ? t("carregado") : (atual ? t("sob_demanda") : t("nao_carregado"));
  info.innerHTML = `<span class="chip ${ativo ? "ok" : ""}" id="chip-estado">● ${esc(estado)}</span>
    <span class="chip">${esc(t("contexto"))} ${m.contexto_tokens}</span><span class="chip">${esc(t("perfil"))} ${esc(perfil)}</span>
    <span class="chip">${esc(m.backend)}</span>`;
  $("#menu-modelo").innerHTML = (m.modelos || []).filter((x) => x.tipo !== "embeddings").map((x) =>
    `<button data-modelo="${esc(x.id)}">${x.id === m.modelo_chat ? "✓ " : ""}${esc(x.id)}${x.visao ? ` <span class="olho" title="${esc(t("visao_modelo"))}">👁</span>` : ""}<div class="sub">${x.carregado ? "● " + esc(t("carregado")) : esc(t("nao_carregado"))}${x.parametros_b ? " · " + (+x.parametros_b).toFixed(1) + "B" : ""}${(x.contexto_carregado || x.contexto_max) ? " · " + esc(t("contexto")) + " " + (x.contexto_carregado || x.contexto_max) : ""}</div></button>`).join("");
}
$("#btn-modelo").onclick = (e) => { e.stopPropagation(); $("#menu-modelo").classList.toggle("oculto"); };
$("#menu-modelo").onclick = async (e) => {
  const b = e.target.closest("[data-modelo]"); if (!b) return;
  $("#menu-modelo").classList.add("oculto");
  try { S.modelos = await api("/api/modelo", { method: "PUT", body: { modelo_chat: b.dataset.modelo } }); } catch (er) { S.modelos = { erro: er.message }; }
  renderModeloInfo();
};
document.addEventListener("click", (e) => {
  if (!e.target.closest(".seletor-modelo")) $("#menu-modelo").classList.add("oculto");
  if (!e.target.closest(".anexar-wrap")) $("#menu-anexar").classList.add("oculto");
});

/* ---------------- chats (barra lateral) ---------------- */
async function carregarChats() {
  const q = $("#busca").value.trim();
  try { S.chats = await api(`/api/chats?q=${encodeURIComponent(q)}`); } catch (e) { S.chats = []; }
  renderChats();
}
function renderChats() {
  const lista = $("#lista-chats");
  if (!S.chats.length) { lista.innerHTML = `<div class="chat-item" style="color:var(--txt3)">${esc(t("sem_chats"))}</div>`; return; }
  const porId = Object.fromEntries(S.chats.map((c) => [c.id, c]));
  const raizes = S.chats.filter((c) => !c.pai || !porId[c.pai]);
  const filhos = {}; S.chats.forEach((c) => { if (c.pai && porId[c.pai]) (filhos[c.pai] = filhos[c.pai] || []).push(c); });
  const html = [];
  const item = (c, filho) => html.push(`<div class="chat-item ${filho ? "filho" : ""} ${S.chat === c.id ? "ativo" : ""}" data-id="${c.id}" title="${esc(c.titulo)}">
      <span class="tit">${esc(c.titulo || "…")}</span>${c.continuacao ? `<span class="elo" title="${esc(t("continua_em"))}">⇢</span>` : ""}
      <span class="acoes"><button data-acao="ren" title="${esc(t("renomear"))}">✎</button><button data-acao="del" title="${esc(t("apagar"))}">🗑</button></span></div>`);
  const andar = (c, filho) => { item(c, filho); (filhos[c.id] || []).forEach((f) => andar(f, true)); };
  raizes.forEach((c) => andar(c, false));
  lista.innerHTML = html.join("");
}
$("#lista-chats").onclick = async (e) => {
  const it = e.target.closest(".chat-item[data-id]"); if (!it) return;
  const id = it.dataset.id, acao = e.target.closest("[data-acao]")?.dataset.acao;
  if (acao === "ren") {
    const atual = S.chats.find((c) => c.id === id)?.titulo || "";
    const novo = prompt(t("novo_titulo"), atual);
    if (novo && novo.trim()) { await api(`/api/chats/${id}`, { method: "PATCH", body: { titulo: novo.trim() } }); carregarChats(); }
    return;
  }
  if (acao === "del") {
    if (!confirm(t("confirmar_apagar"))) return;
    await api(`/api/chats/${id}`, { method: "DELETE" });
    if (S.chat === id) novoChat(); carregarChats(); return;
  }
  abrirChat(id); fecharMenu();
};
let tBusca; $("#busca").oninput = () => { clearTimeout(tBusca); tBusca = setTimeout(carregarChats, 250); };

async function abrirChat(id) {
  abrirView("chat"); S.chat = id; renderChats();
  const d = await api(`/api/chats/${id}`);
  const box = $("#mensagens"); box.innerHTML = "";
  if (d.cadeia && d.cadeia.length > 1) addHandoff(`${t("cadeia")}: ${d.cadeia.length}`);
  d.mensagens.forEach((m) => addMsg(m.role, m.content));
  if (d.continuacao) addHandoff(`${t("continua_em")} → ${d.continuacao}`, d.continuacao);
  S.projetoChat = d.projeto || ""; renderProjetoChat();
  atualizarBoasVindas(); rolar(true);
}
function novoChat() { S.chat = null; S.projetoChat = ""; setTimeout(renderProjetoChat); abrirView("chat"); $("#mensagens").innerHTML = ""; atualizarBoasVindas(); renderChats(); $("#entrada").focus(); }
$("#btn-novo").onclick = () => { novoChat(); fecharMenu(); };
function atualizarBoasVindas() { $("#boas-vindas").classList.toggle("oculto", $("#mensagens").children.length > 0); }

/* ---------------- mensagens ---------------- */
function rolar(forcar) { const b = $("#mensagens"); if (forcar || b.scrollHeight - b.scrollTop - b.clientHeight < 160) b.scrollTop = b.scrollHeight; }
function addHandoff(texto, id) {
  const d = document.createElement("div"); d.className = "handoff"; d.textContent = "⇢ " + texto;
  if (id) { d.style.cursor = "pointer"; d.onclick = () => abrirChat(id); }
  $("#mensagens").appendChild(d); return d;
}
function htmlFontes(fontes) {
  if (!fontes || !fontes.length) return "";
  return `<div class="fontes">` + fontes.map((f) => {
    const web = /^https?:/.test(f.referencia || "");
    let dom = f.referencia || ""; try { if (web) dom = new URL(f.referencia).hostname; } catch (e) {}
    return `<a class="fonte" data-n="${f.n}" ${web ? `href="${esc(f.referencia)}" target="_blank" rel="noopener"` : ""} title="${esc(f.trecho || f.titulo)}">
      <span class="n">${f.n}</span><span><span class="t">${esc(f.titulo)}</span><span class="d">${esc(dom)}${f.local ? " · " + esc(f.local) : ""}</span></span></a>`;
  }).join("") + `</div>`;
}
const MARCA_IMG = /\n?\[imagem:([a-f0-9]{12}\.[a-z]{3,4})\]/g;
function addMsg(papel, texto, extra = {}) {
  const d = document.createElement("div"); d.className = `msg ${papel}`;
  if (papel === "user") {
    const ids = [...String(texto).matchAll(MARCA_IMG)].map((m) => m[1]);
    const limpo = String(texto).replace(MARCA_IMG, "").trim();
    const imgs = (extra.imagens || ids.map((id) => ({ id, url: `/api/imagens/${id}` })));
    d.innerHTML = `<div class="col-user"><div class="bolha"></div>${imgs.length ? `<div class="imgs-msg">${imgs.map((i) =>
      `<img src="${esc(i.miniatura || i.url || "/api/imagens/" + i.id)}" data-full="/api/imagens/${esc(i.id)}" alt="${esc(i.nome || i.id)}" class="${i.pixel ? "pixel" : ""}">`).join("")}</div>` : ""}</div>`;
    d.querySelector(".bolha").textContent = limpo;
  }
  else if (papel === "system") d.innerHTML = `<div class="corpo"></div>`, (d.firstChild.textContent = texto);
  else d.innerHTML = `<div class="avatar">N</div><div class="corpo"></div>`;
  $("#mensagens").appendChild(d);
  if (papel === "assistant") preencher(d, texto, extra);
  atualizarBoasVindas(); return d;
}
function preencher(d, texto, { fontes, avisos, rota, digitando } = {}) {
  const c = d.querySelector(".corpo");
  c.innerHTML = (rota ? `<div class="rota">${esc(t("rota"))}: ${esc(t("modo_" + rota) || rota)}</div>` : "") +
    `<div class="txt ${digitando ? "digitando" : ""}">${md(texto, fontes)}</div>` +
    (fontes && fontes.length ? `<div class="rota" style="margin-top:8px">${esc(t("fontes"))}</div>${htmlFontes(fontes)}` : "") +
    (avisos && avisos.length ? `<div class="avisos">${avisos.map(esc).join("<br>")}</div>` : "") +
    (!digitando ? `<div class="acoes-msg"><button class="copiar" data-texto="${esc(texto)}">⧉ ${esc(t("copiar"))}</button></div>` : "");
}
function limparFontesDoTexto(txt) { return txt.replace(/\n+\*\*(Fontes|Sources)\*\*\n[\s\S]*$/, ""); }

async function garantirChat() {
  if (S.chat) return S.chat;
  const r = await api("/api/chats", { method: "POST", body: {} }); S.chat = r.id; setTimeout(renderProjetoChat); return r.id;
}

async function enviar(acaoImagem = "") {
  const ent = $("#entrada"), texto = ent.value.trim();
  if (S.gerando) { S.gerando.abort(); return; }
  if (S.imagens.some((i) => !i.id)) return;  // ainda enviando
  const imagens = S.imagens.slice();
  if (!texto && !imagens.length) return;
  if (!texto && imagens.length && !acaoImagem) acaoImagem = (S.visao && S.visao.modo_padrao) || "minucioso";
  const modo = $("#modo").value;
  ent.value = ""; autoAltura();
  const sid = await garantirChat();
  const rotulo = acaoImagem ? t("acao_" + acaoImagem) : "";
  addMsg("user", (texto || (rotulo ? `[${rotulo}]` : "")) + (S.anexos.length ? "\n📎 " + S.anexos.map((a) => a.nome).join(", ") : ""), { imagens });
  rolar(true);
  if (!imagens.length && modo === "profunda") return pesquisaProfunda(texto, sid);
  if (!imagens.length && modo === "projeto") return iniciarProjeto(texto);
  const anexos = S.anexos.map((a) => a.texto); S.anexos = []; S.imagens = []; renderAnexos();
  const d = addMsg("assistant", "", { digitando: true }); preencher(d, t("pensando"), { digitando: true });
  const ctrl = new AbortController(); S.gerando = ctrl; botaoEnviar();
  let acc = "", rota = "";
  try {
    const r = await fetch(`/api/chats/${sid}/mensagens`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto, modo, stream: true, anexos, imagens: imagens.map((i) => i.id), acao_imagem: acaoImagem }), signal: ctrl.signal });
    const leitor = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await leitor.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const bloco = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = (bloco.match(/^event: (.*)$/m) || [])[1], dado = JSON.parse((bloco.match(/^data: (.*)$/m) || [])[1] || "{}");
        if (ev === "token") { acc += dado.t; preencher(d, limparFontesDoTexto(acc), { rota, digitando: true }); rolar(); }
        else if (ev === "evento" && dado.tipo === "rota") rota = dado.msg;
        else if (ev === "evento" && dado.tipo === "status" && !acc) preencher(d, `_${dado.msg}_`, { rota, digitando: true });
        else if (ev === "handoff") addHandoff(`${t("handoff_aviso")}: ${dado.msg}`);
        else if (ev === "fim") {
          setTimeout(carregarModelos, 200);
          preencher(d, limparFontesDoTexto(dado.texto), { fontes: dado.fontes, avisos: dado.avisos.filter((a) => !/^(O chat|The chat)/.test(a)), rota: dado.rota });
          if (dado.sessao && dado.sessao !== S.chat) { S.chat = dado.sessao; }
        } else if (ev === "erro") preencher(d, `**${t("erro")}:** ${dado.msg}`);
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") preencher(d, `**${t("erro")}:** ${e.message}`); else preencher(d, acc || "…");
  } finally { S.gerando = null; botaoEnviar(); carregarChats(); rolar(); }
}
function botaoEnviar() { const b = $("#btn-enviar"); b.textContent = S.gerando ? "■" : "↑"; b.title = t(S.gerando ? "parar" : "enviar"); }

/* ---------------- jobs (pesquisa profunda, projetos, benchmark) ---------------- */
async function acompanhar(jid, aoEvento) {
  let desde = 0;
  for (;;) {
    const j = await api(`/api/jobs/${jid}?desde=${desde}`);
    desde = j.total_eventos; j.eventos.forEach(aoEvento);
    if (j.estado !== "rodando") return j;
    await new Promise((r) => setTimeout(r, 900));
  }
}
async function pesquisaProfunda(pergunta, sid) {
  const d = addMsg("assistant", "");
  const c = d.querySelector(".corpo");
  c.innerHTML = `<div class="progresso"><div><b>🔎 ${esc(t("pesquisando"))}</b></div><div class="barra"><i style="width:3%"></i></div><div class="linhas"></div></div>`;
  const linhas = c.querySelector(".linhas"), barra = c.querySelector(".barra i");
  let total = 1, feitos = 0;
  const { job } = await api("/api/pesquisa", { method: "POST", body: { pergunta, chat: sid, fontes: "web",
    profundidade: +$("#prof").value, largura: +$("#larg").value, abnt: !!($("#prof-abnt") && $("#prof-abnt").checked) } });
  S.gerando = { abort() {} }; botaoEnviar();
  const j = await acompanhar(job, (ev) => {
    if (ev.etapa === "inicio") total = (ev.profundidade || 1) * (ev.largura || 3) + 2;
    if (["achado", "secao"].includes(ev.etapa)) feitos++;
    barra.style.width = Math.min(97, 5 + (feitos / total) * 92) + "%";
    linhas.insertAdjacentHTML("beforeend", `<div class="linha"><b>${esc(ev.etapa)}</b><span>${esc(String(ev.msg || "").slice(0, 160))}</span></div>`);
    rolar();
  });
  S.gerando = null; botaoEnviar();
  if (j.estado === "erro") { preencher(d, `**${t("erro")}:** ${j.erro}`); return; }
  const r = j.resultado;
  const corpo = r.markdown.replace(/\n## (Fontes|Sources)\n[\s\S]*?(?=\n## |$)/, "\n");
  preencher(d, corpo + `\n\n_${t("relatorio_salvo")}: ${r.arquivos.map((a) => `[${a}](/api/relatorios/${encodeURIComponent(a)})`).join(", ")}_`,
    { fontes: r.fontes, rota: "profunda" });
  carregarChats(); rolar();
}
async function iniciarProjeto(objetivo) {
  const { job } = await api("/api/projetos", { method: "POST", body: { objetivo, autonomo: $("#autonomo").checked } });
  const d = addMsg("assistant", "");
  const c = d.querySelector(".corpo");
  c.innerHTML = `<div class="progresso"><div><b>🛠 ${esc(t("projeto_iniciado"))}</b></div><div class="linhas"></div></div>`;
  const linhas = c.querySelector(".linhas");
  const j = await acompanhar(job, (ev) => {
    linhas.insertAdjacentHTML("beforeend", `<div class="linha"><b>${esc(ev.etapa)}</b><span>${esc(String(ev.msg || "").slice(0, 200))}</span></div>`); rolar();
  });
  linhas.insertAdjacentHTML("beforeend", j.estado === "erro" ? `<div class="avisos">${esc(j.erro)}</div>` :
    `<div class="linha"><b>✓</b><a href="#" data-proj="${esc(j.resultado.projeto)}">${esc(j.resultado.projeto)} — ${esc(j.resultado.status)}</a></div>`);
}
document.addEventListener("click", (e) => { const a = e.target.closest("[data-proj]"); if (a) { e.preventDefault(); abrirProjeto(a.dataset.proj); } });

/* ---------------- views: projetos e relatórios ---------------- */
function abrirView(v) {
  S.view = v;
  ["chat", "projetos", "relatorios", "memoria", "documentos", "kits"].forEach((x) => $(`#view-${x}`).classList.toggle("oculto", x !== v));
  if (v === "memoria") listarMemoria();
  if (v === "kits") abrirKits();
  if (v === "documentos") listarDocumentos();
  if (v === "projetos") listarProjetos();
  if (v === "relatorios") listarRelatorios();
}
$$(".side-link[data-view]").forEach((b) => (b.onclick = () => { abrirView(b.dataset.view); fecharMenu(); }));
const st = (s) => `<span class="st ${esc(s)}">${esc(t(s) !== s ? t(s) : s)}</span>`;
async function listarProjetos() {
  const ps = await api("/api/projetos").catch(() => []);
  $("#view-projetos").innerHTML = `<h2>${esc(t("projetos"))}</h2>` + (ps.length ? ps.map((p) =>
    `<div class="cartao" data-proj="${esc(p.id)}"><div style="display:flex;justify-content:space-between;gap:8px"><b>${esc(p.nome)}</b>${st(p.status)}</div>
     <div class="sub">${esc(p.objetivo.slice(0, 160))}</div><div class="barra"><i style="width:${p.total ? (100 * p.feitos / p.total) : 0}%"></i></div>
     <div class="sub">${p.feitos}/${p.total} ${esc(t("tarefas"))} · ${esc(p.fase || "")}</div></div>`).join("") : `<p class="sub">${esc(t("nenhum_projeto"))}</p>`);
}
async function abrirProjeto(id) {
  abrirView("projetos");
  const p = await api(`/api/projetos/${encodeURIComponent(id)}`);
  $("#view-projetos").innerHTML = `<button class="side-link" id="voltar-proj">← ${esc(t("voltar"))}</button>
    <h2>${esc(p.nome)} ${st(p.status)}</h2><p class="sub">${esc(p.objetivo)}</p>
    <div class="barra"><i style="width:${p.total ? (100 * p.feitos / p.total) : 0}%"></i></div>
    <h3>${esc(t("tarefas"))} (${p.feitos}/${p.total})</h3>${p.tarefas.map((x) => `<div class="tarefa">${st(x.status)}<div><b>${esc(x.titulo)}</b><div class="sub">${esc(x.descricao)}</div></div></div>`).join("")}
    <h3>${esc(t("arquivos"))}</h3><div class="sub">${p.arquivos.map(esc).join("<br>")}</div>
    <h3>${esc(t("diario"))}</h3><pre class="diario">${esc(p.diario)}</pre>`;
  $("#voltar-proj").onclick = listarProjetos;
}
async function listarRelatorios() {
  const rs = await api("/api/relatorios").catch(() => []);
  $("#view-relatorios").innerHTML = `<h2>${esc(t("relatorios"))}</h2>` + (rs.length ? rs.map((r) =>
    `<a class="cartao" style="display:block;text-decoration:none;color:inherit" href="/api/relatorios/${encodeURIComponent(r.nome)}" target="_blank"><b>${esc(r.nome)}</b>
     <div class="sub">${new Date(r.modificado * 1000).toLocaleString(S.idioma === "en" ? "en-US" : "pt-BR")} · ${(r.tamanho / 1024).toFixed(1)} KB</div></a>`).join("") : `<p class="sub">${esc(t("nenhum_relatorio"))}</p>`);
}

/* ---------------- anexos ---------------- */
$("#btn-anexar").onclick = (e) => { e.stopPropagation(); $("#menu-anexar").classList.toggle("oculto"); };
$("#menu-anexar").onclick = (e) => {
  const b = e.target.closest("[data-dest]"); if (!b) return;
  $("#menu-anexar").classList.add("oculto");
  if (b.dataset.dest === "imagem") { $("#arquivo-imagem").click(); return; }
  $("#arquivo").dataset.dest = b.dataset.dest; $("#arquivo").click();
};
$("#arquivo-imagem").onchange = async (e) => { for (const f of e.target.files) await anexarImagem(f); e.target.value = ""; };
$("#arquivo").onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  if (e.target.dataset.dest !== "biblioteca" && /^image\//.test(f.type)) { await anexarImagem(f); e.target.value = ""; return; }
  const b64 = await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(r.result.split(",")[1]); r.readAsDataURL(f); });
  try {
    const r = await api("/api/upload", { method: "POST", body: { nome: f.name, dados_b64: b64, destino: e.target.dataset.dest } });
    if (r.destino === "chat") { S.anexos.push({ nome: f.name + (r.cortado ? " " + t("anexo_cortado") : ""), texto: r.texto }); renderAnexos(); }
    else addHandoff(`📚 ${f.name}: ${t("anexo_ok_bib")}`);
  } catch (er) { alert(`${t("erro")}: ${er.message}`); }
  e.target.value = "";
};
function renderAnexos() {
  $("#anexos").innerHTML = S.imagens.map((im, i) => `<span class="anexo-img ${im.pixel ? "pixel" : ""}" title="${esc(im.nome)}${im.largura ? ` · ${im.largura}×${im.altura}` : ""}">
      <img src="${esc(im.miniatura || im.local || "")}" alt=""><button data-rm-img="${i}" title="${esc(t("imagem_remover"))}">✕</button>
      ${im.id ? "" : `<span class="carregando">…</span>`}</span>`).join("") +
    S.anexos.map((a, i) => `<span class="anexo">📎 ${esc(a.nome)} <button data-rm="${i}">✕</button></span>`).join("");
  const tem = S.imagens.length > 0;
  $("#acoes-imagem").classList.toggle("oculto", !tem);
  $("#entrada").placeholder = t(tem ? "placeholder_imagem" : "placeholder");
  if (tem) renderVisaoStatus();
}
$("#anexos").onclick = (e) => {
  const b = e.target.closest("[data-rm]"); if (b) { S.anexos.splice(+b.dataset.rm, 1); renderAnexos(); return; }
  const bi = e.target.closest("[data-rm-img]"); if (bi) { S.imagens.splice(+bi.dataset.rmImg, 1); renderAnexos(); }
};

/* ---------------- v0.7: imagens (clipe, arrastar, colar) e visão ---------------- */
function toast(msg) { const d = document.createElement("div"); d.className = "toast"; d.textContent = msg; document.body.appendChild(d); setTimeout(() => d.remove(), 3500); }
async function carregarVisao() { try { S.visao = await api("/api/visao"); } catch (e) { S.visao = { ok: false, erro: e.message }; } renderVisaoStatus(); }
function renderVisaoStatus() {
  const el = $("#visao-status"); if (!el) return;
  const v = S.visao; if (!v) { el.textContent = ""; return; }
  $("#btn-reversa").parentElement.classList.toggle("oculto", v.links_manuais === false);
  if (!v.ok) { el.className = "visao-status mau"; el.textContent = "⚠ " + (v.erro || t("visao_sem")).split("\n")[0]; el.title = v.erro || ""; return; }
  el.className = "visao-status";
  el.textContent = `👁 ${t("visao_modelo")}: ${v.modelo}${v.carregado === false ? " · " + t("sob_demanda") : ""}${v.avisos && v.avisos.length ? " · ⚠ " + v.avisos[0] : ""}`;
  el.title = (v.avisos || []).join("\n");
}
async function anexarImagem(f) {
  const max = (S.visao && S.visao.max_imagens) || 4;
  if (S.imagens.length >= max) { toast(`${t("imagem_limite")} ${max}`); return; }
  const item = { nome: f.name || "imagem.png", local: URL.createObjectURL(f) };
  S.imagens.push(item); renderAnexos();
  if (!S.visao) carregarVisao();
  try {
    const b64 = await lerB64(f);
    const r = await api("/api/imagens", { method: "POST", body: { nome: item.nome, dados_b64: b64 } });
    Object.assign(item, r, { pixel: Math.max(r.largura, r.altura) <= 128 });
  } catch (er) { S.imagens.splice(S.imagens.indexOf(item), 1); toast(`${t("erro")}: ${er.message}`); }
  renderAnexos(); $("#entrada").focus();
}
$$("[data-acao-img]").forEach((b) => (b.onclick = () => enviar(b.dataset.acaoImg)));
document.addEventListener("paste", (e) => {
  if (S.view !== "chat") return;
  const fs = [...(e.clipboardData?.items || [])].filter((i) => i.kind === "file" && i.type.startsWith("image/")).map((i) => i.getAsFile());
  if (!fs.length) return;
  e.preventDefault();
  fs.forEach((f, k) => { if (!f.name || f.name === "image.png") Object.defineProperty(f, "name", { value: `colada-${Date.now()}-${k}.png` }); anexarImagem(f); });
});
(() => {
  const area = $("#view-chat"), aviso = $("#soltar-imagem"); let n = 0;
  const temImg = (e) => [...(e.dataTransfer?.items || [])].some((i) => i.kind === "file");
  area.addEventListener("dragenter", (e) => { if (!temImg(e)) return; e.preventDefault(); n++; aviso.classList.remove("oculto"); });
  area.addEventListener("dragover", (e) => { if (temImg(e)) e.preventDefault(); });
  area.addEventListener("dragleave", () => { n = Math.max(0, n - 1); if (!n) aviso.classList.add("oculto"); });
  area.addEventListener("drop", (e) => {
    n = 0; aviso.classList.add("oculto");
    const fs = [...(e.dataTransfer?.files || [])].filter((f) => f.type.startsWith("image/"));
    if (!fs.length) return; e.preventDefault(); fs.forEach(anexarImagem);
  });
  })();
$("#btn-reversa").onclick = (e) => { e.stopPropagation(); $("#menu-reversa").classList.toggle("oculto"); };
document.addEventListener("click", (e) => { if (!e.target.closest(".reversa-wrap")) $("#menu-reversa").classList.add("oculto"); });
$("#menu-reversa").onclick = async (e) => {
  const b = e.target.closest("[data-reversa]"); if (!b) return;
  $("#menu-reversa").classList.add("oculto");
  const im = S.imagens.find((i) => i.id); const janela = window.open(b.dataset.reversa, "_blank", "noopener");
  if (!im) return;
  try {  // a área de transferência só aceita PNG: converte no navegador
    const blob = await fetch(`/api/imagens/${im.id}`).then((r) => r.blob());
    const bmp = await createImageBitmap(blob); const c = document.createElement("canvas"); c.width = bmp.width; c.height = bmp.height;
    c.getContext("2d").drawImage(bmp, 0, 0);
    const png = await new Promise((ok) => c.toBlob(ok, "image/png"));
    await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
    toast(t("imagem_copiada"));
  } catch (er) { toast(t("imagem_nao_copiada")); }
  if (!janela) toast(t("imagem_nao_copiada"));
};
document.addEventListener("click", (e) => { const im = e.target.closest(".imgs-msg img"); if (im) window.open(im.dataset.full || im.src, "_blank"); });

/* ---------------- compositor ---------------- */
function autoAltura() { const e = $("#entrada"); e.style.height = "auto"; e.style.height = Math.min(200, e.scrollHeight) + "px"; }
$("#entrada").oninput = autoAltura;
$("#entrada").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(); } };
$("#btn-enviar").onclick = () => enviar();
$("#modo").onchange = () => {
  $("#opcoes-profunda").classList.toggle("oculto", $("#modo").value !== "profunda");
  $("#opcoes-projeto").classList.toggle("oculto", $("#modo").value !== "projeto");
};
$$(".sugestao").forEach((b) => (b.onclick = () => { $("#entrada").value = b.textContent; autoAltura(); $("#entrada").focus(); }));

/* ---------------- topo, menu e configurações ---------------- */
$("#btn-tema").onclick = () => aplicarTema(S.tema === "dark" ? "light" : "dark");
$("#btn-idioma").onclick = () => aplicarIdioma(S.idioma === "pt" ? "en" : "pt");
$("#btn-menu").onclick = () => $("#app").classList.toggle("menu-aberto");
$("#overlay").onclick = fecharMenu;
function fecharMenu() { $("#app").classList.remove("menu-aberto"); }
$("#btn-config").onclick = async () => {
  const c = await api("/api/configuracoes").catch(() => ({}));
  $("#cfg-idioma").value = S.idioma; $("#cfg-tema").value = S.tema;
  $("#cfg-backend").value = c.backend || "lmstudio"; $("#cfg-url").value = c.base_url || ""; $("#cfg-status").textContent = "";
  $("#dlg-config").showModal(); fecharMenu();
};
$("#btn-salvar-cfg").onclick = async (e) => {
  e.preventDefault();
  aplicarTema($("#cfg-tema").value);
  try {
    await api("/api/configuracoes", { method: "PUT", body: { idioma: $("#cfg-idioma").value, backend: $("#cfg-backend").value, base_url: $("#cfg-url").value } });
    await aplicarIdioma($("#cfg-idioma").value, false);
    $("#cfg-status").textContent = t("salvo"); carregarModelos();
  } catch (er) { $("#cfg-status").textContent = er.message; }
};
$("#btn-bench").onclick = async () => {
  const out = $("#bench-saida"); out.textContent = "…";
  const { job } = await api("/api/benchmark?rapido=true", { method: "POST" });
  const j = await acompanhar(job, (ev) => (out.textContent += "\n" + ev.msg));
  if (j.estado === "erro") { out.textContent += "\n" + j.erro; return; }
  const r = j.resultado;
  out.textContent = `${r.modelo}: ${r.tokens_por_segundo} tok/s · JSON ${(r.json_primeira * 100).toFixed(0)}% / ${(r.json_com_correcao * 100).toFixed(0)}%\n→ ${t("perfil")} ${r.recomendacao.perfil}, ${t("contexto")} ${r.recomendacao.contexto_tokens}`;
};

/* ---------------- início ---------------- */
async function iniciar() {
  aplicarTema(S.tema);
  await aplicarIdioma(S.idioma, true);
  atualizarRodape();
  carregarModelos(); await carregarChats();
  const h = location.hash.slice(1); if (h) abrirChat(h); else atualizarBoasVindas();
}
iniciar();
setInterval(() => { if (!document.hidden) carregarModelos(); }, 60000);

/* ---------------- v0.5: projeto do chat, memória e documentos ---------------- */
function renderProjetoChat() {
  const b = $("#btn-projeto-chat"); if (!b) return;
  b.classList.toggle("oculto", !S.chat);
  b.textContent = "🧠 " + (S.projetoChat ? t("projeto") + ": " + S.projetoChat : t("memoria_global"));
  b.title = t("projeto_chat_dica");
}
$("#btn-projeto-chat").onclick = async () => {
  if (!S.chat) return;
  const p = prompt(t("projeto_chat_dica"), S.projetoChat || "");
  if (p === null) return;
  const r = await api(`/api/chats/${S.chat}`, { method: "PATCH", body: { projeto: p.trim() } });
  S.projetoChat = r.projeto || ""; renderProjetoChat();
};
S.mem = { escopo: "", q: "" };
const marcaHtml = (m) => `<span class="marca ${esc(m)}">${esc(t("marca_" + m))}</span>`;
async function listarMemoria() {
  const d = await api(`/api/memoria?escopo=${encodeURIComponent(S.mem.escopo)}&q=${encodeURIComponent(S.mem.q)}`).catch(() => ({ escopos: [], itens: [] }));
  const opts = [`<option value="">${esc(t("todos_escopos"))}</option>`].concat(d.escopos.map((e) =>
    `<option value="${esc(e.escopo)}" ${e.escopo === S.mem.escopo ? "selected" : ""}>${esc(e.escopo)} (${e.n})</option>`)).join("");
  const v = $("#view-memoria");
  v.innerHTML = `<h2>${esc(t("memoria"))}</h2><p class="sub">${esc(t("memoria_dica"))}</p>
    <div class="mem-barra"><input id="mem-q" placeholder="${esc(t("buscar_memoria"))}" value="${esc(S.mem.q)}"><select id="mem-escopo">${opts}</select>
    <button id="mem-esquecer" title="${esc(t("esquecer_dica"))}">🧹 ${esc(t("esquecer_antigos"))}</button></div>
    <div class="mem-barra"><input id="mem-novo" placeholder="${esc(t("novo_fato"))}"><input id="mem-novo-escopo" style="max-width:200px;flex:0 1 200px" placeholder="global / projeto:nome" value="${esc(S.mem.escopo || (S.projetoChat ? "projeto:" + S.projetoChat : "global"))}">
    <button class="prim" id="mem-add">+ ${esc(t("adicionar"))}</button></div>
    <div id="mem-lista">${d.itens.length ? d.itens.map((x) => `<div class="mem-item" data-mem="${x.id}">
      <div class="tx">${x.fixada ? "📌 " : ""}${esc(x.texto)}</div>
      <div class="meta">${marcaHtml(x.marca)}<span class="chip">${esc(x.escopo)}</span><span>${esc(t("tipo_" + x.tipo) !== "tipo_" + x.tipo ? t("tipo_" + x.tipo) : x.tipo)}</span>
      <span>· ${esc(t("usos"))}: ${x.usos}</span>${x.evidencia ? `<span title="${esc(x.evidencia)}">· “${esc(x.evidencia.slice(0, 60))}”</span>` : ""}
      <span class="mem-acoes"><button data-acao="editar">✎</button><button data-acao="fixar">${x.fixada ? esc(t("desafixar")) : "📌"}</button>
      ${x.marca !== "usuario" ? `<button data-acao="confirmar" title="${esc(t("confirmar_dica"))}">✓ ${esc(t("confirmar"))}</button>` : ""}<button data-acao="apagar">🗑</button></span></div></div>`).join("")
      : `<p class="sub">${esc(t("memoria_vazia"))}</p>`}</div>`;
  $("#mem-q").onchange = (e) => { S.mem.q = e.target.value; listarMemoria(); };
  $("#mem-escopo").onchange = (e) => { S.mem.escopo = e.target.value; listarMemoria(); };
  $("#mem-add").onclick = async () => { const tx = $("#mem-novo").value.trim(); if (!tx) return;
    await api("/api/memoria", { method: "POST", body: { texto: tx, escopo: $("#mem-novo-escopo").value.trim() || "global" } }); listarMemoria(); };
  $("#mem-esquecer").onclick = async () => { const r = await api(`/api/memoria/esquecer?escopo=${encodeURIComponent(S.mem.escopo)}`, { method: "POST" });
    alert(t("esquecidos") + ": " + r.apagados.length); listarMemoria(); };
  v.querySelectorAll("[data-acao]").forEach((b) => (b.onclick = async () => {
    const it = b.closest("[data-mem]"), id = it.dataset.mem, x = d.itens.find((y) => String(y.id) === id), a = b.dataset.acao;
    if (a === "apagar") { if (confirm(t("confirmar_apagar_memoria"))) await api(`/api/memoria/${id}`, { method: "DELETE" }); }
    else if (a === "fixar") await api(`/api/memoria/${id}`, { method: "PATCH", body: { fixada: !x.fixada } });
    else if (a === "confirmar") await api(`/api/memoria/${id}`, { method: "PATCH", body: { marca: "usuario" } });
    else if (a === "editar") {
      const tx = it.querySelector(".tx"); tx.textContent = x.texto; tx.contentEditable = "true"; tx.focus();
      b.textContent = "💾"; b.onclick = async () => { await api(`/api/memoria/${id}`, { method: "PATCH", body: { texto: tx.textContent } }); listarMemoria(); };
      return;
    }
    listarMemoria();
  }));
}
async function listarDocumentos() {
  const d = await api("/api/documentos").catch((e) => ({ erro: e.message }));
  const v = $("#view-documentos");
  if (d.erro) { v.innerHTML = `<h2>${esc(t("documentos"))}</h2><div class="avisos">${esc(d.erro)}</div>`; return; }
  const sim = (b, txt) => `<span class="chip ${b ? "ok" : ""}">${b ? "✓" : "—"} ${esc(txt)}</span>`;
  v.innerHTML = `<h2>${esc(t("documentos"))}</h2><p class="sub">${esc(t("documentos_dica"))}</p>
    <div class="recursos">${sim(!!d.ocr, "OCR: " + (d.ocr || t("ocr_ausente")))}${sim(d.tabelas_pdf, t("tabelas_pdf"))}${sim(true, t("busca_hibrida") + (d.status.trechos_com_vetor ? "" : " (" + t("so_bm25") + ")"))}${sim(d.reranker !== "nenhum", "reranker: " + d.reranker)}</div>
    <p class="sub">${d.status.arquivos} ${esc(t("arquivos"))} · ${d.status.trechos} ${esc(t("trechos"))} · ${d.status.trechos_com_vetor} ${esc(t("com_vetor"))}</p>
    <div class="mem-barra"><button class="prim" id="doc-enviar">📎 ${esc(t("anexar_biblioteca"))}</button></div>
    ${d.arquivos.length ? `<table class="tabela-docs"><tr><th>${esc(t("arquivo"))}</th><th>${esc(t("trechos"))}</th><th>${esc(t("tabelas"))}</th><th>OCR</th><th>${esc(t("avisos"))}</th></tr>
    ${d.arquivos.map((a) => `<tr><td title="${esc(a.caminho)}">${esc(a.nome)}</td><td>${a.trechos}</td><td>${a.tabelas}</td><td>${a.paginas_ocr ? a.paginas_ocr + " p." : "—"}</td>
    <td class="av">${esc(a.erro || a.avisos || "")}</td></tr>`).join("")}</table>` : `<p class="sub">${esc(t("nenhum_documento"))}</p>`}`;
  $("#doc-enviar").onclick = () => { $("#arquivo").dataset.dest = "biblioteca"; $("#arquivo").click(); };
}

/* ---------------- v0.6: kits (pixel art e ABNT) ---------------- */
S.kit = { aba: "pixel", imgs: [], nome: "imagem.png", info: null };
const lerB64 = (f) => new Promise((ok, erro) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.onerror = erro; r.readAsDataURL(f); });
async function abrirKits() {
  S.kit.info = await api("/api/kits").catch(() => null);
  const v = $("#view-kits"), k = S.kit.info || { pixel: {}, abnt: {} };
  v.innerHTML = `<h2>🧰 ${esc(t("kits"))}</h2><p class="sub">${esc(t("kits_dica"))}</p>
    <div class="abas"><button data-aba="pixel" class="${S.kit.aba === "pixel" ? "ativa" : ""}">🎨 ${esc(t("kit_pixel"))}</button>
    <button data-aba="abnt" class="${S.kit.aba === "abnt" ? "ativa" : ""}">📚 ${esc(t("kit_abnt"))}</button></div><div id="kit-corpo"></div>`;
  v.querySelectorAll("[data-aba]").forEach((b) => (b.onclick = () => { S.kit.aba = b.dataset.aba; abrirKits(); }));
  if (S.kit.aba === "pixel") kitPixel(k.pixel); else kitAbnt(k.abnt);
}
function toggleKit(nome, ativo) {
  return `<label class="kit-toggle"><input type="checkbox" id="kit-ativo" ${ativo ? "checked" : ""}> ${esc(t("kit_ativar_agente"))}</label>`;
}
function ligarToggle(nome) {
  $("#kit-ativo").onchange = async (e) => { await api("/api/kits", { method: "PUT", body: { [nome]: e.target.checked } }); };
}
function kitPixel(p) {
  const pal = Object.keys(p.paletas || {});
  $("#kit-corpo").innerHTML = `${toggleKit("pixel", p.ativo)}
    <p class="sub">Aseprite: ${p.aseprite ? esc(p.aseprite) : esc(t("aseprite_ausente"))}</p>
    <div class="kit-grade"><div class="kit-caixa">
      <h3>1. ${esc(t("pixel_entrada"))}</h3>
      <div class="soltar" id="px-soltar">${esc(t("pixel_soltar"))}</div><input type="file" id="px-arquivo" accept=".png,.gif,.jpg,.jpeg,.webp,.bmp,.ase,.aseprite" multiple hidden>
      <div class="sub" id="px-nomes" style="margin-top:6px"></div>
      <h3 style="margin-top:14px">2. ${esc(t("acoes_rapidas"))}</h3>
      <div class="acoes-rapidas">
        <button data-r='{"acao":"redimensionar","largura":32}'>128→32</button>
        <button data-r='{"acao":"redimensionar","fator":0.5}'>½</button>
        <button data-r='{"acao":"upscale","fator":4}'>4× upscale</button>
        <button data-r='{"acao":"aplicar_paleta","paleta":"pico-8"}'>PICO-8</button>
        <button data-r='{"acao":"aplicar_paleta","paleta":"db32"}'>DB32</button>
        <button data-r='{"acao":"aplicar_paleta","paleta":"endesga-32"}'>Endesga 32</button>
        <button data-r='{"acao":"aplicar_paleta","paleta":"gameboy"}'>Game Boy</button>
        <button data-r='{"acao":"reduzir_paleta","cores":8}'>8 ${esc(t("cores"))}</button>
        <button data-r='{"acao":"remover_fundo"}'>${esc(t("remover_fundo"))}</button>
        <button data-r='{"acao":"extrair_paleta"}'>${esc(t("extrair_paleta"))}</button>
        <button data-r='{"acao":"montar"}'>${esc(t("montar_sheet"))}</button>
        <button data-r='{"acao":"gif","fator":4}'>GIF</button>
      </div>
      <h3>3. ${esc(t("personalizado"))}</h3>
      <div class="kit-campos">
        <label class="largo">${esc(t("acao"))}<select id="px-acao">${["redimensionar", "upscale", "aplicar_paleta", "reduzir_paleta", "extrair_paleta", "remover_fundo", "preview", "montar", "fatiar", "gif"].map((a) => `<option value="${a}">${esc(t("px_" + a))}</option>`).join("")}</select></label>
        <label>${esc(t("largura_px"))}<input id="px-largura" type="number" min="0" value="0"></label>
        <label>${esc(t("altura_px"))}<input id="px-altura" type="number" min="0" value="0"></label>
        <label>${esc(t("fator"))}<input id="px-fator" type="number" min="0" step="0.25" value="0"></label>
        <label>${esc(t("paleta"))}<select id="px-paleta">${pal.map((n) => `<option ${n === p.paleta_padrao ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></label>
        <label>${esc(t("cores"))}<input id="px-cores" type="number" min="2" max="256" value="16"></label>
        <label>${esc(t("duracao_ms"))}<input id="px-duracao" type="number" min="10" value="100"></label>
        <label class="largo" style="flex-direction:row;align-items:center;gap:6px"><input type="checkbox" id="px-dither"> ${esc(t("dither"))}</label>
      </div>
      <div style="margin-top:10px"><button class="prim-btn" id="px-rodar">▶ ${esc(t("aplicar"))}</button></div>
    </div>
    <div class="kit-caixa"><h3>${esc(t("resultado"))}</h3><div class="kit-resultado" id="px-res"><span class="sub">${esc(t("pixel_sem_resultado"))}</span></div></div></div>`;
  ligarToggle("pixel");
  const alvo = $("#px-soltar"), inp = $("#px-arquivo");
  const carregar = async (fs) => { S.kit.imgs = []; for (const f of fs) S.kit.imgs.push(await lerB64(f)); S.kit.nome = fs[0] ? fs[0].name : "imagem.png";
    $("#px-nomes").textContent = [...fs].map((f) => f.name).join(", "); };
  alvo.onclick = () => inp.click(); inp.onchange = () => carregar(inp.files);
  alvo.ondragover = (e) => { e.preventDefault(); alvo.classList.add("sobre"); }; alvo.ondragleave = () => alvo.classList.remove("sobre");
  alvo.ondrop = (e) => { e.preventDefault(); alvo.classList.remove("sobre"); carregar(e.dataTransfer.files); };
  const rodar = async (pedido) => {
    if (!S.kit.imgs.length) { $("#px-res").innerHTML = `<span class="avisos">${esc(t("pixel_sem_imagem"))}</span>`; return; }
    $("#px-res").innerHTML = `<span class="sub">…</span>`;
    try {
      const r = await api("/api/pixel", { method: "POST", body: { imagens_b64: S.kit.imgs, nome: S.kit.nome, ...pedido } });
      $("#px-res").innerHTML = `<img src="data:${r.mime};base64,${r.imagem_b64}" alt="">
        <div class="sub">${esc(r.arquivo)} ${r.tamanho ? "· " + esc(r.tamanho) : ""} ${r.info ? "· " + esc(r.info) : ""}</div>
        ${r.paleta ? `<div class="paleta-mini">${r.paleta.slice(0, 64).map((c) => `<i style="background:${c}" title="${c}"></i>`).join("")}</div>` : ""}
        <a class="prim-btn" style="text-decoration:none" href="${r.url}" download>⬇ ${esc(t("baixar"))}</a>${r.json ? ` <a href="/api/kits/arquivo/pixel/${encodeURIComponent(r.json)}" download class="sub">${esc(r.json)}</a>` : ""}`;
    } catch (e) { $("#px-res").innerHTML = `<span class="avisos">${esc(e.message)}</span>`; }
  };
  $$("#kit-corpo [data-r]").forEach((b) => (b.onclick = () => rodar(JSON.parse(b.dataset.r))));
  $("#px-rodar").onclick = () => rodar({ acao: $("#px-acao").value, largura: +$("#px-largura").value, altura: +$("#px-altura").value,
    fator: +$("#px-fator").value, paleta: $("#px-paleta").value, cores: +$("#px-cores").value, duracao_ms: +$("#px-duracao").value, dither: $("#px-dither").checked });
}
function kitAbnt(a) {
  $("#kit-corpo").innerHTML = `${toggleKit("abnt", a.ativo)}
    <p class="sub">${esc(t("abnt_normas"))} · NBR 10520:${esc(a.norma_citacao || "2023")} · ${esc(a.fonte || "Times New Roman")} 12</p>
    <div class="kit-grade"><div class="kit-caixa"><h3>📎 ${esc(t("abnt_referencias"))}</h3>
      <textarea id="ab-ids" placeholder="10.1038/nature14539&#10;9788535914849&#10;https://..."></textarea>
      <div style="margin-top:8px"><button class="prim-btn" id="ab-gerar">${esc(t("abnt_gerar_refs"))}</button></div>
      <div id="ab-refs" style="margin-top:8px"></div></div>
    <div class="kit-caixa"><h3>📄 ${esc(t("abnt_documento"))}</h3>
      <div class="kit-campos">
        <label class="largo">${esc(t("titulo"))}<input id="ab-titulo"></label>
        <label>${esc(t("autor"))}<input id="ab-autor" value="${esc(a.autor || "")}"></label>
        <label>${esc(t("instituicao"))}<input id="ab-inst" value="${esc(a.instituicao || "")}"></label>
        <label>${esc(t("local"))}<input id="ab-local" value="${esc(a.local || "")}"></label>
        <label>${esc(t("ano"))}<input id="ab-ano" value="${new Date().getFullYear()}"></label>
        <label class="largo">${esc(t("natureza"))}<input id="ab-natureza" placeholder="${esc(t("natureza_ex"))}"></label>
      </div>
      <textarea id="ab-texto" style="margin-top:8px;min-height:120px" placeholder="# Introdução&#10;Texto com citações (Silva, 2020)…&#10;# Desenvolvimento&#10;…"></textarea>
      <p class="sub">${esc(t("abnt_doc_dica"))}</p>
      <button class="prim-btn" id="ab-doc">⬇ ${esc(t("abnt_gerar_docx"))}</button><div id="ab-doc-res" class="sub" style="margin-top:8px"></div>
    </div></div>`;
  ligarToggle("abnt");
  S.kit.refs = [];
  $("#ab-gerar").onclick = async () => {
    const ids = $("#ab-ids").value.split(/\n+/).map((x) => x.trim()).filter(Boolean);
    if (!ids.length) return;
    $("#ab-refs").innerHTML = `<span class="sub">…</span>`;
    const r = await api("/api/abnt/referencias", { method: "POST", body: { identificadores: ids } }).catch((e) => ({ itens: [], erros: [{ identificador: "", erro: e.message }] }));
    S.kit.refs = r.itens.map((x) => x.dados);
    const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    $("#ab-refs").innerHTML = r.itens.map((x) => `<div class="ref-item">${md(x.referencia)}<div class="kit-cit">${esc(t("citacao"))}: ${esc(x.citacao)} · ${esc(x.narrativa)}
      ${x.avisos.length ? ` · ⚠ ${esc(x.avisos.join("; "))}` : ""} <button class="kit-copiar" title="copiar" data-copiar="${esc(x.referencia.replace(/\*\*/g, ""))}">⧉</button></div></div>`).join("")
      + r.erros.map((e) => `<div class="avisos">${esc(e.identificador)} ${esc(e.erro)}</div>`).join("");
    $$("#ab-refs [data-copiar]").forEach((b) => (b.onclick = () => navigator.clipboard && navigator.clipboard.writeText(b.dataset.copiar)));
  };
  $("#ab-doc").onclick = async () => {
    const titulo = $("#ab-titulo").value.trim(); if (!titulo) { $("#ab-titulo").focus(); return; }
    $("#ab-doc-res").textContent = "…";
    try {
      const r = await api("/api/abnt/documento", { method: "POST", body: { titulo, autor: $("#ab-autor").value, instituicao: $("#ab-inst").value,
        local: $("#ab-local").value, ano: $("#ab-ano").value, natureza: $("#ab-natureza").value, texto: $("#ab-texto").value, referencias_prontas: S.kit.refs || [] } });
      $("#ab-doc-res").innerHTML = `✓ <a href="${r.url}" download>${esc(r.arquivo)}</a> · ${r.referencias} ${esc(t("referencias_n"))}`;
    } catch (e) { $("#ab-doc-res").textContent = e.message; }
  };
}

})();
