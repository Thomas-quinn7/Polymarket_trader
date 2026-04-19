# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bt_markets (
    condition_id     TEXT PRIMARY KEY,
    slug             TEXT NOT NULL,
    question         TEXT NOT NULL,
    category         TEXT NOT NULL,
    volume           REAL NOT NULL,
    end_time         TEXT NOT NULL,
    created_at       TEXT,
    resolution       REAL,
    token_id_yes     TEXT,
    token_id_no      TEXT,
    duration_seconds INTEGER,
    fetched_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bt_markets_end ON bt_markets(end_time);
CREATE INDEX IF NOT EXISTS idx_bt_markets_cat ON bt_markets(category, end_time);
CREATE INDEX IF NOT EXISTS idx_bt_markets_dur ON bt_markets(duration_seconds);

CREATE TABLE IF NOT EXISTS bt_price_history (
    condition_id     TEXT    NOT NULL,
    ts               INTEGER NOT NULL,
    price            REAL    NOT NULL,
    PRIMARY KEY (condition_id, ts),
    FOREIGN KEY (condition_id) REFERENCES bt_markets(condition_id)
);

CREATE INDEX IF NOT EXISTS idx_bt_price_ts ON bt_price_history(condition_id, ts);

CREATE TABLE IF NOT EXISTS bt_runs (
    run_id               TEXT PRIMARY KEY,
    strategy_name        TEXT NOT NULL,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    status               TEXT NOT NULL,
    config_json          TEXT NOT NULL,
    market_count         INTEGER DEFAULT 0,
    trade_count          INTEGER DEFAULT 0,
    total_net_pnl        REAL,
    total_return_pct     REAL,
    annualized_return    REAL,
    max_drawdown         REAL,
    sharpe_ratio         REAL,
    sortino_ratio        REAL,
    calmar_ratio         REAL,
    win_rate             REAL,
    profit_factor        REAL,
    avg_hold_seconds     REAL,
    fee_drag_pct         REAL,
    consec_wins_max      INTEGER,
    consec_losses_max    INTEGER,
    metrics_json         TEXT,
    equity_curve_json    TEXT,
    error_message        TEXT
);

