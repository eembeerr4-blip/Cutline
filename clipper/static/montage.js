"use strict";
/* Монтаж: границы по фразам, холодное начало, crop, сомнительные слова. Работает поверх глобального S из app.js. */
const video = () => $("#srcv");
let doubtTimer = null;
const srcT = () => video().currentTime + (S.prep ? S.prep.offset : 0);

async function enterMontage() {
  const body = { start: S.sel.start, end: S.sel.end };
  if (S.open) { body.open_start = S.open[0]; body.open_end = S.open[1]; }
  S.prep = null;
  S.prep = await runJob(await api(`project/${S.name}/prepare`, body), "Готовлю видео…");
  const v = video();
  v.src = `/api/project/${S.name}/source?t=${TOKEN}`;
  v.onerror = () => { $("#vhint").textContent = "Браузер не показывает это видео. Границы можно задавать по расшифровке справа."; };
  $("#vhint").textContent = S.prep.offset ? `Скачан только кусок: доступно ${fmt(S.prep.offset)}–${fmt(S.prep.offset + S.prep.duration)}. За его пределами видео докачается при сборке.` : "";
  setBuilt(false); sum3(); loadDoubts(); guard(showDupes)(); setStep(3);
}

function setBuilt(on) {
  $("#go3").textContent = on ? "Пересобрать" : "Собрать ролик";
  $("#go3").className = on ? "ghost" : "main";
  $("#go3b").hidden = !on;
  if (!on) { $("#video-wrap").hidden = true; $("#out-info").hidden = true; list($("#checks"), []); }
}
function sum3() {
  const d = S.sel.end - S.sel.start, [lo, hi] = S.window;
  $("#sum3").innerHTML = `Отрезок <b>${fmt(S.sel.start)}–${fmt(S.sel.end)}</b>, длина ${fmt(d)}`
    + (d < lo || d > hi ? ` <b style="color:var(--warn)">вне окна ${fmt(lo)}–${fmt(hi)}</b>` : "")
    + (S.open ? `<br>Холодное начало: ${fmt(S.open[0])}–${fmt(S.open[1])}` : "") + (S.crop ? `<br>Crop: ${S.crop}` : "");
}
async function showDupes() {
  const d = await api(`project/${S.name}/dupes`, { start: S.sel.start, end: S.sel.end });
  banner(d.length ? { what: "Этот отрезок уже использован в прежнем клипе.", hint: [...new Set(d.map((x) => x.text))].join(" ") } : null, true);
}
function changed() { guard(showDupes)(); renderRange(); sum3(); setBuilt(false); clearTimeout(doubtTimer); doubtTimer = setTimeout(guard(loadDoubts), 400); }
function cur() {
  const p = S.phrases[S.cur];
  if (!p) throw { what: "Фраза не выбрана.", hint: "Кликни по фразе справа или включи видео: курсор идёт за ним." };
  return p;
}
function setCur(i, seek) {
  S.cur = i; markStrip();
  const el = $("#strip3").children[i];
  if (el && (seek || !video().paused)) $("#strip3").scrollTop = el.offsetTop - 120;
  if (seek) video().currentTime = Math.max(0, S.phrases[i].start - (S.prep ? S.prep.offset : 0));
}
$("#strip3").addEventListener("click", (e) => { const r = e.target.closest(".ph"); if (r) setCur(+r.dataset.i, true); });
video().addEventListener("timeupdate", () => {
  const t = srcT(); let lo = 0, hi = S.phrases.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (S.phrases[m].start <= t) lo = m; else hi = m - 1; }
  if (lo !== S.cur) setCur(lo, false);
});

