// Application ChantierVrai (Android et iPhone).
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, AppState, BackHandler, Platform, View } from 'react-native';
import Constants from 'expo-constants';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import NetInfo from '@react-native-community/netinfo';
import * as Notifications from 'expo-notifications';
import { restore, subscribe, current, queue, api } from './src/services/session';
import { registerPush } from './src/services/device';
import LoginScreen from './src/screens/LoginScreen';
import ProjectsScreen from './src/screens/ProjectsScreen';
import ProjectScreen from './src/screens/ProjectScreen';
import CaptureScreen from './src/screens/CaptureScreen';
import NotificationsScreen from './src/screens/NotificationsScreen';
import SettingsScreen from './src/screens/SettingsScreen';
import OrderScreen from './src/screens/OrderScreen';
import PaymentsScreen from './src/screens/PaymentsScreen';
import { C } from './src/theme';
import { t } from './src/core/i18n';

const SCREENS = { login: LoginScreen, projects: ProjectsScreen, project: ProjectScreen, capture: CaptureScreen,
  notifications: NotificationsScreen, settings: SettingsScreen, order: OrderScreen, payments: PaymentsScreen };

export default function App() {
  const [ready, setReady] = useState(false);
  const [stack, setStack] = useState([{ name: 'login', params: {} }]);
  const [pushToken, setPushToken] = useState(null);
  const [, setTick] = useState(0);
  const stackRef = useRef(stack);
  stackRef.current = stack;

  // Navigation simple : une pile d'ecrans
  const go = (name, params = {}, replace = false) => setStack((s) => {
    if (replace) {
      const i = s.map((x) => x.name).lastIndexOf(name);
      if (i >= 0) return [...s.slice(0, i), { name, params }];
    }
    return [...s, { name, params }];
  });
  const back = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));
  const reset = (name, params = {}) => setStack([{ name, params }]);

  useEffect(() => {
    restore().then((st) => {
      setStack([{ name: st.token ? 'projects' : 'login', params: {} }]);
      setReady(true);
    });
    const unsub = subscribe((st) => {
      setTick((x) => x + 1);
      if (!st.token && stackRef.current[stackRef.current.length - 1].name !== 'login') setStack([{ name: 'login', params: {} }]);
    });
    const hw = BackHandler.addEventListener('hardwareBackPress', () => {
      if (stackRef.current.length > 1) { back(); return true; }
      return false;
    });
    // Envoi des preuves en attente au retour du reseau, ou quand l'application revient au premier plan
    const flush = () => { if (current().token) queue.flush().catch(() => {}); };
    const net = NetInfo.addEventListener((s) => { if (s.isConnected && s.isInternetReachable !== false) flush(); });
    const app = AppState.addEventListener('change', (s) => { if (s === 'active') flush(); });
    // Toucher une notification ouvre le chantier concerne
    const tap = Notifications.addNotificationResponseReceivedListener((r) => {
      const d = r.notification.request.content.data || {};
      if (typeof d.link === 'string' && d.link.startsWith('/paiements')) go('payments');
      else if (d.project_id) go('project', { id: d.project_id });
    });
    return () => { unsub(); hw.remove(); net(); app.remove(); tap.remove(); };
  }, []);

  // Enregistrement du telephone pour les notifications, une fois connecte
  const token = current().token;
  useEffect(() => {
    if (!token) return;
    registerPush().then((pt) => {
      if (pt) { setPushToken(pt); api.registerDevice(pt, Platform.OS).catch(() => {}); }
    }).catch(() => {});
    api.version().then((v) => {
      // version minimale imposee par le serveur (mise a jour obligatoire)
      const need = (v.min_app_version || '0').split('.').map(Number);
      const have = ((Constants.expoConfig && Constants.expoConfig.version) || '0').split('.').map(Number);
      for (let i = 0; i < 3; i++) {
        if ((have[i] || 0) > (need[i] || 0)) break;
        if ((have[i] || 0) < (need[i] || 0)) { Alert.alert(t('Cette version de l\'application est trop ancienne. Mettez-la à jour depuis le store.')); break; }
      }
    }).catch(() => {});
  }, [token]);

  if (!ready) {
    return <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: C.bg }}><ActivityIndicator color={C.green} /></View>;
  }
  const top = stack[stack.length - 1];
  const Screen = SCREENS[top.name];
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <Screen key={`${top.name}-${stack.length}-${JSON.stringify(top.params)}`} params={top.params} go={go} back={back} reset={reset}
        pushToken={pushToken} />
    </SafeAreaProvider>
  );
}
