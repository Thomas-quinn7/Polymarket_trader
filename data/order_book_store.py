"""
Order Book Store
Persists top-5 bid/ask snapshots to ScyllaDB for historical analysis.
24-hour TTL keeps the table size bounded without manual cleanup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

_KEYSPACE_DDL = """
CREATE KEYSPACE IF NOT EXISTS {keyspace}
    WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}
"""

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {keyspace}.order_book_snapshots (
    token_id    text,
    captured_at timestamp,
    bid_prices  list<double>,
    bid_sizes   list<double>,
    ask_prices  list<double>,
    ask_sizes   list<double>,
    PRIMARY KEY (token_id, captured_at)
) WITH CLUSTERING ORDER BY (captured_at DESC)
  AND default_time_to_live = 86400
"""

_INSERT_CQL = """
INSERT INTO {keyspace}.order_book_snapshots
    (token_id, captured_at, bid_prices, bid_sizes, ask_prices, ask_sizes)
VALUES (?, ?, ?, ?, ?, ?)
"""

_SELECT_LATEST_CQL = """
SELECT captured_at, bid_prices, bid_sizes, ask_prices, ask_sizes
FROM {keyspace}.order_book_snapshots
WHERE token_id = ?
ORDER BY captured_at DESC
LIMIT 1
"""


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    token_id: str
    captured_at: datetime
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)


class OrderBookStore:
    """
    Writes and reads order book snapshots from ScyllaDB.

    Top 5 bid/ask levels are captured per snapshot with a 24-hour TTL.
    All failures are non-fatal — the trading loop continues if ScyllaDB is
    unavailable.
    """

    def __init__(self, hosts: List[str], port: int, keyspace: str):
        self._hosts = hosts
        self._port = port
        self._keyspace = keyspace
        self._session = None
        self._insert_stmt = None
        self._select_stmt = None

    def connect(self) -> bool:
        """Connect to ScyllaDB and ensure schema exists. Returns False on failure."""
        try:
            from cassandra.cluster import Cluster
            from cassandra.policies import DCAwareRoundRobinPolicy

            cluster = Cluster(
                contact_points=self._hosts,
                port=self._port,
                load_balancing_policy=DCAwareRoundRobinPolicy(),
                protocol_version=4,
            )
            self._session = cluster.connect()

            self._session.execute(_KEYSPACE_DDL.format(keyspace=self._keyspace))
            self._session.set_keyspace(self._keyspace)
            self._session.execute(_TABLE_DDL.format(keyspace=self._keyspace))

            self._insert_stmt = self._session.prepare(
                _INSERT_CQL.format(keyspace=self._keyspace)
            )
            self._select_stmt = self._session.prepare(
                _SELECT_LATEST_CQL.format(keyspace=self._keyspace)
            )

            logger.info(
                "OrderBookStore connected to ScyllaDB %s:%s (keyspace=%s)",
                self._hosts,
                self._port,
                self._keyspace,
            )
            return True

        except Exception as e:
            logger.warning("OrderBookStore failed to connect: %s", e)
            self._session = None
            return False

    def write_snapshot(self, snapshot: OrderBookSnapshot) -> bool:
        """
        Persist a snapshot. Returns True on success, False on failure.
        Never raises — caller should not need to guard this.
        """
        if self._session is None or self._insert_stmt is None:
            return False
        try:
            self._session.execute(
                self._insert_stmt,
                (
                    snapshot.token_id,
                    snapshot.captured_at,
                    [lvl.price for lvl in snapshot.bids],
                    [lvl.size for lvl in snapshot.bids],
                    [lvl.price for lvl in snapshot.asks],
                    [lvl.size for lvl in snapshot.asks],
                ),
            )
            return True
        except Exception as e:
            logger.warning("OrderBookStore write failed for %s: %s", snapshot.token_id, e)
            return False

    def latest_snapshot(self, token_id: str) -> Optional[OrderBookSnapshot]:
        """Return the most recent snapshot for a token, or None."""
        if self._session is None or self._select_stmt is None:
            return None
        try:
            rows = self._session.execute(self._select_stmt, (token_id,))
            row = rows.one()
            if row is None:
                return None

            return OrderBookSnapshot(
                token_id=token_id,
                captured_at=row.captured_at,
                bids=[OrderBookLevel(p, s) for p, s in zip(row.bid_prices, row.bid_sizes)],
                asks=[OrderBookLevel(p, s) for p, s in zip(row.ask_prices, row.ask_sizes)],
            )
        except Exception as e:
            logger.warning("OrderBookStore read failed for %s: %s", token_id, e)
            return None

    def close(self):
        """Cleanly shut down the cluster connection."""
        if self._session is not None:
            try:
                self._session.cluster.shutdown()
            except Exception:
                pass
            self._session = None