const act = (fn) => guard(async () => { fn(); });
function setStart() { const p = cur(); if (p.start >= S.sel.end) throw { what: "Начало должно быть раньше конца.", hint: "Выбери фразу левее конца." }; S.sel.start = p.start; changed(); }
function setEnd() { const p = cur(); if (p.end <= S.sel.start) throw { what: "Конец должен быть позже начала.", hint: "Выбери фразу правее начала." }; S.sel.end = p.end; changed(); }
function overlaps(o) { return o[0] < S.sel.end && o[1] > S.sel.start; }
function openEdge(startSide) {
  const p = cur(); const o = S.open ? [...S.open] : [p.start, p.end];
  if (startSide) { o[0] = p.start; if (o[1] <= o[0]) o[1] = p.end; } else { o[1] = p.end; if (o[0] >= o[1]) o[0] = p.start; }
  if (overlaps(o)) throw { what: "Холодное начало пересекается с основным отрезком.", hint: "Возьми сильный кусок вне основного отрезка." };
  S.open = o; changed();
}
$("#b-start").onclick = act(setStart); $("#b-end").onclick = act(setEnd);
$("#o-start").onclick = act(() => openEdge(true)); $("#o-end").onclick = act(() => openEdge(false));
$("#o-clear").onclick = act(() => { S.open = null; changed(); });
document.addEventListener("keydown", (e) => {
  if (S.step !== 3 || /INPUT|TEXTAREA/.test(e.target.tagName) || e.ctrlKey || e.altKey) return;
  const m = { "[": setStart, "]": setEnd, ",": () => openEdge(true), ".": () => openEdge(false) }[e.key];
  if (m) { e.preventDefault(); act(m)(); }
});

/* ---- сомнительные слова ---- */
async function loadDoubts() {
  const items = await api(`project/${S.name}/doubts`, { start: S.sel.start, end: S.sel.end, open: S.open });
  const fixed = (w) => (S.fixes.find((f) => f[0] === w) || [])[1];
  const left = items.filter((d) => !S.ok[d.t] && !fixed(d.word)).length;
  $("#doubt-h").textContent = items.length ? (left ? `Слова, в которых расшифровка могла ошибиться: ${left}. Можно не проверять, решение за тобой` : "Слова проверены") : "Сомнительных слов нет";
  $("#doubts").innerHTML = items.map((d) => {
    const fx = fixed(d.word), done = S.ok[d.t] || fx;
    return `<li class="${done ? "done" : ""}"><button class="ghost" data-t="${d.t}" data-a="play" title="Послушать 3 секунды" aria-label="Послушать 3 секунды">▶</button>`
      + `<span>${fmt(d.t)}</span><span class="w">${esc(d.word)}${fx ? " → " + esc(fx) : ""}</span><span class="grow">${esc(d.why)}</span>`
      + `<button class="ghost" data-t="${d.t}" data-a="ok">Верно</button><button class="ghost" data-t="${d.t}" data-w="${esc(d.word)}" data-a="fix">Исправить</button></li>`;
  }).join("");
}
$("#doubts").addEventListener("click", guard(async (e) => {
  const b = e.target.closest("button"); if (!b) return;
  const t = +b.dataset.t, v = video();
  if (b.dataset.a === "play") { v.currentTime = Math.max(0, t - 1.5 - (S.prep ? S.prep.offset : 0)); v.play(); setTimeout(() => v.pause(), 3000); return; }
  if (b.dataset.a === "ok") S.ok[t] = true;
  if (b.dataset.a === "fix") {
    const w = b.dataset.w, nv = await ask("Исправить слово", `Как правильно вместо «${w}»?`, "Исправить", w);
    if (!nv || nv === w) return;
    S.fixes = S.fixes.filter((f) => f[0] !== w).concat([[w, nv]]); S.ok[t] = true; setBuilt(false);
  }
  await loadDoubts();
}));

