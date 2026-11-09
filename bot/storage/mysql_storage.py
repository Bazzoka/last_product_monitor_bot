"""
MySQL/MariaDB storage for products, notifications, logs, settings, and admins.
"""

import json
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import bcrypt
import pymysql
from pymysql.cursors import DictCursor

from bot.config import Config
from bot.storage.storage_mixin import StorageMixin


class MySQLStorage(StorageMixin):
    """Manages MariaDB/MySQL storage operations."""

    def __init__(self):
        self.config = Config()
        self._lock = threading.Lock()

    @contextmanager
    def _connection(self):
        conn = pymysql.connect(
            host=self.config.DB_HOST,
            port=self.config.DB_PORT,
            user=self.config.DB_USER,
            password=self.config.DB_PASSWORD,
            database=self.config.DB_NAME,
            charset='utf8mb4',
            cursorclass=DictCursor,
            autocommit=False,
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_files(self):
        """Ensure database is reachable and seed defaults."""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                self._ensure_default_settings(cur)
                self._ensure_default_admin(cur)

    def verify_admin(self, username: str, password: str) -> bool:
        """Verify dashboard admin credentials against the admins table."""
        if not username or not password:
            return False
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM admins WHERE username = %s",
                    (username,),
                )
                row = cur.fetchone()
        if not row:
            return (
                username == self.config.DASHBOARD_USERNAME
                and password == self.config.DASHBOARD_PASSWORD
            )
        stored_hash = row['password_hash']
        if isinstance(stored_hash, bytes):
            stored_hash = stored_hash.decode('utf-8')
        return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))

    def _ensure_default_settings(self, cur):
        defaults = {
            'price_change_threshold': '0',
            'skip_initial_notification': 'true',
            'hourly_summary_enabled': 'true',
            'last_scan_time': None,
        }
        for key, value in defaults.items():
            cur.execute(
                "INSERT IGNORE INTO settings (setting_key, setting_value) VALUES (%s, %s)",
                (key, value),
            )

    def _ensure_default_admin(self, cur):
        cur.execute("SELECT COUNT(*) AS count FROM admins")
        if cur.fetchone()['count'] > 0:
            return
        username = self.config.DASHBOARD_USERNAME
        password = self.config.DASHBOARD_PASSWORD
        password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt(),
        ).decode('utf-8')
        cur.execute(
            "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
            (username, password_hash),
        )

    @staticmethod
    def _to_iso(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _to_bool(value: Any) -> Optional[bool]:
        if value is None:
            return None
        return bool(value)

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        return float(value)

    def _row_to_product(self, row: Dict, include_history: bool = False) -> Dict:
        selectors = row.get('selectors')
        if isinstance(selectors, str):
            try:
                selectors = json.loads(selectors) if selectors else {}
            except json.JSONDecodeError:
                selectors = {}
        elif selectors is None:
            selectors = {}

        product = {
            'id': row['id'],
            'name': row['name'],
            'url': row['url'],
            'selectors': selectors,
            'monitoring_enabled': self._to_bool(row.get('monitoring_enabled')),
            'in_stock': self._to_bool(row.get('in_stock')),
            'stock_status': row.get('stock_status') or 'unknown',
            'current_price': self._to_float(row.get('current_price')),
            'currency': row.get('currency') or 'USD',
            'quantity': row.get('quantity'),
            'last_checked': self._to_iso(row.get('last_checked')),
            'created_at': self._to_iso(row.get('created_at')),
            'updated_at': self._to_iso(row.get('updated_at')),
        }
        if include_history:
            product['status_history'] = self._fetch_status_history(product['id'])
            product['price_history'] = self._fetch_price_history(product['id'])
        return product

    def _fetch_status_history(self, product_id: str, limit: int = 50) -> List[Dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT in_stock, stock_status, price, quantity, checked_at
                    FROM status_history
                    WHERE product_id = %s
                    ORDER BY checked_at DESC
                    LIMIT %s
                    """,
                    (product_id, limit),
                )
                rows = cur.fetchall()
        history = []
        for row in reversed(rows):
            history.append({
                'timestamp': self._to_iso(row['checked_at']),
                'in_stock': self._to_bool(row.get('in_stock')),
                'stock_status': row.get('stock_status'),
                'price': self._to_float(row.get('price')),
                'quantity': row.get('quantity'),
            })
        return history

    def _fetch_price_history(self, product_id: str, limit: int = 100) -> List[Dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT old_price, new_price, changed_at
                    FROM price_history
                    WHERE product_id = %s
                    ORDER BY changed_at DESC
                    LIMIT %s
                    """,
                    (product_id, limit),
                )
                rows = cur.fetchall()
        history = []
        for row in reversed(rows):
            history.append({
                'timestamp': self._to_iso(row['changed_at']),
                'price': self._to_float(row.get('new_price')),
                'old_price': self._to_float(row.get('old_price')),
            })
        return history

    def get_all_products(self) -> List[Dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM products ORDER BY created_at DESC")
                rows = cur.fetchall()
        return [self._row_to_product(row) for row in rows]

    def get_product(self, product_id: str) -> Optional[Dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
                row = cur.fetchone()
        if not row:
            return None
        return self._row_to_product(row, include_history=True)

    def add_product(self, name: str, url: str, selectors: Dict = None) -> Dict:
        product_id = str(uuid.uuid4())
        selectors_json = json.dumps(selectors or {})
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO products (
                        id, name, url, selectors, monitoring_enabled,
                        stock_status, currency
                    ) VALUES (%s, %s, %s, %s, 1, 'unknown', 'USD')
                    """,
                    (product_id, name, url, selectors_json),
                )
        return self.get_product(product_id) or {
            'id': product_id,
            'name': name,
            'url': url,
            'selectors': selectors or {},
            'monitoring_enabled': True,
            'in_stock': None,
            'stock_status': 'unknown',
            'current_price': None,
            'currency': 'USD',
            'quantity': None,
            'last_checked': None,
            'created_at': datetime.now().isoformat(),
            'status_history': [],
        }

    def update_product(self, product_id: str, updates: Dict) -> bool:
        allowed = {
            'name', 'url', 'selectors', 'monitoring_enabled', 'in_stock',
            'stock_status', 'current_price', 'currency', 'quantity',
            'last_checked',
        }
        fields = []
        values = []
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == 'selectors' and isinstance(value, dict):
                value = json.dumps(value)
            fields.append(f"{key} = %s")
            values.append(value)
        if not fields:
            return False
        values.append(product_id)
        sql = f"UPDATE products SET {', '.join(fields)} WHERE id = %s"
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, values)
                return cur.rowcount > 0

    def delete_product(self, product_id: str) -> bool:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
                return cur.rowcount > 0

    def update_product_status(self, product_id: str, status_data: Dict):
        product = self.get_product(product_id)
        if not product:
            return

        stock_status = status_data.get(
            'stock_status',
            self._derive_stock_status({**product, **status_data}),
        )
        in_stock = status_data.get('in_stock', False)
        price = status_data.get('price', 0)
        currency = 'USD'
        quantity = status_data.get('quantity')
        now = datetime.now()

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE products
                    SET in_stock = %s, stock_status = %s, current_price = %s,
                        currency = %s, quantity = %s, last_checked = %s
                    WHERE id = %s
                    """,
                    (in_stock, stock_status, price, currency, quantity, now, product_id),
                )
                cur.execute(
                    """
                    INSERT INTO status_history (
                        product_id, in_stock, stock_status, price, quantity, checked_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (product_id, in_stock, stock_status, price, quantity, now),
                )
                cur.execute(
                    """
                    DELETE FROM status_history
                    WHERE product_id = %s AND id NOT IN (
                        SELECT id FROM (
                            SELECT id FROM status_history
                            WHERE product_id = %s
                            ORDER BY checked_at DESC
                            LIMIT 50
                        ) AS recent
                    )
                    """,
                    (product_id, product_id),
                )

    def add_price_history(self, product_id: str, price_data: Dict):
        new_price = price_data.get('price', 0)
        currency = 'USD'
        now = datetime.now()
        old_price = None

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT new_price FROM price_history
                    WHERE product_id = %s
                    ORDER BY changed_at DESC
                    LIMIT 1
                    """,
                    (product_id,),
                )
                row = cur.fetchone()
                if row:
                    old_price = row['new_price']
                else:
                    cur.execute(
                        """
                        SELECT price FROM status_history
                        WHERE product_id = %s
                        ORDER BY checked_at DESC
                        LIMIT 1 OFFSET 1
                        """,
                        (product_id,),
                    )
                    prev = cur.fetchone()
                    if prev:
                        old_price = prev['price']

                cur.execute(
                    """
                    INSERT INTO price_history (
                        product_id, old_price, new_price, currency, changed_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (product_id, old_price, new_price, currency, now),
                )
                cur.execute(
                    """
                    DELETE FROM price_history
                    WHERE product_id = %s AND id NOT IN (
                        SELECT id FROM (
                            SELECT id FROM price_history
                            WHERE product_id = %s
                            ORDER BY changed_at DESC
                            LIMIT 100
                        ) AS recent
                    )
                    """,
                    (product_id, product_id),
                )

    def update_last_check(self, product_id: str):
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE products SET last_checked = %s WHERE id = %s",
                    (datetime.now(), product_id),
                )

    def get_product_history(self, product_id: str) -> Optional[Dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT in_stock, stock_status, price, quantity, checked_at
                    FROM status_history
                    WHERE product_id = %s
                    ORDER BY checked_at DESC
                    LIMIT 1
                    """,
                    (product_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            'timestamp': self._to_iso(row['checked_at']),
            'in_stock': self._to_bool(row.get('in_stock')),
            'stock_status': row.get('stock_status'),
            'price': self._to_float(row.get('price')),
            'quantity': row.get('quantity'),
        }

    def add_notification(
        self,
        product_id: str,
        product_name: str,
        notification_type: str,
        message: str,
    ) -> Dict:
        notification_id = str(uuid.uuid4())
        now = datetime.now()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO notifications (
                        id, product_id, product_name, type, message, sent, sent_at
                    ) VALUES (%s, %s, %s, %s, %s, 1, %s)
                    """,
                    (notification_id, product_id, product_name, notification_type, message, now),
                )
                cur.execute(
                    """
                    DELETE FROM notifications
                    WHERE id NOT IN (
                        SELECT id FROM (
                            SELECT id FROM notifications
                            ORDER BY sent_at DESC
                            LIMIT 1000
                        ) AS recent
                    )
                    """
                )
        return {
            'id': notification_id,
            'product_id': product_id,
            'product_name': product_name,
            'type': notification_type,
            'message': message,
            'timestamp': now.isoformat(),
            'sent': True,
        }

    def get_recent_notifications(self, limit: int = 50) -> List[Dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, product_id, product_name, type, message, sent, sent_at
                    FROM notifications
                    ORDER BY sent_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        notifications = []
        for row in rows:
            notifications.append({
                'id': row['id'],
                'product_id': row['product_id'],
                'product_name': row.get('product_name'),
                'type': row['type'],
                'message': row['message'],
                'timestamp': self._to_iso(row['sent_at']),
                'sent': self._to_bool(row.get('sent')),
            })
        return notifications

    def add_log(self, level: str, message: str, component: str = None):
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_logs (level, message, component)
                    VALUES (%s, %s, %s)
                    """,
                    (level, message, component or 'system'),
                )
                cur.execute(
                    """
                    DELETE FROM bot_logs
                    WHERE id NOT IN (
                        SELECT id FROM (
                            SELECT id FROM bot_logs
                            ORDER BY created_at DESC
                            LIMIT 5000
                        ) AS recent
                    )
                    """
                )

    def get_logs(self, limit: int = 100, level: str = None) -> List[Dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                if level:
                    cur.execute(
                        """
                        SELECT level, message, component, created_at
                        FROM bot_logs
                        WHERE level = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (level, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT level, message, component, created_at
                        FROM bot_logs
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                rows = cur.fetchall()
        logs = []
        for row in rows:
            logs.append({
                'timestamp': self._to_iso(row['created_at']),
                'level': row['level'],
                'message': row['message'],
                'component': row.get('component') or 'system',
            })
        return logs

    def get_settings(self) -> Dict:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT setting_key, setting_value FROM settings")
                rows = cur.fetchall()
        settings = {}
        for row in rows:
            key = row['setting_key']
            value = row['setting_value']
            if value is None:
                settings[key] = None
            elif value.lower() in ('true', 'false'):
                settings[key] = value.lower() == 'true'
            else:
                try:
                    if '.' in value:
                        settings[key] = float(value)
                    else:
                        settings[key] = int(value)
                except (ValueError, TypeError):
                    settings[key] = value
        return settings

    def update_settings(self, settings_update: Dict):
        with self._connection() as conn:
            with conn.cursor() as cur:
                for key, value in settings_update.items():
                    if value is None:
                        stored = None
                    elif isinstance(value, bool):
                        stored = 'true' if value else 'false'
                    else:
                        stored = str(value)
                    cur.execute(
                        """
                        INSERT INTO settings (setting_key, setting_value)
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
                        """,
                        (key, stored),
                    )

    def get_statistics(self) -> Dict:
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
            'recent_notifications_count': len([
                n for n in notifications if self._is_recent(n.get('timestamp'))
            ]),
        }
