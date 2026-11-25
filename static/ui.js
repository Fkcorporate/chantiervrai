/* ChantierVrai : confort d'utilisation, sur toutes les pages.
   - Mots techniques expliqués au toucher (glossaire fourni par le serveur, dans la langue de la page).
   - Formulaires : le bouton indique l'envoi en cours et empêche le double envoi.
   - Messages de confirmation qui s'effacent seuls ; messages d'erreur gardés jusqu'à fermeture.
   - Bandeau discret quand le téléphone perd le réseau.
   - Images qui apparaissent en fondu une fois chargées. */
(function () {
  var T = function (m) { return (window.CV_T && window.CV_T[m]) || m; };
  var main = document.querySelector('main');

  /* ---------- Glossaire ---------- */
  var gloss = window.CV_GLOSS || [];
  var SKIP = /^(A|BUTTON|LABEL|INPUT|SELECT|TEXTAREA|OPTION|SCRIPT|STYLE|H1|NAV|CODE|SUMMARY)$/;
  function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  var bubble = null, opened = null;
  function closeBubble() {
    if (bubble) { bubble.remove(); bubble = null; }
    if (opened) { opened.setAttribute('aria-expanded', 'false'); opened = null; }
  }
  function openBubble(btn) {
    if (opened === btn) { closeBubble(); return; }
    closeBubble();
    bubble = document.createElement('div');
    bubble.className = 'gloss-bubble'; bubble.setAttribute('role', 'tooltip'); bubble.id = 'gloss-bubble';
    bubble.innerHTML = '<b></b><span></span>';
    bubble.querySelector('b').textContent = btn.textContent;
    bubble.querySelector('span').textContent = btn.dataset.def;
    document.body.appendChild(bubble);
    var r = btn.getBoundingClientRect(), w = Math.min(320, window.innerWidth - 24);
    bubble.style.width = w + 'px';
    var left = Math.max(12, Math.min(r.left + window.scrollX, window.scrollX + window.innerWidth - w - 12));
    var top = r.bottom + window.scrollY + 8;
    if (r.bottom + bubble.offsetHeight + 16 > window.innerHeight && r.top > bubble.offsetHeight + 16) top = r.top + window.scrollY - bubble.offsetHeight - 8;
    bubble.style.left = left + 'px'; bubble.style.top = top + 'px';
    btn.setAttribute('aria-expanded', 'true'); btn.setAttribute('aria-describedby', 'gloss-bubble');
    opened = btn;
  }
  if (main && gloss.length) {
    var done = {};
    var entries = gloss.map(function (e) {
      return { forms: e[0], def: e[1], re: new RegExp('(^|[^\\wÀ-ÿ])(' + e[0].map(esc).join('|') + ')(?![\\wÀ-ÿ])', 'i') };
    });
    var walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (!n.nodeValue || n.nodeValue.length < 3) return NodeFilter.FILTER_REJECT;
        for (var p = n.parentNode; p && p !== main; p = p.parentNode) {
          if (SKIP.test(p.tagName) || (p.classList && (p.classList.contains('term') || p.classList.contains('no-gloss')))) return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      entries.forEach(function (e, i) {
        if (done[i] || !node.parentNode) return;
        var m = e.re.exec(node.nodeValue);
        if (!m) return;
        done[i] = true;
        var start = m.index + m[1].length, word = m[2];
        var after = node.splitText(start); after.nodeValue = after.nodeValue.slice(word.length);
        var b = document.createElement('button');
        b.type = 'button'; b.className = 'term'; b.textContent = word; b.dataset.def = e.def;
        b.setAttribute('aria-expanded', 'false'); b.title = T("Qu'est-ce que c'est ?");
        after.parentNode.insertBefore(b, after);
        node = after;   // la suite du texte peut contenir d'autres mots
      });
    });
    document.addEventListener('click', function (ev) {
      var t = ev.target.closest && ev.target.closest('.term');
      if (t) { ev.preventDefault(); ev.stopPropagation(); openBubble(t); return; }
      if (bubble && !bubble.contains(ev.target)) closeBubble();
    });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeBubble(); });
    window.addEventListener('resize', closeBubble);
  }

  /* ---------- Formulaires : envoi en cours, pas de double envoi ---------- */
  document.addEventListener('submit', function (ev) {
    var f = ev.target;
    if (ev.defaultPrevented || f.method.toLowerCase() !== 'post' || f.target || f.dataset.nolock !== undefined || f.id === 'proof-form') return;
    if (f.dataset.busy === '1') { ev.preventDefault(); return; }
    f.dataset.busy = '1'; f.setAttribute('aria-busy', 'true');
    var btn = ev.submitter || f.querySelector('button[type=submit], button:not([type])');
    // désactivé juste après le départ du formulaire, pour garder la valeur du bouton cliqué
    setTimeout(function () {
      f.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
      if (btn) { btn.dataset.label = btn.innerHTML; btn.classList.add('is-busy'); }
    }, 0);
    setTimeout(function () { unlock(f); }, 15000);   // réseau lent : on rend la main
  }, false);
  function unlock(f) {
    delete f.dataset.busy; f.removeAttribute('aria-busy');
    f.querySelectorAll('button').forEach(function (b) { b.disabled = false; b.classList.remove('is-busy'); });
  }
  window.addEventListener('pageshow', function (e) { if (e.persisted) document.querySelectorAll('form[data-busy]').forEach(unlock); });

  /* ---------- Messages ---------- */
  document.querySelectorAll('.flash').forEach(function (fl) {
    var x = document.createElement('button');
    x.type = 'button'; x.className = 'flash-close'; x.setAttribute('aria-label', T('Fermer')); x.textContent = '×';
    x.addEventListener('click', function () { hide(fl); });
    fl.appendChild(x);
    if (fl.classList.contains('ok')) setTimeout(function () { hide(fl); }, 6000);
  });
  function hide(fl) { fl.classList.add('is-leaving'); setTimeout(function () { fl.remove(); }, 260); }

  /* ---------- Réseau ---------- */
  var bar = null;
  function net() {
    if (!navigator.onLine) {
      if (!bar) {
        bar = document.createElement('div'); bar.className = 'netbar'; bar.setAttribute('role', 'status');
        document.body.appendChild(bar);
      }
      bar.classList.remove('back'); bar.textContent = T("Hors ligne : vos photos prises dans l'application sont gardées et partiront au retour du réseau.");
    } else if (bar) {
      bar.classList.add('back'); bar.textContent = T('Connexion rétablie.');
      var b = bar; bar = null; setTimeout(function () { b.remove(); }, 2500);
    }
  }
  window.addEventListener('online', net); window.addEventListener('offline', net); net();

  /* ---------- Images en fondu ---------- */
  document.querySelectorAll('main img').forEach(function (im) {
    if (im.complete) return;
    im.classList.add('fade-img');
    im.addEventListener('load', function () { im.classList.add('is-loaded'); }, { once: true });
    im.addEventListener('error', function () { im.classList.add('is-loaded'); }, { once: true });
  });
})();

