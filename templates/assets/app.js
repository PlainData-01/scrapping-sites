/**
 * Prospect Hub v3.1 — SPA comercial
 */
(function () {
  "use strict";

  // ── Constantes ──────────────────────────────────────────────
  const VERSION = "3.2";

  const CRM_LABELS = {
    new: "Novo",
    pendente: "Novo",
    qualified: "Qualificado",
    pronto: "Qualificado",
    contacted: "Abordado",
    abordado: "Abordado",
    responded: "Respondeu",
    interested: "Interessado",
    interessado: "Interessado",
    prototype_requested: "Protótipo solicitado",
    prototype_sent: "Protótipo enviado",
    proposal_sent: "Proposta enviada",
    closed: "Fechado",
    fechado: "Fechado",
    lost: "Perdido",
    perdido: "Perdido",
    discarded: "Descartado",
    descartado: "Descartado",
    follow_up_later: "Chamar depois",
  };

  const MESSAGE_TYPES = [
    { key: "mensagem_curta", label: "Mensagem curta", waKey: "whatsapp_link_curta" },
    { key: "mensagem_consultiva", label: "Mensagem consultiva", waKey: "whatsapp_link_consultiva" },
    { key: "followup_1", label: "Follow-up 1", waKey: null },
    { key: "followup_2", label: "Follow-up 2", waKey: null },
    { key: "resposta_preco", label: "Resposta — preço", waKey: null },
    { key: "resposta_fornecedor", label: "Resposta — fornecedor", waKey: null },
    { key: "resposta_interesse", label: "Resposta — interesse", waKey: null },
  ];

  const BLOCK_KEYS = [
    { key: "novos_para_revisar", label: "Novos" },
    { key: "maior_score", label: "Maior score" },
    { key: "abordados_aguardando", label: "Aguardando" },
    { key: "interessados_pendentes", label: "Interessados" },
    { key: "prototipos_followup", label: "Protótipos" },
    { key: "fechados_periodo", label: "Fechados" },
  ];

  const QUICK_ACTIONS = [
    { acao: "abordado", label: "Abordado", status: "contacted" },
    { acao: "respondeu", label: "Respondeu", status: "responded" },
    { acao: "interessado", label: "Interessado", status: "interested" },
    { acao: "prototipo_enviado", label: "Protótipo enviado", status: "prototype_sent" },
    { acao: "perdido", label: "Perdido", status: "lost" },
    { acao: "descartado", label: "Descartado", status: "discarded" },
  ];

  // ── Estado ──────────────────────────────────────────────────
  const state = {
    view: "dashboard",
    version: VERSION,
    apiBaseUrl: "",
    leads: [],
    icps: [],
    dashboard: null,
    workspaceDomain: null,
    workspaceLead: null,
    wsBusy: false,
    prospectRunning: false,
    prospectPollTimer: null,
    lastProspectLogCount: 0,
    prospectWasRunning: false,
    leadsData: [],
    descartadosData: [],
    activeBlock: "novos_para_revisar",
    sidebarOpen: false,
  };

  // ── Utilitários ─────────────────────────────────────────────
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

  function asList(value) {
    if (Array.isArray(value)) return value;
    if (value && typeof value === "object") {
      const vals = Object.values(value).filter((v) => v != null && String(v).trim());
      return vals.length ? vals : [];
    }
    if (typeof value === "string" && value.trim()) return [value.trim()];
    return [];
  }

  function esc(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function crmLabel(st) {
    return CRM_LABELS[st] || CRM_LABELS[normalizeStatus(st)] || st || "—";
  }

  function normalizeStatus(st) {
    const map = {
      pendente: "new",
      abordado: "contacted",
      interessado: "interested",
      fechado: "closed",
      perdido: "lost",
      descartado: "discarded",
      pronto: "qualified",
    };
    return map[st] || st || "new";
  }

  function extractDomain(url) {
    try {
      return new URL(url.startsWith("http") ? url : `https://${url}`).hostname.replace(/^www\./, "");
    } catch {
      return String(url || "").replace(/^www\./, "");
    }
  }

  function domainSlug(domain) {
    return String(domain || "").replace(/\./g, "_");
  }

  function scoreClass(score) {
    const s = parseInt(score, 10) || 0;
    if (s >= 70) return "high";
    if (s >= 45) return "mid";
    return "low";
  }

  function isWhatsappCompatible(lead) {
    const raw = lead.whatsapp || lead.telefone || "";
    const digits = raw.replace(/\D/g, "");
    if (digits.length >= 13 && digits.startsWith("55")) return digits[4] === "9";
    if (digits.length === 11) return digits[2] === "9";
    return false;
  }

  function formatPhone(raw) {
    if (!raw) return "";
    const digits = raw.replace(/\D/g, "");
    if (digits.length >= 12 && digits.startsWith("55")) {
      const ddd = digits.slice(2, 4);
      const num = digits.slice(4);
      return num.length === 9
        ? `(${ddd}) ${num.slice(0, 5)}-${num.slice(5)}`
        : `(${ddd}) ${num.slice(0, 4)}-${num.slice(4)}`;
    }
    if (digits.length === 11) return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
    if (digits.length === 10) return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
    return raw;
  }

  function formatDate(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
    } catch {
      return iso.slice(0, 16);
    }
  }

  function icpName(id) {
    const icp = state.icps.find((i) => i.id === id);
    return icp ? icp.name : id || "—";
  }

  function getLeadDomain(lead) {
    return lead.domain || extractDomain(lead.website || "");
  }

  function parseLeadLocation(lead) {
    const city = lead.city || "";
    const neighborhood = lead.neighborhood || "";
    if (city || neighborhood) return { city, neighborhood };
    const parts = (lead.endereco || "").split(",").map((p) => p.trim()).filter(Boolean);
    if (parts.length >= 2) return { city: parts[parts.length - 2], neighborhood: parts[parts.length - 1] };
    if (parts.length === 1) return { city: parts[0], neighborhood: "" };
    return { city: "", neighborhood: "" };
  }

  function leadNeedsAction(lead) {
    const st = normalizeStatus(lead.crm_status || "new");
    return ["new", "qualified", "contacted", "responded", "interested", "prototype_sent", "follow_up_later"].includes(st);
  }

  function leadRowClass(lead) {
    const score = parseInt(lead.score, 10) || 0;
    const classes = [];
    if (score >= 70) classes.push("lead-row-hot");
    if (isWhatsappCompatible(lead)) classes.push("lead-row-wa");
    if ((parseInt(lead.total_avaliacoes, 10) || 0) >= 50) classes.push("lead-row-reviews");
    if (lead.main_pain || lead.problema_principal) classes.push("lead-row-pain");
    if (leadNeedsAction(lead)) classes.push("lead-row-action");
    return classes.join(" ");
  }

  function setWsBusy(busy, label = "") {
    state.wsBusy = busy;
    const panel = $("#workspace-panel");
    if (panel) panel.classList.toggle("ws-busy", busy);
    if (busy && label) showToast(label, "info");
  }

  function waLink(telefone, mensagem) {
    const digits = (telefone || "").replace(/\D/g, "");
    if (!digits || !mensagem) return "";
    return `https://wa.me/${digits}?text=${encodeURIComponent(mensagem)}`;
  }

  // ── Toast & status ──────────────────────────────────────────
  function showToast(msg, type = "success") {
    const container = $("#toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("show"));
    setTimeout(() => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  function setStatus(text, cls = "") {
    const badge = $("#status-badge");
    if (!badge) return;
    badge.textContent = text;
    badge.className = "status-badge" + (cls ? ` ${cls}` : "");
  }

  async function copyText(text) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showToast("Copiado!");
    } catch {
      showToast("Não foi possível copiar", "error");
    }
  }

  // ── API ─────────────────────────────────────────────────────
  function apiUrl(path) {
    const base = (state.apiBaseUrl || "").replace(/\/$/, "");
    if (!base || !path.startsWith("/")) return path;
    try {
      if (new URL(base).origin === window.location.origin) return path;
    } catch {
      return path;
    }
    return `${base}${path}`;
  }

  async function api(path, opts = {}) {
    const res = await fetch(apiUrl(path), opts);
    return res.json();
  }

  // ── Navegação ───────────────────────────────────────────────
  function setView(name) {
    state.view = name;
    $$(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === name));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    closeSidebar();
    if (name === "dashboard") loadDashboard();
    if (name === "leads") loadLeads();
    if (name === "diagnoses") loadDiagnoses();
    if (name === "prototypes") loadPrototypes();
    if (name === "config") loadConfig();
    if (name === "prospectar") checkProspectStatus();
  }

  function openSidebar() {
    $("#sidebar")?.classList.add("open");
    $("#sidebar-overlay")?.classList.add("open");
  }

  function closeSidebar() {
    $("#sidebar")?.classList.remove("open");
    $("#sidebar-overlay")?.classList.remove("open");
  }

  // ── Dashboard ───────────────────────────────────────────────
  async function loadDashboard() {
    try {
      const dash = await api("/api/dashboard");
      state.dashboard = dash;
      if (dash.version) state.version = dash.version;
      $("#version-tag").textContent = `v${state.version}`;

      const m = dash.metricas || {};
      $("#m-leads").textContent = m.leads_total ?? 0;
      $("#m-leads-sub").textContent = m.novos_total != null ? `${m.novos_total} novos` : "";
      $("#m-abordados").textContent = m.abordados_total ?? 0;
      $("#m-abordados-sub").textContent = m.abordados_aguardando != null ? `${m.abordados_aguardando} aguardando` : "";
      $("#m-interessados").textContent = m.interessados_total ?? 0;
      $("#m-interessados-sub").textContent = m.interessados_pendentes != null ? `${m.interessados_pendentes} pendentes` : "";
      $("#m-fechados").textContent = m.fechados_total ?? 0;
      $("#m-fechados-sub").textContent = m.prototipos_gerados != null ? `${m.prototipos_gerados} protótipos` : "";

      const alerts = m.alertas_whatsapp || [];
      const alertsEl = $("#dash-alerts");
      if (alerts.length) {
        alertsEl.innerHTML = alerts
          .map((a) => `<div class="alert-box">⚠️ <strong>${esc(a.nome)}</strong> — sem resposta há ${a.horas}h</div>`)
          .join("");
      } else {
        alertsEl.innerHTML = "";
      }

      renderActionQueue(dash.proximas_acoes || []);
      renderBlocks(dash.blocos || {});
      renderSidebarLeads(dash.ultimos_leads || state.leads.slice(0, 5));
    } catch {
      showToast("Erro ao carregar dashboard", "error");
    }
  }

  function renderActionQueue(queue) {
    const el = $("#action-queue");
    if (!el) return;
    if (!queue.length) {
      el.innerHTML = `<div class="empty-state" style="padding:24px">Nenhuma ação pendente.</div>`;
      return;
    }
    el.innerHTML = queue
      .slice(0, 12)
      .map(
        (a) => `
      <div class="action-item" data-domain="${esc(a.domain)}">
        <div class="action-score">${a.score ?? "—"}</div>
        <div class="action-body">
          <div class="action-name">${esc(a.nome || a.domain)}</div>
          <div class="action-desc">${esc(a.action_title)}</div>
        </div>
        <span class="crm-badge ${normalizeStatus(a.status)}">${crmLabel(a.status)}</span>
      </div>`,
      )
      .join("");
    $$(".action-item", el).forEach((item) => {
      item.addEventListener("click", () => openWorkspace(item.dataset.domain));
    });
  }

  function renderBlocks(blocos) {
    const tabsEl = $("#block-tabs");
    const listEl = $("#block-list");
    if (!tabsEl || !listEl) return;

    tabsEl.innerHTML = BLOCK_KEYS.map(
      (b) => {
        const count = (blocos[b.key] || []).length;
        return `<button class="block-tab${state.activeBlock === b.key ? " active" : ""}" data-block="${b.key}">${esc(b.label)} (${count})</button>`;
      },
    ).join("");

    $$(".block-tab", tabsEl).forEach((tab) => {
      tab.addEventListener("click", () => {
        state.activeBlock = tab.dataset.block;
        renderBlocks(blocos);
      });
    });

    const items = blocos[state.activeBlock] || [];
    if (!items.length) {
      listEl.innerHTML = `<div class="empty-state" style="padding:20px">Nenhum lead neste bloco.</div>`;
      return;
    }
    listEl.innerHTML = items
      .map(
        (l) => `
      <div class="block-row" data-domain="${esc(l.domain)}">
        <div>
          <strong>${esc(l.nome || l.domain)}</strong>
          <div class="block-row-meta">${esc(l.acao_sugerida)}</div>
        </div>
        <span class="score-pill ${scoreClass(l.score)}">${l.score ?? "—"}</span>
      </div>`,
      )
      .join("");
    $$(".block-row", listEl).forEach((row) => {
      row.addEventListener("click", () => openWorkspace(row.dataset.domain));
    });
  }

  function renderSidebarLeads(leads) {
    const el = $("#sidebar-leads");
    if (!el) return;
    if (!leads?.length) {
      el.innerHTML = `<div class="mini-lead-empty">Nenhum lead</div>`;
      return;
    }
    el.innerHTML = leads
      .slice(0, 5)
      .map((l) => {
        const dom = getLeadDomain(l);
        const st = normalizeStatus(l.crm_status || "new");
        const name = (l.nome || dom).slice(0, 22);
        return `<div class="mini-lead" data-domain="${esc(dom)}">
          <span class="mini-lead-name">${esc(name)}</span>
          <span class="crm-badge ${st}">${crmLabel(st).slice(0, 8)}</span>
        </div>`;
      })
      .join("");
    $$(".mini-lead", el).forEach((item) => {
      item.addEventListener("click", () => openWorkspace(item.dataset.domain));
    });
  }

  // ── Prospectar ──────────────────────────────────────────────
  function appendProspectLog(line, level) {
    const term = $("#prospect-log-terminal");
    if (!term) return;
    if (term.querySelector(".log-placeholder")) term.innerHTML = "";
    const div = document.createElement("div");
    div.className = "log-line";
    const upper = line.toUpperCase();
    if (level === "error" || upper.includes("ERRO") || line.includes("❌")) div.classList.add("error");
    else if (level === "warning" || line.includes("⚠")) div.classList.add("warning");
    else div.classList.add("info");
    div.textContent = line;
    term.appendChild(div);
    term.scrollTop = term.scrollHeight;
  }

  function setProspectRunning(running) {
    state.prospectRunning = running;
    const btn = $("#btn-prospect");
    if (!btn) return;
    btn.disabled = running;
    btn.textContent = running ? "⏹ Prospectando..." : "🔍 Buscar e Prospectar";
    btn.classList.toggle("running", running);
    $("#prospect-progress")?.classList.toggle("show", running);
    if (!running) setStatus("Pronto", "");
  }

  function updateProspectProgress(atual, total, nome) {
    const pct = total ? Math.round((atual / total) * 100) : 0;
    const fill = $("#prospect-progress-fill");
    if (fill) fill.style.width = `${pct}%`;
    const label = $("#prospect-progress-label");
    if (label) {
      label.textContent = total
        ? `Processando ${atual}/${total}${nome ? ` — ${nome}` : ""}`
        : "Processando...";
    }
  }

  function stopProspectPolling() {
    if (state.prospectPollTimer) {
      clearInterval(state.prospectPollTimer);
      state.prospectPollTimer = null;
    }
  }

  function startProspectPolling() {
    stopProspectPolling();
    pollProspectStatus();
    state.prospectPollTimer = setInterval(pollProspectStatus, 3000);
  }

  async function applyProspectStatus(status, { notify = true } = {}) {
    if (!status || status.status === "idle") return;
    const logs = status.logs || [];
    for (let i = state.lastProspectLogCount; i < logs.length; i++) {
      const entry = logs[i];
      appendProspectLog(typeof entry === "string" ? entry : entry.msg, typeof entry === "string" ? undefined : entry.level);
    }
    state.lastProspectLogCount = logs.length;
    if (status.descartados) state.descartadosData = status.descartados;
    if (status.leads) {
      state.leadsData = status.leads;
      renderProspectLeads();
    }
    if (status.status === "running") {
      state.prospectWasRunning = true;
      setProspectRunning(true);
      setStatus("Prospectando...", "running");
      updateProspectProgress(status.atual || 0, status.total || 0, status.nome_atual);
    }
    if (status.status === "done") {
      stopProspectPolling();
      setProspectRunning(false);
      updateProspectProgress(status.total || 0, status.total || 0, "Concluído");
      setStatus("Concluído", "ok");
      if (notify && state.prospectWasRunning) {
        showToast(`Prospecção concluída — ${status.leads?.length || 0} leads`);
        loadDashboard();
        loadLeads();
      }
      state.prospectWasRunning = false;
    }
    if (status.status === "error") {
      stopProspectPolling();
      setProspectRunning(false);
      setStatus("Erro", "error");
      if (notify && state.prospectWasRunning) showToast(status.erro || "Erro na prospecção", "error");
      state.prospectWasRunning = false;
    }
  }

  async function pollProspectStatus() {
    try {
      const status = await api("/api/prospect/status");
      await applyProspectStatus(status);
    } catch { /* ignore */ }
  }

  async function checkProspectStatus() {
    try {
      const status = await api("/api/prospect/status");
      if (status.status === "running") {
        state.lastProspectLogCount = 0;
        $("#prospect-log-terminal").innerHTML = "";
        state.leadsData = status.leads || [];
        state.descartadosData = status.descartados || [];
        await applyProspectStatus(status, { notify: false });
        startProspectPolling();
      } else if (status.leads?.length) {
        state.leadsData = status.leads;
        state.descartadosData = status.descartados || [];
        renderProspectLeads();
      }
    } catch { /* ignore */ }
  }

  async function runProspect() {
    if (state.prospectRunning) return;
    const query = $("#prospect-query")?.value.trim();
    const cidade = $("#prospect-cidade")?.value.trim();
    const maxLeads = $("#prospect-max")?.value || "20";
    if (!query || !cidade) {
      showToast("Preencha busca e cidade", "error");
      return;
    }

    setProspectRunning(true);
    state.prospectWasRunning = true;
    $("#prospect-log-terminal").innerHTML = "";
    state.lastProspectLogCount = 0;
    state.leadsData = [];
    state.descartadosData = [];
    renderProspectLeads();
    updateProspectProgress(0, parseInt(maxLeads, 10), "");

    const params = new URLSearchParams({ query, cidade, max_leads: maxLeads });
    const icpId = $("#prospect-icp")?.value;
    if (icpId) params.set("icp_id", icpId);

    try {
      const data = await api(`/prospect?${params}`);
      if (!data.ok) {
        setProspectRunning(false);
        showToast(data.error || "Não foi possível iniciar", "error");
        if (data.status) await applyProspectStatus(data.status);
        return;
      }
      appendProspectLog("Prospecção iniciada — acompanhando progresso...");
      startProspectPolling();
    } catch {
      setProspectRunning(false);
      setStatus("Erro", "error");
      showToast("Erro ao iniciar prospecção", "error");
    }
  }

  function renderProspectLeads() {
    const list = $("#prospect-leads-list");
    if (!list) return;
    const leads = state.leadsData || [];
    if (!leads.length) {
      list.innerHTML = `<div class="empty-state">Nenhum lead processado ainda.</div>`;
      return;
    }
    list.innerHTML = leads
      .map((l) => {
        const dom = getLeadDomain(l);
        const score = l.score ?? "—";
        const st = normalizeStatus(l.crm_status || "new");
        return `<div class="lead-card${l.prioridade === "alta" ? " prioridade-alta" : ""}" data-domain="${esc(dom)}">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
            <div>
              <strong>${esc(l.nome || dom)}</strong>
              <div style="font-size:12px;color:var(--text-muted);margin-top:4px">${esc(l.endereco || "")}</div>
            </div>
            <div style="text-align:right">
              <span class="score-pill ${scoreClass(score)}">${score}</span>
              <div style="margin-top:6px"><span class="crm-badge ${st}">${crmLabel(st)}</span></div>
            </div>
          </div>
        </div>`;
      })
      .join("");
    $$(".lead-card", list).forEach((card) => {
      card.addEventListener("click", () => openWorkspace(card.dataset.domain));
    });
  }

  // ── Leads CRM ───────────────────────────────────────────────
  async function loadLeads() {
    try {
      state.leads = await api("/api/leads");
      populateLeadFilters(state.leads);
      renderSidebarLeads(state.leads);
      renderLeadsTable();
    } catch {
      showToast("Erro ao carregar leads", "error");
    }
  }

  function populateLeadFilters(leads) {
    const cities = [...new Set(leads.map((l) => parseLeadLocation(l).city).filter(Boolean))].sort();
    const platforms = [...new Set(leads.map((l) => l.plataforma_detectada || l.plataforma).filter(Boolean))].sort();
    const cityList = $("#crm-city-list");
    if (cityList) cityList.innerHTML = cities.map((c) => `<option value="${esc(c)}"></option>`).join("");
    const platSel = $("#crm-filter-platform");
    if (platSel) {
      const cur = platSel.value;
      platSel.innerHTML = `<option value="">Todas</option>${platforms.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("")}`;
      platSel.value = cur;
    }
  }

  function sortLeads(rows) {
    const sort = $("#crm-sort")?.value || "score_desc";
    const sorted = [...rows];
    switch (sort) {
      case "score_desc":
        sorted.sort((a, b) => (b.score || 0) - (a.score || 0));
        break;
      case "score_asc":
        sorted.sort((a, b) => (a.score || 0) - (b.score || 0));
        break;
      case "nome_asc":
        sorted.sort((a, b) => (a.nome || "").localeCompare(b.nome || "", "pt"));
        break;
      case "nome_desc":
        sorted.sort((a, b) => (b.nome || "").localeCompare(a.nome || "", "pt"));
        break;
      case "status":
        sorted.sort((a, b) => normalizeStatus(a.crm_status).localeCompare(normalizeStatus(b.crm_status), "pt"));
        break;
      case "whatsapp_first":
        sorted.sort((a, b) => {
          const wa = (isWhatsappCompatible(a) ? 0 : 1) - (isWhatsappCompatible(b) ? 0 : 1);
          if (wa !== 0) return wa;
          return (b.score || 0) - (a.score || 0);
        });
        break;
      case "recent_desc":
        sorted.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
        break;
      case "reviews_desc":
        sorted.sort((a, b) => (parseInt(b.total_avaliacoes, 10) || 0) - (parseInt(a.total_avaliacoes, 10) || 0));
        break;
      case "contacted_desc":
        sorted.sort((a, b) => (b.abordado_em || b.last_contacted_at || "").localeCompare(a.abordado_em || a.last_contacted_at || ""));
        break;
      default:
        sorted.sort((a, b) => (b.score || 0) - (a.score || 0));
    }
    return sorted;
  }

  function filterLeads() {
    let rows = state.leads;
    const status = $("#crm-filter-status")?.value;
    const icp = $("#crm-filter-icp")?.value;
    const minScore = parseInt($("#crm-filter-score")?.value, 10);
    const whatsappOnly = $("#crm-filter-whatsapp")?.checked;
    const search = $("#crm-search")?.value.trim().toLowerCase();
    const cityFilter = ($("#crm-filter-city")?.value || "").trim().toLowerCase();
    const neighborhoodFilter = ($("#crm-filter-neighborhood")?.value || "").trim().toLowerCase();
    const platformFilter = $("#crm-filter-platform")?.value || "";

    if (status) rows = rows.filter((l) => normalizeStatus(l.crm_status) === normalizeStatus(status) || l.crm_status === status);
    if (icp) rows = rows.filter((l) => l.icp_id === icp);
    if (!isNaN(minScore) && minScore > 0) rows = rows.filter((l) => (parseInt(l.score, 10) || 0) >= minScore);
    if (whatsappOnly) rows = rows.filter(isWhatsappCompatible);
    if (cityFilter) rows = rows.filter((l) => parseLeadLocation(l).city.toLowerCase().includes(cityFilter));
    if (neighborhoodFilter) rows = rows.filter((l) => parseLeadLocation(l).neighborhood.toLowerCase().includes(neighborhoodFilter));
    if (platformFilter) rows = rows.filter((l) => (l.plataforma_detectada || l.plataforma || "") === platformFilter);
    if (search) {
      rows = rows.filter((l) => {
        const dom = getLeadDomain(l);
        return [l.nome, dom, l.plataforma_detectada, l.main_pain, l.problema_principal, l.website]
          .join(" ")
          .toLowerCase()
          .includes(search);
      });
    }
    return sortLeads(rows);
  }

  function renderLeadsTable() {
    const rows = filterLeads();
    const meta = $("#crm-results-meta");
    if (meta) {
      meta.innerHTML =
        rows.length === state.leads.length
          ? `<strong>${rows.length}</strong> lead${rows.length !== 1 ? "s" : ""}`
          : `<strong>${rows.length}</strong> de ${state.leads.length} leads`;
    }

    const tbody = $("#crm-tbody");
    if (!tbody) return;
    if (!rows.length) {
      const msg = state.leads.length
        ? "Nenhum lead corresponde aos filtros."
        : `Nenhum lead encontrado ainda.<br><small>Escolha um ICP e rode a prospecção para começar.</small>`;
      tbody.innerHTML = `<tr><td colspan="7" class="empty-state">${msg}${!state.leads.length ? '<br><button class="btn btn-primary btn-sm" style="margin-top:12px" id="empty-go-prospect">Ir para Prospectar</button>' : ""}</td></tr>`;
      $("#empty-go-prospect")?.addEventListener("click", () => setView("prospectar"));
      return;
    }

    tbody.innerHTML = rows
      .map((lead) => {
        const dom = getLeadDomain(lead);
        const st = normalizeStatus(lead.crm_status || "new");
        const score = lead.score ?? "—";
        const phone = lead.whatsapp || lead.telefone || "";
        const waBadge = isWhatsappCompatible(lead) ? '<span class="badge-wa">WA</span>' : "";
        const site = lead.website || "";
        const href = site ? (site.startsWith("http") ? site : `https://${site}`) : "";
        const rowCls = leadRowClass(lead);
        return `<tr data-domain="${esc(dom)}" class="${rowCls}">
          <td><strong>${esc(lead.nome || dom)}</strong><br><small style="color:var(--text-muted)">${esc(dom)}</small></td>
          <td><span class="score-pill ${scoreClass(score)}">${score}</span></td>
          <td>${esc(icpName(lead.icp_id))}</td>
          <td>${phone ? esc(formatPhone(phone)) + waBadge : '<span style="color:var(--text-muted)">—</span>'}</td>
          <td>${href ? `<a class="site-link" href="${esc(href)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${esc(extractDomain(site))} ↗</a>` : "—"}</td>
          <td><span class="crm-badge ${st}">${crmLabel(st)}</span></td>
          <td class="lead-quick-actions" onclick="event.stopPropagation()">
            <button class="btn btn-sm btn-secondary" data-lq="ws" data-dom="${esc(dom)}" title="Workspace">📂</button>
            <button class="btn btn-sm btn-secondary" data-lq="copy" data-dom="${esc(dom)}" title="Copiar mensagem">📋</button>
            <button class="btn btn-sm btn-secondary" data-lq="abordado" data-dom="${esc(dom)}" title="Marcar abordado">✓</button>
          </td>
        </tr>`;
      })
      .join("");

    $$("tr[data-domain]", tbody).forEach((tr) => {
      tr.addEventListener("click", () => openWorkspace(tr.dataset.domain));
    });
    $$("[data-lq]", tbody).forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const dom = btn.dataset.dom;
        const lead = state.leads.find((l) => getLeadDomain(l) === dom);
        if (btn.dataset.lq === "ws") openWorkspace(dom);
        else if (btn.dataset.lq === "copy") {
          const pack = lead?.messages_pack || {};
          const text = pack.mensagem_curta || pack.mensagem_whatsapp || lead?.mensagem_whatsapp || "";
          if (text) {
            await copyText(text);
            await logActivity(dom, { type: "message_copied", title: "Mensagem copiada", description: "mensagem_curta" });
          } else showToast("Mensagem não disponível", "warning");
        } else if (btn.dataset.lq === "abordado") {
          await quickAction(dom, "abordado");
        }
      });
    });
  }

  // ── Workspace ───────────────────────────────────────────────
  async function openWorkspace(domain) {
    if (!domain) return;
    state.workspaceDomain = domain;
    $("#workspace-overlay")?.classList.add("open");
    $("#workspace-panel")?.classList.add("open");
    $("#ws-body").innerHTML = `<div class="empty-state">Carregando workspace...</div>`;

    try {
      const lead = await api(`/api/leads/${encodeURIComponent(domain)}`);
      if (lead.error) {
        showToast(lead.error, "error");
        closeWorkspace();
        return;
      }
      state.workspaceLead = lead;
      renderWorkspace(lead);
    } catch (err) {
      console.error("openWorkspace", err);
      showToast("Erro ao carregar lead", "error");
      closeWorkspace();
    }
  }

  function closeWorkspace() {
    state.workspaceDomain = null;
    state.workspaceLead = null;
    $("#workspace-overlay")?.classList.remove("open");
    $("#workspace-panel")?.classList.remove("open");
  }

  function renderWorkspace(lead) {
    const dom = getLeadDomain(lead);
    const st = normalizeStatus(lead.crm_status || "new");
    const score = lead.score ?? lead.opportunity_score ?? "—";
    const loc = parseLeadLocation(lead);
    const nba = lead.next_best_action || {};
    const pack = lead.messages_pack || {};
    const diag = lead.diagnosis || {};
    const proto = lead.prototype || {};
    const quality = proto.quality_report || {};
    const reasons = asList(lead.score_reasons).map((r) => `<li>${esc(r)}</li>`).join("");
    const mapsUrl = lead.google_maps_url || "";
    const phone = lead.telefone || "";
    const wa = lead.whatsapp || phone;

    $("#ws-header-content").innerHTML = `
      <div class="ws-header-top">
        <div>
          <div class="ws-title">${esc(lead.nome || dom)}</div>
          <div class="ws-meta">
            <span class="crm-badge ${st}">${esc(lead.status_label || crmLabel(st))}</span>
            <span>🎯 ${esc(icpName(lead.icp_id))}</span>
          </div>
        </div>
        <div style="text-align:right">
          <div class="ws-score-big">${score}</div>
          <div class="ws-score-label">Score</div>
        </div>
      </div>`;

    const diagBlock = diag.exists
      ? `<div class="production-status ok">✓ Diagnóstico gerado</div>
         <div class="btn-group">
           <a class="btn btn-secondary" href="${esc(apiUrl(diag.html_url || ""))}" target="_blank" rel="noopener">🔗 Abrir diagnóstico</a>
           <button class="btn btn-secondary" id="ws-copy-diag-link" data-url="${esc(apiUrl(diag.html_url || ""))}">📋 Copiar link</button>
         </div>`
      : `<div class="empty-inline">Nenhum diagnóstico gerado para este lead.<br><small>Gere um diagnóstico quando quiser ter argumentos comerciais mais claros.</small></div>
         <button class="btn btn-secondary" id="ws-gen-diagnosis" title="Gera um resumo comercial dos problemas do site">📋 Gerar diagnóstico</button>`;

    const protoBlock = proto.exists
      ? `<div class="production-status ok">✓ Protótipo gerado</div>
         <div class="btn-group">
           <a class="btn btn-secondary" href="${esc(apiUrl(proto.preview_url || ""))}" target="_blank" rel="noopener">👁️ Abrir protótipo</a>
           <button class="btn btn-secondary" id="ws-copy-proto-link" data-url="${esc(apiUrl(proto.preview_url || ""))}">📋 Copiar link</button>
         </div>${renderQualityWarning(quality)}`
      : `<div class="empty-inline">Nenhum protótipo gerado para este lead.<br><small>Gere um protótipo apenas quando houver sinal de interesse.</small></div>
         <button class="btn btn-primary" id="ws-gen-prototype" title="Gera uma landing page inicial para apresentar ao lead">🏗️ Gerar protótipo</button>`;

    $("#ws-body").innerHTML = `
      <div class="ws-section ws-block">
        <div class="section-title">1. Resumo do lead</div>
        <div class="lead-summary-grid">
          <div><span class="lbl">Nicho</span>${esc(lead.categoria || lead.niche || "—")}</div>
          <div><span class="lbl">Cidade</span>${esc(loc.city || "—")}</div>
          <div><span class="lbl">Bairro</span>${esc(loc.neighborhood || "—")}</div>
          <div><span class="lbl">Telefone</span>${phone ? esc(formatPhone(phone)) : "—"}</div>
          <div><span class="lbl">WhatsApp</span>${wa ? esc(formatPhone(wa)) : "—"}</div>
          <div><span class="lbl">Plataforma</span>${esc(lead.plataforma_detectada || "—")}</div>
          <div><span class="lbl">Avaliação</span>${lead.avaliacao ? `⭐ ${lead.avaliacao} (${lead.total_avaliacoes || 0} reviews)` : "—"}</div>
          <div class="span-2"><span class="lbl">Site</span>${lead.website ? `<a href="${esc(lead.website.startsWith("http") ? lead.website : "https://" + lead.website)}" target="_blank" rel="noopener">${esc(lead.website)} ↗</a>` : "—"}</div>
          <div class="span-2"><span class="lbl">Google Maps</span>${mapsUrl ? `<a href="${esc(mapsUrl)}" target="_blank" rel="noopener">Abrir no Maps ↗</a>` : "—"}</div>
        </div>
      </div>

      <div class="ws-section ws-block">
        <div class="section-title">2. Oportunidade</div>
        <p class="opp-intro">Por que vale abordar:</p>
        ${reasons ? `<ul class="why-reasons">${reasons}</ul>` : '<p class="empty-inline">Sem motivos detalhados — revise o score e o site.</p>'}
        <div class="why-grid" style="margin-top:12px">
          <div class="why-item"><div class="why-item-label">Dor principal</div><div class="why-item-value">${esc(lead.main_pain || lead.problema_principal || "—")}</div></div>
          <div class="why-item"><div class="why-item-label">Ângulo comercial</div><div class="why-item-value">${esc(lead.commercial_angle || "—")}</div></div>
          <div class="why-item" style="grid-column:1/-1"><div class="why-item-label">Oferta sugerida</div><div class="why-item-value">${esc(lead.suggested_offer || "—")}</div></div>
        </div>
      </div>

      <div class="ws-section ws-block">
        <div class="section-title">3. Próxima ação</div>
        <div class="ws-nba">
          <p class="nba-status-line"><strong>Status:</strong> ${esc(crmLabel(st))}</p>
          <h3>${esc(nba.title || "Próxima ação")}</h3>
          <p>${esc(nba.description || "")}</p>
          <button class="btn btn-primary" id="ws-nba-primary">${esc(nba.primary_action_label || "Executar")}</button>
        </div>
        <div class="status-quick-row" style="margin-top:14px">
          ${QUICK_ACTIONS.map((a) => `<button class="btn btn-sm btn-secondary" data-quick="${a.acao}" title="${esc(a.label)}">${esc(a.label)}</button>`).join("")}
          <button class="btn btn-sm btn-secondary" data-quick="chamar_depois" title="Marcar para retomada futura">Chamar depois</button>
        </div>
      </div>

      <div class="ws-section ws-block">
        <div class="section-title">4. Mensagens WhatsApp</div>
        <div id="ws-messages">${renderMessages(pack, lead)}</div>
      </div>

      <div class="ws-section ws-block">
        <div class="section-title">5. Produção</div>
        <div class="production-col"><strong>Diagnóstico</strong>${diagBlock}</div>
        <div class="production-col" style="margin-top:16px"><strong>Protótipo</strong>${protoBlock}</div>
      </div>

      <div class="ws-section ws-block">
        <div class="section-title">6. Histórico e notas</div>
        <div class="activity-timeline" id="ws-activities">${renderActivities(lead.atividades || [])}</div>
        <div class="note-list" id="ws-notes" style="margin-top:14px">
          ${(lead.notas || []).length ? (lead.notas || []).map((n) => `<div class="note-item">${esc(typeof n === "string" ? n : n.texto || n.nota)}<small>${formatDate(n.criado_em)}</small></div>`).join("") : '<span class="empty-inline">Sem notas</span>'}
        </div>
        <textarea id="ws-nota-input" rows="2" placeholder="Adicionar nota curta..."></textarea>
        <button class="btn btn-sm btn-primary" id="ws-save-nota" style="margin-top:10px">💾 Salvar nota</button>
      </div>`;

    bindWorkspaceEvents(lead, dom, nba, pack);
  }

  function renderMessages(pack, lead) {
    const telefone = pack.whatsapp_numero || lead.whatsapp || lead.telefone || "";
    return MESSAGE_TYPES.map((mt) => {
      const text = pack[mt.key] || "";
      if (!text) return "";
      const link = pack[mt.waKey] || waLink(telefone, text);
      return `<div class="message-card" data-msg-key="${mt.key}">
        <div class="message-card-header">
          <span class="message-type">${esc(mt.label)}</span>
        </div>
        <div class="message-text">${esc(text)}</div>
        <div class="message-actions">
          <button class="btn btn-sm btn-secondary" data-copy-msg="${mt.key}" title="Copia uma abordagem para WhatsApp">📋 Copiar</button>
          <button class="btn btn-sm btn-secondary" data-copy-abordado="${mt.key}" title="Copia e marca como abordado">📋 Copiar + abordado</button>
          ${link ? `<a class="btn btn-sm btn-secondary wa" href="${esc(link)}" target="_blank" rel="noopener" data-wa-open="${mt.key}" title="Abre conversa manual com o lead">💬 Abrir WA</a>` : ""}
        </div>
      </div>`;
    }).join("") || '<div class="empty-state" style="padding:20px">Mensagens não disponíveis.</div>';
  }

  function renderQualityWarning(quality) {
    if (!quality || !Object.keys(quality).length) return "";
    if (quality.ready_to_send) {
      return `<div class="quality-warning" style="border-color:rgba(16,185,129,0.35);background:var(--success-soft);color:var(--success)">✅ Protótipo pronto para enviar (${quality.passed}/${quality.total} checks)</div>`;
    }
    const failures = quality.critical_failures || [];
    return `<div class="quality-warning">
      ⚠️ ${esc(quality.warning || "Protótipo precisa de revisão antes de enviar.")}
      ${failures.length ? `<ul>${failures.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}
    </div>`;
  }

  function renderActivities(atividades) {
    if (!atividades.length) return '<div class="empty-state" style="padding:16px">Nenhuma atividade registrada.</div>';
    return atividades
      .slice()
      .reverse()
      .map(
        (a) => `<div class="activity-entry">
        <div class="activity-time">${formatDate(a.criado_em || a.timestamp)}</div>
        <div>
          <div class="activity-title">${esc(a.title || a.tipo || a.type || "Atividade")}</div>
          ${a.description || a.nota ? `<div class="activity-desc">${esc(a.description || a.nota)}</div>` : ""}
        </div>
      </div>`,
      )
      .join("");
  }

  function bindWorkspaceEvents(lead, domain, nba, pack) {
    $("#ws-nba-primary")?.addEventListener("click", () => executeNbaAction(nba, pack, lead, domain));

    $$("[data-copy-msg]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const key = btn.dataset.copyMsg;
        await copyText(pack[key] || "");
        await logActivity(domain, { type: "message_copied", title: "Mensagem copiada", description: key });
      });
    });

    $$("[data-copy-abordado]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const key = btn.dataset.copyAbordado;
        await copyText(pack[key] || "");
        await quickAction(domain, "abordado");
        showToast("Copiado e marcado como abordado");
      });
    });

    $$("[data-wa-open]").forEach((link) => {
      link.addEventListener("click", async () => {
        await logActivity(domain, { type: "whatsapp_opened", title: "WhatsApp aberto", description: link.dataset.waOpen });
      });
    });

    $("#ws-copy-diag-link")?.addEventListener("click", () => {
      const u = $("#ws-copy-diag-link")?.dataset.url;
      if (u) copyText(u.startsWith("http") ? u : `${window.location.origin}${u}`);
    });
    $("#ws-copy-proto-link")?.addEventListener("click", () => {
      const u = $("#ws-copy-proto-link")?.dataset.url;
      if (u) copyText(u.startsWith("http") ? u : `${window.location.origin}${u}`);
    });

    $("#ws-gen-diagnosis")?.addEventListener("click", async () => {
      if (state.wsBusy) return;
      setWsBusy(true, "Gerando diagnóstico...");
      const btn = $("#ws-gen-diagnosis");
      if (btn) btn.disabled = true;
      try {
        const data = await api(`/api/leads/${encodeURIComponent(domain)}/diagnosis`, { method: "POST" });
        if (data.ok) {
          showToast("Diagnóstico gerado");
          await openWorkspace(domain);
        } else {
          showToast(data.error || "Não foi possível gerar o diagnóstico. Tente novamente.", "error");
        }
      } finally {
        setWsBusy(false);
        if (btn) btn.disabled = false;
      }
    });

    $("#ws-gen-prototype")?.addEventListener("click", async () => {
      if (state.wsBusy) return;
      setWsBusy(true, "Gerando protótipo...");
      const btn = $("#ws-gen-prototype");
      if (btn) btn.disabled = true;
      try {
        const data = await api(`/api/leads/${encodeURIComponent(domain)}/prototype`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "template" }),
        });
        if (data.ok) {
          showToast("Protótipo gerado");
          await openWorkspace(domain);
        } else {
          showToast(data.error || data.message || "Não foi possível gerar o protótipo. Verifique se o lead tem site.", "error");
        }
      } finally {
        setWsBusy(false);
        if (btn) btn.disabled = false;
      }
    });

    $$("[data-quick]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (state.wsBusy) return;
        setWsBusy(true, "Atualizando status...");
        try {
          await quickAction(domain, btn.dataset.quick);
        } finally {
          setWsBusy(false);
        }
      });
    });

    $("#ws-save-nota")?.addEventListener("click", async () => {
      const texto = $("#ws-nota-input")?.value.trim();
      if (!texto || state.wsBusy) return;
      setWsBusy(true, "Salvando nota...");
      const btn = $("#ws-save-nota");
      if (btn) btn.disabled = true;
      try {
        const data = await api(`/api/leads/${encodeURIComponent(domain)}/nota`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ nota: texto }),
        });
        if (data.ok) {
          showToast("Nota salva");
          await openWorkspace(domain);
        } else showToast(data.error || "Erro ao salvar nota", "error");
      } finally {
        setWsBusy(false);
        if (btn) btn.disabled = false;
      }
    });
  }

  async function executeNbaAction(nba, pack, lead, domain) {
    const type = nba.primary_action_type || "";
    switch (type) {
      case "copy_and_approach":
        await copyText(pack.mensagem_curta || pack.mensagem_whatsapp || "");
        await logActivity(domain, { type: "message_copied", title: "Mensagem copiada", description: "mensagem_curta" });
        await quickAction(domain, "abordado");
        break;
      case "copy_and_approach_consultive":
        await copyText(pack.mensagem_consultiva || "");
        await logActivity(domain, { type: "message_copied", title: "Mensagem copiada", description: "mensagem_consultiva" });
        await quickAction(domain, "abordado");
        break;
      case "copy_short_message":
        await copyText(pack.mensagem_curta || "");
        await logActivity(domain, { type: "message_copied", title: "Mensagem curta copiada", description: "mensagem_curta" });
        break;
      case "copy_consultative_message":
        await copyText(pack.mensagem_consultiva || "");
        await logActivity(domain, { type: "message_copied", title: "Mensagem consultiva copiada", description: "mensagem_consultiva" });
        break;
      case "copy_followup_1":
        await copyText(pack.followup_1 || "");
        await logActivity(domain, { type: "message_copied", title: "Follow-up 1 copiado", description: "followup_1" });
        break;
      case "copy_followup_2":
        await copyText(pack.followup_2 || "");
        await logActivity(domain, { type: "message_copied", title: "Follow-up 2 copiado", description: "followup_2" });
        break;
      case "generate_diagnosis":
        $("#ws-gen-diagnosis")?.click();
        break;
      case "generate_prototype":
        $("#ws-gen-prototype")?.click();
        break;
      case "mark_interested":
        await quickAction(domain, "interessado");
        break;
      case "mark_responded":
        await quickAction(domain, "respondeu");
        break;
      case "mark_proposal_sent":
        await quickAction(domain, "proposta_enviada");
        break;
      case "mark_closed":
        await updateStatus(domain, "closed");
        break;
      case "scroll_messages":
        $("#ws-messages")?.scrollIntoView({ behavior: "smooth" });
        break;
      case "open_site":
        if (lead.website) window.open(lead.website.startsWith("http") ? lead.website : `https://${lead.website}`, "_blank");
        break;
      case "add_note":
        $("#ws-nota-input")?.focus();
        break;
      case "set_status_new":
        await updateStatus(domain, "new");
        break;
      default:
        showToast("Ação não mapeada", "warning");
    }
  }

  async function quickAction(domain, acao) {
    const labels = { abordado: "Abordado", interessado: "Interessado", respondeu: "Respondeu", descartado: "Descartado", chamar_depois: "Chamar depois", proposta_enviada: "Proposta enviada" };
    await api(`/api/leads/${encodeURIComponent(domain)}/activity`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acao }),
    });
    showToast(`Status atualizado: ${labels[acao] || acao}`);
    await loadLeads();
    if (state.workspaceDomain === domain) openWorkspace(domain);
    if (state.view === "dashboard") loadDashboard();
  }

  async function updateStatus(domain, status) {
    const data = await api(`/api/leads/${encodeURIComponent(domain)}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (data.ok) {
      showToast(`Status: ${crmLabel(status)}`);
      await loadLeads();
      if (state.workspaceDomain === domain) openWorkspace(domain);
    } else {
      showToast(data.error || "Erro ao atualizar status", "error");
    }
  }

  async function logActivity(domain, payload) {
    await api(`/api/leads/${encodeURIComponent(domain)}/activity`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  // ── Diagnósticos / Protótipos ───────────────────────────────
  function renderArtifactTable(items, type) {
    const el = type === "diagnosis" ? $("#diagnoses-list") : $("#prototypes-list");
    if (!el) return;
    if (!items.length) {
      el.innerHTML = `<div class="empty-state" style="padding:24px">Nenhum ${type === "diagnosis" ? "diagnóstico" : "protótipo"} gerado ainda.</div>`;
      return;
    }
    el.innerHTML = `<table class="crm-table artifact-table">
      <thead><tr>
        <th>Lead</th><th>Domínio</th><th>ICP</th><th>Score</th><th>Status</th><th>Criado</th><th>Tipo</th><th>Ações</th>
      </tr></thead>
      <tbody>${items.map((item) => {
        const url = type === "diagnosis" ? (item.url_html || item.url_md || "") : (item.url || "");
        const fullUrl = url && item.file_exists !== false ? apiUrl(url) : "";
        const missing = item.file_exists === false;
        const tipo = type === "diagnosis" ? "HTML/MD" : (item.variation || "template");
        return `<tr>
          <td><strong>${esc(item.business_name || item.domain)}</strong></td>
          <td>${esc(item.domain)}</td>
          <td>${esc(icpName(item.icp_id))}</td>
          <td><span class="score-pill ${scoreClass(item.score)}">${item.score ?? "—"}</span></td>
          <td><span class="status-pill">${esc(crmLabel(item.status))}</span></td>
          <td>${formatDate(item.created_at)}</td>
          <td>${esc(tipo)}</td>
          <td class="artifact-actions">
            ${missing ? `<span class="artifact-missing" title="${esc(item.open_error || "")}">⚠️ Arquivo ausente</span>` : ""}
            ${fullUrl ? `<a class="btn btn-sm btn-secondary" href="${esc(fullUrl)}" target="_blank" rel="noopener">Abrir</a>` : ""}
            ${fullUrl ? `<button class="btn btn-sm btn-secondary" data-copy-link="${esc(fullUrl)}">Copiar link</button>` : ""}
            <button class="btn btn-sm btn-primary" data-open-ws="${esc(item.domain)}">Workspace</button>
          </td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
    el.querySelectorAll("[data-copy-link]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const link = btn.dataset.copyLink;
        const abs = link.startsWith("http") ? link : `${window.location.origin}${link}`;
        copyText(abs);
      });
    });
    el.querySelectorAll("[data-open-ws]").forEach((btn) => {
      btn.addEventListener("click", () => openWorkspace(btn.dataset.openWs));
    });
  }

  async function loadDiagnoses() {
    try {
      const items = await api("/api/diagnoses");
      renderArtifactTable(items, "diagnosis");
    } catch {
      showToast("Erro ao carregar diagnósticos", "error");
    }
  }

  async function loadPrototypes() {
    try {
      const items = await api("/api/prototypes");
      renderArtifactTable(items, "prototype");
    } catch {
      showToast("Erro ao carregar protótipos", "error");
    }
  }

  // ── Config ──────────────────────────────────────────────────
  async function loadConfig() {
    try {
      const cfg = await api("/api/config");
      $("#cfg-anthropic").textContent = cfg.anthropic_configured
        ? cfg.anthropic_preview || "••• configurada"
        : "Não configurada";
      $("#cfg-maps").textContent = cfg.maps_configured
        ? cfg.maps_preview || "••• configurada"
        : "Não configurada (Playwright)";
      const ui = cfg.ui || {};
      $("#cfg-delay").value = ui.delay_entre_leads ?? 5;
      $("#cfg-timeout").value = ui.timeout_lead ?? 180;
      $("#cfg-pages").value = ui.paginas_por_lead ?? 8;
      if ($("#cfg-icp") && ui.icp_id) $("#cfg-icp").value = ui.icp_id;
    } catch {
      showToast("Erro ao carregar config", "error");
    }
  }

  async function saveConfig(e) {
    e.preventDefault();
    const body = {
      delay_entre_leads: parseInt($("#cfg-delay").value, 10),
      timeout_lead: parseInt($("#cfg-timeout").value, 10),
      paginas_por_lead: parseInt($("#cfg-pages").value, 10),
      icp_id: $("#cfg-icp")?.value || "odontologia",
    };
    try {
      await api("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      showToast("Configurações salvas");
    } catch {
      showToast("Erro ao salvar", "error");
    }
  }

  // ── ICPs ────────────────────────────────────────────────────
  async function loadIcps() {
    try {
      state.icps = await api("/api/icps");
      const opts = state.icps.map((i) => `<option value="${esc(i.id)}">${esc(i.name)}</option>`).join("");
      if ($("#prospect-icp")) {
        $("#prospect-icp").innerHTML = opts;
        $("#prospect-icp").addEventListener("change", () => {
          const icp = state.icps.find((i) => i.id === $("#prospect-icp").value);
          if (icp?.target_keywords?.[0]) $("#prospect-query").value = icp.target_keywords[0];
          if (icp?.locations?.[0]) $("#prospect-cidade").value = `${icp.locations[0]} DF`;
        });
      }
      if ($("#cfg-icp")) $("#cfg-icp").innerHTML = opts;
      if ($("#crm-filter-icp")) $("#crm-filter-icp").innerHTML = `<option value="">Todos ICPs</option>${opts}`;
    } catch { /* ignore */ }
  }

  // ── Env / init ──────────────────────────────────────────────
  async function loadEnv() {
    try {
      const env = await api("/api/env");
      if (env.version) {
        state.version = env.version;
        $("#version-tag").textContent = `v${env.version}`;
      }
      state.apiBaseUrl = env.api_base_url || "";
    } catch { /* ignore */ }
  }

  function bindEvents() {
    $("#menu-toggle")?.addEventListener("click", () => {
      $("#sidebar")?.classList.contains("open") ? closeSidebar() : openSidebar();
    });
    $("#sidebar-overlay")?.addEventListener("click", closeSidebar);
    $$(".nav-item").forEach((btn) => btn.addEventListener("click", () => setView(btn.dataset.view)));
    $("#btn-go-prospect")?.addEventListener("click", () => setView("prospectar"));
    $("#btn-prospect")?.addEventListener("click", runProspect);
    $("#ws-close")?.addEventListener("click", closeWorkspace);
    $("#workspace-overlay")?.addEventListener("click", closeWorkspace);

    $("#prospect-max")?.addEventListener("input", () => {
      const val = $("#prospect-max-val");
      if (val) val.textContent = $("#prospect-max").value;
    });

    ["#crm-filter-status", "#crm-filter-icp", "#crm-filter-score", "#crm-filter-whatsapp", "#crm-filter-city", "#crm-filter-neighborhood", "#crm-filter-platform", "#crm-sort"].forEach((sel) => {
      $(sel)?.addEventListener("change", renderLeadsTable);
    });
    $("#crm-search")?.addEventListener("input", renderLeadsTable);
    $("#btn-crm-refresh")?.addEventListener("click", loadLeads);
    $("#btn-crm-export")?.addEventListener("click", () => {
      const params = new URLSearchParams();
      const status = $("#crm-filter-status")?.value;
      const icp = $("#crm-filter-icp")?.value;
      const minScore = $("#crm-filter-score")?.value;
      if (status) params.set("status", status);
      if (icp) params.set("icp_id", icp);
      if (minScore) params.set("min_score", minScore);
      window.location.href = apiUrl(`/api/leads/export/csv?${params}`);
    });

    $("#config-form")?.addEventListener("submit", saveConfig);

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (state.workspaceDomain) closeWorkspace();
        else closeSidebar();
        return;
      }
      if (e.target.matches("input, textarea, select") && !e.ctrlKey) return;
      if (e.key === "d" || e.key === "D") setView("dashboard");
      if (e.key === "p" || e.key === "P") setView("prospectar");
      if (e.key === "l" || e.key === "L") setView("leads");
      if (e.key === "c" || e.key === "C") setView("config");
    });
  }

  function init() {
    bindEvents();
    loadEnv();
    loadIcps();
    loadDashboard();
    loadLeads();
    checkProspectStatus();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
