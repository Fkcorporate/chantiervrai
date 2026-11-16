// ChantierVrai : application installable. Garde l'interface et la page du chantier
// du chef en cache pour pouvoir prendre des preuves sans reseau (chef.js les met en
// attente et les envoie au retour du reseau, avec leur heure de prise de vue).
var CACHE = 'chantiervrai-v5';
var PAGES = 'chantiervrai-pages';
var SHELL = ['/static/style.css', '/static/chef.js', '/static/ui.js', '/static/icons/icon-192.png', '/hors-ligne',
  '/static/fonts/Inter-Regular.woff', '/static/fonts/Inter-SemiBold.woff', '/static/fonts/Inter-Bold.woff', '/static/fonts/InterDisplay-ExtraBold.woff'];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE && k !== PAGES; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.indexOf('/static/') === 0) {
    e.respondWith(caches.match(req).then(function (hit) {
      var net = fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
        return res;
      });
      return hit || net;
    }));
    return;
  }
  if (req.mode === 'navigate') {
    // Page du chantier gardee pour pouvoir prendre des preuves sans reseau
    e.respondWith(fetch(req).then(function (res) {
      if (res.ok && res.headers.get('X-CV-Offline') === '1') {
        var copy = res.clone();
        caches.open(PAGES).then(function (c) { c.put(req.url, copy); });
      }
      return res;
    }).catch(function () {
      return caches.open(PAGES).then(function (c) { return c.match(req.url); })
        .then(function (hit) { return hit || caches.match('/hors-ligne'); });
    }));
  }
});
