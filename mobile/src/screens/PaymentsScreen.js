// Paiements suivis : ChantierVrai ne touche pas l'argent.
// Le beneficiaire (chef, fournisseur, inspecteur) confirme ou conteste ; le payeur declare ce qu'il a paye.
import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { Screen, Card, T, Row, Button, Field, Banner, Pill } from '../components/ui';
import { api } from '../services/session';
import { t } from '../core/i18n';
import { fcfa } from '../core/format';
import { C, R } from '../theme';

export default function PaymentsScreen({ back }) {
  const [data, setData] = useState({ a_confirmer: [], recus: [], a_payer: [], moyens: {} });
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState({ text: '', tone: '' });
  const [busy, setBusy] = useState(null);
  const [contest, setContest] = useState(null);      // id du paiement conteste + motif
  const [declare, setDeclare] = useState(null);      // bon a payer en cours de declaration

  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await api.payments()); } catch (e) { setMsg({ text: e.message, tone: 'error' }); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function run(key, fn) {
    setBusy(key); setMsg({ text: '', tone: '' });
    try {
      const r = await fn();
      setMsg({ text: (r.messages || []).join(' '), tone: 'ok' });
      setContest(null); setDeclare(null);
      await load();
    } catch (e) {
      setMsg({ text: e.message, tone: 'error' });
    } finally {
      setBusy(null);
    }
  }

  const confirm = (p) => run(`c${p.id}`, () => api.answerPayment(p.id, 'confirm'));
  const sendContest = () => run(`x${contest.id}`, () => api.answerPayment(contest.id, 'contest', contest.text));
  const sendDeclare = () => run(`d${declare.bon_a_payer}`, () => api.declarePayment(declare.objet, declare.objet_id, {
    amount: String(declare.amount).replace(/\s/g, ''), method: declare.method, reference: declare.reference,
  }));

  return (
    <Screen title={t('Paiements')} onBack={back} refreshing={loading} onRefresh={load}>
      <Banner text={msg.text} tone={msg.tone === 'error' ? 'error' : undefined} />
      <T muted>{t('ChantierVrai ne touche pas l\'argent : le payeur paie directement, puis le bénéficiaire confirme.')}</T>

      {data.a_confirmer.length ? <T bold>{t('À confirmer')}</T> : null}
      {data.a_confirmer.map((p) => (
        <Card key={p.id} tone="alert">
          <Row><T bold style={{ flex: 1 }}>{fcfa(p.montant)}</T><Pill text={t('À confirmer')} tone="warn" /></Row>
          <T>{p.chantier} · {p.libelle}</T>
          <T muted>{t('Payé par %(who)s le %(d)s', { who: p.payeur, d: p.date })} · {p.moyen_label}{p.reference ? ` · ${p.reference}` : ''}</T>
          <T muted>{t('Vérifiez sur votre compte Mobile Money ou bancaire avant de confirmer.')}</T>
          {contest && contest.id === p.id ? (
            <>
              <Field label={t('Ce qui ne va pas')} value={contest.text} onChangeText={(text) => setContest({ ...contest, text })}
                placeholder={t('Rien reçu ; montant différent…')} multiline />
              <Button title={t('Signaler au payeur')} kind="orange" loading={busy === `x${p.id}`}
                disabled={(contest.text || '').trim().length < 10} onPress={sendContest} />
              <Button title={t('Annuler')} kind="ghost" onPress={() => setContest(null)} />
            </>
          ) : (
            <>
              <Button title={t('J\'ai bien reçu %(v)s', { v: fcfa(p.montant) })} loading={busy === `c${p.id}`} onPress={() => confirm(p)} />
              <Button title={t('Signaler un problème')} kind="ghost" onPress={() => setContest({ id: p.id, text: '' })} />
            </>
          )}
        </Card>
      ))}

      {data.a_payer.length ? <T bold>{t('À payer')}</T> : null}
      {data.a_payer.map((b) => (
        <Card key={b.bon_a_payer}>
          <Row><T bold style={{ flex: 1 }}>{fcfa(b.reste)}</T><Pill text={b.bon_a_payer} /></Row>
          <T>{b.chantier} · {b.libelle}</T>
          <T muted>{t('Bénéficiaire : %(who)s', { who: b.beneficiaire || '?' })}{b.telephone ? ` · ${b.telephone}` : ''}</T>
          {b.declare ? <T muted>{t('%(v)s déjà déclarés, en attente de confirmation.', { v: fcfa(b.declare) })}</T> : null}
          {declare && declare.bon_a_payer === b.bon_a_payer ? (
            <>
              <Field label={t('Montant payé (FCFA)')} keyboardType="numeric" value={String(declare.amount)}
                onChangeText={(amount) => setDeclare({ ...declare, amount })} />
              <T muted>{t('Moyen de paiement')}</T>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
                {Object.entries(data.moyens).map(([k, label]) => (
                  <Pressable key={k} onPress={() => setDeclare({ ...declare, method: k })} accessibilityRole="radio"
                    accessibilityState={{ selected: declare.method === k }}
                    style={{ paddingVertical: 8, paddingHorizontal: 12, borderRadius: R.pill, borderWidth: 1,
                      borderColor: declare.method === k ? C.green : C.border, backgroundColor: declare.method === k ? C.greenSoft : C.card }}>
                    <Text style={{ color: declare.method === k ? C.green : C.text }}>{label}</Text>
                  </Pressable>
                ))}
              </View>
              <Field label={t('Référence de la transaction')} value={declare.reference} placeholder="Wave TX123456"
                onChangeText={(reference) => setDeclare({ ...declare, reference })} autoCapitalize="characters" />
              <T muted>{t('Pour joindre la photo du reçu, utilisez le site web.')}</T>
              <Button title={t('Déclarer le paiement')} loading={busy === `d${b.bon_a_payer}`}
                disabled={!declare.reference.trim() || !Number(String(declare.amount).replace(/\s/g, ''))} onPress={sendDeclare} />
              <Button title={t('Annuler')} kind="ghost" onPress={() => setDeclare(null)} />
            </>
          ) : (
            <Button title={t('J\'ai payé : déclarer le paiement')}
              onPress={() => setDeclare({ ...b, amount: b.reste, method: 'mobile_money', reference: '' })} />
          )}
        </Card>
      ))}

      {data.recus.length ? <T bold>{t('Historique')}</T> : null}
      {data.recus.map((p) => (
        <Card key={p.id}>
          <Row><T bold style={{ flex: 1 }}>{fcfa(p.montant)}</T><Pill text={p.statut_label} tone={p.statut === 'conteste' ? 'warn' : undefined} /></Row>
          <T muted>{p.chantier} · {p.libelle} · {p.date}</T>
          {p.motif ? <T muted>{p.motif}</T> : null}
        </Card>
      ))}
      {!data.a_confirmer.length && !data.a_payer.length && !data.recus.length && !loading
        ? <Card><T muted>{t('Aucun paiement pour l\'instant.')}</T></Card> : null}
    </Screen>
  );
}
