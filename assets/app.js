"use strict";

const state = {
  report: null,
  details: null,
  tab: "staff",
  filter: "all",
  unit: "",
  query: "",
  sort: { key: "f", direction: 1 },
};

const SURVEY = {
  s1: { label: "S1", name: "Основной опрос по процессу" },
  s2: { label: "S2", name: "Доопрос" },
  s3: { label: "S3", name: "Фото рабочего дня" },
};

const QUALITY_LABEL = {
  high: "Высокое",
  medium: "Среднее",
  low: "Низкое",
  unknown: "Нет оценки",
};

const NAME_CHECK_LABEL = {
  exact: "ФИО совпало",
  family: "Совпало по фамилии и имени",
  similarity: "Найдена близкая запись",
  duplicate_exact: "Дубликат ФИО в реестре",
  ambiguous: "Неоднозначное ФИО",
  new: "Нет в исходном реестре",
  not_in_source: "Нет сессий для проверки",
};

const byId = (id) => document.getElementById(id);
const formatNumber = (value) => new Intl.NumberFormat("ru-RU").format(value || 0);
const percent = (value) => value == null ? "—" : `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value)}%`;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Yekaterinburg",
  }).format(date);
}

function normalizeName(value) {
  return String(value || "")
    .toLocaleLowerCase("ru-RU")
    .replaceAll("ё", "е")
    .replace(/[^а-яa-z0-9]+/gi, " ")
    .trim();
}

function isTovar(person) {
  return person.o === "Товароведы" || /товаровед/i.test(person.d || "") || /скупщик/i.test(person.d || "");
}

function nameIssue(person) {
  if (!state.report) return false;
  const audit = state.report.fio_audit;
  const duplicateNames = new Set(audit.duplicate_full_names_in_roster || []);
  return person.name_check !== "exact" || duplicateNames.has(normalizeName(person.f));
}

function deduplicateExact(people) {
  const result = new Map();
  for (const person of people) {
    const key = normalizeName(person.f);
    const current = result.get(key);
    if (!current || person.vs > current.vs || (person.vs === current.vs && String(person.f).length > String(current.f).length)) {
      result.set(key, person);
    }
  }
  return [...result.values()];
}

function basePeople() {
  const included = state.report.people.filter((person) => !person.excluded_reason);
  return deduplicateExact(included);
}

function rowsForTab(tab = state.tab) {
  return basePeople().filter((person) => tab === "tovar" ? isTovar(person) : !isTovar(person));
}

function qualityClass(person) {
  if (!person.vs) return "unknown";
  const value = person.quality.average;
  if (value == null) return "unknown";
  if (value >= 75) return "high";
  if (value >= 50) return "medium";
  return "low";
}

function renderKpis() {
  const rows = rowsForTab();
  const passed = rows.filter((person) => person.vs > 0);
  const sessions = rows.reduce((sum, person) => sum + person.vs, 0);
  const scored = passed.filter((person) => person.quality.average != null);
  const average = scored.length ? scored.reduce((sum, person) => sum + person.quality.average, 0) / scored.length : null;
  const issues = rows.filter(nameIssue).length;
  const cards = [
    ["В реестре", formatNumber(rows.length), `${state.tab === "tovar" ? "товароведов и скупщиков" : "сотрудников"}`],
    ["Прошли хотя бы один", formatNumber(passed.length), `${rows.length ? percent(passed.length / rows.length * 100) : "—"} охвата`],
    ["Завершённых сессий", formatNumber(sessions), `S1 + S2 + S3`],
    ["Среднее качество", percent(average), `${formatNumber(issues)} ФИО требуют внимания`],
  ];
  byId("kpis").innerHTML = cards.map(([label, value, note]) => `
    <article class="kpi">
      <span class="kpi-label">${escapeHtml(label)}</span>
      <strong class="kpi-value">${escapeHtml(value)}</strong>
      <span class="kpi-note">${escapeHtml(note)}</span>
    </article>
  `).join("");
}

function renderScenarioCards() {
  const rows = rowsForTab();
  byId("scenarioCards").innerHTML = Object.entries(state.report.scenarios).map(([key, scenario]) => {
    const completed = rows.filter((person) => person[key] > 0).length;
    const coverage = rows.length ? completed / rows.length * 100 : 0;
    return `
      <article class="scenario-card">
        <div class="scenario-top">
          <span class="scenario-tag">${escapeHtml(scenario.tag)}</span>
          <strong class="scenario-score">${percent(scenario.quality.average)}</strong>
        </div>
        <h3>${escapeHtml(scenario.name)}</h3>
        <p>${escapeHtml(scenario.metric)} · ${formatNumber(scenario.sessions)} сессий всего</p>
        <div class="progress"><span style="width:${Math.min(100, coverage)}%"></span></div>
        <div class="scenario-meta"><span>${formatNumber(completed)} из ${formatNumber(rows.length)}</span><span>охват ${percent(coverage)}</span></div>
      </article>
    `;
  }).join("");
}

