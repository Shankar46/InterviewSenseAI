// Run: npm install && npm run test:frontend
// Drives the REAL frontend/scripts/auth.js in jsdom with a stubbed fetch, to guard the
// sign-up / sign-in behaviour: sign-up signs you in, passwords are never trimmed,
// the browser is told whether the password is new or existing, and errors are shown.
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const HTML = `<body>
  <div id="auth-screen"><h2 id="auth-card-title">Welcome Back</h2><p id="auth-card-subtitle"></p>
    <form id="auth-form">
      <input type="text" id="auth-username" autocomplete="username">
      <input type="password" id="auth-password" autocomplete="current-password" placeholder="Enter your password">
      <button type="submit" id="auth-submit-btn"><span>Sign In</span></button>
    </form>
    <span id="auth-toggle-msg"></span><button type="button" id="auth-toggle-btn">Sign Up</button></div>
  <div id="gateway" class="gw-hidden"></div><div id="app"></div>
  <span id="topbar-username-display"></span></body>`;

let failures = 0;
const check = (name, ok, extra = "") => {
  console.log((ok ? "PASS " : "FAIL ") + name + (ok ? "" : "  -> " + extra));
  if (!ok) failures++;
};
const tick = () => new Promise(r => setTimeout(r, 0));

function makeEnv(respond) {
  const dom = new JSDOM(HTML, { runScripts: "outside-only", url: "http://localhost/" });
  const w = dom.window;
  const env = { w, toasts: [], calls: [], rehydrated: 0 };
  w.CONFIG = { BACKEND_URL: "http://api" };
  w.UI = { showToast: (m, t) => env.toasts.push([m, t]) };
  w.Store = { rehydrate: () => env.rehydrated++, clearAll: () => {} };
  w.fetch = async (url, opts = {}) => {
    const body = opts.body && typeof opts.body.get === "function"
      ? { username: opts.body.get("username"), password: opts.body.get("password") } : null;
    env.calls.push({ url, body });
    const { status = 200, json = {} } = respond(url) || {};
    return { ok: status >= 200 && status < 300, status, json: async () => json };
  };
  w.eval(fs.readFileSync(path.join(__dirname, "../scripts/auth.js"), "utf8") + "\nwindow.Auth = Auth;");
  w.Auth.init();
  const $ = id => w.document.getElementById(id);
  env.$ = $;
  env.toSignUp = () => $("auth-toggle-btn").click();
  env.submit = async (user, pass) => {
    $("auth-username").value = user;
    $("auth-password").value = pass;
    $("auth-form").dispatchEvent(new w.Event("submit", { cancelable: true, bubbles: true }));
    await tick(); await tick();
  };
  return env;
}

(async () => {
  // 1. Sign-up signs you in
  let e = makeEnv(() => ({ status: 201, json: { status: "ok", token: "tok123", username: "newuser" } }));
  e.toSignUp();
  await e.submit("newuser", "a-good-passphrase");
  check("sign-up calls the register endpoint", e.calls.length === 1 && e.calls[0].url === "http://api/api/auth/register", JSON.stringify(e.calls));
  check("sign-up stores the session token", e.w.localStorage.getItem("isai_auth_token") === "tok123");
  check("sign-up stores the username", e.w.localStorage.getItem("isai_auth_username") === "newuser");
  check("sign-up hides the auth screen (you are in)", e.$("auth-screen").classList.contains("hidden"));
  check("sign-up shows the app gateway", !e.$("gateway").classList.contains("gw-hidden"));
  check("sign-up greets the new user", e.toasts.some(t => /Account created.*newuser/.test(t[0])), JSON.stringify(e.toasts));
  check("sign-up reloads stored chats for the new user", e.rehydrated === 1);
  check("form goes back to sign-in mode for next time", e.$("auth-card-title").textContent === "Welcome Back");

  // 2. The browser is told what kind of password this is
  e = makeEnv(() => ({ status: 401, json: { message: "x" } }));
  check("sign-in mode: autocomplete=current-password", e.$("auth-password").getAttribute("autocomplete") === "current-password");
  e.toSignUp();
  check("sign-up mode: autocomplete=new-password (lets the browser suggest a strong one)", e.$("auth-password").getAttribute("autocomplete") === "new-password");
  check("sign-up mode: placeholder states the minimum", /8 characters/.test(e.$("auth-password").placeholder));
  e.toSignUp();
  check("back to sign-in: autocomplete=current-password again", e.$("auth-password").getAttribute("autocomplete") === "current-password");

  // 3. Passwords are sent exactly as typed
  e = makeEnv(() => ({ status: 200, json: { token: "t", username: "u" } }));
  await e.submit("  spaced  ", "  my pass phrase  ");
  check("username is trimmed", e.calls[0].body.username === "spaced", JSON.stringify(e.calls[0].body));
  check("password is NOT trimmed", e.calls[0].body.password === "  my pass phrase  ", JSON.stringify(e.calls[0].body));

  // 4. Client-side rules apply to sign-up only
  e = makeEnv(() => ({ status: 201, json: { token: "t", username: "u" } }));
  e.toSignUp();
  await e.submit("validname", "short12");
  check("sign-up: 7-character password is stopped before any request", e.calls.length === 0 && e.toasts.some(t => /at least 8/.test(t[0])), JSON.stringify(e.toasts));
  await e.submit("ab", "long-enough-pass");
  check("sign-up: 2-character username is stopped before any request", e.calls.length === 0);

  e = makeEnv(() => ({ status: 200, json: { token: "t", username: "olduser" } }));
  await e.submit("olduser", "old123");        // 6 chars: legal when the account was created
  check("sign-in: an old 6-character password is still sent to the server", e.calls.length === 1);

  // 5. Server messages reach the user and nothing is stored
  for (const [label, status, message] of [
    ["name taken (409)", 409, "That username is already taken."],
    ["weak password (400)", 400, "That password is too common. Pick something harder to guess."],
    ["locked out (429)", 429, "Too many failed attempts. Try again in 15 minutes."],
    ["wrong password (401)", 401, "Invalid username or password."],
  ]) {
    e = makeEnv(() => ({ status, json: { status: "error", message } }));
    if (status !== 401 && status !== 429) e.toSignUp();
    await e.submit("someuser", "some-password-1");
    check(`${label}: message is shown`, e.toasts.some(t => t[0] === message), JSON.stringify(e.toasts));
    check(`${label}: no token is stored`, e.w.localStorage.getItem("isai_auth_token") === null);
    check(`${label}: the screen stays and the form is kept`,
      !e.$("auth-screen").classList.contains("hidden") && e.$("auth-password").value === "some-password-1");
    check(`${label}: the button works again`, e.$("auth-submit-btn").disabled === false);
  }

  console.log(failures ? `\n${failures} FAILED` : "\nall auth flow checks passed");
  process.exit(failures ? 1 : 0);
})();
