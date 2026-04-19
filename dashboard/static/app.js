// ── State ──────────────────────────────────────────────────────────────
const state = {
  currentPage: 'overview',
  positionsFilter: 'all',
  pnlHistory: [],
  chart: null,
  refreshInterval: null,
  an: {
    pnlDist:     null,
    edgeDist:    null,
    edgeScatter: null,
    slipDist:    null,
    holdDist:    null,
  },
};

const MAX_HISTORY = 60;
const REFRESH_MS  = 10000;

// ── Helpers ────────────────────────────────────────────────────────────
function fmt(n, dec = 2) {
  if (n == null) return '—';
  const v = Number(n);
  return '$' + (v >= 0 ? '' : '-') + Math.abs(v).toFixed(dec);
}

function fmtPct(n) {
  if (n == null) return '—';
  return Number(n).toFixed(1) + '%';
}

function fmtTime(s) {
  if (!s) return '—';
  try {
    return new Date(s).toLocaleTimeString(undefined, {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch { return s; }
}

function fmtDate(s) {
  if (!s) return '—';
  try {
    return new Date(s).toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return s; }
}

function badge(text, color) {
  return `<span class="badge badge-${color}">${text}</span>`;
}

function statusBadge(status) {
  if (!status) return badge('—', 'gray');
  const s = status.toLowerCase();
  if (s === 'open' || s === 'detected') return badge(status, 'yellow');
  if (s === 'settled' || s === 'won' || s === 'filled') return badge(status, 'green');
  if (s === 'lost' || s === 'failed' || s === 'cancelled') return badge(status, 'red');
  return badge(status, 'gray');
}

function pnlSpan(val) {
  if (val == null) return '—';
  const n = Number(val);
  return `<span class="${n >= 0 ? 'pnl-pos' : 'pnl-neg'}">${fmt(n)}</span>`;
}

function emptyRow(cols, msg) {
  return `<tr><td colspan="${cols}" class="empty-row">${msg}</td></tr>`;
}

// ── Navigation ─────────────────────────────────────────────────────────
function nav(page) {
  state.currentPage = page;

  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.page === page);
  });

  document.querySelectorAll('.page').forEach(el => {
    el.classList.toggle('hidden', el.id !== `page-${page}`);
  });

  loadPage(page);
}

// ── API ────────────────────────────────────────────────────────────────
async function apiFetch(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) {
      console.warn(`[apiFetch] ${path} → ${res.status} ${res.statusText}`);
      return null;
    }
    return await res.json();
  } catch (e) {
    console.error(`[apiFetch] ${path} → network error:`, e);
    return null;
  }
}

// ── Page Loader ────────────────────────────────────────────────────────
function loadPage(page) {
  switch (page) {
    case 'overview':  return loadOverview();
    case 'positions': return loadPositions(state.positionsFilter);
    case 'trades':    return loadTrades();
    case 'status':    return loadStatusPage();
    case 'config':    return loadConfig();
    case 'settings':  return loadSettings();
    case 'analytics': return loadAnalytics();
  }
}

// ── Overview ───────────────────────────────────────────────────────────
async function loadOverview() {
  const [statusData, portfolio, pnlData, openPos] = await Promise.all([
    apiFetch('/api/status'),
    apiFetch('/api/portfolio'),
    apiFetch('/api/pnl'),
    apiFetch('/api/positions?status=open'),
  ]);

  renderStats(statusData, portfolio, pnlData);
  renderPortfolioKV(portfolio);
  renderOverviewPositions(openPos);
  updatePnLChart(pnlData);
  updateSidebarMeta(statusData);
  updateControlBar(statusData);
}

function renderStats(statusData, portfolio, pnl) {
  const el = document.getElementById('stats-overview');
  if (!el) return;

  const balance  = portfolio?.balance;
  const totalPnl = pnl?.total_pnl;
  const winRate  = pnl?.win_rate;
  const openPos  = statusData?.open_positions;
  const maxPos   = statusData?.max_positions;

  el.innerHTML = `
    <div class="stat-card">
      <div class="stat-number">${balance != null ? fmt(balance) : '—'}</div>
      <div class="stat-label">Balance</div>
      <div class="stat-sub">${portfolio?.deployed != null ? fmt(portfolio.deployed) + ' deployed' : ''}</div>
    </div>
    <div class="stat-card">
      <div class="stat-number ${totalPnl != null ? (totalPnl >= 0 ? 'num-green' : 'num-red') : ''}">
        ${totalPnl != null ? fmt(totalPnl) : '—'}
      </div>
      <div class="stat-label">Total P&amp;L</div>
      <div class="stat-sub">${pnl?.total_trades ?? 0} trades</div>
    </div>
    <div class="stat-card">
      <div class="stat-number">${winRate != null ? fmtPct(winRate) : '—'}</div>
      <div class="stat-label">Win Rate</div>
      <div class="stat-sub">${pnl?.wins ?? 0}W / ${pnl?.losses ?? 0}L</div>
    </div>
    <div class="stat-card">
      <div class="stat-number">
        ${openPos ?? '—'}<span style="font-size:16px;color:var(--text-2);"> / ${maxPos ?? '—'}</span>
      </div>
      <div class="stat-label">Positions</div>
      <div class="stat-sub">
        ${statusData != null ? (statusData.running ? badge('Running', 'green') : badge('Stopped', 'red')) : ''}
      </div>
    </div>
  `;
}

