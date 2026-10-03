// Minimal service worker: makes the site installable.
// It never caches pages, so logged-in content is always fresh.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() => new Response(
        '<meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<body style="font-family:sans-serif;text-align:center;padding:3rem">' +
        '<h2>You\'re offline</h2><p>Connect to the internet to see lost and found items.</p></body>',
        { headers: { 'Content-Type': 'text/html' } }
      ))
    );
  }
});
