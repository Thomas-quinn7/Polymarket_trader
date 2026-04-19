// ── State ───────────────────────────────────────────────────────────────────
const STATE = {
  activeRunId:       null,
  pollTimer:         null,
  equityChart:       null,
  currentRunId:      null,
  tradesPage:        0,
  tradesPageSize:    50,
  tradesTotal:       0,
};

// ── Auth ─────────────────────────────────────────────────────────────────────
function getAuthHeaders() {
  const key = localStorage.getItem('dashboard_api_key');
  return key ? { 'X-API-Key': key } : {};
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function fmt(n, dec = 2) {
  if (n == null) return '—';
  const v = Number(n);
  return '$' + (v >= 0 ? '' : '-') + Math.abs(v).toFixed(dec);
}

function fmtPct(n) {
  if (n == null) return '—';
  return (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%';
}

function fmtNum(n, dec = 4) {
  if (n == null) return '—';
  return Number(n).toFixed(dec);
}

function fmtTs(ts) {
  if (!ts) return '—';
  try { return new Date(ts * 1000).toLocaleString(); } catch { return String(ts); }
}

function fmtDate(s) {
  if (!s) return '—';
  try { return new Date(s).toLocaleDateString(); } catch { return s; }
}

function fmtHold(seconds) {
  if (seconds == null) return '—';
  const s = Math.round(seconds);
  if (s < 60) return s + 's';
  if (s < 3600) return Math.round(s / 60) + 'm';
  return (s / 3600).toFixed(1) + 'h';
}

function badgeClass(status) {
  if (status === 'complete') return 'badge-green';
  if (status === 'error')    return 'badge-red';
  if (status === 'running')  return 'badge-yellow';
  return 'badge-gray';
}

function outcomeClass(outcome) {
  if (!outcome) return '';
  if (outcome === 'WIN')  return 'color:#00ff88';
  if (outcome === 'LOSS') return 'color:#ff6b6b';
  return 'color:#888';
}

// ── Sidebar navigation ────────────────────────────────────────────────────
document.querySelectorAll('[data-section]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('[data-section]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const target = btn.dataset.section;
    document.querySelectorAll('section[id^="section-"]').forEach(s => {
      s.style.display = s.id === `section-${target}` ? '' : 'none';
    });
    if (target === 'history') loadRuns();
  });
});

// ── Init ──────────────────────────────────────────────────────────────────
async function init() {
  await loadStrategies();
  document.getElementById('run-btn').addEventListener('click', startRun);
  document.getElementById('refresh-runs-btn').addEventListener('click', loadRuns);
  document.getElementById('view-results-btn').addEventListener('click', () => {
    // Switch to history tab and select the active run
    document.querySelector('[data-section="history"]').click();
  });
  document.getElementById('trades-prev-btn').addEventListener('click', () => {
    if (STATE.tradesPage > 0) { STATE.tradesPage--; loadTrades(STATE.currentRunId); }
  });
  document.getElementById('trades-next-btn').addEventListener('click', () => {
    const maxPage = Math.floor(STATE.tradesTotal / STATE.tradesPageSize);
    if (STATE.tradesPage < maxPage) { STATE.tradesPage++; loadTrades(STATE.currentRunId); }
  });
}

// ── Strategies dropdown ───────────────────────────────────────────────────
async function loadStrategies() {
  try {
    const res = await fetch('/api/backtest/strategies', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    const sel = document.getElementById('strategy-select');
    sel.innerHTML = '';
    (data.strategies || []).forEach(s => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s;
      sel.appendChild(opt);
    });
  } catch (e) {
    console.warn('Could not load strategies', e);
  }
}

// ── Start a backtest run ──────────────────────────────────────────────────
async function startRun() {
  document.getElementById('run-error').textContent = '';
  const config = {
    strategy_name:        document.getElementById('strategy-select').value,
    start_date:           document.getElementById('start-date').value,
    end_date:             document.getElementById('end-date').value,
    initial_balance:      parseFloat(document.getElementById('initial-balance').value),
    max_positions:        parseInt(document.getElementById('max-positions').value),
    capital_per_trade_pct: parseFloat(document.getElementById('capital-pct').value),
    taker_fee_pct:        parseFloat(document.getElementById('taker-fee').value),
    min_volume_usd:       parseFloat(document.getElementById('min-volume').value),
    max_duration_seconds: parseInt(document.getElementById('max-duration').value),
    price_interval:       document.getElementById('price-interval').value,
    category:             document.getElementById('category').value,
  };

  if (!config.strategy_name) {
    document.getElementById('run-error').textContent = 'Select a strategy first.';
    return;
  }

  try {
    const res = await fetch('/api/backtest/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify(config),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      document.getElementById('run-error').textContent = err.detail || 'Request failed.';
      return;
    }
    const { run_id } = await res.json();
    STATE.activeRunId = run_id;
    showRunStatus('pending', 'Run queued…');
    startPolling(run_id);
  } catch (e) {
    document.getElementById('run-error').textContent = 'Network error: ' + e.message;
  }
}

