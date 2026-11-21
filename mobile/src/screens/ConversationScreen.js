// Conversation du chantier, comme une messagerie : messages, photos (avec la distance au chantier),
// notes vocales, et les décisions (achat, travaux en plus, étape terminée) directement dans le fil.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, AppState, FlatList, Image, KeyboardAvoidingView, Linking, Platform, Pressable, StyleSheet, Text, TextInput, Vibration, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { AudioModule, RecordingPresets, createAudioPlayer, setAudioModeAsync, useAudioRecorder } from 'expo-audio';
import { Screen, Banner } from '../components/ui';
import { api, current } from '../services/session';
import { t, getLang } from '../core/i18n';
import { fcfa } from '../core/format';
import { duration, mergeItems, rows } from '../core/chat';
import { C } from '../theme';

const POLL_MS = 5000;

export default function ConversationScreen({ back, go, params }) {
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState(null);           // { role, can_write, chef, project, last_read }
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);
  const [busyCard, setBusyCard] = useState('');
  const [rec, setRec] = useState(null);              // { start } pendant l'enregistrement
  const [recSec, setRecSec] = useState(0);
  const [playing, setPlaying] = useState(null);      // clé de la note en cours de lecture
  const last = useRef('');
  const list = useRef(null);
  const player = useRef(null);
  const insets = useSafeAreaInsets();
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const auth = { Authorization: `Bearer ${current().token}` };

  const load = useCallback(async (full) => {
    try {
      const r = await api.chat(params.id, full ? null : last.current);
      if (full) setMeta({ role: r.role, can_write: r.can_write, chef: r.chef, project: r.project, last_read: r.last_read });
      if (r.items.length || full) {
        setItems((old) => (full ? mergeItems([], r.items) : mergeItems(old, r.items)));
        if (!full && r.items.some((x) => !x.mine)) Vibration.vibrate(10);
      }
      last.current = r.last || last.current;
      setError('');
    } catch (e) {
      if (full) setError(e.name === 'NetworkError' ? t('Pas de connexion au serveur.') : e.message);
    }
  }, [params.id]);

  // Chargement, puis les nouveaux messages toutes les 5 s quand l'application est au premier plan
  useEffect(() => {
    load(true);
    let active = AppState.currentState === 'active';
    const sub = AppState.addEventListener('change', (s) => { active = s === 'active'; if (active) load(false); });
    const timer = setInterval(() => { if (active) load(false); }, POLL_MS);
    return () => { clearInterval(timer); sub.remove(); if (player.current) player.current.remove(); };
  }, [load]);

  useEffect(() => {
    if (!rec) return undefined;
    const i = setInterval(() => setRecSec(Math.round((Date.now() - rec.start) / 1000)), 250);
    return () => clearInterval(i);
  }, [rec]);

  async function post(form) {
    setSending(true); setError('');
    try {
      await api.sendChat(params.id, form);
      await load(false);
    } catch (e) {
      setError(e.name === 'NetworkError' ? t('Pas de connexion au serveur.') : e.message);
    } finally { setSending(false); }
  }

  function sendText() {
    const v = text.trim();
    if (!v) return;
    const f = new FormData();
    f.append('body', v);
    setText('');
    post(f);
  }

  async function sendPhoto() {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) { setError(t('Autorisez la caméra pour prendre les preuves.')); return; }
    const r = await ImagePicker.launchCameraAsync({ quality: 0.8, exif: true });
    if (r.canceled || !r.assets || !r.assets[0]) return;
    const f = new FormData();
    f.append('file', { uri: r.assets[0].uri, name: 'photo.jpg', type: 'image/jpeg' });
    if (text.trim()) { f.append('body', text.trim()); setText(''); }
    post(f);
  }

  // Note vocale : appui long sur le micro, on relâche pour envoyer
  async function startRec() {
    const p = await AudioModule.requestRecordingPermissionsAsync();
    if (!p.granted) { setError(t('Micro refusé : autorisez-le dans les réglages du téléphone.')); return; }
    await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: true });
    await recorder.prepareToRecordAsync();
    recorder.record();
    Vibration.vibrate(15);
    setRecSec(0);
    setRec({ start: Date.now() });
  }
  async function stopRec(cancel) {
    if (!rec) return;
    const secs = Math.round((Date.now() - rec.start) / 1000);
    setRec(null);
    try { await recorder.stop(); } catch (e) { return; }
    await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false });
    if (cancel || secs < 1 || !recorder.uri) return;
    const f = new FormData();
    f.append('file', { uri: recorder.uri, name: 'note.m4a', type: 'audio/m4a' });
    f.append('duration', String(secs));
    post(f);
  }

  function play(key, url) {
    if (player.current) { player.current.remove(); player.current = null; }
    if (playing === key) { setPlaying(null); return; }
    const pl = createAudioPlayer({ uri: api.url(url), headers: auth });
    pl.addListener('playbackStatusUpdate', (s) => { if (s.didJustFinish) setPlaying(null); });
    pl.play();
    player.current = pl;
    setPlaying(key);
  }

  async function decide(kind, fields, confirm) {
    const run = async () => {
      setBusyCard(`${kind}-${fields.id}`); setError('');
      try {
        if (kind === 'buy') await api.purchaseAction(params.id, fields);
        else await api.changeOrderAction(params.id, fields);
        await load(true);
      } catch (e) { setError(e.message); } finally { setBusyCard(''); }
    };
    if (!confirm) return run();
    Alert.alert(confirm.title, confirm.body, [{ text: t('Annuler'), style: 'cancel' }, { text: confirm.ok, onPress: run }]);
    return null;
  }

  const openWeb = (path) => Linking.openURL(api.url(path));
  const owner = meta && meta.role === 'owner';
  const data = rows(items, meta && meta.last_read);

  function bubble(it) {
    const me = it.mine;
    const isVoice = (it.type === 'voice' || it.type === 'note') && it.file_url;
    return (
      <View style={[st.msg, me ? st.me : st.them, it.type === 'photo' && st.photoMsg]}>
        {!me && it.author ? <Text style={st.author}>{it.author}</Text> : null}
        {it.type === 'photo' && it.file_url ? (
          <View>
            <Image source={{ uri: api.url(it.file_url), headers: auth }} style={st.photo} resizeMode="cover" accessibilityLabel={t('Photo')} />
            {it.distance != null ? <View style={st.badge}><Text style={st.badgeText}>📍 {t('à %(n)s m du chantier', { n: it.distance })}</Text></View> : null}
          </View>
        ) : null}
        {isVoice ? (
          <Pressable onPress={() => play(`${it.type}-${it.id}`, it.file_url)} style={st.voice} accessibilityRole="button" accessibilityLabel={t('Écouter')}>
            <View style={[st.play, me && st.playMe]}><Ionicons name={playing === `${it.type}-${it.id}` ? 'pause' : 'play'} size={16} color={me ? C.bubbleMe : '#0B2219'} /></View>
            <View style={st.wave}>{[6, 12, 9, 16, 11, 7, 14, 18, 10, 6, 13, 9, 15, 8, 12, 7].map((h, i) => (
              <View key={i} style={[st.bar, { height: h, backgroundColor: me ? C.bubbleMeText : C.text, opacity: playing === `${it.type}-${it.id}` ? 0.9 : 0.4 }]} />))}</View>
            <Text style={[st.dur, me && { color: C.bubbleMeText }]}>{it.duration ? duration(it.duration) : '🎙'}</Text>
          </Pressable>
        ) : null}
        {it.body ? (
          <Text style={[st.body, me && { color: C.bubbleMeText }, it.type === 'note' && isVoice && st.transcript]}>
            {it.type === 'note' && it.urgent ? <Text style={{ color: C.orange, fontWeight: '800' }}>⚠ {t('Urgent')} </Text> : null}{it.body}
          </Text>
        ) : null}
        <Text style={[st.time, me && { color: C.bubbleMeText }]}>{it.time}</Text>
      </View>
    );
  }

  function decisionCard(it) {
    const busy = busyCard === `${it.type}-${it.id}`;
    if (it.type === 'step') {
      return (
        <View style={[st.card, st.stepCard]}>
          <Text style={[st.kicker, { color: '#E3C48E' }]}>{t('Étape déclarée terminée')}</Text>
          <Text style={[st.cardTitle, { color: '#fff', textAlign: 'center' }]}>{it.title}</Text>
          <Text style={[st.amt, { color: '#fff' }]}>{fcfa(it.amount)}</Text>
          {owner ? (
            <Pressable onPress={() => go('project', { id: params.id })} style={st.gold} accessibilityRole="button">
              <Text style={st.goldText}>{t('Vérifier et valider')}</Text>
            </Pressable>
          ) : null}
        </View>
      );
    }
    const isBuy = it.type === 'buy';
    const open = isBuy ? ['demande', 'acceptee'].includes(it.status) : it.status === 'proposee';
    return (
      <View style={[st.card, it.mine ? { alignSelf: 'flex-end' } : null]}>
        <Text style={st.kicker}>{isBuy ? t('Demande d\'achat') : t('Travaux supplémentaires')}{it.author ? ` · ${it.author}` : ''}</Text>
        <Text style={st.cardTitle}>{it.title}</Text>
        <Text style={st.amt}>{isBuy ? '' : '+'}{fcfa(it.amount)}{!isBuy && it.days ? `  ·  +${it.days} ${t('jours')}` : ''}</Text>
        {owner && open ? (
          <View style={st.acts}>
            {busy ? <ActivityIndicator color={C.gold} /> : isBuy ? (
              <>
                <Pressable style={st.gold} accessibilityRole="button" onPress={() => decide('buy', { action: 'paid', id: it.id },
                  { title: t('Payer %(a)s ?', { a: fcfa(it.amount) }), body: t('Confirmez que vous avez envoyé l\'argent au chef de chantier.'), ok: t('Payé') })}>
                  <Text style={st.goldText}>{t('Payer')}</Text>
                </Pressable>
                <Pressable style={st.ghost} accessibilityRole="button" onPress={() => openWeb(`/chantiers/${params.id}/achats?lang=${getLang()}#a${it.id}`)}>
                  <Text style={st.ghostText}>{t('Détail')}</Text>
                </Pressable>
              </>
            ) : (
              <>
                <Pressable style={st.gold} accessibilityRole="button" onPress={() => decide('change', { action: 'accept', id: it.id },
                  { title: t('Accepter ces travaux ?'), body: t('Une nouvelle étape de %(a)s sera ajoutée au chantier.', { a: fcfa(it.amount) }), ok: t('Accepter') })}>
                  <Text style={st.goldText}>{t('Accepter')}</Text>
                </Pressable>
                <Pressable style={st.ghost} accessibilityRole="button" onPress={() => openWeb(`/chantiers/${params.id}/avenants?lang=${getLang()}#c${it.id}`)}>
                  <Text style={st.ghostText}>{t('Détail')}</Text>
                </Pressable>
              </>
            )}
          </View>
        ) : <View style={st.tag}><Text style={st.tagText}>{it.status_label}</Text></View>}
      </View>
    );
  }

  const title = meta ? meta.project.name : '';
  const sub = meta && meta.chef ? t('Avec %(n)s, chef de chantier', { n: meta.chef }) : '';
  return (
    <Screen title={title} kicker={sub} onBack={back} scroll={false}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
        <Banner text={error} tone="error" />
        <FlatList ref={list} data={data} keyExtractor={(r) => r.key} contentContainerStyle={{ paddingVertical: 8, gap: 6 }}
          onContentSizeChange={() => list.current && list.current.scrollToEnd({ animated: true })}
          ListEmptyComponent={meta ? (
            <View style={st.empty}>
              <Text style={st.emptyTitle}>{t('Démarrez la conversation')}</Text>
              <Text style={st.emptyText}>{t('Messages, notes vocales et photos restent ici, avec le chantier : plus rien ne se perd dans WhatsApp.')}</Text>
            </View>
          ) : <ActivityIndicator color={C.green} style={{ marginTop: 40 }} />}
          renderItem={({ item: r }) => {
            if (r.row === 'day') return <View style={st.day}><Text style={st.dayText}>{r.label}</Text></View>;
            if (r.row === 'unread') return <View style={st.day}><Text style={[st.dayText, st.unreadText]}>{t('Nouveaux messages')}</Text></View>;
            const it = r.item;
            return ['buy', 'change', 'step'].includes(it.type) ? decisionCard(it) : bubble(it);
          }} />
        {meta && meta.can_write ? (
          <View style={[st.compose, { paddingBottom: Math.max(insets.bottom, 10) }]}>
            {rec ? (
              <View style={st.recBox}>
                <View style={st.recDot} />
                <Text style={st.recTime}>{duration(recSec)}</Text>
                <Text style={st.recHint} numberOfLines={1}>{t('Relâchez pour envoyer')}</Text>
                <Pressable onPress={() => stopRec(true)} hitSlop={10} accessibilityRole="button" accessibilityLabel={t('Annuler')}>
                  <Ionicons name="trash-outline" size={20} color={C.orange} />
                </Pressable>
              </View>
            ) : (
              <>
                <Pressable onPress={sendPhoto} style={st.round} accessibilityRole="button" accessibilityLabel={t('Envoyer une photo')}>
                  <Ionicons name="camera-outline" size={22} color={C.text} />
                </Pressable>
                <TextInput value={text} onChangeText={setText} placeholder={t('Message…')} placeholderTextColor={C.muted}
                  style={st.input} multiline maxLength={2000} accessibilityLabel={t('Message')} />
              </>
            )}
            {text.trim() && !rec ? (
              <Pressable onPress={sendText} style={[st.round, st.goldRound]} disabled={sending} accessibilityRole="button" accessibilityLabel={t('Envoyer')}>
                {sending ? <ActivityIndicator color="#0B2219" /> : <Ionicons name="send" size={19} color="#0B2219" />}
              </Pressable>
            ) : (
              <Pressable onPressIn={startRec} onPressOut={() => stopRec(false)} delayLongPress={0}
                style={[st.round, st.goldRound, rec && st.micOn]} accessibilityRole="button"
                accessibilityLabel={t('Maintenir pour enregistrer une note vocale')}>
                <Ionicons name="mic" size={22} color="#0B2219" />
              </Pressable>
            )}
          </View>
        ) : null}
      </KeyboardAvoidingView>
    </Screen>
  );
}

