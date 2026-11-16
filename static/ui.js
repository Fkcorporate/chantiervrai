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
  var title = document.getElementById('ab-title'), h1 = document.querySelector('main h1');
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
