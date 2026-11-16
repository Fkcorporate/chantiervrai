// Commande de materiaux : le fournisseur accepte et photographie la livraison sur le terrain,
// le chef de chantier compte et confirme, le proprietaire approuve.
import React, { useState } from 'react';
import { Linking } from 'react-native';
import { Screen, Card, T, Pill, Row, Button, Field, Banner } from '../components/ui';
import { api } from '../services/session';
import { t, getLang } from '../core/i18n';
import { fcfa } from '../core/format';

export default function OrderScreen({ go, back, params }) {
  const role = params.role || 'fournisseur';
  const [o, setO] = useState(params.order);
  const [info, setInfo] = useState(params.message || '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [deliveryDate, setDeliveryDate] = useState('');
  const [problem, setProblem] = useState('');
  const [qty, setQty] = useState(() => Object.fromEntries(o.lines.map((l) => [l.id, String(l.qty)])));

  async function reload() {
    if (role === 'fournisseur') {
      const r = await api.orders();
      const fresh = r.orders.find((x) => x.id === o.id);
      if (fresh) setO(fresh);
    } else {
      const r = await api.project(o.project_id);
      const fresh = (r.project.orders || []).find((x) => x.id === o.id);
      if (fresh) setO(fresh);
    }
  }

  async function act(action, fields) {
    setBusy(action); setError(''); setInfo('');
    try {
      const r = await api.orderAction(o.id, action, fields);
      setInfo((r.messages || []).join(' '));
      await reload();
    } catch (e) {
      setError(e.name === 'NetworkError' ? t('Pas de connexion au serveur.') : e.message);
    } finally {
      setBusy('');
    }
  }

  const s = o.status;
  return (
    <Screen title={o.ref} onBack={back} refreshing={false} onRefresh={() => reload().catch(() => {})}>
      <Banner text={info} />
      <Banner text={error} tone="error" />
      <Card>
        <Row><T bold style={{ flex: 1 }}>{role === 'fournisseur' ? o.project_name : o.supplier}</T><Pill text={o.status_label} /></Row>
        <T muted>{o.address || ''}{o.step_name ? ` · ${o.step_name}` : ''}</T>
        {o.note ? <T>{o.note}</T> : null}
        {o.problem ? <T style={{ color: '#9A3F12' }}>{o.problem}</T> : null}
      </Card>
      <Card>
        {o.lines.map((l) => (
          <Row key={l.id}>
            <T style={{ flex: 1 }}>{l.name}</T>
            <T muted>{l.qty_received != null ? `${l.qty_received}/` : ''}{l.qty} {l.unit}</T>
          </Row>
        ))}
        <Row><T muted style={{ flex: 1 }}>{t('Total')}</T><T bold>{fcfa(o.received_total != null ? o.received_total : o.total)}</T></Row>
      </Card>

      {role === 'fournisseur' && s === 'envoyee' ? (
        <Card>
          <Field label={t('Date de livraison (AAAA-MM-JJ)')} value={deliveryDate} onChangeText={setDeliveryDate} />
          <Button title={t('Accepter la commande')} loading={busy === 'accepter'} onPress={() => act('accepter', { delivery_date: deliveryDate })} />
          <Button kind="ghost" title={t('Refuser')} loading={busy === 'refuser'} onPress={() => act('refuser')} />
        </Card>
      ) : null}
      {role === 'fournisseur' && ['acceptee', 'livree'].includes(s) ? (
        <Card>
          <T>{t('Photographiez les matériaux déchargés sur le chantier : la position GPS prouve la livraison.')}</T>
          {o.site ? <Button kind="ghost" title={t('Itinéraire')}
            onPress={() => Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${o.site.lat},${o.site.lng}`)} /> : null}
          <Button kind="orange" title={t('Photo de livraison')}
            onPress={() => go('capture', { project: { id: o.project_id, name: o.project_name }, mode: 'picture', order: o })} />
        </Card>
      ) : null}

      {role === 'owner' && s === 'proposee' ? (
        <Card tone="alert">
          <Button title={t('Approuver et envoyer')} loading={busy === 'approuver'} onPress={() => act('approuver')} />
          <Button kind="ghost" title={t('Refuser')} loading={busy === 'annuler'} onPress={() => act('annuler')} />
        </Card>
      ) : null}
      {['chef', 'owner'].includes(role) && ['livree', 'litige'].includes(s) ? (
        <Card tone="alert">
          <T bold>{t('Confirmer ce qui est arrivé')}</T>
          <T muted>{t('Le fournisseur est payé seulement pour ce que vous confirmez.')}</T>
          {o.lines.map((l) => (
            <Field key={l.id} label={`${l.name} (${l.unit})`} keyboardType="decimal-pad" value={qty[l.id]}
              onChangeText={(v) => setQty({ ...qty, [l.id]: v })} />
          ))}
          <Button title={t('Confirmer la réception')} loading={busy === 'receptionner'}
            onPress={() => act('receptionner', Object.fromEntries(Object.entries(qty).map(([k, v]) => [`qty_${k}`, v.replace(',', '.')])))} />
        </Card>
      ) : null}
      {['chef', 'owner'].includes(role) && ['acceptee', 'livree'].includes(s) ? (
        <Card>
          <Field label={t('Signaler un problème')} value={problem} onChangeText={setProblem} multiline />
          <Button kind="ghost" title={t('Signaler et suspendre le paiement')} disabled={problem.trim().length < 10}
            loading={busy === 'probleme'} onPress={() => act('probleme', { text: problem })} />
        </Card>
      ) : null}
      <Button kind="ghost" title={t('Ouvrir sur le site web')} onPress={() => Linking.openURL(api.url(`/commandes/${o.id}?lang=${getLang()}`))} />
    </Screen>
  );
}
