# Deploying Perfusion AI: Google Cloud Run (Backend) & Vercel (Frontend)

This guide walks you through deploying the **FastAPI + FAISS + Groq backend on Google Cloud Run** and the **responsive frontend on Vercel**.

---

## Part 1: Deploy Backend to Google Cloud Run

### Step 1: Connect Repository in Google Cloud Console
1. On your Google Cloud Run screen (under **Deploy a web service**), click **Connect repository** (with the GitHub icon).
2. If prompted, authorize Google Cloud Build to access your GitHub account.
3. Select your repository:
   - **Repository:** `ananthakrishnan06/perfusion-technology-cahtbot`
   - **Branch:** `^main$`
   - **Build Type:** Select **Dockerfile**
   - **Source location:** `/Dockerfile`
4. Click **Save** / **Next**.

---

### Step 2: Configure Service Settings
Fill in the service creation form:

| Setting | Value | Why |
| :--- | :--- | :--- |
| **Service name** | `perfusion-backend` | App name identifier |
| **Region** | `us-central1` (Iowa) or `asia-south1` (Mumbai) | Fast low-latency region |
| **Authentication** | **Allow unauthenticated invocations** | Publicly accessible API |
| **Ingress control** | **All** | Allows requests from Vercel frontend |
| **Min instances** | `0` | **Scale to zero** (ensures $0 cost when idle) |
| **Max instances** | `3` or `5` | Prevents runaway costs |

---

### Step 3: Container Capacity & Performance
Click **Container, Volumes, Networking, Security** (or *Advanced settings*):
- **Port:** `8080` (matches `$PORT` in Dockerfile)
- **CPU:** `1 vCPU`
- **Memory:** `1 GiB` or `2 GiB` (recommended for Sentence-Transformers and FAISS vector search)
- **Request timeout:** `300` seconds (allows Groq SSE multi-turn token streaming without interruption)

---

### Step 4: Environment Variables (Secrets)
Under **Variables & Secrets**, click **Add Variable** for each of the following:

| Name | Example / Value | Description |
| :--- | :--- | :--- |
| `GROQ_API_KEY` | `gsk_...` | Your production Groq API Key |
| `DATABASE_URL` | `postgresql://...@ep-xxx.neon.tech/neondb?sslmode=require` | Your Neon PostgreSQL connection string |
| `SECRET_KEY` | `perfusion-secret-key-prod-2026` | Random secure secret string |
| `SUPABASE_URL` | `https://xxxx.supabase.co` | Your Supabase Project URL |
| `SUPABASE_ANON_KEY` | `eyJhbGciOiJIUzI1NiIsInR5...` | Your Supabase Public / Anon API Key |
| `CORS_ORIGINS` | `*` | Allows cross-origin requests from Vercel |

---

### Step 5: Click Create & Get Service URL
Click **Create**. Google Cloud Build will automatically:
1. Clone the repo and build the container from `Dockerfile`.
2. Push the image to Artifact Registry.
3. Deploy to Cloud Run.

Once deployment finishes (green checkmark), copy your live HTTPS URL:
👉 **`https://perfusion-backend-xxxxxx-uc.a.run.app`**

Test it in your browser:
- `https://perfusion-backend-xxxxxx-uc.a.run.app/api/v1/health` (should return `{"status":"ok"}`)
- `https://perfusion-backend-xxxxxx-uc.a.run.app/docs` (interactive Swagger UI)

---

## Part 2: Deploy Frontend to Vercel

### Step 1: Update API URL in `frontend/config.js`
Before deploying frontend, paste your Cloud Run URL into `frontend/config.js`:
```javascript
window.PERFUSION_CONFIG = {
  API_BASE_URL: "https://perfusion-backend-xxxxxx-uc.a.run.app",
  VERSION: "1.0.0"
};
```
Commit and push this change to GitHub:
```bash
git add frontend/config.js
git commit -m "chore: point frontend to live Cloud Run backend"
git push origin main
```

---

### Step 2: Import into Vercel
1. Go to [Vercel Dashboard](https://vercel.com/new).
2. Click **Add New... → Project**.
3. Import your GitHub repository: `ananthakrishnan06/perfusion-technology-cahtbot`.
4. In **Project Configuration**:
   - **Framework Preset:** `Other`
   - **Root Directory:** Click *Edit* and select **`frontend`**
5. Click **Deploy**!

In less than 30 seconds, Vercel will give you a live production URL:
👉 **`https://perfusion-technology.vercel.app`**

---

## Part 3: Production Verification Checklist

- [ ] Open your Vercel URL on mobile and desktop
- [ ] Test asking a question in **Ask Perfusion AI** (streaming tokens + page citations should load)
- [ ] Verify **Knowledge Library** shows the indexed 799-page textbook
- [ ] Sign in with institutional email or Google OAuth via Supabase
- [ ] Verify past chat history saves and loads from Neon PostgreSQL
