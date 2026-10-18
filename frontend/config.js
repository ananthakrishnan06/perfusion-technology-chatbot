/**
 * Perfusion AI - Production Environment Configuration
 * 
 * DEPLOYMENT OPTIONS:
 * 1. Vercel Rewrites Proxy (Default & Recommended):
 *    Leave API_BASE_URL as empty string ("").
 *    All API calls (/api/v1/..., /health) will be relative and proxied by Vercel
 *    directly to your Azure App Service backend via vercel.json.
 *    Benefits: Zero CORS headaches, automatic SSL, faster response.
 * 
 * 2. Direct Cross-Origin API Calls:
 *    Set API_BASE_URL to your Azure App Service backend URL:
 *    e.g., API_BASE_URL: "https://your-perfusion-backend.azurewebsites.net"
 */

window.PERFUSION_CONFIG = {
  // Azure Backend Base URL (leave "" to use Vercel proxy rewrite)
  API_BASE_URL: "",
  
  // App Version
  VERSION: "1.0.0"
};
