"""
Helper utility functions
"""

import hashlib
import json
from datetime import datetime
from typing import Dict, Any


class Helpers:
    """Helper functions for common operations"""
    
    @staticmethod
    def generate_hash(data: str) -> str:
        """Generate SHA256 hash of a string"""
        return hashlib.sha256(data.encode()).hexdigest()
    
    @staticmethod
    def format_currency(amount: float, currency: str = 'USD') -> str:
        """Format currency for display"""
        symbols = {
            'USD': '$',
            'EUR': '€',
            'GBP': '£',
            'JPY': '¥',
            'CAD': 'C$',
            'AUD': 'A$'
        }
        
        symbol = symbols.get(currency, '$')
        return f"{symbol}{amount:.2f}"
    
    @staticmethod
    def truncate_string(text: str, max_length: int = 100) -> str:
        """Truncate string to maximum length"""
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + "..."
    
    @staticmethod
    def safe_parse_json(json_string: str) -> Dict[str, Any]:
        """Safely parse JSON string"""
        try:
            return json.loads(json_string)
        except:
            return {}
    
    @staticmethod
    def is_within_last_hours(timestamp: str, hours: int = 24) -> bool:
        """Check if timestamp is within specified hours"""
        try:
            dt = datetime.fromisoformat(timestamp)
            age = (datetime.now() - dt).total_seconds() / 3600
            return age <= hours
        except:
            return False
