import React from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { C, R } from '../theme';

export function Screen({ title, onBack, right, children, refreshing, onRefresh, scroll = true }) {
  const body = scroll ? (
    <ScrollView contentContainerStyle={s.body}
      refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={C.green} /> : undefined}>
      {children}
    </ScrollView>
  ) : <View style={[s.body, { flex: 1 }]}>{children}</View>;
  return (
    <SafeAreaView style={s.screen} edges={['top', 'left', 'right']}>
      <View style={s.header}>
        {onBack ? <Pressable onPress={onBack} hitSlop={12} accessibilityRole="button" accessibilityLabel="←"><Text style={s.back}>←</Text></Pressable> : null}
        <Text style={s.title} numberOfLines={1} accessibilityRole="header">{title}</Text>
        <View style={s.right}>{right}</View>
      </View>
      {body}
    </SafeAreaView>
  );
}

export function Card({ children, tone, style, onPress }) {
  const st = [s.card, tone === 'green' && s.cardGreen, tone === 'alert' && s.cardAlert, style];
  if (onPress) return <Pressable onPress={onPress} style={st} accessibilityRole="button">{children}</Pressable>;
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
    <Pressable onPress={onPress} disabled={disabled || loading} style={st} accessibilityRole="button"
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
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18, paddingVertical: 12, gap: 12 },
  back: { fontSize: 24, color: C.green, fontWeight: '700' },
  title: { flex: 1, fontSize: 22, fontWeight: '800', color: C.text },
  right: { flexDirection: 'row', gap: 14, alignItems: 'center' },
  body: { padding: 18, paddingTop: 4, gap: 14, paddingBottom: 60 },
  card: { backgroundColor: C.card, borderRadius: R.card, padding: 16, gap: 10 },
  cardGreen: { backgroundColor: C.green },
  cardAlert: { borderWidth: 2, borderColor: C.orange, backgroundColor: '#FFF7F1' },
  t: { fontSize: 15, color: C.text, lineHeight: 21 },
  muted: { fontSize: 13, color: C.muted },
  big: { fontSize: 22, fontWeight: '700' },
  bold: { fontWeight: '700' },
  white: { color: '#fff' },
  btn: { minHeight: 50, borderRadius: R.btn, backgroundColor: C.green, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16 },
  btnGhost: { backgroundColor: '#fff', borderWidth: 1, borderColor: C.border },
  btnOrange: { backgroundColor: C.orange },
  btnSmall: { minHeight: 40 },
  btnDisabled: { opacity: 0.5 },
  btnText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  btnTextGhost: { color: C.text },
  label: { fontSize: 13, fontWeight: '600', color: C.text },
  input: { borderWidth: 1, borderColor: C.border, borderRadius: 12, padding: 12, fontSize: 15, backgroundColor: '#fff', color: C.text },
  bar: { height: 10, borderRadius: 999, backgroundColor: C.line, overflow: 'hidden' },
  barFill: { height: '100%', backgroundColor: C.green, borderRadius: 999 },
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
