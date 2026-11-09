"""
User agent management for rotating user agents
"""

import random
from fake_useragent import UserAgent


class UserAgentManager:
    """Manages rotating user agents for anti-detection"""
    
    def __init__(self):
        """Initialize user agent manager"""
        try:
            self.ua = UserAgent()
        except:
            self.ua = None
            self.fallback_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
            ]
    
    def get_random_user_agent(self) -> str:
        """Get a random user agent string"""
        if self.ua:
            try:
                return self.ua.random
            except:
                pass
        
        return random.choice(self.fallback_agents)
    
    def get_desktop_user_agent(self) -> str:
        """Get a desktop user agent"""
        if self.ua:
            try:
                return self.ua.chrome
            except:
                pass
        
        return self.fallback_agents[0]
    
    def get_mobile_user_agent(self) -> str:
        """Get a mobile user agent"""
        if self.ua:
            try:
                return self.ua.android
            except:
                pass
        
        return 'Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
