// Cloudflare Worker (free): exact-time scheduler + Telegram webhook for @inforuz_bot.
// Secrets (Settings -> Variables and Secrets): GH_TOKEN, TG_BOT_TOKEN, SALES_LOGIN, SALES_PASSWORD.
// Cron trigger: */5 * * * *
// Heavy work (screenshot reading, 3-month visit history) runs on GitHub Actions;
// ticking people, the analytics and deleting a location run here, in seconds.
const REPO = "Boburreal/merch-check";
const BASE = "https://sales.asklepiygroup.uz";

async function dispatch(env, wf, inputs) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${wf}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json",
      "User-Agent": "merch-worker", "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs }),
  });
  return r.status; // 204 = OK
}

// times in UTC (Tashkent = UTC+5)
function jobs(d) {
  const h = d.getUTCHours(), m = d.getUTCMinutes(), wd = d.getUTCDay(), md = d.getUTCDate();
  const out = [];
  if (m === 5) out.push(["snapshot.yml", {}]);                                           // har soat
  if (h === 12 && m === 30) out.push(["report.yml", { mode: "daily", auto: "1" }]);      // 17:30
  if (h === 3 && m === 30) out.push(["report.yml", { mode: "update", auto: "1" }]);      // 08:30
  if (wd === 0 && h === 18 && m === 0) out.push(["report.yml", { mode: "weekly", auto: "1" }]);  // yakshanba 23:00
  if (md === 1 && h === 4 && m === 0) out.push(["report.yml", { mode: "monthly", auto: "1" }]);  // 1-sana 09:00
  return out;
}

async function secret(env) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("hook|" + env.TG_BOT_TOKEN));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("").slice(0, 40);
}

function slim(u) {
  if (u.callback_query) {
    const q = u.callback_query;
    let cb = q.data;
    if (cb.startsWith("go:")) cb = cb + ":" + ticked(q).join(",");
    return { chat: q.message.chat.id, mid: q.message.message_id, cb };
  }
  const m = u.message;
  if (!m) return null;
  let photo = "";
  if (m.photo && m.photo.length) photo = m.photo[m.photo.length - 1].file_id;
  else if (m.document && (m.document.mime_type || "").startsWith("image/")) photo = m.document.file_id;
  return { chat: m.chat.id, mid: m.message_id, text: (m.text || "").slice(0, 300), caption: (m.caption || "").slice(0, 300), photo };
}

function ticked(q) {
  const rows = (q.message.reply_markup || {}).inline_keyboard || [];
  return rows.flat().filter((b) => (b.callback_data || "").startsWith("t:") && b.text.startsWith("✅"))
    .map((b) => b.callback_data.slice(2));
}

const json = (o) => new Response(JSON.stringify(o), { headers: { "Content-Type": "application/json" } });
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function tgCall(env, method, body) {
  return fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }).then((r) => r.json());
}

// ------------------------------------------------------------------ analytics from the hidden context
async function readCtx(msg) {
  for (const e of msg.entities || []) {
    if (e.type === "text_link" && (e.url || "").includes("#c=")) {
      let b = e.url.split("#c=")[1].replace(/-/g, "+").replace(/_/g, "/");
      while (b.length % 4) b += "=";
      const bytes = Uint8Array.from(atob(b), (c) => c.charCodeAt(0));
      const txt = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"))).text();
      return JSON.parse(txt);
    }
  }
  return null;
}

function analytics(c, sel) {
  const chosen = new Set(sel.map(Number).filter((i) => i < c.p.length));
  const L = [...c.h, `\n📊 <b>Охирги 3 ой (${c.d1}–${c.d2}): ${c.n} та визит</b>`, "\n✅ <b>Бириктирилган ходимлар (сиз белгилаган):</b>"];
  if (!chosen.size) L.push(" — ҳеч ким белгиланмади");
  for (const i of chosen) {
    const [emp, grp, n, first, last, ago] = c.p[i];
    L.push(n ? ` • ${esc(emp)} (${grp}) — <b>${n}</b> марта, ${first}…${last}, охиргиси ${ago} кун олдин`
      : ` • ${esc(emp)} — ⚠️ 3 ойда <b>бирор марта ҳам бормаган</b>`);
  }
  const other = c.p.filter((p, i) => !chosen.has(i) && p[2] > 0);
  if (other.length) {
    L.push("\n❗️ <b>Бириктирилмаган, лекин визит қилган:</b>");
    for (const [emp, grp, n, first, last] of other) L.push(` • ${esc(emp)} (${grp}) — <b>${n}</b> марта, ${first}…${last}`);
  }
  if (c.r.length) L.push("\n🕒 Охирги визитлар:", ...c.r, "📅 Ойлар бўйича: " + c.mo);
  if (c.lg.length) L.push("\n🔁 <b>Локация ўзгаришлари:</b>", ...c.lg);
  if (c.of.length) L.push("\n⚠️ <b>Шу аптекадаги шубҳали визитлар:</b>", ...c.of);
  let kb = [];
  if (c.loc) {
    L.push("\n<b>Локацияни ўчирайми?</b>");
    kb = [[{ text: "🗑 Ҳа, ўчир", callback_data: `del:${c.id}` }, { text: "❌ Йўқ", callback_data: `no:${c.id}` }]];
  }
  return { text: L.join("\n"), kb };
}

