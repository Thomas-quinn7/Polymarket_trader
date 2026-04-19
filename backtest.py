#!/usr/bin/env python3
# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only
"""
Backtest CLI — run a strategy against historical PolyMarket data.

Usage:
    python backtest.py --strategy <strategy_name> \\
        --start 2025-01-01 --end 2025-04-01 \\
        --balance 1000 --max-positions 5 --capital-pct 20 \\
        --fee 2.0 --category crypto --interval 5m
"""

import argparse
import os
import sys

# Add repo root to path so imports work without install
sys.path.insert(0, os.path.dirname(__file__))


def main():
    parser = argparse.ArgumentParser(
        description="Backtest a PolyMarket trading strategy against historical data",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--strategy", required=True, help="Strategy folder name (e.g. example_strategy)"
    )
    parser.add_argument("--start", default="2025-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="2025-04-01", help="End date YYYY-MM-DD")
    parser.add_argument("--balance", type=float, default=1000.0, help="Initial balance USDC")
    parser.add_argument("--max-positions", type=int, default=5, help="Max simultaneous positions")
    parser.add_argument("--capital-pct", type=float, default=20.0, help="Capital per trade %%")
    parser.add_argument("--fee", type=float, default=2.0, help="Taker fee %%")
    parser.add_argument("--min-volume", type=float, default=500.0, help="Min market volume USDC")
    parser.add_argument(
        "--max-duration", type=int, default=1800, help="Max market duration seconds (0=any)"
    )
    parser.add_argument(
        "--interval",
        default="5m",
        choices=["1m", "5m", "15m", "1h", "4h", "1d"],
        help="Price history interval",
    )
    parser.add_argument(
        "--category",
        default="crypto",
        choices=["crypto", "fed", "regulatory", "other"],
    )
    parser.add_argument("--rate-limit", type=float, default=3.0, help="Gamma API req/s")
    parser.add_argument(
        "--output", default="./logs/backtest_results/", help="JSON output directory"
    )
    parser.add_argument("--db", default="storage/backtest.db", help="Backtest DB path")
    args = parser.parse_args()

    from backtesting.config import BacktestConfig
    from backtesting.runner import BacktestRunner

    config = BacktestConfig(
        strategy_name=args.strategy,
        start_date=args.start,
        end_date=args.end,
        initial_balance=args.balance,
        max_positions=args.max_positions,
        capital_per_trade_pct=args.capital_pct,
        taker_fee_pct=args.fee,
        min_volume_usd=args.min_volume,
        max_duration_seconds=args.max_duration,
        price_interval=args.interval,
        category=args.category,
        rate_limit_rps=args.rate_limit,
    )

    try:
        config.validate()
    except ValueError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    runner = BacktestRunner(db_path=args.db)

    print(f"\nRunning backtest: {args.strategy} | {args.start} → {args.end} | {args.category}")
    print(
        f"Balance: ${args.balance:.2f} | Max positions: {args.max_positions} | Fee: {args.fee}%\n"
    )

    def progress(msg):
        print(f"  {msg}")

    metrics = runner.execute(config, progress_callback=progress)
    _print_report(metrics, config)
    _save_json(metrics, config, args.output)


def _print_report(metrics, config):
    """Print a formatted summary box."""
    m = metrics
    w = 56
    sep = "─" * w
    print(f"\n╔{sep}╗")
    print(f"║{'BACKTEST RESULTS':^{w}}║")
    print(f"║  Strategy: {config.strategy_name:<{w - 12}}║")
    print(f"║  Period:   {config.start_date} → {config.end_date:<{w - 24}}║")
    print(f"╠{sep}╣")
    print(f"║  Initial Balance:     ${config.initial_balance:>10,.2f}          ║")
    print(f"║  Final Balance:       ${m.final_balance:>10,.2f}          ║")
    print(f"║  Total Return:        {m.total_return_pct:>+10.2f}%         ║")
    print(f"║  Annualized Return:   {m.annualized_return:>+10.2f}%         ║")
    print(f"╠{sep}╣")
    print(f"║  Total Trades:        {m.total_trades:>10}           ║")
    print(f"║  Wins / Losses:       {m.wins:>5} / {m.losses:<18}║")
    print(f"║  Win Rate:            {m.win_rate * 100:>10.1f}%         ║")
    print(f"║  Profit Factor:       {(m.profit_factor or 0):>10.2f}          ║")
    print(f"╠{sep}╣")
    sr = f"{m.sharpe_ratio:.4f}" if m.sharpe_ratio is not None else "N/A"
    so = f"{m.sortino_ratio:.4f}" if m.sortino_ratio is not None else "N/A"
    ca = f"{m.calmar_ratio:.4f}" if m.calmar_ratio is not None else "N/A"
    print(f"║  Sharpe Ratio:        {sr:>10}           ║")
    print(f"║  Sortino Ratio:       {so:>10}           ║")
    print(f"║  Calmar Ratio:        {ca:>10}           ║")
    print(f"║  Max Drawdown:        {m.max_drawdown:>10.2f}%         ║")
    print(f"╠{sep}╣")
    print(f"║  Avg Hold Time:       {m.avg_hold_seconds / 60:>10.1f} min       ║")
    print(f"║  Total Fees:          ${m.total_fees:>10,.2f}          ║")
    print(f"║  Fee Drag:            {m.fee_drag_pct:>10.2f}%         ║")
    print(f"║  Max Consec Wins:     {m.consec_wins_max:>10}           ║")
    print(f"║  Max Consec Losses:   {m.consec_losses_max:>10}           ║")
    print(f"╚{sep}╝\n")


def _save_json(metrics, config, output_dir):
    import json
    from datetime import datetime

    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"{ts}_{config.strategy_name}_backtest.json")
    data = {
        "config": config.to_json(),
        "metrics": metrics.to_dict(),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Results saved to: {path}")


if __name__ == "__main__":
    main()