function renderQualityChart() {
  byId("qualityChart").innerHTML = Object.entries(state.report.scenarios).map(([key, scenario]) => {
    const quality = scenario.quality;
    const total = quality.high + quality.medium + quality.low + quality.unknown || 1;
    return `
      <div class="chart-row">
        <span>${escapeHtml(SURVEY[key].name)}</span>
        <div class="quality-stack" title="Высокое: ${quality.high}; среднее: ${quality.medium}; низкое: ${quality.low}">
          <span class="high" style="width:${quality.high / total * 100}%"></span>
          <span class="medium" style="width:${quality.medium / total * 100}%"></span>
          <span class="low" style="width:${quality.low / total * 100}%"></span>
        </div>
        <span class="chart-value">${percent(quality.average)}</span>
      </div>
    `;
  }).join("");
}

function renderFioSummary() {
  const audit = state.report.fio_audit;
  const values = [
    [audit.issue_count, "критичных сигналов"],
    [(audit.bitrix_ids_with_name_variants || []).length, "ID со сменой ФИО"],
    [(audit.duplicate_full_names_in_roster || []).length, "дубликатов в реестре"],
    [(audit.short_names_in_roster || []).length, "неполных ФИО"],
  ];
  byId("fioSummary").innerHTML = values.map(([value, label]) => `
    <div class="fio-stat"><strong>${formatNumber(value)}</strong><span>${escapeHtml(label)}</span></div>
  `).join("");
}

