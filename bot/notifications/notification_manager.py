"""
Notification manager coordinating all notification channels
"""

import hashlib
from datetime import datetime, timedelta
from typing import Dict, List
from bot.notifications.email_notifier import EmailNotifier
from bot.notifications.telegram_notifier import TelegramNotifier
from bot.storage import get_storage
from bot.utils.logger import Logger


class NotificationManager:
    """Manages all notification channels with duplicate prevention"""
    
    def __init__(self, storage=None):
        self.email_notifier = EmailNotifier()
        self.telegram_notifier = TelegramNotifier()
        self.storage = storage or get_storage()
        self.logger = Logger()
        self._recent_fingerprints = {}
    
    def send_product_notification(self, product: Dict, status_data: Dict, changes: Dict):
        """Send notifications for product changes"""
        product_id = product.get('id')
        product_name = product.get('name')
        
        if not self.should_notify(product_id, changes):
            self.logger.debug(f"Skipping notification for {product_name}", component='notifications')
            return
        
        fingerprint = self._create_fingerprint(product_id, changes)
        if self._is_duplicate(fingerprint):
            self.logger.info(f"Duplicate notification suppressed for {product_name}", component='notifications')
            return
        
        notifications_sent = []
        
        if self.email_notifier.send_notification(product, status_data, changes):
            notifications_sent.append('email')
            self.storage.add_notification(product_id, product_name, 'email', self.format_change_message(changes))
        
        if self.telegram_notifier.send_notification(product, status_data, changes):
            notifications_sent.append('telegram')
            self.storage.add_notification(product_id, product_name, 'telegram', self.format_change_message(changes))
        
        if notifications_sent:
            self._recent_fingerprints[fingerprint] = datetime.now()
            self.logger.info(
                f"Notifications sent via {', '.join(notifications_sent)} for {product_name}",
                component='notifications'
            )
        else:
            self.logger.warning(f"No notifications sent for {product_name}", component='notifications')

    def send_hourly_summary(self, products: List[Dict], changes_list: List[Dict]):
        """Send hourly digest via all configured channels"""
        if not products:
            return

        settings = self.storage.get_settings()
        if not settings.get('hourly_summary_enabled', True):
            return

        sent = []
        if self.email_notifier.send_hourly_summary(products, changes_list):
            sent.append('email')
        if self.telegram_notifier.send_hourly_summary(products, changes_list):
            sent.append('telegram')

        if sent:
            self.logger.info(
                f"Hourly summary sent via {', '.join(sent)} ({len(changes_list)} changes)",
                component='notifications'
            )
        else:
            self.logger.warning("Hourly summary could not be sent — check .env credentials", component='notifications')

    def test_notifications(self) -> Dict[str, bool]:
        """Test both notification channels"""
        results = {
            'email': self.email_notifier.test_connection(),
            'telegram': self.telegram_notifier.test_connection()
        }
        return results
    
    def should_notify(self, product_id: str, changes: Dict) -> bool:
        """Determine if notification should be sent based on change type and settings"""
        settings = self.storage.get_settings()
        
        if 'initial_check' in changes:
            return not settings.get('skip_initial_notification', True)
        
        if 'stock_status' in changes:
            return True
        
        if 'stock' in changes:
            return True

        if 'quantity' in changes:
            return True
        
        if 'price' in changes:
            threshold = settings.get('price_change_threshold', 0)
            old_price = changes['price']['from']
            new_price = changes['price']['to']
            
            if old_price == 0:
                return new_price > 0
            
            if threshold == 0:
                return old_price != new_price
            
            change_percent = abs((new_price - old_price) / old_price) * 100
            return change_percent >= threshold
        
        return False
    
    def _create_fingerprint(self, product_id: str, changes: Dict) -> str:
        """Create unique fingerprint for a change to prevent duplicates"""
        raw = f"{product_id}:{changes}"
        return hashlib.md5(raw.encode()).hexdigest()
    
    def _is_duplicate(self, fingerprint: str, window_minutes: int = 60) -> bool:
        """Check if same notification was sent recently"""
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        self._recent_fingerprints = {
            k: v for k, v in self._recent_fingerprints.items() if v > cutoff
        }
        return fingerprint in self._recent_fingerprints
    
    def format_change_message(self, changes: Dict) -> str:
        """Format a human-readable summary of product changes."""
        return self._format_change_message(changes)

    def _format_change_message(self, changes: Dict) -> str:
        labels = {
            'in_stock': 'In Stock',
            'low_stock': 'Low Stock',
            'out_of_stock': 'Out of Stock',
            'removed': 'Removed from store',
            'unknown': 'Unknown'
        }
        if 'stock_status' in changes:
            from_status = labels.get(changes['stock_status']['from'], changes['stock_status']['from'])
            to_status = labels.get(changes['stock_status']['to'], changes['stock_status']['to'])
            return f"Stock status: {from_status} → {to_status}"
        if 'stock' in changes:
            status = 'In Stock' if changes['stock']['to'] else 'Out of Stock'
            return f"Stock changed to {status}"
        if 'quantity' in changes:
            q = changes['quantity']
            return f"Quantity changed: {q['from']} → {q['to']}"
        if 'price' in changes:
            c = changes['price']
            return f"Price changed: {c['currency']} {c['from']:.2f} → {c['to']:.2f}"
        return str(changes)
