"""
Base scraper class with common functionality
Supports requests, Selenium, session persistence, and anti-detection
"""

import json
import time
import random
import threading
from typing import Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import requests
from bot.config import Config
from bot.utils.logger import Logger
from bot.scrapers.anti_detection import AntiDetection


class BaseScraper:
    """Base class for all scrapers with common functionality"""
    
    _driver_lock = threading.Lock()
    
    def __init__(self):
        self.config = Config()
        self.logger = Logger()
        self.anti_detection = AntiDetection()
        self.driver = None
        self.session = None
    
    def setup_driver(self):
        """Setup Selenium WebDriver with anti-detection options"""
        with self._driver_lock:
            if self.driver:
                return
            
            chrome_options = Options()
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-infobars')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            if self.config.HEADLESS_BROWSER:
                chrome_options.add_argument('--headless=new')
            
            from bot.utils.user_agents import UserAgentManager
            ua = UserAgentManager().get_random_user_agent()
            chrome_options.add_argument(f'--user-agent={ua}')
            
            proxy_dict = self.config.get_proxy_dict()
            if proxy_dict and proxy_dict.get('http'):
                chrome_options.add_argument(f'--proxy-server={proxy_dict["http"]}')
            
            try:
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {'userAgent': ua})
                self.driver.execute_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                self._load_session_cookies()
                self.logger.info("WebDriver initialized successfully", component='scraper')
            except Exception as e:
                self.logger.error(f"Failed to initialize WebDriver: {e}", component='scraper')
                self.driver = None
    
    def _load_session_cookies(self):
        """Load persisted session cookies into the browser"""
        cookie_file = self.config.SESSION_COOKIES_FILE
        if not cookie_file.exists() or not self.driver:
            return
        
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            
            if cookies:
                self.driver.get('about:blank')
                for cookie in cookies:
                    try:
                        if 'expiry' in cookie:
                            cookie['expiry'] = int(cookie['expiry'])
                        self.driver.add_cookie(cookie)
                    except Exception:
                        pass
                self.logger.info(f"Loaded {len(cookies)} session cookies", component='scraper')
        except (json.JSONDecodeError, OSError) as e:
            self.logger.warning(f"Could not load session cookies: {e}", component='scraper')
    
    def _save_session_cookies(self):
        """Persist browser session cookies to disk"""
        if not self.driver:
            return
        
        try:
            cookies = self.driver.get_cookies()
            with open(self.config.SESSION_COOKIES_FILE, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Could not save session cookies: {e}", component='scraper')
    
    def setup_session(self):
        """Setup requests session with browser-like headers and proxies"""
        if self.session:
            return
        
        self.session = requests.Session()
        from bot.utils.user_agents import UserAgentManager
        ua_manager = UserAgentManager()
        
        headers = self.anti_detection.get_request_headers(ua_manager.get_random_user_agent())
        self.session.headers.update(headers)
        
        proxy_dict = self.config.get_proxy_dict()
        if proxy_dict:
            self.session.proxies.update(proxy_dict)
            self.logger.info("Proxy configured for session", component='scraper')
    
    def get_with_retry(self, url: str, max_retries: int = None) -> Optional[requests.Response]:
        """Get URL with retry logic and browser-like headers"""
        if not self.session:
            self.setup_session()
        
        max_retries = max_retries or self.config.MAX_RETRIES
        
        for attempt in range(max_retries):
            try:
                from bot.utils.user_agents import UserAgentManager
                ua = UserAgentManager().get_random_user_agent()
                headers = self.anti_detection.get_request_headers(ua, referer=url)
                
                self.anti_detection.random_delay(1, 3)
                self._force_storefront_usd_cookies()
                
                response = self.session.get(
                    url,
                    headers=headers,
                    timeout=self.config.REQUEST_TIMEOUT,
                    allow_redirects=True,
                    cookies=self._storefront_usd_cookies(),
                )
                
                if response.status_code == 200:
                    return response
                elif response.status_code in (403, 429):
                    self.logger.warning(
                        f"Got status {response.status_code} for {url}, backing off...",
                        component='scraper'
                    )
                    time.sleep(random.uniform(10, 20))
                else:
                    self.logger.warning(
                        f"Got status {response.status_code} for {url}",
                        component='scraper'
                    )
                    
            except requests.RequestException as e:
                self.logger.error(
                    f"Request failed (attempt {attempt + 1}/{max_retries}): {e}",
                    component='scraper'
                )
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(5, 10))
        
        return None

    def fetch_url(self, url: str, max_retries: int = None) -> Optional[requests.Response]:
        """Fetch URL and return the response even for 404/410 (for product-removal detection)."""
        if not self.session:
            self.setup_session()

        max_retries = max_retries or self.config.MAX_RETRIES
        last_response: Optional[requests.Response] = None

        for attempt in range(max_retries):
            try:
                from bot.utils.user_agents import UserAgentManager
                ua = UserAgentManager().get_random_user_agent()
                headers = self.anti_detection.get_request_headers(ua, referer=url)

                self.anti_detection.random_delay(1, 3)
                self._force_storefront_usd_cookies()

                response = self.session.get(
                    url,
                    headers=headers,
                    timeout=self.config.REQUEST_TIMEOUT,
                    allow_redirects=True,
                    cookies=self._storefront_usd_cookies(),
                )
                last_response = response

                if response.status_code in (200, 404, 410):
                    return response
                if response.status_code in (403, 429):
                    self.logger.warning(
                        f"Got status {response.status_code} for {url}, backing off...",
                        component='scraper',
                    )
                    time.sleep(random.uniform(10, 20))
                else:
                    self.logger.warning(
                        f"Got status {response.status_code} for {url}",
                        component='scraper',
                    )

            except requests.RequestException as e:
                self.logger.error(
                    f"Request failed (attempt {attempt + 1}/{max_retries}): {e}",
                    component='scraper',
                )
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(5, 10))

        return last_response

    def _storefront_usd_cookies(self) -> Dict[str, str]:
        """Ask Shopify Markets / currency switchers for the shop USD price."""
        return {'cart_currency': 'USD', 'localization': 'US'}

    def _force_storefront_usd_cookies(self) -> None:
        """Drop geo-localized currency cookies so later requests stay on USD."""
        if not self.session:
            return
        for cookie in list(self.session.cookies):
            if cookie.name not in ('cart_currency', 'localization'):
                continue
            if cookie.name == 'cart_currency' and cookie.value == 'USD':
                continue
            if cookie.name == 'localization' and cookie.value == 'US':
                continue
            try:
                self.session.cookies.clear(cookie.domain, cookie.path, cookie.name)
            except Exception:
                pass
    
    def wait_for_element(self, by: By, value: str, timeout: int = None):
        """Wait for element to be present on the page"""
        if not self.driver:
            self.setup_driver()
        
        timeout = timeout or self.config.REQUEST_TIMEOUT
        
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
        except TimeoutException:
            self.logger.error(f"Timeout waiting for element: {value}", component='scraper')
            return None
    
    def cleanup(self):
        """Clean up scraper resources"""
        if self.driver:
            try:
                self._save_session_cookies()
                self.driver.quit()
                self.logger.info("WebDriver closed", component='scraper')
            except Exception:
                pass
            self.driver = None
        
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
            self.session = None
