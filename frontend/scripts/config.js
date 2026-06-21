// Central configuration — edit BACKEND_URL to point at your Flask server.

const CONFIG = Object.freeze({
  // Leave empty so it automatically routes to your live Vercel domain
  BACKEND_URL: "", 

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
  STREAM_DELAY_MS:   30,  
  STORAGE_KEY:       "isai-workspace",
});