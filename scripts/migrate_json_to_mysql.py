#!/usr/bin/env python3
"""
One-time migration: copy JSON data files into MySQL/MariaDB.

Usage (from product-monitor-bot folder):
    python scripts/migrate_json_to_mysql.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.config import Config
from bot.storage.mysql_storage import MySQLStorage


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def load_json(path: Path, key: str):
    if not path.exists():
        return []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get(key, [])


def migrate():
    config = Config()
    if not config.use_mysql():
        print('Set DB_HOST and DB_NAME in .env (or STORAGE_BACKEND=mysql) before migrating.')
        sys.exit(1)

    storage = MySQLStorage()
    storage.initialize_files()

    data_dir = config.DATA_DIR
    products = load_json(data_dir / 'products.json', 'products')
    notifications = load_json(data_dir / 'notifications.json', 'notifications')
    logs = load_json(data_dir / 'logs.json', 'logs')
    settings_data = {}
    settings_path = data_dir / 'settings.json'
    if settings_path.exists():
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings_data = json.load(f).get('settings', {})

    migrated_products = 0
    migrated_notifications = 0
    migrated_logs = 0

    with storage._connection() as conn:
        with conn.cursor() as cur:
            for product in products:
                cur.execute("SELECT id FROM products WHERE id = %s", (product['id'],))
                if cur.fetchone():
                    continue

                selectors = json.dumps(product.get('selectors') or {})
                stock_status = product.get('stock_status') or 'unknown'
                if stock_status not in ('in_stock', 'low_stock', 'out_of_stock', 'unknown'):
                    stock_status = 'unknown'

                cur.execute(
                    """
                    INSERT INTO products (
                        id, name, url, selectors, monitoring_enabled, in_stock,
                        stock_status, current_price, currency, quantity,
                        last_checked, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        product['id'],
                        product['name'],
                        product['url'],
                        selectors,
                        1 if product.get('monitoring_enabled', True) else 0,
                        product.get('in_stock'),
                        stock_status,
                        product.get('current_price'),
                        product.get('currency', 'USD'),
                        product.get('quantity'),
                        parse_ts(product.get('last_checked')),
                        parse_ts(product.get('created_at')) or datetime.now(),
                    ),
                )
                migrated_products += 1

                prev_price = None
                for entry in product.get('status_history', []):
                    status = entry.get('stock_status') or stock_status
                    if status not in ('in_stock', 'low_stock', 'out_of_stock', 'unknown'):
                        status = None
                    cur.execute(
                        """
                        INSERT INTO status_history (
                            product_id, in_stock, stock_status, price, quantity, checked_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            product['id'],
                            entry.get('in_stock'),
                            status,
                            entry.get('price'),
                            entry.get('quantity'),
                            parse_ts(entry.get('timestamp')) or datetime.now(),
                        ),
                    )

                for entry in product.get('price_history', []):
                    new_price = entry.get('price', 0)
                    cur.execute(
                        """
                        INSERT INTO price_history (
                            product_id, old_price, new_price, currency, changed_at
                        ) VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            product['id'],
                            prev_price,
                            new_price,
                            product.get('currency', 'USD'),
                            parse_ts(entry.get('timestamp')) or datetime.now(),
                        ),
                    )
                    prev_price = new_price

            for note in notifications:
                cur.execute("SELECT id FROM notifications WHERE id = %s", (note['id'],))
                if cur.fetchone():
                    continue
                cur.execute(
                    """
                    INSERT INTO notifications (
                        id, product_id, product_name, type, message, sent, sent_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        note['id'],
                        note['product_id'],
                        note.get('product_name'),
                        note['type'],
                        note['message'],
                        1 if note.get('sent', True) else 0,
                        parse_ts(note.get('timestamp')) or datetime.now(),
                    ),
                )
                migrated_notifications += 1

            for log in logs:
                cur.execute(
                    """
                    INSERT INTO bot_logs (level, message, component, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        log.get('level', 'INFO'),
                        log.get('message', ''),
                        log.get('component', 'system'),
                        parse_ts(log.get('timestamp')) or datetime.now(),
                    ),
                )
                migrated_logs += 1

    if settings_data:
        storage.update_settings(settings_data)

    print(f'Migration complete: {migrated_products} products, '
          f'{migrated_notifications} notifications, {migrated_logs} logs.')


if __name__ == '__main__':
    migrate()
