// Prise de vue dans l'application : pas d'acces a la galerie. L'heure de prise, la position
// et le jeton de capture du serveur sont joints a la photo.
import React, { useEffect, useRef, useState } from 'react';
import { Image, StyleSheet, View } from 'react-native';
import { CameraView, useCameraPermissions, useMicrophonePermissions } from 'expo-camera';
import { Screen, Card, T, Button, Field, Banner } from '../components/ui';
import { api, sendProof, platform, buildForm } from '../services/session';
import { getPosition, attest } from '../services/device';
import { t } from '../core/i18n';

export default function CaptureScreen({ back, go, params }) {
  const { project, mode, inspectionId, order } = params;   // order : photo de livraison du fournisseur
  const cam = useRef(null);
  const [perm, requestPerm] = useCameraPermissions();
  const [micPerm, requestMic] = useMicrophonePermissions();
  const [coords, setCoords] = useState(null);
  const [gpsMsg, setGpsMsg] = useState(t('Recherche de votre position…'));
  const [shot, setShot] = useState(null);             // { uri, kind, capturedAt }
  const [recording, setRecording] = useState(false);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [nonce, setNonce] = useState(null);

  async function locate() {
    const c = await getPosition();
    setCoords(c);
    setGpsMsg(c ? t('Position : précision %(n)s m', { n: Math.round(c.accuracy || 0) }) : t('Position refusée : la preuve sera refusée.'));
  }
  useEffect(() => {
    locate();
    api.attestationNonce().then((r) => setNonce({ value: r.nonce, at: Date.now() })).catch(() => {});
  }, []);

  if (!perm || !perm.granted || (mode === 'video' && (!micPerm || !micPerm.granted))) {
    return (
      <Screen title={t('Prendre une photo')} onBack={back}>
        <Card>
          <T>{t('Autorisez la caméra pour prendre les preuves.')}</T>
          <Button title={t('Autoriser')} onPress={async () => { await requestPerm(); if (mode === 'video') await requestMic(); }} />
        </Card>
      </Screen>
    );
  }

  async function takePicture() {
    const capturedAt = Date.now();
    const r = await cam.current.takePictureAsync({ quality: 0.85, exif: true, skipProcessing: false });
    setShot({ uri: r.uri, kind: 'photo', capturedAt });
    locate();
  }

  async function toggleVideo() {
    if (recording) { cam.current.stopRecording(); return; }
    const capturedAt = Date.now();
    setRecording(true);
    try {
      const r = await cam.current.recordAsync({ maxDuration: 90 });
      setShot({ uri: r.uri, kind: 'video', capturedAt });
    } finally {
      setRecording(false);
      locate();
    }
  }

  async function send() {
    setBusy(true); setError('');
    try {
      const fresh = nonce && Date.now() - nonce.at < 25 * 60 * 1000 ? nonce.value : null;
      const attestation = fresh ? await attest(fresh) : null;
      if (order) {
        // Livraison : envoi direct (le fournisseur est sur le terrain, la preuve doit partir maintenant)
        const meta = { captureToken: order.capture_token, capturedAt: shot.capturedAt, coords, note, platform,
          attestation, nonce: attestation ? fresh : null };
        try {
          const r = await api.uploadDelivery(order.id, buildForm({ kind: shot.kind, fileUri: shot.uri, meta, offline: false }));
          go('order', { order: { ...order, status: 'livree' }, message: (r.messages || []).join(' ') }, true);
        } catch (e) {
          setError(e.name === 'NetworkError' ? t('Pas de connexion au serveur.') : e.message);
          setShot(null);
        }
        return;
      }
      const r = await sendProof({
        projectId: project.id, kind: shot.kind, uri: shot.uri,
        meta: { captureToken: project.capture_token, capturedAt: shot.capturedAt, coords, note, platform,
          attestation, nonce: attestation ? fresh : null, inspectionId },
      });
      if (r.queued) {
        go('project', { id: project.id, message: t('Pas de réseau : preuve gardée sur le téléphone. Elle partira toute seule au retour du réseau.') }, true);
      } else if (r.ok) {
        go('project', { id: project.id, message: t('Preuve vérifiée et envoyée au propriétaire.') }, true);
      } else {
        setError(`${t('Preuve refusée')} : ${(r.reasons || []).join(' ; ')}`);
        setShot(null);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (shot) {
    return (
      <Screen title={mode === 'video' ? t('Vidéo') : t('Prendre une photo')} onBack={() => setShot(null)}>
        {shot.kind === 'photo' ? <Image source={{ uri: shot.uri }} style={s.preview} resizeMode="cover" /> : <Card><T>▶ {t('Vidéo')}</T></Card>}
        <T muted>{gpsMsg}</T>
        <Banner text={error} tone="error" />
        <Field label={t('Description (facultatif)')} value={note} onChangeText={setNote} />
        <Button title={busy ? t('Envoi…') : t('Envoyer la preuve')} onPress={send} loading={busy} />
        <Button kind="ghost" title={t('Reprendre')} onPress={() => setShot(null)} disabled={busy} />
      </Screen>
    );
  }

  return (
    <Screen title={project.name} onBack={back} scroll={false}>
      <View style={s.camBox}>
        <CameraView ref={cam} style={s.cam} facing="back" mode={mode === 'video' ? 'video' : 'picture'} />
      </View>
      <T muted>{gpsMsg}</T>
      <Banner text={error} tone="error" />
      {mode === 'video'
        ? <Button kind="orange" title={recording ? t('Arrêter') : t('Filmer (90 s max)')} onPress={toggleVideo} />
        : <Button kind="orange" title={t('Prendre une photo')} onPress={takePicture} />}
    </Screen>
  );
}

const s = StyleSheet.create({
  camBox: { flex: 1, borderRadius: 16, overflow: 'hidden', backgroundColor: '#000', minHeight: 300 },
  cam: { flex: 1 },
  preview: { width: '100%', aspectRatio: 0.75, borderRadius: 16, backgroundColor: '#D9D4CA' },
});
