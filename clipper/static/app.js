"use strict";
const TOKEN = document.body.dataset.token;
const $ = (s) => document.querySelector(s);
const S = { name: null, phrases: [], sel: null, open: null, window: [150, 330], step: 1, built: false };

async function api(path, body, opts = {}) {
  const r = await fetch("/api/" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Token": TOKEN, ...(opts.raw ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : opts.raw ? body : JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw j;
  return j;
}
const fmt = (s) => { s = Math.round(s); const h = (s / 3600) | 0, m = ((s % 3600) / 60) | 0, x = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0"); };
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let bannerTimer = null;
function banner(e, ok) {
  const b = $("#banner"); clearTimeout(bannerTimer);
  if (!e) { b.hidden = true; return; }
  b.className = "banner" + (ok ? " warn" : "");
  b.innerHTML = `<b>${esc(e.what || "Ошибка")}</b>${e.hint ? (ok ? "" : "Что делать: ") + esc(e.hint) : ""}`;
  b.hidden = false; b.onclick = () => { b.hidden = true; };
  if (ok) bannerTimer = setTimeout(() => { b.hidden = true; }, 8000);
}
/* окно подтверждения вместо системных confirm/prompt */
function ask(title, text, okLabel = "Да", withInput = null) {
  return new Promise((res) => {
    $("#m-t").textContent = title; $("#m-x").textContent = text; $("#m-yes").textContent = okLabel;
    const inp = $("#m-in"); inp.hidden = withInput === null; inp.value = withInput || "";
    $("#modal").hidden = false; (withInput === null ? $("#m-yes") : inp).focus();
    const done = (v) => { $("#modal").hidden = true; res(v); };
    $("#m-yes").onclick = () => done(withInput === null ? true : inp.value);
    $("#m-no").onclick = () => done(withInput === null ? false : null);
    inp.onkeydown = (e) => { if (e.key === "Enter") $("#m-yes").click(); if (e.key === "Escape") $("#m-no").click(); };
  });
}
function list(el, rows) {
  el.innerHTML = rows.map(([lv, m]) => `<li class="${lv}">${esc(m)}</li>`).join("");
}
function setStep(n) {
  S.step = n;
  S.reachBy = S.reachBy || {};
  const key = S.name || "";
  const reach = S.reachBy[key] = Math.max(S.reachBy[key] || 1, n);   // самый дальний шаг, где проект уже был
  document.querySelectorAll(".step").forEach((e) => e.classList.toggle("on", e.id === "step-" + n));
  document.querySelectorAll("#steps li").forEach((e) => {
    const k = +e.dataset.step;
    e.classList.toggle("on", k === n); e.classList.toggle("done", k < n);
    e.classList.toggle("ahead", k > n && k <= reach);     // можно вернуться вперёд
    e.title = k > n && k <= reach ? `Вернуться вперёд: ${STEP_NAMES[k]}` : "";
  });
  document.querySelectorAll(".navrow .fwd").forEach((b) => {
    const to = +b.dataset.to;
    b.hidden = !(to > n && to <= reach && +b.closest(".step").id.slice(5) === n);
  });
}
function guard(fn) { return async (...a) => { try { banner(null); await fn(...a); } catch (e) { banner(e); $("#job").hidden = true; } }; }

async function runJob(job, title) {
  $("#job").hidden = false;
  for (;;) {
    $("#bar").style.width = Math.round((job.progress || 0) * 100) + "%";
    $("#jobtext").textContent = (job.log && job.log.length ? job.log[job.log.length - 1] : title) + (job.progress ? ` (${Math.round(job.progress * 100)}%)` : "");
    if (job.status === "done") { $("#job").hidden = true; return job.result; }
    if (job.status === "error") { $("#job").hidden = true; throw job.error; }
    await new Promise((r) => setTimeout(r, 700));
    job = await api("job/" + job.id);
  }
}

/* ---------- шаг 1 ---------- */
async function startSource(source) {
  const job = await api("new", { source });
  const r = await runJob(job, "Читаю источник…");
  await openProject(r.name, 2);
}
$("#go1").onclick = guard(async () => {
  const v = $("#src").value.trim();
  if (!v) throw { what: "Источник пустой.", hint: "Вставь ссылку или выбери файл." };
  await startSource(v);
});
$("#pick").onclick = guard(async () => { const r = await api("pick_file", {}); if (r.path) await startSource(r.path); });
const drop = $("#drop");
["dragover", "dragenter"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
drop.addEventListener("drop", guard(async (e) => {
  e.preventDefault();
  const f = e.dataTransfer.files[0];
  if (!f) return;
  $("#job").hidden = false; $("#jobtext").textContent = "Копирую файл…";
  const r = await api("upload?name=" + encodeURIComponent(f.name), f, { raw: true });
  await startSource(r.path);
}));

/* ---------- шаг 2 ---------- */
function renderHeat(p) {
  const h = p.heatmap, box = $("#heat-wrap"); box.hidden = !(h && h.length);
  if (box.hidden) return;
  const max = Math.max(...h.map((x) => x.value || 0)) || 1;
  $("#heat").innerHTML = h.map((x) => `<i data-t="${x.start_time}" title="${fmt(x.start_time)}" style="height:${Math.max(6, Math.round(100 * x.value / max))}%"></i>`).join("");
  $("#heat").onclick = (e) => { const b = e.target.closest("i"); if (b) { $("#q").value = fmt(+b.dataset.t); $("#find").click(); } };
}
async function openProject(name, step) {
  S.name = name; S.sel = null; S.open = null; S.built = false; S.cur = null; S.crop = null; S.fixes = []; S.ok = {};
  const p = await api("project/" + name);
  $("#ptitle").textContent = p.title || "Где момент";
  S.phrases = await api(`project/${name}/phrases`);
  renderStrip(); renderRange(); renderHeat(p);
  S.fixes = p.fixes || []; $("#post").value = p.post_draft || ""; $("#reply").value = ""; list($("#reply-out"), []); if (p.moment && step !== 2) { S.crop = p.moment.crop || null; S.sel = { start: p.moment.start, end: p.moment.end }; S.open = p.moment.open; renderRange(); }
  $("#video-wrap").hidden = true; $("#go3b").hidden = true; $("#go3").hidden = false; list($("#checks"), []);
  setStep(step || (p.clip ? 4 : 2));
  if (p.clip && (step === 4)) await showClip(p);
  showTab("clip");
}
const STRIPS = ["#strip", "#strip3"];
function renderStrip() {
  const html = S.phrases.map((p) => `<div class="ph" data-i="${p.i}"><span class="n">${p.i}</span><span class="t">${fmt(p.start)}</span><span>${esc(p.text)}</span></div>`).join("");
  STRIPS.forEach((id) => { $(id).innerHTML = html; });
  markStrip();
}
function markStrip() {
  const inR = (p) => S.sel && p.start >= S.sel.start - 0.01 && p.start < S.sel.end;
  STRIPS.forEach((id) => {
    const kids = $(id).children;
    S.phrases.forEach((p, k) => {
      const el = kids[k]; if (!el) return;
      const prev = S.phrases[k - 1], next = S.phrases[k + 1];
      el.className = "ph" + (inR(p) ? " in" : "") + (inR(p) && !(prev && inR(prev)) ? " first" : "") + (inR(p) && !(next && inR(next)) ? " last" : "")
        + (S.open && p.start >= S.open[0] - 0.01 && p.start < S.open[1] ? " open" : "") + (S.cur === k ? " cur" : "");
    });
  });
}
function renderRange() {
  const r = $("#range"), has = !!S.sel;
  r.hidden = !has; $("#go2").disabled = !has;
  if (!has) return;
  const d = S.sel.end - S.sel.start, [lo, hi] = S.window;
  const warn = d < lo || d > hi ? ` <b style="color:var(--warn)">Длина вне окна ${fmt(lo)}–${fmt(hi)}</b>` : "";
  r.innerHTML = `Отрезок <b>${fmt(S.sel.start)}–${fmt(S.sel.end)}</b>, длина ${fmt(d)}.${warn}`
    + (S.open ? `<br>Холодное начало: ${fmt(S.open[0])}–${fmt(S.open[1])}` : "");
  markStrip();
}
function pickHit(h) {
  S.sel = { start: h.start, end: h.end };
  renderRange();
  const el = $("#strip").children[h.first]; if (el) $("#strip").scrollTop = el.offsetTop - 60;
}
$("#find").onclick = guard(async () => {
  const text = $("#q").value.trim();
  if (!text) throw { what: "Поле момента пустое.", hint: "Впиши цитату из видео по-английски или время, например 12:34." };
  const r = await api(`project/${S.name}/moment`, { text });
  $("#hits").innerHTML = r.hits.map((h, i) => `<div class="hit" data-i="${i}"><b>${fmt(h.start)}</b>${h.score ? " · совпадение " + h.score + "%" : ""}`
    + `<small>${esc((h.before || "").slice(-80))} ▸ ${esc((h.text || "").slice(0, 160))} ◂ ${esc((h.after || "").slice(0, 80))}</small></div>`).join("");
  document.querySelectorAll(".hit").forEach((el) => el.onclick = () => {
    document.querySelectorAll(".hit").forEach((x) => x.classList.remove("sel")); el.classList.add("sel"); pickHit(r.hits[+el.dataset.i]);
  });
  if (r.hits.length) { document.querySelector(".hit").click(); }
});
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#find").click(); });
$("#strip").addEventListener("click", (e) => {
  const row = e.target.closest(".ph"); if (!row) return;
  const p = S.phrases[+row.dataset.i];
  if (S.sel && p.start > S.sel.start) S.sel = { start: S.sel.start, end: p.end ?? p.start + 5 };
  else S.sel = { start: p.start, end: p.start + 240 };
  renderRange();
});
$("#copy-num").onclick = guard(async () => { const r = await api(`project/${S.name}/for_claude`); await api("copy", { text: r.text }); banner({ what: "Вся расшифровка скопирована вместе с правилами.", hint: "Вставь в чат с Claude: он выберет момент и сразу напишет пост." }, true); });
$("#copy-link").onclick = guard(async () => { const r = await api(`project/${S.name}/link_request`); await api("copy", { text: r.text }); banner({ what: "Запрос со ссылкой скопирован.", hint: "Вставь в чат, где Claude умеет открывать видео. Ответ с временем клипа и постом вставь ниже." }, true); });
async function applyReply() {
  const r = await api(`project/${S.name}/claude_reply`, { text: $("#reply").value });
  const rows = [...r.errors.map((m) => ["FAIL", m]), ...r.warnings.map((m) => ["WARN", m])];
  if (!r.errors.length) rows.unshift(["OK", `Клип ${fmt(r.start)}–${fmt(r.end)} (фразы ${r.first}–${r.last})` + (r.open ? `, холодное начало ${fmt(r.open[0])}–${fmt(r.open[1])}` : "")]);
  rows.push(r.subs_text ? ["OK", "Субтитры с пунктуацией от Claude получены: знаки и заглавные возьмутся из них."] : ["WARN", "Блока «СУБТИТРЫ» в ответе нет: знаки препинания в субтитрах будут из расшифровки (регистр поправлю сам)."]);
  if (r.post) rows.push(["OK", `Пост получен: цитаты дословно в клипе ${r.quotes_ok} из ${r.quotes}. Он уже вставлен на шаге «Текст».`], ...r.post_checks.filter(([lv]) => lv !== "OK").map(([lv, m]) => [lv, "Текст: " + m]));
  else rows.push(["WARN", "Поста в ответе нет: его можно получить на шаге «Текст» через пакет для чата."]);
  list($("#reply-out"), rows);
  if (!r.errors.length) { S.sel = { start: r.start, end: r.end }; S.open = r.open; renderRange(); const el = $("#strip").children[r.first]; if (el) $("#strip").scrollTop = el.offsetTop - 60; }
  if (r.post) $("#post").value = r.post;
}
$("#apply-reply").onclick = guard(applyReply);
$("#auto-run").onclick = guard(async () => {
  await applyReply();
  if (!S.sel) throw { what: "Нет границ клипа.", hint: "Проверь ответ Claude: нужны START и END или время клипа." };
  if ($("#reply-out").querySelector(".FAIL")) throw { what: "В ответе Claude есть ошибка, ролик не собираю.", hint: "Исправь её по красной строке выше." };
  await enterMontage();
  await autoBuild();
});
$("#go2").onclick = guard(() => enterMontage());

/* ---------- шаг 4 ---------- */
$("#copy-pkg").onclick = guard(async () => { const r = await api(`project/${S.name}/package`); await api("copy", { text: r.text }); banner({ what: "Пакет скопирован: вставь в чат с Claude.", hint: "" }, true); });
const checkPost = (save) => guard(async () => {
  const r = await api(`project/${S.name}/post`, { text: $("#post").value, save });
  if (r.text && r.text !== $("#post").value) $("#post").value = r.text;   // подставлен пропущенный разделитель ---
  const rows = [...r.results]; if (r.stats && r.stats.words) rows.push(["OK", `Слов ${r.stats.words}, прямых цитат ${r.stats.quotes}`]);
  if (save) rows.push(r.saved ? ["OK", "Сохранено как post.md в папке с готовым"] : ["FAIL", "Не сохранено: сначала исправь красные пункты"]);
  list($("#post-out"), rows);
});
$("#check-post").onclick = checkPost(false); $("#save-post").onclick = checkPost(true);
$("#open-folder").onclick = guard(() => api(`project/${S.name}/open_folder`, {}));

/* ---------- вкладки ---------- */
function showTab(t) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p.id === "tab-" + t));
  if (t === "history") loadHistory(); if (t === "system") { loadSystem(); loadSettings(); } if (t === "storage") loadStorage();
}
document.querySelectorAll(".tab").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
const loadHistory = guard(async () => {
  const items = await api("projects");
  const status = (p) => p.clip ? "ролик готов" + (p.post ? ", текст сохранён" : ", текста пока нет") : p.has_transcript ? "расшифровано, ролика пока нет" : "начат";
  $("#hist").innerHTML = items.length ? items.map((p) => `<div class="hrow" data-n="${esc(p.name)}"><span class="dot ${p.verdict || ""}"></span><div class="grow"><b>${esc(p.title || p.name)}</b><br><small class="muted">${esc((p.created || "").slice(0, 16).replace("T", " "))} · ${status(p)}</small></div>`
    + `<button class="main" data-o="${esc(p.name)}" data-c="${p.clip ? 1 : 0}" style="padding:8px 20px;min-height:38px;font-size:14px">${p.clip ? "Смотреть" : "Продолжить"}</button><div class="hdetail" hidden></div></div>`).join("")
    : "<p class='muted'>Клипов пока нет. Начни на вкладке «Клип».</p>";
  $("#hist").querySelectorAll("button[data-o]").forEach((b) => b.onclick = guard(async () => {
    const row = b.closest(".hrow"), box = row.querySelector(".hdetail");
    if (b.dataset.c !== "1") return openProject(b.dataset.o, 2);
    if (!box.hidden) { box.hidden = true; box.innerHTML = ""; b.textContent = "Смотреть"; return; }
    const p = await api(`project/${b.dataset.o}`);
    box.innerHTML = `<video controls preload="metadata" src="/api/project/${esc(p.name)}/video?t=${TOKEN}"></video><div class="path">${esc(p.published || "")}</div>`
      + `<div class="row"><button class="ghost" data-f>Показать файл в папке</button><button class="ghost" data-t>К тексту поста</button></div>`;
    box.hidden = false; b.textContent = "Свернуть";
    box.querySelector("[data-f]").onclick = guard(() => api(`project/${p.name}/open_folder`, {}));
    box.querySelector("[data-t]").onclick = guard(() => openProject(p.name, 4));
  }));
});
const loadSystem = guard(async () => { const r = await api("system"); list($("#sys"), r.map((x) => [x.status, `${x.name}: ${x.detail}`])); });
$("#copy-diag").onclick = guard(async () => { const r = await api("diagnostics"); await api("copy", { text: r.text }); banner({ what: "Диагностика скопирована: вставь в чат.", hint: "" }, true); });

