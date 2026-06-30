# 🤖 InterviewSense AI

An intelligent, full-stack mock interview preparation platform and career study-path developer powered by AI. **InterviewSense AI** helps developers upskill, plan their career roadmaps, practice realistic mock interviews, and solve coding challenges in a secure, sandbox-isolated IDE.

---

## 🚀 Key Features

* **🧠 AI-Powered Career Roadmap & Study Planner**: Generates personalized daily learning modules and dynamic DSA tracks based on roles, experience level, and study pacing.
* **🎙️ Realistic Mock Interview Simulator**: Simulates mock technical and behavioral interviews tailored to target roles, target companies, and uploadable resumes/JDs. Provides detailed scorecards, strength maps, and feedback.
* **💻 Secure IDE Code Execution Sandbox**: Features a code editor supporting Python, JavaScript, Java, and C++ with real-time compilation and execution sandboxed through the Judge0 runtime API.
* **🛡️ Secure JWT-Style Bearer Auth**: Robust local registration, credential verification hashed using high-security PBKDF2-HMAC-SHA256, and stateful token expiry handlers.
* **⚡ Self-Healing DB Migration Engine**: Integrates an automatic, non-destructive migration system that detects outdated database tables and upgrades them on startup while preserving all existing progress.

---

## 🛠️ Technology Stack

| Component | Technologies Used |
| :--- | :--- |
| **Backend API** | Python, Flask, WSGI Server, Werkzeug |
| **Database** | SQLite3 (WAL Journal Mode, Foreign Key Cascade) |
| **Security / Auth** | `hashlib` (PBKDF2-HMAC-SHA256), `secrets` token generator |
| **Code Runner** | Judge0 API (Sandboxed Compiler & Executer) |
| **Frontend UI** | HTML5, Vanilla CSS3 (Custom gradients, animations, glassmorphism) |
| **Frontend Logic** | Vanilla JavaScript (ES6+ async/await, Bearer Authorization header state) |

---

## 📊 Relational Database Schema

The SQLite schema is optimized for referential integrity:

```sql
-- Core user profiles
CREATE TABLE users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Active user bearer tokens
CREATE TABLE user_sessions (
    session_token   TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at      TEXT NOT NULL
);

-- Active learning courses & daily schedules
CREATE TABLE course_sessions (
    chat_id         TEXT PRIMARY KEY,
    role            TEXT NOT NULL DEFAULT 'Python Developer',
    duration_days   INTEGER NOT NULL DEFAULT 30,
    hours_per_day   TEXT NOT NULL DEFAULT '2',
    level           TEXT NOT NULL DEFAULT 'beginner',
    dsa_track       TEXT NOT NULL DEFAULT 'yes',
    current_day     INTEGER NOT NULL DEFAULT 1,
    started         INTEGER NOT NULL DEFAULT 0,
    awaiting_answers INTEGER NOT NULL DEFAULT 0,
    last_quiz       TEXT NOT NULL DEFAULT '',
    day_plan        TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Active mock interviews
CREATE TABLE interview_sessions (
    chat_id       TEXT PRIMARY KEY,
    role          TEXT NOT NULL DEFAULT '',
    company       TEXT NOT NULL DEFAULT '',
    jd_text       TEXT NOT NULL DEFAULT '',
    resume_text   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'active',
    question_idx  INTEGER NOT NULL DEFAULT 0,
    total_q       INTEGER NOT NULL DEFAULT 0,
    question_bank TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    domain        TEXT NOT NULL DEFAULT 'it',
    round_type    TEXT NOT NULL DEFAULT 'tech',
    report_feedback TEXT NOT NULL DEFAULT '',
    weekly_career_day INTEGER NOT NULL DEFAULT 0
);
```

---

## 🏁 Getting Started

### Prerequisites
* Python 3.10+
* Virtual Environment (optional, but highly recommended)

### 1. Installation & Environment Configuration
Clone the repository, create a virtual environment, and install dependencies:
```bash
# Clone the repository
git clone https://github.com/Shankar46/InterviewSenseAI.git
cd InterviewSenseAI

# Set up virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

Create a `.env` file in the root directory:
```env
FLASK_HOST=127.0.0.1
PORT=5000
FLASK_DEBUG=false
HF_TOKEN=your_huggingface_token
```

### 2. Running the Application
Start the Flask backend:
```bash
python -m backend.main
```
*Note: On startup, the backend automatically validates the database and executes migrations if any tables are outdated.*

Open `frontend/index.html` in your browser or run it using a local live server extension.