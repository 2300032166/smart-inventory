# 🛍️ SIRA — Smart Inventory Replenishment Advisor

**SIRA** is an advanced, AI-driven inventory management platform and modern retail storefront. Built with a robust backend architecture using **FastAPI** and a premium, glassmorphism-styled frontend built purely in **HTML, CSS, and vanilla JS**, SIRA empowers retail ecosystems on all fronts.

From helping managers make smarter reorder decisions with Groq-powered AI, to real-time supplier comparison analytics and a state-of-the-art customer storefront, SIRA is an end-to-end management solution.

---

## ✨ Core Features & Offerings

### 👔 For Managers (Operations & Procurement)
- **🧠 Daily AI Briefing** — AI-generated, prioritized task list spotlighting critical attention areas, dynamically ranked by urgency and risk levels.
- **📦 Smart Procurement Dashboard** — A unified, state-preserving dashboard to review, approve, override, skip, or undo AI-suggested POs with detailed audit trails.
- **🔄 Advanced Supplier Portal** — Granular supplier management, product mapping, and a multi-dimensional supplier comparison engine scoring partners on Reliability, On-Time Percentage, Lead Time, and Quality.
- **⏳ Expiry & Dead-Stock Tracking** — Aggressive monitoring of nearing-expiry batches and dead-stock lifecycle management.
- **🏷️ Automated Discounts** — ML-driven pricing and discount campaigns tailored towards maximizing clearance of aging inventory.
- **🌦️ Weather-Aware Forecasting** — Ingests localized forecasts to predict shifts in purchasing behaviors and adjusts restock alerts dynamically.
- **🤖 Intelligent Chatbot** — Natural Language Interface (NLI) asking cross-relational questions about stock, logistics, and historical trends.

### 🛡️ For System Administrators
- **🔑 RBAC User Management** — Full-suite credential management encompassing provisioning, resets, and role assignments for staff.
- **📊 System & Override Analytics** — Deep-dive analytics into system overrides, evaluating manager compliance versus AI suggestions.
- **⚙️ AI & System Configuration** — Dynamic toggle for AI endpoints, caching rules, confidence thresholds, and testing directly from the dashboard.
- **📜 Comprehensive Audit Logs** — Filterable, immutable ledger of all meaningful actions across the platform.
- **📁 Legacy Sales Import** — Intelligent CSV parsing with built-in deduplication and immediate rollback capabilities for historical data loads.

### 🛒 For Customers
- **💎 Premium Modern Storefront** — A sleek, unified glassmorphism aesthetic built from the ground up to provide a bespoke, highly responsive e-commerce experience.
- **🔍 Advanced Cataloging & Search** — Filterable catalog with seamless real-time search, customized recommendations, and aesthetic categorized borders.
- **💳 Fully-Fledged Checkout** — Persistent cart states, wishlisting capabilities, tiered checkout, and community reviews.
- **📦 Order Tracking** — Self-service portal for viewing historical and current order statuses, from placement to dispatch.

---

## 🛠️ Technology Stack

| Component | Technology | 
|-----------|------------|
| **Backend API** | Python 3, FastAPI, Uvicorn, Pydantic |
| **Artificial Intelligence** | Groq API (LLM Integration with Configurable Context) |
| **External Integrations**| Open-Meteo API (Live Weather Context) |
| **Frontend UI/UX** | HTML5, CSS3 (Modern Glassmorphism & Tokens), Vanilla JS |
| **Data Persistence** | File-based JSON & CSV (under `backend/data/`) |
| **CI/CD & DevOps** | Docker, Helm (K8s), Jenkins pipelines |

---

## 🏗️ Project Architecture

```text
.
├── backend/
│   ├── main.py                 # FastAPI ASGI entry point
│   ├── routes/                 # API controllers and modular endpoints
│   ├── logic/                  # Core algorithms, prediction engines & AI logic
│   ├── middleware/             # JWT-based Authentication middleware
│   ├── data/                   # Persistent flat-file layer (JSON/CSV)
│   └── .env                    # Secrets and environment configurations
├── frontend/
│   ├── pages/                  # Segregated views (admin, manager, customer)
│   ├── js/                     # Component-specific behavioral logic
│   ├── app.js                  # Shared utilities (auth, polling, UX wrappers)
│   ├── style.css               # Global styling, tokens, animations
│   └── customer-style.css      # E-Commerce storefront styling layer
├── helm_chart/                 # Kubernetes deployment templates
├── Dockerfile                  # Containerization blueprints
├── Jenkinsfile*                # Automated CI/CD Declarations
└── requirements.txt            # Python dependencies (optimized)
```

---

## 🚀 Quick Start (Local Setup)

### 1. Install Dependencies
Ensure you have Python 3.11+ installed.
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (Secrets)
Generate a `backend/.env` file with the requisite configuration flags:
```env
JWT_SECRET_KEY=your_secure_random_hash_here
GROQ_API_KEY=your_groq_production_key
CHATBOT_GROQ_API_KEY=your_groq_agent_key
CHATBOT_GROQ_MODEL=llama-3.1-8b-instant
BRIEF_CACHE_HOURS=6
CONFIDENCE_THRESHOLD=60
MAX_BRIEF_ITEMS=100
PAYDAY_DATES=25,26,27
```


### 3. Initialize Server
Shift directory and execute the ASGI web server directly:
```bash
cd backend
python main.py
```


### 4. Experience SIRA 
Navigate directly to [http://localhost:4040](http://localhost:4040).
Authenticate with respective RBAC boundaries using identities populated in `backend/data/users.json`.

---

## 📋 Endpoint Topology

| Domain | Access | Purpose |
|--------|--------|---------|
| `/api/auth` | Public | Token generation, validation, session handling |
| `/api/brief` | Manager | Fetch & parse AI daily operational imperatives |
| `/api/orders`| Manager | End-to-end Procurement Order (PO) lifestyle logic |
| `/api/inventory`| Man/Admin | Supplier maps, product matrix, and batches |
| `/api/discounts`| Man/Admin | Analytics metrics for markdowns |
| `/api/suppliers/*`| Man/Admin | Specialized analytics on fill rate, reliability scores |
| `/api/customer-*`| Customer | Storefront endpoints mapping shopping behaviors |
| `/api/chatbot`| Auth | Stream-enabled LLM interrogation points |
| `/api/admin` | Admin | Cross-level system config and user state handling |

---