/* ---------- старт и «пульс» ---------- */
async function beat() { try { const r = await api("ping"); $("#profile").textContent = r.profile; S.window = r.window; if (!window.__subsInit) { $("#subs").checked = r.subs_default !== false; window.__subsInit = true; } } catch (e) { banner({ what: "Потеряна связь с Cutline.", hint: "Закрой окно и запусти Cutline заново." }); } }
setStep(1); beat(); setInterval(beat, 8000);

window.addEventListener("pagehide", () => navigator.sendBeacon(`/api/bye?t=${TOKEN}`));

/* запоминаем размер и место окна: приложение откроется там же */
let lastWin = "";
function sendWin() {
  if (window.pywebview) return;   // в собственном окне положение сохраняет сама программа
  const max = outerWidth >= screen.availWidth - 16 && outerHeight >= screen.availHeight - 16;
  const st = JSON.stringify({ x: screenX, y: screenY, w: outerWidth, h: outerHeight, max });
  if (st === lastWin) return; lastWin = st;
  navigator.sendBeacon(`/api/window?t=${TOKEN}`, new Blob([st], { type: "application/json" }));
}
setInterval(sendWin, 2000); window.addEventListener("pagehide", sendWin);

/* ---------- переходы между шагами: можно вернуться и пойти вперёд ---------- */
const STEP_NAMES = { 1: "Источник", 2: "Момент", 3: "Монтаж", 4: "Текст" };
async function goStep(n) {
  if (n === 1) return setStep(1);
  if (!S.name) throw { what: "Сначала выбери источник.", hint: "Вставь ссылку или файл на шаге «Источник»." };
  if (n === 3 && !S.sel) throw { what: "Сначала выбери момент.", hint: "Вставь ответ Claude или найди момент на шаге «Момент»." };
  if (n === 3 && !S.prep) return enterMontage();
  setStep(n);
}
document.querySelectorAll("#steps li").forEach((li) => {
  li.tabIndex = 0; li.setAttribute("role", "button");
  li.onclick = guard(() => goStep(+li.dataset.step));
  li.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); li.click(); } };
});
[1, 2, 3, 4].forEach((n) => {
  const row = document.createElement("div"); row.className = "navrow";
  if (n > 1) row.insertAdjacentHTML("beforeend", `<button class="ghost back">← Назад: ${STEP_NAMES[n - 1]}</button>`);
  if (n < 4) row.insertAdjacentHTML("beforeend", `<button class="ghost fwd" data-to="${n + 1}" hidden>Вперёд: ${STEP_NAMES[n + 1]} →</button>`);
  const back = row.querySelector(".back"), fwd = row.querySelector(".fwd");
  if (back) back.onclick = guard(() => goStep(n - 1));
  if (fwd) fwd.onclick = guard(() => goStep(n + 1));
  document.getElementById("step-" + n).prepend(row);
});
setStep(S.step);
/* ---------- настройки ---------- */
const loadSettings = guard(async () => {
  const s = await api("settings");
  $("#set-out").value = s.output_dir; $("#set-model").value = s.whisper_model; $("#set-subs").checked = s.subtitles_default;
});
$("#set-save").onclick = guard(async () => {
  const s = await api("settings", { output_dir: $("#set-out").value.trim(), whisper_model: $("#set-model").value, subtitles_default: $("#set-subs").checked });
  $("#subs").checked = s.subtitles_default; banner({ what: "Настройки сохранены.", hint: "" }, true);
});
$("#set-open").onclick = guard(() => api("open_output", {}));