function showRunStatus(status, msg) {
  const card = document.getElementById('run-status-card');
  card.classList.add('visible');
  const badge = document.getElementById('status-badge');
  badge.textContent = status;
  badge.className = 'badge ' + badgeClass(status);
  document.getElementById('status-msg').textContent = msg || '';
  document.getElementById('view-results-wrap').style.display =
    status === 'complete' ? '' : 'none';
}

// ── Poll run status ────────────────────────────────────────────────────────
function startPolling(run_id) {
  if (STATE.pollTimer) clearInterval(STATE.pollTimer);
  STATE.pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/backtest/runs/${run_id}`, { headers: getAuthHeaders() });
      if (!res.ok) return;
      const run = await res.json();
      const msg = run.status === 'error'
        ? ('Error: ' + (run.error_message || 'unknown'))
        : run.status === 'complete'
          ? `Complete — ${run.trade_count || 0} trades across ${run.market_count || 0} markets`
          : 'Running…';
      showRunStatus(run.status, msg);
      if (run.status === 'complete' || run.status === 'error') {
        clearInterval(STATE.pollTimer);
        STATE.pollTimer = null;
      }
    } catch (e) {
      // network blip — keep polling
    }
  }, 2000);
}

// ── Run history table ─────────────────────────────────────────────────────
async function loadRuns() {
  try {
    const res = await fetch('/api/backtest/runs?limit=50', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    renderRunsTable(data.runs || []);
  } catch (e) {
    console.warn('Could not load runs', e);
  }
}

function renderRunsTable(runs) {
  const tbody = document.getElementById('runs-tbody');
  if (!runs.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; color:#888;">No runs yet.</td></tr>';
    return;
  }
  tbody.innerHTML = runs.map(r => {
    let cfg = {};
    try { cfg = r.config_json ? JSON.parse(r.config_json) : {}; } catch {}
    const range = cfg.start_date && cfg.end_date
      ? `${cfg.start_date} → ${cfg.end_date}`
      : (r.started_at || '').substring(0, 10);
    return `<tr class="clickable" data-run-id="${r.run_id}">
      <td>${r.strategy_name}</td>
      <td style="font-size:0.75rem">${range}</td>
      <td>${r.market_count ?? '—'}</td>
      <td>${r.trade_count ?? '—'}</td>
      <td style="${(r.total_return_pct ?? 0) >= 0 ? 'color:#00ff88' : 'color:#ff6b6b'}">${fmtPct(r.total_return_pct)}</td>
      <td>${fmtNum(r.sharpe_ratio)}</td>
      <td>${r.max_drawdown != null ? fmtNum(r.max_drawdown, 2) + '%' : '—'}</td>
      <td>${r.win_rate != null ? fmtNum(r.win_rate * 100, 1) + '%' : '—'}</td>
      <td><span class="badge ${badgeClass(r.status)}">${r.status}</span></td>
    </tr>`;
  }).join('');

  tbody.querySelectorAll('tr[data-run-id]').forEach(tr => {
    tr.addEventListener('click', () => loadRunDetail(tr.dataset.runId));
  });
}

// ── Run detail ────────────────────────────────────────────────────────────
async function loadRunDetail(run_id) {
  STATE.currentRunId = run_id;
  STATE.tradesPage = 0;
  try {
    const res = await fetch(`/api/backtest/runs/${run_id}`, { headers: getAuthHeaders() });
    if (!res.ok) return;
    const run = await res.json();
    renderDetail(run);
    await loadTrades(run_id);
  } catch (e) {
    console.warn('Could not load run detail', e);
  }
}

function renderDetail(run) {
  const detail = document.getElementById('run-detail');
  detail.classList.add('visible');
  document.getElementById('detail-title').textContent =
    `${run.strategy_name} — ${run.started_at ? run.started_at.substring(0, 10) : ''}`;

  const metrics = run.metrics_json ? JSON.parse(run.metrics_json) : {};
  const grid = document.getElementById('metrics-grid');
  const items = [
    ['Initial Balance', fmt(metrics.initial_balance)],
    ['Final Balance',   fmt(metrics.final_balance)],
    ['Total Return',    fmtPct(metrics.total_return_pct)],
    ['Ann. Return',     fmtPct(metrics.annualized_return)],
    ['Total Trades',    metrics.total_trades ?? '—'],
    ['Win Rate',        metrics.win_rate != null ? fmtNum(metrics.win_rate * 100, 1) + '%' : '—'],
    ['Profit Factor',   fmtNum(metrics.profit_factor)],
    ['Sharpe',          fmtNum(metrics.sharpe_ratio)],
    ['Sortino',         fmtNum(metrics.sortino_ratio)],
    ['Calmar',          fmtNum(metrics.calmar_ratio)],
    ['Max Drawdown',    metrics.max_drawdown != null ? fmtNum(metrics.max_drawdown, 2) + '%' : '—'],
    ['Total Fees',      fmt(metrics.total_fees)],
    ['Fee Drag',        metrics.fee_drag_pct != null ? fmtNum(metrics.fee_drag_pct, 2) + '%' : '—'],
    ['Avg Hold',        fmtHold(metrics.avg_hold_seconds)],
    ['Max Consec Wins', metrics.consec_wins_max ?? '—'],
    ['Max Consec Loss', metrics.consec_losses_max ?? '—'],
  ];
  grid.innerHTML = items.map(([label, val]) => `
    <div class="stat-card">
      <div class="stat-number" style="font-size:1rem;">${val}</div>
      <div class="stat-label">${label}</div>
    </div>`).join('');

  if (run.equity_curve_json) {
    renderEquityChart(run.equity_curve_json);
  }
}

// ── Equity chart ──────────────────────────────────────────────────────────
function renderEquityChart(equityCurveJson) {
  const chartEl = document.getElementById('equity-chart');
  if (!STATE.equityChart) {
    STATE.equityChart = echarts.init(chartEl, 'dark');
  }

  let curve;
  try { curve = JSON.parse(equityCurveJson); } catch { return; }

  // Curve is [[ts, balance], ...] or [{ts, balance}, ...]
  const points = curve.map(p => {
    const ts  = Array.isArray(p) ? p[0] : p.ts;
    const bal = Array.isArray(p) ? p[1] : p.balance;
    return [ts * 1000, parseFloat(Number(bal).toFixed(2))];
  }).filter(p => p[0] > 0);

  STATE.equityChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      formatter: params => {
        const d = new Date(params[0].data[0]);
        return `${d.toLocaleString()}<br/>Balance: $${params[0].data[1]}`;
      },
    },
    xAxis: { type: 'time', splitLine: { show: false } },
    yAxis: { type: 'value', name: 'Balance (USDC)', axisLabel: { formatter: v => '$' + v } },
    series: [{
      name: 'Backtest',
      type: 'line',
      data: points,
      smooth: true,
      showSymbol: false,
      lineStyle: { color: '#00ff88', width: 2 },
      areaStyle: { color: 'rgba(0,255,136,0.05)' },
    }],
    grid: { left: '8%', right: '3%', top: '10%', bottom: '12%' },
  });
}

// ── Trades table ──────────────────────────────────────────────────────────
async function loadTrades(run_id) {
  const offset = STATE.tradesPage * STATE.tradesPageSize;
  try {
    const res = await fetch(
      `/api/backtest/runs/${run_id}/trades?offset=${offset}&limit=${STATE.tradesPageSize}`,
      { headers: getAuthHeaders() }
    );
    if (!res.ok) return;
    const data = await res.json();
    const trades = data.trades || [];
    STATE.tradesTotal = data.total_count ?? (offset + trades.length);

    renderTradesTable(trades);
    document.getElementById('trades-count').textContent = trades.length;
    document.getElementById('trades-page-label').textContent = `Page ${STATE.tradesPage + 1}`;
    document.getElementById('trades-prev-btn').disabled = STATE.tradesPage === 0;
    document.getElementById('trades-next-btn').disabled =
      offset + trades.length >= STATE.tradesTotal;
  } catch (e) {
    console.warn('Could not load trades', e);
  }
}

function renderTradesTable(trades) {
  const tbody = document.getElementById('trades-tbody');
  if (!trades.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; color:#888;">No trades.</td></tr>';
    return;
  }
  tbody.innerHTML = trades.map(t => {
    const hold = t.exit_ts && t.entry_ts ? t.exit_ts - t.entry_ts : null;
    const pnlColor = (t.net_pnl ?? 0) >= 0 ? 'color:#00ff88' : 'color:#ff6b6b';
    const question = (t.question || t.condition_id || '').substring(0, 40);
    return `<tr>
      <td title="${t.question || ''}">${question}…</td>
      <td style="font-size:0.75rem">${fmtTs(t.entry_ts)}</td>
      <td style="font-size:0.75rem">${fmtTs(t.exit_ts)}</td>
      <td>${fmtNum(t.entry_price)}</td>
      <td>${fmtNum(t.exit_price)}</td>
      <td style="${pnlColor}">${fmt(t.net_pnl)}</td>
      <td>${fmt((t.entry_fee || 0) + (t.exit_fee || 0))}</td>
      <td style="${outcomeClass(t.outcome)}">${t.outcome || '—'}</td>
      <td>${fmtHold(hold)}</td>
    </tr>`;
  }).join('');
}

// ── Boot ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
