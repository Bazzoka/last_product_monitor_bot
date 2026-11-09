"""
Anti-detection techniques for web scraping
Handles random delays, retries, and proxy rotation
"""

import time
import random
from typing import Optional, Callable
from functools import wraps
from bot.utils.logger import Logger


class AntiDetection:
    """Implements anti-detection techniques for web scraping"""
    
    def __init__(self):
        """Initialize anti-detection mechanisms"""
        self.logger = Logger()
    
    @staticmethod
    def random_delay(min_seconds: float = 1, max_seconds: float = 3):
        """Add random delay between requests"""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)
    
    @staticmethod
    def retry(max_attempts: int = 3, delay: float = 1, backoff: float = 2):
        """Decorator for retry logic with exponential backoff"""
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                last_exception = None
                current_delay = delay
                
                for attempt in range(max_attempts):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e
                        if attempt < max_attempts - 1:
                            time.sleep(current_delay)
                            current_delay *= backoff
                
                raise last_exception
            return wrapper
        return decorator
    
    def get_request_headers(self, user_agent: str, referer: Optional[str] = None) -> dict:
        """Get headers with anti-detection measures"""
        accept_encoding = 'gzip, deflate'
        try:
            import brotlicffi  # noqa: F401
            accept_encoding = 'gzip, deflate, br'
        except ImportError:
            try:
                import brotli  # noqa: F401
                accept_encoding = 'gzip, deflate, br'
            except ImportError:
                pass

        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': accept_encoding,
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'User-Agent': user_agent
        }
        
        if referer:
            headers['Referer'] = referer
        
        return headers
    
    def should_use_proxy(self, use_proxy: bool = False) -> bool:
        """Determine if proxy should be used"""
        if not use_proxy:
            return False
        
        # Random chance to use proxy even if enabled
        return random.random() < 0.8
