// frontend/scripts/auth.js
// Handles user authentication, credential validation, token storage, and logout.

const Auth = (() => {
  let isLoginMode = true;
  let token = null;
  let username = null;

  // ── DOM selectors ──────────────────────────────────────────
  const screen      = document.getElementById("auth-screen");
  const cardTitle   = document.getElementById("auth-card-title");
  const cardSub     = document.getElementById("auth-card-subtitle");
  const form        = document.getElementById("auth-form");
  const submitBtn   = document.getElementById("auth-submit-btn");
  const toggleMsg   = document.getElementById("auth-toggle-msg");
  const toggleBtn   = document.getElementById("auth-toggle-btn");
  const usernameInput = document.getElementById("auth-username");
  const passwordInput = document.getElementById("auth-password");

  const gateway     = document.getElementById("gateway");
  const appEl       = document.getElementById("app");

  // ── Getters ────────────────────────────────────────────────
  function getToken() {
    if (!token) token = localStorage.getItem("isai_auth_token");
    return token;
  }

  function getUsername() {
    if (!username) username = localStorage.getItem("isai_auth_username");
    return username;
  }

  // ── Authentication Checks ──────────────────────────────────
  async function checkAuth() {
    const localToken = getToken();
    const localUser = getUsername();

    if (!localToken || !localUser) {
      logoutCleanly(false); // Make sure local storage is cleaned up
      showScreen();
      return false;
    }

    try {
      // Validate the token with the server
      const res = await fetch(CONFIG.BACKEND_URL + "/api/auth/me", {
        method: "GET",
        headers: {
          "Authorization": `Bearer ${localToken}`
        }
      });

      if (res.ok) {
        const data = await res.json();
        username = data.username;
        localStorage.setItem("isai_auth_username", username);
        updateUserBadges(username);
        hideScreen();
        return true;
      } else {
        // Token is invalid/expired
        logoutCleanly(false);
        showScreen();
        return false;
      }
    } catch (err) {
      console.warn("[Auth] Server health/auth check failed:", err);
      // If server is offline, trust local session or fall back gracefully
      updateUserBadges(localUser);
      hideScreen();
      return true;
    }
  }

  // ── Screen Visibility ──────────────────────────────────────
  function showScreen() {
    if (screen) screen.classList.remove("hidden");
    if (gateway) gateway.classList.add("gw-hidden");
    if (appEl) appEl.classList.remove("active");
    if (usernameInput) usernameInput.value = "";
    if (passwordInput) passwordInput.value = "";
  }

  function hideScreen() {
    if (screen) screen.classList.add("hidden");
    if (gateway) gateway.classList.remove("gw-hidden");
  }

  // ── Mode Switch ────────────────────────────────────────────
  function toggleMode() {
    isLoginMode = !isLoginMode;
    if (isLoginMode) {
      cardTitle.textContent = "Welcome Back";
      cardSub.textContent = "Please sign in to access your intelligence suite.";
      submitBtn.querySelector("span").textContent = "Sign In";
      toggleMsg.textContent = "Don't have an account?";
      toggleBtn.textContent = "Sign Up";
    } else {
      cardTitle.textContent = "Create Account";
      cardSub.textContent = "Join InterviewSense AI and start your learning journey.";
      submitBtn.querySelector("span").textContent = "Sign Up";
      toggleMsg.textContent = "Already have an account?";
      toggleBtn.textContent = "Sign In";
    }
  }

  // ── Submit Handling ────────────────────────────────────────
  async function handleSubmit(e) {
    e.preventDefault();

    const uVal = usernameInput.value.trim();
    const pVal = passwordInput.value.trim();

    if (!uVal || !pVal) {
      UI.showToast("All fields are required.", "warning");
      return;
    }

    if (uVal.length < 3) {
      UI.showToast("Username must be at least 3 characters.", "warning");
      return;
    }

    if (pVal.length < 6) {
      UI.showToast("Password must be at least 6 characters.", "warning");
      return;
    }

    submitBtn.disabled = true;
    submitBtn.querySelector("span").textContent = isLoginMode ? "Signing In..." : "Signing Up...";

    const formBody = new FormData();
    formBody.append("username", uVal);
    formBody.append("password", pVal);

    try {
      const path = isLoginMode ? "/api/auth/login" : "/api/auth/register";
      const res = await fetch(CONFIG.BACKEND_URL + path, {
        method: "POST",
        body: formBody
      });

      const data = await res.json();

      if (res.ok) {
        if (isLoginMode) {
          // Store token & username
          token = data.token;
          username = data.username;
          localStorage.setItem("isai_auth_token", token);
          localStorage.setItem("isai_auth_username", username);

          // Update elements & change screens
          updateUserBadges(username);
          hideScreen();
          UI.showToast(`Welcome back, ${username}!`, "success");
        } else {
          // Switch to login mode
          toggleMode();
          UI.showToast("Registration successful! Please sign in.", "success");
        }
      } else {
        UI.showToast(data.message || "Authentication failed.", "warning");
      }
    } catch (err) {
      console.error(err);
      UI.showToast("Could not connect to the authentication server.", "warning");
    } finally {
      submitBtn.disabled = false;
      submitBtn.querySelector("span").textContent = isLoginMode ? "Sign In" : "Sign Up";
    }
  }

  // ── Badge management ───────────────────────────────────────
  function updateUserBadges(uname) {
    const topbarDisplay = document.getElementById("topbar-username-display");
    const gatewayDisplay = document.getElementById("gateway-username-display");
    if (topbarDisplay) topbarDisplay.textContent = uname;
    if (gatewayDisplay) gatewayDisplay.textContent = uname;
  }

  // ── Logout cleaner ─────────────────────────────────────────
  function logoutCleanly(sendRequest = true) {
    const curToken = getToken();

    // Clear local token state
    token = null;
    username = null;
    localStorage.removeItem("isai_auth_token");
    localStorage.removeItem("isai_auth_username");

    // CRITICAL: Wipe chat histories from localStorage to prevent session spillover
    Store.clearAll();

    // Call server to invalidate session
    if (sendRequest && curToken) {
      fetch(CONFIG.BACKEND_URL + "/api/auth/logout", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${curToken}`
        }
      }).catch(() => {});
    }

    // Reset UI Badges and transition back to Auth screen
    updateUserBadges("");
    showScreen();
    UI.showToast("Logged out successfully.", "info");
  }

  // ── Event binding ──────────────────────────────────────────
  function init() {
    if (form) form.addEventListener("submit", handleSubmit);
    if (toggleBtn) toggleBtn.addEventListener("click", toggleMode);

    // Logout actions
    const logoutBtn = document.getElementById("logout-btn");
    const gatewayLogoutBtn = document.getElementById("gateway-logout-btn");

    if (logoutBtn) logoutBtn.onclick = () => logoutCleanly(true);
    if (gatewayLogoutBtn) gatewayLogoutBtn.onclick = () => logoutCleanly(true);
  }

  return {
    init,
    checkAuth,
    getToken,
    getUsername,
    logout: () => logoutCleanly(true)
  };
})();