/* ---- crop рамкой на стоп-кадре ---- */
$("#grab").onclick = act(() => {
  const img = $("#frame"); img.onload = () => { $("#frame-wrap").hidden = false; };
  img.src = `/api/project/${S.name}/frame?at=${srcT().toFixed(2)}&t=${TOKEN}`;
});
$("#crop-clear").onclick = act(() => { S.crop = null; $("#crop-rect").hidden = true; $("#crop-info").textContent = ""; changed(); });
(() => {
  const wrap = $("#frame-wrap"), rect = $("#crop-rect"); let a = null;
  const pos = (e) => { const r = $("#frame").getBoundingClientRect(); return [Math.min(Math.max(e.clientX - r.left, 0), r.width), Math.min(Math.max(e.clientY - r.top, 0), r.height)]; };
  wrap.addEventListener("mousedown", (e) => { a = pos(e); rect.hidden = false; });
  window.addEventListener("mousemove", (e) => {
    if (!a) return; const b = pos(e);
    Object.assign(rect.style, { left: Math.min(a[0], b[0]) + "px", top: Math.min(a[1], b[1]) + "px", width: Math.abs(a[0] - b[0]) + "px", height: Math.abs(a[1] - b[1]) + "px" });
  });
  window.addEventListener("mouseup", (e) => {
    if (!a) return; const b = pos(e), img = $("#frame"), k = img.naturalWidth / img.clientWidth;
    const even = (n) => Math.max(2, Math.round(n) & ~1);
    const w = even(Math.abs(a[0] - b[0]) * k), h = even(Math.abs(a[1] - b[1]) * k);
    if (w < 64 || h < 64) { rect.hidden = true; } else {
      S.crop = `${even(Math.min(a[0], b[0]) * k)}:${even(Math.min(a[1], b[1]) * k)}:${w}:${h}`;
      $("#crop-info").textContent = `рамка ${w}×${h}`; changed();
    }
    a = null;
  });
})();

/* ---- сборка ---- */
async function autoBuild() {
  await $("#go3").onclick();
  if (S.built && !document.querySelector("#checks .FAIL")) { setStep(4); banner({ what: "Ролик собран и проверен, текст поста уже на шаге «Текст».", hint: "Файл в папке «Готовые видео»." }, true); }
}
$("#go3").onclick = guard(async () => {
  $("#go3").disabled = true;
  try {
    const job = await api(`project/${S.name}/build`, { start: S.sel.start, end: S.sel.end, open: S.open, subtitles: $("#subs").checked, fixes: S.fixes, crop: S.crop });
    const r = await runJob(job, "Собираю ролик…");
    const dd = await api(`project/${S.name}/doubts`, { start: S.sel.start, end: S.sel.end, open: S.open });
    const left = dd.filter((d) => !S.ok[d.t] && !S.fixes.find((f) => f[0] === d.word)).length;
    $("#video").src = `/api/project/${S.name}/video?t=${TOKEN}&v=${Date.now()}`; $("#video-h").textContent = "Готовый ролик";
    setBuilt(true); S.built = true; $("#video-wrap").hidden = false; showOut(r.published);
    list($("#checks"), [...r.checks, ...r.warnings.map((m) => ["WARN", m]), ...(left ? [["WARN", `${left} слов не проверены: решение за тобой`]] : [])]);
  } finally { $("#go3").disabled = false; }
});
$("#go3b").onclick = () => setStep(4);
function showOut(path) { $("#out-info").hidden = !path; $("#out-path").textContent = path || ""; }
$("#open-out").onclick = guard(() => api(`project/${S.name}/open_folder`, {}));
async function showClip(p) {
  showOut(p.published);
  setBuilt(true); $("#video").src = `/api/project/${p.name}/video?t=${TOKEN}`; $("#video-wrap").hidden = false;
  if (p.checks) list($("#checks"), p.checks);
}

/* ---- предпросмотр: быстрый просмотр монтажа до финальной сборки ---- */
$("#prev3").onclick = guard(async () => {
  $("#prev3").disabled = true;
  try {
    const job = await api(`project/${S.name}/preview`, { start: S.sel.start, end: S.sel.end, open: S.open, subtitles: $("#subs").checked, fixes: S.fixes, crop: S.crop });
    const r = await runJob(job, "Собираю предпросмотр…");
    $("#video").src = `/api/project/${S.name}/preview_video?t=${TOKEN}&v=${Date.now()}`;
    $("#video-h").textContent = "Предпросмотр (быстро, низкое качество). Финальный ролик будет чётким";
    $("#video-wrap").hidden = false; $("#out-info").hidden = true;
    list($("#checks"), [["OK", `Предпросмотр ${fmt(r.duration)}: смотри границы, субтитры и звук. Нравится: нажми «Собрать ролик».`], ...r.notes.map((m) => ["WARN", m])]);
    $("#video-wrap").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } finally { $("#prev3").disabled = false; }
});
