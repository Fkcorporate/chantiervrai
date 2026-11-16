// File d'attente des preuves prises sans reseau. Logique pure : le stockage (AsyncStorage +
// fichiers) et l'envoi sont fournis par l'application, ce qui permet de la tester avec Node.

export const MAX_AGE_MS = 72 * 3600 * 1000;   // meme limite que le serveur

export function createQueue({ load, save, removeFile, send, now = () => Date.now() }) {
  let flushing = null;

  async function list() {
    return (await load()) || [];
  }

  async function add(item) {
    const items = await list();
    const entry = { ...item, id: `${now()}-${Math.random().toString(36).slice(2, 8)}`, queuedAt: now(), attempts: 0 };
    items.push(entry);
    await save(items);
    return entry;
  }

  async function remove(id) {
    const items = await list();
    const item = items.find((i) => i.id === id);
    await save(items.filter((i) => i.id !== id));
    if (item && item.fileUri) await removeFile(item.fileUri);
  }

  // Envoie tout ce qui attend. Retourne { sent, rejected, kept, expired, results }.
  async function flush() {
    if (flushing) return flushing;
    flushing = (async () => {
      const out = { sent: 0, rejected: 0, kept: 0, expired: 0, results: [] };
      for (const item of await list()) {
        if (now() - item.capturedAt > MAX_AGE_MS) {
          await remove(item.id);
          out.expired += 1;
          continue;
        }
        try {
          const res = await send(item);
          await remove(item.id);
          out.results.push({ item, res });
          if (res && res.ok) out.sent += 1; else out.rejected += 1;
        } catch (e) {
          if (e && e.name === 'NetworkError') {
            out.kept += 1;                       // toujours pas de reseau : on reessaiera
            break;
          }
          // refus definitif du serveur (session expiree, chantier inaccessible) : on retire
          if (e && e.status && e.status >= 400 && e.status < 500 && e.status !== 408 && e.status !== 429) {
            await remove(item.id);
            out.rejected += 1;
            out.results.push({ item, error: e.message });
          } else {
            out.kept += 1;
            const items = await list();
            const it = items.find((i) => i.id === item.id);
            if (it) { it.attempts += 1; await save(items); }
          }
        }
      }
      return out;
    })();
    try {
      return await flushing;
    } finally {
      flushing = null;
    }
  }

  return { list, add, remove, flush };
}