function renderPortfolioKV(data) {
  const el = document.getElementById('portfolio-kv');
  if (!el) return;
  if (!data) { el.innerHTML = '<div class="kv-empty">Bot not running</div>'; return; }

  // Use total_value (cash + deployed at cost) so open positions don't
  // appear as losses just because capital left the available balance.
  const portfolioValue = data.total_value ?? data.balance;
  const gain = portfolioValue != null && data.starting_balance != null
    ? portfolioValue - data.starting_balance : null;

  el.innerHTML = [
    ['Balance',          fmt(data.balance)],
    ['Available',        fmt(data.available)],
    ['Deployed',         fmt(data.deployed)],
    ['Starting Balance', fmt(data.starting_balance)],
    ['Unrealised Gain',  pnlSpan(gain)],
  ].map(([k, v]) => `
    <div class="kv-row">
      <span class="kv-key">${k}</span>
      <span class="kv-val">${v}</span>
    </div>
  `).join('');
}

function renderOverviewPositions(positions) {
  const countEl = document.getElementById('open-pos-count');
  const tableEl = document.getElementById('overview-positions-table');
  if (!tableEl) return;

  const arr = Array.isArray(positions) ? positions : [];
  if (countEl) countEl.textContent = arr.length;
  tableEl.innerHTML = buildPositionsTable(arr);
}

// ── Positions ──────────────────────────────────────────────────────────
async function loadPositions(filter) {
  const url = filter === 'all' ? '/api/positions' : `/api/positions?status=${filter}`;
  const data = await apiFetch(url);
  const el = document.getElementById('positions-table');
  if (el) el.innerHTML = buildPositionsTable(Array.isArray(data) ? data : []);
}

function buildPositionsTable(arr) {
  const headers = ['Market', 'Question', 'Shares', 'Entry', 'Capital', 'Edge', 'Status', 'Opened'];
  const head = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>`;
  if (!arr.length) {
    return `<table>${head}<tbody>${emptyRow(headers.length, 'No positions')}</tbody></table>`;
  }
  const rows = arr.map(p => `
    <tr>
      <td class="mono" style="font-size:12px;">${p.market_slug || '—'}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--text-1);">${p.question || '—'}</td>
      <td class="mono">${p.shares != null ? Number(p.shares).toFixed(4) : '—'}</td>
      <td class="mono">${fmt(p.entry_price, 4)}</td>
      <td class="mono">${fmt(p.allocated_capital)}</td>
      <td>${p.edge_percent != null ? `<span class="pnl-pos">${Number(p.edge_percent).toFixed(2)}%</span>` : '—'}</td>
      <td>${statusBadge(p.status)}</td>
      <td style="font-size:12px;color:var(--text-2);">${fmtDate(p.opened_at)}</td>
    </tr>
  `).join('');
  return `<table>${head}<tbody>${rows}</tbody></table>`;
}

// ── Trades ─────────────────────────────────────────────────────────────
async function loadTrades() {
  const data = await apiFetch('/api/trades?limit=100');
  const el = document.getElementById('trades-table');
  if (!el) return;

  const arr = Array.isArray(data) ? data : [];
  const headers = ['Order ID', 'Market', 'Action', 'Qty', 'Price', 'Total', 'Status', 'Time', 'P&L'];
  const head = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>`;

  if (!arr.length) {
    el.innerHTML = `<table>${head}<tbody>${emptyRow(headers.length, 'No trades')}</tbody></table>`;
    return;
  }

  const rows = arr.map(t => `
    <tr>
      <td class="mono" style="font-size:11px;color:var(--text-2);">${(t.order_id || '').slice(0, 12)}…</td>
      <td class="mono" style="font-size:12px;">${t.market_slug || '—'}</td>
      <td>${(t.action || '').toUpperCase() === 'BUY' ? badge('BUY', 'green') : badge(t.action || '—', 'gray')}</td>
      <td class="mono">${t.quantity != null ? Number(t.quantity).toFixed(4) : '—'}</td>
      <td class="mono">${fmt(t.price, 4)}</td>
      <td class="mono">${fmt(t.total)}</td>
      <td>${statusBadge(t.status)}</td>
      <td style="font-size:12px;color:var(--text-2);">${fmtTime(t.executed_at)}</td>
      <td>${pnlSpan(t.pnl)}</td>
    </tr>
  `).join('');

  el.innerHTML = `<table>${head}<tbody>${rows}</tbody></table>`;
}

// ── Status page ────────────────────────────────────────────────────────
async function loadStatusPage() {
  const [statusData, pnlData] = await Promise.all([
    apiFetch('/api/status'),
    apiFetch('/api/pnl'),
  ]);
  renderStatusKV(statusData);
  renderPnLKV(pnlData);
}

