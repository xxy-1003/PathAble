import { UserManager, WebStorageStateStore, InMemoryWebStorage } from './vendor/oidc-client.mjs';
import { apiBase } from './api.mjs';

export const ROLE_SCOPES = Object.freeze({
  reviewer: 'openid pathable/reviewer pathable/map',
  camera: 'openid pathable/camera pathable/map',
});

export function authConfig(value) {
  if (!value || !/^https:\/\/cognito-idp\.ap-southeast-2\.amazonaws\.com\/ap-southeast-2_[a-zA-Z0-9]+$/.test(value.issuer) ||
      !/^[a-z0-9]{1,128}$/.test(value.clientId) || value.issuer.includes('REPLACE')) {
    throw new Error('Application sign-in is not configured. Set the public Cognito settings first.');
  }
  const origin = new URL(value.loginOrigin);
  if (origin.href !== origin.origin + '/' || origin.username || origin.password ||
      (origin.protocol !== 'https:' && !(origin.protocol === 'http:' && origin.hostname === 'localhost'))) {
    throw new Error('Sign-in requires an HTTPS origin or http://localhost for local development.');
  }
  return { issuer: value.issuer, clientId: value.clientId, loginOrigin: origin.origin,
    apiBase: value.apiBase ? apiBase(value.apiBase) : '' };
}

export function managerSettings(config, sessionStore, memoryStore) {
  return {
    authority: config.issuer, client_id: config.clientId,
    redirect_uri: config.loginOrigin + '/callback.html',
    response_type: 'code', response_mode: 'query', scope: ROLE_SCOPES.reviewer,
    disablePKCE: false, automaticSilentRenew: false, monitorSession: false,
    loadUserInfo: false, staleStateAgeInSeconds: 900,
    // Only the short-lived PKCE/state/nonce transaction survives the redirect.
    stateStore: new WebStorageStateStore({ store: sessionStore, prefix: 'pathable.oidc.' }),
    // Access/ID/refresh tokens stay in memory. No browser storage holds a session.
    userStore: new WebStorageStateStore({ store: memoryStore, prefix: 'pathable.user.' }),
  };
}

export function validateSession(user) {
  const role = user?.state?.role;
  if (!ROLE_SCOPES[role] || user.expired || !user.access_token || user.token_type?.toLowerCase() !== 'bearer' ||
      !ROLE_SCOPES[role].split(' ').filter(s => s.startsWith('pathable/')).every(s => user.scopes.includes(s))) {
    throw new Error('Sign-in did not provide the requested PathAble permissions.');
  }
  return { role, user };
}

export function reviewerToken(session, configuredBase, requestedBase) {
  if (!session || session.role !== 'reviewer' || session.user.expired) return '';
  if (!configuredBase || apiBase(requestedBase) !== configuredBase) {
    throw new Error('Signed-in credentials can only be sent to the configured backend API.');
  }
  return session.user.access_token;
}

export function createAuth(config, sessionStore = window.sessionStorage) {
  const manager = new UserManager(managerSettings(config, sessionStore, new InMemoryWebStorage()));
  return {
    manager,
    async signIn(role) {
      if (!ROLE_SCOPES[role]) throw new Error('Choose reviewer or camera sign-in.');
      await manager.clearStaleState();
      await manager.signinRedirect({ scope: ROLE_SCOPES[role], nonce: crypto.randomUUID(), state: { role }, prompt: 'login' });
    },
    async complete(url) {
      const user = await manager.signinRedirectCallback(url);
      try { return validateSession(user); }
      catch (error) { await manager.removeUser(); throw error; }
    },
    async forget() { await manager.removeUser(); },
  };
}
