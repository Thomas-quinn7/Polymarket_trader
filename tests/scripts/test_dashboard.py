"""
Test Dashboard Server
Simple test to run the dashboard server independently
"""

import uvicorn
import sys

if __name__ == "__main__":
    print("Starting dashboard server on http://127.0.0.1:8080")
    print("Press Ctrl+C to stop")
    
    uvicorn.run(
        "dashboard.api:app",
        host="127.0.0.1",
        port=8080,
        log_level="info",
    )
