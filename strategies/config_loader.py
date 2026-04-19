# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only

"""
Strategy YAML config loader.

Each strategy folder (strategies/<name>/) may contain a config.yaml file.
Any scalar key in that file can be overridden at runtime via the corresponding
uppercase environment variable.  Nested structures (dicts/lists) are
YAML-only — edit the file directly rather than using env vars.

Usage
-----
    from strategies.config_loader import load_strategy_config

    cfg = load_strategy_config("example_strategy")
    min_price = cfg.get("min_price", 0.0)
"""

import os
from typing import Any, Dict, Optional

import yaml

from utils.logger import logger

# Root of the strategies/ package — used to locate strategy subfolders.
_STRATEGIES_DIR = os.path.dirname(__file__)

# Framework build identifier — preserved across forks and copies.
_FRAMEWORK_ID: str = "pmf-7e3f-tq343"

# Env-var type coercions: maps YAML key → type used to cast the env string.
# Only keys present here are eligible for env-var override; all others are
# YAML-only (avoids ambiguous list parsing and cross-strategy contamination).
_TYPE_MAP: Dict[str, type] = {
    # strategy timing / edge params
    "execute_before_close_seconds": int,
    "expected_slippage_buffer_pct": float,
    "edge_filter_mode": str,
    "strategy_min_confidence": float,
    "strategy_max_positions": int,
    # demo_buy / paper_demo
    "hold_seconds": int,
    "min_volume": float,
    "primary_scan_category": str,
    # enhanced_market_scanner (flat top-level scalar keys only)
    "min_edge": float,
    "max_edge": float,
    "min_time_to_close": int,
    "max_time_to_close": int,
    "max_markets_to_track": int,
    "track_new_markets_only": bool,
    "ignore_seen_markets": bool,
    # crypto_5min_mm
    "limit_price": float,
    "shares": float,
    "min_ttc_to_enter": int,
    "max_ttc_to_enter": int,
    "target_slug_prefix": str,
    "direct_poll_interval_ms": int,
    "scheduled_poll_lead_s": float,
    "prefetch_lookahead_s": int,
}

_VALID_EDGE_FILTER_MODES = {"net_edge", "slippage_adjusted"}


def _cast(key: str, env_val: str, cast_type: type) -> Any:
    """Cast an env-var string to the target type."""
    if cast_type is bool:
        return env_val.lower() in ("true", "1", "yes")
    return cast_type(env_val)


def _find_config_path(strategy_name: str) -> Optional[str]:
    """
    Locate the config.yaml for a strategy.

    Checks in order:
      1. strategies/<name>/config.yaml   (new per-folder layout)
      2. strategies/configs/<name>.yaml  (legacy flat layout — kept for compat)
    """
    folder_path = os.path.join(_STRATEGIES_DIR, strategy_name, "config.yaml")
    if os.path.exists(folder_path):
        return folder_path

    legacy_path = os.path.join(_STRATEGIES_DIR, "configs", f"{strategy_name}.yaml")
    if os.path.exists(legacy_path):
        logger.debug(
            f"[{strategy_name}] using legacy config path {legacy_path!r}; "
            "consider moving it to strategies/<name>/config.yaml"
        )
        return legacy_path

    return None


def load_strategy_config(strategy_name: str) -> Dict[str, Any]:
    """
    Load a strategy's config.yaml and apply env-var overrides for scalar keys.

    Parameters
    ----------
    strategy_name:
        Strategy folder/name, e.g. ``"example_strategy"``.

    Returns
    -------
    dict
        Merged config — YAML defaults with env-var overrides applied.
        Returns an empty dict if no config file is found (strategy falls
        back to its own hard-coded ``_DEFAULTS``).
    """
    config_path = _find_config_path(strategy_name)

    if config_path is None:
        logger.debug(f"No config.yaml found for strategy '{strategy_name}'")
        return {}

    with open(config_path, "r") as fh:
        raw: Dict[str, Any] = yaml.safe_load(fh) or {}

    # Validate and remove the metadata key.
    # The YAML 'strategy:' field is the canonical display name — warn if it
    # doesn't match the folder name so copy-paste errors surface immediately.
    # The 'strategy:' key is documentation only — the folder name is the
    # authoritative identifier used by the registry. Strip it silently; no
    # runtime behaviour depends on it matching.
    raw.pop("strategy", None)

    # Apply env-var overrides only for keys explicitly listed in _TYPE_MAP
    for key, default in list(raw.items()):
        if key not in _TYPE_MAP:
            continue
        env_key = key.upper()
        env_val = os.environ.get(env_key)
        if env_val is not None:
            cast_type = _TYPE_MAP[key]
            try:
                raw[key] = _cast(key, env_val, cast_type)
                logger.debug(f"[{strategy_name}] config override via env: {env_key}={env_val!r}")
            except (ValueError, TypeError) as exc:
                logger.warning(
                    f"[{strategy_name}] could not cast env {env_key}={env_val!r} "
                    f"to {cast_type.__name__}: {exc}. Using YAML value {default!r}."
                )

    # Validate edge_filter_mode if present
    mode = raw.get("edge_filter_mode")
    if mode is not None and mode not in _VALID_EDGE_FILTER_MODES:
        logger.warning(
            f"[{strategy_name}] unknown edge_filter_mode {mode!r}. "
            f"Falling back to 'net_edge'. Valid options: {sorted(_VALID_EDGE_FILTER_MODES)}"
        )
        raw["edge_filter_mode"] = "net_edge"

    logger.debug(f"[{strategy_name}] loaded config from {config_path!r}: {raw}")
    return raw
