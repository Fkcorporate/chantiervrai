// Accueil des métiers (inspecteur, fournisseur, télépilote) : la prochaine mission en grand,
// trois chiffres du mois, puis « À faire » et « Terminé ». Même contenu que l'accueil du site.
import React from 'react';
import { ActivityIndicator, Image, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { C } from '../theme';
import { t } from '../core/i18n';
import { fcfa } from '../core/format';

const TAG = { amber: '#B4671B', blue: '#2D5EA8', bad: '#B23A1C', green: '#1F7A4D' };
const TAG_NIGHT = { amber: '#F2B872', blue: '#A4C6F4', bad: '#F3A188', green: '#74DBA8' };

export default function ProHome({ data, image, open, onAnswer, busy, glyph }) {
  if (!data || !data.pro) return null;
  const { pro } = data;
  const h = pro.hero;
  const amount = (n) => fcfa(n).replace(' FCFA', '');
  return (
    <View style={s.wrap}>
      <View>
        <Text style={s.date}>{data.greeting} · {data.today}</Text>
        <Text style={s.name} accessibilityRole="header">{(data.name || '').split(' ')[0]}</Text>
      </View>
      {h ? (
        <View style={s.hero}>
          {h.thumb_url ? <Image source={image(h.thumb_url)} style={StyleSheet.absoluteFill} resizeMode="cover" /> : (
            <View style={s.glyph} pointerEvents="none"><Ionicons name={glyph} size={190} color="rgba(227,196,142,0.16)" /></View>
          )}
          <View style={[StyleSheet.absoluteFill, h.thumb_url ? s.shade : null]} pointerEvents="none" />
          <View style={s.heroBody}>
            <View style={s.kicker}><Text style={s.kickerText}>{h.kicker}</Text></View>
            <Text style={s.heroTitle} numberOfLines={2}>{h.title}</Text>
            {h.sub ? <Text style={s.heroSub} numberOfLines={2}>{h.sub}</Text> : null}
            <View style={s.meta}>
              <View style={s.when}><View style={s.dot} /><Text style={s.whenText}>{h.when}</Text></View>
              {h.amount ? <Text style={s.heroAmt}>{amount(h.amount)} <Text style={s.unit}>FCFA</Text></Text> : null}
            </View>
            <View style={s.acts}>
              <Pressable onPress={() => open(h.cta.path)} style={({ pressed }) => [s.cta, pressed && s.pressed]} accessibilityRole="button">
                <Text style={s.ctaText} numberOfLines={2}>{h.cta.label}</Text>
              </Pressable>
              {h.alt ? (
                <Pressable onPress={() => Linking.openURL(h.alt.url)} style={({ pressed }) => [s.alt, pressed && s.pressed]} accessibilityRole="button">
                  <Ionicons name="navigate-outline" size={16} color="#fff" /><Text style={s.altText}>{h.alt.label}</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        </View>
      ) : (
        <View style={[s.hero, s.calm]}>
          <View style={s.heroBody}>
            <View style={s.kicker}><Text style={s.kickerText}>{t('Rien d\'urgent')}</Text></View>
            <Text style={s.heroTitle}>{data.role === 'fournisseur' ? t('Aucune livraison prévue') : t('Aucune mission prévue')}</Text>
            <Text style={s.heroSub}>{t('Les nouvelles demandes apparaîtront ici, avec une alerte sur votre téléphone.')}</Text>
          </View>
        </View>
      )}
      <View style={s.kpis}>
        {pro.kpis.map((k) => (
          <View key={k.label} style={s.kpi}>
            <Text style={s.kpiVal} numberOfLines={1} adjustsFontSizeToFit>{k.value}{k.unit ? <Text style={s.kpiUnit}> {k.unit}</Text> : null}</Text>
            <Text style={s.kpiLabel} numberOfLines={2}>{k.label}</Text>
          </View>
        ))}
      </View>
      {pro.todo.length ? <Text style={s.h}>{t('À faire')}  <Text style={s.count}> {pro.todo.length} </Text></Text> : null}
      {pro.todo.map((it, i) => (
        <View key={`t${i}`} style={s.item}>
          <Pressable onPress={() => open(it.path)} style={({ pressed }) => [s.row, pressed && s.pressed]} accessibilityRole="button">
            {it.thumb_url ? <Image source={image(it.thumb_url)} style={s.th} /> : <View style={s.th}><Text style={s.thLetter}>{(it.title || '?').slice(0, 1)}</Text></View>}
            <View style={{ flex: 1, minWidth: 0 }}>
              {it.tag ? <Text style={[s.tag, { color: (C.dark ? TAG_NIGHT : TAG)[it.tagc] || C.goldText }]}>{it.tag}</Text> : null}
              <Text style={s.title} numberOfLines={1}>{it.title}</Text>
              <Text style={s.sub} numberOfLines={1}>{it.sub}</Text>
            </View>
            <View style={{ alignItems: 'flex-end', gap: 3 }}>
              {it.amount ? <Text style={s.amt}>{amount(it.amount)}</Text> : null}
              {it.when ? <Text style={s.w}>{it.when}</Text> : null}
            </View>
          </Pressable>
          {it.note ? <Text style={s.note}>« {it.note} »</Text> : null}
          {it.answer_inspection ? (
            <View style={s.answer}>
              {busy === it.answer_inspection ? <ActivityIndicator color={C.gold} /> : (
                <>
                  <Pressable onPress={() => onAnswer(it.answer_inspection, 'accepter')} style={[s.btn, s.btnMain]} accessibilityRole="button">
                    <Text style={s.btnMainText}>{t('Accepter')}</Text>
                  </Pressable>
                  <Pressable onPress={() => onAnswer(it.answer_inspection, 'refuser')} style={[s.btn, s.btnGhost]} accessibilityRole="button">
                    <Text style={s.btnGhostText}>{t('Refuser')}</Text>
                  </Pressable>
                </>
              )}
            </View>
          ) : null}
        </View>
      ))}
      {pro.done.length ? <Text style={s.h}>{t('Terminé')}</Text> : null}
      {pro.done.map((it, i) => (
        <Pressable key={`d${i}`} onPress={() => open(it.path)} style={({ pressed }) => [s.done, pressed && s.pressed]} accessibilityRole="button">
          <View style={s.tick}><Ionicons name="checkmark" size={16} color={C.dark ? '#74DBA8' : '#1F7A4D'} /></View>
          <View style={{ flex: 1 }}>
            <Text style={s.title} numberOfLines={1}>{it.title}</Text>
            <Text style={s.sub} numberOfLines={1}>{[it.sub, it.when].filter(Boolean).join(' · ')}</Text>
          </View>
          {it.amount ? <Text style={s.amt}>{amount(it.amount)}</Text> : null}
        </Pressable>
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { gap: 14 },
  date: { fontSize: 12.5, fontWeight: '600', color: C.muted },
  name: { fontSize: 30, fontWeight: '700', letterSpacing: -0.8, color: C.text },
  hero: { minHeight: 300, borderRadius: 28, overflow: 'hidden', backgroundColor: '#123A2B', justifyContent: 'flex-end' },
  calm: { minHeight: 0 },
  shade: { backgroundColor: 'rgba(5,14,10,0.45)' },
  glyph: { position: 'absolute', right: -24, top: -16 },
  heroBody: { padding: 22, gap: 6 },
  kicker: { alignSelf: 'flex-start', backgroundColor: 'rgba(227,196,142,0.95)', borderRadius: 99, paddingHorizontal: 11, paddingVertical: 6 },
  kickerText: { fontSize: 11, fontWeight: '800', letterSpacing: 1.2, textTransform: 'uppercase', color: '#0B2219' },
  heroTitle: { color: '#fff', fontSize: 26, fontWeight: '700', letterSpacing: -0.5, marginTop: 6 },
  heroSub: { color: 'rgba(255,255,255,0.78)', fontSize: 14 },
  meta: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 6 },
  when: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#E3C48E' },
  whenText: { color: '#fff', fontWeight: '700', fontSize: 14 },
  heroAmt: { color: '#fff', fontSize: 22, fontWeight: '800', letterSpacing: -0.4 },
  unit: { fontSize: 12, fontWeight: '600', color: 'rgba(255,255,255,0.7)' },
  acts: { flexDirection: 'row', gap: 8, marginTop: 10 },
  cta: { flex: 1, minHeight: 48, borderRadius: 99, backgroundColor: '#D6B57D', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 14 },
  ctaText: { color: '#0B2219', fontWeight: '800', fontSize: 15, textAlign: 'center' },
  alt: { minHeight: 48, borderRadius: 99, backgroundColor: 'rgba(255,255,255,0.14)', flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 16 },
  altText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  pressed: { opacity: 0.85, transform: [{ scale: 0.985 }] },
  kpis: { flexDirection: 'row', gap: 8 },
  kpi: { flex: 1, padding: 14, borderRadius: 20, backgroundColor: C.card, borderWidth: 1, borderColor: C.line, gap: 2 },
  kpiVal: { fontSize: 19, fontWeight: '800', color: C.text, letterSpacing: -0.4 },
  kpiUnit: { fontSize: 10.5, fontWeight: '600', color: C.muted },
  kpiLabel: { fontSize: 11.5, color: C.muted },
  h: { fontSize: 18, fontWeight: '700', color: C.text, marginTop: 10 },
  count: { fontSize: 12, fontWeight: '800', color: C.dark ? '#0B2219' : '#E3C48E', backgroundColor: C.dark ? '#E3C48E' : '#0B2219' },
  item: { borderRadius: 22, backgroundColor: C.card, borderWidth: 1, borderColor: C.line, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12 },
  th: { width: 56, height: 56, borderRadius: 16, backgroundColor: C.dark ? '#14211B' : '#E9E4D8', alignItems: 'center', justifyContent: 'center' },
  thLetter: { fontSize: 20, fontWeight: '800', color: C.dark ? '#E3C48E' : '#9A7A3E' },
  tag: { fontSize: 10.5, fontWeight: '800', letterSpacing: 0.6, textTransform: 'uppercase', marginBottom: 2 },
  title: { fontSize: 15, fontWeight: '700', color: C.text },
  sub: { fontSize: 12.5, color: C.muted },
  amt: { fontSize: 14, fontWeight: '700', color: C.text },
  w: { fontSize: 12, fontWeight: '700', color: C.dark ? '#E3C48E' : '#9A7A3E' },
  note: { fontSize: 13.5, fontStyle: 'italic', color: C.muted, paddingHorizontal: 14, paddingBottom: 12 },
  answer: { flexDirection: 'row', gap: 8, paddingHorizontal: 12, paddingBottom: 12 },
  btn: { flex: 1, minHeight: 44, borderRadius: 99, alignItems: 'center', justifyContent: 'center' },
  btnMain: { backgroundColor: C.forest },
  btnMainText: { color: '#fff', fontWeight: '700' },
  btnGhost: { borderWidth: 1, borderColor: C.border },
  btnGhostText: { color: C.text, fontWeight: '700' },
  done: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: C.line },
  tick: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center', backgroundColor: C.dark ? 'rgba(31,138,87,0.18)' : '#E5F2EA' },
});
