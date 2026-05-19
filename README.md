<<<<<<< HEAD
# Smart Inventory Replenishment Advisor

An AI-powered internal store operations tool that analyses sales history, detects patterns, and generates replenishment recommendations for store managers. Admins manage products, suppliers, users, and AI configuration through a separate panel.

---

## Prerequisites

- Python 3.11+
- Docker & Docker Compose (for the easiest setup)
- No Node.js required — frontend is pure HTML/CSS/JavaScript

---

## Default Login Credentials

| Role    | Email               | Password     |
|---------|---------------------|--------------|
| Admin   | admin@store.com     | Admin@123    |
| Manager | manager@store.com   | Manager@123  |

---

## Local Setup (with Docker — recommended)

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd smart-inventory-advisor

# 2. Create the .env file
cp backend/.env.example backend/.env
# Edit backend/.env and set JWT_SECRET_KEY and AI credentials

# 3. Start both services
docker-compose up --build

# 4. Open the app
# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
```

---

## Local Setup (without Docker)

### Backend

```bash
cd backend

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env
cp .env.example .env
# Edit .env and set at minimum: JWT_SECRET_KEY

# Run the API server
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend

Serve the frontend with any static file server that proxies /api/ to localhost:8000.

**Option A — Python**
```bash
cd frontend
python -m http.server 3000
```
Then edit your browser's requests to point to the backend, or use the nginx setup below.

**Option B — nginx (local)**
```bash
# Point nginx root to the frontend/ folder
# Use nginx/nginx.conf as your site config
# Update the proxy_pass to http://localhost:8000/api/
```

---

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in:

| Variable              | Description                                     | Default                  |
|-----------------------|-------------------------------------------------|--------------------------|
| `JWT_SECRET_KEY`      | Secret key for JWT signing (change this!)       | *required*               |
| `AI_PROVIDER`         | `claude` or `ollama`                            | `claude`                 |
| `ANTHROPIC_API_KEY`   | Your Anthropic API key                          | —                        |
| `CLAUDE_MODEL`        | Claude model name                               | `claude-sonnet-4-20250514` |
| `OLLAMA_URL`          | Ollama server URL (if using local AI)           | `http://localhost:11434` |
| `OLLAMA_MODEL`        | Ollama model name                               | `llama3`                 |
| `BRIEF_CACHE_HOURS`   | How long to cache the daily brief               | `6`                      |
| `CONFIDENCE_THRESHOLD`| Min confidence % to include in brief            | `60`                     |
| `MAX_BRIEF_ITEMS`     | Max products in one brief                       | `10`                     |
| `PAYDAY_DATES`        | Comma-separated day-of-month numbers for payday | `25,26,27`              |

**Note:** The app works fully without an AI key — all pages load and function. Only the Daily Brief page requires an AI provider to generate AI reasoning text.

---

## Calibo Sandbox Deployment

```bash
# Install Calibo CLI
npm install -g @calibo/cli

# Login
calibo login

# Deploy
calibo deploy --env sandbox
```

The `calibo.yaml` file defines both the backend (Python/uvicorn) and frontend (static) services. Ensure your environment variables are configured in the Calibo project settings before deploying.

---

## Project Structure

```
smart-inventory-advisor/
├── frontend/               Static HTML/CSS/JS frontend
│   ├── index.html          Redirects to login
│   ├── style.css           Global design system
│   ├── app.js              Auth, API wrapper, sidebar/topbar
│   ├── pages/              One HTML file per page (18 pages)
│   └── js/                 One JS file per page
├── backend/
│   ├── main.py             FastAPI app entry point
│   ├── requirements.txt    Python dependencies
│   ├── .env.example        Environment variable template
│   ├── data/               CSV and JSON data files
│   ├── routes/             FastAPI route handlers
│   ├── logic/              Business logic (AI, patterns, reorder)
│   └── middleware/         JWT auth middleware
├── nginx/
│   └── nginx.conf          Nginx config (proxies /api/ to backend)
├── docker-compose.yml      Runs frontend + backend together
├── bitbucket-pipelines.yml CI/CD pipeline
└── calibo.yaml             Calibo Sandbox deployment config
```

