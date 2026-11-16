import React, { useCallback, useEffect, useState } from 'react';
import { Screen, Card, T, Pill, Row, Button, Field, Banner, Band, PhotoCard } from '../components/ui';
import { api, current, queue, setCounts } from '../services/session';
import { t } from '../core/i18n';
import { fcfa } from '../core/format';

export default function ProjectsScreen({ go }) {
  const [projects, setProjects] = useState([]);
  const [summary, setSummary] = useState(null);
  const [orders, setOrders] = useState([]);
  const [toConfirm, setToConfirm] = useState(0);
  const [pending, setPending] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [code, setCode] = useState('');
  const user = current().user || {};

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      if (user.role === 'fournisseur') {
        const [o, n] = await Promise.all([api.orders(), api.notifications()]);
        setOrders(o.orders); setCounts({ unread: n.unread || 0 });
      } else {
        const [p, n] = await Promise.all([api.projects(), api.notifications()]);
        setProjects(p.projects); setSummary(p.summary || null); setCounts({ unread: n.unread || 0 });
      }
      if (user.role !== 'proprio') {
        api.me().then((m) => { setToConfirm(m.user.paiements_a_confirmer || 0); setCounts({ toConfirm: m.user.paiements_a_confirmer || 0 }); }).catch(() => {});
      }
    } catch (e) {
      setError(e.name === 'NetworkError' ? t('Pas de connexion au serveur.') : e.message);
    } finally {
      setPending((await queue.list()).length);
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function join() {
    try { await api.joinProject(code.trim().toUpperCase()); setCode(''); load(); } catch (e) { setError(e.message); }
  }

  return (
    <Screen large title={user.role === 'fournisseur' ? t('Mes commandes') : 'ChantierVrai'} refreshing={loading} onRefresh={load}>
      <Banner text={error} tone="error" />
      {pending ? <Banner text={t('%(n)s preuve(s) en attente de réseau', { n: pending })} /> : null}
      {toConfirm ? (
        <Card tone="alert" onPress={() => go('payments')}>
          <T bold>{t('%(n)s paiement(s) à confirmer', { n: toConfirm })}</T>
          <T muted>{t('Vérifiez votre compte, puis confirmez la réception.')}</T>
        </Card>
      ) : null}
      {user.role === 'proprio' && summary && projects.length ? (
        <Band kicker={projects.length > 1 ? t('Argent suivi sur vos %(n)s chantiers', { n: projects.length }) : t('Argent suivi sur votre chantier')}
          value={summary.paid_short} unit="FCFA" sub={`${t('sur un budget de')} ${summary.total_short} FCFA`}
          stats={[{ label: t('À valider'), value: t('%(n)s étape(s)', { n: summary.to_validate }),
            onPress: summary.to_validate ? () => go('project', { id: (projects.find((x) => x.to_validate) || projects[0]).id }) : undefined }]} />
      ) : null}
      {projects.length ? <T bold style={{ fontSize: 20, fontWeight: '800', marginTop: 4 }}>{user.role === 'proprio' ? t('Vos chantiers') : t('Mes chantiers')}</T> : null}
      {projects.map((p) => {
        const late = p.prediction && !p.prediction.done && p.prediction.delay > 7;
        const tags = p.to_validate ? [{ text: t('Étape à valider'), hot: true }]
          : late ? [{ text: `${t('Retard prévu')} ${p.prediction.delay} ${t('j')}`, hot: true }]
            : [{ text: p.prediction && p.prediction.done ? t('Terminé') : t('Dans les temps') }];
        if (p.current) tags.push({ text: p.current.name });
        return (
          <PhotoCard key={p.id} onPress={() => go('project', { id: p.id })} title={p.name} pct={p.verified_pct} tags={tags}
            uri={p.cover_url ? api.url(p.cover_url) : null} headers={{ Authorization: `Bearer ${current().token}` }}
            chip={p.cover_url ? `${t('Photo')} ${p.cover_ago} · ${t('vérifiée')}` : t('Pas encore de photo')} />
        );
      })}
      {orders.map((o) => (
        <Card key={o.id} onPress={() => go('order', { order: o, role: 'fournisseur' })}
          tone={['envoyee', 'acceptee'].includes(o.status) ? 'alert' : undefined}>
          <Row><T bold style={{ flex: 1 }}>{o.project_name}</T><Pill text={o.status_label} tone={['envoyee', 'acceptee'].includes(o.status) ? 'warn' : undefined} /></Row>
          <T muted>{o.address || ''}{o.delivery_date ? ` · ${o.delivery_date}` : ''}</T>
          <T bold>{fcfa(o.total)}</T>
        </Card>
      ))}
      {user.role === 'fournisseur' && !orders.length && !loading ? <Card><T muted>{t('Aucune commande pour l\'instant.')}</T></Card> : null}
      {user.role !== 'fournisseur' && !projects.length && !loading ? <Card><T muted>{t('Aucun chantier pour l\'instant.')}</T></Card> : null}
      {user.role === 'chef' ? (
        <Card>
          <T bold>{t('Rejoindre un chantier')}</T>
          <Field label={t('Code d\'invitation')} value={code} onChangeText={setCode} autoCapitalize="characters" />
          <Button title={t('Rejoindre')} onPress={join} disabled={code.length < 4} />
        </Card>
      ) : null}
    </Screen>
  );
}
