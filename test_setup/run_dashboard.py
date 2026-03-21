"""
Dashboard Runner
Starts the web dashboard server for monitoring the trading bot
"""

import sys
from dashboard.api import start_dashboard

if __name__ == "__main__":
    # Start dashboard on localhost:8080
    start_dashboard(port=8080, host="127.0.0.1")
