"""
SQLite persistence layer.
Stores positions, trade records, and PnL history so data survives restarts.

All writes are non-fatal — the trading loop continues if the DB is unavailable.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    position_id         TEXT PRIMARY KEY,
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
    status              TEXT DEFAULT 'OPEN',
    opened_at           TEXT,
    settled_at          TEXT,
    settlement_price    REAL,
    realized_pnl        REAL
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id            TEXT PRIMARY KEY,
    position_id         TEXT NOT NULL,
    market_id           TEXT NOT NULL,
    action              TEXT,
    quantity            REAL,
    entry_price         REAL,
    exit_price          REAL,
    entry_time          TEXT,
    exit_time           TEXT,
    pnl                 REAL,
    pnl_percent         REAL
);

CREATE TABLE IF NOT EXISTS pnl_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at         TEXT NOT NULL,
    balance             REAL NOT NULL,
    pnl                 REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_positions_status   ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_opened   ON positions(opened_at);
CREATE INDEX IF NOT EXISTS idx_trades_position    ON trades(position_id);
CREATE INDEX IF NOT EXISTS idx_trades_exit        ON trades(exit_time);
CREATE INDEX IF NOT EXISTS idx_pnl_recorded       ON pnl_history(recorded_at);
"""


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
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
            logger.info("TradeDatabase ready: %s", self._db_path)
            return True
        except Exception as e:
            logger.warning("TradeDatabase failed to connect: %s", e)
            self._conn = None
            return False

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
            self._conn.execute(
                """
                INSERT INTO positions VALUES (
                    :position_id, :market_id, :market_slug, :question,
                    :token_id_yes, :token_id_no, :winning_token_id,
                    :shares, :entry_price, :allocated_capital,
                    :expected_profit, :edge_percent, :status,
                    :opened_at, :settled_at, :settlement_price, :realized_pnl
                )
                ON CONFLICT(position_id) DO UPDATE SET
                    status           = excluded.status,
                    settled_at       = excluded.settled_at,
                    settlement_price = excluded.settlement_price,
                    realized_pnl     = excluded.realized_pnl
                """,
                d,
            )
            self._conn.commit()
            return True
        except Exception as e:
            logger.warning("DB upsert_position failed: %s", e)
            return False

    def upsert_trade(self, trade) -> bool:
        """
        Insert or update a trade.
        Accepts a TradeRecord dataclass (from utils/pnl_tracker.py).
        On conflict only the mutable exit fields are updated.
        """
        if self._conn is None:
            return False
        try:
            d = trade.to_dict()
            self._conn.execute(
                """
                INSERT INTO trades VALUES (
                    :trade_id, :position_id, :market_id, :action,
                    :quantity, :entry_price, :exit_price,
                    :entry_time, :exit_time, :pnl, :pnl_percent
                )
                ON CONFLICT(trade_id) DO UPDATE SET
                    exit_price  = excluded.exit_price,
                    exit_time   = excluded.exit_time,
                    pnl         = excluded.pnl,
                    pnl_percent = excluded.pnl_percent
                """,
                d,
            )
            self._conn.commit()
            return True
        except Exception as e:
            logger.warning("DB upsert_trade failed: %s", e)
            return False

    def add_pnl_snapshot(self, balance: float, pnl: float) -> bool:
        """Append a balance/PnL data point to the history table."""
        if self._conn is None:
            return False
        try:
            from datetime import datetime

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

    def get_positions(self, status: Optional[str] = None) -> List[Dict]:
        """Return positions ordered newest-first. Filter by status if given."""
        if self._conn is None:
            return []
        try:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM positions WHERE status = ? ORDER BY opened_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM positions ORDER BY opened_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("DB get_positions failed: %s", e)
            return []

    def get_trades(self, limit: Optional[int] = None) -> List[Dict]:
        """Return closed trades ordered most-recent first."""
        if self._conn is None:
            return []
        try:
            q = "SELECT * FROM trades WHERE exit_time IS NOT NULL ORDER BY exit_time DESC"
            if limit:
                q += f" LIMIT {int(limit)}"
            return [dict(r) for r in self._conn.execute(q).fetchall()]
        except Exception as e:
            logger.warning("DB get_trades failed: %s", e)
            return []

    def get_all_trades(self, limit: Optional[int] = None) -> List[Dict]:
        """Return all trades (open + closed) ordered most-recent first."""
        if self._conn is None:
            return []
        try:
            q = "SELECT * FROM trades ORDER BY entry_time DESC"
            if limit:
                q += f" LIMIT {int(limit)}"
            return [dict(r) for r in self._conn.execute(q).fetchall()]
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