/* Panneau « Plus » (menu de l'application sur téléphone) */
(function () {
  document.addEventListener('click', function (ev) {
    var open = ev.target.closest && ev.target.closest('[data-sheet]');
    if (open) {
      var d = document.getElementById(open.dataset.sheet);
      if (d && d.showModal) { d.showModal(); d.classList.add('is-open'); open.setAttribute('aria-expanded', 'true'); }
      return;
    }
    var dlg = ev.target.closest && ev.target.closest('dialog.sheet');
    if (ev.target.matches && ev.target.matches('dialog.sheet')) dlg = ev.target;   // clic sur le fond
    if (dlg && (ev.target === dlg || ev.target.closest('[data-close]'))) closeSheet(dlg);
  });
  function closeSheet(d) {
    d.classList.remove('is-open'); d.classList.add('is-closing');
    setTimeout(function () { d.classList.remove('is-closing'); if (d.open) d.close(); }, 200);
    document.querySelectorAll('[data-sheet="' + d.id + '"]').forEach(function (b) { b.setAttribute('aria-expanded', 'false'); });
  }
  document.querySelectorAll('dialog.sheet').forEach(function (d) {
    d.addEventListener('cancel', function (e) { e.preventDefault(); closeSheet(d); });
  });
})();

/* Barre du haut : un fin trait apparaît dès qu'on fait défiler */
(function () {
  var bar = document.querySelector('.appbar');
  if (!bar) return;
  var on = false;
  function tick() { var s = window.scrollY > 4; if (s !== on) { on = s; bar.classList.toggle('scrolled', s); } }
  window.addEventListener('scroll', tick, { passive: true }); tick();
})();

