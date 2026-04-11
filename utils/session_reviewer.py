"""
Session Reviewer — generates a natural language strategy review using a local Ollama model.

The reviewer calls the Ollama HTTP API synchronously (blocking) so the shutdown path
always gets a complete review before the process exits. If Ollama is unreachable or
the generation times out, the failure is logged and the bot shuts down normally —
the session JSON is still complete without the review field.

Ollama API used
---------------
  GET  /api/tags           — list available models
  POST /api/pull           — pull a model by name
  POST /api/generate       — generate text (stream=false)
"""

from datetime import datetime
from typing import Optional

import requests

from utils.logger import logger


# ── Privacy whitelist ────────────────────────────────────────────────────────
# Only these trade fields are forwarded to the Ollama model.
# Everything else — position UUIDs, session IDs, token IDs, wallet-adjacent
# identifiers, raw capital allocation, and per-trade running balance — is
# stripped before the prompt is built.
#
# Deliberately excluded:
#   trade_id, session_id, position_id  — internal UUIDs, not useful to the LLM
#   market_id                          — raw Polymarket market UUID
#   winning_token_id                   — long hex string; could be mistaken for
#                                        a wallet address by downstream tooling
#   shares, allocated_capital          — exact position sizing
#   entry_fee, exit_fee                — granular fee breakdown
#   balance_after                      — running account balance per trade
#   strategy_name                      — already in the session header
_REVIEW_SAFE_TRADE_FIELDS: frozenset[str] = frozenset({
    "market_slug",    # human-readable market identifier (public Polymarket data)
    "question",       # market question text (public)
    "entry_time",
    "exit_time",
    "hold_seconds",
    "entry_price",
    "exit_price",
    "edge_pct",
    "gross_pnl",
    "net_pnl",
    "outcome",        # WIN | LOSS | BREAK_EVEN
    "exit_reason",    # settlement | stop_loss | strategy_exit
})


_PROMPT_TEMPLATE = """\
You are a quantitative trading analyst reviewing a Polymarket prediction market strategy session.

STRATEGY: {strategy}
DATE: {date}
DURATION: {duration}
MODE: {trading_mode}
BALANCE: ${start_balance:.2f} → ${end_balance:.2f} ({balance_change:+.1f}%)

PERFORMANCE
Trades: {total_trades} | Won: {wins} | Lost: {losses} | Win rate: {win_rate:.0%}
Net PnL: ${net_pnl:+.2f} | Fees paid: ${fees:.2f} | Profit factor: {profit_factor}
Avg hold time: {avg_hold} | Avg edge at entry: {avg_edge}
Best trade: ${best_pnl} | Worst trade: ${worst_pnl}

TRADE LOG
{trade_log}

Write a concise strategy review covering:
1. Overall performance verdict (1 sentence)
2. What worked — cite specific data points from the table
3. What did not work or where edge was lost
4. One concrete, testable improvement for the next session

Limit: 250 words. Be specific and data-driven. Do not repeat the table numbers verbatim.\
"""


def _fmt_hold(seconds: Optional[float]) -> str:
    """Format a hold duration in seconds as 'Xh YYm'."""
    if seconds is None:
        return "n/a"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _fmt_trade_log(trades: list) -> str:
    """Build a compact ASCII table of settled trades for the prompt."""
    if not trades:
        return "(no settled trades this session)"
    header = (
        "#   Market                  Entry   Exit    Hold      Edge%   Net PnL  Outcome"
    )
    lines = [header]
    for i, t in enumerate(trades, 1):
        slug = (t.get("market_slug") or "")[:22].ljust(22)
        entry = f"{t.get('entry_price', 0):.3f}"
        exit_price = t.get("exit_price")
        exit_str = f"{exit_price:.3f}" if exit_price is not None else "  n/a "
        hold = _fmt_hold(t.get("hold_seconds"))
        edge = f"{t.get('edge_pct', 0):.1f}%"
        pnl_val = t.get("net_pnl")
        pnl_str = f"{pnl_val:+.2f}" if pnl_val is not None else "  n/a"
        outcome = t.get("outcome") or "UNKNOWN"
        lines.append(
            f"{i:<3} {slug} {entry:<7} {exit_str:<7} {hold:<9} {edge:<7} {pnl_str:<8} {outcome}"
        )
    return "\n".join(lines)


