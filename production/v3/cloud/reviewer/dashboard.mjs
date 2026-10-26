import { ApiClient, photoURL, statusLabel, measurement } from './api.mjs';
import { ReviewController } from './controller.mjs';
import { FixtureClient } from './fixture.mjs';
import { authConfig, createAuth, reviewerToken } from './auth.mjs';

const $ = id => document.getElementById(id);
let controller, activeFixture = true, photoReady = false, photoBusy = false;
let selection = null, photoEpoch = 0, photoExpiry, photoLoadTimeout;
let login, loginConfig, session = null;
const fixtures = await fetch('./fixtures.json', { cache: 'no-store' }).then(r => {
  if (!r.ok) throw new Error('Fixture file unavailable');
  return r.json();
}).catch(() => null);

function text(id, value) { $(id).textContent = value; }
function clearPhoto() {
  photoEpoch++; clearTimeout(photoExpiry); clearTimeout(photoLoadTimeout); photoReady = false; photoBusy = false;
  $('photo').hidden = true; $('photo').removeAttribute('src');
  $('photo').onload = null; $('photo').onerror = null;
  text('photo-status', 'Evidence has not been loaded.');
}
function updateControls() {
  const s = controller?.state;
  const busy = Boolean(s?.busy);
  for (const id of ['mode', 'connect', 'filter', 'refresh', 'more', 'fail']) $(id).disabled = busy;
  for (const id of ['reviewer-login', 'camera-login']) $(id).disabled = busy || !loginConfig;
  $('forget-login').disabled = busy;
  const api = $('mode').value === 'api';
  $('api-base').disabled = busy || !api; $('token').disabled = busy || !api;
  $('notes').disabled = busy || Boolean(s?.retry) || s?.selected?.status !== 'PENDING';
  const canReview = s?.selected?.status === 'PENDING' && s?.map && !s.stale && !s.retry && !busy;
  $('approve').disabled = !canReview || !photoReady;
  $('reject').disabled = !canReview;
  $('retry-decision').hidden = !s?.retry;
  $('retry-decision').disabled = busy || !s?.retry;
  $('photo-retry').disabled = busy || photoBusy;
  document.querySelectorAll('.ticket').forEach(button => { button.disabled = busy || Boolean(s?.retry); });
}
function fact(label, value) {
  const term = document.createElement('dt'), definition = document.createElement('dd');
  term.textContent = label; definition.textContent = value ?? 'Unknown';
  $('facts').append(term, definition);
}
function render(s) {
  $('error').hidden = !s.error; text('error', s.error);
  text('notice', s.busy ? 'Working… ' + s.notice : s.notice);
  text('mode-badge', activeFixture ? 'FIXTURE MODE · NOT AWS' : 'API MODE · SERVICE DATA');
  text('mode-note', activeFixture ? 'Synthetic contract fixtures. No AWS reports, approvals or laptop updates are made.' :
    !s.health ? 'API connection is not yet verified. No reports or map updates are confirmed.' :
    new URL(controller.client.base).hostname === '127.0.0.1' || new URL(controller.client.base).hostname === 'localhost' ?
    'LOCAL API · NOT AWS. This connection does not verify cloud storage, laptop synchronisation or speech.' :
    'Connected API data. This dashboard does not independently verify AWS durability, laptop synchronisation or speech.');
  $('fixture-tools').hidden = !activeFixture;
  $('tickets').replaceChildren();
  text('list-count', `${s.items.length} report(s) loaded${s.cursor ? ' · more available' : ''}`);
  if (!s.items.length) {
    const empty = document.createElement('p'); empty.className = 'muted';
    empty.textContent = s.stale ? 'Reports are not confirmed. Refresh to retry.' : 'No reports in this view.';
    $('tickets').append(empty);
  }
  for (const report of s.items) {
    const button = document.createElement('button'); button.className = 'ticket';
    button.setAttribute('aria-pressed', String(report.ticket_id === s.selected?.ticket_id));
    button.textContent = `${report.edge_key} · ${statusLabel(report.status)}`;
    for (const value of [report.ticket_id, report.timestamp]) {
      const span = document.createElement('span'); span.textContent = value; button.append(span);
    }
    button.addEventListener('click', () => controller.select(report.ticket_id));
    $('tickets').append(button);
  }
  $('more').hidden = !s.cursor;
  const report = s.selected;
  $('detail').hidden = !report; $('empty-detail').hidden = Boolean(report);
  text('ticket-status', report ? `${report.status} · ${statusLabel(report.status)}` : 'No report selected');
  $('ticket-status').dataset.status = report?.status || '';
  const nextSelection = report?.ticket_id || null;
  if (selection !== nextSelection) {
    selection = nextSelection; clearPhoto(); $('notes').value = '';
    if (report) queueMicrotask(loadPhoto);
  }
  if (report) {
    $('facts').replaceChildren();
    const evidence = report.detection_evidence || {};
    fact('Event ID', report.event_id); fact('Ticket ID', report.ticket_id);
    fact('Location', `${report.junction} / ${report.edge_key} (assigned)`);
    fact('Report time', report.timestamp); fact('Received', report.received_at);
    fact('Detection', evidence.obstacle_class);
    fact('Score', Number.isFinite(evidence.confidence) ? `${(evidence.confidence * 100).toFixed(1)}% (client-reported)` : 'Unknown');
    fact('Region overlap', Number.isInteger(evidence.overlap_count) && Number.isInteger(evidence.frame_count) ?
      `${evidence.overlap_count} / ${evidence.frame_count} frames (client-reported)` : 'Unknown');
    fact('Distance', measurement(report.distance_m)); fact('Clearance', measurement(report.clearance_m));
    text('decision-context', s.retry ? 'The previous request outcome is uncertain. Retry sends the exact same decision and notes, or Refresh to reconcile.' :
      `Decision uses displayed map version ${s.map?.version ?? 'unknown'}. Approve becomes available after the image loads. Reviewer identity is verified by the API.`);
    text('review-record', report.review ? `Recorded reviewer: ${report.review.reviewer_id} · ${report.review.reviewed_at} · Notes: ${report.review.notes || '(none)'}` : 'No review recorded.');
  }
  text('map-version', s.map ? `v${s.map.version}${s.stale ? ' · STALE' : ''}` : 'Not loaded');
  const edge = s.map?.edges.find(e => e.from === 'B' && e.to === 'C');
  text('map-status', s.stale ? 'Shared-map state is unconfirmed. Refresh before reviewing.' :
    edge?.blocked ? 'B–C: approved closure recorded in shared map.' : 'B–C: no approved closure recorded.');
  $('map-edges').replaceChildren();
  for (const edge of s.map?.edges || []) {
    const row = document.createElement('div'); row.className = 'edge';
    const label = document.createElement('strong'), value = document.createElement('span');
    label.textContent = `${edge.from}–${edge.to}`;
    value.textContent = `${edge.blocked ? 'Approved closure' : 'No approved closure'} · distance ${measurement(edge.distance)}`;
    row.append(label, value); $('map-edges').append(row);
  }
  text('service', s.health ? `Service storage: ${s.health.storage}. ${activeFixture ? 'Synthetic practice only.' : 'A storage label alone does not prove deployment or durability.'}` : 'Service not yet verified.');
  updateControls();
}
async function loadPhoto() {
  const report = controller?.state.selected;
  if (!report || photoBusy) return;
  clearPhoto(); photoBusy = true;
  const epoch = photoEpoch, current = controller;
  text('photo-status', 'Loading evidence…'); updateControls();
  const valid = () => epoch === photoEpoch && current === controller;
  try {
    const link = await current.client.photo(report.event_id);
    if (!valid()) return;
    // Fixture image is an included synthetic JPEG, never a camera capture.
    const source = activeFixture ? './synthetic.jpg' : photoURL(link.url, current.client.base);
    if (!Number.isFinite(link.expires_in) || link.expires_in <= 0) throw new Error('Evidence link has expired.');
    $('photo').onload = () => {
      if (!valid()) return;
      clearTimeout(photoLoadTimeout);
      photoReady = true; photoBusy = false; $('photo').hidden = false;
      text('photo-status', activeFixture ? 'SYNTHETIC gray image · contract fixture only' :
        current.state.health?.storage?.startsWith('local-') ? 'Local API evidence image · not an AWS privacy or storage verification.' :
        'Private evidence image · use Reload if the temporary link expires.');
      updateControls();
    };
    $('photo').onerror = () => {
      if (!valid()) return;
      clearTimeout(photoLoadTimeout);
      photoReady = false; photoBusy = false; $('photo').hidden = true;
      text('photo-status', 'Image could not be loaded. The private link may have expired. Reload evidence to retry.'); updateControls();
    };
    photoExpiry = setTimeout(() => {
      if (!valid()) return;
      clearPhoto(); text('photo-status', 'Private link expired. Reload evidence before approval.'); updateControls();
    }, Math.min(link.expires_in, 300) * 1000);
    photoLoadTimeout = setTimeout(() => {
      if (!valid()) return;
      clearPhoto(); text('photo-status', 'Image loading timed out. Reload evidence to retry.'); updateControls();
    }, 15000);
    $('photo').alt = activeFixture ? 'Synthetic gray contract fixture; not a camera capture' :
      `Camera evidence for report ${report.event_id}, assigned to B–C`;
    $('photo').src = source;
  } catch (error) {
    if (!valid()) return;
    photoBusy = false;
    text('photo-status', error.message); updateControls();
  }
}
async function connect(event) {
  event?.preventDefault();
  if (controller?.state.busy) return;
  try {
    const isFixture = $('mode').value === 'fixture';
    if (isFixture && !fixtures) throw new Error('Fixture file unavailable. Reload the page or connect to an API.');
    const token = isFixture ? '' : $('token').value || reviewerToken(session, loginConfig?.apiBase, $('api-base').value);
    const client = isFixture ? new FixtureClient(fixtures) : new ApiClient($('api-base').value, token);
    activeFixture = isFixture; clearPhoto(); selection = null; $('notes').value = ''; $('fail').checked = false;
    const next = new ReviewController(client, state => { if (controller === next) render(state); });
    controller = next; $('token').value = ''; $('filter').value = 'PENDING';
    await controller.refresh();
  } catch (error) { $('error').hidden = false; text('error', error.message); }
}
$('connection-form').addEventListener('submit', connect);
$('mode').addEventListener('change', updateControls);
$('refresh').addEventListener('click', () => controller.refresh($('filter').value));
$('filter').addEventListener('change', async () => {
  await controller.refresh($('filter').value); $('filter').value = controller.state.status;
});
$('more').addEventListener('click', () => controller.refresh(controller.state.status, true));
$('approve').addEventListener('click', () => controller.decide('APPROVE', $('notes').value));
$('reject').addEventListener('click', () => controller.decide('REJECT', $('notes').value));
$('retry-decision').addEventListener('click', () => controller.decide(null, '', true));
$('photo-retry').addEventListener('click', loadPhoto);
$('fail').addEventListener('change', () => { if (activeFixture) controller.client.fail = $('fail').checked; });

