# Decoupled Deployment Guide: Azure (Backend) + Vercel (Frontend)

This repository is pre-configured for a decoupled production architecture:
- **Backend API**: Hosted on **Microsoft Azure App Service** or **Azure Container Apps** (Python 3.12 / FastAPI).
- **Frontend UI**: Hosted on **Vercel** (`frontend/`) with seamless reverse proxy rewrites to your Azure backend.
- **Database**: **Neon Serverless PostgreSQL** (persistent conversation history & sessions).
- **Authentication**: **Supabase Auth** with Google OAuth 2.0.
- **Inference Engine**: **Groq API** (ultra-fast clinical reasoning & citation synthesis).

---

## Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │                End User                      │
                      └──────────────────────┬───────────────────────┘
                                             │
                          https://<your-app>.vercel.app
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │              Vercel Frontend                 │
                      │  - Static clinical UI (HTML / Tailwind / JS) │
                      │  - vercel.json reverse proxy for /api/*      │
                      └──────────────────────┬───────────────────────┘
                                             │  (Reverse Proxy / Direct CORS)
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │            Azure App Service                 │
                      │  - FastAPI / Uvicorn (port dynamic / 8000)   │
                      │  - Hybrid BM25 + FAISS Vector Engine         │
                      │  - Rate Limiting + OWASP Defense Headers     │
                      └──────────────┬──────────────────┬────────────┘
                                     │                  │
                                     ▼                  ▼
                       ┌──────────────────────┐  ┌─────────────────────┐
                       │    Neon Postgres     │  │      Groq API       │
                       │  (Conversation Logs) │  │  (RAG LLM Engine)   │
                       └──────────────────────┘  └─────────────────────┘
```

---

## Part 1: Deploy Backend to Microsoft Azure

### Option A: Azure App Service (Code Deployment via GitHub Actions or Git)
1. In the **Azure Portal**, click **Create a resource** &rarr; **Web App**.
2. Configure App Details:
   - **Name**: e.g., `perfusion-backend` (creates `perfusion-backend.azurewebsites.net`).
   - **Publish**: `Code`
   - **Runtime stack**: `Python 3.12`
   - **Operating System**: `Linux`
   - **Pricing Plan**: `Basic B1` or `Free F1` (for evaluation).
3. Under **Settings** &rarr; **Configuration** &rarr; **General settings**:
   - **Startup Command**: `sh startup.sh` (or `python -m uvicorn main:app --host 0.0.0.0 --port 8000`)
4. Under **Settings** &rarr; **Environment variables** (Application settings), add your production secrets:
   | Variable | Value / Description |
   | :--- | :--- |
   | `GROQ_API_KEY` | Your Groq Cloud API key (`gsk_...`) |
   | `GROQ_MODEL` | `llama-3.3-70b-versatile` or `qwen/qwen3.8-27b` |
   | `DATABASE_URL` | Neon PostgreSQL connection string (`postgresql://...`) |
   | `SUPABASE_URL` | `https://vpwrrtpotyprdxcevelr.supabase.co` |
   | `SUPABASE_ANON_KEY` | Your Supabase publishable/anon key |
   | `SUPABASE_SERVICE_ROLE_KEY`| Your Supabase service role key |
   | `GOOGLE_CLIENT_ID` | Your Google OAuth Web Client ID |
   | `GOOGLE_CLIENT_SECRET` | Your Google OAuth Web Client Secret |
   | `CORS_ORIGINS` | `https://<your-vercel-app>.vercel.app,http://localhost:3000` |
   | `WEBSITES_PORT` | `8000` |
5. Connect your GitHub repository (`ananthakrishnan06/perfusion-technology-cahtbot`) in **Deployment Center** to enable automatic continuous deployment on push to `main`.
6. Verify your Azure backend:
   Open `https://<your-azure-app>.azurewebsites.net/health` in your browser. It should return:
   ```json
   {"status":"ok","service":"PerfusionGPT","version":"1.0.0"}
   ```

---

### Option B: Azure Container Apps / Docker Deployment
1. Build and push container to Azure Container Registry (ACR) or Docker Hub:
   ```bash
   docker build -t perfusiongpt-backend:latest .
   ```
2. Create an **Azure Container App**:
   - Ingress: `Enabled` (Accepting traffic from anywhere, target port `8000`).
   - Environment variables: add the same secrets listed in Option A.

---

## Part 2: Deploy Frontend to Vercel

1. Log in to [Vercel](https://vercel.com) and click **Add New** &rarr; **Project**.
2. Import the repository: `ananthakrishnan06/perfusion-technology-cahtbot`.
3. In the project configure screen:
   - **Framework Preset**: Select `Other`.
   - **Root Directory**: Click edit and select `frontend` (or leave blank if deploying whole repo).
4. **Update Azure Backend URL in `vercel.json`**:
   Before or after deploying, update `frontend/vercel.json` (and root `vercel.json`) with your real Azure URL:
   ```json
   {
     "rewrites": [
       {
         "source": "/api/:path*",
         "destination": "https://<your-azure-app>.azurewebsites.net/api/:path*"
       },
       {
         "source": "/health",
         "destination": "https://<your-azure-app>.azurewebsites.net/health"
       }
     ]
   }
   ```
5. Click **Deploy**. Vercel will provision your site in seconds:
   e.g. `https://perfusion-ai.vercel.app`

---

## Part 3: Synchronize Supabase & Google Cloud OAuth

Once your Vercel URL is live (e.g. `https://perfusion-ai.vercel.app`), update the OAuth redirect whitelist:

### 1. In Supabase Dashboard
1. Go to **Authentication** &rarr; **URL Configuration**.
2. Set **Site URL** to:
   ```
   https://<your-vercel-app>.vercel.app
   ```
3. In **Redirect URLs**, add:
   ```
   https://<your-vercel-app>.vercel.app/**
   http://127.0.0.1:8000/**
   http://localhost:8000/**
   ```
4. Click **Save**.

### 2. In Google Cloud Console
1. Go to **APIs & Services** &rarr; **Credentials**.
2. Edit your **OAuth 2.0 Web Client ID**.
3. Under **Authorized JavaScript origins**, add:
   ```
   https://<your-vercel-app>.vercel.app
   http://127.0.0.1:8000
   ```
4. Under **Authorized redirect URIs**, verify you have:
   ```
   https://vpwrrtpotyprdxcevelr.supabase.co/auth/v1/callback
   ```
5. Click **Save**.

---

## Verification Checklist

- [ ] Azure backend responds with HTTP 200 on `https://<azure-app>.azurewebsites.net/health`
- [ ] Vercel frontend loads cleanly with medical illustration theme on `https://<vercel-app>.vercel.app`
- [ ] Clicking "Sign in with Google" authenticates and returns user profile
- [ ] Asking a clinical perfusion question streams grounded answers with citations
- [ ] Knowledge Library displays indexed textbooks
- [ ] Past conversations persist across refreshes via Neon PostgreSQL
