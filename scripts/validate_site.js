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
  'id="drawer"',
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

for (const marker of ["data/report.json", "data/details.json", "renderQualityChart", "showPerson", "showFioAudit"]) {
  if (!app.includes(marker)) throw new Error(`Не найден JS-контракт: ${marker}`);
}

for (const marker of ["Справка по качеству", "Словарь показателей", "Что именно сравнивается", "Основной опрос", "Доопрос", "Фото рабочего дня", "Вопрос", "Ответ", "Оценка качества", "Расчёт оценки качества", "Итоговая оценка качества", "Итог считается по полным метрикам документа"]) {
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

const counted = report.people.filter((person) => !person.excluded_reason).reduce((sum, person) => sum + person.vs, 0);
if (counted !== report.summary.sessions) {
  throw new Error(`Сессии людей не сходятся с итогом: people=${counted}, report=${report.summary.sessions}`);
}

const countedPartial = report.people.filter((person) => !person.excluded_reason).reduce((sum, person) => sum + (person.partial_sessions || 0), 0);
if (countedPartial !== report.summary.partial_sessions) {
  throw new Error(`Person partial totals differ: people=${countedPartial}, report=${report.summary.partial_sessions}`);
}

for (const person of report.people.filter((item) => item.vs > 0 || item.partial_sessions > 0)) {
  if (!details.people[person.key]) throw new Error(`Нет деталей для ${person.key}`);
  const sessions = details.people[person.key].sessions || [];
  const completed = sessions.filter((session) => session.completed).length;
  const partial = sessions.filter((session) => !session.completed).length;
  if (completed !== person.vs || partial !== (person.partial_sessions || 0)) {
    throw new Error(`Детали не сходятся для ${person.key}: completed=${completed}/${person.vs}, partial=${partial}/${person.partial_sessions || 0}`);
  }
  if (sessions.some((session) => typeof session.completed !== "boolean" || !session.completion_status)) {
    throw new Error(`В деталях отсутствует статус завершения для ${person.key}`);
  }
}

console.log(`Сайт и данные: OK; ${report.people.length} карточек, ${report.summary.sessions} завершённых, ${report.summary.partial_sessions} незавершённых, ${report.fio_audit.issue_count} ФИО-сигналов`);
