
const CACHE_NAME = 'hisa-account-pwa-v2';
const ASSETS_TO_CACHE = [
    '/',
    '/login',
    '/manifest.json'
];

// 1. Install Event: Cache app shell & core routes
self.addEventListener('install', (e) => {
    e.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS_TO_CACHE);
        }).then(() => self.skipWaiting()) // Activate new service worker immediately
    );
});

// 2. Activate Event: Clean up old version caches
self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('[Service Worker] Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        }).then(() => self.clients.claim()) // Take control of all open pages immediately
    );
});

// 3. Fetch Event: Network-first for dynamic pages/data, cache fallback for offline
self.addEventListener('fetch', (e) => {
    // Skip non-GET requests (like Firestore POST/PUT calls)
    if (e.request.method !== 'GET') return;

    e.respondWith(
        fetch(e.request)
            .then((networkResponse) => {
                // Optional: If you want to dynamically cache successful GET requests, you can do it here
                return networkResponse;
            })
            .catch(() => {
                // If offline or network fails, fall back to cache
                return caches.match(e.request).then((cachedResponse) => {
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    // If it's a page navigation and not in cache, fallback to root index
                    if (e.request.mode === 'navigate') {
                        return caches.match('/');
                    }
                });
            })
    );
});