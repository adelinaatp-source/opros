"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const projectRoot = path.resolve(__dirname, "..");
const readProjectFile = (relativePath) =>
  fs.readFileSync(path.join(projectRoot, relativePath), "utf8");

const html = readProjectFile("index.html");
const app = readProjectFile("assets/app.js");
const styles = readProjectFile("assets/styles.css");
const report = JSON.parse(readProjectFile("data/report.json"));
const details = JSON.parse(readProjectFile("data/details.json"));
const status = JSON.parse(readProjectFile("data/update-status.json"));

new vm.Script(app, { filename: "assets/app.js" });

if (/const\s+_ALL\s*=/.test(html)) {
  throw new Error("Данные снова встроены в index.html");
}

for (const marker of [
  'href="assets/styles.css"',
  'src="assets/app.js"',
  'id="tabs"',
  'id="segFilter"',
  'id="selUnit"',
  'id="search"',
  'id="qualityChart"',
  'id="scenarioScope"',
  'id="drawer"',
  'id="sessionLogic"',
  'data-f="all"',
  'data-f="none"',
  'data-f="pass"',
  'data-f="low"',
  'data-f="partial"',
  'data-f="fio"',
  'data-f="cov"',
  'data-tab="staff"',
  'data-tab="tovar"',
]) {
  if (!html.includes(marker)) throw new Error(`Не найден обязательный элемент: ${marker}`);
}

for (const marker of ["data/report.json", "data/details.json", "renderScenarioScope", "renderQualityChart", "renderFilterCounts", "renderSessionLogic", "sourceFileName", "showPerson", "showFioAudit"]) {
  if (!app.includes(marker)) throw new Error(`Не найден JS-контракт: ${marker}`);
}

for (const marker of ["Справка по качеству", "Словарь показателей", "Что именно сравнивается", "Основной опрос", "Доопрос", "Фото рабочего дня", "Вопрос", "Ответ", "Оценка качества", "Расчёт оценки качества", "Итоговая оценка качества", "Итог считается по полным метрикам документа", "Опрос проведён", "Есть вопросы на уточнение", "Требуется уточнение", "Завершён · требуется уточнение", "Полностью закрыто", "Закрыто с оговорками", "Частично", "Открыто", "Переадресовано"]) {
  if (!`${html}\n${app}`.includes(marker)) throw new Error(`Не найден русский текст справки: ${marker}`);
}
if (/>\s*S[123]\s*</.test(html) || /label:\s*"S[123]"/.test(app) || /<h3>S[123]/.test(app)) {
  throw new Error("В пользовательском интерфейсе остались технические обозначения опросов");
}

if (!styles.includes("@media") || !styles.includes(".quality-chart") || !styles.includes(".drawer")) {
  throw new Error("Не найден адаптивный стиль графика или панели деталей");
}

if (report.schema_version !== 2 || details.schema_version !== 2 || status.schema_version !== 2) {
  throw new Error("Неверная версия JSON-схемы");
}
if (!Array.isArray(report.people) || report.people.length === 0) throw new Error("Реестр сотрудников пуст");
if (!report.quality_method?.warning) throw new Error("Не описано ограничение индекса качества");
if (Object.values(report.scenarios).some((scenario) => /^S[123]$/.test(scenario.tag))) {
  throw new Error("В карточках сценариев остались технические обозначения опросов");
}
if (!report.fio_audit || typeof report.fio_audit.issue_count !== "number") throw new Error("Нет аудита ФИО");

const sessionTotal = Object.values(report.scenarios).reduce((sum, scenario) => sum + scenario.sessions, 0);
if (sessionTotal !== report.summary.sessions || sessionTotal !== status.included_sessions) {
  throw new Error(`Не сходится число включённых сессий: scenarios=${sessionTotal}, report=${report.summary.sessions}, status=${status.included_sessions}`);
}

const partialTotal = Object.values(report.scenarios).reduce((sum, scenario) => sum + (scenario.partial_sessions || 0), 0);
if (partialTotal !== report.summary.partial_sessions || partialTotal !== status.included_partial_sessions) {
  throw new Error(`Partial session totals differ: scenarios=${partialTotal}, report=${report.summary.partial_sessions}, status=${status.included_partial_sessions}`);
}

const conductedTotal = Object.values(report.scenarios).reduce((sum, scenario) => sum + (scenario.conducted_sessions || 0), 0);
if (conductedTotal !== report.summary.conducted_sessions || conductedTotal !== status.included_conducted_sessions) {
  throw new Error(`Не сходится число проведённых опросов: scenarios=${conductedTotal}, report=${report.summary.conducted_sessions}, status=${status.included_conducted_sessions}`);
}
if (report.summary.conducted_sessions !== report.summary.sessions + report.summary.partial_sessions) {
  throw new Error("Проведённые опросы должны включать опросы, требующие уточнения");
}

const counted = report.people.filter((person) => !person.excluded_reason).reduce((sum, person) => sum + person.vs, 0);
if (counted !== report.summary.sessions) {
  throw new Error(`Сессии людей не сходятся с итогом: people=${counted}, report=${report.summary.sessions}`);
}

const countedPartial = report.people.filter((person) => !person.excluded_reason).reduce((sum, person) => sum + (person.partial_sessions || 0), 0);
if (countedPartial !== report.summary.partial_sessions) {
  throw new Error(`Person partial totals differ: people=${countedPartial}, report=${report.summary.partial_sessions}`);
}

const normalizeName = (value) => String(value || "")
  .toLocaleLowerCase("ru-RU")
  .replaceAll("ё", "е")
  .replace(/[^а-яa-z0-9]+/gi, " ")
  .trim();
