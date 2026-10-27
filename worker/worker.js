// Cloudflare Worker (free): exact-time scheduler + Telegram webhook for @inforuz_bot.
// Secrets (Settings -> Variables and Secrets): GH_TOKEN (GitHub fine-grained token), TG_BOT_TOKEN.
// Cron trigger: */5 * * * *
const REPO = "Boburreal/merch-check";

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
    return { chat: q.message.chat.id, mid: q.message.message_id, cb: q.data };
  }
  const m = u.message;
  if (!m) return null;
  let photo = "";
  if (m.photo && m.photo.length) photo = m.photo[m.photo.length - 1].file_id;
  else if (m.document && (m.document.mime_type || "").startsWith("image/")) photo = m.document.file_id;
  return { chat: m.chat.id, mid: m.message_id, text: (m.text || "").slice(0, 300), caption: (m.caption || "").slice(0, 300), photo };
}

const json = (o) => new Response(JSON.stringify(o), { headers: { "Content-Type": "application/json" } });

export default {
  async scheduled(event, env, ctx) {
    const t = new Date(Math.round(event.scheduledTime / 300000) * 300000);
    for (const [wf, inp] of jobs(t)) ctx.waitUntil(dispatch(env, wf, inp));
  },

  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const sec = await secret(env);
    if (url.pathname === "/setup") {
      const tg = await fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/setWebhook`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: `${url.origin}/tg`, secret_token: sec, allowed_updates: ["message", "callback_query"] }),
      }).then((r) => r.json());
      const gh = await dispatch(env, "snapshot.yml", {});
      return new Response(
        `Telegram: ${tg.ok ? "OK ✅" : "XATO ❌ " + tg.description}\n` +
        `GitHub: ${gh === 204 ? "OK ✅" : "XATO ❌ (" + gh + ") - tokenni tekshiring"}\n`,
        { headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
    if (url.pathname === "/tg" && req.method === "POST") {
      if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== sec) return new Response("forbidden", { status: 403 });
      const u = await req.json();
      const s = slim(u);
      if (!s) return new Response("ok");
      ctx.waitUntil(dispatch(env, "bot.yml", { update: JSON.stringify(s) }));
      if (u.callback_query) return json({ method: "answerCallbackQuery", callback_query_id: u.callback_query.id, text: "⏳ Бажарилмоқда..." });
      return json({ method: "sendChatAction", chat_id: s.chat, action: "typing" });
    }
    return new Response("merch-check worker ishlayapti");
  },
};
