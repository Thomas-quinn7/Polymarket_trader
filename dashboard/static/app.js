// API base URL
const API_BASE = 'http://localhost:8080/api';

// State
let refreshInterval = null;
const REFRESH_RATE = 5000; // 5 seconds

// Initialize dashboard
async function initDashboard() {
    console.log('Initializing dashboard...');

    // Start auto-refresh
    startAutoRefresh();

    // Initial data load
    await loadAllData();
}

// Start auto-refresh
function startAutoRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }

    refreshInterval = setInterval(async () => {
        await loadAllData();
    }, REFRESH_RATE);

    console.log(`Auto-refresh started (${REFRESH_RATE / 1000}s interval)`);
}

// Load all data
async function loadAllData() {
    try {
        await Promise.all([
            loadStatus(),
            loadPnL(),
            loadPositions(),
            loadTrades(),
        ]);
    } catch (error) {
        console.error('Error loading data:', error);
    }
}

// Load status
async function loadStatus() {
    try {
        const response = await fetch(`${API_BASE}/status`);
        const data = await response.json();

        // Update status badge
        const statusBadge = document.getElementById('statusBadge');
        const statusIcon = document.getElementById('statusIcon');
        const statusText = document.getElementById('statusText');

        if (data.running) {
            statusBadge.className = 'status-badge running';
            statusIcon.textContent = '🟢';
            statusText.textContent = 'Running';
        } else {
            statusBadge.className = 'status-badge stopped';
            statusIcon.textContent = '🔴';
            statusText.textContent = 'Stopped';
        }

        // Update system status
        document.getElementById('uptime').textContent = data.uptime;
        document.getElementById('lastUpdate').textContent = formatDateTime(data.last_update);
        document.getElementById('positionCount').textContent = `${data.open_positions}/${data.max_positions}`;

    } catch (error) {
        console.error('Error loading status:', error);
    }
}

// Load P&L
async function loadPnL() {
    try {
        const response = await fetch(`${API_BASE}/pnl`);
        const data = await response.json();

        // Update P&L display
        const totalPnl = document.getElementById('totalPnl');
        totalPnl.textContent = formatCurrency(data.total_pnl);
        totalPnl.className = `value ${data.total_pnl >= 0 ? 'positive' : 'negative'}`;

        document.getElementById('winRate').textContent = `${data.win_rate.toFixed(1)}%`;
        document.getElementById('totalTrades').textContent = data.total_trades;
        document.getElementById('drawdown').textContent = `${data.current_drawdown.toFixed(2)}%`;

    } catch (error) {
        console.error('Error loading P&L:', error);
    }
}

// Load portfolio
async function loadPortfolio() {
    try {
        const response = await fetch(`${API_BASE}/portfolio`);
        const data = await response.json();

        // Update portfolio display
        const balance = document.getElementById('balance');
        balance.textContent = formatCurrency(data.balance);

        document.getElementById('deployed').textContent = formatCurrency(data.deployed);

    } catch (error) {
        console.error('Error loading portfolio:', error);
    }
}

// Load positions
async function loadPositions() {
    try {
        const response = await fetch(`${API_BASE}/positions?status=open`);
        const positions = await response.json();

        const positionsTable = document.getElementById('positionsTable');

        if (positions.length === 0) {
            positionsTable.innerHTML = '<div class="empty-state">No open positions</div>';
            return;
        }

        // Create table
        let html = `
            <div class="table-row header">
                <div class="table-cell">Market</div>
                <div class="table-cell">Shares</div>
                <div class="table-cell">Entry</div>
                <div class="table-cell">Expected P&L</div>
                <div class="table-cell">Edge</div>
            </div>
        `;

        positions.forEach(pos => {
            const expectedPnlClass = pos.expected_profit >= 0 ? 'positive' : 'negative';
            html += `
                <div class="table-row">
                    <div class="table-cell">
                        <strong>${pos.market_slug}</strong><br>
                        <small>${truncateText(pos.question, 50)}</small>
                    </div>
                    <div class="table-cell">${pos.shares.toFixed(4)}</div>
                    <div class="table-cell">$${pos.entry_price.toFixed(4)}</div>
                    <div class="table-cell ${expectedPnlClass}">${formatCurrency(pos.expected_profit)}</div>
                    <div class="table-cell">${pos.edge_percent.toFixed(2)}%</div>
                </div>
            `;
        });

        positionsTable.innerHTML = html;

    } catch (error) {
        console.error('Error loading positions:', error);
    }
}

// Load trades
async function loadTrades() {
    try {
        const response = await fetch(`${API_BASE}/trades?limit=20`);
        const trades = await response.json();

        const tradesTable = document.getElementById('tradesTable');

        if (trades.length === 0) {
            tradesTable.innerHTML = '<div class="empty-state">No trades yet</div>';
            return;
        }

        // Create table
        let html = `
            <div class="table-row header">
                <div class="table-cell">Time</div>
                <div class="table-cell">Action</div>
                <div class="table-cell">Market</div>
                <div class="table-cell">Price</div>
                <div class="table-cell">Total</div>
            </div>
        `;

        trades.forEach(trade => {
            const actionClass = trade.action.toLowerCase();
            const pnlText = trade.pnl !== null ? formatCurrency(trade.pnl) : '-';
            const pnlClass = trade.pnl !== null ? (trade.pnl >= 0 ? 'positive' : 'negative') : '';

            html += `
                <div class="table-row">
                    <div class="table-cell">${formatTime(trade.executed_at)}</div>
                    <div class="table-cell ${actionClass}">${trade.action}</div>
                    <div class="table-cell">${trade.market_slug}</div>
                    <div class="table-cell">$${trade.price.toFixed(4)}</div>
                    <div class="table-cell">${formatCurrency(trade.total)}</div>
                </div>
            `;
        });

        tradesTable.innerHTML = html;

    } catch (error) {
        console.error('Error loading trades:', error);
    }
}

// Utility functions
function formatCurrency(value) {
    if (value === null || value === undefined) return '$0.00';
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(value);
}

function formatTime(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

function formatDateTime(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

function truncateText(text, maxLength) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initDashboard();
});