function renderStatusKV(data) {
  const el = document.getElementById('status-kv');
  if (!el) return;
  if (!data) { el.innerHTML = '<div class="kv-empty">Bot not running</div>'; return; }

  el.innerHTML = [
    ['Running',        data.running ? badge('Yes', 'green') : badge('No', 'red')],
    ['Mode',           badge(data.mode || '—', 'blue')],
    ['Open Positions', `${data.open_positions} / ${data.max_positions}`],
    ['Balance',        fmt(data.balance)],
    ['Deployed',       fmt(data.deployed)],
    ['Win Rate',       fmtPct(data.win_rate)],
    ['Total P&amp;L',  pnlSpan(data.total_pnl)],
    ['Uptime',         data.uptime || '—'],
    ['Last Update',    fmtDate(data.last_update)],
  ].map(([k, v]) => `
    <div class="kv-row">
      <span class="kv-key">${k}</span>
      <span class="kv-val">${v}</span>
    </div>
  `).join('');
}

function renderPnLKV(data) {
  const el = document.getElementById('pnl-kv');
  if (!el) return;
  if (!data) { el.innerHTML = '<div class="kv-empty">No data</div>'; return; }

  el.innerHTML = [
    ['Total Trades',   data.total_trades ?? '—'],
    ['Wins',           `<span class="pnl-pos">${data.wins ?? 0}</span>`],
    ['Losses',         `<span class="pnl-neg">${data.losses ?? 0}</span>`],
    ['Win Rate',       fmtPct(data.win_rate)],
    ['Total P&amp;L',  pnlSpan(data.total_pnl)],
    ['Avg Win',        fmt(data.average_win)],
    ['Avg Loss',       fmt(data.average_loss)],
    ['Profit Factor',  data.profit_factor != null ? Number(data.profit_factor).toFixed(2) : '—'],
    ['Max Drawdown',   fmt(data.max_drawdown)],
    ['Peak Balance',   fmt(data.peak_balance)],
  ].map(([k, v]) => `
    <div class="kv-row">
      <span class="kv-key">${k}</span>
      <span class="kv-val">${v}</span>
    </div>
  `).join('');
}

// ── Config page ────────────────────────────────────────────────────────
async function loadConfig() {
  const data = await apiFetch('/api/config');
  const el = document.getElementById('config-kv');
  if (!el) return;
  if (!data) { el.innerHTML = '<div class="kv-empty">No data</div>'; return; }

  el.innerHTML = [
    ['Execute Before Close', `${data.execute_before_close_seconds}s`],
    ['Max Positions',        data.max_positions],
    ['Capital Split',        fmtPct((data.capital_split_percent ?? 0) * 100)],
    ['Scan Interval',        `${data.scan_interval_ms}ms`],
    ['Starting Balance',     fmt(data.fake_currency_balance)],
  ].map(([k, v]) => `
    <div class="kv-row">
      <span class="kv-key">${k}</span>
      <span class="kv-val mono">${v}</span>
    </div>
  `).join('');
}

// ── Bot Control Bar ────────────────────────────────────────────────────

function updateControlBar(statusData) {
  const statusBadge = document.getElementById('ctrl-status-badge');
  const btnStart    = document.getElementById('btn-start');
  const btnStop     = document.getElementById('btn-stop');

  if (!statusBadge) return;

  const running = statusData?.running ?? false;

  statusBadge.className = running ? 'badge badge-green' : 'badge badge-gray';
  statusBadge.textContent = running ? 'Running' : 'Stopped';

  if (btnStart) btnStart.disabled = running;
  if (btnStop)  btnStop.disabled  = !running;
}

function setCtrlFeedback(msg, type = '') {
  const el = document.getElementById('ctrl-feedback');
  if (!el) return;
  el.textContent = msg;
  el.className = 'ctrl-feedback ' + (type === 'ok' ? 'save-ok' : type === 'err' ? 'save-err' : '');
  if (msg) setTimeout(() => { el.textContent = ''; el.className = 'ctrl-feedback'; }, 5000);
}

async function handleStart() {
  const res  = await fetch('/api/bot/start', { method: 'POST' });
  const data = await res.json();

  if (!res.ok) {
    setCtrlFeedback(data.detail ?? 'Start failed', 'err');
    return;
  }
  setCtrlFeedback(`Started in ${data.mode} mode`, 'ok');
  updateControlBar({ running: data.running });
  updateSidebarMeta({ mode: data.mode });
  setTimeout(() => loadPage('overview'), 1500);
}

async function handleStop() {
  const res  = await fetch('/api/bot/stop', { method: 'POST' });
  const data = await res.json();

  if (!res.ok) {
    setCtrlFeedback(data.detail ?? 'Stop failed', 'err');
    return;
  }
  setCtrlFeedback('Stopping…', '');
  updateControlBar({ running: false });
}

function initControlBar() {
  const btnStart = document.getElementById('btn-start');
  const btnStop  = document.getElementById('btn-stop');
  if (btnStart) btnStart.addEventListener('click', handleStart);
  if (btnStop)  btnStop.addEventListener('click', handleStop);
}

