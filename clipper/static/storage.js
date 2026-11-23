"use strict";
/* Хранилище: проекты слева, корзина справа, кнопки над списками. Готовые ролики лежат в «Готовые видео» и при очистке не страдают. */
let TR = [];
const size = (b) => b >= 1e9 ? (b / 1e9).toFixed(1) + " ГБ" : b >= 1e6 ? (b / 1e6).toFixed(0) + " МБ" : b > 0 ? Math.max(1, Math.round(b / 1e3)) + " КБ" : "0";
const checked = (cls) => [...document.querySelectorAll(cls + ":checked")].map((x) => x.value);

function counters() {
  $("#st-cnt").textContent = `выбрано ${checked(".pj").length}`; $("#tr-cnt").textContent = `выбрано ${checked(".tr").length}`;
  const all = (cls, btn) => { const b = document.querySelectorAll(cls); $(btn).textContent = b.length && checked(cls).length === b.length ? "Снять выбор" : "Выбрать все"; };
  all(".pj", "#st-all-p"); all(".tr", "#st-all-t");
}
function toggleAll(cls) {
  const boxes = [...document.querySelectorAll(cls)], on = checked(cls).length !== boxes.length;
  boxes.forEach((b) => { b.checked = on; }); counters();
}
$("#st-all-p").onclick = () => toggleAll(".pj"); $("#st-all-t").onclick = () => toggleAll(".tr");

const loadStorage = guard(async () => {
  const r = await api("storage"); TR = r.trash;
  const trashTotal = r.trash.reduce((s, t) => s + t.size, 0);
  $("#st-sum").textContent = `Данные ${size(r.total)} · в корзине ${size(trashTotal)} · свободно ${size(r.free)}`;
  $("#st-list").innerHTML = r.projects.length ? r.projects.map((p) => `<label class="srow"><input type="checkbox" class="pj" value="${esc(p.name)}">`
    + `<span class="grow"><b>${esc(p.title)}</b><br><small class="muted">${esc((p.created || "").slice(0, 10))} · ${p.has_clip ? "ролик готов" : "без ролика"}${p.has_post ? ", текст сохранён" : ""}</small></span>`
    + `<span class="sz">${size(p.size)}</span></label>`).join("") : "<p class='muted'>Проектов пока нет.</p>";
  $("#st-trash").innerHTML = r.trash.length ? r.trash.map((t) => `<label class="srow"><input type="checkbox" class="tr" value="${esc(t.id)}">`
    + `<span class="grow">${esc(t.project || "загруженные файлы")}<br><small class="muted">${t.kind === "all" ? "проект целиком" : t.kind === "uploads" ? "загруженные файлы" : "скачанное видео и звук"} · ${esc(t.moved.replace("T", " "))}</small></span>`
    + `<span class="sz">${size(t.size)}</span></label>`).join("") : "<p class='muted'>Корзина пуста.</p>";
  document.querySelectorAll(".pj,.tr").forEach((b) => { b.onchange = counters; }); counters();
});

async function moved(r, okText, emptyText) {
  await loadStorage();
  if (!r.moved) { banner({ what: emptyText, hint: "" }, true); return; }
  banner({ what: `${okText}: ${r.moved}`, hint: "Они теперь справа, в корзине: оттуда можно вернуть." }, true);
}
const picked = () => { const n = checked(".pj"); if (!n.length) throw { what: "Ничего не выбрано.", hint: "Отметь проекты галочками слева или нажми «Выбрать все»." }; return n; };
$("#st-whole").onclick = guard(async () => moved(await api("storage/trash", { names: picked(), whole: true }), "В корзину перенесено проектов", "Ничего не перенесено."));
$("#st-older").onclick = guard(async () => {
  const days = parseInt($("#st-days").value, 10); if (!(days >= 0)) throw { what: "Не понимаю число дней.", hint: "Впиши целое число, например 30." };
  await moved(await api("storage/older", { days }), "Убрано скачанное из проектов", "Нечего убирать: скачанного видео старше этого срока нет.");
});
$("#st-cache").onclick = guard(async () => moved(await api("storage/cache", {}), "Убрано скачанное из проектов", "Нечего убирать: скачанных видео и звука нет."));
$("#st-open-out").onclick = guard(() => api("open_output", {}));
$("#st-restore").onclick = guard(async () => {
  const ids = checked(".tr"); if (!ids.length) throw { what: "В корзине ничего не выбрано.", hint: "Отметь галочками или нажми «Выбрать все»." };
  for (const id of ids) await api("storage/restore", { id });
  await loadStorage(); banner({ what: `Возвращено: ${ids.length}`, hint: "" }, true);
});
$("#st-purge").onclick = guard(async () => {
  const ids = checked(".tr"); if (!ids.length) throw { what: "В корзине ничего не выбрано.", hint: "Отметь галочками или нажми «Выбрать все»." };
  const total = TR.filter((t) => ids.includes(t.id)).reduce((s, t) => s + t.size, 0);
  if (!(await ask("Удалить навсегда?", `Элементов: ${ids.length}, размер ${size(total)}. Вернуть будет нельзя.`, "Удалить навсегда"))) return;
  const r = await api("storage/purge", { ids, confirm_bytes: total });
  await loadStorage(); banner({ what: `Удалено навсегда: ${size(r.freed)}`, hint: "" }, true);
});