function populateUnits() {
  const select = byId("selUnit");
  const units = [...new Set(rowsForTab().map((person) => person.u).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru"));
  select.innerHTML = `<option value="">Все управления</option>${units.map((unit) => `<option value="${escapeHtml(unit)}">${escapeHtml(unit)}</option>`).join("")}`;
  select.value = units.includes(state.unit) ? state.unit : "";
  state.unit = select.value;
}

function filteredRows() {
  const query = state.query.toLocaleLowerCase("ru-RU");
  return rowsForTab().filter((person) => {
    if (state.filter === "pass" && person.vs <= 0) return false;
    if (state.filter === "none" && person.vs > 0) return false;
    if (state.filter === "low" && !(person.vs > 0 && qualityClass(person) === "low")) return false;
    if (state.filter === "fio" && !nameIssue(person)) return false;
    if (state.unit && person.u !== state.unit) return false;
    if (query && !`${person.f} ${person.d} ${person.o} ${person.u}`.toLocaleLowerCase("ru-RU").includes(query)) return false;
    return true;
  });
}

function sortRows(rows) {
  const { key, direction } = state.sort;
  return [...rows].sort((left, right) => {
    let a = key === "quality" ? left.quality.average ?? -1 : left[key] ?? "";
    let b = key === "quality" ? right.quality.average ?? -1 : right[key] ?? "";
    if (typeof a === "number" && typeof b === "number") return (a - b) * direction;
    return String(a).localeCompare(String(b), "ru", { numeric: true }) * direction;
  });
}

function scenarioMark(value, key) {
  const label = value ? `✓${value > 1 ? ` ×${value}` : ""}` : "—";
  return `<span class="scenario-mark ${value ? "done" : "off"}" title="${escapeHtml(SURVEY[key].name)}">${label}</span>`;
}

function qualityPill(person) {
  const kind = qualityClass(person);
  return `<span class="quality-pill ${kind}">${QUALITY_LABEL[kind]} · ${percent(person.quality.average)}</span>`;
}

function renderRoster() {
  const all = rowsForTab();
  const rows = sortRows(filteredRows());
  byId("rosterBody").innerHTML = rows.map((person) => {
    const issue = nameIssue(person);
    return `
      <tr>
        <td>
          <div class="person-name">${escapeHtml(person.f)}</div>
          <div class="person-sub">${issue ? `<span class="name-pill issue">${escapeHtml(NAME_CHECK_LABEL[person.name_check] || "Проверить ФИО")}</span>` : "ФИО проверено"}</div>
        </td>
        <td>${escapeHtml(person.u || "—")}<div class="person-sub">${escapeHtml(person.o || "—")}</div></td>
        <td>${escapeHtml(person.d || "—")}</td>
        <td class="center">${scenarioMark(person.s1, "s1")}</td>
        <td class="center">${scenarioMark(person.s2, "s2")}</td>
        <td class="center">${scenarioMark(person.s3, "s3")}</td>
        <td>${qualityPill(person)}</td>
        <td>${formatDate(person.last)}</td>
        <td>${person.vs ? `<button class="details-button" type="button" data-person="${escapeHtml(person.key)}">Ответы</button>` : ""}</td>
      </tr>
    `;
  }).join("");
  byId("rosterCount").innerHTML = `показано <strong>${formatNumber(rows.length)}</strong> из ${formatNumber(all.length)}`;
}

function renderCoverage() {
  const groups = new Map();
  for (const person of rowsForTab()) {
    const key = person.u || "Не указано";
    const value = groups.get(key) || { total: 0, passed: 0, sessions: 0 };
    value.total += 1;
    value.passed += person.vs > 0 ? 1 : 0;
    value.sessions += person.vs;
    groups.set(key, value);
  }
  const rows = [...groups.entries()].sort((a, b) => (b[1].passed / b[1].total) - (a[1].passed / a[1].total));
  byId("covView").innerHTML = rows.map(([name, value]) => {
    const coverage = value.total ? value.passed / value.total * 100 : 0;
    return `
      <div class="coverage-row">
        <span>${escapeHtml(name)}</span>
        <div class="coverage-bar"><span style="width:${coverage}%"></span></div>
        <strong>${percent(coverage)}</strong>
      </div>
    `;
  }).join("");
}

function applyView() {
  const coverage = state.filter === "cov";
  byId("rosterScroll").classList.toggle("hidden", coverage);
  byId("covView").classList.toggle("hidden", !coverage);
  byId("selUnit").classList.toggle("hidden", coverage);
  byId("search").closest("label").classList.toggle("hidden", coverage);
  if (coverage) renderCoverage(); else renderRoster();
}

function renderBoard() {
  renderKpis();
  renderScenarioCards();
  populateUnits();
  applyView();
}

function openDrawer(title, eyebrow, content) {
  byId("drawerTitle").textContent = title;
  byId("drawerEyebrow").textContent = eyebrow;
  byId("drawerBody").innerHTML = content;
  byId("drawer").classList.remove("hidden");
  byId("drawerBackdrop").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  byId("closeDrawer").focus();
}

function closeDrawer() {
  byId("drawer").classList.add("hidden");
  byId("drawerBackdrop").classList.add("hidden");
  document.body.style.overflow = "";
}

function metricLabel(key) {
  const labels = {
    confidence: "Confidence",
    document_status: "Статус",
    asked: "Задано",
    closed: "Закрыто",
    closed_soft: "Закрыто soft",
    partial: "Частично",
    reassigned: "Переадресовано",
    open: "Открыто",
    grounded: "Обосновано",
    completeness: "Полнота",
    workload_assessed: "Загрузка оценена",
  };
  return labels[key] || key;
}

async function loadDetails() {
  if (state.details) return state.details;
  const response = await fetch("data/details.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`Не удалось загрузить ответы: HTTP ${response.status}`);
  state.details = await response.json();
  return state.details;
}

async function showPerson(personKey) {
  openDrawer("Загрузка…", "Ответы сотрудника", `<p class="muted">Получаем детали ответов…</p>`);
  try {
    const details = await loadDetails();
    const person = details.people[personKey];
    if (!person) throw new Error("Для сотрудника не найдены детали сессий");
    const cards = person.sessions.map((session) => {
      const metrics = Object.entries(session.metrics || {}).map(([key, value]) => `<span class="metric">${escapeHtml(metricLabel(key))}: ${escapeHtml(value ?? "—")}</span>`).join("");
      const answers = (session.answers || []).map(([topic, answer, status]) => `
        <div class="answer">
          <strong>${escapeHtml(topic || "Фрагмент ответа")}</strong>
          <p>${escapeHtml(answer || "—")}</p>
          <small>${escapeHtml(status || "")}</small>
        </div>
      `).join("") || `<p class="muted">Структурированные фрагменты не извлечены; метрики сессии показаны выше.</p>`;
      return `
        <article class="detail-card">
          <span class="quality-pill ${escapeHtml(session.quality)}">${escapeHtml(SURVEY[session.scenario]?.label || session.scenario)} · ${percent(session.score)}</span>
          <h3>${escapeHtml(session.title || SURVEY[session.scenario]?.name || "Сессия")}</h3>
          <div class="person-sub">${formatDate(session.created_at)} · ${escapeHtml(session.session_id)}</div>
          <div class="metric-list">${metrics}</div>
          ${answers}
        </article>
      `;
    }).join("");
    openDrawer(person.name, `${formatNumber(person.sessions.length)} сессий · точные фрагменты ответов`, cards);
  } catch (error) {
    openDrawer("Ошибка загрузки", "Ответы сотрудника", `<div class="notice error">${escapeHtml(error.message)}</div>`);
  }
}

function showMethod() {
  const method = state.report.quality_method;
  openDrawer("Как считается качество", "Прозрачная формула", `
    <article class="detail-card">
      <h3>S1 · Основной опрос</h3><p>${escapeHtml(method.s1)}</p>
      <h3>S2 · Доопрос</h3><p>${escapeHtml(method.s2)}</p>
      <h3>S3 · Фото рабочего дня</h3><p>${escapeHtml(method.s3)}</p>
    </article>
    <article class="detail-card">
      <h3>Пороговые уровни</h3>
      <p><span class="quality-pill high">Высокое ${escapeHtml(method.high)}</span> <span class="quality-pill medium">Среднее ${escapeHtml(method.medium)}</span> <span class="quality-pill low">Низкое ${escapeHtml(method.low)}</span></p>
      <p class="muted">${escapeHtml(method.warning)}</p>
    </article>
  `);
}

function auditSection(title, items, formatter = (item) => item) {
  if (!items?.length) return `<article class="detail-card"><h3>${escapeHtml(title)}</h3><p class="muted">Проблем не найдено.</p></article>`;
  return `<article class="detail-card"><h3>${escapeHtml(title)} · ${formatNumber(items.length)}</h3><ul class="audit-list">${items.slice(0, 80).map((item) => `<li>${escapeHtml(formatter(item))}</li>`).join("")}</ul>${items.length > 80 ? `<p class="muted">Показаны первые 80 записей.</p>` : ""}</article>`;
}

function showFioAudit() {
  const audit = state.report.fio_audit;
  const content = [
    auditSection("Один Bitrix ID — разные ФИО", audit.bitrix_ids_with_name_variants, (item) => `ID ${item.person_id}: ${item.names.join(" ↔ ")}`),
    auditSection("Одно ФИО — разные Bitrix ID", audit.names_with_multiple_bitrix_ids, (item) => `${item.name}: ID ${item.person_ids.join(", ")}`),
    auditSection("Дубликаты полного ФИО в реестре", audit.duplicate_full_names_in_roster),
    auditSection("Неполные ФИО", audit.short_names_in_roster),
    auditSection("Неоднозначно сопоставленные", audit.ambiguous_people),
  ].join("");
  openDrawer("Аудит ФИО", `${formatNumber(audit.issue_count)} критичных сигналов`, content);
}

function bindEvents() {
  byId("tabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-tab]");
    if (!button) return;
    state.tab = button.dataset.tab;
    state.filter = "all";
    state.unit = "";
    state.query = "";
    byId("search").value = "";
    document.querySelectorAll("#tabs button").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll("#segFilter button").forEach((item) => item.classList.toggle("active", item.dataset.f === "all"));
    renderBoard();
  });
  byId("segFilter").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-f]");
    if (!button) return;
    state.filter = button.dataset.f;
    document.querySelectorAll("#segFilter button").forEach((item) => item.classList.toggle("active", item === button));
    applyView();
  });
  byId("selUnit").addEventListener("change", (event) => { state.unit = event.target.value; renderRoster(); });
  byId("search").addEventListener("input", (event) => { state.query = event.target.value.trim(); renderRoster(); });
  byId("rosterT").addEventListener("click", (event) => {
    const details = event.target.closest("button[data-person]");
    if (details) { showPerson(details.dataset.person); return; }
    const heading = event.target.closest("th[data-k]");
    if (!heading) return;
    state.sort = state.sort.key === heading.dataset.k ? { key: heading.dataset.k, direction: state.sort.direction * -1 } : { key: heading.dataset.k, direction: 1 };
    renderRoster();
  });
  byId("showMethod").addEventListener("click", showMethod);
  byId("showFio").addEventListener("click", showFioAudit);
  byId("closeDrawer").addEventListener("click", closeDrawer);
  byId("drawerBackdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
}

