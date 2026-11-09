"""
Product scraper for extracting availability and price information
"""

import json
import re
import threading
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote_plus, urlparse
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from bot.scrapers.base_scraper import BaseScraper
from bot.utils.logger import Logger
from bot.utils.user_agents import UserAgentManager


class ProductScraper(BaseScraper):
    """Scrapes product information from various websites"""

    _selenium_lock = threading.Lock()

    JS_SITES = [
        'amazon', 'walmart', 'target', 'bestbuy', 'newegg',
        'ebay', 'aliexpress', 'etsy'
    ]

    SHOPIFY_INDICATORS = ('cdn/shop', 'shopify', 'myshopify.com')

    REMOVED_PAGE_SELECTORS = (
        '.template-404', '.page-404', '.main-404', '.error-404',
        '[data-template="404"]', 'body.template-404',
        'body[class*="template-404"]', 'body[class*="404"]',
        '#shopify-section-template--404', '.errors-404',
    )

    REMOVED_PAGE_PHRASES = (
        'page not found',
        '404 not found',
        'this page could not be found',
        'the page you requested does not exist',
        'the page you were looking for does not exist',
        'the page you are looking for does not exist',
        'we can\'t find the page',
        'we cannot find the page',
        'sorry, this page isn\'t available',
        'product you are looking for',
        'no longer available',
        'no longer exists',
        'has been removed',
        'this product is no longer',
        'this item is no longer',
        'couldn\'t find the page',
        'could not find the page',
        'product is unavailable',
        'product unavailable',
    )

    NON_USD_CURRENCY_RE = re.compile(
        r'\b(?:EGP|SAR|AED|EUR|GBP|CAD|AUD|SEK|NOK|DKK|JPY|CHF)\b|'
        r'(?<![A-Za-z])LE\s*[\d,]|ج\.?\s*م',
        re.IGNORECASE,
    )
    USD_CURRENCY_RE = re.compile(r'(?:US\s*\$|US\$|\$|\bUSD\b)', re.IGNORECASE)

    OUT_OF_STOCK_KEYWORDS = (
        'out of stock', 'sold out', 'unavailable', 'not available',
        'currently unavailable', 'temporarily out of stock', 'discontinued'
    )

    IN_STOCK_KEYWORDS = (
        'in stock', 'add to cart', 'buy now', 'add to bag', 'only \\d+ left'
    )

    LOW_STOCK_PATTERNS = (
        r'low\s+stock',
        r'limited\s+stock',
        r'only\s+a\s+few\s+left',
        r'almost\s+gone',
        r'hurry,\s+only',
        r'only\s+\d+\s+left',
    )

    INVENTORY_SELECTORS = (
        '.product__inventory', '.product-inventory', '#VariantInventory',
        '.product-form__inventory', '.inventory-notice', '.stock-level',
        '[data-product-stock]', '[data-inventory-quantity]',
    )

    CURRENCY_SYMBOLS = {
        '$': 'USD', 'US$': 'USD', '€': 'EUR', '£': 'GBP', '¥': 'JPY',
        'A$': 'AUD', 'C$': 'CAD', 'EGP': 'EGP', 'SAR': 'SAR', 'AED': 'AED',
    }

    AMAZON_PRICE_SELECTORS = (
        '.apex-pricetopay-value',
        '.priceToPay',
        '.reinventPricePriceToPayMargin',
    )

    def __init__(self):
        super().__init__()
        self.logger = Logger()
        self.ua_manager = UserAgentManager()

    def scrape_product(self, url: str, product_config: Dict) -> Optional[Dict]:
        """Scrape product information from URL"""
        self.logger.info(f"Scraping product from {url}", component='scraper')

        force_js = product_config.get('selectors', {}).get('use_javascript', False)

        if force_js or self.needs_javascript_rendering(url):
            return self.scrape_with_selenium(url, product_config)
        return self.scrape_with_requests(url, product_config)

    def needs_javascript_rendering(self, url: str) -> bool:
        """Determine if URL likely needs JavaScript rendering"""
        return any(site in url.lower() for site in self.JS_SITES)

    def scrape_with_requests(self, url: str, product_config: Dict) -> Optional[Dict]:
        """Scrape using requests and BeautifulSoup"""
        response = self.fetch_url(url)

        if response is None:
            self.logger.error(f"Failed to fetch {url}", component='scraper')
            return None

        if response.status_code in (404, 410):
            return self._build_removed_product_data(url, product_config)

        if self._url_indicates_product_removed(url, response.url):
            return self._build_removed_product_data(url, product_config)

        soup = BeautifulSoup(response.content, 'html.parser')
        return self._extract_product_data(
            soup, url, product_config, final_url=response.url
        )

    def scrape_with_selenium(self, url: str, product_config: Dict) -> Optional[Dict]:
        """Scrape using Selenium for JavaScript-rendered content"""
        with self._selenium_lock:
            if not self.driver:
                self.setup_driver()

            if not self.driver:
                self.logger.error("WebDriver not available, falling back to requests", component='scraper')
                return self.scrape_with_requests(url, product_config)

            try:
                user_agent = self.ua_manager.get_random_user_agent()
                self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {'userAgent': user_agent})

                self.driver.get(url)
                self.anti_detection.random_delay(2, 5)

                wait_selector = product_config.get('selectors', {}).get('wait_for')
                if wait_selector:
                    self.wait_for_element(By.CSS_SELECTOR, wait_selector)
                else:
                    self.wait_for_element(By.TAG_NAME, 'body', timeout=15)

                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                self._save_session_cookies()
                final_url = self.driver.current_url
                if self._url_indicates_product_removed(url, final_url):
                    return self._build_removed_product_data(url, product_config)
                return self._extract_product_data(soup, url, product_config, final_url=final_url)

            except Exception as e:
                self.logger.error(f"Error scraping with Selenium: {e}", component='scraper')
                return self.scrape_with_requests(url, product_config)

    def _extract_product_data(
        self,
        soup: BeautifulSoup,
        url: str,
        product_config: Dict,
        final_url: Optional[str] = None,
    ) -> Dict:
        """Extract product data from parsed HTML"""
        selectors = product_config.get('selectors', {})
        shopify_api = {}
        is_shopify = self._is_shopify_product_url(url, soup)
        if '/products/' in url.lower():
            shopify_api = self._fetch_shopify_product_json(url)
            if shopify_api:
                is_shopify = True
        if shopify_api.get('product_removed'):
            return self._build_removed_product_data(url, product_config)

        page_currency = self._active_shopify_currency(soup)
        if shopify_api.get('price') and page_currency and page_currency != 'USD':
            shopify_api = dict(shopify_api)
            shopify_api.pop('price', None)

        structured = self._extract_structured_data(soup, url)
        if shopify_api:
            # Shopify .js is requested in USD; keep it over geo-converted JSON-LD/EGP.
            structured = self._merge_product_sources(shopify_api, structured)
        amazon_data = self._extract_amazon_data(soup) if self._is_amazon_url(url) else {}

        product_data = {
            'url': url,
            'timestamp': self.get_current_timestamp(),
            'in_stock': False,
            'price': 0.0,
            'currency': 'USD',
            'quantity': None,
            'title': product_config.get('name', ''),
            'is_product_page': structured.get('is_product_page', True),
        }

        stock_selectors = selectors.get('stock', [])
        if stock_selectors:
            product_data['in_stock'] = self.check_stock_with_selectors(soup, stock_selectors)
        elif amazon_data.get('in_stock') is not None:
            product_data['in_stock'] = amazon_data['in_stock']
        elif structured.get('in_stock') is not None:
            product_data['in_stock'] = structured['in_stock']
        else:
            product_data['in_stock'] = self.auto_detect_stock(soup)

        if structured.get('quantity') is not None:
            product_data['quantity'] = structured['quantity']
        else:
            product_data['quantity'] = self._detect_quantity_from_page(soup)

        price_selectors = selectors.get('price', [])
        if price_selectors:
            product_data['price'] = self.extract_price_with_selectors(soup, price_selectors)
        if not product_data.get('price') and amazon_data.get('price'):
            product_data['price'] = amazon_data['price']
        if not product_data.get('price') and structured.get('price'):
            product_data['price'] = structured['price']
        if not product_data.get('price'):
            product_data['price'] = self.auto_detect_price(soup)

        title_selectors = selectors.get('title', [])
        if title_selectors:
            product_data['title'] = self.extract_title_with_selectors(soup, title_selectors)
        elif structured.get('title'):
            product_data['title'] = structured['title']
        elif not product_data['title']:
            product_data['title'] = self.extract_title_with_selectors(
                soup, ['h1', 'meta[property="og:title"]']
            )

        self._apply_product_removal_heuristics(
            product_data, soup, url, final_url=final_url, is_shopify=is_shopify, shopify_api=shopify_api
        )
        self._apply_stock_status(product_data, soup)
        product_data['currency'] = 'USD'

        return product_data

    def _build_removed_product_data(self, url: str, product_config: Dict) -> Dict:
        """Minimal payload when a storefront deleted or unpublished the product."""
        return {
            'url': url,
            'timestamp': self.get_current_timestamp(),
            'in_stock': False,
            'price': 0.0,
            'currency': 'USD',
            'quantity': 0,
            'title': product_config.get('name', ''),
            'is_product_page': False,
            'product_removed': True,
            'stock_status': 'removed',
        }

    def _shopify_product_handle(self, url: str) -> Optional[str]:
        match = re.search(r'/products/([^/?#]+)', url, re.IGNORECASE)
        return match.group(1).lower() if match else None

    def _url_indicates_product_removed(self, requested_url: str, final_url: str) -> bool:
        """True when a product URL redirects away from that product (common on Shopify)."""
        if not requested_url or not final_url:
            return False
        handle = self._shopify_product_handle(requested_url)
        if not handle:
            return False
        final_path = urlparse(final_url).path.lower().rstrip('/')
        if f'/products/{handle}' in final_path:
            return False
        if '/products/' not in requested_url.lower():
            return False
        final_handle = self._shopify_product_handle(final_url)
        if final_handle and final_handle != handle:
            return True
        if '/products/' not in final_path:
            return True
        return False

    def _page_indicates_product_removed(self, soup: BeautifulSoup) -> bool:
        for selector in self.REMOVED_PAGE_SELECTORS:
            if soup.select_one(selector):
                return True

        title = (soup.find('title').get_text(strip=True).lower() if soup.find('title') else '')
        if title and ('404' in title or 'not found' in title):
            return True

        for heading in soup.find_all(['h1', 'h2'], limit=3):
            text = heading.get_text(separator=' ', strip=True).lower()
            if not text:
                continue
            if '404' in text or 'not found' in text:
                return True
            if any(phrase in text for phrase in self.REMOVED_PAGE_PHRASES):
                return True

        body_snippet = soup.get_text(separator=' ', strip=True)[:4000].lower()
        return any(phrase in body_snippet for phrase in self.REMOVED_PAGE_PHRASES)

    def _canonical_url(self, soup: BeautifulSoup) -> Optional[str]:
        link = soup.find('link', rel=lambda value: value and 'canonical' in str(value).lower())
        if link and link.get('href'):
            return link['href']
        og_url = soup.find('meta', property='og:url')
        if og_url and og_url.get('content'):
            return og_url['content']
        return None

    def _apply_product_removal_heuristics(
        self,
        product_data: Dict,
        soup: BeautifulSoup,
        url: str,
        final_url: Optional[str] = None,
        is_shopify: bool = False,
        shopify_api: Optional[Dict] = None,
    ) -> None:
        """Mark listings that no longer exist on the storefront."""
        shopify_api = shopify_api or {}
        if shopify_api and not shopify_api.get('product_removed'):
            return

        if final_url and self._url_indicates_product_removed(url, final_url):
            product_data['product_removed'] = True
            product_data['is_product_page'] = False
            return

        canonical = self._canonical_url(soup)
        if canonical and self._url_indicates_product_removed(url, canonical):
            product_data['product_removed'] = True
            product_data['is_product_page'] = False
            return

        if self._page_indicates_product_removed(soup):
            product_data['product_removed'] = True
            product_data['is_product_page'] = False
            return

        if '/products/' in url.lower() and is_shopify:
            has_shopify_data = bool(shopify_api) and not shopify_api.get('product_removed')
            has_product_schema = bool(product_data.get('is_product_page'))
            if not has_shopify_data and not has_product_schema:
                product_data['product_removed'] = True
                product_data['is_product_page'] = False
                return

            if not has_shopify_data and self._page_indicates_product_removed(soup):
                product_data['product_removed'] = True
                product_data['is_product_page'] = False

    def _apply_stock_status(self, product_data: Dict, soup: BeautifulSoup) -> None:
        """Set stock_status from availability, quantity, and page text."""
        threshold = self.config.LOW_STOCK_THRESHOLD

        if product_data.get('product_removed'):
            product_data['in_stock'] = False
            product_data['stock_status'] = 'removed'
            return

        if not product_data.get('in_stock'):
            product_data['stock_status'] = 'out_of_stock'
            return

        quantity = product_data.get('quantity')
        if quantity is not None and quantity > 0 and quantity <= threshold:
            product_data['stock_status'] = 'low_stock'
            return

        if self._detect_low_stock_from_inventory_elements(soup):
            product_data['stock_status'] = 'low_stock'
            return

        product_root = self._find_product_section(soup)
        search_areas = [product_root] if product_root else [soup]

        for area in search_areas:
            text = area.get_text(separator=' ', strip=True).lower()
            for pattern in self.LOW_STOCK_PATTERNS:
                if re.search(pattern, text):
                    product_data['stock_status'] = 'low_stock'
                    return

        product_data['stock_status'] = 'in_stock'

    def _detect_low_stock_from_inventory_elements(self, soup: BeautifulSoup) -> bool:
        """Detect low stock from dedicated inventory badges (common on Shopify)."""
        threshold = self.config.LOW_STOCK_THRESHOLD

        for selector in self.INVENTORY_SELECTORS:
            for element in soup.select(selector):
                for attr in ('data-product-stock', 'data-inventory-quantity'):
                    value = element.get(attr)
                    if value is not None and str(value).strip().isdigit():
                        if int(value) <= threshold:
                            return True

                text = element.get_text(separator=' ', strip=True).lower()
                if not text:
                    continue
                for pattern in self.LOW_STOCK_PATTERNS:
                    if re.search(pattern, text):
                        return True

        return False

    def _is_amazon_url(self, url: str) -> bool:
        return 'amazon.' in url.lower()

    def _extract_amazon_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract price, currency, and stock from Amazon product pages."""
        result: Dict[str, Any] = {}

        price_roots = [
            soup.select_one('#corePriceDisplay_desktop_feature_div'),
            soup.select_one('#corePrice_feature_div'),
            soup.select_one('#buybox'),
            soup.select_one('#ppd'),
        ]

        for root in price_roots:
            if not root:
                continue

            for selector in self.AMAZON_PRICE_SELECTORS:
                element = root.select_one(selector)
                if not element:
                    continue
                price, currency = self._parse_split_price_element(element)
                if price > 0:
                    result['price'] = price
                    if currency:
                        result['currency'] = currency
                    break

            if result.get('price'):
                break

            for element in root.select('.a-price:not(.a-text-price)'):
                class_names = ' '.join(element.get('class', []))
                if 'basisprice' in class_names or 'a-text-price' in class_names:
                    continue
                price, currency = self._parse_split_price_element(element)
                if price > 0:
                    result['price'] = price
                    if currency:
                        result['currency'] = currency
                    break

            if result.get('price'):
                break

        availability = soup.select_one('#buybox #availability') or soup.select_one('#availability')
        if availability:
            availability_text = availability.get_text(strip=True).lower()
            if any(kw in availability_text for kw in ('out of stock', 'unavailable', 'currently unavailable')):
                result['in_stock'] = False
            elif 'in stock' in availability_text:
                result['in_stock'] = True

        if result.get('in_stock') is None and soup.select_one('#outOfStock'):
            result['in_stock'] = False

        if result.get('in_stock') is None:
            add_to_cart = soup.select_one('#add-to-cart-button, #submit.add-to-cart, #buy-now-button')
            if add_to_cart and not add_to_cart.has_attr('disabled'):
                result['in_stock'] = True

        return result

    def _parse_split_price_element(self, price_el) -> Tuple[float, Optional[str]]:
        """Parse prices split across whole/fraction spans (common on Amazon)."""
        if not price_el:
            return 0.0, None

        offscreen = price_el.select_one('.a-offscreen')
        if offscreen:
            text = offscreen.get_text(strip=True)
            if text:
                return self.parse_price(text), self._extract_currency_from_text(text)

        symbol_el = price_el.select_one('.a-price-symbol')
        currency = self._normalize_currency(symbol_el.get_text(strip=True)) if symbol_el else None

        whole_el = price_el.select_one('.a-price-whole')
        fraction_el = price_el.select_one('.a-price-fraction')
        if whole_el:
            fraction_text = fraction_el.get_text(strip=True) if fraction_el else None
            price = self._combine_price_parts(whole_el.get_text(), fraction_text)
            if price > 0:
                return price, currency

        text = price_el.get_text(strip=True)
        parsed = self.parse_price(text)
        if parsed > 0:
            return parsed, currency or self._extract_currency_from_text(text)

        return 0.0, currency

    def _combine_price_parts(self, whole_text: str, fraction_text: Optional[str] = None) -> float:
        whole_clean = re.sub(r'[^\d]', '', whole_text or '')
        if not whole_clean:
            return 0.0

        fraction_clean = re.sub(r'[^\d]', '', fraction_text or '') if fraction_text else ''
        if not fraction_clean:
            return float(whole_clean)

        try:
            return float(f"{whole_clean}.{fraction_clean}")
        except ValueError:
            return 0.0

    def _extract_currency_from_text(self, text: str) -> Optional[str]:
        if not text:
            return None

        for symbol in sorted(self.CURRENCY_SYMBOLS, key=len, reverse=True):
            if text.strip().startswith(symbol):
                return self.CURRENCY_SYMBOLS[symbol]

        match = re.match(r'^([A-Z]{3})', text.strip())
        if match:
            return match.group(1)

        return None

    def _normalize_currency(self, value: str) -> str:
        return 'USD'

    def _is_shopify_product_url(self, url: str, soup: BeautifulSoup) -> bool:
        if '/products/' not in url.lower():
            return False
        page_text = str(soup)[:50000].lower()
        return any(indicator in page_text for indicator in self.SHOPIFY_INDICATORS)

    def _active_shopify_currency(self, soup: BeautifulSoup) -> Optional[str]:
        page_text = str(soup)[:80000]
        match = re.search(
            r'Shopify\.currency\s*=\s*\{[^}]*"active"\s*:\s*"([A-Z]{3})"',
            page_text,
        )
        return match.group(1) if match else None

    def _merge_product_sources(self, primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(primary)
        for key, value in secondary.items():
            if value is None:
                continue
            if key == 'price' and merged.get('price'):
                continue
            if key == 'in_stock' and merged.get('in_stock') is not None and merged.get('variant_matched'):
                continue
            if key == 'quantity' and merged.get('quantity') is not None:
                continue
            merged[key] = value
        return merged

    def _normalize_url_for_match(self, url: str) -> str:
        parsed = urlparse(url.lower().strip())
        path = parsed.path.rstrip('/')
        params = parse_qs(parsed.query, keep_blank_values=True)
        normalized_params = []
        for key in sorted(params):
            values = sorted(unquote_plus(v).lower().strip() for v in params[key])
            normalized_params.append(f"{key.lower()}={'/'.join(values)}")
        query = '&'.join(normalized_params)
        return f"{parsed.netloc}{path}?{query}" if query else f"{parsed.netloc}{path}"

    def _get_url_variant_hints(self, url: str) -> Dict[str, Any]:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        hints: Dict[str, Any] = {
            'normalized_url': self._normalize_url_for_match(url),
            'path': parsed.path.rstrip('/').lower(),
        }
        if 'variant' in params and params['variant']:
            hints['variant_id'] = str(params['variant'][0]).strip()
        for key in ('colour', 'color', 'option1', 'option2', 'option3', 'size'):
            if key in params and params[key]:
                hints['option'] = unquote_plus(params[key][0]).lower().strip()
                break
        return hints

    def _variant_matches_url(self, url: str, variant: Dict[str, Any]) -> bool:
        hints = self._get_url_variant_hints(url)
        if hints.get('variant_id'):
            variant_id = str(variant.get('id', '')).strip()
            if variant_id and variant_id == hints['variant_id']:
                return True

        candidate_urls = [
            variant.get('url', ''),
            variant.get('@id', ''),
        ]
        normalized_page = hints['normalized_url']
        for candidate in candidate_urls:
            if candidate and self._normalize_url_for_match(str(candidate)) == normalized_page:
                return True

        option_hint = hints.get('option')
        if option_hint:
            color_fields = [
                str(variant.get('color', '')).lower(),
                str(variant.get('name', '')).lower(),
                str(variant.get('title', '')).lower(),
                str(variant.get('public_title', '')).lower(),
            ]
            option_values = variant.get('options') or []
            if isinstance(option_values, list):
                color_fields.extend(str(v).lower() for v in option_values)
            for field in color_fields:
                if field and (option_hint in field or field in option_hint):
                    return True

        return False

    def _select_variant_for_url(self, url: str, variants: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        valid_variants = [v for v in variants if isinstance(v, dict)]
        if not valid_variants:
            return None

        hints = self._get_url_variant_hints(url)
        has_hint = bool(hints.get('variant_id') or hints.get('option'))

        for variant in valid_variants:
            if self._variant_matches_url(url, variant):
                return variant

        if has_hint:
            return None

        for variant in valid_variants:
            if variant.get('available') is True:
                return variant

        return valid_variants[0]

    def _shopify_price_to_float(self, price: Any) -> float:
        try:
            value = float(str(price).replace(',', ''))
        except (TypeError, ValueError):
            return 0.0
        if value <= 0:
            return 0.0
        if value >= 1000 and float(value).is_integer():
            return value / 100.0
        return value

    def _extract_variant_details(self, variant: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        offers = variant.get('offers')
        if isinstance(offers, dict):
            price, currency = self._extract_price_from_offers(offers)
            stock = self._extract_stock_from_offers(offers)
        else:
            price = self._shopify_price_to_float(variant.get('price'))
            currency = variant.get('priceCurrency') or variant.get('currency')
            stock = variant.get('available')
            if isinstance(stock, bool):
                stock = stock
            else:
                stock = None

        if price and price > 0:
            result['price'] = price
        if currency:
            result['currency'] = self._normalize_currency(str(currency))
        if stock is not None:
            result['in_stock'] = bool(stock)

        if 'inventory_quantity' in variant:
            qty = variant.get('inventory_quantity')
            if isinstance(qty, int):
                result['quantity'] = max(qty, 0)
        elif variant.get('inventory_management') == 'shopify' and variant.get('available') is False:
            result['quantity'] = 0

        if variant.get('name'):
            result['title'] = self._clean_text(str(variant['name']))
        elif variant.get('title'):
            result['title'] = self._clean_text(str(variant['title']))

        return result

    def _fetch_shopify_product_json(self, url: str) -> Dict[str, Any]:
        """Fetch canonical product data from Shopify's public product JSON endpoint."""
        parsed = urlparse(url)
        match = re.search(r'/products/([^/?#]+)', parsed.path, re.IGNORECASE)
        if not match:
            return {}

        json_url = f"{parsed.scheme}://{parsed.netloc}/products/{match.group(1)}.js"
        response = self.fetch_url(json_url, max_retries=2)
        if response is None:
            return {}

        content_type = (response.headers.get('Content-Type') or '').lower()
        is_json_payload = (
            'json' in content_type
            or 'javascript' in content_type
            or response.text.strip().startswith('{')
        )

        if response.status_code in (404, 410):
            if is_json_payload or not response.text.strip():
                return {'product_removed': True, 'is_product_page': False}
            return {}

        if self._url_indicates_product_removed(url, response.url):
            return {'product_removed': True, 'is_product_page': False}

        if not is_json_payload:
            return {}

        try:
            product = response.json()
        except (json.JSONDecodeError, ValueError):
            return {}

        if not isinstance(product, dict):
            return {}

        if not product.get('variants'):
            if product.get('id') is None and not product.get('title'):
                return {'product_removed': True, 'is_product_page': False}
            return {}

        variants = [v for v in product.get('variants', []) if isinstance(v, dict)]
        selected = self._select_variant_for_url(url, variants)
        if not selected:
            return {}

        result = self._extract_variant_details(selected)
        result['variant_matched'] = self._variant_matches_url(url, selected)
        result['is_product_page'] = True

        if not result.get('title') and product.get('title'):
            result['title'] = self._clean_text(product['title'])

        if result.get('in_stock') is None and isinstance(product.get('available'), bool):
            result['in_stock'] = product['available']

        return result

    def _extract_structured_data(self, soup: BeautifulSoup, url: str = '') -> Dict[str, Any]:
        """Extract price, stock, title, and currency from JSON-LD and meta tags."""
        result: Dict[str, Any] = {}
        found_product_schema = False
        url_hints = self._get_url_variant_hints(url) if url else {}

        for item in self._iter_json_ld_items(soup):
            item_type = item.get('@type', '')
            types = item_type if isinstance(item_type, list) else [item_type]

            if any(t in ('Product', 'ProductGroup') for t in types):
                found_product_schema = True
                if not result.get('title') and item.get('name'):
                    result['title'] = self._clean_text(item['name'])

                variants = item.get('hasVariant', []) or []
                matched_variant = None
                if url and variants:
                    matched_variant = self._select_variant_for_url(url, variants)

                if matched_variant:
                    variant_data = self._extract_variant_details(matched_variant)
                    result.update({k: v for k, v in variant_data.items() if v is not None})
                    result['variant_matched'] = self._variant_matches_url(url, matched_variant)
                else:
                    price, currency = self._extract_price_from_offers(item.get('offers'))
                    if price and not result.get('price'):
                        result['price'] = price
                        if currency:
                            result['currency'] = currency

                    stock = self._extract_stock_from_offers(item.get('offers'))
                    if stock is not None and result.get('in_stock') is None:
                        result['in_stock'] = stock

                    if variants and not result.get('price'):
                        for variant in variants:
                            if not isinstance(variant, dict):
                                continue
                            v_price, v_currency = self._extract_price_from_offers(variant.get('offers'))
                            if v_price and not result.get('price'):
                                result['price'] = v_price
                                if v_currency:
                                    result['currency'] = v_currency
                            v_stock = self._extract_stock_from_offers(variant.get('offers'))
                            if v_stock is not None and result.get('in_stock') is None:
                                result['in_stock'] = v_stock

        if url and '/products/' in url.lower():
            result['is_product_page'] = found_product_schema
        elif url:
            result['is_product_page'] = found_product_schema
        else:
            result['is_product_page'] = found_product_schema

        meta_currency = soup.find('meta', property='product:price:currency')
        meta_currency_code = (meta_currency.get('content') or '').upper() if meta_currency else ''
        if meta_currency_code:
            result['currency'] = self._normalize_currency(meta_currency_code)

        meta_price = soup.find('meta', property='product:price:amount')
        if meta_price and meta_price.get('content') and meta_currency_code in ('', 'USD'):
            try:
                price = float(str(meta_price['content']).replace(',', ''))
                if price > 0:
                    result['price'] = price
                    result['currency'] = 'USD'
            except ValueError:
                pass

        og_price = soup.find('meta', property='og:price:amount')
        og_currency_el = soup.find('meta', property='og:price:currency')
        og_currency = (og_currency_el.get('content') or '').upper() if og_currency_el else ''
        if og_price and og_price.get('content') and og_currency in ('', 'USD') and not result.get('price'):
            try:
                price = float(str(og_price['content']).replace(',', ''))
                if price > 0:
                    result['price'] = price
                    result['currency'] = 'USD'
            except ValueError:
                pass

        og_availability = soup.find('meta', property='og:availability') or soup.find(
            'meta', attrs={'name': 'availability'}
        )
        if og_availability and og_availability.get('content') and result.get('in_stock') is None:
            result['in_stock'] = self._parse_availability(og_availability['content'])

        shopify = self._extract_shopify_data(soup, url)
        shopify_currency = str(shopify.get('currency') or '').upper()
        if shopify_currency and shopify_currency != 'USD':
            shopify.pop('price', None)
        if shopify.get('price') and not result.get('price'):
            result['price'] = shopify['price']
        if shopify.get('currency') and not result.get('currency'):
            result['currency'] = shopify['currency']
        if shopify.get('in_stock') is not None and result.get('in_stock') is None:
            result['in_stock'] = shopify['in_stock']
        if shopify.get('quantity') is not None and result.get('quantity') is None:
            result['quantity'] = shopify['quantity']
        if shopify.get('title') and not result.get('title'):
            result['title'] = shopify['title']

        return result

    def _extract_shopify_data(self, soup: BeautifulSoup, url: str = '') -> Dict[str, Any]:
        """Extract product data from Shopify inline scripts."""
        result: Dict[str, Any] = {}

        for script in soup.find_all('script'):
            text = script.string or script.get_text() or ''
            if not text:
                continue

            currency_match = re.search(
                r'Shopify\.currency\s*=\s*\{[^}]*"active"\s*:\s*"([A-Z]{3})"',
                text
            )
            if currency_match and not result.get('currency'):
                result['currency'] = currency_match.group(1)

            for pattern in (
                r'productData\s*:\s*(\{[\s\S]*?\})\s*,\s*(?:productCollections|initialSelectedVariant)',
                r'const\s+product\s*=\s*(\{[\s\S]*?\});',
                r'targetProduct\s*:\s*JSON\.parse\(JSON\.stringify\((\{[\s\S]*?\})\)\)',
            ):
                match = re.search(pattern, text)
                if not match:
                    continue
                try:
                    product = json.loads(match.group(1))
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue

                variants = product.get('variants') if isinstance(product, dict) else None
                if not isinstance(variants, list) or not variants:
                    continue

                selected = self._select_variant_for_url(url, variants) if url else variants[0]
                if not isinstance(selected, dict):
                    continue

                variant_data = self._extract_variant_details(selected)
                if variant_data.get('price') and not result.get('price'):
                    result['price'] = variant_data['price']
                if variant_data.get('currency') and not result.get('currency'):
                    result['currency'] = variant_data['currency']
                if variant_data.get('in_stock') is not None and result.get('in_stock') is None:
                    result['in_stock'] = variant_data['in_stock']
                if variant_data.get('quantity') is not None and result.get('quantity') is None:
                    result['quantity'] = variant_data['quantity']
                if variant_data.get('title') and not result.get('title'):
                    result['title'] = variant_data['title']

            variants_match = re.search(
                r'"variants"\s*:\s*(\[[\s\S]*?\])\s*,\s*"remote"',
                text
            )
            if variants_match and not result.get('price'):
                try:
                    variants = json.loads(variants_match.group(1))
                    selected = self._select_variant_for_url(url, variants) if url else None
                    if isinstance(selected, dict):
                        variant_data = self._extract_variant_details(selected)
                        result.update({k: v for k, v in variant_data.items() if v is not None})
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass

        return result

    _QUANTITY_PATTERNS = (
        r'only\s+(\d{1,4})\s+left',
        r'(\d{1,4})\s+left in stock',
        r'(?<![.,\d])(\d{1,4})\s+in stock',
        r'low stock[:\s-]*(\d{1,4})',
    )

    def _parse_quantity_from_text(self, text: str) -> Optional[int]:
        """Extract a stock count from text, ignoring price decimals like '36,100.00 in stock'."""
        if not text:
            return None
        normalized = text.lower()
        for pattern in self._QUANTITY_PATTERNS:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if not match:
                continue
            try:
                return int(match.group(1))
            except ValueError:
                continue
        return None

    def _detect_quantity_from_page(self, soup: BeautifulSoup) -> Optional[int]:
        """Detect remaining stock quantity from common storefront patterns."""
        product_root = self._find_product_section(soup)
        search_areas = [product_root] if product_root else [soup]

        for area in search_areas:
            quantity = self._parse_quantity_from_text(
                area.get_text(separator=' ', strip=True)
            )
            if quantity is not None:
                return quantity

        for element in soup.select(
            '.product__inventory, .product-inventory, #VariantInventory, '
            '[data-product-stock], [data-inventory-quantity]'
        ):
            data_qty = element.get('data-product-stock') or element.get('data-inventory-quantity')
            if data_qty and str(data_qty).strip().isdigit():
                return int(data_qty)
            quantity = self._parse_quantity_from_text(
                element.get_text(separator=' ', strip=True)
            )
            if quantity is not None:
                return quantity

        return None

    def _iter_json_ld_items(self, soup: BeautifulSoup) -> List[Dict]:
        """Yield all JSON-LD objects from the page."""
        items: List[Dict] = []

        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
            except (json.JSONDecodeError, TypeError):
                continue

            if isinstance(data, list):
                items.extend(d for d in data if isinstance(d, dict))
            elif isinstance(data, dict):
                if '@graph' in data and isinstance(data['@graph'], list):
                    items.extend(d for d in data['@graph'] if isinstance(d, dict))
                else:
                    items.append(data)

        return items

    def _parse_offer_amount(self, raw: Any) -> Optional[float]:
        if raw is None:
            return None
        try:
            parsed = float(str(raw).replace(',', ''))
        except ValueError:
            return None
        return parsed if parsed > 0 else None

    def _extract_price_from_offers(self, offers: Any) -> Tuple[Optional[float], Optional[str]]:
        """Extract the USD price from schema.org offers, ignoring EGP/local currencies."""
        if not offers:
            return None, None

        offer_list = offers if isinstance(offers, list) else [offers]
        usd_prices: List[float] = []
        unmarked_prices: List[float] = []

        for offer in offer_list:
            if not isinstance(offer, dict):
                continue

            currency = str(offer.get('priceCurrency') or '').upper() or None
            amount = self._parse_offer_amount(offer.get('price') or offer.get('lowPrice'))

            if isinstance(offer.get('priceSpecification'), dict):
                spec = offer['priceSpecification']
                spec_currency = str(spec.get('priceCurrency') or currency or '').upper() or None
                spec_amount = self._parse_offer_amount(spec.get('price'))
                if spec_amount:
                    amount = amount or spec_amount
                    currency = spec_currency or currency

            if amount and currency == 'USD':
                usd_prices.append(amount)
            elif amount and not currency:
                unmarked_prices.append(amount)

            if isinstance(offer.get('offers'), (dict, list)):
                nested_price, nested_currency = self._extract_price_from_offers(offer['offers'])
                if nested_price and (nested_currency or 'USD') == 'USD':
                    usd_prices.append(nested_price)

        if usd_prices:
            return min(usd_prices), 'USD'
        if unmarked_prices:
            return min(unmarked_prices), 'USD'
        return None, None

    def _extract_stock_from_offers(self, offers: Any) -> Optional[bool]:
        """Extract stock status from schema.org offers."""
        if not offers:
            return None

        offer_list = offers if isinstance(offers, list) else [offers]
        any_in_stock = False
        any_out_of_stock = False

        for offer in offer_list:
            if not isinstance(offer, dict):
                continue

            availability = offer.get('availability', '')
            if availability:
                stock = self._parse_availability(str(availability))
                if stock is True:
                    any_in_stock = True
                elif stock is False:
                    any_out_of_stock = True

            nested = offer.get('offers')
            if nested:
                nested_stock = self._extract_stock_from_offers(nested)
                if nested_stock is True:
                    any_in_stock = True
                elif nested_stock is False:
                    any_out_of_stock = True

        if any_in_stock:
            return True
        if any_out_of_stock:
            return False
        return None

    def _parse_availability(self, availability: str) -> Optional[bool]:
        """Parse schema.org or plain-text availability strings."""
        value = availability.lower()

        if any(kw in value for kw in ('instock', 'in stock', 'available', 'preorder', 'pre-order')):
            return True
        if any(kw in value for kw in ('outofstock', 'out of stock', 'soldout', 'sold out', 'discontinued')):
            return False
        return None

    def check_stock_with_selectors(self, soup: BeautifulSoup, selectors: list) -> bool:
        for selector in selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text().lower()
                if any(kw in text for kw in self.OUT_OF_STOCK_KEYWORDS):
                    return False
                if any(kw in text for kw in ('in stock', 'add to cart', 'buy now', 'available')):
                    return True
        return False

    def extract_price_with_selectors(self, soup: BeautifulSoup, selectors: list) -> float:
        for selector in selectors:
            for element in soup.select(selector):
                price = self._parse_price_from_element(element)
                if price > 0:
                    return price
        return 0.0

    def _is_non_usd_price_text(self, text: str) -> bool:
        if not text:
            return False
        if self.USD_CURRENCY_RE.search(text):
            return False
        return bool(self.NON_USD_CURRENCY_RE.search(text))

    def _parse_price_from_element(self, element) -> float:
        if element is None:
            return 0.0

        text = element.get_text(separator=' ', strip=True)
        if self._is_non_usd_price_text(text):
            return 0.0

        price_container = element if 'a-price' in element.get('class', []) else element.find_parent(class_='a-price')
        if price_container:
            price, _ = self._parse_split_price_element(price_container)
            if price > 0:
                return price

        return self.parse_price(text)

    def extract_title_with_selectors(self, soup: BeautifulSoup, selectors: list) -> str:
        for selector in selectors:
            if selector.startswith('meta'):
                element = soup.select_one(selector)
                if element and element.get('content'):
                    return self._clean_text(element['content'])
            else:
                elements = soup.select(selector)
                if elements:
                    return self._clean_text(elements[0].get_text())

        title_tag = soup.find('title')
        if title_tag:
            return self._clean_text(title_tag.get_text())
        return "Unknown Product"

    def auto_detect_stock(self, soup: BeautifulSoup) -> bool:
        """Detect stock status from product-specific page areas."""
        product_root = self._find_product_section(soup)
        search_areas = [product_root] if product_root else [soup]

        for area in search_areas:
            text = area.get_text(separator=' ', strip=True).lower()

            disabled_cart = area.select(
                'button[disabled], .product-form__submit[disabled], '
                '[name="add"][disabled], .btn--sold-out'
            )
            if disabled_cart:
                btn_text = ' '.join(el.get_text().lower() for el in disabled_cart)
                if any(kw in btn_text for kw in ('sold out', 'out of stock', 'unavailable')):
                    return False

            sold_out_el = area.select_one('.sold-out, .product-form--sold-out, .badge--sold-out')
            if sold_out_el:
                return False

            for pattern in (r'in\s+stock', r'add\s+to\s+cart', r'buy\s+now', r'only\s+\d+\s+left'):
                if re.search(pattern, text):
                    return True

            add_to_cart = area.find(
                ['button', 'a', 'input'],
                string=re.compile(r'add to cart|buy now|add to bag', re.I)
            )
            if add_to_cart and not add_to_cart.has_attr('disabled'):
                return True

            for pattern in (r'out\s+of\s+stock', r'sold\s+out', r'currently\s+unavailable',
                            r'temporarily\s+out\s+of\s+stock', r'not\s+available'):
                if re.search(pattern, text):
                    return False

        return False

    def auto_detect_price(self, soup: BeautifulSoup) -> float:
        """Detect product price from structured data, meta tags, and product area."""
        structured = self._extract_structured_data(soup)
        if structured.get('price'):
            return structured['price']

        product_root = self._find_product_section(soup)
        price_selectors = [
            '.price-item--sale', '.price__regular .price-item--regular',
            '.product__price .price-item', '.product__price',
            '[data-product-price]', '.price .money', '.price .amount',
            '.product-price', '.sale-price', '.current-price',
            'span.price', '.a-price .a-offscreen', '#priceblock_ourprice',
            '#priceblock_dealprice', '.apex-pricetopay-value', '.priceToPay',
        ]

        search_roots = [product_root, soup] if product_root else [soup]
        for root in search_roots:
            for selector in price_selectors:
                for element in root.select(selector):
                    if 'a-text-price' in ' '.join(element.get('class', [])):
                        continue
                    price = self._parse_price_from_element(element)
                    if price >= 0.01 and self._looks_like_product_price(element.get_text()):
                        return price

        product_text = product_root.get_text(separator=' ') if product_root else soup.get_text()
        if product_root:
            top_text = product_text[:5000]
            candidates = self._extract_prices_from_text(top_text)
            if candidates:
                return candidates[0]

        candidates = self._extract_prices_from_text(product_text)
        if candidates:
            return candidates[0]

        return 0.0

    def _looks_like_product_price(self, text: str) -> bool:
        if not text:
            return False
        if self._is_non_usd_price_text(text):
            return False

        if self.USD_CURRENCY_RE.search(text):
            return True

        return self.parse_price(text) >= 1

    def _extract_prices_from_text(self, text: str) -> List[float]:
        """Extract USD product prices only (ignore EGP / LE / other currencies)."""
        if not text:
            return []

        candidates: List[float] = []
        seen = set()

        for match in re.finditer(
            r'\$\s*(\d+(?:,\d{3})*)\s*\.\s*(\d{1,2})',
            text,
            re.IGNORECASE
        ):
            price = self._combine_price_parts(match.group(1), match.group(2))
            if 0.01 <= price < 1_000_000 and price not in seen:
                candidates.append(price)
                seen.add(price)

        patterns = [
            r'US\$\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)',
            r'\$\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)',
            r'(?:USD)\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)',
            r'(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:USD)\b',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                price = self.parse_price(match.group(1))
                if 0.01 <= price < 1_000_000 and price not in seen:
                    candidates.append(price)
                    seen.add(price)

        return candidates

    def _looks_like_product_section(self, element) -> bool:
        """Return True when an element looks like the main buy box, not a widget."""
        if not element:
            return False

        buy_box_selectors = (
            '.product-form', '.product__inventory', '.product__info',
            '#add-to-cart-button', '[name="add"]', '.add-to-cart',
            '#buybox', '#availability',
        )
        for selector in buy_box_selectors:
            if element.select_one(selector):
                return True

        text = element.get_text(separator=' ', strip=True).lower()
        return bool(re.search(
            r'add to cart|buy now|sold out|in stock|low stock|out of stock',
            text
        ))

    def _find_product_section(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """Locate the main product section to avoid unrelated prices/stock text."""
        selectors = [
            '#ppd', '#centerCol', '#dp-container', '#buybox',
            '.product__info', '.product__info-wrapper',
            'div.product', 'product-info', 'product-form',
            '.product-single', '.product-detail', '.product-page',
            '#product', '.product-form', 'main .product',
            '[data-product-id]',
        ]
        for selector in selectors:
            element = soup.select_one(selector)
            if element and self._looks_like_product_section(element):
                return element
        return soup.find('main') or soup.find('article')

    def _clean_text(self, text: str) -> str:
        if not text:
            return ''
        return re.sub(r'\s+', ' ', text).strip()

    def parse_price(self, price_text: str) -> float:
        if not price_text:
            return 0.0

        price_text = price_text.strip()
        cleaned = re.sub(r'[^\d.,]', '', price_text)
        if not cleaned:
            return 0.0

        if ',' in cleaned and '.' in cleaned:
            if cleaned.rfind(',') > cleaned.rfind('.'):
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            parts = cleaned.split(',')
            if len(parts) == 2 and len(parts[1]) <= 2:
                cleaned = f"{parts[0]}.{parts[1]}"
            else:
                cleaned = cleaned.replace(',', '')
        elif cleaned.count('.') > 1:
            whole, fraction = cleaned.rsplit('.', 1)
            if len(fraction) <= 2:
                cleaned = whole.replace('.', '') + '.' + fraction

        cleaned = cleaned.rstrip('.')

        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def get_current_timestamp(self) -> str:
        from datetime import datetime
        return datetime.now().isoformat()