/* Titre compact de la barre du haut : il apparaît quand le grand titre de la page sort de l'écran */
(function () {
  var title = document.getElementById('ab-title'),
      h1 = [].slice.call(document.querySelectorAll('main h1')).filter(function (h) { return h.offsetParent; })[0];   // le premier titre visible (la version ordinateur est masquée)
  if (!title || !h1 || !('IntersectionObserver' in window) || window.innerWidth >= 1000) return;
  if (h1.getBoundingClientRect().top > 520) return;          // grand titre loin du haut : barre toujours titrée
  title.style.transition = 'none'; title.classList.add('is-hidden');
  void title.offsetHeight; title.style.transition = '';          // masqué d'emblée, sans animation au chargement
  new IntersectionObserver(function (es) { title.classList.toggle('is-hidden', es[0].isIntersecting); },
    { rootMargin: '-60px 0px 0px 0px' }).observe(h1);
})();

/* Flèche de retour de la barre du haut : elle suit le lien « ← … » de la page quand il existe (parent exact) */
(function () {
  var back = document.querySelector('.appbar .ab-back');
  var link = document.querySelector('main .backlink[href]');
  if (back && link) {
    back.setAttribute('href', link.getAttribute('href'));
    back.removeAttribute('onclick');
  }
})();

/* Envoi de fichiers : une zone claire, dans la langue de la page, au lieu du « Choose Files / No file chosen » du navigateur.
   Le vrai champ reste en place (transparent, par-dessus la zone) : clic, clavier, glisser-déposer et validation restent ceux du navigateur. */
(function () {
  var T = function (m, n) { var s = (window.CV_T && window.CV_T[m]) || m; return n == null ? s : s.replace('%(n)s', n); };
  var ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>';
  function enhance(inp) {
    if (inp.dataset.fz || inp.classList.contains('hidden') || inp.closest('.camera, .filezone')) return;
    if (getComputedStyle(inp).display === 'none') return;
    inp.dataset.fz = '1';
    var zone = document.createElement('span');
    zone.className = 'filezone';
    var multi = inp.multiple;
    zone.innerHTML = '<span class="fz-ico">' + ICON + '</span><span class="fz-txt"><b></b><span class="fz-name"></span></span>';
    var title = zone.querySelector('b'), name = zone.querySelector('.fz-name');
    function update() {
      var f = inp.files || [];
      zone.classList.toggle('has-file', f.length > 0);
      title.textContent = f.length ? T('Changer') : T(multi ? 'Choisir des fichiers' : 'Choisir un fichier');
      name.textContent = !f.length ? T('Aucun fichier choisi') : f.length === 1 ? f[0].name : T('%(n)s fichiers choisis', f.length);
    }
    inp.parentNode.insertBefore(zone, inp);
    zone.appendChild(inp);
    inp.addEventListener('change', update);
    ['dragenter', 'dragover'].forEach(function (e) { inp.addEventListener(e, function () { zone.classList.add('is-drag'); }); });
    ['dragleave', 'drop'].forEach(function (e) { inp.addEventListener(e, function () { zone.classList.remove('is-drag'); }); });
    var form = inp.form;
    if (form) form.addEventListener('reset', function () { setTimeout(update, 0); });
    update();
  }
  document.querySelectorAll('main input[type=file]').forEach(enhance);

  /* Mot de passe : un œil pour vérifier ce qu'on a tapé (utile sur téléphone) */
  var EYE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 5.1A10.9 10.9 0 0 1 12 5c6.4 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.1M6.6 6.6C3.9 8.4 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 4.3-1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';
  document.querySelectorAll('main input[type=password]').forEach(function (inp) {
    if (inp.closest('.pw-wrap')) return;
    var wrap = document.createElement('span');
    wrap.className = 'pw-wrap';
    inp.parentNode.insertBefore(wrap, inp);
    wrap.appendChild(inp);
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'pw-eye'; b.innerHTML = EYE;
    b.setAttribute('aria-label', T('Afficher le mot de passe'));
    b.addEventListener('click', function () {
      var show = inp.type === 'password';
      inp.type = show ? 'text' : 'password';
      b.innerHTML = show ? EYE_OFF : EYE;
      b.setAttribute('aria-label', T(show ? 'Masquer le mot de passe' : 'Afficher le mot de passe'));
      b.setAttribute('aria-pressed', show ? 'true' : 'false');
      inp.focus();
    });
    wrap.appendChild(b);
  });
})();

