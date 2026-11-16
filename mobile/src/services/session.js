// Etat partage de l'application : serveur, jeton de connexion, langue, file hors ligne.
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import * as FileSystem from 'expo-file-system/legacy';
import * as Localization from 'expo-localization';
import Constants from 'expo-constants';
import { Platform } from 'react-native';
import { createApi, proofFields } from '../core/apiClient';
import { createQueue } from '../core/queue';
import { setLang, getLang } from '../core/i18n';

const DEFAULT_URL = (Constants.expoConfig && Constants.expoConfig.extra && Constants.expoConfig.extra.apiUrl)
  || 'https://chantiervrai.ci';
const QUEUE_DIR = `${FileSystem.documentDirectory}envois/`;

const state = { serverUrl: DEFAULT_URL, token: null, user: null, counts: { unread: 0, toConfirm: 0 }, listeners: new Set() };

export function subscribe(fn) {
  state.listeners.add(fn);
  return () => state.listeners.delete(fn);
}
function emit() { state.listeners.forEach((fn) => fn({ ...state })); }

export const api = createApi({
  baseUrl: () => state.serverUrl,
  getToken: async () => state.token,
  lang: () => getLang(),
  onUnauthorized: () => { signOutLocal(); },
});

export async function restore() {
  const [url, lang] = await Promise.all([AsyncStorage.getItem('cv_server'), AsyncStorage.getItem('cv_lang')]);
  if (url) state.serverUrl = url;
  const deviceLang = (Localization.getLocales()[0] || {}).languageCode;
  setLang(lang || (deviceLang === 'en' ? 'en' : 'fr'));
  state.token = await SecureStore.getItemAsync('cv_token');
  const u = await AsyncStorage.getItem('cv_user');
  state.user = u ? JSON.parse(u) : null;
  emit();
  return { ...state };
}

export function current() { return { ...state }; }

// Pastilles des onglets : alertes non lues, paiements reçus à confirmer.
export function setCounts(c) {
  const next = { ...state.counts, ...c };
  if (next.unread === state.counts.unread && next.toConfirm === state.counts.toConfirm) return;
  state.counts = next;
  emit();
}

export async function refreshCounts() {
  if (!state.token) return;
  try {
    const [n, m] = await Promise.all([api.notifications(), api.me()]);
    setCounts({ unread: n.unread || 0, toConfirm: (m.user && m.user.paiements_a_confirmer) || 0 });
  } catch (e) { /* hors ligne : on garde les derniers chiffres */ }
}

export async function signIn(token, user) {
  state.token = token;
  state.user = user;
  await SecureStore.setItemAsync('cv_token', token);
  await AsyncStorage.setItem('cv_user', JSON.stringify(user));
  if (user.lang) await chooseLang(user.lang, false);
  emit();
}

async function signOutLocal() {
  state.token = null;
  state.user = null;
  await SecureStore.deleteItemAsync('cv_token');
  await AsyncStorage.removeItem('cv_user');
  emit();
}

export async function signOut(pushToken) {
  try { await api.logout(pushToken); } catch (e) { /* hors ligne : on deconnecte quand meme */ }
  await signOutLocal();
}

export async function deleteAccount(password) {
  // Suppression définitive du compte (exigée par l'App Store) ; la session locale est effacée ensuite.
  const r = await api.deleteAccount(password);
  await signOutLocal();
  return r;
}

export async function setServer(url) {
  state.serverUrl = url.trim().replace(/\/+$/, '');
  await AsyncStorage.setItem('cv_server', state.serverUrl);
  emit();
}

export async function chooseLang(lang, sync = true) {
  setLang(lang);
  await AsyncStorage.setItem('cv_lang', lang);
  if (sync && state.token) { try { await api.updateMe({ lang }); } catch (e) { /* plus tard */ } }
  emit();
}

export async function updateUser(user) {
  state.user = user;
  await AsyncStorage.setItem('cv_user', JSON.stringify(user));
  emit();
}

// --- Envoi d'une preuve (et file d'attente sans reseau) ---
export function buildForm(item) {
  const f = new FormData();
  const fields = proofFields({ ...item.meta, clientNow: Date.now(), offline: item.offline });
  Object.keys(fields).forEach((k) => f.append(k, fields[k]));
  f.append('photo', { uri: item.fileUri, name: item.kind === 'video' ? 'capture.mp4' : 'capture.jpg',
    type: item.kind === 'video' ? 'video/mp4' : 'image/jpeg' });
  return f;
}

export const queue = createQueue({
  load: async () => JSON.parse((await AsyncStorage.getItem('cv_queue')) || '[]'),
  save: async (items) => AsyncStorage.setItem('cv_queue', JSON.stringify(items)),
  removeFile: async (uri) => { try { await FileSystem.deleteAsync(uri, { idempotent: true }); } catch (e) { /* deja supprime */ } },
  send: async (item) => api.uploadProof(item.projectId, buildForm({ ...item, offline: true })),
});

export async function sendProof({ projectId, kind, uri, meta }) {
  try {
    return await api.uploadProof(projectId, buildForm({ kind, fileUri: uri, meta, offline: false }));
  } catch (e) {
    if (e.name !== 'NetworkError') throw e;
    // Pas de reseau : copie du fichier dans l'espace de l'application, puis mise en attente.
    await FileSystem.makeDirectoryAsync(QUEUE_DIR, { intermediates: true }).catch(() => {});
    const dest = `${QUEUE_DIR}${Date.now()}.${kind === 'video' ? 'mp4' : 'jpg'}`;
    await FileSystem.copyAsync({ from: uri, to: dest });
    // l'attestation de l'appareil exige du reseau : la preuve differee part sans elle
    const m = { ...meta, attestation: null, nonce: null };
    await queue.add({ projectId, kind, fileUri: dest, meta: m, capturedAt: meta.capturedAt });
    return { queued: true };
  }
}

export const platform = Platform.OS;
