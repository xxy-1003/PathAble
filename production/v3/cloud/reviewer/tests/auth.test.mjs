import test from 'node:test';
import assert from 'node:assert/strict';
import { authConfig, managerSettings, validateSession, reviewerToken, ROLE_SCOPES } from '../auth.mjs';
import { InMemoryWebStorage } from '../vendor/oidc-client.mjs';

const config = authConfig({ issuer: 'https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_example',
  clientId: 'publicclient123', loginOrigin: 'http://localhost:8003', apiBase: 'https://api.example/api/v2' });
const user = (role = 'reviewer') => ({ state: { role }, access_token: 'test-token', token_type: 'Bearer',
  scopes: ROLE_SCOPES[role].split(' '), expired: false });

test('public-client sign-in uses code, PKCE and the exact callback without a secret', () => {
  const settings = managerSettings(config, new InMemoryWebStorage(), new InMemoryWebStorage());
  assert.equal(settings.response_type, 'code'); assert.equal(settings.disablePKCE, false);
  assert.equal(settings.redirect_uri, 'http://localhost:8003/callback.html');
  assert.equal(settings.client_secret, undefined); assert.equal(settings.automaticSilentRenew, false);
});
test('sign-in transaction and token stores are separate; tokens stay in ephemeral memory', async () => {
  const browserTransaction = new InMemoryWebStorage();
  const settings = managerSettings(config, browserTransaction, new InMemoryWebStorage());
  await settings.stateStore.set('transaction', 'pkce-state');
  await settings.userStore.set('session', 'token-memory-only');
  assert.equal(browserTransaction.length, 1);
  assert.ok(!await settings.stateStore.get('session'));
  const reloaded = managerSettings(config, browserTransaction, new InMemoryWebStorage());
  assert.ok(!await reloaded.userStore.get('session'));
  assert.equal(await reloaded.stateStore.get('transaction'), 'pkce-state');
});
test('callback requires a known role and its requested scopes', () => {
  assert.equal(validateSession(user()).role, 'reviewer');
  assert.equal(validateSession(user('camera')).role, 'camera');
  assert.throws(() => validateSession({ ...user(), state: { role: 'admin' } }));
  assert.throws(() => validateSession({ ...user(), scopes: ['openid', 'pathable/map'] }));
});
test('expired or invalid callback tokens are not accepted', () => {
  assert.throws(() => validateSession({ ...user(), expired: true }));
  assert.throws(() => validateSession({ ...user(), access_token: '' }));
  assert.throws(() => validateSession({ ...user(), token_type: 'other' }));
});
test('reviewer token is sent only to the pinned API; camera tokens never become reviewer credentials', () => {
  const session = validateSession(user());
  assert.equal(reviewerToken(session, config.apiBase, config.apiBase), 'test-token');
  assert.throws(() => reviewerToken(session, config.apiBase, 'https://other.example/api/v2'));
  assert.throws(() => reviewerToken(session, '', config.apiBase));
  assert.equal(reviewerToken(validateSession(user('camera')), config.apiBase, config.apiBase), '');
});
test('configuration refuses insecure origins, invalid client ids and other identity regions', () => {
  for (const loginOrigin of ['http://remote.example', 'https://site.example/path', 'https://user:pass@site.example']) {
    assert.throws(() => authConfig({ ...config, loginOrigin }));
  }
  assert.throws(() => authConfig({ ...config, clientId: '<client secret>' }));
  assert.throws(() => authConfig({ ...config, issuer: config.issuer.replace('ap-southeast-2', 'us-east-1') }));
});