/* Glisser pour payer : un geste volontaire avant de verser de l'argent, comme dans une application bancaire.
   Le vrai bouton reste dans le formulaire (masqué visuellement) : au clavier, Tab puis Entrée valide comme avant. */
(function () {
  var ARROW = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M13 6l6 6-6 6"/></svg>';
  var CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5L19 7"/></svg>';
  document.querySelectorAll('main button[data-slide]').forEach(function (btn) {
    var form = btn.form; if (!form) return;
    var track = document.createElement('div');
    track.className = 'slide-pay' + (btn.disabled ? ' is-disabled' : '');
    track.setAttribute('aria-hidden', 'true');
    track.innerHTML = '<span class="sp-fill"></span><span class="sp-label"></span><span class="sp-knob">' + ARROW + '</span>';
    track.querySelector('.sp-label').textContent = btn.dataset.slide;
    btn.parentNode.insertBefore(track, btn);
    btn.classList.add('sr-pay');
    var knob = track.querySelector('.sp-knob'), fill = track.querySelector('.sp-fill');
    var startX = 0, x = 0, max = 0, dragging = false;
    function place(v) { x = Math.max(0, Math.min(max, v)); knob.style.transform = 'translateX(' + x + 'px)'; fill.style.width = (x + 58) + 'px'; }
    function reset() { knob.style.transition = 'transform .25s ease'; fill.style.transition = 'width .25s ease'; place(0);
      setTimeout(function () { knob.style.transition = ''; fill.style.transition = ''; }, 260); }
    knob.addEventListener('pointerdown', function (e) {
      if (btn.disabled || track.classList.contains('is-done')) return;
      dragging = true; track.classList.add('is-dragging');
      max = track.clientWidth - knob.offsetWidth - 12; startX = e.clientX - x;
      knob.setPointerCapture(e.pointerId); e.preventDefault();
    });
    knob.addEventListener('pointermove', function (e) { if (dragging) place(e.clientX - startX); });
    function end() {
      if (!dragging) return; dragging = false; track.classList.remove('is-dragging');
      if (x >= max * 0.92) {
        place(max); track.classList.add('is-done'); knob.innerHTML = CHECK;
        if (form.requestSubmit) form.requestSubmit(btn); else btn.click();
      } else reset();
    }
    knob.addEventListener('pointerup', end);
    knob.addEventListener('pointercancel', end);
    // Un simple appui ne paie pas : il montre le geste attendu
    knob.addEventListener('click', function () {
      if (btn.disabled || track.classList.contains('is-done') || x > 4) return;
      max = track.clientWidth - knob.offsetWidth - 12;
      knob.style.transition = 'transform .3s ease'; place(Math.min(48, max)); setTimeout(reset, 320);
    });
  });
})();