// ------------------------------------------------------------------ Sales: login, project, edit form
class Jar {
  constructor() { this.c = {}; }
  take(res) {
    for (const sc of res.headers.getSetCookie ? res.headers.getSetCookie() : []) {
      const kv = sc.split(";")[0]; const i = kv.indexOf("=");
      if (i > 0) this.c[kv.slice(0, i).trim()] = kv.slice(i + 1);
    }
  }
  get header() { return Object.entries(this.c).map(([k, v]) => `${k}=${v}`).join("; "); }
}

async function req(jar, url, opt = {}) {
  const go = (u, o) => {
    const h = new Headers(o.headers || {});
    h.set("Cookie", jar.header); h.set("User-Agent", "Mozilla/5.0 merch-check");
    return fetch(u, { ...o, headers: h, redirect: "manual" });
  };
  let r = await go(url, opt); jar.take(r);
  for (let n = 0; n < 5 && [301, 302, 303, 307, 308].includes(r.status); n++) {
    url = new URL(r.headers.get("Location"), url).toString();
    r = await go(url, {}); jar.take(r);
  }
  return { r, url };
}

const unent = (s) => String(s)
  .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
  .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(+d))
  .replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&");

async function salesLogin(env) {
  const jar = new Jar();
  const a = await req(jar, `${BASE}/login`);
  const t = (await a.r.text()).match(/name="_token" value="([^"]+)"/)[1];
  const body = new URLSearchParams({ _token: t, email: env.SALES_LOGIN, password: env.SALES_PASSWORD, remember: "on" });
  const b = await req(jar, `${BASE}/login`, { method: "POST", body, headers: { "Content-Type": "application/x-www-form-urlencoded" } });
  const txt = await b.r.text();
  if (b.url.includes("/login") || txt.includes('name="password"')) throw new Error("Sales'га кириб бўлмади (логин/парол)");
  return jar;
}

async function switchProject(jar, pid) {
  const { r } = await req(jar, `${BASE}/visits/reports`);
  const h = await r.text();
  const csrf = h.match(/data-csrf="([^"]+)"/)[1];
  const upd = unent(h.match(/data-update-uri="([^"]+)"/)[1]);
  for (const m of h.matchAll(/wire:snapshot="([^"]+)"/g)) {
    const raw = unent(m[1]);
    let j; try { j = JSON.parse(raw); } catch { continue; }
    if (j.memo && j.memo.name === "project-select") {
      await req(jar, new URL(upd, BASE).toString(), {
        method: "POST", body: JSON.stringify({ _token: csrf, components: [{ snapshot: raw, updates: { currentProjectId: String(pid) }, calls: [] }] }),
        headers: { "X-Livewire": "true", "Content-Type": "application/json", "X-CSRF-TOKEN": csrf, Referer: `${BASE}/visits/reports` },
      });
      return;
    }
  }
  throw new Error("project-select topilmadi");
}

// the edit form serialized exactly like a browser submits it
async function serializeForm(html) {
  const out = []; let sel = null; let ta = null;
  const rw = new HTMLRewriter()
    .on("form.edit_form input", { element(e) {
      const n = e.getAttribute("name"); if (!n || e.hasAttribute("disabled")) return;
      const t = (e.getAttribute("type") || "text").toLowerCase();
      if (["submit", "button", "image", "reset", "file"].includes(t)) return;
      if (t === "checkbox" || t === "radio") { if (e.hasAttribute("checked")) out.push([unent(n), unent(e.getAttribute("value") ?? "on")]); return; }
      out.push([unent(n), unent(e.getAttribute("value") ?? "")]);
    } })
    .on("form.edit_form select", { element(e) {
      const s = { n: unent(e.getAttribute("name") || ""), multiple: e.hasAttribute("multiple"), opts: [], skip: !e.getAttribute("name") || e.hasAttribute("disabled") };
      out.push(s); sel = s; e.onEndTag(() => { sel = null; });
    } })
    .on("form.edit_form option", {
      element(e) { if (sel) sel.opts.push({ v: e.getAttribute("value"), on: e.hasAttribute("selected"), txt: "" }); },
      text(t) { if (sel && sel.opts.length) sel.opts[sel.opts.length - 1].txt += t.text; },
    })
    .on("form.edit_form textarea", {
      element(e) { const s = { n: unent(e.getAttribute("name") || ""), ta: true, txt: "", skip: !e.getAttribute("name") || e.hasAttribute("disabled") }; out.push(s); ta = s; e.onEndTag(() => { ta = null; }); },
      text(t) { if (ta) ta.txt += t.text; },
    });
  await rw.transform(new Response(html)).text();
  const res = [];
  for (const x of out) {
    if (Array.isArray(x)) { res.push(x); continue; }
    if (x.skip) continue;
    if (x.ta) { res.push([x.n, unent(x.txt)]); continue; }
    const val = (o) => (o.v !== null ? unent(o.v) : unent(o.txt).trim());
    const on = x.opts.filter((o) => o.on);
    if (x.multiple) on.forEach((o) => res.push([x.n, val(o)]));
    else if (x.opts.length) res.push([x.n, val(on.length ? on[on.length - 1] : x.opts[0])]);
  }
  return res;
}

