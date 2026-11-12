// Cloudflare Worker (free): exact-time scheduler + Telegram webhook for @inforuz_bot.
// Secrets (Settings -> Variables and Secrets): GH_TOKEN, TG_BOT_TOKEN, SALES_LOGIN, SALES_PASSWORD, BAZA_BOT_TOKEN.
// Second bot (BAZA_BOT_TOKEN): branch requests in the "Sales ASKLEPIY" group -> baza.yml on GitHub.
// Cron trigger: */5 * * * *
// Heavy work (/tekshir checks) runs on GitHub Actions. Location deletion was removed 09.11.2026.
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
  // har soat; hisobot paytida emas (ikkalasi bir Sales akkauntida loyihani almashtirib, bir-birini sekinlashtiradi)
  if (m === 5 && h !== 12 && h !== 3 && h !== 4 && h !== 8 && h !== 9) out.push(["snapshot.yml", {}]);
  if (h === 12 && m === 5) out.push(["report.yml", { mode: "daily", auto: "1" }]);       // 17:05 -> fayl 17:45–17:55
  if (h === 3 && m === 30) out.push(["report.yml", { mode: "update", auto: "1" }]);      // 08:30
  if (h === 8 && m === 10) out.push(["az.yml", {}]);                                      // 13:10 Аудиозаписи (kechagi kun, ТП+МП): Gemini kunlik limiti 13:00 da yangilanadi
  if (wd === 0 && h === 18 && m === 0) out.push(["report.yml", { mode: "weekly", auto: "1" }]);  // yakshanba 23:00
  if (md === 1 && h === 4 && m === 0) out.push(["report.yml", { mode: "monthly", auto: "1" }]);  // 1-sana 09:00
  return out;
}

async function secret(env) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("hook|" + env.TG_BOT_TOKEN));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("").slice(0, 40);
}

async function bazaSecret(env) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("baza|" + env.BAZA_BOT_TOKEN));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("").slice(0, 40);
}

// group message -> what baza.py should do with it (null = not ours, nothing is started)
function bazaSlim(env, u) {
  const m = u.message;
  if (!m || !m.from || m.from.is_bot) return null;
  const text = (m.text || m.caption || "").slice(0, 3000);
  const base = { chat: m.chat.id, mid: m.message_id, from_id: m.from.id, first: m.from.first_name || "",
                 last: m.from.last_name || "", text };
  if (m.chat.type === "private") return { kind: "private", ...base };
  const botId = String(env.BAZA_BOT_TOKEN || "").split(":")[0];
  const r = m.reply_to_message;
  if (r && r.from && String(r.from.id) === botId) return { kind: "reply", reply_mid: r.message_id, ...base };
  if (/(^|\D)\d{9}(\D|$)/.test(text) && /(inn|инн|stir|стир|filial|филиал|фил|fil)/i.test(text)) return { kind: "request", ...base };
  return null;
}

function slim(u) {
  if (u.callback_query) {
    const q = u.callback_query;
    let cb = q.data;
    return { chat: q.message.chat.id, mid: q.message.message_id, cb };
  }
  const m = u.message;
  if (!m) return null;
  let photo = "";
  if (m.photo && m.photo.length) photo = m.photo[m.photo.length - 1].file_id;
  else if (m.document && (m.document.mime_type || "").startsWith("image/")) photo = m.document.file_id;
  return { chat: m.chat.id, mid: m.message_id, text: (m.text || "").slice(0, 300), caption: (m.caption || "").slice(0, 300), photo };
}


const json = (o) => new Response(JSON.stringify(o), { headers: { "Content-Type": "application/json" } });

function tgCall(env, method, body) {
  return fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }).then((r) => r.json());
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


export default {
  async scheduled(event, env, ctx) {
    const t = new Date(Math.round(event.scheduledTime / 300000) * 300000);
    for (const [wf, inp] of jobs(t)) ctx.waitUntil(dispatch(env, wf, inp));
  },

  async fetch(req_, env, ctx) {
    const url = new URL(req_.url);
    const sec = await secret(env);
    if (url.pathname === "/setup") {
      if (!env.SETUP_KEY || url.searchParams.get("key") !== env.SETUP_KEY) {
        return new Response("Forbidden: ?key= kerak (Worker'ga SETUP_KEY secret qo'ying)", { status: 403 });
      }
      const tg = await fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/setWebhook`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: `${url.origin}/tg`, secret_token: sec, allowed_updates: ["message", "callback_query"] }),
      }).then((r) => r.json());
      let baza = "kalit qo'shilmagan";
      if (env.BAZA_BOT_TOKEN) {
        const b = await fetch(`https://api.telegram.org/bot${env.BAZA_BOT_TOKEN}/setWebhook`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: `${url.origin}/baza`, secret_token: await bazaSecret(env), allowed_updates: ["message"] }),
        }).then((r) => r.json());
        baza = b.ok ? "OK ✅" : "XATO ❌ " + b.description;
      }
      const gh = await dispatch(env, "snapshot.yml", {});
      let sales = "kalit qo'shilmagan";
      if (env.SALES_LOGIN && env.SALES_PASSWORD) {
        try { await salesLogin(env); sales = "OK ✅"; } catch (e) { sales = "XATO ❌ " + e.message; }
      }
      return new Response(
        `Telegram: ${tg.ok ? "OK ✅" : "XATO ❌ " + tg.description}\n` +
        `GitHub: ${gh === 204 ? "OK ✅" : "XATO ❌ (" + gh + ") - tokenni tekshiring"}\n` +
        `Sales: ${sales}\n` +
        `Baza bot: ${baza}\n`,
        { headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
    if (url.pathname === "/baza" && req_.method === "POST" && env.BAZA_BOT_TOKEN) {
      if (req_.headers.get("X-Telegram-Bot-Api-Secret-Token") !== (await bazaSecret(env))) return new Response("forbidden", { status: 403 });
      const s = bazaSlim(env, await req_.json());
      if (s) ctx.waitUntil(dispatch(env, "baza.yml", { update: JSON.stringify(s) }));
      return new Response("ok");
    }
    if (url.pathname === "/tg" && req_.method === "POST") {
      if (req_.headers.get("X-Telegram-Bot-Api-Secret-Token") !== sec) return new Response("forbidden", { status: 403 });
      const u = await req_.json();
      if (u.callback_query) {   // /tekshir buttons (period choice) -> bot.yml
        const q = u.callback_query;
        ctx.waitUntil(tgCall(env, "answerCallbackQuery", { callback_query_id: q.id }));
        ctx.waitUntil(tgCall(env, "sendMessage", { chat_id: q.message.chat.id, text: "⏳" }));
        ctx.waitUntil(dispatch(env, "bot.yml", { update: JSON.stringify(slim(u)) }));
        return json({ method: "editMessageReplyMarkup", chat_id: q.message.chat.id, message_id: q.message.message_id, reply_markup: { inline_keyboard: [] } });
      }
      const s = slim(u);
      if (!s) return new Response("ok");
      ctx.waitUntil(dispatch(env, "bot.yml", { update: JSON.stringify(s) }));
      return json({ method: "sendChatAction", chat_id: s.chat, action: "typing" });
    }
    return new Response("merch-check worker ishlayapti");
  },
};
