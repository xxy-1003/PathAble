// Contract: backend 63de1ad, fixed_camera/HANDOFF.md revision 1.1.
export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export function apiBase(value) {
  const url = new URL(value);
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) ||
      url.username || url.password || url.search || url.hash) {
    throw new Error('Use an HTTPS API address, or HTTP on localhost only.');
  }
  if (!url.pathname.replace(/\/$/, '').endsWith('/api/v2')) {
    throw new Error('The API address must end in /api/v2.');
  }
  return url.href.replace(/\/$/, '');
}

export class ApiClient {
  constructor(base, token, fetcher = (...args) => globalThis.fetch(...args)) {
    this.base = apiBase(base);
    this.token = token.trim();
    if (!this.token && !['localhost', '127.0.0.1', '[::1]'].includes(new URL(this.base).hostname)) {
      throw new Error('A reviewer access token is required for a remote API.');
    }
    this.fetcher = fetcher;
  }
  async request(path, body) {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 15000);
    try {
      const response = await this.fetcher(this.base + path, {
        method: body ? 'POST' : 'GET', credentials: 'omit', redirect: 'error',
        cache: 'no-store', referrerPolicy: 'no-referrer', signal: abort.signal,
        headers: { ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
          ...(body ? { 'Content-Type': 'application/json' } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      if (!response.ok) {
        // Never echo server text: it may contain a token, signed URL or private notes.
        const messages = { 401: 'Sign-in expired. Reconnect with a fresh reviewer token.',
          403: 'Reviewer access was denied. Check the reviewer scope and allowlist.',
          404: 'This report is no longer available.',
          409: 'The report or map changed. Refresh and inspect it before deciding again.',
          410: 'The evidence photo retention period has ended.',
          422: 'The server rejected this request. Check the contract and refresh.',
          429: 'Too many requests. Wait briefly, then retry.',
          503: 'The service is unavailable. Wait briefly, then retry.' };
        throw new ApiError(response.status, messages[response.status] || `Request failed (HTTP ${response.status}).`);
      }
      return await response.json();
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, 'Connection failed or timed out. The request outcome is unknown; refresh or retry the same decision.');
    } finally { clearTimeout(timer); }
  }
  health() { return this.request('/health'); }
  tickets(status, cursor) {
    const params = new URLSearchParams({ limit: '50' });
    if (status) params.set('status', status);
    if (cursor) params.set('cursor', cursor);
    return this.request('/tickets?' + params);
  }
  ticket(id) { return this.request('/tickets/' + encodeURIComponent(id)); }
  photo(id) { return this.request('/reports/' + encodeURIComponent(id) + '/photo'); }
  map() { return this.request('/map'); }
  version() { return this.request('/map/version'); }
  review(id, body) { return this.request('/tickets/' + encodeURIComponent(id) + '/review', body); }
}

export function photoURL(value, base, fixture = false) {
  if (fixture && /^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(value)) return value;
  const url = new URL(value, base + '/');
  if (url.username || url.password ||
      (url.protocol !== 'https:' && !(url.protocol === 'http:' &&
       ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) &&
       url.origin === new URL(base).origin))) throw new Error('Unsupported evidence image address.');
  return url.href;
}

export const statusLabel = status => ({ PENDING: 'Awaiting human review',
  APPROVED: 'Approved closure', REJECTED: 'Rejected report' }[status] || 'Unknown status');
export const measurement = value => Number.isFinite(value) ? `${value} m` : 'Unknown';

export function validateTicket(report) {
  if (!report || !['PENDING', 'APPROVED', 'REJECTED'].includes(report.status) ||
      !/^T-[0-9a-f-]{36}$/i.test(report.ticket_id) || report.ticket_id !== 'T-' + report.event_id ||
      report.edge_key !== 'B-C' || report.junction !== 'B') {
    throw new Error('Unsupported ticket response. Check the backend contract.');
  }
  return report;
}

export function validateMap(map) {
  if (!map || map.map_id !== 'prototype' || !Number.isInteger(map.version) || map.version < 1 ||
      !Array.isArray(map.edges) || !map.edges.some(e => e.from === 'B' && e.to === 'C' && typeof e.blocked === 'boolean')) {
    throw new Error('Unsupported shared-map response.');
  }
  return map;
}