const field = (f, k) => (f.find((x) => x[0] === k) || [null, ""])[1];

async function deleteIn(jar, cid, dry) {
  const url = `${BASE}/lists/companies/${cid}/edit`;
  const page = await (await req(jar, url)).r.text();
  if (!page.includes('class="edit_form"')) return null;
  const before = await serializeForm(page);
  const loc = field(before, "location"), name = field(before, "name");
  if (dry) return { st: "dry", name, loc, fields: before };
  if (!loc.trim()) return { st: "already", name, loc };
  const fd = new FormData();
  for (const [k, v] of before) fd.append(k, k === "location" ? "" : v);
  const p = await req(jar, url, { method: "POST", body: fd, headers: { Referer: url } });
  const after = await serializeForm(await (await req(jar, url)).r.text());
  const keep = (f) => JSON.stringify(f.filter(([k]) => k !== "_token" && k !== "location"));
  if (field(after, "location").trim()) return { st: "failed", name, loc, msg: `HTTP ${p.r.status}, локация сақланиб қолди` };
  if (keep(after) !== keep(before)) {
    const a = new Set(after.map((x) => x.join("=")));
    const changed = [...new Set(before.filter((x) => !a.has(x.join("="))).map((x) => x[0]))].join(", ");
    return { st: "changed", name, loc, msg: changed };
  }
  return { st: "ok", name, loc };
}

async function deleteLocation(env, cid, dry = false) {
  const jar = await salesLogin(env);
  try {
    for (const p of [1, 4]) {
      await switchProject(jar, p);
      const r = await deleteIn(jar, cid, dry);
      if (r) return r;
    }
    return { st: "failed", name: "", loc: "", msg: "таҳрирлаш саҳифаси очилмади (ТП ва МП лойиҳаларида ҳам)" };
  } finally {
    await switchProject(jar, 1);       // leave the account on "Торговые представители"
  }
}

async function doDelete(env, chat, cid) {
  try {
    const r = await deleteLocation(env, cid);
    const nm = `<b>${esc(r.name)}</b> (ID ${cid})`;
    let text;
    if (r.st === "ok") {
      text = `✅ ${nm} — локация ўчирилди.\nЭски координата: <code>${esc(r.loc)}</code>\nБошқа маълумотлари ўзгармади (текширилди). Кимдир янги локация қўйса, хабар бераман.`;
      await dispatch(env, "bot.yml", { update: JSON.stringify({ chat, cb: `logdel:${cid}`, name: r.name, old: r.loc }) });
    } else if (r.st === "already") text = `ℹ️ ${nm} — локацияси аллақачон бўш экан.`;
    else if (r.st === "changed") text = `⚠️ ${nm} — локация ўчди, лекин бошқа майдонлар ҳам ўзгарган кўринди: ${esc(r.msg)}. Sales'да шу аптекани текшириб кўринг.`;
    else text = `❗️ ${nm} — ўчмади: ${esc(r.msg)}. Қўлда текшириб кўринг.`;
    await tgCall(env, "sendMessage", { chat_id: chat, text, parse_mode: "HTML" });
  } catch (e) {
    // fallback: the same job on GitHub (slower, but independent)
    await tgCall(env, "sendMessage", { chat_id: chat, text: `⏳ Тезкор ўчириш ишламади (${String(e.message || e).slice(0, 120)}), GitHub орқали ўчиряпман...` });
    await dispatch(env, "bot.yml", { update: JSON.stringify({ chat, mid: 0, cb: `del:${cid}` }) });
  }
}

