import React from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View, RefreshControl } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { C, R } from '../theme';

export function Screen({ title, kicker, onBack, right, children, refreshing, onRefresh, scroll = true, large }) {
  // En-tête d'application : retour (chevron) à gauche, titre, actions à droite. Grand titre sur les écrans d'onglet.
  const body = scroll ? (
    <ScrollView contentContainerStyle={s.body} keyboardShouldPersistTaps="handled"
      refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={C.green} /> : undefined}>
      {children}
    </ScrollView>
  ) : <View style={[s.body, { flex: 1 }]}>{children}</View>;
  return (
    <SafeAreaView style={s.screen} edges={['top', 'left', 'right']}>
      <View style={[s.header, large && s.headerLarge]}>
        {onBack ? (
          <Pressable onPress={onBack} hitSlop={10} accessibilityRole="button" accessibilityLabel="Retour"
            style={({ pressed }) => [s.iconBtn, pressed && s.pressed]}>
            <Ionicons name="chevron-back" size={26} color={C.text} />
          </Pressable>
        ) : null}
        <View style={{ flex: 1 }}>
          {kicker ? <Text style={s.kicker} numberOfLines={1}>{kicker}</Text> : null}
          <Text style={[s.title, large && s.titleLarge]} numberOfLines={1} accessibilityRole="header">{title}</Text>
        </View>
        <View style={s.right}>{right}</View>
      </View>
      {body}
    </SafeAreaView>
  );
}

export function IconButton({ name, onPress, label, badge }) {
  return (
    <Pressable onPress={onPress} hitSlop={8} accessibilityRole="button" accessibilityLabel={label}
      style={({ pressed }) => [s.iconBtn, pressed && s.pressed]}>
      <Ionicons name={name} size={24} color={C.text} />
      {badge ? <View style={s.badge}><Text style={s.badgeText}>{badge > 9 ? '9+' : badge}</Text></View> : null}
    </Pressable>
  );
}

