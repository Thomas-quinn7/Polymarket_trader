"""
Webhook Sender Module
Handles Discord webhook notifications with rich embeds.

Embed color palette matches the dashboard design system:
  Green  #3ecf8e -> 0x3ECF8E  (profit, success, running)
  Yellow #f5a623 -> 0xF5A623  (warning, loss, pending)
  Red    #ff4444 -> 0xFF4444  (error, critical, stopped)
  Blue   #5865f2 -> 0x5865F2  (info, system events)
  Gray   #4e5058 -> 0x4E5058  (neutral / stopped)
"""

import json
import time
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional

from utils.logger import logger

# ── Design-system colors (integer form for Discord) ─────────────────
_COLOR_GREEN = 0x3ECF8E  # profit / success / running
_COLOR_YELLOW = 0xF5A623  # warning / loss
_COLOR_RED = 0xFF4444  # error / critical
_COLOR_BLUE = 0x5865F2  # info / system
_COLOR_GRAY = 0x4E5058  # neutral / stopped

# ── Emoji + color per alert type ────────────────────────────────────
_ALERT_META: Dict[str, Dict] = {
    "system_start": {"emoji": "🟢", "color": _COLOR_BLUE},
    "system_stop": {"emoji": "⭕", "color": _COLOR_GRAY},
    "system_error": {"emoji": "🔴", "color": _COLOR_RED},
    "position_opened": {"emoji": "📈", "color": _COLOR_GREEN},
    "position_closed": {"emoji": "✅", "color": _COLOR_GREEN},  # overridden for loss
    "position_loss": {"emoji": "⚠️", "color": _COLOR_YELLOW},
    "trade_executed": {"emoji": "⚡", "color": _COLOR_GREEN},
    "order_failed": {"emoji": "❌", "color": _COLOR_RED},
    "stop_loss_triggered": {"emoji": "🛑", "color": _COLOR_RED},
    "take_profit_triggered": {"emoji": "💰", "color": _COLOR_GREEN},
    "circuit_breaker": {"emoji": "⛔", "color": _COLOR_RED},
    "daily_loss_limit": {"emoji": "🚨", "color": _COLOR_RED},
    "connection_error": {"emoji": "📡", "color": _COLOR_RED},
    "api_error": {"emoji": "⚙️", "color": _COLOR_RED},
    "opportunity_detected": {"emoji": "🔍", "color": _COLOR_BLUE},
    "general_info": {"emoji": "ℹ️", "color": _COLOR_BLUE},
}

# Alert types that always ping the configured user
_MENTION_TYPES = {
    "system_error",
    "order_failed",
    "stop_loss_triggered",
    "circuit_breaker",
    "daily_loss_limit",
    "connection_error",
    "api_error",
    "position_loss",
}

