"""
Configuration management for the bot
Handles environment variables and configuration settings
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Project root directory
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / '.env'


class Config:
    """Configuration manager for the bot"""
    
    def __init__(self):
        """Load configuration from environment variables"""
        load_dotenv(dotenv_path=ENV_PATH)
        
        # Email configuration
        self.EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com').strip()
        self.EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
        self.EMAIL_USERNAME = os.getenv('EMAIL_USERNAME', '').strip()
        # Gmail app passwords are often pasted with spaces — remove them
        self.EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '').replace(' ', '').strip()
        self.EMAIL_FROM = os.getenv('EMAIL_FROM', '').strip() or self.EMAIL_USERNAME
        self.EMAIL_TO = os.getenv('EMAIL_TO', '').strip()
        self.EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'false').lower() == 'true'
        self.EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'true').lower() == 'true'
        
        # Telegram configuration
        self.TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
        chat_id_raw = os.getenv('TELEGRAM_CHAT_ID', '').strip()
        # Chat IDs are numeric; strip accidental trailing characters (e.g. "6588637300ss")
        if chat_id_raw and chat_id_raw.lstrip('-').isdigit():
            self.TELEGRAM_CHAT_ID = chat_id_raw
        else:
            digits = ''.join(c for c in chat_id_raw if c.isdigit() or (c == '-' and not chat_id_raw.replace('-', '').isdigit()))
            self.TELEGRAM_CHAT_ID = digits if digits else chat_id_raw
        
        # Proxy configuration
        self.USE_PROXY = os.getenv('USE_PROXY', 'false').lower() == 'true'
        self.PROXY_HTTP = os.getenv('PROXY_HTTP', '')
        self.PROXY_HTTPS = os.getenv('PROXY_HTTPS', '')
        
        # Database configuration (MariaDB/MySQL)
        self.DB_HOST = os.getenv('DB_HOST', '127.0.0.1').strip()
        self.DB_PORT = int(os.getenv('DB_PORT', 3306))
        self.DB_NAME = os.getenv('DB_NAME', 'bot').strip()
        self.DB_USER = os.getenv('DB_USER', 'root').strip()
        self.DB_PASSWORD = os.getenv('DB_PASSWORD', '').strip()
        self.STORAGE_BACKEND = os.getenv('STORAGE_BACKEND', 'auto').strip().lower()

        # Dashboard configuration
        self.DASHBOARD_USERNAME = os.getenv('DASHBOARD_USERNAME', 'admin')
        self.DASHBOARD_PASSWORD = os.getenv('DASHBOARD_PASSWORD', 'admin123')
        self.DASHBOARD_SECRET_KEY = os.getenv('DASHBOARD_SECRET_KEY', 'dev-secret-key-change-in-production')
        self.DASHBOARD_HOST = os.getenv('DASHBOARD_HOST', '127.0.0.1')
        self.DASHBOARD_PORT = int(os.getenv('DASHBOARD_PORT', 8080))
        
        # Monitoring settings
        self.CHECK_INTERVAL_HOURS = int(os.getenv('CHECK_INTERVAL_HOURS', 1))
        self.MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
        self.REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', 30))
        self.MAX_CONCURRENT_CHECKS = int(os.getenv('MAX_CONCURRENT_CHECKS', 10))
        self.LOW_STOCK_THRESHOLD = int(os.getenv('LOW_STOCK_THRESHOLD', 5))
        self.HEADLESS_BROWSER = os.getenv('HEADLESS_BROWSER', 'true').lower() == 'true'
        
        # File paths
        self.DATA_DIR = ROOT_DIR / 'data'
        self.LOGS_DIR = ROOT_DIR / 'bot' / 'logs'
        self.SESSION_DIR = self.DATA_DIR / 'session'
        self.PRODUCTS_FILE = self.DATA_DIR / 'products.json'
        self.NOTIFICATIONS_FILE = self.DATA_DIR / 'notifications.json'
        self.LOGS_FILE = self.DATA_DIR / 'logs.json'
        self.SETTINGS_FILE = self.DATA_DIR / 'settings.json'
        self.APP_LOG_FILE = self.LOGS_DIR / 'application.log'
        self.SESSION_COOKIES_FILE = self.SESSION_DIR / 'cookies.json'
        
        # Ensure directories exist
        self.DATA_DIR.mkdir(exist_ok=True)
        self.LOGS_DIR.mkdir(exist_ok=True)
        self.SESSION_DIR.mkdir(exist_ok=True)
    
    def get(self, key, default=None):
        """Get configuration value by key"""
        return getattr(self, key, default)

    def use_mysql(self) -> bool:
        """Return True when MySQL/MariaDB storage should be used."""
        if self.STORAGE_BACKEND == 'json':
            return False
        if self.STORAGE_BACKEND == 'mysql':
            return True
        return bool(self.DB_HOST and self.DB_NAME)
    
    def is_email_configured(self):
        """Check if email notifications are configured with real credentials"""
        placeholders = {
            'your_email@gmail.com', 'your_app_password', 'recipient@example.com',
            'your_email@example.com'
        }
        if not (self.EMAIL_USERNAME and self.EMAIL_PASSWORD and self.EMAIL_TO):
            return False
        if self.EMAIL_USERNAME.lower() in placeholders:
            return False
        if self.EMAIL_PASSWORD.lower() in placeholders:
            return False
        if self.EMAIL_TO.lower() in placeholders:
            return False
        return True
    
    def is_telegram_configured(self):
        """Check if telegram notifications are configured"""
        if not (self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID):
            return False
        if 'your_bot_token' in self.TELEGRAM_BOT_TOKEN.lower():
            return False
        if 'your_chat_id' in self.TELEGRAM_CHAT_ID.lower():
            return False
        return True
    
    def get_config_warnings(self):
        """Return list of configuration issues to log at startup"""
        warnings = []
        if not self.is_email_configured():
            if os.getenv('EMAIL_USERNAME', '').strip():
                warnings.append(
                    'Email credentials look like placeholders or are incomplete. '
                    'Set real Gmail app password values in .env (see README).'
                )
        if not self.is_telegram_configured():
            if os.getenv('TELEGRAM_BOT_TOKEN', '').strip():
                warnings.append('Telegram bot token or chat ID is missing/invalid in .env')
        return warnings
    
    def get_proxy_dict(self):
        """Get proxy configuration as dictionary for requests"""
        if not self.USE_PROXY:
            return None
        
        proxies = {}
        if self.PROXY_HTTP:
            proxies['http'] = self.PROXY_HTTP
        if self.PROXY_HTTPS:
            proxies['https'] = self.PROXY_HTTPS
        
        return proxies if proxies else None
