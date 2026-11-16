// Tests de la logique de l'application mobile (sans telephone) : traductions, file hors ligne,
// et parcours complet contre le vrai serveur ChantierVrai avec le meme client API que l'application.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, mkdtempSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn, execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { createApi, proofFields, NetworkError } from '../src/core/apiClient.js';
import { createQueue, MAX_AGE_MS } from '../src/core/queue.js';
import { t, setLang, KEYS } from '../src/core/i18n.js';
import { fcfa } from '../src/core/format.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

test('chaque texte affiché par l\'application a sa traduction anglaise', () => {
  const files = ['App.js', ...readdirSync(join(ROOT, 'src/screens')).map((f) => `src/screens/${f}`)];
  const used = new Set();
  for (const f of files) {
    const src = readFileSync(join(ROOT, f), 'utf8');
    for (const m of src.matchAll(/\bt\(\s*'((?:[^'\\]|\\.)*)'/g)) used.add(m[1].replace(/\\'/g, "'"));
    for (const m of src.matchAll(/\['notify_\w+', '([^']+)'\]/g)) used.add(m[1]);
  }
  const missing = [...used].filter((k) => !KEYS.includes(k));
  assert.deepEqual(missing, []);
  setLang('en');
  assert.equal(t('%(n)s preuve(s) en attente de réseau', { n: 3 }), '3 pieces of evidence waiting for network');
  assert.equal(t('%(n)s preuve(s) en attente de réseau', { n: 1 }), '1 piece of evidence waiting for network');
  setLang('fr');
  assert.equal(t('Prendre une photo'), 'Prendre une photo');
  assert.equal(t('%(n)s preuve(s) en attente de réseau', { n: 1 }), '1 preuve en attente de réseau');
  assert.equal(t('%(n)s preuve(s) en attente de réseau', { n: 2 }), '2 preuves en attente de réseau');
  assert.equal(fcfa(2500000), '2 500 000 FCFA');
});

test('file d\'attente hors ligne : garde, envoie, abandonne', async () => {
  let store = [], removed = [], now = 1_000_000, mode = 'offline';
  const sent = [];
  const q = createQueue({
    load: async () => JSON.parse(JSON.stringify(store)),
    save: async (items) => { store = items; },
    removeFile: async (u) => removed.push(u),
    now: () => now,
    send: async (item) => {
      if (mode === 'offline') throw new NetworkError('offline');
      if (item.fileUri === 'refus') { const e = new Error('Forbidden'); e.status = 403; throw e; }
      sent.push(item.fileUri);
      return { ok: item.fileUri !== 'floue' };
    },
  });
  await q.add({ fileUri: 'a', capturedAt: now });
  await q.add({ fileUri: 'floue', capturedAt: now });
  await q.add({ fileUri: 'refus', capturedAt: now });
  let r = await q.flush();
  assert.equal(r.kept, 1); assert.equal((await q.list()).length, 3);
  mode = 'online';
  await q.add({ fileUri: 'vieille', capturedAt: now - MAX_AGE_MS - 1 });
  r = await q.flush();
  assert.deepEqual([r.sent, r.rejected, r.expired], [1, 2, 1]);
  assert.deepEqual(sent, ['a', 'floue']);
  assert.equal((await q.list()).length, 0);
  assert.deepEqual(removed.sort(), ['a', 'floue', 'refus', 'vieille']);
});

