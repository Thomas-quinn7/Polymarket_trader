"""
SQLite persistence layer.
Stores positions, trade records, and PnL history so data survives restarts.

All writes are non-fatal — the trading loop continues if the DB is unavailable.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    position_id         TEXT PRIMARY KEY,
    strategy_name       TEXT NOT NULL DEFAULT '',
    market_id           TEXT NOT NULL,
    market_slug         TEXT NOT NULL,
    question            TEXT,
    token_id_yes        TEXT,
    token_id_no         TEXT,
    winning_token_id    TEXT,
    shares              REAL,
    entry_price         REAL,
    allocated_capital   REAL,
    expected_profit     REAL,
    edge_percent        REAL,
    entry_fee           REAL DEFAULT 0.0,
    exit_fee            REAL DEFAULT 0.0,
    neg_risk            BOOLEAN DEFAULT 0,
    status              TEXT DEFAULT 'OPEN',
    opened_at           TEXT,
    settled_at          TEXT,
    settlement_price    REAL,
    realized_pnl        REAL
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id            TEXT PRIMARY KEY,
    strategy_name       TEXT NOT NULL DEFAULT '',
    position_id         TEXT NOT NULL,
    market_id           TEXT NOT NULL,
    action              TEXT,
    quantity            REAL,
    entry_price         REAL,
    exit_price          REAL,
    entry_time          TEXT,
    exit_time           TEXT,
    pnl                 REAL,
    pnl_percent         REAL,
    gross_pnl           REAL,
    entry_fee           REAL DEFAULT 0.0,
    exit_fee            REAL DEFAULT 0.0,
    slippage_pct        REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS pnl_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at         TEXT NOT NULL,
    balance             REAL NOT NULL,
    pnl                 REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_positions_status    ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_opened    ON positions(opened_at);
CREATE INDEX IF NOT EXISTS idx_positions_strategy  ON positions(strategy_name);
CREATE INDEX IF NOT EXISTS idx_trades_position     ON trades(position_id);
CREATE INDEX IF NOT EXISTS idx_trades_exit         ON trades(exit_time);
CREATE INDEX IF NOT EXISTS idx_trades_strategy     ON trades(strategy_name);
CREATE INDEX IF NOT EXISTS idx_pnl_recorded        ON pnl_history(recorded_at);
"""

# Columns added after initial schema release — applied as safe migrations.
_MIGRATIONS = [
    "ALTER TABLE positions ADD COLUMN strategy_name TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE trades    ADD COLUMN strategy_name TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE positions ADD COLUMN neg_risk BOOLEAN DEFAULT 0",
    "ALTER TABLE positions ADD COLUMN category TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE positions ADD COLUMN slippage_pct REAL DEFAULT 0.0",
    "ALTER TABLE trades    ADD COLUMN gross_pnl REAL",
    "ALTER TABLE trades    ADD COLUMN entry_fee REAL DEFAULT 0.0",
    "ALTER TABLE trades    ADD COLUMN exit_fee REAL DEFAULT 0.0",
    "ALTER TABLE trades    ADD COLUMN slippage_pct REAL DEFAULT 0.0",
]