// ── Sidebar meta ───────────────────────────────────────────────────────
function updateSidebarMeta(statusData) {
  const modeEl   = document.getElementById('mode-badge');
  const uptimeEl = document.getElementById('sidebar-uptime');

  if (modeEl && statusData?.mode) {
    const mode = statusData.mode;
    modeEl.className = 'badge badge-' + (mode === 'paper' ? 'yellow' : mode === 'simulation' ? 'blue' : 'gray');
    modeEl.textContent = mode.toUpperCase();
  }

  if (uptimeEl && statusData?.uptime) {
    uptimeEl.textContent = 'up ' + statusData.uptime;
  }
}

// ── ECharts ────────────────────────────────────────────────────────────
function initChart() {
  if (state.chart || !window.echarts) return;
  const el = document.getElementById('pnl-chart');
  if (!el) return;

  state.chart = echarts.init(el, null, { renderer: 'canvas' });

  state.chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 52, right: 16, top: 12, bottom: 28 },
    xAxis: {
      type: 'category',
      data: [],
      axisLine:  { lineStyle: { color: '#1e1e1e' } },
      axisLabel: { color: '#666', fontSize: 10 },
      splitLine: { show: false },
      axisTick:  { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine:  { show: false },
      axisTick:  { show: false },
      axisLabel: { color: '#666', fontSize: 10, formatter: v => '$' + Number(v).toFixed(2) },
      splitLine: { lineStyle: { color: '#1e1e1e', type: 'dashed' } },
    },
    series: [{
      type: 'line',
      data: [],
      smooth: true,
      symbol: 'none',
      lineStyle:  { color: '#3ecf8e', width: 2 },
      itemStyle:  { color: '#3ecf8e' },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(62,207,142,0.25)' },
            { offset: 1, color: 'rgba(62,207,142,0)' },
          ],
        },
      },
    }],
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#111111',
      borderColor: '#1e1e1e',
      textStyle: { color: '#ededed', fontSize: 12, fontFamily: 'JetBrains Mono, monospace' },
      formatter: params => {
        const p = params[0];
        return `${p.name}<br/><span style="color:#3ecf8e">${fmt(p.value, 4)}</span>`;
      },
    },
  });

  window.addEventListener('resize', () => state.chart && state.chart.resize());
}

function updatePnLChart(pnlData) {
  initChart();
  if (!state.chart) return;

  const now = new Date().toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const val = pnlData?.total_pnl ?? 0;

  state.pnlHistory.push({ time: now, value: val });
  if (state.pnlHistory.length > MAX_HISTORY) state.pnlHistory.shift();

  const isNeg     = val < 0;
  const lineColor = isNeg ? '#ff4444' : '#3ecf8e';
  const area0     = isNeg ? 'rgba(255,68,68,0.25)'  : 'rgba(62,207,142,0.25)';
  const area1     = isNeg ? 'rgba(255,68,68,0)'     : 'rgba(62,207,142,0)';

  state.chart.setOption({
    xAxis:  { data: state.pnlHistory.map(p => p.time) },
    series: [{
      data:       state.pnlHistory.map(p => p.value),
      lineStyle:  { color: lineColor },
      itemStyle:  { color: lineColor },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: area0 },
            { offset: 1, color: area1 },
          ],
        },
      },
    }],
  });
}

// ── Settings page ──────────────────────────────────────────────────────

// Schema defines each section's fields: type, label, options, constraints
const SETTINGS_SECTIONS = {
  trading: [
    { key: 'trading_mode',          label: 'Trading Mode',           type: 'select',  options: ['paper','simulation'] },
    { key: 'fake_currency_balance', label: 'Starting Balance ($)',   type: 'number',  min: 0,    step: 100, restart: true },
  ],
  strategy: [
    { key: 'execute_before_close_seconds', label: 'Execute Before Close (s)', type: 'number', min: 1, max: 60 },
    { key: 'scan_interval_ms',             label: 'Scan Interval (ms)',        type: 'number', min: 100, max: 60000, step: 100 },
    { key: 'max_positions',                label: 'Max Positions',             type: 'number', min: 1,   max: 20 },
    { key: 'capital_split_percent',        label: 'Capital Split (0–1)',       type: 'number', min: 0.01, max: 1, step: 0.01 },
  ],
  alerts: [
    { key: 'enable_email_alerts',   label: 'Email Alerts',           type: 'boolean' },
    { key: 'enable_discord_alerts', label: 'Discord Alerts',         type: 'boolean' },
    { key: 'discord_webhook_url',   label: 'Discord Webhook URL',    type: 'text',   wide: true },
    { key: 'smtp_server',           label: 'SMTP Server',            type: 'text' },
    { key: 'smtp_port',             label: 'SMTP Port',              type: 'number', min: 1, max: 65535 },
    { key: 'smtp_username',         label: 'SMTP Username',          type: 'text' },
    { key: 'alert_email_from',      label: 'From Address',           type: 'text' },
    { key: 'alert_email_to',        label: 'To Address',             type: 'text' },
  ],
  logging: [
    { key: 'log_level', label: 'Log Level', type: 'select', options: ['DEBUG','INFO','WARNING','ERROR'] },
  ],
};

let _settingsData = null;

