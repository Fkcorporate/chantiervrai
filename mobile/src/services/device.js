// Position, notifications sur le telephone, attestation de l'appareil.
import * as Location from 'expo-location';
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import Constants from 'expo-constants';
import { Platform } from 'react-native';

export async function getPosition() {
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== 'granted') return null;
  try {
    const p = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
    // Android signale les positions simulees (applications de « faux GPS »)
    if (p.mocked) return { ...p.coords, mocked: true };
    return p.coords;
  } catch (e) {
    const last = await Location.getLastKnownPositionAsync({ maxAge: 60000 });
    return last ? last.coords : null;
  }
}

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: true }),
});

export async function registerPush() {
  if (!Device.isDevice) return null;
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', { name: 'ChantierVrai', importance: Notifications.AndroidImportance.HIGH });
  }
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== 'granted') ({ status } = await Notifications.requestPermissionsAsync());
  if (status !== 'granted') return null;
  const projectId = Constants.expoConfig && Constants.expoConfig.extra && Constants.expoConfig.extra.eas
    && Constants.expoConfig.extra.eas.projectId;
  if (!projectId) return null;           // renseigne par « eas init »
  const { data } = await Notifications.getExpoPushTokenAsync({ projectId });
  return data;
}

// Attestation de l'appareil (Play Integrity sur Android, App Attest sur iPhone).
// A brancher avec un module natif : voir mobile/README.md, section « Attestation ».
// Tant qu'il n'est pas branche, les preuves sont marquees « attestation absente » sur le serveur,
// sans etre refusees.
export async function attest(nonce) { // eslint-disable-line no-unused-vars
  return null;
}