# Alert types that ping on ERROR / CRITICAL severity regardless of type
_MENTION_SEVERITIES = {"ERROR", "CRITICAL"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _field(name: str, value: str, inline: bool = True) -> Dict:
    return {"name": name, "value": str(value), "inline": inline}


def _parse_extra(data_raw) -> Dict:
    """Safely parse the extra `data` JSON blob attached to some alerts."""
    if not data_raw:
        return {}
    try:
        return json.loads(data_raw) if isinstance(data_raw, str) else dict(data_raw)
    except Exception:
        return {}


# ── Per-alert-type embed builders ───────────────────────────────────


def _build_system_start(title: str, extra: Dict) -> Dict:
    fields = [
        _field("Mode", extra.get("mode", "paper")),
        _field("Strategy", extra.get("strategy", "—")),
        _field("Balance", f"${float(extra['balance']):,.2f}" if "balance" in extra else "—"),
    ]
    return {"fields": fields}


def _build_system_stop(title: str, message: str, extra: Dict) -> Dict:
    fields: List[Dict] = []
    if "reason" in extra:
        fields.append(_field("Reason", extra["reason"], inline=False))
    for k, label in [
        ("session_pnl", "Session P&L"),
        ("trades", "Trades"),
        ("win_rate", "Win Rate"),
    ]:
        if k in extra:
            fields.append(_field(label, str(extra[k])))
    return {"fields": fields}


def _build_position_opened(title: str, extra: Dict) -> Dict:
    fields = []
    if "market_id" in extra:
        fields.append(_field("Market", extra["market_id"], inline=False))
    fields += [
        _field("Entry Price", f"{float(extra['price']):.4f}" if "price" in extra else "—"),
        _field("Quantity", f"{float(extra['quantity']):.2f}" if "quantity" in extra else "—"),
        _field("Side", extra.get("side", "—")),
    ]
    if "edge_percent" in extra:
        fields.append(_field("Edge", f"+{float(extra['edge_percent']):.2f}%"))
    return {"fields": fields}


def _build_position_closed(title: str, extra: Dict) -> Dict:
    pnl = float(extra["pnl"]) if "pnl" in extra else None
    fields = []
    if "market_id" in extra:
        fields.append(_field("Market", extra["market_id"], inline=False))
    fields += [
        _field("Exit Price", f"{float(extra['exit_price']):.4f}" if "exit_price" in extra else "—"),
        _field(
            "P&L",
            (
                (f"+${pnl:.2f}" if pnl and pnl >= 0 else f"-${abs(pnl):.2f}")
                if pnl is not None
                else "—"
            ),
        ),
        _field("Hold Time", extra.get("hold_time", "—")),
    ]
    return {"fields": fields}


def _build_position_loss(title: str, extra: Dict) -> Dict:
    loss = abs(float(extra["loss"])) if "loss" in extra else None
    fields = []
    if "market_id" in extra:
        fields.append(_field("Market", extra["market_id"], inline=False))
    if loss is not None:
        fields.append(_field("Loss", f"-${loss:.2f}"))
    return {"fields": fields}


def _build_trade_executed(title: str, extra: Dict) -> Dict:
    fields = [
        _field("Action", extra.get("action", "—")),
        _field("Symbol", extra.get("symbol", "—")),
        _field("Price", f"${float(extra['price']):.4f}" if "price" in extra else "—"),
        _field("Quantity", f"{float(extra['quantity']):.2f}" if "quantity" in extra else "—"),
        _field("Total", f"${float(extra['total']):.2f}" if "total" in extra else "—"),
    ]
    if extra.get("reason"):
        fields.append(_field("Reason", extra["reason"], inline=False))
    return {"fields": fields}


def _build_opportunity(title: str, extra: Dict) -> Dict:
    fields = [
        _field("Market", extra.get("market_id", "—"), inline=False),
        _field("Price", f"{float(extra['price']):.4f}" if "price" in extra else "—"),
        _field("Edge", f"{float(extra['edge']):.2f}%" if "edge" in extra else "—"),
    ]
    return {"fields": fields}


def _build_error(title: str, message: str, extra: Dict) -> Dict:
    fields: List[Dict] = []
    lines = [ln.strip() for ln in message.splitlines() if ln.strip()]
    for line in lines:
        if ":" in line:
            k, _, v = line.partition(":")
            fields.append(_field(k.strip(), v.strip(), inline=False))
    return {"fields": fields}


def _build_generic(message: str, extra: Dict) -> Dict:
    """Fallback: split the plain-text message into embed fields."""
    fields: List[Dict] = []
    for line in message.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            fields.append(_field(k.strip(), v.strip(), inline=True))
    return {"fields": fields[:25]}


# ── Main embed factory ───────────────────────────────────────────────


def _build_embed(alert_data: Dict) -> Dict:
    alert_type = alert_data.get("alert_type", "general_info")
    severity = alert_data.get("severity", "INFO")
    title_raw = alert_data.get("title", "Trading Alert")
    message = alert_data.get("message", "")
    extra = _parse_extra(alert_data.get("data"))

    meta = _ALERT_META.get(alert_type, {"emoji": "ℹ️", "color": _COLOR_BLUE})
    emoji = meta["emoji"]
    color = meta["color"]

    # For position_closed, override color/emoji when it's a loss
    if alert_type == "position_closed":
        pnl = float(extra.get("pnl", 0))
        if pnl < 0:
            color = _COLOR_YELLOW
            emoji = "⚠️"
            title_raw = title_raw.replace("WIN", "LOSS")

    # Route to per-type builder
    if alert_type == "system_start":
        body = _build_system_start(title_raw, extra)
    elif alert_type == "system_stop":
        body = _build_system_stop(title_raw, message, extra)
    elif alert_type == "position_opened":
        body = _build_position_opened(title_raw, extra)
    elif alert_type == "position_closed":
        body = _build_position_closed(title_raw, extra)
    elif alert_type == "position_loss":
        body = _build_position_loss(title_raw, extra)
    elif alert_type == "trade_executed":
        body = _build_trade_executed(title_raw, extra)
    elif alert_type == "opportunity_detected":
        body = _build_opportunity(title_raw, extra)
    elif alert_type in {
        "system_error",
        "order_failed",
        "connection_error",
        "api_error",
        "stop_loss_triggered",
        "circuit_breaker",
        "daily_loss_limit",
    }:
        body = _build_error(title_raw, message, extra)
    else:
        body = _build_generic(message, extra)

    embed: Dict = {
        "title": f"{emoji}  {title_raw}",
        "color": color,
        "timestamp": _now_iso(),
        "footer": {"text": f"{alert_type} · {severity}"},
        "fields": body.get("fields", []),
    }

    # Add description for error alerts where fields don't capture everything
    if not body.get("fields") and message:
        embed["description"] = message[:2000]

    return embed


# ── WebhookSender ────────────────────────────────────────────────────


class WebhookSender:
    """
    Discord webhook sender with rich per-alert-type embeds.

    Public API: __init__(webhook_url, discord_username) and send_alert(alert_data) -> bool.
    """

    def __init__(self, webhook_url: str, discord_username: Optional[str] = None):
        from config.polymarket_config import config

        self.webhook_url = webhook_url
        self.timeout = 10
        self.retry_count = 3
        self.enabled = bool(webhook_url)
        self.discord_username = discord_username or config.DISCORD_MENTION_USER
        self.mention_user = bool(self.discord_username)

        if not self.enabled:
            logger.warning("Webhook sender not configured")
        else:
            logger.info(
                "Discord webhook sender initialised"
                + (f" (mentions: {self.discord_username})" if self.mention_user else "")
            )

    # ── Public API ───────────────────────────────────────────────────

    def send_alert(self, alert_data: Dict) -> bool:
        """Build a rich Discord embed and post it to the webhook."""
        if not self.enabled:
            return False
        payload = self._build_payload(alert_data)
        return self._post(payload)

    def test_connection(self) -> bool:
        """Send a ping embed to verify the webhook URL is reachable."""
        if not self.enabled:
            return False
        payload = {
            "embeds": [
                {
                    "title": "🔗  Webhook Connected",
                    "description": "Polymarket Arbitrage Bot is online.",
                    "color": _COLOR_BLUE,
                    "timestamp": _now_iso(),
                    "footer": {"text": "connection_test · INFO"},
                }
            ]
        }
        return self._post(payload)

    # ── Internal helpers ─────────────────────────────────────────────

    def _mention_str(self) -> str:
        if not self.mention_user or not self.discord_username:
            return ""
        return self.discord_username  # already '<@ID>' if configured correctly

    def _should_mention(self, alert_data: Dict) -> bool:
        alert_type = alert_data.get("alert_type", "")
        severity = alert_data.get("severity", "INFO")
        return alert_type in _MENTION_TYPES or severity in _MENTION_SEVERITIES

    def _build_payload(self, alert_data: Dict) -> Dict:
        embed = _build_embed(alert_data)
        mention = self._mention_str()
        should = self._should_mention(alert_data)

        content = mention if should and mention else None

        # allowed_mentions: only fire ping when value is a proper <@ID>
        is_id = mention.startswith("<@") if mention else False
        allowed = {"parse": ["users"]} if (should and is_id) else {"parse": []}

        payload: Dict = {"embeds": [embed], "allowed_mentions": allowed}
        if content:
            payload["content"] = content
        return payload

    def _post(self, payload: Dict) -> bool:
        for attempt in range(self.retry_count):
            try:
                resp = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code in (200, 201, 204):
                    logger.debug(f"Discord webhook sent (HTTP {resp.status_code})")
                    return True

                # 429 = rate-limited — respect Retry-After
                if resp.status_code == 429:
                    retry_after = float(resp.json().get("retry_after", 1))
                    logger.warning(f"Discord rate-limited, retrying in {retry_after}s")
                    time.sleep(retry_after)
                    continue

                logger.warning(
                    f"Discord webhook HTTP {resp.status_code} "
                    f"(attempt {attempt + 1}/{self.retry_count}): {resp.text[:200]}"
                )

            except requests.exceptions.Timeout:
                logger.error(f"Discord webhook timeout (attempt {attempt + 1}/{self.retry_count})")
            except requests.exceptions.ConnectionError:
                logger.error(
                    f"Discord webhook connection error (attempt {attempt + 1}/{self.retry_count})"
                )
            except requests.exceptions.RequestException as exc:
                logger.error(
                    f"Discord webhook error (attempt {attempt + 1}/{self.retry_count}): {exc}"
                )

            if attempt < self.retry_count - 1:
                time.sleep(2**attempt)  # 1s, 2s backoff

        logger.error("Discord webhook failed after all retries")
        return False