/* Caméra plein écran : la position trouvée s'affiche aussi par-dessus le viseur */
(function () {
  var src = document.getElementById('gps-status'), dst = document.querySelector('#camera .cam-gps');
  if (!src || !dst) return;
  function sync() {
    var t = (src.textContent || '').trim();
    dst.textContent = t;
    dst.classList.toggle('is-ok', /(trouvée|found|précision|accuracy)/i.test(t) && !/(refus|denied)/i.test(t));
  }
  sync();
  new MutationObserver(sync).observe(src, { childList: true, characterData: true, subtree: true });
  // Échap ferme la caméra comme le bouton Annuler
  document.addEventListener('keydown', function (e) {
    var cam = document.getElementById('camera'), close = document.getElementById('cam-close');
    if (e.key === 'Escape' && cam && !cam.classList.contains('hidden') && close) close.click();
  });
})();

/* Panneau « Toutes les fonctions » : recherche instantanée, et la recherche reprend la main à l'ouverture */
(function () {
  var dr = document.getElementById('fn-drawer'), q = document.getElementById('fn-q');
  if (!dr || !q) return;
  var norm = function (s) { return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); };
  var items = [].slice.call(dr.querySelectorAll('.dr-item'));
  items.forEach(function (a) { a.dataset.n = norm(a.dataset.q); });
  var empty = dr.querySelector('.dr-empty');
  // Mode simple : « Autres fonctions » est replié ; un toucher le déplie, la recherche y cherche aussi
  var more = dr.querySelector('[data-collapsed]'), moreBtn = more && more.querySelector('.dr-more-btn'),
      moreList = more && more.querySelector('ul'), opened = false;
  var setMore = function (open) {
    if (!more) return;
    moreList.hidden = !open; moreBtn.setAttribute('aria-expanded', open ? 'true' : 'false'); more.classList.toggle('is-open', open);
  };
  if (moreBtn) moreBtn.addEventListener('click', function () {
    opened = moreList.hidden; setMore(opened);
    if (opened) setTimeout(function () { moreBtn.scrollIntoView({block: 'start', behavior: 'smooth'}); }, 30);
  });
  q.addEventListener('input', function () {
    var words = norm(q.value).split(/\s+/).filter(Boolean), shown = 0;
    items.forEach(function (a) {
      var ok = words.every(function (w) { return a.dataset.n.indexOf(w) > -1; });
      a.parentNode.hidden = !ok; if (ok) shown++;
    });
    dr.querySelectorAll('[data-group]').forEach(function (g) { g.hidden = !g.querySelector('li:not([hidden])'); });
    if (more) setMore(words.length ? !more.hidden : opened);
    empty.hidden = shown > 0;
  });
  // Entrée ouvre le premier résultat
  q.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    var first = dr.querySelector('li:not([hidden]) .dr-item'); if (first) { e.preventDefault(); first.click(); }
  });
  // Sur ordinateur, le curseur va directement dans la recherche ; sur téléphone on évite d'ouvrir le clavier
  new MutationObserver(function () {
    if (dr.open && window.matchMedia('(min-width: 1000px)').matches) setTimeout(function () { q.focus(); }, 60);
    if (!dr.open) { q.value = ''; q.dispatchEvent(new Event('input')); }
  }).observe(dr, { attributes: true, attributeFilter: ['open'] });
  // Raccourci clavier : « / » ouvre le panneau
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && !/input|textarea|select/i.test((document.activeElement || {}).tagName || '') && !dr.open) {
      e.preventDefault(); dr.showModal(); dr.classList.add('is-open');
    }
  });
})();

/* Raccourcis de l'accueil : ouvrent « Toutes les fonctions » directement à la bonne famille */
document.addEventListener('click', function (e) {
  var b = e.target.closest && e.target.closest('[data-group-go]');
  if (!b) return;
  setTimeout(function () {
    var g = document.getElementById(b.dataset.groupGo);
    if (!g) return;
    g.scrollIntoView({block: 'start'});
    g.classList.add('dr-flash');
    setTimeout(function () { g.classList.remove('dr-flash'); }, 1400);
  }, 80);
});

