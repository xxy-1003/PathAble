import { ApiError } from './api.mjs';

// Browser-memory simulation, deliberately disconnected from the API client.
export class FixtureClient {
  constructor(fixtures) {
    this.base = 'http://127.0.0.1/api/v2';
    this.fixtures = structuredClone(fixtures);
    this.report = structuredClone(fixtures.pending_response);
    this.sharedMap = structuredClone(fixtures.map_before);
    this.fail = false;
  }
  async read(value) {
    await new Promise(resolve => setTimeout(resolve, 180));
    if (this.fail) throw new ApiError(0, 'SIMULATED connection failure. No AWS request was made.');
    return structuredClone(value);
  }
  health() { return this.read({ status: 'healthy', storage: 'fixture-memory-NOT-AWS', map_version: this.sharedMap.version }); }
  tickets(status) { return this.read({ items: !status || status === this.report.status ? [this.report] : [], next_cursor: null }); }
  ticket() { return this.read(this.report); }
  map() { return this.read(this.sharedMap); }
  version() { return this.read({ map_id: 'prototype', version: this.sharedMap.version }); }
  photo() { return this.read({ url: './synthetic.jpg', expires_in: 300 }); }
  async review(id, body) {
    await this.read(null);
    if (this.report.status !== 'PENDING') {
      if (JSON.stringify(this.lastBody) === JSON.stringify(body)) return structuredClone(this.lastResult);
      throw new ApiError(409, 'Fixture already reviewed. Reset fixtures for a fresh case.');
    }
    if (body.expected_map_version !== this.sharedMap.version) throw new ApiError(409, 'Refresh the fixture map.');
    if (body.action === 'APPROVE') this.sharedMap = structuredClone(this.fixtures.map_after_approval);
    this.report.status = body.action === 'APPROVE' ? 'APPROVED' : 'REJECTED';
    this.report.review = { ...body, reviewer_id: 'fixture-reviewer',
      reviewed_at: new Date().toISOString(), map_version: this.sharedMap.version };
    this.lastBody = structuredClone(body);
    this.lastResult = { report: this.report, map_version: this.sharedMap.version };
    return structuredClone(this.lastResult);
  }
}
