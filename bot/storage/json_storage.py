"""
JSON-based storage management
Handles all file operations for products, notifications, logs, and settings
"""

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from bot.config import Config
from bot.storage.storage_mixin import StorageMixin


class JSONStorage(StorageMixin):
    """Manages JSON file storage operations"""
    
    def __init__(self):
        """Initialize storage with configuration"""
        self.config = Config()
        self.products_file = self.config.PRODUCTS_FILE
        self.notifications_file = self.config.NOTIFICATIONS_FILE
        self.logs_file = self.config.LOGS_FILE
        self.settings_file = self.config.SETTINGS_FILE
        self._file_lock = threading.Lock()
        
        # Initialize files
        self.initialize_files()
    
    def initialize_files(self):
        """Create JSON files if they don't exist"""
        files_config = {
            self.products_file: {'products': []},
            self.notifications_file: {'notifications': []},
            self.logs_file: {'logs': []},
            self.settings_file: {
                'settings': {
                    'price_change_threshold': 0,
                    'skip_initial_notification': True,
                    'hourly_summary_enabled': True,
                    'last_scan_time': None
                }
            }
        }
        
        for file_path, default_data in files_config.items():
            if not file_path.exists():
                self._write_json(file_path, default_data)

    def verify_admin(self, username: str, password: str) -> bool:
        """Verify dashboard admin credentials from environment variables."""
        return (
            username == self.config.DASHBOARD_USERNAME
            and password == self.config.DASHBOARD_PASSWORD
        )
    
    def _read_json(self, file_path: Path) -> Dict:
        """Read JSON data from file"""
        with self._file_lock:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return {}
    
    def _write_json(self, file_path: Path, data: Dict):
        """Write JSON data to file"""
        with self._file_lock:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    
    # Product operations
    def get_all_products(self) -> List[Dict]:
        """Get all monitored products"""
        data = self._read_json(self.products_file)
        return data.get('products', [])
    
    def get_product(self, product_id: str) -> Optional[Dict]:
        """Get a specific product by ID"""
        products = self.get_all_products()
        for product in products:
            if product.get('id') == product_id:
                return product
        return None
    
    def add_product(self, name: str, url: str, selectors: Dict = None) -> Dict:
        """Add a new product to monitor"""
        products = self.get_all_products()
        
        product = {
            'id': str(uuid.uuid4()),
            'name': name,
            'url': url,
            'selectors': selectors or {},
            'monitoring_enabled': True,
            'in_stock': None,
            'stock_status': 'unknown',
            'current_price': None,
            'currency': 'USD',
            'last_checked': None,
            'created_at': datetime.now().isoformat(),
            'status_history': []
        }
        
        products.append(product)
        self._write_json(self.products_file, {'products': products})
        
        return product
    
    def update_product(self, product_id: str, updates: Dict) -> bool:
        """Update product information"""
        products = self.get_all_products()
        
        for i, product in enumerate(products):
            if product.get('id') == product_id:
                products[i].update(updates)
                self._write_json(self.products_file, {'products': products})
                return True
        
        return False
    
    def delete_product(self, product_id: str) -> bool:
        """Delete a product from monitoring"""
        products = self.get_all_products()
        products = [p for p in products if p.get('id') != product_id]
        
        self._write_json(self.products_file, {'products': products})
        return True
    
    def update_product_status(self, product_id: str, status_data: Dict):
        """Update product availability status"""
        product = self.get_product(product_id)
        if not product:
            return
        
        product['in_stock'] = status_data.get('in_stock', False)
        product['stock_status'] = status_data.get('stock_status', self._derive_stock_status(product))
        product['current_price'] = status_data.get('price', 0)
        product['currency'] = 'USD'
        product['quantity'] = status_data.get('quantity')
        product['last_checked'] = datetime.now().isoformat()
        
        # Add to status history
        if 'status_history' not in product:
            product['status_history'] = []
        
        product['status_history'].append({
            'timestamp': datetime.now().isoformat(),
            'in_stock': status_data.get('in_stock', False),
            'stock_status': product['stock_status'],
            'price': status_data.get('price', 0),
            'quantity': status_data.get('quantity')
        })
        
        # Keep last 50 history entries
        product['status_history'] = product['status_history'][-50:]
        
        self.update_product(product_id, product)
    
    def add_price_history(self, product_id: str, price_data: Dict):
        """Add price change to history"""
        product = self.get_product(product_id)
        if not product:
            return
        
        if 'price_history' not in product:
            product['price_history'] = []
        
        product['price_history'].append({
            'timestamp': datetime.now().isoformat(),
            'price': price_data.get('price', 0),
            'in_stock': price_data.get('in_stock', False)
        })
        
        # Keep last 100 price entries
        product['price_history'] = product['price_history'][-100:]
        
        self.update_product(product_id, product)
    
    def update_last_check(self, product_id: str):
        """Update last checked timestamp"""
        product = self.get_product(product_id)
        if product:
            product['last_checked'] = datetime.now().isoformat()
            self.update_product(product_id, product)
    
    def get_product_history(self, product_id: str) -> Optional[Dict]:
        """Get the latest status for a product"""
        product = self.get_product(product_id)
        if product and product.get('status_history'):
            return product['status_history'][-1]
        return None
    
    # Notification operations
    def add_notification(self, product_id: str, product_name: str, 
                        notification_type: str, message: str) -> Dict:
        """Add a notification to history"""
        data = self._read_json(self.notifications_file)
        notifications = data.get('notifications', [])
        
        notification = {
            'id': str(uuid.uuid4()),
            'product_id': product_id,
            'product_name': product_name,
            'type': notification_type,
            'message': message,
            'timestamp': datetime.now().isoformat(),
            'sent': True
        }
        
        notifications.append(notification)
        
        # Keep last 1000 notifications
        if len(notifications) > 1000:
            notifications = notifications[-1000:]
        
        self._write_json(self.notifications_file, {'notifications': notifications})
        
        return notification
    
    def get_recent_notifications(self, limit: int = 50) -> List[Dict]:
        """Get recent notifications"""
        data = self._read_json(self.notifications_file)
        notifications = data.get('notifications', [])
        
        # Sort by timestamp descending
        notifications.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return notifications[:limit]
    
    # Log operations
    def add_log(self, level: str, message: str, component: str = None):
        """Add a log entry"""
        data = self._read_json(self.logs_file)
        logs = data.get('logs', [])
        
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            'component': component or 'system'
        }
        
        logs.append(log_entry)
        
        # Keep last 5000 logs
        if len(logs) > 5000:
            logs = logs[-5000:]
        
        self._write_json(self.logs_file, {'logs': logs})
    
    def get_logs(self, limit: int = 100, level: str = None) -> List[Dict]:
        """Get logs with optional filtering"""
        data = self._read_json(self.logs_file)
        logs = data.get('logs', [])
        
        # Sort by timestamp descending
        logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        if level:
            logs = [l for l in logs if l.get('level') == level]
        
        return logs[:limit]
    
    # Settings operations
    def get_settings(self) -> Dict:
        """Get application settings"""
        data = self._read_json(self.settings_file)
        return data.get('settings', {})
    
    def update_settings(self, settings_update: Dict):
        """Update application settings"""
        data = self._read_json(self.settings_file)
        settings = data.get('settings', {})
        settings.update(settings_update)
        
        self._write_json(self.settings_file, {'settings': settings})
    
    # Dashboard statistics
    def get_statistics(self) -> Dict:
        """Get monitoring statistics for dashboard"""
        products = self.get_all_products()
        
        total_products = len(products)
        enabled_products = len([p for p in products if p.get('monitoring_enabled', True)])
        statuses = [self._derive_stock_status(p) for p in products]
        in_stock = len([s for s in statuses if s == 'in_stock'])
        low_stock = len([s for s in statuses if s == 'low_stock'])
        out_of_stock = len([s for s in statuses if s == 'out_of_stock'])
        unknown = len([s for s in statuses if s == 'unknown'])
        
        notifications = self.get_recent_notifications(100)
        
        return {
            'total_products': total_products,
            'enabled_products': enabled_products,
            'in_stock': in_stock,
            'low_stock': low_stock,
            'out_of_stock': out_of_stock,
            'unknown': unknown,
            'total_notifications': len(notifications),
            'recent_notifications_count': len([n for n in notifications if self._is_recent(n.get('timestamp'))])
        }