async function loadSettings() {
  const data = await apiFetch('/api/settings');
  if (!data) {
    ['trading','strategy','alerts','logging'].forEach(s => {
      const el = document.getElementById(`fields-${s}`);
      if (el) el.innerHTML = '<div class="kv-empty">Could not load settings</div>';
    });
    return;
  }
  _settingsData = data;
  for (const [section, fields] of Object.entries(SETTINGS_SECTIONS)) {
    renderSettingsSection(section, fields, data);
  }
}

function renderSettingsSection(section, fields, data) {
  const el = document.getElementById(`fields-${section}`);
  if (!el) return;
  el.innerHTML = fields.map(f => buildFieldRow(f, data[f.key])).join('');
}

function buildFieldRow(field, value) {
  let input;
  if (field.type === 'boolean') {
    const checked = value ? 'checked' : '';
    input = `<label class="toggle"><input type="checkbox" data-key="${field.key}" ${checked}><span class="toggle-slider"></span></label>`;
  } else if (field.type === 'select') {
    const opts = field.options.map(o =>
      `<option value="${o}" ${o === value ? 'selected' : ''}>${o}</option>`
    ).join('');
    input = `<select class="field-input" data-key="${field.key}">${opts}</select>`;
  } else {
    const extra = [
      field.min  != null ? `min="${field.min}"`   : '',
      field.max  != null ? `max="${field.max}"`   : '',
      field.step != null ? `step="${field.step}"` : '',
      field.wide             ? 'style="width:280px;"' : '',
    ].filter(Boolean).join(' ');
    input = `<input type="${field.type}" class="field-input mono" data-key="${field.key}" value="${value ?? ''}" ${extra}>`;
  }

  const note = field.restart
    ? ' <span class="field-note">(restart required)</span>'
    : field.note
    ? ` <span class="field-note">(${field.note})</span>`
    : '';

  return `
    <div class="field-row">
      <span class="field-label">${field.label}${note}</span>
      ${input}
    </div>
  `;
}

function collectSectionValues(section) {
  const fields = SETTINGS_SECTIONS[section];
  const out = {};
  fields.forEach(f => {
    const el = document.querySelector(`#fields-${section} [data-key="${f.key}"]`);
    if (!el) return;
    if (f.type === 'boolean') {
      out[f.key] = el.checked;
    } else if (f.type === 'number') {
      out[f.key] = Number(el.value);
    } else {
      out[f.key] = el.value;
    }
  });
  return out;
}

async function saveSection(section, feedbackId) {
  const fb = document.getElementById(feedbackId);
  if (fb) { fb.textContent = 'Saving…'; fb.className = 'save-feedback'; }

  const payload = collectSectionValues(section);
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Save failed');

    let msg = `Saved`;
    if (data.restart_required?.length) {
      msg += ` · restart required for: ${data.restart_required.join(', ')}`;
    }
    if (fb) { fb.textContent = msg; fb.className = 'save-feedback save-ok'; }
    _settingsData = { ..._settingsData, ...payload };
  } catch (err) {
    if (fb) { fb.textContent = err.message; fb.className = 'save-feedback save-err'; }
  }

  // Clear feedback after 5s
  setTimeout(() => { if (fb) fb.textContent = ''; }, 5000);
}

function initSettingsSaveButtons() {
  const sections = ['trading','strategy','alerts','logging'];
  sections.forEach(s => {
    const btn = document.getElementById(`save-${s}`);
    if (btn) btn.addEventListener('click', () => saveSection(s, `fb-${s}`));
  });
}

// ── Filter tabs ────────────────────────────────────────────────────────
function initFilterTabs() {
  document.querySelectorAll('#positions-filter .filter-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('#positions-filter .filter-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      state.positionsFilter = tab.dataset.filter;
      loadPositions(state.positionsFilter);
    });
  });
}

// ── Init ───────────────────────────────────────────────────────────────
function init() {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => nav(btn.dataset.page));
  });

  initFilterTabs();
  initSettingsSaveButtons();
  initControlBar();
  nav('overview');

  state.refreshInterval = setInterval(() => loadPage(state.currentPage), REFRESH_MS);
}

document.addEventListener('DOMContentLoaded', init);

// ── Analytics ──────────────────────────────────────────────────────────

async function loadAnalytics() {
  const data = await apiFetch('/api/analytics');
  if (!data) {
    const msg = '<div class="kv-empty">Unavailable</div>';
    ['risk-kv', 'costs-kv', 'an-edge-kv', 'slippage-kv'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = msg;
    });
    document.getElementById('analytics-warning').textContent =
      'Analytics unavailable — check /api/health to verify bot status.';
    document.getElementById('analytics-warning').classList.remove('hidden');
    return;
  }

  const warn = document.getElementById('analytics-warning');
  if (data.insufficient_data) {
    warn.textContent =
      `Only ${data.sample_size} settled trade(s) available. ` +
      'Most metrics need ≥ 5 trades; Sharpe/Sortino need ≥ 20 for reliability.';
    warn.classList.remove('hidden');
  } else {
    warn.classList.add('hidden');
  }

  renderAnalyticsStatRow(data);
  renderRiskKV(data.risk, data.sample_size);
  renderCostsKV(data.costs);
  renderEdgeKV(data.edge_realization);
  renderSlippageKV(data.slippage);
  initAnalyticsCharts();
  renderPnlDistChart(data.distributions);
  renderEdgeDistChart(data.distributions);
  renderEdgeScatterChart(data.edge_realization);
  renderSlipDistChart(data.slippage);
  renderHoldDistChart(data.hold_times);
}