CREATE TABLE IF NOT EXISTS bt_run_trades (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL,
    strategy_name     TEXT NOT NULL,
    condition_id      TEXT NOT NULL,
    question          TEXT,
    entry_ts          INTEGER NOT NULL,
    exit_ts           INTEGER,
    entry_price       REAL NOT NULL,
    exit_price        REAL,
    shares            REAL NOT NULL,
    allocated_capital REAL NOT NULL,
    side              TEXT NOT NULL,
    gross_pnl         REAL,
    net_pnl           REAL,
    entry_fee         REAL DEFAULT 0.0,
    exit_fee          REAL DEFAULT 0.0,
    outcome           TEXT,
    exit_reason       TEXT,
    FOREIGN KEY (run_id) REFERENCES bt_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_bt_run_trades_run ON bt_run_trades(run_id);
CREATE INDEX IF NOT EXISTS idx_bt_run_trades_ts  ON bt_run_trades(run_id, entry_ts);
"""


class BacktestDB:
    """
    Thread-safe SQLite wrapper for backtest data.
    Pattern identical to SessionStore and TradeDatabase — raw sqlite3 + threading.Lock.
    """

    def __init__(self, db_path: str = "storage/backtest.db"):
        self._path = db_path
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Market cache ──────────────────────────────────────────────────────────

    def upsert_market(self, market: dict):
        """Insert or ignore a market row. Cache-first — never overwrites existing."""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO bt_markets
                  (condition_id, slug, question, category, volume, end_time,
                   created_at, resolution, token_id_yes, token_id_no,
                   duration_seconds, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    market["condition_id"],
                    market["slug"],
                    market["question"],
                    market["category"],
                    market["volume"],
                    market["end_time"],
                    market.get("created_at"),
                    market.get("resolution"),
                    market.get("token_id_yes"),
                    market.get("token_id_no"),
                    market.get("duration_seconds"),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()

    def get_markets_in_range(
        self,
        start_iso: str,
        end_iso: str,
        category: str = None,
        max_duration_s: int = None,
        min_volume: float = 0.0,
    ) -> List[sqlite3.Row]:
        """Return cached markets matching the given filters."""
        sql = "SELECT * FROM bt_markets WHERE end_time >= ? AND end_time <= ?"
        params: list = [start_iso, end_iso]
        if category:
            sql += " AND category = ?"
            params.append(category)
        if max_duration_s and max_duration_s > 0:
            sql += " AND (duration_seconds IS NULL OR duration_seconds <= ?)"
            params.append(max_duration_s)
        if min_volume > 0:
            sql += " AND volume >= ?"
            params.append(min_volume)
        sql += " ORDER BY end_time ASC"
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def count_markets_in_range(self, start_iso: str, end_iso: str, category: str = None) -> int:
        sql = "SELECT COUNT(*) FROM bt_markets WHERE end_time >= ? AND end_time <= ?"
        params: list = [start_iso, end_iso]
        if category:
            sql += " AND category = ?"
            params.append(category)
        with self._lock:
            return self._conn.execute(sql, params).fetchone()[0]

    # ── Price history ─────────────────────────────────────────────────────────

    def insert_price_history(self, condition_id: str, ticks: List[Tuple[int, float]]):
        """Bulk insert price history ticks. INSERT OR IGNORE — safe to re-run."""
        with self._lock:
            self._conn.executemany(
                "INSERT OR IGNORE INTO bt_price_history (condition_id, ts, price) VALUES (?,?,?)",
                [(condition_id, ts, price) for ts, price in ticks],
            )
            self._conn.commit()

    def get_price_history(self, condition_id: str) -> List[Tuple[int, float]]:
        """Return sorted (ts, price) list for a market."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, price FROM bt_price_history WHERE condition_id = ? ORDER BY ts",
                (condition_id,),
            ).fetchall()
        return [(r["ts"], r["price"]) for r in rows]

    def has_price_history(self, condition_id: str) -> bool:
        with self._lock:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM bt_price_history WHERE condition_id = ?",
                (condition_id,),
            ).fetchone()[0]
        return count >= 3

    # ── Run lifecycle ─────────────────────────────────────────────────────────

    def create_run(self, run_id: str, strategy_name: str, config_json: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bt_runs (run_id, strategy_name, started_at, status, config_json)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (run_id, strategy_name, datetime.now(timezone.utc).isoformat(), config_json),
            )
            self._conn.commit()

    def update_run_status(self, run_id: str, status: str, error_message: str = None):
        with self._lock:
            if status in ("complete", "error"):
                self._conn.execute(
                    """
                    UPDATE bt_runs SET status=?, finished_at=?, error_message=?
                    WHERE run_id=?
                    """,
                    (
                        status,
                        datetime.now(timezone.utc).isoformat(),
                        error_message,
                        run_id,
                    ),
                )
            else:
                self._conn.execute("UPDATE bt_runs SET status=? WHERE run_id=?", (status, run_id))
            self._conn.commit()

    def save_run_results(
        self,
        run_id: str,
        market_count: int,
        trade_count: int,
        metrics: dict,
        equity_curve: list,
    ):
        """Flatten scalar metrics into columns and save blobs."""
        with self._lock:
            self._conn.execute(
                """
                UPDATE bt_runs SET
                    market_count=?, trade_count=?,
                    total_net_pnl=?, total_return_pct=?, annualized_return=?,
                    max_drawdown=?, sharpe_ratio=?, sortino_ratio=?, calmar_ratio=?,
                    win_rate=?, profit_factor=?, avg_hold_seconds=?,
                    fee_drag_pct=?, consec_wins_max=?, consec_losses_max=?,
                    metrics_json=?, equity_curve_json=?,
                    status='complete', finished_at=?
                WHERE run_id=?
                """,
                (
                    market_count,
                    trade_count,
                    metrics.get("total_net_pnl"),
                    metrics.get("total_return_pct"),
                    metrics.get("annualized_return"),
                    metrics.get("max_drawdown"),
                    metrics.get("sharpe_ratio"),
                    metrics.get("sortino_ratio"),
                    metrics.get("calmar_ratio"),
                    metrics.get("win_rate"),
                    metrics.get("profit_factor"),
                    metrics.get("avg_hold_seconds"),
                    metrics.get("fee_drag_pct"),
                    metrics.get("consec_wins_max"),
                    metrics.get("consec_losses_max"),
                    json.dumps(metrics),
                    json.dumps(equity_curve),
                    datetime.now(timezone.utc).isoformat(),
                    run_id,
                ),
            )
            self._conn.commit()

    def insert_run_trades(self, run_id: str, trades: list):
        """Bulk insert simulated trades for a completed run."""
        with self._lock:
            self._conn.executemany(
                """
                INSERT INTO bt_run_trades
                  (run_id, strategy_name, condition_id, question,
                   entry_ts, exit_ts, entry_price, exit_price,
                   shares, allocated_capital, side,
                   gross_pnl, net_pnl, entry_fee, exit_fee,
                   outcome, exit_reason)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        run_id,
                        t["strategy_name"],
                        t["condition_id"],
                        t.get("question"),
                        t["entry_ts"],
                        t.get("exit_ts"),
                        t["entry_price"],
                        t.get("exit_price"),
                        t["shares"],
                        t["allocated_capital"],
                        t.get("side", "YES"),
                        t.get("gross_pnl"),
                        t.get("net_pnl"),
                        t.get("entry_fee", 0.0),
                        t.get("exit_fee", 0.0),
                        t.get("outcome"),
                        t.get("exit_reason"),
                    )
                    for t in trades
                ],
            )
            self._conn.commit()

    # ── Query helpers ─────────────────────────────────────────────────────────

    def get_runs(self, limit: int = 20, strategy_name: str = None) -> List[sqlite3.Row]:
        sql = """SELECT run_id, strategy_name, started_at, finished_at, status,
                        market_count, trade_count, total_net_pnl, total_return_pct,
                        annualized_return, max_drawdown, sharpe_ratio, win_rate,
                        profit_factor, consec_wins_max, consec_losses_max, config_json
                 FROM bt_runs"""
        params: list = []
        if strategy_name:
            sql += " WHERE strategy_name = ?"
            params.append(strategy_name)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def get_run(self, run_id: str) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM bt_runs WHERE run_id = ?", (run_id,)
            ).fetchone()

    def get_run_trades(self, run_id: str, offset: int = 0, limit: int = 100) -> List[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM bt_run_trades WHERE run_id = ? ORDER BY entry_ts LIMIT ? OFFSET ?",
                (run_id, limit, offset),
            ).fetchall()

    def count_run_trades(self, run_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM bt_run_trades WHERE run_id = ?", (run_id,)
            ).fetchone()
            return row[0] if row else 0
