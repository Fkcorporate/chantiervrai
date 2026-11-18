import React, { useState } from 'react';
import { Linking, Platform, Pressable } from 'react-native';
import * as Device from 'expo-device';
import { Screen, Card, T, Button, Field, Banner, BrandHeader } from '../components/ui';
import { api, signIn, current } from '../services/session';
import { t, getLang } from '../core/i18n';
import { C } from '../theme';

export default function LoginScreen({ go, reset, params }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [need2fa, setNeed2fa] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true); setError('');
    try {
      const device = `${Device.manufacturer || ''} ${Device.modelName || Platform.OS}`.trim();
      const r = await api.login(email.trim(), password, need2fa ? code : undefined, device, getLang());
      if (r.need_2fa && !r.token) { setNeed2fa(true); return; }
      await signIn(r.token, r.user);
      reset('projects');
    } catch (e) {
      if (e.body && e.body.need_2fa) setNeed2fa(true);
      setError(e.name === 'NetworkError' ? t('Pas de connexion au serveur.') : e.message);
    } finally {
      setBusy(false);
    }
  }

  const web = (path) => Linking.openURL(`${current().serverUrl}${path}?lang=${getLang()}`);
  return (
    <Screen title="" right={null}>
      <BrandHeader pitch={t('Faites construire au pays. Payez seulement ce qui est bâti.')} />
      <T bold style={{ fontSize: 26, fontWeight: '800', letterSpacing: -0.6, marginTop: 6 }} accessibilityRole="header">{t('Connexion')}</T>
      <T muted>{t('Suivez votre chantier à distance, avec des preuves vérifiées.')}</T>
      <Banner text={params && params.message} />
      <Banner text={error} tone="error" />
      <Card>
        <Field label={t('E-mail')} value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address"
          autoComplete="email" textContentType="emailAddress" />
        <Field label={t('Mot de passe')} value={password} onChangeText={setPassword} secureTextEntry
          autoComplete="password" textContentType="password" />
        {need2fa ? (
          <Field label={t('Code de double authentification')} value={code} onChangeText={setCode} keyboardType="number-pad"
            autoComplete="one-time-code" textContentType="oneTimeCode" autoFocus />
        ) : null}
        <Button title={t('Se connecter')} onPress={submit} loading={busy} disabled={!email || !password} />
      </Card>
      <Pressable onPress={() => web('/mot-de-passe-oublie')} hitSlop={8} accessibilityRole="link" style={{ alignSelf: 'center', paddingVertical: 8 }}>
        <T style={{ color: C.green, fontWeight: '700' }}>{t('Mot de passe oublié ?')}</T>
      </Pressable>
      <Button kind="ghost" title={t('Créer un compte')} onPress={() => web('/inscription')} />
      <Pressable onPress={() => go('settings')} hitSlop={8} accessibilityRole="button" style={{ alignSelf: 'center', paddingVertical: 8 }}>
        <T muted>{t('Réglages')}</T>
      </Pressable>
    </Screen>
  );
}