function renderAnalyticsStatRow(data) {
  const r = data.risk || {};
  const c = data.costs || {};

  const sampleEl  = document.getElementById('an-sample');
  const var95El   = document.getElementById('an-var95');
  const sharpeEl  = document.getElementById('an-sharpe');
  const feedragEl = document.getElementById('an-feedrag');

  if (sampleEl) sampleEl.textContent = data.sample_size ?? '—';

  if (var95El) {
    const v = r.var_95;
    var95El.textContent = v != null ? fmt(v) : '—';
    var95El.className = 'stat-number ' + (v != null ? (v < 0 ? 'num-red' : 'num-green') : '');
  }

  if (sharpeEl) {
    const s = r.sharpe;
    sharpeEl.textContent = s != null ? s.toFixed(3) : '—';
    sharpeEl.className = 'stat-number ' + (s != null ? (s >= 0 ? 'num-green' : 'num-red') : '');
  }

  if (feedragEl) {
    const f = c.fee_drag_pct;
    feedragEl.textContent = f != null ? fmtPct(f) : '—';
  }
}

function renderRiskKV(r, sampleSize) {
  const el = document.getElementById('risk-kv');
  if (!el) return;
  if (!r) { el.innerHTML = '<div class="kv-empty">No data</div>'; return; }

  const subEl = document.getElementById('an-risk-sub');
  if (subEl) subEl.textContent = `n = ${sampleSize}`;

  const needMore = sampleSize < 20
    ? `<span style="color:var(--yellow);font-size:11px;">⚠ ${sampleSize} trades — need ≥ 20 for reliability</span>`
    : '';

  el.innerHTML = [
    ['VaR 95%',      r.var_95   != null ? `<span class="${r.var_95 < 0 ? 'pnl-neg':'pnl-pos'}">${fmt(r.var_95)}</span>` : '—'],
    ['CVaR 95%',     r.cvar_95  != null ? `<span class="${r.cvar_95 < 0 ? 'pnl-neg':'pnl-pos'}">${fmt(r.cvar_95)}</span>` : '—'],
    ['VaR 99%',      r.var_99   != null ? `<span class="${r.var_99 < 0 ? 'pnl-neg':'pnl-pos'}">${fmt(r.var_99)}</span>` : badge('need ≥ 100 trades', 'gray')],
    ['Sharpe',       r.sharpe   != null ? r.sharpe.toFixed(3) : '—'],
    ['Sortino',      r.sortino  != null ? r.sortino.toFixed(3) : '—'],
    ['Max Drawdown', r.max_drawdown_pct != null ? fmtPct(r.max_drawdown_pct) : '—'],
  ].map(([k, v]) => `
    <div class="kv-row">
      <span class="kv-key">${k}</span>
      <span class="kv-val mono">${v}</span>
    </div>
  `).join('') + (needMore ? `<div style="padding:8px 0;">${needMore}</div>` : '');
}

function renderCostsKV(c) {
  const el = document.getElementById('costs-kv');
  if (!el) return;
  if (!c) { el.innerHTML = '<div class="kv-empty">No data</div>'; return; }

  const breakEvenLine = `${fmt(c.break_even_price, 4)} (min edge ${fmtPct(c.break_even_edge_pct)})`;

  el.innerHTML = [
    ['Gross P&amp;L',      pnlSpan(c.total_gross_pnl)],
    ['Net P&amp;L',        pnlSpan(c.total_net_pnl)],
    ['Total Fees',     `<span class="pnl-neg">${fmt(c.total_fees)}</span>`],
    ['Entry Fees',     fmt(c.entry_fees)],
    ['Exit Fees',      fmt(c.exit_fees)],
    ['Fee Drag',       c.fee_drag_pct != null ? `<span class="pnl-neg">${fmtPct(c.fee_drag_pct)}</span>` : '—'],
    ['Avg Fee / Trade',fmt(c.avg_fee_per_trade)],
    ['Break-Even',     breakEvenLine],
  ].map(([k, v]) => `
    <div class="kv-row">
      <span class="kv-key">${k}</span>
      <span class="kv-val mono">${v}</span>
    </div>
  `).join('');
}

function renderEdgeKV(e) {
  const el = document.getElementById('an-edge-kv');
  if (!el) return;
  if (!e) { el.innerHTML = ''; return; }

  el.innerHTML = [
    ['Avg Expected Edge', e.avg_expected_edge != null ? `${e.avg_expected_edge.toFixed(2)}%` : '—'],
    ['Avg Realised Edge', e.avg_realized_edge != null
      ? `<span class="${e.avg_realized_edge >= 0 ? 'pnl-pos' : 'pnl-neg'}">${e.avg_realized_edge.toFixed(2)}%</span>`
      : '—'],
    ['Avg Leakage',       e.avg_leakage != null
      ? `<span class="${e.avg_leakage <= 0 ? 'pnl-pos' : 'pnl-neg'}">${e.avg_leakage > 0 ? '-' : '+'}${Math.abs(e.avg_leakage).toFixed(2)}%</span>`
      : '—'],
  ].map(([k, v]) => `
    <div class="kv-row">
      <span class="kv-key">${k}</span>
      <span class="kv-val mono">${v}</span>
    </div>
  `).join('');
}