/* Montants lisibles pendant la saisie : 1250000 → 1 250 000 */
document.querySelectorAll('input[data-money]').forEach(function (i) {
  i.addEventListener('input', function () {
    var v = parseInt(i.value.replace(/\D/g, ''), 10);
    i.value = v ? v.toLocaleString('fr-FR').replace(/ | /g, ' ') : '';
  });
});

/* « ＋ › Photo » : la page du chantier s'ouvre directement sur l'appareil photo, comme Snapchat */
(function () {
  if (location.hash !== '#photo') return;
  var go = function () {
    var b = document.getElementById('shoot');
    if (!b) return;
    history.replaceState(null, '', location.pathname + location.search);
    b.scrollIntoView({block: 'center'}); b.click();
  };
  if (document.readyState === 'complete') setTimeout(go, 150); else window.addEventListener('load', function () { setTimeout(go, 150); });
})();

/* Ordinateur : palette de commandes (⌘K / Ctrl+K ou « / »), filtrage au clavier */
(function () {
  var dlg = document.getElementById('dk-cmd');
  if (!dlg || !dlg.showModal) return;
  var input = dlg.querySelector('input'), sel = 0;
  function links() { return [].slice.call(dlg.querySelectorAll('li a')).filter(function (a) { return a.parentNode.style.display !== 'none'; }); }
  function mark() { var l = links(); l.forEach(function (a, i) { a.classList.toggle('on', i === sel); }); if (l[sel]) l[sel].scrollIntoView({ block: 'nearest' }); }
  function filter() {
    var q = input.value.trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    dlg.querySelectorAll('li').forEach(function (li) {
      if (li.classList.contains('dk-cmd-h')) { li.style.display = q ? 'none' : ''; return; }
      var t = li.textContent.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
      li.style.display = !q || t.indexOf(q) > -1 ? '' : 'none';
    });
    sel = 0; mark();
  }
  function open() { input.value = ''; filter(); dlg.showModal(); input.focus(); }
  document.querySelectorAll('[data-cmdk]').forEach(function (b) { b.addEventListener('click', open); });
  document.addEventListener('keydown', function (e) {
    var typing = /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || '');
    if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || (e.key === '/' && !typing && !dlg.open)) { e.preventDefault(); open(); }
  });
  input.addEventListener('input', filter);
  input.addEventListener('keydown', function (e) {
    var l = links();
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, l.length - 1); mark(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); mark(); }
    else if (e.key === 'Enter' && l[sel]) { e.preventDefault(); location.href = l[sel].href; }
  });
  dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
})();
/* Ordinateur : une ligne de tableau entière est cliquable */
document.addEventListener('click', function (e) {
  var tr = e.target.closest && e.target.closest('tr[data-href]');
  if (tr && !e.target.closest('a,button,form')) location.href = tr.dataset.href;
});

/* Page « Plus » du chantier : recherche dans toutes les fonctions, y compris celles masquées */
(function () {
  var box = document.querySelector('[data-px]');
  if (!box) return;
  var q = box.querySelector('[data-px-q]'), empty = box.querySelector('[data-px-empty]');
  var norm = function (t) { return (t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); };
  var items = [].slice.call(box.querySelectorAll('[data-px-it]'));
  items.forEach(function (a) { a.dataset.n = norm(a.dataset.n); });
  q.addEventListener('input', function () {
    var words = norm(q.value).split(/\s+/).filter(Boolean), shown = 0;
    items.forEach(function (a) {
      var ok = !words.length || words.every(function (w) { return a.dataset.n.indexOf(w) > -1; });
      a.hidden = !ok; if (ok && words.length) shown++;
    });
    box.querySelectorAll('[data-px-grp]').forEach(function (g) {
      if (g.hasAttribute('data-px-keep')) { g.hidden = words.length > 0; return; }
      var hiddenGrp = g.classList.contains('px-hidden');
      g.hidden = words.length ? !g.querySelector('[data-px-it]:not([hidden])') : hiddenGrp;
    });
    empty.hidden = !words.length || shown > 0;
  });
})();
