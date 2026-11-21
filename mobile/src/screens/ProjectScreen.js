import React, { useCallback, useEffect, useState } from 'react';
import { Image, Linking, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Screen, Card, T, Bar, Pill, Row, Button, Field, Banner, SlideToConfirm } from '../components/ui';
import FunctionsPanel from '../components/FunctionsPanel';
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
  const [showAllAlerts, setShowAllAlerts] = useState(false);
  const [fnOpen, setFnOpen] = useState(false);
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
  const cover = (p.proofs || []).find((x) => x.ok && (x.kind !== 'video' || x.thumb_url));
  const missingChecks = cur ? (p.checks || []).filter((c) => c.required && c.status !== 'conforme' && c.step_id === cur.id) : [];

  return (
    <Screen title={t('Chantier')} onBack={back} refreshing={loading} onRefresh={load}
      right={(p.functions || []).length ? (
        <Pressable onPress={() => setFnOpen(true)} accessibilityRole="button" accessibilityLabel={t('Toutes les fonctions')} hitSlop={6}
          style={({ pressed }) => [st.fnBtn, pressed && { opacity: 0.7 }]}>
          <Ionicons name="grid-outline" size={20} color={C.text} />
        </Pressable>
      ) : null}>
      <View style={st.hero}>
        {cover ? (
          <Image source={{ uri: api.url(cover.thumb_url || cover.url), headers: { Authorization: `Bearer ${current().token}` } }}
            style={StyleSheet.absoluteFill} resizeMode="cover" accessibilityLabel={t('Dernière photo vérifiée du chantier')} />
        ) : null}
        {cover ? <View style={st.heroChip}><T bold style={{ fontSize: 12 }}>✓ {t('Photo vérifiée')} · {dateTime(cover.created_at, getLang())}</T></View> : null}
        <View style={st.heroBody}>
          {cur ? <T style={st.heroKicker}>{t('Étape %(i)s sur %(n)s', { i: p.steps.findIndex((x) => x.id === cur.id) + 1, n: p.steps.length })}</T> : null}
          <T style={st.heroTitle} numberOfLines={2}>{p.name}</T>
          {cur ? <T style={st.heroStep}>{cur.name} · {cur.status_label}</T> : <T style={st.heroStep}>{t('Toutes les étapes sont terminées.')}</T>}
          {p.address ? <T style={st.heroAddr} numberOfLines={1}>{p.address}</T> : null}
        </View>
      </View>
      <Banner text={error} tone="error" />
      <Banner text={info} />
      {pending ? <Banner text={t('%(n)s preuve(s) en attente de réseau', { n: pending })} /> : null}
      {['owner', 'chef', 'intervenant'].includes(p.role) ? (
        <Pressable onPress={() => go('conversation', { id: p.id })} accessibilityRole="button"
          accessibilityLabel={p.chat_unread ? `${t('Conversation du chantier')} (${p.chat_unread})` : t('Conversation du chantier')}
          style={({ pressed }) => [st.chat, pressed && { transform: [{ scale: 0.985 }] }]}>
          <View style={st.chatIco}>
            <Ionicons name="chatbubble-ellipses" size={20} color="#0B2219" />
            {p.chat_unread ? <View style={st.chatBadge}><T style={st.chatBadgeText}>{p.chat_unread > 9 ? '9+' : p.chat_unread}</T></View> : null}
          </View>
          <View style={{ flex: 1 }}>
            <T bold>{p.role === 'chef' ? t('Conversation') : t('Conversation du chantier')}</T>
            <T muted style={{ fontSize: 13 }}>{p.chat_unread ? (p.chat_unread === 1 ? t('1 nouveau message') : t('%(n)s nouveaux messages', { n: p.chat_unread }))
              : p.role === 'chef' ? t('Parler au propriétaire') : t('Écrire, envoyer une note vocale ou une photo')}</T>
          </View>
          <Ionicons name="chevron-forward" size={20} color={C.muted} />
        </Pressable>
      ) : null}

      {p.role === 'chef' && cur ? (
        cur.status === 'en_cours' ? (
          <Card>
            <View style={st.shootRow}>
              <Pressable onPress={() => go('capture', { project: p, mode: 'picture' })} accessibilityRole="button"
                style={({ pressed }) => [st.shoot, st.shootMain, pressed && st.shootPressed]}>
                <Ionicons name="camera" size={30} color="#FFFFFF" />
                <T style={st.shootMainText}>{t('Prendre une photo')}</T>
              </Pressable>
              <Pressable onPress={() => go('capture', { project: p, mode: 'video' })} accessibilityRole="button"
                style={({ pressed }) => [st.shoot, st.shootAlt, pressed && st.shootPressed]}>
                <Ionicons name="videocam" size={26} color={C.forest} />
                <T style={st.shootAltText}>{t('Filmer (90 s max)')}</T>
              </Pressable>
            </View>
            <T muted style={{ textAlign: 'center' }}>{t('%(n)s preuve(s) vérifiée(s) pour cette étape', { n: verifiedForCurrent })}</T>
            <Button kind="ghost" title={t('Déclarer l\'étape terminée')} disabled={!verifiedForCurrent}
              loading={busy === 'declarer'} onPress={() => act('declarer', cur.id)} />
            {!verifiedForCurrent ? <T muted>{t('Envoyez au moins une preuve vérifiée d\'abord.')}</T> : null}
          </Card>
        ) : <Card><T muted>{t('En attente de validation par le propriétaire.')}</T></Card>
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
        <View style={st.decide}>
          <T style={st.decideKicker}>{t('Votre décision')}</T>
          <T style={st.decideTitle}>{t('%(name)s terminée', { name: cur.name })}</T>
          <T style={st.decideAmount}>{fcfa(cur.amount)} <T style={st.decideUnit}>FCFA</T></T>
          <View style={st.decideChecks}>
            <View style={st.decideCheck}><Ionicons name="checkmark-circle" size={18} color="#9FE0BC" /><T style={st.decideCheckText}>{t('%(n)s photo(s) vérifiée(s) sur le terrain', { n: verifiedForCurrent })}</T></View>
            {missingChecks.length ? (
              <View style={st.decideCheck}><Ionicons name="alert-circle" size={18} color="#F6B48A" /><T style={st.decideCheckText}>{t('%(n)s contrôle(s) obligatoire(s) à faire', { n: missingChecks.length })}</T></View>
            ) : (
              <View style={st.decideCheck}><Ionicons name="checkmark-circle" size={18} color="#9FE0BC" /><T style={st.decideCheckText}>{t('Contrôles techniques conformes')}</T></View>
            )}
          </View>
          <SlideToConfirm label={`${p.pay_mode === 'suivi' ? t('Glisser pour valider') : t('Glisser pour payer')} ${fcfa(cur.amount)}`}
            loading={busy === 'valider'} disabled={!!busy}
            onConfirm={() => { if (!p.sequestre && p.pay_mode !== 'suivi') { setField(''); setDialog({ action: 'valider', stepId: cur.id }); } else act('valider', cur.id, {}); }} />
          <Pressable onPress={() => { setField(''); setDialog({ action: 'refuser', stepId: cur.id }); }} accessibilityRole="button"
            style={{ alignSelf: 'center', minHeight: 44, justifyContent: 'center' }}>
            <T style={{ color: C.mint, fontWeight: '600' }}>{t('Refuser avec un motif')}</T>
          </Pressable>
        </View>
      ) : null}

      <View style={st.stats}>
        <View style={st.stat}><T style={st.statLabel}>{t('Avancement vérifié')}</T><T style={st.statValue}>{p.verified_pct} %</T></View>
        {p.role === 'owner' ? (
          <View style={st.stat}><T style={st.statLabel}>{p.sequestre ? t('Bloqué sur le séquestre') : t('Reste à payer')}</T><T style={st.statValue} numberOfLines={1} adjustsFontSizeToFit>{fcfa(p.locked)}</T></View>
        ) : (
          <View style={st.stat}><T style={st.statLabel}>{t('Déclaré par le chantier')}</T><T style={st.statValue}>{p.declared_pct} %</T></View>
        )}
      </View>
      <Card>
        <Row><T bold>{t('Avancement vérifié')}</T><T bold style={{ color: C.green }}>{p.verified_pct} %</T></Row>
        <Bar pct={p.verified_pct} />
        <Row><T muted>{t('Déclaré par le chantier')}</T><T bold style={{ color: '#9A3F12' }}>{p.declared_pct} %</T></Row>
        <Bar pct={p.declared_pct} color="#D98B5F" />
        {p.role === 'owner' ? <T muted>{t('Déjà versé')} : {fcfa(p.paid)}</T> : null}
        {p.prediction ? <T muted>{t('Fin estimée le %(d)s', { d: date(p.prediction.predicted_end, getLang()) })}</T> : null}
      </Card>

      {(p.alerts || []).length ? (
        <Card style={{ gap: 0, paddingVertical: 8 }}>
          <View style={st.alertHead}>
            <View style={st.alertCount}><T style={st.alertCountText}>{p.alerts.length}</T></View>
            <T bold style={{ fontSize: 16 }}>{t('%(n)s point(s) à voir', { n: p.alerts.length })}</T>
          </View>
          {(showAllAlerts ? p.alerts : p.alerts.slice(0, 2)).map((a, i) => (
            <View key={i} style={st.alertRow}><T bold>{a.title}</T>{a.detail ? <T muted>{a.detail}</T> : null}</View>
          ))}
          {p.alerts.length > 2 ? (
            <Pressable onPress={() => setShowAllAlerts((v) => !v)} accessibilityRole="button" style={st.alertMore}>
              <T style={{ color: C.green, fontWeight: '600' }}>{showAllAlerts ? t('Réduire') : t('Voir les %(n)s autres', { n: p.alerts.length - 2 })}</T>
            </Pressable>
          ) : null}
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
      <Card style={{ gap: 0, paddingVertical: 6 }}>
        {p.steps.map((stp, i) => {
          const done = stp.status === 'paye' || stp.status === 'versement';
          const now = stp.status === 'en_cours' || stp.status === 'declare';
          return (
            <View key={stp.id} style={[s.stepRow, i > 0 && s.stepSep]}>
              <View style={[s.stepDot, done && s.stepDotDone, now && s.stepDotNow, stp.status === 'declare' && s.stepDotDecl]}>
                {done ? <Ionicons name="checkmark" size={15} color="#fff" /> : <T style={[s.stepNum, now && { color: '#fff' }]}>{i + 1}</T>}
              </View>
              <View style={{ flex: 1, gap: 2 }}>
                <T bold={now} numberOfLines={2}>{stp.name}</T>
                <T muted>{fcfa(stp.amount)}{stp.pay_ref ? ` · ${stp.pay_ref}` : ''}</T>
              </View>
              <Pill text={stp.status_label} tone={stp.status === 'declare' ? 'warn' : stp.status === 'attente' ? 'grey' : undefined} />
            </View>
          );
        })}
      </Card>

      {(p.functions || []).length ? (
        <Pressable onPress={() => setFnOpen(true)} accessibilityRole="button" style={({ pressed }) => [st.fnCta, pressed && { opacity: 0.85 }]}>
          <View style={st.fnCtaIco}><Ionicons name="grid-outline" size={22} color="#fff" /></View>
          <View style={{ flex: 1, gap: 2 }}>
            <T bold style={{ fontSize: 15 }}>{t('Toutes les fonctions du chantier')}</T>
            <T muted style={{ fontSize: 13 }} numberOfLines={2}>{(p.functions || []).map((g) => g.title).join(' · ')}</T>
          </View>
          <Ionicons name="chevron-forward" size={18} color="#9AA09C" />
        </Pressable>
      ) : <Button kind="ghost" title={t('Ouvrir sur le site web')} onPress={openWeb} />}
      <FunctionsPanel visible={fnOpen} onClose={() => setFnOpen(false)} title={p.name} groups={p.functions}
        onOpen={(it) => {
          if (it.path.endsWith('#proof-form')) { go('capture', { project: p, mode: 'picture' }); return; }
          const [path, hash] = it.path.split('#');
          Linking.openURL(api.url(`${path}${path.includes('?') ? '&' : '?'}lang=${getLang()}${hash ? `#${hash}` : ''}`));
        }} />

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
  stepRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  stepSep: { borderTopWidth: 1, borderTopColor: '#F0EDE6' },
  stepDot: { width: 28, height: 28, borderRadius: 14, borderWidth: 2, borderColor: C.border, alignItems: 'center', justifyContent: 'center' },
  stepDotDone: { backgroundColor: C.accentFill, borderColor: C.accentFill },
  stepDotNow: { backgroundColor: C.forest, borderColor: C.forest },
  stepDotDecl: { backgroundColor: C.orange, borderColor: C.orange },
  stepNum: { fontSize: 13, fontWeight: '700', color: C.muted },
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,.45)', justifyContent: 'center', padding: 18 },
  full: { width: '100%', aspectRatio: 0.75, borderRadius: 12, backgroundColor: '#D9D4CA' },
});

const st = StyleSheet.create({
  hero: { height: 280, borderRadius: 28, overflow: 'hidden', backgroundColor: C.forest },
  heroChip: { position: 'absolute', left: 12, top: 12, backgroundColor: 'rgba(255,255,255,0.94)', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  heroBody: { position: 'absolute', left: 0, right: 0, bottom: 0, padding: 18, paddingTop: 28, gap: 3, backgroundColor: 'rgba(12,42,30,0.80)' },
  heroKicker: { color: C.mint, fontSize: 12, fontWeight: '700' },
  heroTitle: { color: '#fff', fontSize: 28, fontWeight: '600', letterSpacing: -1, lineHeight: 32 },
  heroStep: { color: '#fff', fontSize: 15, fontWeight: '600' },
  heroAddr: { color: '#CFE3D8', fontSize: 13 },
  stats: { flexDirection: 'row', gap: 10 },
  stat: { flex: 1, backgroundColor: C.card, borderRadius: 18, padding: 14, gap: 2 },
  statLabel: { fontSize: 12, color: C.muted },
  statValue: { fontSize: 22, fontWeight: '300', letterSpacing: -0.8, color: C.text },
  shootRow: { flexDirection: 'row', gap: 10 },
  shoot: { borderRadius: 20, alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 18, paddingHorizontal: 8 },
  shootMain: { flex: 1.6, backgroundColor: C.forest, minHeight: 112 },
  shootAlt: { flex: 1, backgroundColor: C.greenSoft, minHeight: 112 },
  shootPressed: { transform: [{ scale: 0.97 }], opacity: 0.92 },
  shootMainText: { color: '#FFFFFF', fontWeight: '600', fontSize: 16, textAlign: 'center' },
  shootAltText: { color: C.forest, fontWeight: '700', fontSize: 13, textAlign: 'center' },
  fnBtn: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: C.card },
  fnCta: { flexDirection: 'row', alignItems: 'center', gap: 14, backgroundColor: C.card, borderRadius: 20, padding: 14, minHeight: 72 },
  fnCtaIco: { width: 44, height: 44, borderRadius: 14, backgroundColor: C.forest, alignItems: 'center', justifyContent: 'center' },
  alertHead: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8 },
  alertCount: { minWidth: 24, height: 24, borderRadius: 12, paddingHorizontal: 7, backgroundColor: '#FBE3DA', alignItems: 'center', justifyContent: 'center' },
  alertCountText: { color: '#A63A12', fontSize: 13, fontWeight: '700' },
  alertRow: { paddingVertical: 11, borderTopWidth: 1, borderTopColor: '#F2EFE8', gap: 2 },
  alertMore: { minHeight: 44, justifyContent: 'center', borderTopWidth: 1, borderTopColor: '#F2EFE8' },
  decide: { backgroundColor: C.forest, borderRadius: 26, padding: 20, gap: 10 },
  decideKicker: { color: C.gold, fontWeight: '700', fontSize: 12, letterSpacing: 0.8, textTransform: 'uppercase' },
  decideTitle: { color: '#fff', fontSize: 20, fontWeight: '600', letterSpacing: -0.4 },
  decideAmount: { fontSize: 38, fontWeight: '300', letterSpacing: -1.6, color: '#fff' },
  decideUnit: { fontSize: 14, fontWeight: '500', color: C.mint, letterSpacing: 0 },
  decideChecks: { gap: 8, marginBottom: 6 },
  decideCheck: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  decideCheckText: { color: '#DCE8E1', fontSize: 14, flex: 1 },
  chat: { flexDirection: 'row', alignItems: 'center', gap: 14, padding: 14, borderRadius: 22, backgroundColor: C.card, borderWidth: 1, borderColor: C.line },
  chatIco: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#D6B57D', alignItems: 'center', justifyContent: 'center' },
  chatBadge: { position: 'absolute', top: -4, right: -4, minWidth: 20, height: 20, borderRadius: 10, paddingHorizontal: 5, backgroundColor: '#D9622B',
    alignItems: 'center', justifyContent: 'center', borderWidth: 2, borderColor: C.card },
  chatBadgeText: { color: '#fff', fontSize: 11, fontWeight: '800' },
});
