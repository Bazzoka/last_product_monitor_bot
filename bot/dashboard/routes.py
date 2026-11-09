"""
Dashboard route handlers
"""

from flask import jsonify, render_template, request
from bot.config import Config
from bot.utils.validators import Validators


class DashboardRoutes:
    """Handles dashboard route logic"""
    
    def __init__(self, bot, storage, logger):
        """Initialize routes handler"""
        self.bot = bot
        self.storage = storage
        self.logger = logger
        self.validators = Validators()
    
    def dashboard(self):
        """Render dashboard page"""
        return render_template('dashboard.html')
    
    def products(self):
        """Render products management page"""
        return render_template('products.html')
    
    def logs(self):
        """Render logs page"""
        return render_template('logs.html')
    
    def settings(self):
        """Render settings page"""
        return render_template('settings.html')
    
    def get_products(self):
        """API: Get all products"""
        try:
            products = self.storage.get_all_products()
            return jsonify({'success': True, 'products': products})
        except Exception as e:
            self.logger.error(f"Error getting products: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def add_product(self, request):
        """API: Add new product"""
        try:
            data = request.get_json()
            
            # Validate URL
            if not self.validators.validate_url(data.get('url')):
                return jsonify({'success': False, 'error': 'Invalid URL'}), 400
            
            # Validate product name
            if not self.validators.validate_product_name(data.get('name')):
                return jsonify({'success': False, 'error': 'Invalid product name'}), 400
            
            # Add product
            product = self.storage.add_product(
                name=self.validators.sanitize_input(data.get('name')),
                url=data.get('url').strip(),
                selectors=data.get('selectors', {})
            )

            # Scrape immediately so the dashboard shows correct price/stock
            if self.bot and self.bot.product_scraper:
                try:
                    scraped = self.bot.product_scraper.scrape_product(product['url'], product)
                    if scraped:
                        self.storage.update_product_status(product['id'], scraped)
                        product = self.storage.get_product(product['id']) or product
                except Exception as scrape_error:
                    self.logger.warning(f"Initial scrape failed for {product.get('name')}: {scrape_error}")
            
            self.logger.info(f"Product added: {product.get('name')}")
            return jsonify({'success': True, 'product': product})
            
        except Exception as e:
            self.logger.error(f"Error adding product: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def delete_product(self, request):
        """API: Delete product"""
        try:
            data = request.get_json()
            product_id = data.get('product_id')
            
            if self.storage.delete_product(product_id):
                self.logger.info(f"Product deleted: {product_id}")
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'error': 'Product not found'}), 404
                
        except Exception as e:
            self.logger.error(f"Error deleting product: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def toggle_product(self, product_id):
        """API: Enable/disable product monitoring"""
        try:
            product = self.storage.get_product(product_id)
            if not product:
                return jsonify({'success': False, 'error': 'Product not found'}), 404
            
            new_status = not product.get('monitoring_enabled', True)
            self.storage.update_product(product_id, {'monitoring_enabled': new_status})
            
            self.logger.info(f"Product {product_id} monitoring toggled to {new_status}")
            return jsonify({'success': True, 'enabled': new_status})
            
        except Exception as e:
            self.logger.error(f"Error toggling product: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def get_statistics(self):
        """API: Get dashboard statistics"""
        try:
            stats = self.storage.get_statistics()
            
            # Add bot status
            stats['bot_running'] = self.bot.running if self.bot else False
            stats['last_check_time'] = (
                self.bot.last_check_time if self.bot and self.bot.last_check_time
                else self.storage.get_settings().get('last_scan_time')
            )
            
            return jsonify({'success': True, 'statistics': stats})
            
        except Exception as e:
            self.logger.error(f"Error getting statistics: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def get_notifications(self):
        """API: Get recent notifications"""
        try:
            limit = request.args.get('limit', 50, type=int)
            notifications = self.storage.get_recent_notifications(limit)
            return jsonify({'success': True, 'notifications': notifications})
            
        except Exception as e:
            self.logger.error(f"Error getting notifications: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def get_logs(self):
        """API: Get system logs"""
        try:
            limit = request.args.get('limit', 100, type=int)
            level = request.args.get('level')
            logs = self.storage.get_logs(limit, level)
            return jsonify({'success': True, 'logs': logs})
            
        except Exception as e:
            self.logger.error(f"Error getting logs: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def get_settings(self):
        """API: Get current settings"""
        try:
            config = Config()
            settings = self.storage.get_settings()
            settings['email_configured'] = config.is_email_configured()
            settings['telegram_configured'] = config.is_telegram_configured()
            return jsonify({'success': True, 'settings': settings})
            
        except Exception as e:
            self.logger.error(f"Error getting settings: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def update_settings(self, request):
        """API: Update settings"""
        try:
            data = request.get_json()
            self.storage.update_settings(data)
            return jsonify({'success': True})
            
        except Exception as e:
            self.logger.error(f"Error updating settings: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def trigger_check(self, bot):
        """API: Manually trigger product check"""
        try:
            if bot:
                bot.check_all_products()
                return jsonify({'success': True, 'message': 'Check triggered successfully'})
            else:
                return jsonify({'success': False, 'error': 'Bot not available'}), 500
                
        except Exception as e:
            self.logger.error(f"Error triggering check: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    def test_notifications(self):
        """API: Send test messages on email and Telegram"""
        try:
            if not self.bot:
                return jsonify({'success': False, 'error': 'Bot not available'}), 500
            results = self.bot.notification_manager.test_notifications()
            return jsonify({'success': True, 'results': results})
        except Exception as e:
            self.logger.error(f"Error testing notifications: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
