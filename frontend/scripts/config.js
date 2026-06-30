// Central configuration — edit BACKEND_URL to point at your Flask server.

const CONFIG = Object.freeze({
  // Automatically routes to local Flask server when testing locally via file:// or localhost,
  // and falls back to relative paths when deployed on Vercel.
  BACKEND_URL: (location.protocol === "file:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")
    ? "http://127.0.0.1:5000"
    : "",

  ENDPOINTS: {
    STUDY:            "/api/workspace/generate",
    CAREER:           "/api/edtech/generate",
    RESET:            "/api/edtech/reset",
    DELETE:           "/api/edtech/delete",
    STATS:            "/api/edtech/stats",
    NOTIFICATIONS:    "/api/notifications",
    NOTIF_READ:       "/api/notifications/read",
    HEALTH:           "/api/health",
    INTERVIEW_START:  "/api/interview/start",
    INTERVIEW_ANSWER: "/api/interview/answer",
    INTERVIEW_REPORT: "/api/interview/report",
    INTERVIEW_RESET:  "/api/interview/reset",
  },

  MAX_HISTORY_TURNS: 8,
  STREAM_DELAY_MS:   30,  
  STORAGE_KEY:       "isai-workspace",
});