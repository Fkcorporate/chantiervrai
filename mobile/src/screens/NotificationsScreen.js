import React, { useCallback, useEffect, useState } from 'react';
import { Screen, Card, T, Row, Button, Banner } from '../components/ui';
import { api } from '../services/session';
import { t, getLang } from '../core/i18n';
import { dateTime } from '../core/format';
import { C } from '../theme';

export default function NotificationsScreen({ back, go }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { setItems((await api.notifications()).notifications); } catch (e) { setError(e.message); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function readAll() { await api.markRead().catch(() => {}); load(); }

  return (
    <Screen title={t('Notifications')} onBack={back} refreshing={loading} onRefresh={load}>
      <Banner text={error} tone="error" />
      {items.some((n) => !n.read) ? <Button kind="ghost" small title={t('Tout marquer lu')} onPress={readAll} /> : null}
      {items.map((n) => (
        <Card key={n.id} style={!n.read ? { borderLeftWidth: 4, borderLeftColor: C.green } : null}
          onPress={n.link && n.link.startsWith('/paiements') ? () => go('payments')
            : n.project_id ? () => go('project', { id: n.project_id }) : undefined}>
          <Row><T bold style={{ flex: 1 }}>{n.title}</T></Row>
          <T>{n.body}</T>
          <T muted>{dateTime(n.created_at, getLang())}</T>
        </Card>
      ))}
      {!items.length && !loading ? <Card><T muted>{t('Aucune notification.')}</T></Card> : null}
    </Screen>
  );
}