const isTovar = (person) => person.o === "Товароведы" || /товаровед/i.test(person.d || "") || /скупщик/i.test(person.d || "");
const visibleByName = new Map();
for (const person of report.people.filter((item) => !item.excluded_reason)) {
  const key = normalizeName(person.f);
  const current = visibleByName.get(key);
  const conducted = person.conducted_sessions ?? ((person.vs || 0) + (person.partial_sessions || 0));
  const currentConducted = current?.conducted_sessions ?? ((current?.vs || 0) + (current?.partial_sessions || 0));
  if (!current || conducted > currentConducted || (conducted === currentConducted && person.vs > current.vs) || (conducted === currentConducted && person.vs === current.vs && String(person.f).length > String(current.f).length)) {
    visibleByName.set(key, person);
  }
}
const dashboardRows = [...visibleByName.values()];
const filterGroups = {
  staff: dashboardRows.filter((person) => !isTovar(person)),
  tovar: dashboardRows.filter(isTovar),
};
const scenarioAverage = (rows, key) => {
  let weighted = 0;
  let scored = 0;
  for (const person of rows) {
    const quality = person.scenario_quality?.[key];
    const count = (quality?.high || 0) + (quality?.medium || 0) + (quality?.low || 0);
    if (quality?.average != null && count) {
      weighted += quality.average * count;
      scored += count;
    }
  }
  return scored ? Math.round(weighted / scored * 10) / 10 : null;
};
const staffScenarioQuality = ["s1", "s2", "s3"].map((key) => scenarioAverage(filterGroups.staff, key));
const tovarScenarioQuality = ["s1", "s2", "s3"].map((key) => scenarioAverage(filterGroups.tovar, key));
if (staffScenarioQuality.every((value, index) => value === tovarScenarioQuality[index])) {
  throw new Error("Качество сценариев не различается между группами — возможна подстановка глобальных процентов");
}
const filterTotals = Object.values(filterGroups).reduce((result, rows) => ({
  completed: result.completed + rows.reduce((sum, person) => sum + person.vs, 0),
  partial: result.partial + rows.reduce((sum, person) => sum + (person.partial_sessions || 0), 0),
}), { completed: 0, partial: 0 });
if (filterTotals.completed !== report.summary.sessions || filterTotals.partial !== report.summary.partial_sessions) {
  throw new Error(`Фильтры групп теряют сессии: completed=${filterTotals.completed}/${report.summary.sessions}, partial=${filterTotals.partial}/${report.summary.partial_sessions}`);
}
for (const [name, rows] of Object.entries(filterGroups)) {
  const passed = rows.filter((person) => (person.conducted_sessions || 0) > 0);
  const notPassed = rows.filter((person) => (person.conducted_sessions || 0) <= 0);
  const low = rows.filter((person) => person.vs > 0 && person.quality.average < 50);
  const partial = rows.filter((person) => (person.partial_sessions || 0) > 0);
  if (passed.length + notPassed.length !== rows.length || low.some((person) => person.vs <= 0) || partial.some((person) => !person.partial_sessions)) {
    throw new Error(`Нарушена логика фильтров для группы ${name}`);
  }
}

const passedPeople = dashboardRows.filter((person) => (person.conducted_sessions || 0) > 0).length;
if (passedPeople !== report.summary.passed_people) {
  throw new Error(`Охват людей не сходится: people=${passedPeople}, report=${report.summary.passed_people}`);
}
if (dashboardRows.length !== report.summary.people || dashboardRows.length - passedPeople !== report.summary.not_passed_people) {
  throw new Error(`Количество уникальных людей не сходится с фильтрами: rows=${dashboardRows.length}, summary=${report.summary.people}`);
}

for (const person of report.people.filter((item) => item.vs > 0 || item.partial_sessions > 0)) {
  if (!details.people[person.key]) throw new Error(`Нет деталей для ${person.key}`);
  const sessions = details.people[person.key].sessions || [];
  for (const session of sessions) {
    if (!session.source_file || !String(session.source_file).trim()) {
      throw new Error(`У сессии ${session.session_id || "без ID"} не указано имя исходного файла`);
    }
    if (session.scenario === "s2") {
      const metrics = session.metrics || {};
      const answerStates = ["closed", "closed_soft", "partial", "open", "reassigned"];
      if (answerStates.some((key) => !Number.isFinite(Number(metrics[key])))) {
        throw new Error(`У доопроса ${session.session_id || "без ID"} нет счётчика одного из статусов вопросов`);
      }
      const classified = answerStates.reduce((sum, key) => sum + Number(metrics[key]), 0);
      if (classified !== Number(metrics.asked)) {
        throw new Error(`Статусы вопросов не сходятся у ${session.session_id || "без ID"}: ${classified}/${metrics.asked}`);
      }
    }
  }
  const completed = sessions.filter((session) => session.completed).length;
  const partial = sessions.filter((session) => !session.completed).length;
  if (completed !== person.vs || partial !== (person.partial_sessions || 0)) {
    throw new Error(`Детали не сходятся для ${person.key}: completed=${completed}/${person.vs}, partial=${partial}/${person.partial_sessions || 0}`);
  }
  if (sessions.some((session) => typeof session.completed !== "boolean" || !session.completion_status)) {
    throw new Error(`В деталях отсутствует статус завершения для ${person.key}`);
  }
  if (sessions.some((session) => session.conducted !== true || session.requires_clarification !== !session.completed)) {
    throw new Error(`В деталях неверно определён проведённый опрос или признак уточнения для ${person.key}`);
  }
}

console.log(`Сайт и данные: OK; ${report.people.length} карточек, ${report.summary.conducted_sessions} опросов проведено, ${report.summary.partial_sessions} требуют уточнения, ${report.fio_audit.issue_count} ФИО-сигналов`);
