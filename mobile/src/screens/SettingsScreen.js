import React, { useState } from 'react';
import { Switch } from 'react-native';
import Constants from 'expo-constants';
import { Screen, Card, T, Row, Button, Field, Banner } from '../components/ui';
import { api, current, chooseLang, deleteAccount, setServer, signOut, updateUser } from '../services/session';
import { t, getLang } from '../core/i18n';
import { C } from '../theme';

export default function SettingsScreen({ back, reset, pushToken }) {
  const st = current();
  const user = st.user;
  const [url, setUrl] = useState(st.serverUrl);
  const [phone, setPhone] = useState(user ? user.phone || '' : '');
  const [prefs, setPrefs] = useState(user ? { notify_whatsapp: !!user.notify_whatsapp, notify_sms: !!user.notify_sms, notify_email: !!user.notify_email } : {});
  const [msg, setMsg] = useState('');
  const [del, setDel] = useState(false);        // étape de confirmation de la suppression
  const [delPw, setDelPw] = useState('');
  const [delMsg, setDelMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [, force] = useState(0);

  async function save() {
    setMsg('');
    try {
      const r = await api.updateMe({ phone, ...prefs });
      await updateUser(r.user);
      setMsg(t('Enregistré.'));
    } catch (e) { setMsg(e.message); }
  }

  async function removeAccount() {
    setDelMsg('');
    if (!delPw) { setDelMsg(t('Entrez votre mot de passe pour confirmer.')); return; }
    setBusy(true);
    try {
      await deleteAccount(delPw);
      reset('login', { message: t('Votre compte a été supprimé et vos données personnelles effacées.') });
    } catch (e) {
      setDelMsg(e.message);
    } finally { setBusy(false); }
  }

  return (
    <Screen title={t('Réglages')} onBack={back}>
      <Banner text={msg} />
      <Card>
        <T bold>{t('Langue')}</T>
        <Row>
          <Button small kind={getLang() === 'fr' ? 'primary' : 'ghost'} title="Français" onPress={async () => { await chooseLang('fr'); force((x) => x + 1); }} />
          <Button small kind={getLang() === 'en' ? 'primary' : 'ghost'} title="English" onPress={async () => { await chooseLang('en'); force((x) => x + 1); }} />
        </Row>
      </Card>
      {user ? (
        <Card>
          <T bold>{t('Compte')}</T>
          <T muted>{user.name} · {user.email}</T>
          <Field label={t('Téléphone (WhatsApp, Mobile Money)')} value={phone} onChangeText={setPhone} keyboardType="phone-pad" />
          {[['notify_whatsapp', 'Me prévenir par WhatsApp'], ['notify_sms', 'Me prévenir par SMS'], ['notify_email', 'Me prévenir par e-mail']].map(([k, label]) => (
            <Row key={k}><T style={{ flex: 1 }}>{t(label)}</T>
              <Switch value={!!prefs[k]} onValueChange={(v) => setPrefs({ ...prefs, [k]: v })} trackColor={{ true: C.green }} /></Row>
          ))}
          <Button title={t('Enregistrer')} onPress={save} />
          <Button kind="ghost" title={t('Se déconnecter')} onPress={async () => { await signOut(pushToken); reset('login'); }} />
        </Card>
      ) : null}
      {user ? (
        <Card>
          <T bold>{t('Supprimer mon compte')}</T>
          {!del ? (
            <>
              <T muted>{t('Vos données personnelles sont effacées et vous ne pourrez plus vous connecter. Les chantiers partagés avec d\'autres personnes restent visibles pour elles, sans votre nom.')}</T>
              <Button kind="ghost" title={t('Supprimer mon compte')} onPress={() => setDel(true)} />
            </>
          ) : (
            <>
              <Banner text={delMsg} tone="error" />
              <T>{t('Cette action est définitive. Confirmez avec votre mot de passe.')}</T>
              <Field label={t('Mot de passe')} value={delPw} onChangeText={setDelPw} secureTextEntry autoCapitalize="none" />
              <Button kind="orange" title={t('Supprimer définitivement')} onPress={removeAccount} disabled={busy} loading={busy} />
              <Button kind="ghost" small title={t('Annuler')} onPress={() => { setDel(false); setDelPw(''); setDelMsg(''); }} />
            </>
          )}
        </Card>
      ) : null}
      <Card>
        <Field label={t('Adresse du serveur')} value={url} onChangeText={setUrl} autoCapitalize="none" keyboardType="url" />
        <Button kind="ghost" small title={t('Enregistrer')} onPress={async () => { await setServer(url); setMsg(t('Enregistré.')); }} />
      </Card>
      <T muted>{t('Version')} {Constants.expoConfig ? Constants.expoConfig.version : ''}</T>
    </Screen>
  );
}