// Barre d'onglets du bas : icône dans une pastille quand l'onglet est actif, libellé dessous, pastille de compteur.
export function TabBar({ tabs, active, onChange }) {
  // Barre flottante vert profond : l'onglet actif est une pastille blanche, les autres en vert clair.
  const insets = useSafeAreaInsets();
  return (
    <View style={[s.tabWrap, { paddingBottom: Math.max(insets.bottom, 10) }]}>
      <View style={s.tabbar} accessibilityRole="tablist">
        {tabs.map((tb) => {
          const on = tb.key === active;
          return (
            <Pressable key={tb.key} onPress={() => onChange(tb.key)} accessibilityRole="tab"
              accessibilityState={{ selected: on }} accessibilityLabel={tb.badge ? `${tb.label} (${tb.badge})` : tb.label}
              style={({ pressed }) => [s.tab, on && s.tabOn, pressed && { transform: [{ scale: 0.95 }] }]}>
              <View>
                <Ionicons name={on ? tb.icon : `${tb.icon}-outline`} size={22} color={on ? C.forest : C.mint} />
                {tb.badge ? <View style={[s.badge, s.tabBadge]}><Text style={s.badgeText}>{tb.badge > 9 ? '9+' : tb.badge}</Text></View> : null}
              </View>
              <Text style={[s.tabLabel, on && s.tabLabelOn]} numberOfLines={1}>{tb.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

// Bandeau vert profond : un grand chiffre et deux indicateurs (accueil du propriétaire).
export function Band({ kicker, value, unit, sub, stats }) {
  return (
    <View style={s.band}>
      <Text style={s.bandKicker}>{kicker}</Text>
      <Text style={s.bandBig}>{value} <Text style={s.bandUnit}>{unit}</Text></Text>
      {sub ? <Text style={s.bandKicker}>{sub}</Text> : null}
      {stats ? (
        <View style={s.bandStats}>
          {stats.map((x) => (
            <Pressable key={x.label} onPress={x.onPress} disabled={!x.onPress} style={s.bandStat}>
              <Text style={s.bandStatLabel}>{x.label}</Text>
              <Text style={s.bandStatValue}>{x.value}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

// Carte photo d'un chantier : la dernière photo vérifiée en fond, le nom et l'avancement par-dessus.
export function PhotoCard({ uri, headers, chip, title, pct, tags, onPress }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={title}
      style={({ pressed }) => [s.pcard, pressed && { transform: [{ scale: 0.985 }] }]}>
      {uri ? <Image source={{ uri, headers }} style={StyleSheet.absoluteFill} resizeMode="cover" />
        : <View style={[StyleSheet.absoluteFill, s.pcardEmpty]}><Ionicons name="camera-outline" size={48} color="rgba(255,255,255,0.3)" /></View>}
      {chip ? <View style={s.pcardChip}><Text style={s.pcardChipText}>{chip}</Text></View> : null}
      <View style={s.pcardBody}>
        <Text style={s.pcardTitle} numberOfLines={2}>{title}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <View style={s.pcardBar}><View style={[s.pcardFill, { width: `${Math.max(0, Math.min(100, pct || 0))}%` }]} /></View>
          <Text style={s.pcardPct}>{pct} %</Text>
        </View>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
          {(tags || []).map((tg) => (
            <View key={tg.text} style={[s.pcardTag, tg.hot && s.pcardTagHot]}><Text style={[s.pcardTagText, tg.hot && { color: '#2A1305' }]}>{tg.text}</Text></View>
          ))}
        </View>
      </View>
    </Pressable>
  );
}

export function Card({ children, tone, style, onPress }) {
  const st = [s.card, tone === 'green' && s.cardGreen, tone === 'alert' && s.cardAlert, style];
  if (onPress) {
    return (
      <Pressable onPress={onPress} accessibilityRole="button"
        style={({ pressed }) => [...st, pressed && { transform: [{ scale: 0.985 }], opacity: 0.92 }]}>{children}</Pressable>
    );
  }
  return <View style={st}>{children}</View>;
}

export function T({ children, muted, big, bold, white, style, ...rest }) {
  return (
    <Text style={[s.t, muted && s.muted, big && s.big, bold && s.bold, white && s.white, style]} {...rest}>{children}</Text>
  );
}

export function Button({ title, onPress, kind = 'primary', disabled, loading, small }) {
  const st = [s.btn, kind === 'ghost' && s.btnGhost, kind === 'orange' && s.btnOrange, small && s.btnSmall,
    (disabled || loading) && s.btnDisabled];
  return (
    <Pressable onPress={onPress} disabled={disabled || loading} style={({ pressed }) => [...st, pressed && { transform: [{ scale: 0.98 }] }]} accessibilityRole="button"
      accessibilityState={{ disabled: !!(disabled || loading) }}>
      {loading ? <ActivityIndicator color={kind === 'ghost' ? C.green : '#fff'} />
        : <Text style={[s.btnText, kind === 'ghost' && s.btnTextGhost]}>{title}</Text>}
    </Pressable>
  );
}

export function Field({ label, ...props }) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={s.label}>{label}</Text>
      <TextInput style={s.input} placeholderTextColor="#8A8F8C" accessibilityLabel={label} {...props} />
    </View>
  );
}

export function Bar({ pct, color }) {
  return (
    <View style={s.bar}><View style={[s.barFill, { width: `${Math.max(0, Math.min(100, pct || 0))}%` }, color && { backgroundColor: color }]} /></View>
  );
}

export function Pill({ text, tone }) {
  return (
    <View style={[s.pill, tone === 'warn' && s.pillWarn, tone === 'amber' && s.pillAmber, tone === 'grey' && s.pillGrey]}>
      <Text style={[s.pillText, tone === 'warn' && { color: '#9A3F12' }, tone === 'amber' && { color: C.amber }, tone === 'grey' && { color: '#3C433F' }]}>{text}</Text>
    </View>
  );
}

export function Row({ children, style }) {
  return <View style={[s.row, style]}>{children}</View>;
}

export function Banner({ text, tone }) {
  if (!text) return null;
  return <View style={[s.banner, tone === 'error' && s.bannerError]}><Text style={[s.bannerText, tone === 'error' && { color: '#9A3F12' }]}>{text}</Text></View>;
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.bg },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, paddingVertical: 6, gap: 4, minHeight: 56 },
  headerLarge: { paddingHorizontal: 18, paddingTop: 10, paddingBottom: 8 },
  kicker: { fontSize: 12, fontWeight: '600', color: C.muted },
  title: { fontSize: 18, fontWeight: '700', color: C.text, letterSpacing: -0.2 },
  titleLarge: { fontSize: 30, fontWeight: '800', letterSpacing: -0.8 },
  right: { flexDirection: 'row', gap: 4, alignItems: 'center' },
  iconBtn: { width: 44, height: 44, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  pressed: { backgroundColor: 'rgba(14,90,58,0.08)', transform: [{ scale: 0.95 }] },
  badge: { position: 'absolute', top: 6, left: 24, minWidth: 16, height: 16, paddingHorizontal: 4, borderRadius: 8,
    backgroundColor: C.orange, alignItems: 'center', justifyContent: 'center', borderWidth: 2, borderColor: C.bg },
  badgeText: { color: '#fff', fontSize: 10, fontWeight: '800' },
  tabWrap: { backgroundColor: C.bg, paddingHorizontal: 12, paddingTop: 6 },
  tabbar: { flexDirection: 'row', backgroundColor: C.forest, borderRadius: 26, padding: 6, gap: 4,
    shadowColor: C.forest, shadowOpacity: 0.28, shadowRadius: 14, shadowOffset: { width: 0, height: 8 }, elevation: 10 },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 3, minHeight: 56, borderRadius: 20 },
  tabOn: { backgroundColor: '#FFFFFF' },
  tabBadge: { top: -4, left: 14, borderColor: C.forest },
  tabLabel: { fontSize: 11, fontWeight: '600', color: C.mint },
  tabLabelOn: { color: C.forest, fontWeight: '800' },
  band: { backgroundColor: C.forest, borderRadius: 24, padding: 20, gap: 4 },
  bandKicker: { color: C.mint, fontSize: 13 },
  bandBig: { color: '#fff', fontSize: 38, fontWeight: '800', letterSpacing: -1 },
  bandUnit: { color: C.mint, fontSize: 15, fontWeight: '700', letterSpacing: 0 },
  bandStats: { flexDirection: 'row', gap: 10, marginTop: 12 },
  bandStat: { flex: 1, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: 16, padding: 12, gap: 2 },
  bandStatLabel: { color: C.mint, fontSize: 12 },
  bandStatValue: { color: '#fff', fontSize: 19, fontWeight: '800' },
  pcard: { height: 250, borderRadius: 24, overflow: 'hidden', backgroundColor: C.forest },
  pcardEmpty: { alignItems: 'center', justifyContent: 'center', paddingBottom: 70, backgroundColor: C.forest2 },
  pcardChip: { position: 'absolute', left: 14, top: 14, backgroundColor: 'rgba(255,255,255,0.94)', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  pcardChipText: { fontSize: 12, fontWeight: '700', color: C.text },
  pcardBody: { position: 'absolute', left: 0, right: 0, bottom: 0, padding: 16, paddingTop: 40, gap: 8, backgroundColor: 'rgba(12,42,30,0.78)' },
  pcardTitle: { color: '#fff', fontSize: 20, fontWeight: '800', letterSpacing: -0.3 },
  pcardBar: { flex: 1, height: 6, borderRadius: 999, backgroundColor: 'rgba(255,255,255,0.25)', overflow: 'hidden' },
  pcardFill: { height: 6, borderRadius: 999, backgroundColor: '#fff' },
  pcardPct: { color: '#fff', fontWeight: '700', fontSize: 14 },
  pcardTag: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, backgroundColor: 'rgba(255,255,255,0.16)' },
  pcardTagHot: { backgroundColor: C.warm },
  pcardTagText: { color: '#fff', fontSize: 12, fontWeight: '700' },
  body: { padding: 18, paddingTop: 4, gap: 14, paddingBottom: 40 },
  card: { backgroundColor: C.card, borderRadius: R.card, padding: 16, gap: 10, shadowColor: '#1B1F1D', shadowOpacity: 0.04,
    shadowRadius: 6, shadowOffset: { width: 0, height: 1 }, elevation: 1 },
  cardGreen: { backgroundColor: C.forest },
  cardAlert: { borderWidth: 2, borderColor: C.orange, backgroundColor: '#FFF7F1' },
  t: { fontSize: 15, color: C.text, lineHeight: 21 },
  muted: { fontSize: 13, color: C.muted },
  big: { fontSize: 22, fontWeight: '700' },
  bold: { fontWeight: '700' },
  white: { color: '#fff' },
  btn: { minHeight: 52, borderRadius: R.btn, backgroundColor: C.forest, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16 },
  btnGhost: { backgroundColor: '#fff', borderWidth: 1, borderColor: C.border },
  btnOrange: { backgroundColor: C.orange },
  btnSmall: { minHeight: 40 },
  btnDisabled: { opacity: 0.5 },
  btnText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  btnTextGhost: { color: C.text },
  label: { fontSize: 13, fontWeight: '600', color: C.text },
  input: { borderWidth: 1, borderColor: C.border, borderRadius: 12, padding: 12, fontSize: 15, backgroundColor: '#fff', color: C.text },
  bar: { height: 10, borderRadius: 999, backgroundColor: C.line, overflow: 'hidden' },
  barFill: { height: '100%', backgroundColor: C.accentFill, borderRadius: 999 },
  pill: { paddingHorizontal: 9, paddingVertical: 4, borderRadius: 999, backgroundColor: C.greenSoft, alignSelf: 'flex-start' },
  pillWarn: { backgroundColor: C.orangeSoft },
  pillAmber: { backgroundColor: C.amberSoft },
  pillGrey: { backgroundColor: '#ECE9E2' },
  pillText: { fontSize: 12, fontWeight: '600', color: C.green },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10 },
  banner: { padding: 12, borderRadius: 12, backgroundColor: C.greenSoft },
  bannerError: { backgroundColor: C.orangeSoft },
  bannerText: { color: C.green, fontWeight: '600', fontSize: 14 },
});