function renderSlippageKV(s) {
  const el = document.getElementById('slippage-kv');
  if (!el) return;
  if (!s) { el.innerHTML = '<div class="kv-empty">No data</div>'; return; }

  if (!s.count) {
    el.innerHTML = '<div class="kv-empty">No orders with slippage data yet</div>';
    return;
  }

  el.innerHTML = [
    ['Orders',          s.count],
    ['Avg Slippage',    s.avg_pct != null
      ? `<span class="${s.avg_pct > 0 ? 'pnl-neg' : 'pnl-pos'}">${s.avg_pct > 0 ? '+' : ''}${s.avg_pct.toFixed(3)}%</span>`
      : '—'],
    ['Max Adverse',     s.max_adverse_pct != null ? `<span class="pnl-neg">+${s.max_adverse_pct.toFixed(3)}%</span>` : '—'],
    ['Adverse Fills',   fmtPct(s.pct_adverse_trades)],
  ].map(([k, v]) => `
    <div class="kv-row">
      <span class="kv-key">${k}</span>
      <span class="kv-val mono">${v}</span>
    </div>
  `).join('');
}

// ── Analytics chart helpers ────────────────────────────────────────────

const _CHART_DEFAULTS = {
  backgroundColor: 'transparent',
  textStyle: { fontFamily: 'JetBrains Mono, monospace', color: '#666' },
  grid: { left: 52, right: 16, top: 12, bottom: 36 },
};

const _TOOLTIP = {
  backgroundColor: '#111111',
  borderColor: '#1e1e1e',
  textStyle: { color: '#ededed', fontSize: 12, fontFamily: 'JetBrains Mono, monospace' },
};

const _AXIS_LABEL = { color: '#666', fontSize: 10 };
const _SPLIT_LINE = { lineStyle: { color: '#1e1e1e', type: 'dashed' } };

function initAnalyticsCharts() {
  const ids = {
    pnlDist:     'pnl-dist-chart',
    edgeDist:    'edge-dist-chart',
    edgeScatter: 'edge-scatter-chart',
    slipDist:    'slippage-dist-chart',
    holdDist:    'hold-dist-chart',
  };
  for (const [key, id] of Object.entries(ids)) {
    if (!state.an[key]) {
      const el = document.getElementById(id);
      if (el && window.echarts) {
        state.an[key] = echarts.init(el, null, { renderer: 'canvas' });
      }
    }
  }
  window.addEventListener('resize', () => {
    Object.values(state.an).forEach(c => c && c.resize());
  });
}

function renderPnlDistChart(dist) {
  const chart = state.an.pnlDist;
  if (!chart || !dist) return;

  const buckets = dist.pnl_buckets || [];
  const counts  = dist.pnl_counts  || [];

  // Colour each bar by sign of its midpoint label
  const itemStyle = buckets.map(label => {
    const v = parseFloat(label.replace('$', ''));
    return { value: counts[buckets.indexOf(label)] || 0, itemStyle: { color: v >= 0 ? '#3ecf8e' : '#ff4444' } };
  });

  chart.setOption({
    ..._CHART_DEFAULTS,
    tooltip: { ..._TOOLTIP, formatter: p => `${p.name}<br/>${p.value} trades` },
    xAxis: {
      type: 'category', data: buckets,
      axisLabel: { ..._AXIS_LABEL, rotate: 30 },
      axisLine: { lineStyle: { color: '#1e1e1e' } },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: _AXIS_LABEL,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: _SPLIT_LINE,
      minInterval: 1,
    },
    series: [{ type: 'bar', data: itemStyle, barMaxWidth: 40 }],
  });
}

function renderEdgeDistChart(dist) {
  const chart = state.an.edgeDist;
  if (!chart || !dist) return;

  const buckets = dist.edge_buckets || [];
  const counts  = dist.edge_counts  || [];
  const beEdge  = dist.edge_breakeven_pct;

  const markLine = beEdge != null ? {
    silent: true,
    symbol: 'none',
    lineStyle: { color: '#ff4444', type: 'dashed', width: 1 },
    label: { formatter: `break-even\n${beEdge}%`, color: '#ff4444', fontSize: 10 },
    data: [{ xAxis: `${beEdge.toFixed(2)}%` }],
  } : undefined;

  chart.setOption({
    ..._CHART_DEFAULTS,
    tooltip: { ..._TOOLTIP, formatter: p => `Edge ${p.name}<br/>${p.value} trades` },
    xAxis: {
      type: 'category', data: buckets,
      axisLabel: { ..._AXIS_LABEL, rotate: 30 },
      axisLine: { lineStyle: { color: '#1e1e1e' } },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: _AXIS_LABEL,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: _SPLIT_LINE,
      minInterval: 1,
    },
    series: [{
      type: 'bar',
      data: counts,
      itemStyle: { color: '#d4a853' },
      barMaxWidth: 40,
      markLine: markLine,
    }],
  });
}

