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
  s1: { label: "Основной опрос", name: "Основной опрос по процессу" },
  s2: { label: "Доопрос", name: "Доопрос" },
  s3: { label: "Фото рабочего дня", name: "Фото рабочего дня" },
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
    const conducted = person.conducted_sessions ?? ((person.vs || 0) + (person.partial_sessions || 0));
    const currentConducted = current?.conducted_sessions ?? ((current?.vs || 0) + (current?.partial_sessions || 0));
    if (!current || conducted > currentConducted || (conducted === currentConducted && person.vs > current.vs) || (conducted === currentConducted && person.vs === current.vs && String(person.f).length > String(current.f).length)) {
      result.set(key, person);
    }
  }
  return [...result.values()];
}

function conductedCount(person) {
  return person.conducted_sessions ?? ((person.vs || 0) + (person.partial_sessions || 0));
}

function hasConductedSurvey(person) {
  return conductedCount(person) > 0;
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

function sessionCounts(rows) {
  const completed = rows.reduce((sum, person) => sum + (person.vs || 0), 0);
  const partial = rows.reduce((sum, person) => sum + (person.partial_sessions || 0), 0);
  return { completed, partial, total: completed + partial };
}

function aggregateScenarioQuality(rows, scenarioKey) {
  const result = { average: null, high: 0, medium: 0, low: 0, unknown: 0 };
  let weightedScore = 0;
  let scored = 0;
  for (const person of rows) {
    const quality = person.scenario_quality?.[scenarioKey];
    if (!quality) continue;
    result.high += quality.high || 0;
    result.medium += quality.medium || 0;
    result.low += quality.low || 0;
    result.unknown += quality.unknown || 0;
    const personScored = (quality.high || 0) + (quality.medium || 0) + (quality.low || 0);
    if (quality.average != null && personScored) {
      weightedScore += quality.average * personScored;
      scored += personScored;
    }
  }
  result.average = scored ? Math.round(weightedScore / scored * 10) / 10 : null;
  return result;
}

function filterCounts(rows) {
  return {
    all: rows.length,
    none: rows.filter((person) => !hasConductedSurvey(person)).length,
    pass: rows.filter(hasConductedSurvey).length,
    low: rows.filter((person) => person.vs > 0 && qualityClass(person) === "low").length,
    partial: rows.filter((person) => (person.partial_sessions || 0) > 0).length,
    fio: rows.filter(nameIssue).length,
  };
}

function renderFilterCounts() {
  const rows = rowsForTab();
  const counts = filterCounts(rows);
  const labels = {
    all: "Все",
    none: "Не прошли",
    pass: "Прошли",
    low: "Низкое качество",
    partial: "Требуется уточнение",
    fio: "Проверить ФИО",
    cov: "Охват",
  };
  for (const button of document.querySelectorAll("#segFilter button[data-f]")) {
    const key = button.dataset.f;
    const value = key === "cov" ? `${counts.pass}/${counts.all}` : counts[key];
    button.innerHTML = `${escapeHtml(labels[key])}<span class="filter-count">${escapeHtml(value)}</span>`;
    if (key === "partial") {
      button.title = `${formatNumber(sessionCounts(rows).partial)} опросов требуют уточнения у ${formatNumber(counts.partial)} человек`;
    }
  }
}

function renderSessionLogic() {
  const currentRows = rowsForTab();
  const current = sessionCounts(currentRows);
  const staff = sessionCounts(rowsForTab("staff"));
  const tovar = sessionCounts(rowsForTab("tovar"));
  const overall = state.report.summary;
  const groupName = state.tab === "tovar" ? "Товароведы и скупщики" : "Сотрудники";
  byId("sessionLogic").innerHTML = `
    <div class="session-logic-summary">
      <div><span>${escapeHtml(groupName)}</span><strong>${formatNumber(current.total)} опросов проведено</strong><small>${formatNumber(current.partial)} требуют уточнения</small></div>
      <div><span>Весь дашборд</span><strong>${formatNumber(overall.conducted_sessions)} опросов проведено</strong><small>${formatNumber(overall.partial_sessions)} требуют уточнения (${formatNumber(staff.partial)} + ${formatNumber(tovar.partial)})</small></div>
    </div>
    <p><strong>Логика:</strong> каждый сохранённый опрос считается проведённым и входит в охват. Метка «требуется уточнение» означает, что часть вопросов осталась открытой, частичной или переадресованной. Такие опросы показаны отдельно и пока не входят в среднюю оценку качества.</p>
  `;
}

function renderKpis() {
  const rows = rowsForTab();
  const passed = rows.filter(hasConductedSurvey);
  const sessions = rows.reduce((sum, person) => sum + person.vs, 0);
  const partialSessions = rows.reduce((sum, person) => sum + (person.partial_sessions || 0), 0);
  const scored = passed.filter((person) => person.quality.average != null);
  const average = scored.length ? scored.reduce((sum, person) => sum + person.quality.average, 0) / scored.length : null;
  const issues = rows.filter(nameIssue).length;
  const cards = [
    ["В реестре", formatNumber(rows.length), `${state.tab === "tovar" ? "товароведов и скупщиков" : "сотрудников"}`],
    ["Опрос проведён", formatNumber(passed.length), `${rows.length ? percent(passed.length / rows.length * 100) : "—"} охвата`],
    ["Проведено опросов", formatNumber(sessions + partialSessions), `${formatNumber(partialSessions)} требуют уточнения`],
    ["Среднее качество", percent(average), `по опросам без отметки уточнения · ${formatNumber(issues)} ФИО требуют внимания`],
  ];
  byId("kpis").innerHTML = cards.map(([label, value, note]) => `
    <article class="kpi">
      <span class="kpi-label">${escapeHtml(label)}</span>
      <strong class="kpi-value">${escapeHtml(value)}</strong>
      <span class="kpi-note">${escapeHtml(note)}</span>
    </article>
  `).join("");
}

function renderScenarioScope() {
  const rows = rowsForTab();
  const sessions = sessionCounts(rows);
  const groupName = state.tab === "tovar" ? "Товароведы и скупщики" : "Сотрудники";
  byId("scenarioScope").textContent = `Выбранная группа: ${groupName} · охват включает ${formatNumber(sessions.total)} проведённых опросов; качество рассчитано по ${formatNumber(sessions.completed)} опросам без отметки уточнения`;
}

function renderScenarioCards() {
  const rows = rowsForTab();
  byId("scenarioCards").innerHTML = Object.entries(state.report.scenarios).map(([key, scenario]) => {
    const completed = rows.filter((person) => person[key] > 0 || (key === "s2" && (person.partial_sessions || 0) > 0)).length;
    const completedSessions = rows.reduce((sum, person) => sum + (person[key] || 0), 0);
    const partialSessions = key === "s2" ? sessionCounts(rows).partial : 0;
    const quality = aggregateScenarioQuality(rows, key);
    const coverage = rows.length ? completed / rows.length * 100 : 0;
    return `
      <article class="scenario-card">
        <div class="scenario-top">
          <span class="scenario-tag">${escapeHtml(scenario.tag)}</span>
          <strong class="scenario-score">${percent(quality.average)}</strong>
        </div>
        <h3>${escapeHtml(scenario.name)}</h3>
        <p>${escapeHtml(scenario.metric)} · ${formatNumber(completedSessions + partialSessions)} опросов проведено${partialSessions ? ` · ${formatNumber(partialSessions)} требуют уточнения` : ""}</p>
        <div class="progress"><span style="width:${Math.min(100, coverage)}%"></span></div>
        <div class="scenario-meta"><span>${formatNumber(completed)} из ${formatNumber(rows.length)}</span><span>охват ${percent(coverage)}</span></div>
      </article>
    `;
  }).join("");
}

function renderQualityChart() {
  const rows = rowsForTab();
  byId("qualityChart").innerHTML = Object.entries(state.report.scenarios).map(([key]) => {
    const quality = aggregateScenarioQuality(rows, key);
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
    if (state.filter === "pass" && !hasConductedSurvey(person)) return false;
    if (state.filter === "none" && hasConductedSurvey(person)) return false;
    if (state.filter === "low" && !(person.vs > 0 && qualityClass(person) === "low")) return false;
    if (state.filter === "partial" && !(person.partial_sessions > 0)) return false;
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

function scenarioMark(value, key, partial = 0) {
  const label = value ? `✓${value > 1 ? ` ×${value}` : ""}${partial ? ` · ~${partial}` : ""}` : partial ? `~${partial}` : "—";
  const kind = value ? "done" : partial ? "partial" : "off";
  const note = partial ? `; требуют уточнения: ${partial}` : "";
  return `<span class="scenario-mark ${kind}" title="${escapeHtml(SURVEY[key].name)}${escapeHtml(note)}">${label}</span>`;
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
        <td class="center">${scenarioMark(person.s2, "s2", person.partial_sessions || 0)}</td>
        <td class="center">${scenarioMark(person.s3, "s3")}</td>
        <td>${qualityPill(person)}</td>
        <td>${formatDate(person.last)}</td>
        <td>${person.vs || person.partial_sessions ? `<button class="details-button" type="button" data-person="${escapeHtml(person.key)}">Ответы</button>` : ""}</td>
      </tr>
    `;
  }).join("");
  const sessions = sessionCounts(rows);
  byId("rosterCount").innerHTML = `показано <strong>${formatNumber(rows.length)}</strong> из ${formatNumber(all.length)} человек · ${formatNumber(sessions.total)} опросов проведено · ${formatNumber(sessions.partial)} требуют уточнения`;
}

function sourceFileName(value) {
  const parts = String(value || "").split(/[\\/]/).filter(Boolean);
  return parts.at(-1) || "Имя файла не указано";
}

function renderCoverage() {
  const groups = new Map();
  const people = rowsForTab();
  for (const person of people) {
    const key = person.u || "Не указано";
    const value = groups.get(key) || { total: 0, passed: 0, completed: 0, partial: 0 };
    value.total += 1;
    value.passed += hasConductedSurvey(person) ? 1 : 0;
    value.completed += person.vs || 0;
    value.partial += person.partial_sessions || 0;
    groups.set(key, value);
  }
  const rows = [...groups.entries()].sort((a, b) => (b[1].passed / b[1].total) - (a[1].passed / a[1].total));
  byId("covView").innerHTML = rows.map(([name, value]) => {
    const coverage = value.total ? value.passed / value.total * 100 : 0;
    return `
      <div class="coverage-row">
        <span class="coverage-title">${escapeHtml(name)}<small>${formatNumber(value.completed + value.partial)} опросов проведено · ${formatNumber(value.partial)} требуют уточнения</small></span>
        <div class="coverage-bar"><span style="width:${coverage}%"></span></div>
        <strong>${percent(coverage)}</strong>
      </div>
    `;
  }).join("");
  const totals = sessionCounts(people);
  const passed = people.filter(hasConductedSurvey).length;
  byId("rosterCount").innerHTML = `охват <strong>${formatNumber(passed)}</strong> из ${formatNumber(people.length)} человек · ${formatNumber(totals.total)} опросов проведено · ${formatNumber(totals.partial)} требуют уточнения`;
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
  renderScenarioScope();
  renderScenarioCards();
  renderQualityChart();
  renderFilterCounts();
  renderSessionLogic();
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
    confidence: "Уверенность описания",
    document_status: "Статус",
    asked: "Задано",
    closed: "Полностью закрыто",
    closed_soft: "Закрыто с оговорками",
    partial: "Частично",
    reassigned: "Переадресовано",
    open: "Открыто",
    grounded: "Подтверждено конкретикой",
    completeness: "Полнота",
    workload_assessed: "Оценка загрузки",
  };
  return labels[key] || key;
}

function formatDecimal(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(number);
}

function questionBreakdown(session) {
  if (session.scenario !== "s2") return "";
  const metrics = session.metrics || {};
  const items = [
    ["Полностью закрыто", metrics.closed],
    ["С оговорками", metrics.closed_soft],
    ["Частично", metrics.partial],
    ["Открыто", metrics.open],
    ["Переадресовано", metrics.reassigned],
  ];
  return `
    <section class="question-summary" aria-label="Количество вопросов по статусам">
      <div class="question-summary-heading">
        <span>Ответы на вопросы</span>
        <strong>${formatNumber(metrics.asked)} задано</strong>
      </div>
      <div class="question-summary-grid">
        ${items.map(([label, value]) => `<div><strong>${formatNumber(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("")}
      </div>
    </section>
  `;
}

function answerQuality(session, status) {
  if (session.scenario !== "s2") {
    return {
      className: "not-scored",
      label: "Отдельно не рассчитывается",
      detail: session.scenario === "s1"
        ? "Итог определяется уверенностью всего документа"
        : "Итог определяется полнотой всего документа",
    };
  }

  const normalized = String(status || "").trim().toLocaleLowerCase("ru-RU");
  const rules = [
    { matches: ["closed-soft", "с оговор"], score: 75, label: "Засчитано с оговорками" },
    { matches: ["reassigned", "передан"], score: 0, label: "Переадресовано" },
    { matches: ["open", "открыт", "не закрыт"], score: 0, label: "Не закрыто" },
    { matches: ["partial", "частич"], score: 50, label: "Засчитано частично" },
    { matches: ["closed", "закрыт"], score: 100, label: "Засчитано полностью" },
  ];
  const rule = rules.find((item) => item.matches.some((marker) => normalized.includes(marker)));
  if (!rule) {
    return {
      className: "not-scored",
      label: "Не участвует в расчёте",
      detail: "В строке нет расчётного статуса доопроса",
    };
  }
  return {
    className: rule.score >= 75 ? "high" : rule.score >= 50 ? "medium" : "low",
    label: `${formatDecimal(rule.score)}% · ${rule.label}`,
    detail: `Вклад в числитель: ${formatDecimal(rule.score / 100)}`,
  };
}

function qualityCalculation(session) {
  const metrics = session.metrics || {};
  if (session.score == null) {
    return {
      formula: "Расчёт недоступен: в документе недостаточно исходных показателей.",
      basis: "Такая сессия не получает числовой оценки качества.",
    };
  }
  if (session.scenario === "s1") {
    return {
      formula: `${formatDecimal(metrics.confidence)} × 100 = ${percent(session.score)}`,
      basis: "Уверенность описания умножается на 100.",
    };
  }
  if (session.scenario === "s2") {
    return {
      formula: `не более 100%: (${formatDecimal(metrics.closed)} + 0,75 × ${formatDecimal(metrics.closed_soft)} + 0,5 × ${formatDecimal(metrics.partial)}) / ${formatDecimal(metrics.asked)} × 100 = ${percent(session.score)}`,
      basis: "Полностью закрытые ответы дают 1, с оговорками — 0,75, частичные — 0,5; открытые и переадресованные — 0. Результат ограничивается 100%.",
    };
  }
  return {
    formula: `${formatDecimal(metrics.completeness)} × 100 = ${percent(session.score)}`,
    basis: "Полнота фото рабочего дня умножается на 100.",
  };
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
      const questionMetricKeys = new Set(["asked", "closed", "closed_soft", "partial", "open", "reassigned"]);
      const metrics = Object.entries(session.metrics || {})
        .filter(([key]) => session.scenario !== "s2" || !questionMetricKeys.has(key))
        .map(([key, value]) => `<span class="metric">${escapeHtml(metricLabel(key))}: ${escapeHtml(value ?? "—")}</span>`)
        .join("");
      const answerRows = (session.answers || []).map(([topic, answer, status], index) => {
        const assessment = answerQuality(session, status);
        return `
          <div class="answer-row">
            <div class="answer-cell" data-label="Вопрос">
              <span class="answer-number">${index + 1}</span>
              <strong>${escapeHtml(topic || "Фрагмент ответа")}</strong>
            </div>
            <div class="answer-cell answer-text" data-label="Ответ">
              <p>${escapeHtml(answer || "—")}</p>
              ${status ? `<small>Статус/контекст источника: ${escapeHtml(status)}</small>` : ""}
            </div>
            <div class="answer-cell answer-assessment ${assessment.className}" data-label="Оценка качества">
              <strong>${escapeHtml(assessment.label)}</strong>
              <small>${escapeHtml(assessment.detail)}</small>
            </div>
          </div>
        `;
      }).join("");
      const answers = answerRows ? `
        <p class="answer-note">Показаны доступные извлечённые фрагменты. Итог считается по полным метрикам документа, поэтому только видимые строки могут не складываться в итоговый балл.</p>
        <div class="answer-table">
          <div class="answer-head" aria-hidden="true">
            <span>Вопрос</span><span>Ответ</span><span>Оценка качества</span>
          </div>
          ${answerRows}
        </div>
      ` : `<p class="muted">Структурированные фрагменты не извлечены; метрики сессии показаны выше.</p>`;
      const calculation = qualityCalculation(session);
      return `
        <article class="detail-card">
          <span class="quality-pill ${escapeHtml(session.quality)}">${escapeHtml(SURVEY[session.scenario]?.label || session.scenario)} · ${percent(session.score)}</span>
          <span class="completion-pill ${session.completed ? "completed" : "partial"}">${session.completed ? "Опрос проведён" : "Завершён · требуется уточнение"}</span>
          <h3>${escapeHtml(session.title || SURVEY[session.scenario]?.name || "Сессия")}</h3>
          <div class="person-sub">${formatDate(session.created_at)} · ${escapeHtml(session.session_id)}</div>
          <div class="session-source"><span>Файл</span><code title="${escapeHtml(session.source_file || "")}">${escapeHtml(sourceFileName(session.source_file))}</code></div>
          <div class="metric-list">${metrics}</div>
          ${questionBreakdown(session)}
          ${answers}
          <section class="calculation-card">
            <span class="calculation-label">Расчёт оценки качества</span>
            <strong>${escapeHtml(calculation.formula)}</strong>
            <p>${escapeHtml(calculation.basis)}</p>
          </section>
          <section class="quality-total ${escapeHtml(session.quality)}">
            <div>
              <span>Итоговая оценка качества</span>
              <small>${session.completed ? "Учитывается в охвате и сводном качестве" : "Учитывается в охвате; качество показано отдельно до уточнения вопросов"}</small>
            </div>
            <strong>${percent(session.score)}</strong>
            <span class="quality-total-label">${escapeHtml(QUALITY_LABEL[session.quality] || QUALITY_LABEL.unknown)}</span>
          </section>
        </article>
      `;
    }).join("");
    const partial = person.sessions.filter((session) => !session.completed).length;
    openDrawer(person.name, `${formatNumber(person.sessions.length)} опросов проведено · ${formatNumber(partial)} требуют уточнения`, cards);
  } catch (error) {
    openDrawer("Ошибка загрузки", "Ответы сотрудника", `<div class="notice error">${escapeHtml(error.message)}</div>`);
  }
}

function showMethod() {
  const method = state.report.quality_method;
  const summary = state.report.summary;
  const scenarioRows = Object.values(state.report.scenarios).map((scenario) => `
    <tr>
      <td>${escapeHtml(scenario.name)}</td>
      <td>${formatNumber(scenario.conducted_sessions)}</td>
      <td>${formatNumber(scenario.partial_sessions || 0)}</td>
      <td>${percent(scenario.quality.average)}</td>
      <td>${formatNumber(scenario.quality.high)}</td>
      <td>${formatNumber(scenario.quality.medium)}</td>
      <td>${formatNumber(scenario.quality.low)}</td>
    </tr>
  `).join("");
  const audit = state.report.fio_audit;
  openDrawer("Справка по качеству", "Формулы, результаты и расшифровка терминов", `
    <article class="detail-card">
      <h3>Как рассчитывается балл</h3>
      <dl class="glossary-list compact">
        <dt>Основной опрос по процессу</dt><dd>${escapeHtml(method.s1)}.</dd>
        <dt>Доопрос</dt><dd>${escapeHtml(method.s2)}.</dd>
        <dt>Фото рабочего дня</dt><dd>${escapeHtml(method.s3)}.</dd>
      </dl>
    </article>
    <article class="detail-card">
      <h3>Пороговые уровни</h3>
      <p><span class="quality-pill high">Высокое ${escapeHtml(method.high)}</span> <span class="quality-pill medium">Среднее ${escapeHtml(method.medium)}</span> <span class="quality-pill low">Низкое ${escapeHtml(method.low)}</span></p>
      <p class="muted">${escapeHtml(method.warning)}</p>
    </article>
    <article class="detail-card">
      <h3>Текущие проверенные результаты</h3>
      <div class="reference-table-wrap">
        <table class="reference-table">
          <thead><tr><th>Опрос</th><th>Опрос проведён</th><th>Требуется уточнение</th><th>Среднее</th><th>Высокое</th><th>Среднее</th><th>Низкое</th></tr></thead>
          <tbody>${scenarioRows}</tbody>
          <tfoot><tr><th>Итого</th><th>${formatNumber(summary.conducted_sessions)}</th><th>${formatNumber(summary.partial_sessions)}</th><th>${percent(summary.quality.average)}</th><th>${formatNumber(summary.quality.high)}</th><th>${formatNumber(summary.quality.medium)}</th><th>${formatNumber(summary.quality.low)}</th></tr></tfoot>
        </table>
      </div>
      <p class="muted">Все сохранённые опросы считаются проведёнными и входят в охват. Опросы с отметкой «требуется уточнение» показаны отдельно и пока не входят в средний результат качества.</p>
    </article>
    <article class="detail-card">
      <h3>Что именно сравнивается</h3>
      <ul class="audit-list">
        <li><strong>Баллы анкеты</strong> — результат одного опроса по метрикам исходного документа.</li>
        <li><strong>Качество сотрудника</strong> — среднее его опросов без отметки уточнения.</li>
        <li><strong>Низкое качество</strong> — средний результат сотрудника ниже 50%.</li>
        <li><strong>Распределение качества</strong> — количество отдельных опросов без отметки уточнения каждого уровня.</li>
        <li><strong>Среднее на вкладке</strong> — среднее персональных результатов выбранной группы.</li>
        <li><strong>Охват</strong> — доля людей хотя бы с одним проведённым опросом, включая требующие уточнения.</li>
      </ul>
    </article>
    <article class="detail-card">
      <h3>Словарь показателей</h3>
      <dl class="glossary-list">
        <dt>Уверенность описания</dt><dd>Полнота описания основного процесса.</dd>
        <dt>Задано</dt><dd>Общее количество вопросов в доопросе.</dd>
        <dt>Полностью закрыто</dt><dd>Получен полный ответ; вес в расчёте — 1.</dd>
        <dt>Закрыто с оговорками</dt><dd>Ответ принят с небольшими ограничениями; вес — 0,75.</dd>
        <dt>Частично</dt><dd>Получена только часть ответа; вес — 0,5.</dd>
        <dt>Открыто</dt><dd>Ответ не получен; вес — 0.</dd>
        <dt>Переадресовано</dt><dd>Вопрос направлен другому сотруднику и отдельно показывается в деталях.</dd>
        <dt>Подтверждено конкретикой</dt><dd>Ответ содержит факт, пример, документ или другое основание.</dd>
        <dt>Полнота карты дня</dt><dd>Насколько полно описаны активности рабочего дня.</dd>
        <dt>Опрос проведён</dt><dd>Сохранённый опрос учитывается в охвате.</dd>
        <dt>Есть вопросы на уточнение</dt><dd>Опрос проведён, но часть вопросов осталась открытой, частичной или переадресованной.</dd>
        <dt>Нет оценки</dt><dd>В документе недостаточно данных для вычисления балла.</dd>
      </dl>
    </article>
    <article class="detail-card">
      <h3>Проверка ФИО</h3>
      <p>${formatNumber(audit.issue_count)} основных сигналов: ${formatNumber((audit.duplicate_full_names_in_roster || []).length)} дубликатов полного ФИО, ${formatNumber((audit.bitrix_ids_with_name_variants || []).length)} идентификаторов с вариантами ФИО и ${formatNumber((audit.names_with_multiple_bitrix_ids || []).length)} ФИО с разными идентификаторами.</p>
      <p class="muted">Неполные ФИО учитываются отдельно: ${formatNumber((audit.short_names_in_roster || []).length)}.</p>
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
    byId("sourceHealth").textContent = `${formatNumber(state.report.summary.conducted_sessions)} опросов проведено · ${formatNumber(state.report.summary.partial_sessions)} требуют уточнения · версия данных ${state.report.schema_version}`;
    const staff = rowsForTab("staff").length;
    const tovar = rowsForTab("tovar").length;
    byId("cntStaff").textContent = formatNumber(staff);
    byId("cntTovar").textContent = formatNumber(tovar);
    renderFioSummary();
    renderBoard();
    byId("foot").textContent = `Источник KB-ARM-survey только для чтения · ${state.report.snapshot} · требуют уточнения: ${formatNumber(state.report.summary.partial_sessions)} · исключено из свода: ${formatNumber(state.report.summary.excluded_people)} · детали ответов загружаются только по запросу.`;
    bindEvents();
  } catch (error) {
    byId("loadError").textContent = `${error.message}. Откройте сайт через GitHub Pages или локальный HTTP-сервер.`;
    byId("loadError").classList.remove("hidden");
    byId("sourceHealth").textContent = "Ошибка загрузки";
  }
}

start();
