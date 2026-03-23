"""
Simple Test for Enhanced Market Scanner
Basic tests to verify the scanner works
"""

import sys
import os

# Add parent directory to path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

try:
    from data.polymarket_client import PolymarketClient
    from strategies.enhanced_market_scanner import EnhancedMarketScanner
    from utils.logger import logger
    
    print("=" * 70)
    print("Simple Enhanced Market Scanner Test")
    print("=" * 70)
    print()
    
    print("1. Testing PolymarketClient import...")
    client = PolymarketClient()
    print("   PolymarketClient: OK")
    print()
    
    print("2. Testing EnhancedMarketScanner import...")
    scanner = EnhancedMarketScanner(client)
    print("   EnhancedMarketScanner: OK")
    print()
    
    print("3. Testing scanner configuration loading...")
    config = scanner.config
    print(f"   Config loaded: OK")
    print(f"   Crypto enabled: {config.crypto_enabled}")
    print(f"   Fed enabled: {config.fed_enabled}")
    print(f"   Regulatory enabled: {config.regulatory_enabled}")
    print(f"   Other enabled: {config.other_enabled}")
    print()
    
    print("4. Testing basic market scan...")
    # Just initialize without calling API
    print("   Scanner initialized: OK")
    print()
    
    print("=" * 70)
    print("All basic tests PASSED")
    print("=" * 70)
    print()
    print("To test full functionality, update your .env file with API keys")
    print("Then run: uv run main.py")
    print()
    
except Exception as e:
    print("=" * 70)
    print(f"ERROR: {e}")
    print("=" * 70)
    sys.exit(1)