async function signIn(role) {
  if (!loginConfig || controller?.state.busy) return;
  if (location.origin !== loginConfig.loginOrigin) {
    location.assign(loginConfig.loginOrigin + '/?login=' + encodeURIComponent(role));
    return;
  }
  try { text('auth-status', 'Opening the AWS application sign-in page…'); await login.signIn(role); }
  catch { text('auth-status', 'Sign-in could not be started. Check the application settings and retry.'); }
}
function displaySession() {
  $('forget-login').hidden = !session;
  $('camera-token-tools').hidden = session?.role !== 'camera';
  text('auth-status', session ? `Signed in for ${session.role === 'reviewer' ? 'reviewer' : 'camera/laptop'} access. ${loginConfig.apiBase ? 'API access is still checked by the backend.' : 'The backend API address is not configured yet.'}` : 'Not signed in. Use your assigned reviewer or camera account.');
}
async function forgetSession(expired = false) {
  session = null; await login?.forget();
  if (controller?.client?.token) controller.client.token = '';
  $('mode').value = 'fixture';
  await connect(); displaySession();
  if (expired) text('auth-status', 'The access token expired. Sign in again before API operations.');
}
$('reviewer-login').addEventListener('click', () => signIn('reviewer'));
$('camera-login').addEventListener('click', () => signIn('camera'));
$('forget-login').addEventListener('click', () => { $('mode').value = 'fixture'; forgetSession(); });
$('copy-camera-token').addEventListener('click', async () => {
  if (session?.role !== 'camera' || session.user.expired) return;
  try { await navigator.clipboard.writeText(session.user.access_token); text('auth-status', 'Camera token copied. Use it only in the camera laptop environment, then clear the clipboard.'); }
  catch { text('auth-status', 'Clipboard access failed. Retry from the camera laptop browser.'); }
});
async function initializeAuth() {
  const callbackURL = location.href;
  const parameters = new URL(callbackURL).searchParams;
  const isCallback = location.pathname === '/callback.html';
  if (isCallback) history.replaceState(null, '', '/');
  try {
    const response = await fetch('./auth-config.json', { cache: 'no-store' });
    if (!response.ok) throw new Error();
    loginConfig = authConfig(await response.json());
    login = createAuth(loginConfig);
    login.manager.events.addAccessTokenExpired(() => forgetSession(true));
    if (isCallback) {
      session = await login.complete(callbackURL);
      if (session.role === 'reviewer' && loginConfig.apiBase) {
        $('mode').value = 'api'; $('api-base').value = loginConfig.apiBase;
        await connect();
      }
    }
    displaySession(); updateControls();
    const requested = parameters.get('login');
    if (!isCallback && ['reviewer', 'camera'].includes(requested)) {
      history.replaceState(null, '', '/'); await signIn(requested);
    }
  } catch {
    session = null;
    text('auth-status', isCallback ? 'Sign-in could not be completed or the callback did not match this browser session. Start sign-in again.' : 'Application sign-in is not configured or unavailable. Fixture mode is still available.');
    updateControls();
  }
}
await connect();
await initializeAuth();
