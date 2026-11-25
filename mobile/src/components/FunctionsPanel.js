// Panneau « Toutes les fonctions » : glisse depuis la droite, rangé par famille, avec recherche.
// Le catalogue vient du serveur (même liste que le site web), filtré selon le profil de la personne.
import React from 'react';
import { Animated, Dimensions, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { C } from '../theme';
import { t } from '../core/i18n';

const ICONS = {
  cam: 'camera-outline', steps: 'list-outline', sat: 'globe-outline', note: 'mic-outline', doc: 'document-text-outline',
  zones: 'grid-outline', quality: 'search-outline', plan: 'map-outline', insp: 'person-circle-outline', trust: 'shield-checkmark-outline',
  qty: 'bar-chart-outline', money: 'cash-outline', card: 'card-outline', bank: 'business-outline', folder: 'folder-outline',
  csv: 'download-outline', stock: 'cube-outline', list: 'reorder-four-outline', calc: 'calculator-outline', sheet: 'clipboard-outline',
  land: 'trail-sign-outline', ai: 'sparkles-outline', team: 'people-outline', flag: 'flag-outline', pro: 'briefcase-outline',
  bim: 'layers-outline', pano: 'aperture-outline', sensor: 'thermometer-outline', check: 'checkmark-circle-outline', bill: 'receipt-outline',
};

const norm = (s) => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

export default function FunctionsPanel({ visible, onClose, title, groups, onOpen, simpleMode, onMode }) {
  const width = Math.min(440, Dimensions.get('window').width * 0.92);
  const x = React.useRef(new Animated.Value(width)).current;
  const [q, setQ] = React.useState('');
  const [more, setMore] = React.useState(false);   // mode simple : « Autres fonctions » replié
  React.useEffect(() => {
    if (visible) { setQ(''); setMore(false); Animated.timing(x, { toValue: 0, duration: 260, useNativeDriver: true }).start(); }
  }, [visible]);
  const close = () => Animated.timing(x, { toValue: width, duration: 180, useNativeDriver: true }).start(() => onClose());
  const words = norm(q).split(/\s+/).filter(Boolean);
  const shown = (groups || []).map((g) => ({
    ...g, items: g.items.filter((it) => { const h = norm(`${it.label} ${it.desc} ${g.title}`); return words.every((w) => h.includes(w)); }),
  })).filter((g) => g.items.length);

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close} statusBarTranslucent>
      <View style={s.root}>
        <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityLabel={t('Fermer')} />
        <Animated.View style={[s.panel, { width, transform: [{ translateX: x }] }]}>
          <SafeAreaView style={{ flex: 1 }} edges={['top', 'bottom', 'right']}>
            <View style={s.head}>
              <View style={{ flex: 1, minWidth: 0 }}>
                {title ? <Text style={s.kicker} numberOfLines={1}>{title}</Text> : null}
                <Text style={s.h} accessibilityRole="header">{t('Toutes les fonctions')}</Text>
              </View>
              <Pressable onPress={close} style={s.close} accessibilityRole="button" accessibilityLabel={t('Fermer')} hitSlop={6}>
                <Ionicons name="close" size={20} color={C.text} />
              </Pressable>
            </View>
            <View style={s.search}>
              <Ionicons name="search" size={18} color={C.muted} />
              <TextInput value={q} onChangeText={setQ} placeholder={t('Rechercher : stock, paiement, plan…')} placeholderTextColor="#8A8F8C"
                style={s.input} returnKeyType="search" accessibilityLabel={t('Rechercher une fonction')} autoCorrect={false} />
            </View>
            <ScrollView contentContainerStyle={{ paddingHorizontal: 18, paddingBottom: 24 }} keyboardShouldPersistTaps="handled">
              {shown.map((g) => (
                <View key={g.key} style={{ marginTop: g.collapsed ? 20 : 14 }}>
                  {g.collapsed && !words.length ? (
                    <Pressable onPress={() => setMore(!more)} accessibilityRole="button" accessibilityState={{ expanded: more }}
                      style={({ pressed }) => [s.more, more && s.moreOpen, pressed && { opacity: 0.7 }]}>
                      <View style={{ flex: 1, gap: 2 }}>
                        <Text style={s.label}>{g.title || t('Fonctions masquées')}</Text>
                        <Text style={s.desc}>{t('%(n)s fonction(s) éteinte(s) : réglez-les sur le site, dans « Fonctions de l\'appli »', { n: g.items.length })}</Text>
                      </View>
                      <Ionicons name={more ? 'chevron-down' : 'chevron-forward'} size={18} color="#9AA09C" />
                    </Pressable>
                  ) : <Text style={s.gTitle}>{g.title}</Text>}
                  {g.collapsed && !words.length && !more ? null : <View style={[s.list, g.collapsed && !words.length && { marginTop: 6 }]}>
                    {g.items.map((it, i) => (
                      <Pressable key={it.path} onPress={() => { onOpen(it); close(); }} accessibilityRole="button"
                        accessibilityLabel={`${it.label}. ${it.desc}`}
                        style={({ pressed }) => [s.item, i > 0 && s.sep, pressed && { opacity: 0.6 }]}>
                        <View style={s.ico}><Ionicons name={ICONS[it.icon] || 'document-text-outline'} size={20} color={C.green} /></View>
                        <View style={{ flex: 1, gap: 1 }}>
                          <Text style={s.label}>{it.label}</Text>
                          <Text style={s.desc}>{it.desc}</Text>
                        </View>
                        <Ionicons name="chevron-forward" size={16} color="#B7BCB9" />
                      </Pressable>
                    ))}
                  </View>}
                </View>
              ))}
              {onMode && simpleMode !== undefined && simpleMode !== null && !words.length ? (
                <View style={s.mode}>
                  <Text style={s.desc}>{simpleMode ? t('Mode simple : l\'essentiel d\'abord.') : t('Vous voyez toutes les fonctions.')}</Text>
                  <Pressable onPress={() => onMode(simpleMode ? 'complet' : 'simple')} accessibilityRole="button" hitSlop={8}>
                    <Text style={s.link}>{simpleMode ? t('Toujours tout afficher') : t('Revenir au mode simple')}</Text>
                  </Pressable>
                </View>
              ) : null}
              {!shown.length ? <Text style={[s.desc, { textAlign: 'center', marginTop: 24 }]}>{t('Aucune fonction ne correspond. Essayez un autre mot.')}</Text> : null}
            </ScrollView>
          </SafeAreaView>
        </Animated.View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: 'rgba(11,34,25,0.32)', flexDirection: 'row', justifyContent: 'flex-end' },
  panel: { height: '100%', backgroundColor: C.bg, borderTopLeftRadius: 24, borderBottomLeftRadius: 24, overflow: 'hidden',
    shadowColor: '#0B2219', shadowOpacity: 0.2, shadowRadius: 30, shadowOffset: { width: -10, height: 0 }, elevation: 12 },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingHorizontal: 20, paddingTop: 14, paddingBottom: 10 },
  kicker: { fontSize: 13, color: C.muted },
  h: { fontSize: 24, fontWeight: '600', letterSpacing: -0.7, color: C.text },
  close: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#ECE8DF', alignItems: 'center', justifyContent: 'center' },
  search: { flexDirection: 'row', alignItems: 'center', gap: 10, marginHorizontal: 18, paddingHorizontal: 14, minHeight: 48,
    borderRadius: 14, backgroundColor: '#fff', borderWidth: 1, borderColor: '#E4E0D6' },
  input: { flex: 1, fontSize: 16, color: C.text, paddingVertical: 10 },
  gTitle: { fontSize: 12, fontWeight: '700', letterSpacing: 0.8, textTransform: 'uppercase', color: C.muted, marginBottom: 6, marginLeft: 4 },
  list: { backgroundColor: '#fff', borderRadius: 18, paddingHorizontal: 12 },
  item: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 60, paddingVertical: 10 },
  sep: { borderTopWidth: 1, borderTopColor: '#F2EFE8' },
  ico: { width: 38, height: 38, borderRadius: 12, backgroundColor: '#F1F5F2', alignItems: 'center', justifyContent: 'center' },
  label: { fontSize: 15, fontWeight: '600', color: C.text },
  desc: { fontSize: 13, color: C.muted, lineHeight: 18 },
  more: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 60, paddingHorizontal: 16, paddingVertical: 12,
    borderRadius: 18, borderWidth: 1, borderStyle: 'dashed', borderColor: '#CFC9BB' },
  moreOpen: { borderColor: 'transparent', paddingHorizontal: 4, minHeight: 44 },
  mode: { marginTop: 18, marginHorizontal: 4, gap: 4 },
  link: { fontSize: 14, fontWeight: '600', color: C.green, textDecorationLine: 'underline', paddingVertical: 8 },
});
