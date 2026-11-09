"""
Shared helpers for JSON and MySQL storage backends.
"""

from datetime import datetime
from typing import Dict


class StorageMixin:
    """Common stock-status and statistics helpers."""

    def _derive_stock_status(self, product: Dict) -> str:
        """Derive stock_status from legacy in_stock/quantity fields."""
        status = product.get('stock_status')
        if status in ('in_stock', 'low_stock', 'out_of_stock', 'removed', 'unknown'):
            return status
        if product.get('in_stock') is True:
            quantity = product.get('quantity')
            threshold = getattr(self.config, 'LOW_STOCK_THRESHOLD', 5)
            if quantity is not None and quantity > 0 and quantity <= threshold:
                return 'low_stock'
            return 'in_stock'
        if product.get('in_stock') is False:
            return 'out_of_stock'
        return 'unknown'

    def _is_recent(self, timestamp: str, hours: int = 24) -> bool:
        """Check if timestamp is within specified hours."""
        if not timestamp:
            return False
        try:
            log_time = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
            age = (datetime.now() - log_time.replace(tzinfo=None)).total_seconds() / 3600
            return age <= hours
        except (ValueError, TypeError):
            return False
