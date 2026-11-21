// Couleurs et tailles, identiques à la version web. Trois thèmes, comme sur le site :
// « Ivoire » (fond chaud, par défaut), « Blanc » (blanc pur) et « Nuit » (sombre, doré pour décider).
// Les styles sont calculés au démarrage : un changement de thème s'applique au prochain lancement.
const IVOIRE = {
  bg: '#F6F4EF',
  forest: '#0B2219',
  forest2: '#16382A',
  mint: '#A9C2B5',
  warm: '#F08A4B',
  gold: '#C9A46A',
  goldSoft: '#F3ECDD',
  goldInk: '#2B2008',
  goldText: '#7A5C22',
  accentFill: '#1F7A4D',
  card: '#FFFFFF',
  text: '#111A15',
  muted: '#5F6662',
  green: '#1F7A4D',
  greenSoft: '#E4F1EA',
  orange: '#B4501F',
  orangeSoft: '#FDEBDD',
  amberSoft: '#FBF0D2',
  amber: '#7A5A0B',
  line: '#ECE8DF',
  border: '#DCD6CA',
  bubbleThem: '#FFFFFF',
  bubbleMe: '#0F3324',
  bubbleMeText: '#FFFFFF',
  dark: false,
};

const BLANC = { ...IVOIRE, bg: '#FFFFFF', card: '#FFFFFF', line: '#EDEDEB', border: '#E3E3E0', goldSoft: '#F7F2E7', bubbleThem: '#F2F2EF' };

const NUIT = {
  ...IVOIRE,
  bg: '#070F0B',
  forest: '#123326',
  forest2: '#1A4433',
  card: '#0E1914',
  text: '#ECE8DD',
  muted: '#93A69D',
  green: '#74DBA8',
  greenSoft: '#11271C',
  orange: '#F3A188',
  orangeSoft: '#2A1912',
  amberSoft: '#251F14',
  amber: '#F2B872',
  goldSoft: '#251F14',
  goldText: '#E3C48E',
  line: 'rgba(255,255,255,0.08)',
  border: '#24342C',
  bubbleThem: '#14211B',
  bubbleMe: '#D6B57D',
  bubbleMeText: '#0B2219',
  dark: true,
};

export const THEMES = { ivoire: IVOIRE, blanc: BLANC, nuit: NUIT };
export const THEME_NAMES = ['ivoire', 'blanc', 'nuit'];

// Objet partagé par tous les écrans : rempli avant le premier rendu (voir index.js).
export const C = { ...IVOIRE };
export let themeName = 'ivoire';

export function applyTheme(name) {
  themeName = THEMES[name] ? name : 'ivoire';
  Object.assign(C, THEMES[themeName]);
  return themeName;
}

export const R = { card: 22, btn: 999, pill: 999 };
