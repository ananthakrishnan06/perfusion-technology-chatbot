# Deploying Perfusion AI: Render (Backend) & Vercel (Frontend)

This guide walks you through deploying the **FastAPI backend on Render** (Free, no credit card required) and the **responsive clinical UI on Vercel**.

---

## Part 1: Deploy Backend to Render (Free Web Service)

### Step 1: Sign in to Render with GitHub
1. Go to **[dashboard.render.com](https://dashboard.render.com/)**.
2. Sign up or log in using your **GitHub account**.

---

### Step 2: Create a New Web Service
1. In your Render dashboard, click the blue **New +** button in the top right.
2. Select **Web Service**.
3. Under *Connect a repository*, find and click **Connect** next to:
   👉 **`ananthakrishnan06/perfusion-technology-cahtbot`**

---

### Step 3: Configure Service Details

Fill in the settings:

| Setting | Value | Notes |
| :--- | :--- | :--- |
| **Name** | `perfusion-backend` | Your service name |
| **Region** | `Frankfurt (EU Central)` or `Oregon (US West)` | Choose nearest region |
| **Branch** | `main` | Production branch |
| **Runtime** | **Docker** | Render automatically detects your `/Dockerfile` |
| **Instance Type** | **Free** ($0/month) | 100% free web service tier |

---

### Step 4: Add Environment Variables
Scroll down to the **Environment Variables** section and click **Add Environment Variable** for each:

| Key | Value to Paste |
| :--- | :--- |
| **`GROQ_API_KEY`** | `gsk_your_groq_api_key_from_console.groq.com` |
| **`DATABASE_URL`** | `postgresql://your_user:your_password@your-neon-pooler.aws.neon.tech/neondb?sslmode=require` |
| **`SUPABASE_URL`** | `https://your-project.supabase.co` |
| **`SUPABASE_ANON_KEY`** | `your_supabase_anon_public_key` |
| **`SECRET_KEY`** | `your_strong_random_secret_key` |
| **`CORS_ORIGINS`** | `*` |

*(Optional)* Under **Advanced**:
- **Health Check Path:** `/api/v1/health`

---

### Step 5: Click "Deploy Web Service"
Click the blue **Deploy Web Service** button at the bottom.

Render will start building your Docker container. In 2–3 minutes, you'll see a green **"Live"** badge with your permanent HTTPS URL:
👉 **`https://perfusion-backend-xxxx.onrender.com`**

Test it in your browser:
- `https://perfusion-backend-xxxx.onrender.com/api/v1/health` (returns `{"status":"ok"}`)
- `https://perfusion-backend-xxxx.onrender.com/docs` (interactive Swagger UI)

---

## Part 2: Connect and Deploy Frontend on Vercel

### Step 1: Update `frontend/config.js`
Once you have your Render URL, update `frontend/config.js` with your Render URL:
```javascript
window.PERFUSION_CONFIG = {
  API_BASE_URL: "https://perfusion-backend-xxxx.onrender.com",
  VERSION: "1.0.0"
};
```
Commit and push to GitHub:
```bash
git add frontend/config.js
git commit -m "chore: point frontend to live Render backend"
git push origin main
```

---

### Step 2: Deploy Frontend on Vercel
1. Go to **[vercel.com/new](https://vercel.com/new)** and log in with GitHub.
2. Click **Import** next to `ananthakrishnan06/perfusion-technology-cahtbot`.
3. In **Project Configuration**:
   - **Framework Preset:** `Other`
   - **Root Directory:** Click *Edit* and select **`frontend`**
4. Click **Deploy**.

Vercel will give you a live production URL:
👉 **`https://perfusion-technology.vercel.app`**

---

## Part 3: Live Clinical Verification

1. Open the Vercel link on your mobile phone or computer.
2. Ask a question in **Ask Perfusion AI** (multi-turn Groq streaming tokens should stream live with authentic textbook page citations).
3. Test **Clinical Calculators** (BSA & Flow Rate).
4. Verify past conversation histories load and sync with your Neon cloud database!

