#!/usr/bin/env python3
"""
Product Availability Monitoring Bot - Main Entry Point
Run this file to start the application
"""

import sys
import os
import threading
import multiprocessing

# Add the bot directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.main import main

if __name__ == "__main__":
    # Allow running on different platforms
    multiprocessing.freeze_support()
    
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Application stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] Application crashed: {e}")
        sys.exit(1)
