import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ApiClient, ApiError, apiBase, photoURL, measurement } from '../api.mjs';
import { ReviewController } from '../controller.mjs';
import { FixtureClient } from '../fixture.mjs';
const fixture = JSON.parse(readFileSync(new URL('../fixtures.json', import.meta.url)));
const setup = () => { const client = new FixtureClient(fixture); client.read = async v => structuredClone(v);
  return { client, controller: new ReviewController(client) }; };
async function ready() { const s = setup(); await s.controller.refresh();
  await s.controller.select(fixture.pending_response.ticket_id); return s; }

test('pending receipt does not mutate shared map; unknown stays unknown', async () => {
  const { controller } = await ready();
  assert.equal(controller.state.selected.status, 'PENDING');
  assert.equal(controller.state.map.version, 1);
  assert.equal(controller.state.map.edges[1].blocked, false);
  assert.equal(measurement(null), 'Unknown'); assert.equal(measurement(undefined), 'Unknown');
  assert.equal(measurement(0), '0 m');
});
test('approve uses contract ticket route body and fetches authoritative map', async () => {
  const { controller } = await ready(); await controller.decide('APPROVE', 'Reviewed');
  assert.equal(controller.state.selected.status, 'APPROVED');
  assert.equal(controller.state.selected.review.reviewer_id, 'fixture-reviewer');
  assert.equal(controller.state.map.version, 2); assert.equal(controller.state.map.edges[1].blocked, true);
  assert.equal(controller.state.items.length, 0); assert.equal(controller.state.stale, false);
});
test('rejection creates no closure and does not increment map version', async () => {
  const { controller } = await ready(); await controller.decide('REJECT');
  assert.equal(controller.state.selected.status, 'REJECTED');
  assert.equal(controller.state.map.version, 1); assert.equal(controller.state.map.edges[1].blocked, false);
});
test('request in flight cannot make a second decision or optimistic status change', async () => {
  const { client, controller } = await ready(); let resolve; let calls = 0;
  const original = client.review.bind(client);
  client.review = async (...args) => { calls++; await new Promise(r => { resolve = r; }); return original(...args); };
  const pending = controller.decide('APPROVE');
  assert.equal(controller.state.busy, true); assert.equal(controller.state.selected.status, 'PENDING');
  await controller.decide('REJECT'); assert.equal(calls, 1);
  resolve(); await pending; assert.equal(controller.state.selected.status, 'APPROVED');
});
test('lost review response retries exactly the same body without another map increment', async () => {
  const { client, controller } = await ready(); const original = client.review.bind(client); const bodies = [];
  client.review = async (id, body) => { bodies.push(structuredClone(body)); const response = await original(id, body);
    if (bodies.length === 1) throw new ApiError(0, 'Response lost'); return response; };
  await controller.decide('APPROVE', 'same notes');
  assert.equal(controller.state.selected.status, 'PENDING'); assert.ok(controller.state.retry);
  assert.equal(controller.state.stale, true);
  await controller.decide('REJECT', 'different'); assert.equal(bodies.length, 1);
  await controller.decide(null, '', true);
  assert.deepEqual(bodies[0], bodies[1]); assert.equal(controller.state.map.version, 2);
});
test('refresh reconciles a review whose response was lost', async () => {
  const { client, controller } = await ready(); const original = client.review.bind(client);
  client.review = async (...args) => { await original(...args); throw new ApiError(0, 'Lost'); };
  await controller.decide('REJECT'); await controller.refresh();
  assert.equal(controller.state.retry, null); assert.equal(controller.state.selected.status, 'REJECTED');
});
test('409 requires refresh and a deliberate new decision; no automatic resubmit', async () => {
  const { client, controller } = await ready(); let calls = 0;
  client.review = async () => { calls++; throw new ApiError(409, 'Refresh required'); };
  await controller.decide('APPROVE'); assert.equal(controller.state.stale, true);
  await controller.decide('APPROVE'); assert.equal(calls, 1);
  assert.equal(controller.state.selected.status, 'PENDING');
});
test('saved review plus map fetch failure shows confirmed review and stale map', async () => {
  const { client, controller } = await ready(); client.map = async () => { throw new Error('offline'); };
  await controller.decide('APPROVE'); assert.equal(controller.state.selected.status, 'APPROVED');
  assert.equal(controller.state.map.version, 1); assert.equal(controller.state.stale, true);
  assert.match(controller.state.error, /Review was saved/);
});
test('refresh failure preserves last map as stale and blocks decisions', async () => {
  const { client, controller } = await ready(); client.health = async () => { throw new ApiError(0, 'offline'); };
  await controller.refresh(); assert.equal(controller.state.map.version, 1);
  assert.equal(controller.state.stale, true); await controller.decide('APPROVE');
  assert.equal(controller.state.selected.status, 'PENDING');
});
test('unsupported ticket and review responses cannot invent approval', async () => {
  const { client, controller } = await ready();
  client.review = async () => ({ report: { ...fixture.pending_response, status: 'APPROVED', ticket_id: 'wrong' }, map_version: 2 });
  await controller.decide('APPROVE'); assert.equal(controller.state.selected.status, 'PENDING');
  assert.ok(controller.state.retry); assert.match(controller.state.error, /not understood/);
});
test('real client uses reviewer bearer on API only; no caller-supplied reviewer identity', async () => {
  const requests = [];
  const api = new ApiClient('https://api.example/api/v2/', 'reviewer-token', async (url, options) => {
    requests.push({ url, options }); return { ok: true, json: async () => fixture.review_response }; });
  await api.review(fixture.pending_response.ticket_id, fixture.review_request);
  assert.match(requests[0].url, /\/api\/v2\/tickets\/T-.*\/review$/);
  assert.equal(requests[0].options.headers.Authorization, 'Bearer reviewer-token');
  assert.equal(requests[0].options.credentials, 'omit'); assert.equal(requests[0].options.redirect, 'error');
  assert.equal(JSON.parse(requests[0].options.body).reviewer_id, undefined);
});
test('unsafe API and image addresses are refused', () => {
  for (const value of ['http://remote.example/api/v2', 'https://user:pass@example.com/api/v2', 'https://example.com/api/v1',
    'https://example.com/api/v2?token=secret']) assert.throws(() => apiBase(value));
  assert.equal(apiBase('http://127.0.0.1:8002/api/v2'), 'http://127.0.0.1:8002/api/v2');
  assert.throws(() => photoURL('javascript:alert(1)', 'https://api.example/api/v2'));
  assert.throws(() => photoURL('http://other.example/photo.jpg', 'https://api.example/api/v2'));
  assert.throws(() => new ApiClient('https://api.example/api/v2', ''));
});
test('default fetch preserves the browser global receiver', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = function () {
    assert.equal(this, globalThis);
    return Promise.resolve({ ok: true, json: async () => ({ status: 'healthy' }) });
  };
  try { assert.equal((await new ApiClient('http://127.0.0.1:8002/api/v2', '').health()).status, 'healthy'); }
  finally { globalThis.fetch = original; }
});
test('auth and image-retention errors are clear; server secrets are not echoed', async () => {
  for (const status of [401, 403, 409, 410, 429, 503]) {
    const api = new ApiClient('https://api.example/api/v2', 'token', async () => ({ ok: false, status,
      json: async () => ({ detail: 'secret signed URL' }) }));
    await assert.rejects(api.health(), error => error.status === status && !error.message.includes('secret'));
  }
});
test('pagination is encoded, pages deduplicated and filtered statuses retained', async () => {
  const { client, controller } = await ready();
  client.tickets = async () => ({ items: [fixture.pending_response], next_cursor: 'REPORT#next' });
  await controller.refresh('PENDING', true); assert.equal(controller.state.items.length, 1);
  let requested;
  const api = new ApiClient('https://api.example/api/v2', 'token', async url => {
    requested = url; return { ok: true, json: async () => ({ items: [] }) }; });
  await api.tickets('PENDING', 'REPORT#next'); assert.match(requested, /cursor=REPORT%23next/);
});
test('fixture reset isolates rejection from an earlier approved case', async () => {
  const a = await ready(); await a.controller.decide('APPROVE');
  const b = await ready(); await b.controller.decide('REJECT');
  assert.equal(a.controller.state.map.version, 2); assert.equal(b.controller.state.map.version, 1);
});
