// Explicitly localhost only. Requires local_contract_server.py; creates synthetic test records.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { ApiClient } from '../api.mjs';
import { ReviewController } from '../controller.mjs';
const base = 'http://127.0.0.1:8002/api/v2';
const fixtures = JSON.parse(readFileSync(new URL('../fixtures.json', import.meta.url)));
async function post(path, body, expected = 201) {
  const response = await fetch(base + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  assert.equal(response.status, expected); return response.json();
}
const api = new ApiClient(base, '');
const before = await api.map();
const photo = await post('/photos', { camera_id: 'camera-b-01',
  jpeg_base64: readFileSync(new URL('../synthetic.jpg', import.meta.url)).toString('base64') });
const request = { ...fixtures.report_request, event_id: randomUUID(), image: photo };
const report = await post('/reports', request);
assert.equal(report.status, 'PENDING'); assert.equal((await api.map()).version, before.version);
console.log('PASS: actual local API report intake leaves map unchanged');
const duplicate = await post('/reports', request, 200);
assert.equal(duplicate.ticket_id, report.ticket_id);
console.log('PASS: identical report retry returns the same ticket');
const rejectRequest = { ...request, event_id: randomUUID() };
const rejectedReport = await post('/reports', rejectRequest);
const rejection = await api.review(rejectedReport.ticket_id, { action: 'REJECT', expected_map_version: before.version, notes: 'Local smoke only' });
assert.equal(rejection.report.status, 'REJECTED'); assert.equal((await api.map()).version, before.version);
console.log('PASS: isolated rejection leaves existing map state unchanged');
const controller = new ReviewController(api);
await controller.refresh(); await controller.select(report.ticket_id);
await controller.decide('APPROVE', 'Local smoke only');
assert.equal(controller.state.error, ''); assert.equal(controller.state.selected.status, 'APPROVED');
assert.equal(controller.state.map.version, before.version + 1);
assert.equal(controller.state.map.edges.find(e => e.from === 'B' && e.to === 'C').blocked, true);
console.log('PASS: dashboard controller receives confirmed approval and authoritative full map');
const body = { action: 'APPROVE', expected_map_version: before.version, notes: 'Local smoke only' };
await api.review(report.ticket_id, body); assert.equal((await api.map()).version, before.version + 1);
console.log('PASS: identical review retry does not increment the map again');
await assert.rejects(api.review(report.ticket_id, { ...body, action: 'REJECT' }), e => e.status === 409);
assert.equal((await api.version()).version, before.version + 1);
console.log('PASS: changed terminal review returns conflict and preserves closure');
console.log('LOCAL SYNTHETIC CONTRACT VERIFICATION ONLY. No AWS, camera, laptop or speech evidence.');
