"""
Session Store — persists per-strategy session summaries and settled trade records.

Each bot run creates one session. Only settled trades are recorded (open positions
at shutdown are excluded). Data is stored in two places:

  - SQLite (strategy_sessions + session_trades tables) — queryable, algo-friendly
  - JSON export in SESSIONS_DIR — chart-ready, one self-contained file per session

JSON layout
-----------
  session      — metadata (id, strategy, times, mode, balance)
  stats        — aggregate metrics (win rate, PnL, hold times, fees, etc.)
  equity_curve — time-indexed balance snapshots for charting the P&L curve
  trades       — one dict per settled trade with every field
  ollama_review — natural language review (written in after generation)
"""

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config.polymarket_config import config
from utils.logger import logger


class SessionStore:
    """
    Persists strategy session data for post-session review and algo reprocessing.

    All public methods are non-fatal — failures are logged and swallowed so the
    trading loop is never blocked by a storage error.
    """

    _CREATE_SESSIONS_TABLE = """
    CREATE TABLE IF NOT EXISTS strategy_sessions (
        session_id        TEXT PRIMARY KEY,
        strategy_name     TEXT NOT NULL,
        start_time        TEXT NOT NULL,
        end_time          TEXT,
        trading_mode      TEXT NOT NULL,
        starting_balance  REAL NOT NULL,
        ending_balance    REAL,
        total_trades      INTEGER DEFAULT 0,
        winning_trades    INTEGER DEFAULT 0,
        losing_trades     INTEGER DEFAULT 0,
        break_even_trades INTEGER DEFAULT 0,
        total_gross_pnl   REAL DEFAULT 0.0,
        total_net_pnl     REAL DEFAULT 0.0,
        total_fees        REAL DEFAULT 0.0,
        win_rate          REAL DEFAULT 0.0,
        profit_factor     REAL,
        avg_hold_seconds  REAL,
        avg_edge_pct      REAL,
        avg_entry_price   REAL,
        best_trade_pnl    REAL,
        worst_trade_pnl   REAL,
        ollama_review     TEXT,
        ollama_model      TEXT
    )
    """

    _CREATE_TRADES_TABLE = """
    CREATE TABLE IF NOT EXISTS session_trades (
        trade_id          TEXT PRIMARY KEY,
        session_id        TEXT NOT NULL,
        strategy_name     TEXT NOT NULL,
        position_id       TEXT NOT NULL,
        market_id         TEXT NOT NULL,
        market_slug       TEXT NOT NULL,
        question          TEXT,
        entry_time        TEXT NOT NULL,
        exit_time         TEXT,
        hold_seconds      REAL,
        entry_price       REAL NOT NULL,
        exit_price        REAL,
        edge_pct          REAL NOT NULL,
        shares            REAL NOT NULL,
        allocated_capital REAL NOT NULL,
        entry_fee         REAL DEFAULT 0.0,
        exit_fee          REAL DEFAULT 0.0,
        gross_pnl         REAL,
        net_pnl           REAL,
        outcome           TEXT,
        exit_reason       TEXT,
        balance_after     REAL,
        winning_token_id  TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES strategy_sessions(session_id)
    )
    """

    def __init__(self, db_path: str, sessions_dir: str):
        self._db_path = db_path
        self._sessions_dir = Path(sessions_dir)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """Open the SQLite connection and create tables if needed. Returns False on failure."""
        try:
            self._sessions_dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            with self._lock:
                self._conn.execute(self._CREATE_SESSIONS_TABLE)
                self._conn.execute(self._CREATE_TRADES_TABLE)
                self._conn.commit()
            logger.info(
                "SessionStore connected (db=%s, export_dir=%s)",
                self._db_path,
                self._sessions_dir,
            )
            return True
        except Exception as exc:
            logger.warning("SessionStore failed to connect: %s", exc)
            self._conn = None
            return False

    # ── Session lifecycle ──────────────────────────────────────────────

    def create_session(self, strategy_name: str, trading_mode: str, starting_balance: float) -> str:
        """
        Insert a new session row and return its session_id.

        Returns a valid UUID even when the DB is unavailable so callers never
        need to branch on None.
        """
        session_id = str(uuid.uuid4())
        if self._conn is None:
            return session_id
        try:
            start_time = datetime.now().isoformat()
            with self._lock:
                self._conn.execute(
                    """
                    INSERT INTO strategy_sessions
                        (session_id, strategy_name, start_time, trading_mode, starting_balance)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, strategy_name, start_time, trading_mode, starting_balance),
                )
                self._conn.commit()
            logger.info(
                "Session started: %s (strategy=%s, mode=%s)",
                session_id[:8],
                strategy_name,
                trading_mode,
            )
        except Exception as exc:
            logger.warning("SessionStore.create_session failed: %s", exc)
        return session_id

    def record_settled_trade(
        self,
        session_id: str,
        position,
        balance_after: float,
        exit_reason: str,
    ) -> None:
        """
        Persist a single settled trade.

        position must be a portfolio.position_tracker.Position with status=SETTLED.
        balance_after is the currency_tracker balance immediately after settlement.
        exit_reason is one of: "settlement", "strategy_exit", "stop_loss".
        """
        if self._conn is None:
            return
        try:
            entry_time = position.opened_at.isoformat() if position.opened_at else None
            exit_time = position.settled_at.isoformat() if position.settled_at else None

            hold_seconds: Optional[float] = None
            if position.opened_at and position.settled_at:
                hold_seconds = (position.settled_at - position.opened_at).total_seconds()

            net_pnl = position.realized_pnl
            if net_pnl is None:
                outcome = None
            elif net_pnl > 0:
                outcome = "WIN"
            elif net_pnl < 0:
                outcome = "LOSS"
            else:
                outcome = "BREAK_EVEN"

            trade_id = f"{session_id[:8]}_{position.position_id}"

            with self._lock:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO session_trades (
                        trade_id, session_id, strategy_name, position_id,
                        market_id, market_slug, question,
                        entry_time, exit_time, hold_seconds,
                        entry_price, exit_price, edge_pct, shares, allocated_capital,
                        entry_fee, exit_fee, gross_pnl, net_pnl,
                        outcome, exit_reason, balance_after, winning_token_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade_id,
                        session_id,
                        config.STRATEGY,
                        position.position_id,
                        position.market_id,
                        position.market_slug,
                        position.question,
                        entry_time,
                        exit_time,
                        hold_seconds,
                        position.entry_price,
                        position.settlement_price,
                        position.edge_percent,
                        position.shares,
                        position.allocated_capital,
                        position.entry_fee,
                        position.exit_fee,
                        position.gross_pnl,
                        net_pnl,
                        outcome,
                        exit_reason,
                        balance_after,
                        position.winning_token_id,
                    ),
                )
                self._conn.commit()
        except Exception as exc:
            logger.warning("SessionStore.record_settled_trade failed: %s", exc)

    def close_session(self, session_id: str, ending_balance: float) -> dict:
        """
        Compute aggregate stats, update the session row, write the JSON export file,
        and return the full session dict.

        The returned dict is passed directly to SessionReviewer.generate_review().
        Returns an empty dict on failure.
        """
        if self._conn is None:
            return {}
        try:
            end_time = datetime.now().isoformat()

            with self._lock:
                session_row = self._conn.execute(
                    "SELECT * FROM strategy_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                trade_rows = self._conn.execute(
                    "SELECT * FROM session_trades WHERE session_id = ? ORDER BY entry_time",
                    (session_id,),
                ).fetchall()

            if not session_row:
                return {}

            trades = [dict(r) for r in trade_rows]
            starting_balance = session_row["starting_balance"]
            strategy_name = session_row["strategy_name"]
            start_time = session_row["start_time"]
            trading_mode = session_row["trading_mode"]

            # ── Aggregate stats ────────────────────────────────────────
            total = len(trades)
            wins = sum(1 for t in trades if t["outcome"] == "WIN")
            losses = sum(1 for t in trades if t["outcome"] == "LOSS")
            breaks = sum(1 for t in trades if t["outcome"] == "BREAK_EVEN")

            net_pnls = [t["net_pnl"] for t in trades if t["net_pnl"] is not None]
            gross_pnls = [t["gross_pnl"] for t in trades if t["gross_pnl"] is not None]
            fees = [(t["entry_fee"] or 0.0) + (t["exit_fee"] or 0.0) for t in trades]
            holds = [t["hold_seconds"] for t in trades if t["hold_seconds"] is not None]
            edges = [t["edge_pct"] for t in trades if t["edge_pct"] is not None]
            entry_prices = [t["entry_price"] for t in trades if t["entry_price"] is not None]

            total_net_pnl = sum(net_pnls)
            total_gross_pnl = sum(gross_pnls)
            total_fees = sum(fees)
            win_rate = wins / total if total else 0.0
            avg_hold = sum(holds) / len(holds) if holds else None
            avg_edge = sum(edges) / len(edges) if edges else None
            avg_entry = sum(entry_prices) / len(entry_prices) if entry_prices else None
            best_pnl = max(net_pnls) if net_pnls else None
            worst_pnl = min(net_pnls) if net_pnls else None

            gross_wins = sum(p for p in net_pnls if p > 0)
            gross_losses = abs(sum(p for p in net_pnls if p < 0))
            profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else None

            # ── Equity curve (chart-ready time series) ─────────────────
            equity_curve = [{"time": start_time, "balance": starting_balance, "trade_count": 0}]
            running_balance = starting_balance
            for i, t in enumerate(trades, 1):
                if t["balance_after"] is not None:
                    running_balance = t["balance_after"]
                equity_curve.append(
                    {
                        "time": t["exit_time"] or t["entry_time"],
                        "balance": running_balance,
                        "trade_count": i,
                    }
                )

            # ── Build full export dict ─────────────────────────────────
            session_data: dict = {
                "session": {
                    "session_id": session_id,
                    "strategy": strategy_name,
                    "start_time": start_time,
                    "end_time": end_time,
                    "trading_mode": trading_mode,
                    "starting_balance": starting_balance,
                    "ending_balance": ending_balance,
                },
                "stats": {
                    "total_trades": total,
                    "winning_trades": wins,
                    "losing_trades": losses,
                    "break_even_trades": breaks,
                    "win_rate": round(win_rate, 4),
                    "total_gross_pnl": round(total_gross_pnl, 4),
                    "total_net_pnl": round(total_net_pnl, 4),
                    "total_fees": round(total_fees, 4),
                    "avg_hold_seconds": round(avg_hold, 2) if avg_hold is not None else None,
                    "avg_edge_pct": round(avg_edge, 2) if avg_edge is not None else None,
                    "avg_entry_price": round(avg_entry, 4) if avg_entry is not None else None,
                    "best_trade_pnl": round(best_pnl, 4) if best_pnl is not None else None,
                    "worst_trade_pnl": round(worst_pnl, 4) if worst_pnl is not None else None,
                    "profit_factor": (
                        round(profit_factor, 4) if profit_factor is not None else None
                    ),
                },
                "equity_curve": equity_curve,
                "trades": trades,
                "ollama_review": None,
            }

            # ── Update session row ─────────────────────────────────────
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE strategy_sessions SET
                        end_time = ?, ending_balance = ?,
                        total_trades = ?, winning_trades = ?, losing_trades = ?,
                        break_even_trades = ?,
                        total_gross_pnl = ?, total_net_pnl = ?, total_fees = ?,
                        win_rate = ?, profit_factor = ?,
                        avg_hold_seconds = ?, avg_edge_pct = ?, avg_entry_price = ?,
                        best_trade_pnl = ?, worst_trade_pnl = ?
                    WHERE session_id = ?
                    """,
                    (
                        end_time,
                        ending_balance,
                        total,
                        wins,
                        losses,
                        breaks,
                        total_gross_pnl,
                        total_net_pnl,
                        total_fees,
                        win_rate,
                        profit_factor,
                        avg_hold,
                        avg_edge,
                        avg_entry,
                        best_pnl,
                        worst_pnl,
                        session_id,
                    ),
                )
                self._conn.commit()

            # ── Write JSON export ──────────────────────────────────────
            self._write_json(session_id, strategy_name, start_time, session_data)

            return session_data

        except Exception as exc:
            logger.warning("SessionStore.close_session failed: %s", exc)
            return {}

    def save_review(self, session_id: str, review_text: str, model: str) -> None:
        """Patch the Ollama review into both the SQLite row and the JSON export file."""
        if self._conn is None:
            return
        try:
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE strategy_sessions
                    SET ollama_review = ?, ollama_model = ?
                    WHERE session_id = ?
                    """,
                    (review_text, model, session_id),
                )
                self._conn.commit()
                row = self._conn.execute(
                    "SELECT strategy_name, start_time FROM strategy_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()

            if row:
                json_path = self._json_path(session_id, row["strategy_name"], row["start_time"])
                if json_path.exists():
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["ollama_review"] = review_text
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, default=str)
                    logger.info("Review saved to %s", json_path)
        except Exception as exc:
            logger.warning("SessionStore.save_review failed: %s", exc)

    # ── Query helpers (used by the dashboard) ─────────────────────────

    def get_sessions(self, strategy: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Return session rows (newest first), optionally filtered by strategy name."""
        if self._conn is None:
            return []
        try:
            if strategy:
                rows = self._conn.execute(
                    """
                    SELECT * FROM strategy_sessions
                    WHERE strategy_name = ?
                    ORDER BY start_time DESC LIMIT ?
                    """,
                    (strategy, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM strategy_sessions ORDER BY start_time DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("SessionStore.get_sessions failed: %s", exc)
            return []

    def get_all_trades(self, limit: Optional[int] = None) -> List[Dict]:
        """Return all settled trades across every session, newest first.

        Used by the analytics endpoint to compute cross-session metrics
        (VaR, Sharpe, fee drag, edge realization, hold-time distribution).
        """
        if self._conn is None:
            return []
        try:
            q = "SELECT * FROM session_trades ORDER BY entry_time DESC"
            if limit:
                q += f" LIMIT {int(limit)}"
            with self._lock:
                rows = self._conn.execute(q).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("SessionStore.get_all_trades failed: %s", exc)
            return []

    def get_session(self, session_id: str) -> dict:
        """Return full session dict including the trades array."""
        if self._conn is None:
            return {}
        try:
            session_row = self._conn.execute(
                "SELECT * FROM strategy_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not session_row:
                return {}
            trade_rows = self._conn.execute(
                "SELECT * FROM session_trades WHERE session_id = ? ORDER BY entry_time",
                (session_id,),
            ).fetchall()
            return {**dict(session_row), "trades": [dict(r) for r in trade_rows]}
        except Exception as exc:
            logger.warning("SessionStore.get_session failed: %s", exc)
            return {}

    # ── Internal helpers ───────────────────────────────────────────────

    def close(self) -> None:
        """Close the SQLite connection cleanly."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _json_path(self, session_id: str, strategy_name: str, start_time: str) -> Path:
        date_str = start_time[:10].replace("-", "")  # e.g. "20260411"
        safe_strategy = strategy_name.replace("/", "_").replace(" ", "_")
        return self._sessions_dir / f"{date_str}_{safe_strategy}_{session_id[:8]}.json"

    def _write_json(self, session_id: str, strategy_name: str, start_time: str, data: dict) -> None:
        path = self._json_path(session_id, strategy_name, start_time)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("Session JSON exported: %s", path)