async function start() {
  try {
    const response = await fetch("data/report.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Не удалось загрузить отчёт: HTTP ${response.status}`);
    state.report = await response.json();
    if (state.report.schema_version !== 2 || !Array.isArray(state.report.people)) throw new Error("Неверная версия данных отчёта");
    byId("snapshot").textContent = state.report.snapshot;
    byId("sourceHealth").textContent = `${formatNumber(state.report.summary.sessions)} сессий · JSON v${state.report.schema_version}`;
    const staff = rowsForTab("staff").length;
    const tovar = rowsForTab("tovar").length;
    byId("cntStaff").textContent = formatNumber(staff);
    byId("cntTovar").textContent = formatNumber(tovar);
    renderQualityChart();
    renderFioSummary();
    renderBoard();
    byId("foot").textContent = `Read-only источник KB-ARM-survey · ${state.report.snapshot} · исключено из свода: ${formatNumber(state.report.summary.excluded_people)} · детали ответов загружаются только по запросу.`;
    bindEvents();
  } catch (error) {
    byId("loadError").textContent = `${error.message}. Откройте сайт через GitHub Pages или локальный HTTP-сервер.`;
    byId("loadError").classList.remove("hidden");
    byId("sourceHealth").textContent = "Ошибка загрузки";
  }
}

start();
