import { ApiError, validateTicket, validateMap } from './api.mjs';

// UI state owns no map mutation; only API responses may change review/map state.
export class ReviewController {
  constructor(client, changed = () => {}) {
    this.client = client;
    this.changed = changed;
    this.state = { busy: false, items: [], selected: null, map: null, stale: true,
      cursor: null, status: 'PENDING', health: null, error: '', notice: '', retry: null };
  }
  emit() { this.changed(this.state); }
  async task(work) {
    if (this.state.busy) return;
    this.state.busy = true; this.state.error = ''; this.emit();
    try { await work(); }
    catch (error) {
      this.state.error = error.message;
      this.state.notice = 'The request did not complete successfully. Check the error above before continuing.';
    }
    finally { this.state.busy = false; this.emit(); }
  }
  async refresh(status = this.state.status, more = false) {
    return this.task(async () => {
      this.state.stale = true;
      const selectedId = this.state.selected?.ticket_id;
      const [health, page, map, selected] = await Promise.all([
        this.client.health(), this.client.tickets(status, more ? this.state.cursor : null),
        this.client.map(), selectedId ? this.client.ticket(selectedId) : null,
      ]);
      if (health.status !== 'healthy' || !Array.isArray(page.items)) throw new Error('Unsupported API response.');
      page.items.forEach(validateTicket); validateMap(map);
      if (selected) validateTicket(selected);
      this.state.health = health; this.state.map = map; this.state.stale = false;
      this.state.items = more ? [...new Map([...this.state.items, ...page.items].map(t => [t.ticket_id, t])).values()] : page.items;
      this.state.cursor = page.next_cursor; this.state.status = status;
      this.state.selected = selected;
      this.state.retry = null;
      this.state.notice = 'Refreshed from the service. Laptop synchronisation is not checked by this dashboard.';
    });
  }
  async select(id) {
    return this.task(async () => {
      if (this.state.retry) throw new Error('Refresh or retry the unresolved decision first.');
      this.state.selected = null;
      this.state.notice = 'Loading report…'; this.emit();
      this.state.selected = validateTicket(await this.client.ticket(id));
      this.state.notice = 'Report received. Inspect its evidence before deciding.';
    });
  }
  async decide(action, notes = '', retry = false) {
    return this.task(async () => {
      const { selected, map, stale } = this.state;
      if (!selected || !map || (stale && !retry) || selected.status !== 'PENDING') throw new Error('Refresh and select a pending report first.');
      if (this.state.retry && !retry) throw new Error('Refresh or retry the unresolved decision first.');
      const request = retry ? this.state.retry : { id: selected.ticket_id,
        body: { action, expected_map_version: map.version, notes } };
      if (!request || !['APPROVE', 'REJECT'].includes(request.body.action)) throw new Error('Invalid decision.');
      this.state.notice = 'Waiting for server confirmation…'; this.emit();
      let result;
      try { result = await this.client.review(request.id, request.body); }
      catch (error) {
        if (error instanceof ApiError && [0, 429, 503].includes(error.status)) {
          this.state.retry = request; this.state.stale = true;
        }
        else { this.state.retry = null; this.state.stale = true; }
        throw error;
      }
      try {
        validateTicket(result.report);
        if (result.report.ticket_id !== request.id ||
            result.report.status !== (request.body.action === 'APPROVE' ? 'APPROVED' : 'REJECTED') ||
            !Number.isInteger(result.map_version)) throw new Error();
      } catch {
        this.state.retry = request; this.state.stale = true;
        throw new Error('Review response was not understood. Refresh to confirm the outcome.');
      }
      this.state.selected = result.report; this.state.retry = null;
      this.state.items = this.state.items.map(t => t.ticket_id === request.id ? result.report : t)
        .filter(t => !this.state.status || t.status === this.state.status);
      this.state.stale = true;
      this.state.notice = `${result.report.status} confirmed by the server at map version ${result.map_version}. Checking the full shared map…`;
      this.emit();
      try {
        const current = validateMap(await this.client.map());
        if (current.version < result.map_version) throw new Error();
        this.state.map = current; this.state.stale = false;
        this.state.notice = `${result.report.status} confirmed. Shared map version ${current.version} fetched. Laptop rerouting and speech still need separate verification.`;
      } catch {
        this.state.error = 'Review was saved, but the shared map could not be refreshed. The displayed map is stale; use Refresh.';
      }
    });
  }
}
