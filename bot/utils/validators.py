"""
Input validation utilities
"""

import re
from urllib.parse import urlparse


class Validators:
    """Input validation class"""
    
    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate URL format"""
        if not url or not isinstance(url, str):
            return False
        
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    @staticmethod
    def validate_product_name(name: str) -> bool:
        """Validate product name"""
        if not name or not isinstance(name, str):
            return False
        
        # Product name should be between 1 and 200 characters
        if len(name.strip()) < 1 or len(name) > 200:
            return False
        
        # Check for invalid characters
        if re.search(r'[<>]', name):
            return False
        
        return True
    
    @staticmethod
    def validate_price(price: float) -> bool:
        """Validate price value"""
        try:
            return isinstance(price, (int, float)) and 0 <= price <= 1000000
        except:
            return False
    
    @staticmethod
    def sanitize_input(text: str) -> str:
        """Sanitize user input to prevent XSS"""
        if not text:
            return ""
        
        # Remove HTML tags
        text = re.sub(r'<[^>]*>', '', text)
        
        # Escape special characters
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        text = text.replace('"', '&quot;')
        text = text.replace("'", '&#x27;')
        
        return text.strip()
