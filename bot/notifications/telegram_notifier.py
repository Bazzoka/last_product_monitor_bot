"""
Telegram notification service
"""

import requests
from typing import Dict
from bot.config import Config
from bot.utils.logger import Logger


class TelegramNotifier:
    """Handles Telegram notifications"""
    
    def __init__(self):
        """Initialize telegram notifier"""
        self.config = Config()
        self.logger = Logger()
        self.base_url = f"https://api.telegram.org/bot{self.config.TELEGRAM_BOT_TOKEN}"
    
    def test_connection(self) -> bool:
        """Verify Telegram bot can send messages"""
        if not self.config.is_telegram_configured():
            return False
        try:
            payload = {
                'chat_id': self.config.TELEGRAM_CHAT_ID,
                'text': '✅ Product Monitor Bot — test notification successful!',
                'parse_mode': 'HTML'
            }
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json=payload,
                timeout=30
            )
            if response.status_code == 200:
                return True
            self.logger.error(f"Telegram test failed: {response.text}", component='notifications')
            return False
        except Exception as e:
            self.logger.error(f"Telegram test failed: {e}", component='notifications')
            return False

    def send_hourly_summary(self, products: list, changes_list: list) -> bool:
        """Send hourly monitoring summary via Telegram"""
        if not self.config.is_telegram_configured():
            return False

        try:
            if changes_list:
                header = f"📊 <b>Hourly Report</b> — {len(changes_list)} change(s)\n\n"
                changes_text = "<b>Changes:</b>\n"
                for item in changes_list:
                    changes_text += f"• {item['name']}: {item['summary']}\n"
            else:
                header = "📊 <b>Hourly Report</b> — no changes\n\n"
                changes_text = "All products checked. No changes detected.\n"

            status_text = "\n<b>Current Status:</b>\n"
            for product in products:
                status = product.get('stock_status') or (
                    'in_stock' if product.get('in_stock') else 'out_of_stock'
                )
                emoji = {
                    'in_stock': '✅',
                    'low_stock': '⚠️',
                    'out_of_stock': '❌',
                    'removed': '🗑️',
                }.get(status, '❓')
                price = product.get('current_price', 0) or 0
                currency = product.get('currency', 'USD')
                status_text += f"{emoji} {product.get('name', 'Unknown')} — {currency} {float(price):.2f}\n"

            message = header + changes_text + status_text

            payload = {
                'chat_id': self.config.TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json=payload,
                timeout=30
            )
            if response.status_code == 200:
                self.logger.info(
                    f"Telegram hourly summary sent ({len(products)} products)",
                    component='notifications'
                )
                return True
            self.logger.error(
                f"Telegram hourly summary failed: {response.text}",
                component='notifications'
            )
            return False
        except Exception as e:
            self.logger.error(f"Failed to send telegram summary: {e}", component='notifications')
            return False
    
    def send_notification(self, product: Dict, status_data: Dict, changes: Dict) -> bool:
        """Send telegram notification about product changes"""
        if not self.config.is_telegram_configured():
            self.logger.warning("Telegram not configured, skipping notification")
            return False
        
        try:
            message = self.create_message(product, status_data, changes)
            
            payload = {
                'chat_id': self.config.TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            }
            
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                self.logger.info(f"Telegram notification sent for {product.get('name')}")
                return True
            else:
                self.logger.error(f"Telegram API error: {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to send telegram notification: {e}")
            return False
    
    def create_message(self, product: Dict, status_data: Dict, changes: Dict) -> str:
        """Create formatted telegram message"""
        product_name = product.get('name', 'Product')
        product_url = product.get('url', '#')
        
        # Determine emoji based on changes
        if 'stock_status' in changes:
            status = changes['stock_status']['to']
            if status == 'low_stock':
                emoji = "⚠️"
                status_text = "LOW STOCK"
            elif status == 'in_stock':
                emoji = "✅"
                status_text = "IN STOCK"
            elif status == 'out_of_stock':
                emoji = "❌"
                status_text = "OUT OF STOCK"
            else:
                emoji = "📦"
                status_text = "STATUS UPDATE"
        elif 'stock' in changes:
            if changes['stock']['to']:
                emoji = "✅"
                status_text = "IN STOCK"
            else:
                emoji = "❌"
                status_text = "OUT OF STOCK"
        elif 'price' in changes:
            emoji = "💰"
            status_text = "PRICE CHANGED"
        elif 'quantity' in changes:
            emoji = "📦"
            status_text = "QUANTITY CHANGED"
        else:
            emoji = "📦"
            status_text = "STATUS UPDATE"
        
        status_labels = {
            'in_stock': 'In Stock',
            'low_stock': 'Low Stock',
            'out_of_stock': 'Out of Stock',
            'unknown': 'Unknown'
        }
        current_status = status_labels.get(
            status_data.get('stock_status'),
            'In Stock' if status_data.get('in_stock') else 'Out of Stock'
        )
        
        message = f"""
{emoji} <b>Product Monitor Alert</b>

<b>Product:</b> {product_name}
<b>Status:</b> {status_text}
<b>Current Stock:</b> {current_status}
<b>Current Price:</b> {status_data.get('currency', 'USD')} {status_data.get('price', 0):.2f}
<b>Quantity:</b> {status_data.get('quantity') if status_data.get('quantity') is not None else 'Unknown'}
<b>Time:</b> {status_data.get('timestamp', 'N/A')}
        """
        
        # Add change details
        if 'stock_status' in changes:
            from_label = status_labels.get(changes['stock_status']['from'], changes['stock_status']['from'])
            to_label = status_labels.get(changes['stock_status']['to'], changes['stock_status']['to'])
            message += f"\n<b>Stock Change:</b> {from_label} → {to_label}"
        elif 'stock' in changes:
            message += f"\n<b>Stock Change:</b> {'Out of Stock' if not changes['stock']['from'] else 'In Stock'} → {'In Stock' if changes['stock']['to'] else 'Out of Stock'}"
        
        if 'price' in changes:
            message += f"\n<b>Price Change:</b> {changes['price']['currency']} {changes['price']['from']:.2f} → {changes['price']['currency']} {changes['price']['to']:.2f}"
        
        if 'quantity' in changes:
            message += f"\n<b>Quantity Change:</b> {changes['quantity']['from']} → {changes['quantity']['to']}"
        
        message += f"\n\n<a href='{product_url}'>🔗 View Product</a>"
        
        return message
