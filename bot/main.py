"""
Main application coordinator
Handles bot initialization, scheduling, and coordination between components
"""

import threading
import schedule
import time
import signal
import sys
from datetime import datetime
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from bot.config import Config
from bot.scrapers.product_scraper import ProductScraper
from bot.notifications.notification_manager import NotificationManager
from bot.storage import get_storage
from bot.dashboard.app import DashboardApp
from bot.utils.logger import Logger


class ProductMonitorBot:
    """Main bot class coordinating all monitoring activities"""
    
    def __init__(self):
        self.config = Config()
        self.logger = Logger()
        self.storage = get_storage()
        self.notification_manager = NotificationManager(self.storage)
        self.product_scraper = ProductScraper()
        self.dashboard_app = None
        self.running = False
        self.scheduler_thread = None
        self.check_lock = threading.Lock()
        self.last_check_time = None
        self.product_cache = {}

        backend = 'MySQL' if self.config.use_mysql() else 'JSON files'
        self.logger.info(f"Storage backend: {backend}", component='bot')
        self.logger.info("Bot initialized successfully", component='bot')
    
    def _load_product_cache(self):
        """Load saved product states from disk so restarts keep history."""
        for product in self.storage.get_all_products():
            if product.get('in_stock') is not None or product.get('stock_status') not in (None, 'unknown'):
                self.product_cache[product['id']] = {
                    'in_stock': product.get('in_stock'),
                    'stock_status': self.storage._derive_stock_status(product),
                    'price': product.get('current_price', 0),
                    'currency': 'USD',
                    'quantity': product.get('quantity'),
                    'product_removed': product.get('stock_status') == 'removed',
                }
    
    def setup_dashboard(self):
        """Setup and start the dashboard in a background thread"""
        self.dashboard_app = DashboardApp(self)
        dashboard_thread = threading.Thread(target=self.dashboard_app.run, daemon=True)
        dashboard_thread.start()
        self.logger.info("Dashboard started", component='bot')
    
    def check_all_products(self):
        """Check availability for all monitored products concurrently"""
        with self.check_lock:
            self.logger.info("Starting product availability check", component='bot')
            
            try:
                products = self.storage.get_all_products()
                active_products = [p for p in products if p.get('monitoring_enabled', True)]
                
                if not active_products:
                    self.logger.info("No active products to monitor", component='bot')
                    return
                
                self.last_check_time = datetime.now().isoformat()
                max_workers = min(self.config.MAX_CONCURRENT_CHECKS, len(active_products))
                
                changes_list: List[Dict] = []
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(self.check_single_product, product): product
                        for product in active_products
                    }
                    
                    for future in as_completed(futures):
                        product = futures[future]
                        try:
                            change_info = future.result()
                            if change_info:
                                changes_list.append(change_info)
                        except Exception as e:
                            name = product.get('name', 'Unknown')
                            self.logger.error(f"Error checking product {name}: {e}", component='bot')
                            self.storage.add_log('ERROR', f"Product check failed: {e}", name)
                
                self.last_check_time = datetime.now().isoformat()
                self.storage.update_settings({'last_scan_time': self.last_check_time})
                self.logger.info(
                    f"Completed check for {len(active_products)} products",
                    component='bot'
                )

                summary_products = self._products_for_summary(active_products)
                self.notification_manager.send_hourly_summary(summary_products, changes_list)
                
            except Exception as e:
                self.logger.error(f"Error in check_all_products: {e}", component='bot')
    
    def _products_for_summary(self, products: List[Dict]) -> List[Dict]:
        """Build product list with derived stock status for hourly reports."""
        summary = []
        for product in products:
            entry = dict(product)
            entry['stock_status'] = self.storage._derive_stock_status(product)
            summary.append(entry)
        return summary

    def check_single_product(self, product: Dict) -> Optional[Dict]:
        """Check a single product's availability and handle state changes"""
        product_id = product.get('id')
        product_name = product.get('name')
        product_url = product.get('url')
        
        self.logger.info(f"Checking product: {product_name}", component='bot')
        
        scraped_data = self.product_scraper.scrape_product(product_url, product)
        
        if not scraped_data:
            self.logger.warning(f"Failed to scrape product: {product_name}", component='bot')
            self.storage.add_log('WARNING', f"Failed to scrape product: {product_name}", product_name)
            self.storage.update_last_check(product_id)
            return None
        
        previous_state = self._get_previous_state(product_id)
        changes = self.detect_changes(previous_state, scraped_data)
        change_info = None
        
        if changes and 'initial_check' not in changes:
            self.logger.info(f"Changes detected for {product_name}: {changes}", component='bot')
            self.notification_manager.send_product_notification(product, scraped_data, changes)
            self.storage.update_product_status(product_id, scraped_data)
            self.storage.add_price_history(product_id, scraped_data)
            self.storage.add_log('INFO', f"Product status changed: {changes}", product_name)
            change_info = {
                'name': product_name,
                'summary': self.notification_manager.format_change_message(changes)
            }
        elif 'initial_check' in changes:
            self.storage.update_product_status(product_id, scraped_data)
            self.storage.add_log('INFO', f"Initial check completed for {product_name}", product_name)
        else:
            stored = self.storage.get_product(product_id)
            stored_status = self.storage._derive_stock_status(stored) if stored else 'unknown'
            if (
                stored
                and (
                    stored.get('quantity') != scraped_data.get('quantity')
                    or stored_status != scraped_data.get('stock_status')
                )
            ):
                self.storage.update_product_status(product_id, scraped_data)
            else:
                self.storage.update_last_check(product_id)
        
        self.product_cache[product_id] = scraped_data
        return change_info
    
    def _get_previous_state(self, product_id: str) -> Dict:
        """Get previous product state from cache or storage"""
        if product_id in self.product_cache:
            return self.product_cache[product_id]
        
        product = self.storage.get_product(product_id)
        if product and product.get('in_stock') is not None:
            return {
                'in_stock': product.get('in_stock'),
                'stock_status': self.storage._derive_stock_status(product),
                'price': product.get('current_price', 0),
                'currency': 'USD',
                'quantity': product.get('quantity'),
                'product_removed': product.get('stock_status') == 'removed',
            }
        
        history = self.storage.get_product_history(product_id)
        if history:
            return history
        
        return {}
    
    def detect_changes(self, previous: Dict, current: Dict) -> Dict:
        """Detect changes between previous and current product states"""
        changes = {}
        
        if not previous:
            changes['initial_check'] = True
            return changes
        
        prev_status = previous.get('stock_status')
        if not prev_status or prev_status == 'unknown':
            if previous.get('in_stock') is True:
                prev_status = 'in_stock'
            elif previous.get('in_stock') is False:
                prev_status = 'out_of_stock'
            else:
                prev_status = 'unknown'

        curr_status = current.get('stock_status', 'unknown')
        if current.get('product_removed') or curr_status == 'removed':
            curr_status = 'removed'
        if prev_status != curr_status:
            changes['stock_status'] = {'from': prev_status, 'to': curr_status}

        if curr_status == 'removed':
            return changes
        
        prev_price = previous.get('price', 0) or 0
        curr_price = current.get('price', 0) or 0
        if abs(float(prev_price) - float(curr_price)) > 0.001:
            changes['price'] = {
                'from': float(prev_price),
                'to': float(curr_price),
                'currency': 'USD',
            }

        prev_qty = previous.get('quantity')
        curr_qty = current.get('quantity')
        if prev_qty is not None and curr_qty is not None and prev_qty != curr_qty:
            changes['quantity'] = {'from': prev_qty, 'to': curr_qty}
        
        return changes
    
    def run_scheduler(self):
        """Run the monitoring scheduler loop"""
        interval_hours = self.config.CHECK_INTERVAL_HOURS
        schedule.every(interval_hours).hours.do(self.check_all_products)
        self.check_all_products()
        
        self.logger.info(f"Scheduler started with {interval_hours} hour interval", component='bot')
        
        while self.running:
            schedule.run_pending()
            time.sleep(60)
    
    def start(self):
        """Start the bot and all background services"""
        self.logger.info("Starting Product Availability Monitoring Bot", component='bot')
        self.running = True
        self.storage.initialize_files()
        self._init_default_settings()
        self._load_product_cache()
        self._log_notification_status()
        self.setup_dashboard()
        
        self.scheduler_thread = threading.Thread(target=self.run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)
        
        while self.running:
            time.sleep(1)
    
    def _init_default_settings(self):
        """Ensure default settings exist in settings.json"""
        settings = self.storage.get_settings()
        defaults = {
            'price_change_threshold': 0,
            'skip_initial_notification': True,
            'hourly_summary_enabled': True,
            'last_scan_time': None
        }
        updated = False
        for key, value in defaults.items():
            if key not in settings:
                settings[key] = value
                updated = True
        if updated:
            self.storage.update_settings(settings)
    
    def _log_notification_status(self):
        """Log notification channel status at startup."""
        for warning in self.config.get_config_warnings():
            self.logger.warning(warning, component='notifications')

        email_ok = self.config.is_email_configured()
        telegram_ok = self.config.is_telegram_configured()
        self.logger.info(
            f"Notifications: email={'ready' if email_ok else 'not configured'}, "
            f"telegram={'ready' if telegram_ok else 'not configured'}",
            component='notifications'
        )

    def shutdown(self, signum=None, frame=None):
        """Shutdown the bot gracefully"""
        self.logger.info("Shutting down bot...", component='bot')
        self.running = False
        
        if self.product_scraper:
            self.product_scraper.cleanup()
        
        self.logger.info("Bot shutdown complete", component='bot')
        sys.exit(0)


def main():
    """Main entry point"""
    bot = ProductMonitorBot()
    bot.start()


if __name__ == "__main__":
    main()