class TradeDatabase:
    """
    SQLite-backed store for positions, trades, and PnL snapshots.

    The database file is created automatically on first connect.
    SQLite is embedded — no separate process or container required;
    in Docker the file is written to a mounted host volume so it persists
    across container restarts.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    # ── Lifecycle ──────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Open (or create) the database and apply schema. Returns False on error."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            self._conn.row_factory = sqlite3.Row
            # Migrations run first: they add any missing columns to existing
            # tables so that the subsequent executescript (which creates indexes
            # referencing those columns) does not fail on old databases.
            self._migrate()
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
            logger.info("TradeDatabase ready: %s", self._db_path)
            return True
        except Exception as e:
            logger.warning("TradeDatabase failed to connect: %s", e)
            self._conn = None
            return False

    def _migrate(self):
        """Apply additive schema changes that are safe on existing databases."""
        for stmt in _MIGRATIONS:
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists — nothing to do

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Writes ─────────────────────────────────────────────────────────

    def upsert_position(self, position) -> bool:
        """
        Insert or update a position.
        Accepts a Position dataclass (from portfolio/position_tracker.py).
        On conflict only the mutable settlement fields are updated.
        """
        if self._conn is None:
            return False
        try:
            d = position.to_dict()
            with self._lock:
                self._conn.execute(
                    """
                    INSERT INTO positions (
                        position_id, strategy_name, market_id, market_slug, question,
                        token_id_yes, token_id_no, winning_token_id,
                        shares, entry_price, allocated_capital,
                        expected_profit, edge_percent, neg_risk,
                        category, slippage_pct, entry_fee, exit_fee,
                        status, opened_at, settled_at, settlement_price, realized_pnl
                    ) VALUES (
                        :position_id, :strategy_name, :market_id, :market_slug, :question,
                        :token_id_yes, :token_id_no, :winning_token_id,
                        :shares, :entry_price, :allocated_capital,
                        :expected_profit, :edge_percent, :neg_risk,
                        :category, :slippage_pct, :entry_fee, :exit_fee,
                        :status, :opened_at, :settled_at, :settlement_price, :realized_pnl
                    )
                    ON CONFLICT(position_id) DO UPDATE SET
                        status           = excluded.status,
                        settled_at       = excluded.settled_at,
                        settlement_price = excluded.settlement_price,
                        exit_fee         = excluded.exit_fee,
                        realized_pnl     = excluded.realized_pnl
                    """,
                    d,
                )
                self._conn.commit()
            return True
        except Exception as e:
            logger.warning("DB upsert_position failed: %s", e)
            return False

    def upsert_trade(self, trade, strategy_name: str = "") -> bool:
        """
        Insert or update a trade.
        Accepts a TradeRecord dataclass (from utils/pnl_tracker.py).
        On conflict only the mutable exit fields are updated.
        """
        if self._conn is None:
            return False
        try:
            d = trade.to_dict()
            d["strategy_name"] = strategy_name
            with self._lock:
                self._conn.execute(
                    """
                    INSERT INTO trades (
                        trade_id, strategy_name, position_id, market_id, action,
                        quantity, entry_price, exit_price,
                        entry_time, exit_time,
                        pnl, pnl_percent, gross_pnl,
                        entry_fee, exit_fee, slippage_pct
                    ) VALUES (
                        :trade_id, :strategy_name, :position_id, :market_id, :action,
                        :quantity, :entry_price, :exit_price,
                        :entry_time, :exit_time,
                        :pnl, :pnl_percent, :gross_pnl,
                        :entry_fee, :exit_fee, :slippage_pct
                    )
                    ON CONFLICT(trade_id) DO UPDATE SET
                        exit_price  = excluded.exit_price,
                        exit_time   = excluded.exit_time,
                        pnl         = excluded.pnl,
                        pnl_percent = excluded.pnl_percent,
                        gross_pnl   = excluded.gross_pnl,
                        exit_fee    = excluded.exit_fee
                    """,
                    d,
                )
                self._conn.commit()
            return True
        except Exception as e:
            logger.warning("DB upsert_trade failed: %s", e)
            return False

    def update_position_status(self, position_id: str, status: str) -> bool:
        """Lightweight status update — no full Position dataclass required."""
        if self._conn is None:
            return False
        try:
            with self._lock:
                self._conn.execute(
                    "UPDATE positions SET status = ? WHERE position_id = ?",
                    (status, position_id),
                )
                self._conn.commit()
            return True
        except Exception as e:
            logger.warning("DB update_position_status failed: %s", e)
            return False

    def add_pnl_snapshot(self, balance: float, pnl: float) -> bool:
        """Append a balance/PnL data point to the history table."""
        if self._conn is None:
            return False
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO pnl_history (recorded_at, balance, pnl) VALUES (?, ?, ?)",
                    (datetime.now().isoformat(), balance, pnl),
                )
                self._conn.commit()
            return True
        except Exception as e:
            logger.warning("DB add_pnl_snapshot failed: %s", e)
            return False

    # ── Reads ──────────────────────────────────────────────────────────

    def get_positions(
        self,
        status: Optional[str] = None,
        strategy_name: Optional[str] = None,
    ) -> List[Dict]:
        """Return positions ordered newest-first. Filter by status and/or strategy_name."""
        if self._conn is None:
            return []
        try:
            clauses, params = [], []
            if status:
                clauses.append("status = ?")
                params.append(status)
            if strategy_name:
                clauses.append("strategy_name = ?")
                params.append(strategy_name)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = self._conn.execute(
                f"SELECT * FROM positions {where} ORDER BY opened_at DESC",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("DB get_positions failed: %s", e)
            return []

    def get_trades(
        self,
        limit: Optional[int] = None,
        strategy_name: Optional[str] = None,
    ) -> List[Dict]:
        """Return closed trades ordered most-recent first. Filter by strategy_name."""
        if self._conn is None:
            return []
        try:
            clauses = ["exit_time IS NOT NULL"]
            params: list = []
            if strategy_name:
                clauses.append("strategy_name = ?")
                params.append(strategy_name)
            where = f"WHERE {' AND '.join(clauses)}"
            q = f"SELECT * FROM trades {where} ORDER BY exit_time DESC"
            if limit:
                q += f" LIMIT {int(limit)}"
            return [dict(r) for r in self._conn.execute(q, params).fetchall()]
        except Exception as e:
            logger.warning("DB get_trades failed: %s", e)
            return []

    def get_all_trades(
        self,
        limit: Optional[int] = None,
        strategy_name: Optional[str] = None,
    ) -> List[Dict]:
        """Return all trades (open + closed) ordered most-recent first. Filter by strategy_name."""
        if self._conn is None:
            return []
        try:
            params: list = []
            if strategy_name:
                where = "WHERE strategy_name = ?"
                params.append(strategy_name)
            else:
                where = ""
            q = f"SELECT * FROM trades {where} ORDER BY entry_time DESC"
            if limit:
                q += f" LIMIT {int(limit)}"
            return [dict(r) for r in self._conn.execute(q, params).fetchall()]
        except Exception as e:
            logger.warning("DB get_all_trades failed: %s", e)
            return []

    def get_pnl_history(self, limit: Optional[int] = None) -> List[Dict]:
        """Return PnL history ordered chronologically."""
        if self._conn is None:
            return []
        try:
            q = "SELECT recorded_at, balance, pnl FROM pnl_history ORDER BY id"
            if limit:
                q += f" LIMIT {int(limit)}"
            return [dict(r) for r in self._conn.execute(q).fetchall()]
        except Exception as e:
            logger.warning("DB get_pnl_history failed: %s", e)
            return []
