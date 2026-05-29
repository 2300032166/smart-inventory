# Smart Inventory Replenishment Advisor 🛒🤖

An AI-powered internal store operations platform that transforms retail data into actionable inventory decisions. This tool analyzes sales history, predicts demand patterns (including payday spikes and trends), and generates intelligent replenishment recommendations for store managers.

---

## ✨ Core Features

- **AI-Powered Daily Briefs**: Get natural language explanations for replenishment needs using state-of-the-art LLMs (Gemini, Groq, Claude).
- **Intelligent Pattern Detection**: Automatically detects **Payday Spikes** (days 25-27) and **Declining Trends** to optimize stock levels.
- **Smart Risk Metrics**: Real-time synchronization between dashboard statistics and recommendations. Approved items are immediately removed from the "Stockout Risk" count to ensure data accuracy.
- **Review Mode**: A high-efficiency "Review Flow" for managers with keyboard shortcuts (`A` for Approve, `S` for Skip) to process orders rapidly.
- **Admin Control Panel**: Manage the product catalog, monitor supplier lead times, configure AI behavior, and view detailed audit logs.
- **Zero-Infrastructure Portability**: Built using a flat-file architecture (CSV/JSON)—no complex database setup required.

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+**
- **Docker & Docker Compose** (Recommended for easiest setup)
- Vanilla HTML5/CSS3/JavaScript.

### Local Setup (with Docker)

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd Store-Advisor/smart-inventory-advisor

# 2. Create the .env file
cp backend/.env.example backend/.env
# Edit backend/.env and set your API keys

# 3. Start the services
docker-compose up --build

# 4. Access the application
# Frontend: http://localhost:8000
# API docs: http://localhost:8000/docs
```

### Local Setup (Manual)

```bash
cd smart-inventory-advisor/backend

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
*Note: The backend automatically serves the frontend at the root URL.*

---

## 🔑 Default Login Credentials

| Role    | Email               | Password     |
|---------|---------------------|--------------|
| **Admin**   | `admin@store.com`     | `Admin@123`    |
| **Manager** | `manager@store.com`   | `Manager@123`  |

---

## ⚙️ Environment Variables

Copy `backend/.env.example` to `backend/.env` and configure:

| Variable              | Description                                     | Supported Providers / Values |
|-----------------------|-------------------------------------------------|-----------------------------|
| `AI_PROVIDER`         | The primary AI engine to use                    | `gemini`, `groq`, `claude`, `ollama` |
| `GEMINI_API_KEY`      | Google Gemini API Key                           | — |
| `GROQ_API_KEY`        | Groq Cloud API Key                              | — |
| `ANTHROPIC_API_KEY`   | Anthropic API Key                               | — |
| `OLLAMA_URL`          | Local Ollama instance URL                       | `http://localhost:11434` |
| `BRIEF_CACHE_HOURS`   | How long to cache the AI daily brief            | `6` (Default) |
| `PAYDAY_DATES`        | Days of the month to expect sales spikes        | `25,26,27` |

**Note:** The application functions fully even without an AI key. Only the "Daily Brief" reasoning text requires an active AI provider.

---

## 🏗️ Project Architecture

```text
smart-inventory-advisor/
├── frontend/               # Premium Vanilla JS/CSS Frontend
│   ├── pages/              # 18+ interactive control screens
│   ├── style.css           # Global Design System & Components
│   └── app.js              # Auth & API core
├── backend/                # FastAPI Application
│   ├── data/               # CSV/JSON storage (The "Database")
│   ├── logic/              # AI Clients, Pattern Detectors, Calculators
│   ├── routes/             # RESTful API Endpoints
│   └── main.py             # App Entry & Static File Mounting
├── docker-compose.yml      # Orchestration
└── calibo.yaml             # Cloud Sandbox Deployment
```

---

## 🎨 Design Aesthetics & UX

This project prioritizes a **Premium Store Operations Experience**:
- **Modern UI**: Dark-mode optimized with sleek gradients and glassmorphism.
- **Micro-Animations**: Subtle hover effects and transitions for a responsive feel.
- **Visual Feedback**: Real-time status indicators (e.g., Stockout Risk, Pending Orders) that update instantly upon manager interaction.
- **Typography**: Clean, professional fonts (Inter/Outfit) for maximum readability in high-speed retail environments.

---

## 📊 Inventory Decision Logic

1. **Extraction**: Sales data is pulled from `sales.csv` using Pandas.
2. **Analysis**: The `PatternDetector` identifies seasonal spikes and velocity.
3. **Calculation**: `ReorderCalculator` suggests quantities based on stock levels, lead times, and detected patterns.
4. **Execution**: The `AI Client` (Gemini/Groq/Claude) adds natural language "Reasoning" to help the manager understand *why* an order is needed.
5. **Sync**: Decisions are logged in `override_history.json`, instantly updating dashboard KPIs.

