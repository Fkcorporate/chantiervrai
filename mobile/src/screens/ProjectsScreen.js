import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, Text } from 'react-native';
import { Screen, Card, T, Bar, Pill, Row, Button, Field, Banner } from '../components/ui';
import { api, current, queue } from '../services/session';
import { t } from '../core/i18n';
import { C } from '../theme';
import { fcfa } from '../core/format';

export default function ProjectsScreen({ go }) {
  const [projects, setProjects] = useState([]);
  const [orders, setOrders] = useState([]);
  const [unread, setUnread] = useState(0);
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
        setOrders(o.orders); setUnread(n.unread);
      } else {
        const [p, n] = await Promise.all([api.projects(), api.notifications()]);
        setProjects(p.projects); setUnread(n.unread);
      }
      if (user.role !== 'proprio') {
        api.me().then((m) => setToConfirm(m.user.paiements_a_confirmer || 0)).catch(() => {});
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

  const right = (
    <>
      <Pressable onPress={() => go('payments')} accessibilityRole="button" accessibilityLabel={t('Paiements')}>
        <Text style={{ color: C.green, fontWeight: '700' }}>{t('Paiements')}{toConfirm ? ` (${toConfirm})` : ''}</Text>
      </Pressable>
      <Pressable onPress={() => go('notifications')} accessibilityRole="button" accessibilityLabel={t('Notifications')}>
        <Text style={{ color: C.green, fontWeight: '700' }}>{t('Alertes')}{unread ? ` (${unread})` : ''}</Text>
      </Pressable>
      <Pressable onPress={() => go('settings')} accessibilityRole="button" accessibilityLabel={t('Réglages')}>
        <Text style={{ color: C.green, fontSize: 20 }}>⚙</Text>
      </Pressable>
    </>
  );

  return (
    <Screen title={user.role === 'fournisseur' ? t('Mes commandes') : t('Mes chantiers')} right={right} refreshing={loading} onRefresh={load}>
      <Banner text={error} tone="error" />
      {pending ? <Banner text={t('%(n)s preuve(s) en attente de réseau', { n: pending })} /> : null}
      {toConfirm ? (
        <Card tone="alert" onPress={() => go('payments')}>
          <T bold>{t('%(n)s paiement(s) à confirmer', { n: toConfirm })}</T>
          <T muted>{t('Vérifiez votre compte, puis confirmez la réception.')}</T>
        </Card>
      ) : null}
      {projects.map((p) => (
        <Card key={p.id} onPress={() => go('project', { id: p.id })}>
          <Row>
            <T bold style={{ flex: 1 }}>{p.name}</T>
            {p.to_validate ? <Pill text={t('À valider')} tone="warn" />
              : p.prediction && !p.prediction.done ? (p.prediction.delay > 7
                ? <Pill text={t('Retard prévu : %(n)s j', { n: p.prediction.delay })} tone={p.prediction.delay > 30 ? 'warn' : 'amber'} />
                : <Pill text={t('Dans les temps')} />) : null}
          </Row>
          <T muted>{p.address}{p.current ? ` · ${p.current.name}` : ''}</T>
          <Row><T muted>{t('Avancement vérifié')}</T><T bold>{p.verified_pct} %</T></Row>
          <Bar pct={p.verified_pct} />
        </Card>
      ))}
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