class SessionReviewer:
    """
    Calls a local Ollama instance to generate a natural language strategy review.

    All network calls are given generous timeouts — on first use the model may
    need to be pulled (~2 GB download).  Every failure is non-fatal.
    """

    _PULL_TIMEOUT_S = 600   # model pull can be slow on first run
    _GENERATE_TIMEOUT_S = 180

    def __init__(self, host: str, model: str):
        self._host = host.rstrip("/")
        self._model = model

    def _ensure_model(self) -> bool:
        """
        Check if the model is available; pull it if not.
        Returns True when the model is ready to use.
        """
        try:
            resp = requests.get(f"{self._host}/api/tags", timeout=15)
            resp.raise_for_status()
            available = [m["name"] for m in resp.json().get("models", [])]
            base_name = self._model.split(":")[0]
            if any(name.startswith(base_name) for name in available):
                return True

            logger.info(
                "Ollama model %s not found locally — pulling now "
                "(this may take several minutes on first run)…",
                self._model,
            )
            pull = requests.post(
                f"{self._host}/api/pull",
                json={"name": self._model, "stream": False},
                timeout=self._PULL_TIMEOUT_S,
            )
            pull.raise_for_status()
            logger.info("Ollama model %s ready.", self._model)
            return True

        except Exception as exc:
            logger.warning("Ollama model check/pull failed: %s", exc)
            return False

    def generate_review(self, session_data: dict) -> Optional[str]:
        """
        Build a prompt from session_data, call Ollama, and return the review text.
        Returns None if Ollama is unavailable or times out.
        """
        if not self._ensure_model():
            return None

        sess = session_data.get("session", {})
        stats = session_data.get("stats", {})

        # Strip every field not in the whitelist before any data touches the prompt.
        # This ensures internal IDs and wallet-adjacent hex strings never reach the model,
        # regardless of how session_data was assembled by the caller.
        raw_trades = session_data.get("trades", [])
        trades = [
            {k: v for k, v in t.items() if k in _REVIEW_SAFE_TRADE_FIELDS}
            for t in raw_trades
        ]

        # Session duration
        start = sess.get("start_time", "")
        end = sess.get("end_time", "")
        duration = "n/a"
        if start and end:
            try:
                delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
                h, rem = divmod(int(delta.total_seconds()), 3600)
                duration = f"{h}h {rem // 60}m"
            except Exception:
                pass

        start_bal = sess.get("starting_balance", 0.0) or 0.0
        end_bal = sess.get("ending_balance", start_bal) or start_bal
        pct_change = ((end_bal - start_bal) / start_bal * 100) if start_bal else 0.0

        pf = stats.get("profit_factor")
        profit_factor_str = f"{pf:.2f}" if pf is not None else "n/a"

        avg_edge = stats.get("avg_edge_pct")
        avg_edge_str = f"{avg_edge:.1f}%" if avg_edge is not None else "n/a"

        best = stats.get("best_trade_pnl")
        worst = stats.get("worst_trade_pnl")

        prompt = _PROMPT_TEMPLATE.format(
            strategy=sess.get("strategy", "unknown"),
            date=start[:10] if start else "unknown",
            duration=duration,
            trading_mode=sess.get("trading_mode", "unknown"),
            start_balance=start_bal,
            end_balance=end_bal,
            balance_change=pct_change,
            total_trades=stats.get("total_trades", 0),
            wins=stats.get("winning_trades", 0),
            losses=stats.get("losing_trades", 0),
            win_rate=stats.get("win_rate", 0.0),
            net_pnl=stats.get("total_net_pnl", 0.0),
            fees=stats.get("total_fees", 0.0),
            profit_factor=profit_factor_str,
            avg_hold=_fmt_hold(stats.get("avg_hold_seconds")),
            avg_edge=avg_edge_str,
            best_pnl=f"{best:+.2f}" if best is not None else "n/a",
            worst_pnl=f"{worst:+.2f}" if worst is not None else "n/a",
            trade_log=_fmt_trade_log(trades),
        )

        try:
            logger.info(
                "Generating session review via Ollama (model=%s) — this may take up to 2 min…",
                self._model,
            )
            resp = requests.post(
                f"{self._host}/api/generate",
                json={"model": self._model, "prompt": prompt, "stream": False},
                timeout=self._GENERATE_TIMEOUT_S,
            )
            resp.raise_for_status()
            review = resp.json().get("response", "").strip()
            logger.info("Ollama review generated (%d chars).", len(review))
            return review
        except Exception as exc:
            logger.warning("Ollama generate failed: %s", exc)
            return None