test('parcours complet contre le serveur : chef (français) et propriétaire (anglais)', { timeout: 120000 }, async () => {
  const inst = mkdtempSync(join(tmpdir(), 'cv-mobile-'));
  const env = { ...process.env, CV_INSTANCE: inst, CV_SYNC: '1', EXPO_PUSH: '0', SECRET_KEY: 'test', PORT: '5066' };
  const code = execFileSync('python3', [join(ROOT, 'tests/seed_server.py')], { env }).toString().trim();
  const server = spawn('python3', [join(ROOT, '..', 'app.py')], { env, stdio: 'ignore' });
  try {
    const base = 'http://127.0.0.1:5066';
    for (let i = 0; i < 50; i++) {
      try { await fetch(`${base}/api/v1/version`); break; } catch (e) { await new Promise((r) => setTimeout(r, 200)); }
    }
    let chefToken = null, ownToken = null, offline = false;
    const fetchImpl = (...a) => (offline ? Promise.reject(new TypeError('Network request failed')) : fetch(...a));
    const chef = createApi({ baseUrl: base, getToken: async () => chefToken, fetchImpl, lang: 'fr' });
    const own = createApi({ baseUrl: base, getToken: async () => ownToken, fetchImpl, lang: 'en' });

    await assert.rejects(chef.login('k@x.ci', 'faux'), /incorrect/);
    chefToken = (await chef.login('k@x.ci', 'Bingerville-2026', undefined, 'Test', 'fr')).token;
    ownToken = (await own.login('ama@x.co.uk', 'Bingerville-2026')).token;
    const j = await chef.joinProject(code);
    assert.equal(j.ok, true);
    const [p] = (await chef.projects()).projects;
    assert.equal(p.role, 'chef');
    const detail = (await chef.project(p.id)).project;
    assert.ok(detail.capture_token);

    // photo « prise » par l'application : image JPEG minimale valide
    const photoOf = (seed) => Buffer.from(execFileSync('python3', ['-c',
      `import io,sys,base64,numpy as n;from PIL import Image;b=io.BytesIO();Image.fromarray(n.random.default_rng(${seed}).integers(0,255,(240,320,3),dtype=n.uint8)).save(b,"JPEG");print(base64.b64encode(b.getvalue()).decode())`]).toString().trim(), 'base64');
    let seed = 0;
    const form = (meta) => {
      const photo = photoOf(++seed);
      const f = new FormData();
      const fields = proofFields(meta);
      Object.keys(fields).forEach((k) => f.append(k, fields[k]));
      f.append('photo', new Blob([photo], { type: 'image/jpeg' }), 'capture.jpg');
      return f;
    };
    const nonce = (await chef.attestationNonce()).nonce;
    const meta = { captureToken: detail.capture_token, capturedAt: Date.now() - 2000, clientNow: Date.now(),
      coords: { latitude: 5.3522, longitude: -3.8891, accuracy: 7 }, note: 'Fouilles', platform: 'android',
      attestation: 'jeton-test', nonce };
    const r1 = await chef.uploadProof(p.id, form(meta));
    assert.equal(r1.ok, true, JSON.stringify(r1));

    // faux GPS signalé par le téléphone : refusé, motif en français pour le chef
    const r2 = await chef.uploadProof(p.id, form({ ...meta, nonce: null, attestation: null, capturedAt: Date.now(), clientNow: Date.now(),
      coords: { latitude: 5.3522, longitude: -3.8891, accuracy: 3, mocked: true } }));
    assert.equal(r2.ok, false);
    assert.ok(r2.reasons.some((x) => x.includes('faux GPS')), r2.reasons.join());

    // sans réseau : la preuve attend, puis part toute seule
    let saved = [];
    const q = createQueue({ load: async () => saved, save: async (i) => { saved = i; }, removeFile: async () => {},
      send: async (item) => chef.uploadProof(item.projectId, form({ ...item.meta, clientNow: Date.now(), offline: true })) });
    offline = true;
    await assert.rejects(chef.project(p.id), (e) => e.name === 'NetworkError');
    const shotAt = Date.now();                      // photo prise apres l'ouverture de l'ecran, sans reseau
    await q.add({ projectId: p.id, capturedAt: shotAt, meta: { ...meta, nonce: null, attestation: null, capturedAt: shotAt } });
    assert.equal((await q.flush()).kept, 1);
    offline = false;
    const fl = await q.flush();
    assert.equal(fl.sent, 1, JSON.stringify(fl.results));

    const steps = (await chef.project(p.id)).project.steps;
    const d1 = await chef.stepAction(p.id, steps[0].id, 'declarer');
    assert.equal(d1.ok, true);
    const ownView = (await own.project(p.id)).project;
    assert.equal(ownView.current.status_label, 'Declared complete');
    assert.equal(ownView.proofs.filter((x) => x.ok).length, 2);
    const v = await own.stepAction(p.id, steps[0].id, 'valider', { override: '1' });
    assert.ok(v.messages[0].includes('Stage approved'), v.messages[0]);
    const notes = (await chef.notifications()).notifications;
    assert.ok(notes.some((n) => n.title === 'Paiement à venir' && n.link === '/paiements/recus'), notes.map((n) => n.title).join());

    // Paiement suivi : le propriétaire déclare depuis l'application, le chef confirme depuis la sienne
    const toPay = (await own.payments()).a_payer;
    assert.equal(toPay.length, 1);
    assert.equal(toPay[0].telephone, '0700000000');
    await assert.rejects(own.declarePayment('etape', steps[0].id, { amount: '1000', method: 'mobile_money' }),
      (e) => e.status === 400 && /reference or the receipt/.test(e.message));
    const dec = await own.declarePayment('etape', steps[0].id,
      { amount: String(toPay[0].reste), method: 'mobile_money', reference: 'WAVE-42' });
    assert.equal(dec.ok, true);
    assert.equal((await chef.me()).user.paiements_a_confirmer, 1);
    const [pending] = (await chef.payments()).a_confirmer;
    assert.equal(pending.reference, 'WAVE-42');
    assert.equal(pending.statut_label, 'Déclaré, en attente de confirmation');
    await assert.rejects(own.answerPayment(pending.id, 'confirm'), (e) => e.status === 403);
    const conf = await chef.answerPayment(pending.id, 'confirm');
    assert.ok(conf.messages[0].includes('Réception confirmée'), conf.messages[0]);
    assert.equal((await chef.payments()).recus[0].statut, 'confirme');
    assert.equal((await own.project(p.id)).project.steps[0].status, 'paye');
    const paidNote = (await own.notifications()).notifications.map((n) => n.title);
    assert.ok(paidNote.includes('Payment confirmed'), paidNote.join());
    const ownNotes = (await own.notifications()).notifications.map((n) => n.title);
    assert.ok(ownNotes.includes('Stage to approve'), ownNotes.join());
    // Suppression du compte depuis l'application (exigée par l'App Store)
    await assert.rejects(chef.deleteAccount('faux'), (e) => e.status === 401);
    const gone = await chef.deleteAccount('Bingerville-2026');
    assert.equal(gone.ok, true);
    assert.ok(gone.message.includes('supprimé'), gone.message);
    await assert.rejects(chef.projects(), (e) => e.status === 401);
    await assert.rejects(chef.login('k@x.ci', 'Bingerville-2026'), (e) => e.status === 401);
    const after = (await own.project(p.id)).project;
    assert.equal(after.steps[0].status, 'paye');          // l'historique du propriétaire reste intact
    await own.logout();
    await assert.rejects(own.projects(), (e) => e.status === 401);
  } finally {
    server.kill();
    rmSync(inst, { recursive: true, force: true });
  }
});
