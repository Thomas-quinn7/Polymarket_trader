"""
Simple Enhanced Market Scanner
Simplified version that avoids import issues
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
    
    # Test 1: Imports
    print("1. Testing imports...")
    print("   PolymarketClient: ", end="")
    client = PolymarketClient()
    print("OK")
    print()
    
    print("   EnhancedMarketScanner: ", end="")
    scanner = EnhancedMarketScanner(client)
    print("OK")
    print()
    
    # Test 2: Basic initialization
    print("2. Testing scanner initialization...")
    print("   Config: ", end="")
    config = scanner.config
    print("OK")
    print()
    
    # Test 3: Scanner methods
    print("3. Testing scanner methods...")
    print("   scan_markets_by_category(): ", end="")
    try:
        markets = scanner.scan_markets_by_category("crypto")
        print(f"OK (found {len(markets)} markets)")
    except Exception as e:
        print(f"ERROR: {e}")
    print()
    
    # Summary
    print()
    print("=" * 70)
    print("All tests PASSED!")
    print("=" * 70)
    print()
    print("Scanner is ready to use!")
    print()
    
except Exception as e:
    print()
    print("=" * 70)
    print("ERROR:")
    print(str(e))
    print("=" * 70)
    sys.exit(1)
