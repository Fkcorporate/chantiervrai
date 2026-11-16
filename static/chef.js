/* ChantierVrai : capture des preuves sur le chantier.
   - Photo : camera integree a l'application (pas de galerie). Repli sur l'appareil photo du telephone
     si la camera n'est pas accessible et si le chantier l'autorise.
   - Video : appareil photo du telephone (90 s max).
   - Sans reseau : la preuve est gardee dans le telephone (IndexedDB) et envoyee au retour du reseau. */
(function () {
  function T(msg, n) {
    var t = (window.CV_T && window.CV_T[msg]) || msg;
    if (n === undefined) return t;
    var one = (document.documentElement.lang === 'en') ? n === 1 : Math.abs(n) < 2;   // accord du pluriel
    return t.replace(/\((s|x|es)\)/g, function (m, g) { return one ? '' : g; }).replace('%(n)s', n);
  }
  var DB_NAME = 'chantiervrai', STORE = 'envois';

  function openDb() {
    return new Promise(function (ok, ko) {
      if (!window.indexedDB) return ko(new Error('IndexedDB indisponible'));
      var r = indexedDB.open(DB_NAME, 1);
      r.onupgradeneeded = function () { r.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true }); };
      r.onsuccess = function () { ok(r.result); };
      r.onerror = function () { ko(r.error); };
    });
  }
  function tx(mode, fn) {
    return openDb().then(function (db) {
      return new Promise(function (ok, ko) {
        var t = db.transaction(STORE, mode), res = fn(t.objectStore(STORE));
        t.oncomplete = function () { ok(res && res.result !== undefined ? res.result : res); };
        t.onerror = function () { ko(t.error); };
      });
    });
  }
  function queueAll() { return tx('readonly', function (s) { return s.getAll(); }); }

  var form = document.getElementById('proof-form');
  var queueStatus = document.getElementById('queue-status');

  function showQueue() {
    if (!queueStatus) return;
    queueAll().then(function (items) {
      queueStatus.classList.toggle('hidden', !items.length);
      queueStatus.textContent = items.length ? T('%(n)s preuve(s) en attente de réseau : envoi automatique dès le retour de la connexion.', items.length) : '';
    }).catch(function () {});
  }

  var flushing = false;
  function flush() {
    if (flushing || !navigator.onLine) return;
    flushing = true;
    queueAll().then(function (items) {
      return items.reduce(function (chain, item) {
        return chain.then(function () {
          var fd = new FormData();
          item.fields.forEach(function (kv) { fd.append(kv[0], kv[1]); });
          fd.set('offline', '1');
          fd.set('client_now', String(Date.now()));
          if (item.file) fd.append('photo', item.file, item.name || 'capture.jpg');
          return fetch(item.action, { method: 'POST', body: fd, credentials: 'same-origin' }).then(function (r) {
            // envoyee (ou definitivement refusee : session expiree, chantier inaccessible) : on la retire de la file
            if (r.ok || r.status === 400 || r.status === 403 || r.status === 404) return tx('readwrite', function (s) { s.delete(item.id); });
          });
        });
      }, Promise.resolve());
    }).catch(function () {}).then(function () {
      flushing = false; showQueue();
    });
  }
  window.addEventListener('online', flush);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) flush(); });
  setInterval(flush, 60000);   // réseau qui revient sans événement « online » (3G instable)
  flush(); showQueue();

  if (!form) return;
  var required = form.dataset.required === '1';
  var status = document.getElementById('gps-status');
  var input = document.getElementById('photo');
  var send = document.getElementById('send');
  var img = document.getElementById('preview');
  var vid = document.getElementById('preview-video');
  var cam = document.getElementById('camera'), camVideo = document.getElementById('cam-video');
  var field = function (id) { return document.getElementById(id); };
  var captured = null, stream = null;

  /* Premier envoi : on montre les deux autorisations à donner, et quoi faire si l'une est refusée. */
  var guide = field('perm-guide'), help = field('perm-help');
  var perms = { geo: 'prompt', cam: 'prompt' };
  var firstTime = true;
  try { firstTime = !localStorage.getItem('cv_photo_ok'); } catch (e) {}
  function paint() {
    if (!guide) return;
    [['geo', 'Position autorisée'], ['cam', 'Caméra autorisée']].forEach(function (x) {
      var tag = guide.querySelector('#perm-' + x[0] + ' .tag'), st = perms[x[0]];
      tag.className = 'tag ' + (st === 'granted' ? 'green' : st === 'denied' ? 'bad' : 'grey');
      tag.textContent = st === 'granted' ? T(x[1]) : st === 'denied' ? T('Refusée') : T('À autoriser');
    });
    var msgs = [];
    if (perms.geo === 'denied') msgs.push(T("Position refusée. Sur Android : touchez le cadenas à côté de l'adresse, puis Autorisations, puis Position. Sur iPhone : Réglages, Safari, Position."));
    if (perms.cam === 'denied') msgs.push(T("Caméra refusée. Sur Android : touchez le cadenas à côté de l'adresse, puis Autorisations, puis Caméra. Sur iPhone : Réglages, Safari, Caméra."));
    help.textContent = msgs.join(' ');
    help.classList.toggle('hidden', !msgs.length);
    var allOk = perms.geo === 'granted' && perms.cam === 'granted';
    guide.classList.toggle('hidden', !(msgs.length || (firstTime && !allOk)));
  }
  function setPerm(k, v) { perms[k] = v; paint(); }
  if (navigator.permissions && navigator.permissions.query) {
    [['geo', 'geolocation'], ['cam', 'camera']].forEach(function (x) {
      navigator.permissions.query({ name: x[1] }).then(function (r) {
        setPerm(x[0], r.state);
        r.onchange = function () { setPerm(x[0], r.state); };
      }).catch(function () {});
    });
  }
  paint();

  function locate() {
    if (!navigator.geolocation) { status.textContent = T('Localisation non disponible sur ce téléphone.'); return; }
    navigator.geolocation.getCurrentPosition(function (p) {
      setPerm('geo', 'granted');
      field('f-lat').value = p.coords.latitude;
      field('f-lng').value = p.coords.longitude;
      field('f-acc').value = Math.round(p.coords.accuracy);
      status.textContent = T('Position trouvée (précision %(n)s m).', Math.round(p.coords.accuracy));
    }, function (err) {
      if (err && err.code === 1) setPerm('geo', 'denied');
      status.textContent = T('Position refusée : la preuve sera refusée. Autorisez la localisation.');
    }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
  }
  locate();

  function ready(fileOrBlob, isVideo) {
    var url = URL.createObjectURL(fileOrBlob);
    img.style.display = isVideo ? 'none' : 'block';
    vid.classList.toggle('hidden', !isVideo);
    if (isVideo) vid.src = url; else img.src = url;
    send.disabled = false;
  }

  function stopCamera() {
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null; cam.classList.add('hidden');
  }
  function openFilePicker(accept) {
    input.setAttribute('accept', accept);
    input.value = '';
    input.click();
  }
  function openCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      if (required) { status.textContent = T('Caméra non disponible dans ce navigateur. Ouvrez ChantierVrai dans Chrome ou Safari à jour.'); return; }
      return openFilePicker('image/*');
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1440 } }, audio: false })
      .then(function (s) { stream = s; camVideo.srcObject = s; cam.classList.remove('hidden'); setPerm('cam', 'granted'); locate(); })
      .catch(function (err) {
        if (err && (err.name === 'NotAllowedError' || err.name === 'SecurityError')) setPerm('cam', 'denied');
        if (required) { status.textContent = T('Accès à la caméra refusé. Autorisez la caméra pour ce site dans les réglages du navigateur.'); return; }
        openFilePicker('image/*');
      });
  }
  field('shoot').addEventListener('click', openCamera);
  field('cam-close').addEventListener('click', stopCamera);
  field('cam-snap').addEventListener('click', function () {
    var w = camVideo.videoWidth, h = camVideo.videoHeight;
    if (!w) return;
    var c = document.createElement('canvas'); c.width = w; c.height = h;
    c.getContext('2d').drawImage(camVideo, 0, 0, w, h);
    var at = Date.now();
    c.toBlob(function (blob) {
      captured = blob;
      field('f-capture').value = 'app';
      field('f-captured').value = String(at);
      field('f-tz').value = new Date().getTimezoneOffset();
      field('f-lm').value = ''; input.value = '';
      stopCamera(); ready(blob, false);
    }, 'image/jpeg', 0.88);
  });
  var film = field('film');
  if (film) film.addEventListener('click', function () { openFilePicker('video/*'); });
  var imp = field('import');
  if (imp) imp.addEventListener('click', function () { openFilePicker('image/*'); });

  input.addEventListener('change', function () {
    var f = input.files && input.files[0];
    if (!f) return;
    captured = null;
    field('f-capture').value = 'fichier';
    field('f-captured').value = '';
    field('f-lm').value = f.lastModified;
    field('f-tz').value = new Date().getTimezoneOffset();
    var isVideo = (f.type || '').indexOf('video/') === 0;
    if (isVideo && f.size > 110 * 1024 * 1024) { status.textContent = T('Vidéo trop lourde : filmez moins longtemps.'); send.disabled = true; return; }
    ready(f, isVideo); locate();
  });

  form.addEventListener('submit', function (e) {
    field('f-now').value = String(Date.now());
    if (!captured && !(input.files && input.files.length)) { e.preventDefault(); return; }
    if (!navigator.onLine) {
      e.preventDefault();
      if (!captured) { status.textContent = T("Pas de réseau : seules les photos prises avec la caméra de l'application peuvent attendre le réseau."); return; }
      var fields = [];
      new FormData(form).forEach(function (v, k) { if (k !== 'photo') fields.push([k, v]); });
      tx('readwrite', function (s) { s.add({ action: form.action, fields: fields, file: captured, name: 'capture.jpg', at: Date.now() }); })
        .then(function () {
          status.textContent = T('Pas de réseau : preuve gardée sur le téléphone, envoi automatique au retour du réseau.');
          captured = null; img.style.display = 'none'; send.disabled = true; showQueue();
        })
        .catch(function () { status.textContent = T('Impossible de garder la photo hors ligne sur ce téléphone.'); });
      return;
    }
    if (captured) {
      var dt = new DataTransfer();
      dt.items.add(new File([captured], 'capture.jpg', { type: 'image/jpeg', lastModified: Number(field('f-captured').value) }));
      input.files = dt.files;
    }
    send.disabled = true;
    send.classList.add('is-busy');
    send.textContent = T('Vérification et envoi…');
    var file = input.files && input.files[0];
    if (!window.fetch || !window.AbortController || (file && (file.type || '').indexOf('video/') === 0)) return;   // vidéo : envoi classique
    // Photo : envoi en arrière-plan. Si le réseau lâche en route, la photo prise dans l'application
    // est gardée et repart toute seule ; sinon le chef est prévenu au lieu de voir une page d'erreur.
    e.preventDefault();
    var fd = new FormData(form), ctl = new AbortController();
    var timer = setTimeout(function () { ctl.abort(); }, 90000);
    var keep = captured;
    fetch(form.action, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CV-Fetch': '1' }, signal: ctl.signal })
      .then(function (r) {
        clearTimeout(timer);
        try { localStorage.setItem('cv_photo_ok', '1'); } catch (er) {}
        var ct = r.headers.get('Content-Type') || '';
        if (ct.indexOf('application/json') === 0) return r.json().then(function (j) { window.location.href = j.redirect || window.location.href; });
        return r.text().then(function (html) { document.open(); document.write(html); document.close(); });
      })
      .catch(function () {
        clearTimeout(timer);
        send.classList.remove('is-busy'); send.textContent = T('Envoyer la preuve');
        if (!keep) { status.textContent = T("Réseau trop faible : l'envoi n'a pas abouti. Réessayez dans un endroit mieux couvert."); send.disabled = false; return; }
        var fields = [];
        fd.forEach(function (v, k) { if (k !== 'photo') fields.push([k, v]); });
        tx('readwrite', function (st) { st.add({ action: form.action, fields: fields, file: keep, name: 'capture.jpg', at: Date.now() }); })
          .then(function () {
            status.textContent = T('Réseau trop faible : la photo est gardée sur le téléphone et partira automatiquement.');
            captured = null; img.style.display = 'none'; showQueue();
          })
          .catch(function () { status.textContent = T('Impossible de garder la photo hors ligne sur ce téléphone.'); send.disabled = false; });
      });
  });
})();
