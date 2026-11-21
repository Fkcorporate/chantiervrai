// Logique de la conversation et de l'accueil, sans React Native : testée avec Node.

// 75 -> « 1:15 »
export function duration(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// Ajoute les éléments reçus au fil, sans doublon (même type et même identifiant), puis trie par heure.
// Un élément déjà présent est remplacé : son statut a pu changer (demande payée, travaux acceptés…).
export function mergeItems(list, incoming) {
  const key = (x) => `${x.type}:${x.id}`;
  const map = new Map(list.map((x) => [key(x), x]));
  for (const x of incoming || []) map.set(key(x), x);
  return [...map.values()].sort((a, b) => (a.t || '').localeCompare(b.t || ''));
}

// Lignes à afficher : séparateur de jour quand le jour change, repère « nouveaux messages » une seule fois.
export function rows(items, lastRead) {
  const out = [];
  let day = null, unread = false;
  for (const it of items) {
    if (it.day !== day) { day = it.day; out.push({ row: 'day', key: `d-${it.t}`, label: it.day }); }
    if (!unread && lastRead && !it.mine && (it.t || '') > lastRead) { unread = true; out.push({ row: 'unread', key: 'unread' }); }
    out.push({ row: 'item', key: `${it.type}-${it.id}`, item: it });
  }
  return out;
}

// Chemin du site -> écran de l'application quand il existe, sinon page web.
export function route(path) {
  if (!path) return null;
  let m = path.match(/^\/chantiers\/(\d+)\/conversation\b/);
  if (m) return { screen: 'conversation', params: { id: Number(m[1]) } };
  m = path.match(/^\/chantiers\/(\d+)\/?(\?.*)?(#.*)?$/);
  if (m) return { screen: 'project', params: { id: Number(m[1]) } };
  m = path.match(/^\/commandes\/(\d+)\/?$/);
  if (m) return { screen: 'order', params: { orderId: Number(m[1]) } };
  return { web: path };
}

// Glisser sur le viseur : prochain sujet de photo (borné aux extrémités)
export function nextIndex(i, n, dx) {
  if (Math.abs(dx) < 50 || !n) return i;
  return Math.max(0, Math.min(n - 1, i + (dx < 0 ? 1 : -1)));
}