---

## Data Files

All data is stored as flat files — no database required:

| File                         | Purpose                              |
|------------------------------|--------------------------------------|
| `backend/data/products.csv`  | Product catalogue with stock levels  |
| `backend/data/suppliers.csv` | Supplier contacts and lead times     |
| `backend/data/sales.csv`     | Sales history (Kaggle format)        |
| `backend/data/users.json`    | User accounts with hashed passwords  |
| `backend/data/override_history.json` | Replenishment decisions      |
| `backend/data/audit_log.json` | Full system audit trail             |
| `backend/data/alerts.json`   | User notifications                   |
| `backend/data/ai_config.json` | AI model configuration              |
| `backend/data/brief_log.json` | Cached AI briefs (by date)          |

---

## API Documentation

When the backend is running, visit `http://localhost:8000/docs` for the interactive Swagger API documentation.

---

## How AI Brief Generation Works

1. Sales history is read from `sales.csv` using Pandas
2. For each product, daily averages, payday spikes, and trends are detected
3. A reorder score and recommended quantity are calculated
4. A prompt is built and sent to Claude API (falls back to Ollama, then fallback text)
5. The AI's reasoning paragraph is attached to each recommendation
6. The full brief is cached for `BRIEF_CACHE_HOURS` to avoid repeated API calls
=======
**Edit a file, create a new file, and clone from Bitbucket in under 2 minutes**

When you're done, you can delete the content in this README and update the file with details for others getting started with your repository.

*We recommend that you open this README in another tab as you perform the tasks below. You can [watch our video](https://youtu.be/0ocf7u76WSo) for a full demo of all the steps in this tutorial. Open the video in a new tab to avoid leaving Bitbucket.*

---

## Edit a file

You’ll start by editing this README file to learn how to edit a file in Bitbucket.

1. Click **Source** on the left side.
2. Click the README.md link from the list of files.
3. Click the **Edit** button.
4. Delete the following text: *Delete this line to make a change to the README from Bitbucket.*
5. After making your change, click **Commit** and then **Commit** again in the dialog. The commit page will open and you’ll see the change you just made.
6. Go back to the **Source** page.

---

## Create a file

Next, you’ll add a new file to this repository.

1. Click the **New file** button at the top of the **Source** page.
2. Give the file a filename of **contributors.txt**.
3. Enter your name in the empty file space.
4. Click **Commit** and then **Commit** again in the dialog.
5. Go back to the **Source** page.

Before you move on, go ahead and explore the repository. You've already seen the **Source** page, but check out the **Commits**, **Branches**, and **Settings** pages.

---

## Clone a repository

Use these steps to clone from SourceTree, our client for using the repository command-line free. Cloning allows you to work on your files locally. If you don't yet have SourceTree, [download and install first](https://www.sourcetreeapp.com/). If you prefer to clone from the command line, see [Clone a repository](https://confluence.atlassian.com/x/4whODQ).

1. You’ll see the clone button under the **Source** heading. Click that button.
2. Now click **Check out in SourceTree**. You may need to create a SourceTree account or log in.
3. When you see the **Clone New** dialog in SourceTree, update the destination path and name if you’d like to and then click **Clone**.
4. Open the directory you just created to see your repository’s files.

Now that you're more familiar with your Bitbucket repository, go ahead and add a new file locally. You can [push your change back to Bitbucket with SourceTree](https://confluence.atlassian.com/x/iqyBMg), or you can [add, commit,](https://confluence.atlassian.com/x/8QhODQ) and [push from the command line](https://confluence.atlassian.com/x/NQ0zDQ).
>>>>>>> 304f9a5407d22c20a132de112aac9212541b8e73