export default {
  async scheduled(event, env, ctx) {
    const t = new Date(Math.round(event.scheduledTime / 300000) * 300000);
    for (const [wf, inp] of jobs(t)) ctx.waitUntil(dispatch(env, wf, inp));
  },

  async fetch(req_, env, ctx) {
    const url = new URL(req_.url);
    const sec = await secret(env);
    if (url.pathname === "/setup") {
      const tg = await fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/setWebhook`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: `${url.origin}/tg`, secret_token: sec, allowed_updates: ["message", "callback_query"] }),
      }).then((r) => r.json());
      const gh = await dispatch(env, "snapshot.yml", {});
      let sales = "kalit qo'shilmagan";
      if (env.SALES_LOGIN && env.SALES_PASSWORD) {
        try { await salesLogin(env); sales = "OK ✅"; } catch (e) { sales = "XATO ❌ " + e.message; }
      }
      return new Response(
        `Telegram: ${tg.ok ? "OK ✅" : "XATO ❌ " + tg.description}\n` +
        `GitHub: ${gh === 204 ? "OK ✅" : "XATO ❌ (" + gh + ") - tokenni tekshiring"}\n` +
        `Sales: ${sales}\n`,
        { headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
    // self-test from GitHub Actions: reads the edit form, changes nothing
    if (url.pathname === "/selftest" && url.searchParams.get("k") === sec) {
      const r = await deleteLocation(env, Number(url.searchParams.get("id")), true);
      return json(r);
    }
    if (url.pathname === "/tg" && req_.method === "POST") {
      if (req_.headers.get("X-Telegram-Bot-Api-Secret-Token") !== sec) return new Response("forbidden", { status: 403 });
      const u = await req_.json();
      const q = u.callback_query;
      if (q && (q.data || "").startsWith("t:")) {   // tick / untick a person instantly
        const kb = ((q.message.reply_markup || {}).inline_keyboard || []).map((row) => row.map((b) => {
          if (b.callback_data !== q.data) return b;
          return { ...b, text: (b.text.startsWith("✅") ? "☐" : "✅") + b.text.slice(1) };
        }));
        ctx.waitUntil(tgCall(env, "answerCallbackQuery", { callback_query_id: q.id }));
        return json({ method: "editMessageReplyMarkup", chat_id: q.message.chat.id, message_id: q.message.message_id,
                      reply_markup: { inline_keyboard: kb } });
      }
      if (q) {
        const chat = q.message.chat.id, data = q.data || "";
        ctx.waitUntil(tgCall(env, "answerCallbackQuery", { callback_query_id: q.id }));
        // remove the buttons at once so a second tap cannot start the same job twice
        const strip = json({ method: "editMessageReplyMarkup", chat_id: chat, message_id: q.message.message_id, reply_markup: { inline_keyboard: [] } });
        if (data.startsWith("go:")) {
          const c = await readCtx(q.message).catch(() => null);
          if (c) {
            const a = analytics(c, ticked(q));
            ctx.waitUntil(tgCall(env, "sendMessage", { chat_id: chat, text: a.text, parse_mode: "HTML", disable_web_page_preview: true,
                                                       ...(a.kb.length ? { reply_markup: { inline_keyboard: a.kb } } : {}) }));
            return strip;
          }
        }
        if (data.startsWith("del:") && env.SALES_LOGIN && env.SALES_PASSWORD) {
          ctx.waitUntil(tgCall(env, "sendMessage", { chat_id: chat, text: "⏳ Ўчирилмоқда..." }));
          ctx.waitUntil(doDelete(env, chat, Number(data.slice(4))));
          return strip;
        }
        if (data.startsWith("no:")) {
          ctx.waitUntil(tgCall(env, "sendMessage", { chat_id: chat, text: "❌ Бекор қилинди, локацияга тегилмади." }));
          return strip;
        }
        const msg = data.startsWith("go:") ? "⏳ Таҳлил қилинмоқда..." : data.startsWith("pick:") ? "⏳ Визитлар йиғилмоқда..." : "⏳";
        ctx.waitUntil(tgCall(env, "sendMessage", { chat_id: chat, text: msg }));
        ctx.waitUntil(dispatch(env, "bot.yml", { update: JSON.stringify(slim(u)) }));
        return strip;
      }
      const s = slim(u);
      if (!s) return new Response("ok");
      ctx.waitUntil(dispatch(env, "bot.yml", { update: JSON.stringify(s) }));
      if (s.photo || (s.text && !s.text.startsWith("/")))
        return json({ method: "sendMessage", chat_id: s.chat, text: "⏳ Қабул қилдим, аптека қидирилмоқда..." });
      return json({ method: "sendChatAction", chat_id: s.chat, action: "typing" });
    }
    return new Response("merch-check worker ishlayapti");
  },
};
