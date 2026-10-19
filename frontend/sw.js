// Perfusion AI - Progressive Web App Service Worker
// Version: 20261018_v1
// Scope: Static shell and visual assets only.
// STRICT SECURITY POLICY: API calls, authentication tokens, private chat histories,
// and user data are NEVER stored in CacheStorage.

const CACHE_NAME = 'perfusion-ai-v20261019_v1';

// Static Shell Assets to Pre-cache
const PRECACHE_ASSETS = [
  '/',
  '/index.html',
  '/style.css?v=20261018_v10',
  '/config.js',
  '/app.js',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-192.png',
  '/icons/icon-maskable-512.png',
  '/icons/apple-touch-icon.png',
  '/favicon.png',
  '/images/bg_perfusion.png?v=2'
];

// Helper: Determine if request is an API call or contains sensitive data
function isApiOrSensitiveRequest(url, request) {
  // Only GET requests can be considered for caching
  if (request.method !== 'GET') return true;

  const pathname = url.pathname.toLowerCase();
  
  // Explicitly bypass all backend APIs
  if (
    pathname.startsWith('/api/') ||
    pathname.includes('/auth') ||
    pathname.includes('/chat') ||
    pathname.includes('/conversations') ||
    pathname.includes('/memories') ||
    pathname.includes('/documents') ||
    pathname.includes('/retrieval') ||
    pathname.includes('/study') ||
    pathname.includes('/health') ||
    pathname.includes('/docs') ||
    pathname.includes('/openapi.json')
  ) {
    return true;
  }

  // Bypass Google identity / tokeninfo endpoints
  if (url.hostname.includes('googleapis.com') || url.hostname.includes('supabase.co')) {
    return true;
  }

  // Bypass Server-Sent Events (SSE) streaming connections
  const acceptHeader = request.headers.get('accept') || '';
  if (acceptHeader.includes('text/event-stream')) {
    return true;
  }

  return false;
}

// 1. INSTALL LIFECYCLE: Pre-cache static shell
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Use catch for individual assets so missing optional assets don't abort installation
      return Promise.allSettled(
        PRECACHE_ASSETS.map((asset) =>
          cache.add(asset).catch((err) => {
            console.debug(`[PWA SW] Precache note for ${asset}:`, err);
          })
        )
      );
    })
  );
});

// 2. ACTIVATE LIFECYCLE: Purge obsolete cache versions and claim clients
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME && name.startsWith('perfusion-ai-'))
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// 3. FETCH LIFECYCLE: Network-first for dynamic code; strictly bypass API
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Security Rule 1: Always bypass and never cache API or sensitive requests
  if (isApiOrSensitiveRequest(url, event.request)) {
    return; // Let browser perform default network request without SW interference
  }

  // Static Assets Strategy:
  // For navigation requests (HTML page): Network-First, fallback to cached index.html
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const clone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return networkResponse;
        })
        .catch(() => {
          return caches.match('/index.html') || caches.match('/');
        })
    );
    return;
  }

  // For static scripts, styles, icons, and images:
  // Stale-While-Revalidate (Fast offline loading + background update)
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      const fetchPromise = fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
            const clone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return networkResponse;
        })
        .catch(() => cachedResponse);

      return cachedResponse || fetchPromise;
    })
  );
});