function renderEdgeScatterChart(er) {
  const chart = state.an.edgeScatter;
  if (!chart || !er) return;

  const scatter = (er.scatter || []);
  const wins   = scatter.filter(p => p.outcome === 'WIN').map(p => [p.expected, p.realized]);
  const losses = scatter.filter(p => p.outcome === 'LOSS').map(p => [p.expected, p.realized]);
  const other  = scatter.filter(p => p.outcome !== 'WIN' && p.outcome !== 'LOSS').map(p => [p.expected, p.realized]);

  // Range for reference lines
  const allX = scatter.map(p => p.expected);
  const xMin = allX.length ? Math.min(...allX) - 0.2 : -1;
  const xMax = allX.length ? Math.max(...allX) + 0.2 : 3;

  chart.setOption({
    ..._CHART_DEFAULTS,
    grid: { left: 52, right: 16, top: 16, bottom: 36 },
    tooltip: {
      ..._TOOLTIP,
      formatter: p => `Expected: ${p.data[0].toFixed(2)}%<br/>Realised: ${p.data[1].toFixed(2)}%`,
    },
    xAxis: {
      type: 'value', name: 'Expected (%)',
      nameTextStyle: { color: '#666', fontSize: 10 },
      axisLabel: { ..._AXIS_LABEL, formatter: v => `${v}%` },
      axisLine: { lineStyle: { color: '#1e1e1e' } },
      splitLine: _SPLIT_LINE,
    },
    yAxis: {
      type: 'value', name: 'Realised (%)',
      nameTextStyle: { color: '#666', fontSize: 10 },
      axisLabel: { ..._AXIS_LABEL, formatter: v => `${v}%` },
      axisLine: { show: false },
      splitLine: _SPLIT_LINE,
    },
    series: [
      {
        // Diagonal perfect-realization reference line
        type: 'line', data: [[xMin, xMin], [xMax, xMax]],
        lineStyle: { color: '#333', type: 'dashed', width: 1 },
        symbol: 'none', tooltip: { show: false }, silent: true,
      },
      {
        // Break-even horizontal at y=0
        type: 'line', data: [[xMin, 0], [xMax, 0]],
        lineStyle: { color: '#ff4444', type: 'dashed', width: 1 },
        symbol: 'none', tooltip: { show: false }, silent: true,
      },
      {
        name: 'WIN', type: 'scatter', data: wins,
        symbolSize: 6, itemStyle: { color: '#3ecf8e', opacity: 0.75 },
      },
      {
        name: 'LOSS', type: 'scatter', data: losses,
        symbolSize: 6, itemStyle: { color: '#ff4444', opacity: 0.75 },
      },
      {
        name: 'Other', type: 'scatter', data: other,
        symbolSize: 5, itemStyle: { color: '#555', opacity: 0.6 },
      },
    ],
    legend: {
      data: ['WIN', 'LOSS', 'Other'],
      textStyle: { color: '#666', fontSize: 10 },
      right: 0, top: 0,
      itemWidth: 10, itemHeight: 10,
    },
  });
}

function renderSlipDistChart(s) {
  const chart = state.an.slipDist;
  if (!chart || !s) return;

  const buckets = s.buckets || [];
  const counts  = s.counts  || [];

  // Colour: buckets 0-1 (favourable/zero) green, 2-4 (adverse) red
  const coloured = counts.map((v, i) => ({
    value: v,
    itemStyle: { color: i <= 1 ? '#3ecf8e' : '#ff4444' },
  }));

  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 80, right: 16, top: 8, bottom: 8 },
    tooltip: { ..._TOOLTIP, formatter: p => `${p.name}<br/>${p.value} orders` },
    xAxis: {
      type: 'value',
      axisLabel: _AXIS_LABEL,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: _SPLIT_LINE,
      minInterval: 1,
    },
    yAxis: {
      type: 'category', data: buckets,
      axisLabel: { ..._AXIS_LABEL, fontSize: 10 },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      inverse: true,
    },
    series: [{ type: 'bar', data: coloured, barMaxWidth: 22 }],
  });
}

function renderHoldDistChart(ht) {
  const chart = state.an.holdDist;
  if (!chart || !ht) return;

  const buckets = ht.buckets || [];
  const counts  = ht.counts  || [];

  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 80, right: 16, top: 8, bottom: 8 },
    tooltip: { ..._TOOLTIP, formatter: p => `${p.name}<br/>${p.value} positions` },
    xAxis: {
      type: 'value',
      axisLabel: _AXIS_LABEL,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: _SPLIT_LINE,
      minInterval: 1,
    },
    yAxis: {
      type: 'category', data: buckets,
      axisLabel: { ..._AXIS_LABEL, fontSize: 10 },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      inverse: true,
    },
    series: [{
      type: 'bar', data: counts,
      itemStyle: { color: '#d4a853' },
      barMaxWidth: 22,
    }],
  });
}
