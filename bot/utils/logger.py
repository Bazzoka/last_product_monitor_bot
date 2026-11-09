"""
Logging utility for the bot
Handles structured logging to console, application.log, and logs.json
"""

import logging
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import traceback

from bot.config import Config


class Logger:
    """Custom logger with structured logging support"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, log_file: Optional[str] = None):
        """Initialize logger with file and console handlers"""
        if getattr(self, '_initialized', False):
            return
        
        config = Config()
        self.log_file = Path(log_file) if log_file else config.APP_LOG_FILE
        self.json_log_file = config.LOGS_FILE
        self._json_lock = threading.Lock()
        
        self.logger = logging.getLogger('ProductMonitor')
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        self.logger.addHandler(console_handler)
        
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
        ))
        self.logger.addHandler(file_handler)
        
        self.logs_storage = []
        self._initialized = True
    
    def _append_json_log(self, level: str, message: str, component: str = 'system'):
        """Append log entry to logs.json"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            'component': component
        }
        
        with self._json_lock:
            try:
                if self.json_log_file.exists():
                    with open(self.json_log_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                else:
                    data = {'logs': []}
                
                logs = data.get('logs', [])
                logs.append(entry)
                if len(logs) > 5000:
                    logs = logs[-5000:]
                
                with open(self.json_log_file, 'w', encoding='utf-8') as f:
                    json.dump({'logs': logs}, f, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, OSError):
                pass
    
    def _log(self, level: str, message: str, extra: Dict[str, Any] = None, component: str = 'system'):
        """Internal logging method"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            'extra': extra or {},
            'component': component
        }
        
        log_method = getattr(self.logger, level.lower(), self.logger.info)
        log_method(message, extra=extra or {})
        
        self.logs_storage.append(log_entry)
        if len(self.logs_storage) > 1000:
            self.logs_storage.pop(0)
        
        self._append_json_log(level, message, component)
    
    def debug(self, message: str, extra: Dict[str, Any] = None, component: str = 'system'):
        self._log('DEBUG', message, extra, component)
    
    def info(self, message: str, extra: Dict[str, Any] = None, component: str = 'system'):
        self._log('INFO', message, extra, component)
    
    def warning(self, message: str, extra: Dict[str, Any] = None, component: str = 'system'):
        self._log('WARNING', message, extra, component)
    
    def error(self, message: str, extra: Dict[str, Any] = None, component: str = 'system'):
        self._log('ERROR', message, extra, component)
        self.logger.error(traceback.format_exc())
    
    def critical(self, message: str, extra: Dict[str, Any] = None, component: str = 'system'):
        self._log('CRITICAL', message, extra, component)
    
    def get_recent_logs(self, limit: int = 100):
        return self.logs_storage[-limit:]
