// frontend/scripts/config.js
// Central configuration — edit BACKEND_URL to point at your Flask server.

const CONFIG = Object.freeze({
  BACKEND_URL: "http://127.0.0.1:5000",

  ENDPOINTS: {
    STUDY:         "/api/workspace/generate",
    CAREER:        "/api/edtech/generate",
    RESET:         "/api/edtech/reset",
    DELETE:        "/api/edtech/delete",
    STATS:         "/api/edtech/stats",
    NOTIFICATIONS: "/api/notifications",
    NOTIF_READ:    "/api/notifications/read",
    HEALTH:        "/api/health",
  },

  MAX_HISTORY_TURNS: 8,
  STREAM_DELAY_MS:   30,  // milliseconds between stream updates (was 0.8 - too fast)
  STORAGE_KEY:       "isai-workspace",
});