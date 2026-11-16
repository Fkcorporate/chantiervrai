import React, { useCallback, useEffect, useState } from 'react';
import { Image, Linking, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { Screen, Card, T, Bar, Pill, Row, Button, Field, Banner } from '../components/ui';
import { api, current, queue } from '../services/session';
import { t, getLang } from '../core/i18n';
import { fcfa, date, dateTime } from '../core/format';
import { C } from '../theme';

export default function ProjectScreen({ go, back, params }) {
  const [p, setP] = useState(null);
  const [error, setError] = useState('');
  const [info, setInfo] = useState(params.message || '');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState('');
  const [dialog, setDialog] = useState(null);       // { action, stepId }
  const [field, setField] = useState('');
  const [viewer, setViewer] = useState(null);
  const [pending, setPending] = useState(0);
  const { token } = current();

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const r = await api.project(params.id);
      setP(r.project);
    } catch (e) {
      setError(e.name === 'NetworkError' ? t('Pas de connexion au serveur.') : e.message);
    } finally {
      setPending((await queue.list()).filter((i) => i.projectId === params.id).length);
      setLoading(false);
    }
  }, [params.id]);
  useEffect(() => { load(); }, [load]);

  async function act(action, stepId, fields) {
    setBusy(action); setError(''); setInfo('');
    try {
      const r = await api.stepAction(p.id, stepId, action, fields);
      setInfo((r.messages || []).join(' '));
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(''); setDialog(null); setField('');
    }
  }

  if (!p) {
    return (
      <Screen title="" onBack={back} refreshing={loading} onRefresh={load}>
        <Banner text={error} tone="error" />
      </Screen>
    );
  }

  const cur = p.current;
  const verifiedForCurrent = cur ? p.proofs.filter((x) => x.ok && x.step_id === cur.id).length : 0;
  const img = (url) => ({ uri: api.url(url), headers: { Authorization: `Bearer ${token}` } });
  const openWeb = () => Linking.openURL(api.url(`/chantiers/${p.id}?lang=${getLang()}`));
  const accepted = (p.inspections || []).filter((i) => i.status === 'acceptee');

  return (
    <Screen title={p.name} onBack={back} refreshing={loading} onRefresh={load}>
      <T muted>{p.address}</T>
      <Banner text={error} tone="error" />
      <Banner text={info} />
      {pending ? <Banner text={t('%(n)s preuve(s) en attente de réseau', { n: pending })} /> : null}

      <Card>
        <Row><T bold>{t('Avancement vérifié')}</T><T bold style={{ color: C.green }}>{p.verified_pct} %</T></Row>
        <Bar pct={p.verified_pct} />
        <Row><T muted>{t('Déclaré par le chantier')}</T><T bold style={{ color: '#9A3F12' }}>{p.declared_pct} %</T></Row>
        <Bar pct={p.declared_pct} color="#D98B5F" />
        {p.prediction ? <T muted>{t('Fin estimée le %(d)s', { d: date(p.prediction.predicted_end, getLang()) })}</T> : null}
      </Card>

      {p.role === 'owner' ? (
        <Row style={{ alignItems: 'stretch' }}>
          <Card tone="green" style={{ flex: 1 }}>
            <T white muted style={{ color: '#D4E6DB' }}>{p.sequestre ? t('Bloqué sur le séquestre') : t('Reste à payer')}</T>
            <T white big>{fcfa(p.locked)}</T>
          </Card>
          <Card style={{ flex: 1 }}>
            <T muted>{t('Déjà versé')}</T>
            <T big>{fcfa(p.paid)}</T>
          </Card>
        </Row>
      ) : null}

      {(p.alerts || []).map((a, i) => (
        <Card key={i} tone="alert"><T bold>{a.title}</T>{a.detail ? <T muted>{a.detail}</T> : null}</Card>
      ))}

      {cur ? (
        <Card tone="green">
          <T white muted style={{ color: '#D4E6DB' }}>{t('Étape en cours')}</T>
          <T white big>{cur.name}</T>
          <T white style={{ color: '#D4E6DB' }}>{t('Paiement à la validation : %(n)s', { n: fcfa(cur.amount) })}</T>
          <Pill text={cur.status_label} tone={cur.status === 'declare' ? 'warn' : undefined} />
        </Card>
      ) : <Card><T>{t('Toutes les étapes sont terminées.')}</T></Card>}

      {p.role === 'chef' && cur ? (
        <Card>
          {cur.status === 'en_cours' ? (
            <>
              <Button kind="orange" title={t('Prendre une photo')}
                onPress={() => go('capture', { project: p, mode: 'picture' })} />
              <Button kind="orange" title={t('Filmer (90 s max)')}
                onPress={() => go('capture', { project: p, mode: 'video' })} />
              <Button kind="ghost" title={t('Déclarer l\'étape terminée')} disabled={!verifiedForCurrent}
                loading={busy === 'declarer'} onPress={() => act('declarer', cur.id)} />
              {!verifiedForCurrent ? <T muted>{t('Envoyez au moins une preuve vérifiée d\'abord.')}</T> : null}
            </>
          ) : <T muted>{t('En attente de validation par le propriétaire.')}</T>}
        </Card>
      ) : null}

      {p.role === 'inspecteur' && accepted.length ? (
        <Card>
          <T bold>{t('Photos d\'inspection')}</T>
          <Button kind="orange" title={t('Prendre une photo')}
            onPress={() => go('capture', { project: p, mode: 'picture', inspectionId: accepted[0].id })} />
          <T muted>{t('Rédigez le rapport sur le site web.')}</T>
        </Card>
      ) : null}

      {p.role === 'owner' && cur && cur.status === 'declare' ? (
        <Card tone="alert">
          <T bold>{cur.name}</T>
          <Button title={`${t('Valider et payer')} ${fcfa(cur.amount)}`} loading={busy === 'valider'}
            onPress={() => { setField(''); setDialog({ action: 'valider', stepId: cur.id }); }} />
          <Button kind="ghost" title={t('Refuser')} loading={busy === 'refuser'}
            onPress={() => { setField(''); setDialog({ action: 'refuser', stepId: cur.id }); }} />
        </Card>
      ) : null}

      {p.trust && p.trust.score != null ? (
        <Card onPress={() => Linking.openURL(api.url(`/chantiers/${p.id}/confiance?lang=${getLang()}`))}>
          <Row><T bold style={{ flex: 1 }}>{t('Indice de confiance')}</T>
            <T bold style={{ fontSize: 22, color: p.trust.level === 'good' ? '#0E5A3A' : p.trust.level === 'medium' ? '#B06A00' : '#B3261E' }}>{p.trust.score}/100</T></Row>
          <T muted>{p.trust.label}</T>
          {p.trust.criteria.filter((c) => c.score != null && c.score < 60).map((c) => (
            <T key={c.key} muted>• {c.title} : {c.why}</T>
          ))}
        </Card>
      ) : null}

      {(p.checks || []).filter((c) => c.required && c.status !== 'conforme' && p.current && c.step_id === p.current.id).length ? (
        <Card tone="alert">
          <T bold>{t('Contrôles obligatoires avant paiement')}</T>
          {p.checks.filter((c) => c.required && c.status !== 'conforme' && c.step_id === p.current.id).map((c) => (
            <T key={c.id} muted>• {c.name} ({c.status_label})</T>
          ))}
        </Card>
      ) : null}

      {p.orders && (p.orders.length || p.role === 'chef') ? (
        <>
          <T bold style={{ fontSize: 18 }}>{t('Commandes de matériaux')}</T>
          {p.orders.map((o) => (
            <Card key={o.id} onPress={() => go('order', { order: o, role: p.role })}
              tone={(o.status === 'livree' && p.role === 'chef') || (o.status === 'proposee' && p.role === 'owner') ? 'alert' : undefined}>
              <Row><T bold style={{ flex: 1 }}>{o.supplier}</T><Pill text={o.status_label} tone={['livree', 'proposee', 'litige'].includes(o.status) ? 'warn' : undefined} /></Row>
              <T muted>{o.ref} · {fcfa(o.received_total != null ? o.received_total : o.total)}</T>
            </Card>
          ))}
          {!p.orders.length ? <T muted>{t('Commandez sur le site web : le fournisseur est payé seulement pour ce qui est livré et compté.')}</T> : null}
        </>
      ) : null}

      <T bold style={{ fontSize: 18 }}>{t('Preuves')}</T>
      <View style={s.grid}>
        {p.proofs.slice(0, 24).map((pr) => (
          <Pressable key={pr.id} onPress={() => setViewer(pr)} style={[s.thumbBox, !pr.ok && s.thumbBad]}
            accessibilityRole="imagebutton" accessibilityLabel={`${pr.step_name} ${pr.ok ? t('Vérifiée') : t('Refusée')}`}>
            {pr.kind === 'video' && !pr.thumb_url ? <View style={[s.thumb, s.video]}><T white>▶ {t('Vidéo')}</T></View>
              : <Image source={img(pr.kind === 'video' ? pr.thumb_url : pr.url)} style={s.thumb} />}
            <View style={[s.badge, !pr.ok && s.badgeBad]}><T style={s.badgeText}>{pr.ok ? '✓' : '✕'}</T></View>
          </Pressable>
        ))}
      </View>
      {!p.proofs.length ? <T muted>{t('Aucune preuve.')}</T> : null}

      <T bold style={{ fontSize: 18 }}>{t('Étapes')}</T>
      {p.steps.map((st, i) => (
        <Card key={st.id} style={st.status === 'en_cours' ? s.cur : st.status === 'declare' ? s.decl : null}>
          <Row><T bold style={{ flex: 1 }}>{i + 1}. {st.name}</T><Pill text={st.status_label} tone={st.status === 'declare' ? 'warn' : st.status === 'attente' ? 'grey' : undefined} /></Row>
          <T muted>{fcfa(st.amount)}{st.pay_ref ? ` · ${st.pay_ref}` : ''}</T>
        </Card>
      ))}

      <Button kind="ghost" title={t('Ouvrir sur le site web')} onPress={openWeb} />
      <T muted>{t('Satellite, documents, matériaux et inspections sont sur le site web.')}</T>

      <Modal visible={!!dialog} transparent animationType="fade" onRequestClose={() => setDialog(null)}>
        <View style={s.overlay}>
          <Card style={{ width: '100%' }}>
            <T bold>{dialog && dialog.action === 'valider' ? (p.pay_mode === 'suivi' ? t('Valider et émettre le bon à payer') : t('Valider et payer')) : t('Refuser')}</T>
            {dialog && dialog.action === 'valider' && p.pay_mode === 'suivi' ? (
              <T muted>{t('Vous payez ensuite le bénéficiaire, puis vous déclarez le paiement sur le site web.')}</T>
            ) : null}
            {dialog && (dialog.action === 'refuser' || (!p.sequestre && p.pay_mode !== 'suivi')) ? (
              <Field label={dialog.action === 'refuser' ? t('Motif du refus') : t('Référence du paiement (facultatif)')}
                value={field} onChangeText={setField} autoFocus />
            ) : null}
            <Button title={t('Confirmer')} loading={!!busy}
              onPress={() => act(dialog.action, dialog.stepId, dialog.action === 'refuser' ? { motif: field } : { pay_ref: field })} />
            <Button kind="ghost" title={t('Annuler')} onPress={() => setDialog(null)} />
          </Card>
        </View>
      </Modal>

      <Modal visible={!!viewer} animationType="slide" onRequestClose={() => setViewer(null)}>
        {viewer ? (
          <ScrollView contentContainerStyle={{ padding: 18, gap: 12, paddingTop: 50, backgroundColor: C.bg, flexGrow: 1 }}>
            {viewer.kind === 'video'
              ? <Button kind="ghost" title={`▶ ${t('Vidéo')}`} onPress={() => Linking.openURL(api.url(`/chantiers/${p.id}?onglet=preuves`))} />
              : <Image source={img(viewer.url)} style={s.full} resizeMode="contain" />}
            <Row><T bold>{viewer.step_name}</T><Pill text={viewer.ok ? t('Vérifiée') : t('Refusée')} tone={viewer.ok ? undefined : 'warn'} /></Row>
            {viewer.note ? <T>{viewer.note}</T> : null}
            {viewer.reasons.map((r, i) => <T key={i} style={{ color: '#9A3F12' }}>• {r}</T>)}
            {viewer.delayed_minutes ? <T muted>{t('Envoyée sans réseau')}</T> : null}
            {viewer.attestation === 'verifiee' ? <T muted>{t('Appareil certifié')}</T> : null}
            {viewer.ai_note ? <T muted>{viewer.ai_note}</T> : null}
            <T muted>{dateTime(viewer.created_at, getLang())} · {viewer.author}</T>
            <Button kind="ghost" title={t('Retour')} onPress={() => setViewer(null)} />
          </ScrollView>
        ) : null}
      </Modal>
    </Screen>
  );
}

const s = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  thumbBox: { width: '31.5%', aspectRatio: 1, borderRadius: 10, overflow: 'hidden', backgroundColor: '#D9D4CA' },
  thumbBad: { borderWidth: 2, borderColor: C.orange },
  thumb: { width: '100%', height: '100%' },
  video: { alignItems: 'center', justifyContent: 'center', backgroundColor: C.text },
  badge: { position: 'absolute', right: 6, bottom: 6, backgroundColor: C.green, borderRadius: 999, width: 22, height: 22, alignItems: 'center', justifyContent: 'center' },
  badgeBad: { backgroundColor: C.orange },
  badgeText: { color: '#fff', fontSize: 12, fontWeight: '700' },
  cur: { borderWidth: 2, borderColor: C.green },
  decl: { borderWidth: 2, borderColor: C.orange },
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,.45)', justifyContent: 'center', padding: 18 },
  full: { width: '100%', aspectRatio: 0.75, borderRadius: 12, backgroundColor: '#D9D4CA' },
});
