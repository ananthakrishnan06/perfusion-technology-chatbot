/**
 * Perfusion AI - Production Environment Configuration
 * 
 * BACKEND HOSTING: Google Cloud Run
 * FRONTEND HOSTING: Vercel
 * 
 * Two ways to connect:
 * 
 * Option 1: Direct Cloud Run URL (Recommended & Simplest)
 * Set API_BASE_URL to your Google Cloud Run service URL:
 * e.g., API_BASE_URL: "https://perfusion-backend-xxxxxx-uc.a.run.app"
 * 
 * Option 2: Local Development (Default fallback)
 * When API_BASE_URL is empty ("") and running locally on localhost:8000,
 * it will automatically use relative API routes.
 */

window.PERFUSION_CONFIG = {
  // Replace with your Google Cloud Run service URL once deployed, or leave "" for local/Vercel rewrite
  API_BASE_URL: "",
  
  // App Version
  VERSION: "1.0.0"
};
