
# Smart Inventory Replenishment Advisor 🛒🤖

An AI-powered internal store operations platform that transforms retail data into actionable inventory decisions. This tool analyzes sales history, predicts demand patterns (including payday spikes and historical trends), and generates intelligent replenishment recommendations for store managers.

---

## ✨ Core Features

- **AI-Powered Daily Briefs**: Get natural language explanations for replenishment needs using state-of-the-art LLMs (Gemini, Groq, Claude).
- **Intelligent Pattern Detection**: Automatically detects **Payday Spikes** (days 25-27) and **Declining Trends** to optimize stock levels.
- **Synchronized Risk Metrics**: Real-time synchronization between dashboard statistics and recommendations. Handled items are immediately removed from the "Stockout Risk" count across a 48-hour window to maintain single-source-of-truth accuracy.
- **Review Mode**: A high-efficiency "Review Flow" for managers with keyboard shortcuts (`A` for Approve, `S` for Skip) to process orders rapidly.
- **Admin Control Panel**: Manage the product catalog, monitor supplier lead times, configure AI behavior, and view detailed audit logs.
- **Zero-Infrastructure Portability**: Built using a flat-file architecture (CSV/JSON)—no complex database setup required.

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.11+**
- **Docker & Docker Compose** (Recommended)
- **An API Key** for Groq or Gemini (Optional, for AI reasoning)

### Quick Start (with Docker)

```bash
# 1. Clone the repository
cd Store-Advisor/smart-inventory-advisor

# 2. Create the .env file
cp backend/.env.example backend/.env
# Edit backend/.env and set your API keys

# 3. Start the services
docker compose up --build

# 4. Access the application
# URL: http://localhost:8001
```

### Manual Setup

```bash
# 1. Install Backend Dependencies
cd backend
pip install -r requirements.txt

# 2. Configure Environment
cp .env.example .env
# Edit .env and set your JWT_SECRET_KEY and API Keys

# 3. Start the Server
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```
*Note: The backend automatically serves the frontend at http://localhost:8001.*

---

## 🔑 Default Login Credentials

| Role    | Email               | Password     |
|---------|---------------------|--------------|
| **Admin**   | `admin@store.com`     | `Admin@123`    |
| **Manager** | `manager@store.com`   | `Manager@123`  |

---

## ⚙️ Environment Variables

Copy `backend/.env.example` to `backend/.env` and configure:

| Variable              | Description                                     | Supported Values |
|-----------------------|-------------------------------------------------|-----------------------------|
| `AI_PROVIDER`         | The primary AI engine to use                    | `gemini`, `groq`, `claude`, `ollama` |
| `GROQ_API_KEY`        | Groq Cloud API Key                              | — |
| `GEMINI_API_KEY`      | Google Gemini API Key                           | — |
| `BRIEF_CACHE_HOURS`   | How long to cache the AI daily brief            | `1` (Default) |
| `PAYDAY_DATES`        | Days of the month to expect sales spikes        | `25,26,27` |

---

## 🏗️ Project Architecture

```text
smart-inventory-advisor/
├── frontend/               # Premium Vanilla JS/CSS Frontend
│   ├── pages/              # 18+ interactive control screens
│   ├── style.css           # Global Design System & Components
│   └── app.js              # Auth & API core logic
├── backend/                # FastAPI Application
│   ├── data/               # CSV/JSON storage (The "Database")
│   ├── logic/              # AI Clients, Pattern Detectors, Calculators
│   ├── routes/             # RESTful API Endpoints (/api/...)
│   └── main.py             # App Entry & Static File Mounting
├── docker-compose.yml      # Orchestration
└── calibo.yaml             # Cloud Sandbox Deployment settings
```

---

## 📊 Inventory Decision Logic

1. **Extraction**: Sales data is pulled from `sales.csv` using Pandas.
2. **Analysis**: The `PatternDetector` identifies seasonal spikes and sales velocity.
3. **Calculation**: `ReorderCalculator` suggests quantities based on stock levels, lead times, and detected patterns.
4. **AI Reasoning**: The `AI Client` translates technical data into natural language suggestions to help managers understand *why* an order is needed.
5. **Real-time Sync**: Manager decisions are logged in `override_history.json`, instantly updating dashboard risk metrics and removing the item from the daily brief.

---

## 🎨 Design System
This project follows a **Premium Operations** aesthetic:
- **Dark Mode First**: Optimized for high-contrast visibility.
- **Glassmorphism**: Subtle translucent layers for depth.
- **Responsive**: Fully functional on tablets and desktops.
