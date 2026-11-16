// Client de l'API ChantierVrai (/api/v1). Sans dependance a React Native : teste avec Node.

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body || {};
  }
}

export class NetworkError extends Error {
  constructor(message) {
    super(message);
    this.name = 'NetworkError';
  }
}

export function createApi({ baseUrl, getToken, onUnauthorized, fetchImpl, lang }) {
  const doFetch = fetchImpl || ((...a) => fetch(...a));
  const root = () => (typeof baseUrl === 'function' ? baseUrl() : baseUrl).replace(/\/+$/, '');

  async function request(method, path, { json, form, auth = true } = {}) {
    const headers = { Accept: 'application/json' };
    const l = typeof lang === 'function' ? lang() : lang;
    if (l) headers['Accept-Language'] = l;
    const token = auth ? await getToken() : null;
    if (token) headers.Authorization = `Bearer ${token}`;
    let body;
    if (json !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(json);
    } else if (form) {
      body = form;               // FormData : le type multipart est ajoute automatiquement
    }
    let res;
    try {
      res = await doFetch(root() + path, { method, headers, body });
    } catch (e) {
      throw new NetworkError(e && e.message ? e.message : 'network');
    }
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    if (res.status === 401 && auth && onUnauthorized && !data.need_2fa) onUnauthorized();
    if (!res.ok) {
      const msg = data.error || (data.messages && data.messages.join(' ')) || `HTTP ${res.status}`;
      throw new ApiError(msg, res.status, data);
    }
    return data;
  }

  return {
    request,
    url: (path) => root() + path,
    login: (email, password, code, device, language) =>
      request('POST', '/api/v1/connexion', { json: { email, password, code, device, lang: language }, auth: false }),
    logout: (pushToken) => request('POST', '/api/v1/deconnexion', { json: { push_token: pushToken || null } }),
    me: () => request('GET', '/api/v1/moi'),
    deleteAccount: (password) => request('POST', '/api/v1/compte/supprimer', { json: { password } }),
    updateMe: (fields) => request('PUT', '/api/v1/moi', { json: fields }),
    projects: () => request('GET', '/api/v1/chantiers'),
    project: (id) => request('GET', `/api/v1/chantiers/${id}`),
    joinProject: (code) => request('POST', '/api/v1/rejoindre', { json: { code } }),
    attestationNonce: () => request('POST', '/api/v1/attestation/defi'),
    uploadProof: (projectId, form) => request('POST', `/api/v1/chantiers/${projectId}/preuves`, { form }),
    stepAction: (projectId, stepId, action, fields) =>
      request('POST', `/api/v1/chantiers/${projectId}/etapes/${stepId}/${action}`, { json: fields || {} }),
    orders: () => request('GET', '/api/v1/commandes'),
    orderAction: (orderId, action, fields) =>
      request('POST', `/api/v1/commandes/${orderId}/${action}`, { json: fields || {} }),
    uploadDelivery: (orderId, form) => request('POST', `/api/v1/commandes/${orderId}/livraison`, { form }),
    payments: () => request('GET', '/api/v1/paiements'),
    paymentOrder: (kind, id) => request('GET', `/api/v1/paiements/${kind}/${id}`),
    declarePayment: (kind, id, fields) => request('POST', `/api/v1/paiements/${kind}/${id}`, { json: fields }),
    answerPayment: (rid, action, text) => request('POST', `/api/v1/paiements/recus/${rid}`, { json: { action, text: text || '' } }),
    notifications: () => request('GET', '/api/v1/notifications'),
    markRead: () => request('POST', '/api/v1/notifications'),
    registerDevice: (pushToken, platform) =>
      request('POST', '/api/v1/appareils', { json: { push_token: pushToken, platform } }),
    version: () => request('GET', '/api/v1/version', { auth: false }),
  };
}

// Champs du formulaire d'une preuve (les memes que la version web, capture = « native »)
export function proofFields({ captureToken, capturedAt, clientNow, coords, note, platform, attestation, nonce,
  offline, inspectionId }) {
  const f = {
    capture: 'native',
    capture_token: captureToken,
    captured_at: String(Math.round(capturedAt)),
    client_now: String(Math.round(clientNow)),
    tz_offset: String(new Date().getTimezoneOffset()),
    note: note || '',
    platform: platform || '',
    offline: offline ? '1' : '0',
  };
  if (coords) {
    f.lat = String(coords.latitude);
    f.lng = String(coords.longitude);
    if (coords.accuracy != null) f.acc = String(Math.round(coords.accuracy));
    if (coords.mocked) f.mocked = '1';
  }
  if (attestation && nonce) {
    f.attestation = attestation;
    f.attestation_nonce = nonce;
  }
  if (inspectionId) f.inspection_id = String(inspectionId);
  return f;
}
