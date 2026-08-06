const fs = require("fs");

const html = fs.readFileSync("index.html", "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];

if (scripts.length !== 1) {
  throw new Error(`Ожидался один встроенный script, найдено: ${scripts.length}`);
}

new Function(scripts[0][1]);

for (const marker of [
  'id="tabs"',
  'id="segFilter"',
  'id="selUnit"',
  'id="search"',
  'data-f="all"',
  'data-f="none"',
  'data-f="pass"',
  'data-f="cov"',
  'data-tab="staff"',
  'data-tab="tovar"',
  'rFilter="all"',
  'rUnit',
  'rQuery',
  'rSort',
]) {
  if (!html.includes(marker)) {
    throw new Error(`Не найден обязательный элемент фильтра: ${marker}`);
  }
}

console.log("HTML/JavaScript и контракт фильтров: OK");