const st = StyleSheet.create({
  day: { alignItems: 'center', marginVertical: 8 },
  dayText: { fontSize: 11.5, fontWeight: '700', paddingHorizontal: 12, paddingVertical: 5, borderRadius: 99, overflow: 'hidden',
    backgroundColor: C.dark ? 'rgba(255,255,255,0.07)' : 'rgba(11,34,25,0.07)', color: C.muted },
  unreadText: { backgroundColor: C.amberSoft, color: C.goldText },
  msg: { maxWidth: '80%', paddingHorizontal: 12, paddingTop: 8, paddingBottom: 20, borderRadius: 20 },
  them: { alignSelf: 'flex-start', backgroundColor: C.bubbleThem, borderBottomLeftRadius: 6 },
  me: { alignSelf: 'flex-end', backgroundColor: C.bubbleMe, borderBottomRightRadius: 6 },
  photoMsg: { padding: 4, paddingBottom: 20 },
  author: { fontSize: 12, fontWeight: '700', color: '#9A7A3E', marginBottom: 2, paddingHorizontal: 4 },
  body: { fontSize: 15.5, lineHeight: 21, color: C.text, paddingHorizontal: 2 },
  transcript: { fontStyle: 'italic', fontSize: 13.5, opacity: 0.85, marginTop: 6 },
  time: { position: 'absolute', right: 10, bottom: 4, fontSize: 10.5, color: C.muted, opacity: 0.8 },
  photo: { width: 240, height: 180, borderRadius: 16, backgroundColor: '#E9E4D8' },
  badge: { position: 'absolute', left: 8, bottom: 8, backgroundColor: 'rgba(255,255,255,0.92)', borderRadius: 99, paddingHorizontal: 8, paddingVertical: 4 },
  badgeText: { fontSize: 11, fontWeight: '700', color: '#0B2219' },
  voice: { flexDirection: 'row', alignItems: 'center', gap: 10, minWidth: 200, paddingTop: 2 },
  play: { width: 36, height: 36, borderRadius: 18, backgroundColor: '#C9A46A', alignItems: 'center', justifyContent: 'center' },
  playMe: { backgroundColor: C.bubbleMeText },
  wave: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 2 },
  bar: { width: 3, borderRadius: 2 },
  dur: { fontSize: 12, color: C.muted },
  card: { alignSelf: 'flex-start', maxWidth: '88%', padding: 14, gap: 6, borderRadius: 20, backgroundColor: C.card,
    borderWidth: 1.5, borderColor: 'rgba(201,164,106,0.45)' },
  stepCard: { alignSelf: 'center', alignItems: 'center', backgroundColor: '#0F3324', borderColor: 'rgba(227,196,142,0.5)' },
  kicker: { fontSize: 11, fontWeight: '800', letterSpacing: 1, textTransform: 'uppercase', color: '#9A7A3E' },
  cardTitle: { fontSize: 16, fontWeight: '700', color: C.text },
  amt: { fontSize: 22, fontWeight: '800', letterSpacing: -0.4, color: C.text },
  acts: { flexDirection: 'row', gap: 8, marginTop: 2 },
  gold: { minHeight: 42, paddingHorizontal: 18, borderRadius: 99, backgroundColor: '#D6B57D', alignItems: 'center', justifyContent: 'center' },
  goldText: { color: '#0B2219', fontWeight: '800', fontSize: 14.5 },
  ghost: { minHeight: 42, paddingHorizontal: 16, borderRadius: 99, borderWidth: 1, borderColor: C.border, alignItems: 'center', justifyContent: 'center' },
  ghostText: { color: C.text, fontWeight: '700', fontSize: 14 },
  tag: { alignSelf: 'flex-start', backgroundColor: C.goldSoft, borderRadius: 99, paddingHorizontal: 10, paddingVertical: 4 },
  tagText: { fontSize: 12, fontWeight: '700', color: C.goldText },
  empty: { alignItems: 'center', padding: 40, gap: 6 },
  emptyTitle: { fontSize: 17, fontWeight: '700', color: C.text },
  emptyText: { fontSize: 14, color: C.muted, textAlign: 'center' },
  compose: { flexDirection: 'row', alignItems: 'flex-end', gap: 8, paddingTop: 10, borderTopWidth: 1, borderTopColor: C.line, backgroundColor: C.bg },
  round: { width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center', backgroundColor: C.dark ? '#14211B' : '#ECE7DC' },
  goldRound: { backgroundColor: '#D6B57D' },
  micOn: { transform: [{ scale: 1.2 }] },
  input: { flex: 1, minHeight: 46, maxHeight: 120, borderRadius: 23, paddingHorizontal: 16, paddingTop: 12, paddingBottom: 12, fontSize: 15.5,
    backgroundColor: C.card, color: C.text, borderWidth: 1, borderColor: C.border },
  recBox: { flex: 1, minHeight: 46, borderRadius: 23, flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, backgroundColor: C.card },
  recDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#D9622B' },
  recTime: { fontVariant: ['tabular-nums'], fontWeight: '700', color: C.text },
  recHint: { flex: 1, color: C.muted, fontSize: 13 },
});
