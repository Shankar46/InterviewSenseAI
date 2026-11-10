// Run: npm install && npm run test:frontend
// Loads the SAME marked / DOMPurify versions index.html pins, plus the real ui.js,
// and throws attack payloads at them. Guards the XSS fix against regressions.
const { JSDOM } = require("jsdom");
const path = require("path");
const fs = require("fs");
const R = path.join(__dirname, "..") + path.sep;
const MARKED = path.join(__dirname, "../../node_modules/marked/marked.min.js");
const PURIFY = path.join(__dirname, "../../node_modules/dompurify/dist/purify.min.js");
const dom = new JSDOM(`<body><div id="toast-container"></div><div id="notif-list"></div><div id="notif-empty"></div></body>`,
  { runScripts: "outside-only", pretendToBeVisual: true });
const w = dom.window;
w.eval(fs.readFileSync(MARKED, "utf8"));
w.eval(fs.readFileSync(PURIFY, "utf8"));
w.eval(fs.readFileSync(R + "scripts/ui.js", "utf8") + "\nwindow.UI = UI;");
const UI = w.UI;
let fail = 0;
const check = (name, ok, extra="") => { console.log((ok ? "PASS " : "FAIL ") + name + (ok ? "" : "  -> " + extra)); if (!ok) fail++; };

const payloads = {
  "img onerror":       '<img src=x onerror="window.pwned=1">',
  "script tag":        '<script>window.pwned=1</script>',
  "svg onload":        '<svg onload="window.pwned=1"><circle/></svg>',
  "javascript: link":  '[click](javascript:window.pwned=1)',
  "iframe srcdoc":     '<iframe srcdoc="<script>parent.pwned=1</script>"></iframe>',
  "markdown+html mix": '**ok** <b onmouseover="window.pwned=1">x</b>',
  "fake login form":   '<form action="https://evil.example"><input name=password><button>Sign in</button></form>',
  "math mXSS carrier": '<math><mtext><table><mglyph><style><img src=x onerror="window.pwned=1">',
};
for (const [name, p] of Object.entries(payloads)) {
  const html = UI.safeMarkdown(p);
  const holder = w.document.createElement("div"); holder.innerHTML = html; w.document.body.appendChild(holder);
  const bad = /onerror|onload|onmouseover|<script|javascript:|<iframe|<form|<input|<button|<svg|<math/i.test(holder.innerHTML);
  check("markdown XSS blocked: " + name, !bad, holder.innerHTML);
}
const good = UI.safeMarkdown("## Title\n\n**bold** and `code`\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n[docs](https://example.com)");
check("normal markdown still renders (h2, strong, code, table)", /<h2/.test(good) && /<strong>/.test(good) && /<code>/.test(good) && /<table>/.test(good), good);
check("links get rel=noopener + target=_blank", /rel="noopener noreferrer"/.test(good) && /target="_blank"/.test(good), good);

// notifications + toasts: HTML in server strings must be shown as text
UI.renderNotifications([{ type: "info", title: "<img src=x onerror=window.pwned=1>", body: "Dev <script>window.pwned=1</script> @ Acme", created_at: "10:00" }]);
const nl = w.document.getElementById("notif-list");
check("notification renders as text, no elements injected", nl.querySelector("img,script") === null && /<img/.test(nl.textContent), nl.innerHTML);
UI.showToast('<img src=x onerror="window.pwned=1">', "warning");
const tc = w.document.getElementById("toast-container");
check("toast renders as text, no elements injected", tc.querySelector("img") === null && /<img/.test(tc.textContent), tc.innerHTML);

// fail-closed: if DOMPurify did not load, never emit raw HTML
const dom2 = new JSDOM(`<body></body>`, { runScripts: "outside-only" });
dom2.window.eval(fs.readFileSync(MARKED, "utf8"));
dom2.window.eval(fs.readFileSync(R + "scripts/ui.js", "utf8") + "\nwindow.UI = UI;");
const out = dom2.window.UI.safeMarkdown('<img src=x onerror="window.pwned=1">');
check("fails closed when DOMPurify is missing (escaped text)", !/<img/i.test(out) && /&lt;img/.test(out), out);
check("no payload executed (window.pwned unset)", w.pwned === undefined && dom2.window.pwned === undefined);
console.log(fail ? `\n${fail} FAILED` : "\nall XSS checks passed");
process.exit(fail ? 1 : 0);
