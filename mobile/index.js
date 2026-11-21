// Point d'entrée : on lit le thème choisi (Ivoire, Blanc, Nuit) AVANT de charger les écrans,
// car leurs styles sont calculés une fois, au chargement.
import React, { useEffect, useState } from 'react';
import { View } from 'react-native';
import { registerRootComponent } from 'expo';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { applyTheme, C } from './src/theme';

function Boot() {
  const [App, setApp] = useState(null);
  useEffect(() => {
    AsyncStorage.getItem('cv_theme').catch(() => null).then((name) => {
      applyTheme(name || 'ivoire');
      setApp(() => require('./App').default);   // chargé seulement maintenant, avec les bonnes couleurs
    });
  }, []);
  return App ? <App /> : <View style={{ flex: 1, backgroundColor: C.bg }} />;
}

registerRootComponent(Boot);
