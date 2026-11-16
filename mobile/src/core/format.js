// Mise en forme des montants et des dates.
export function fcfa(n) {
  const v = Math.round(Number(n) || 0);
  return v.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' FCFA';
}

export function date(iso, lang = 'fr') {
  if (!iso) return '';
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(lang === 'en' ? 'en-GB' : 'fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function dateTime(iso, lang = 'fr') {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(lang === 'en' ? 'en-GB' : 'fr-FR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}
