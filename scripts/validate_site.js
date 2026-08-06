"use strict";

const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync("index.html", "utf8");
const app = fs.readFileSync("assets/app.js", "utf8");
const styles = fs.readFileSync("assets/styles.css", "utf8");
const report = JSON.parse(fs.readFileSync("data/report.json", "utf8"));
const details = JSON.parse(fs.readFileSync("data/details.json", "utf8"));
const status = JSON.parse(fs.readFileSync("data/update-status.json", "utf8"));

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

if (!styles.includes("@media") || !styles.includes(".quality-chart") || !styles.includes(".drawer")) {
  throw new Error("Не найден адаптивный стиль графика или панели деталей");
}

if (report.schema_version !== 2 || details.schema_version !== 2 || status.schema_version !== 2) {
  throw new Error("Неверная версия JSON-схемы");
}
if (!Array.isArray(report.people) || report.people.length === 0) throw new Error("Реестр сотрудников пуст");
if (!report.quality_method?.warning) throw new Error("Не описано ограничение индекса качества");
if (!report.fio_audit || typeof report.fio_audit.issue_count !== "number") throw new Error("Нет аудита ФИО");

const sessionTotal = Object.values(report.scenarios).reduce((sum, scenario) => sum + scenario.sessions, 0);
if (sessionTotal !== report.summary.sessions || sessionTotal !== status.included_sessions) {
  throw new Error(`Не сходится число включённых сессий: scenarios=${sessionTotal}, report=${report.summary.sessions}, status=${status.included_sessions}`);
}

const counted = report.people.filter((person) => !person.excluded_reason).reduce((sum, person) => sum + person.vs, 0);
if (counted !== report.summary.sessions) {
  throw new Error(`Сессии людей не сходятся с итогом: people=${counted}, report=${report.summary.sessions}`);
}

for (const person of report.people.filter((item) => item.vs > 0)) {
  if (!details.people[person.key]) throw new Error(`Нет деталей для ${person.key}`);
}

console.log(`Сайт и данные: OK; ${report.people.length} карточек, ${report.summary.sessions} сессий, ${report.fio_audit.issue_count} ФИО-сигналов`);
