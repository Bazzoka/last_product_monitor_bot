"""
Flask dashboard application
"""

from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from functools import wraps
from bot.config import Config
from bot.storage import get_storage
from bot.utils.logger import Logger
from bot.utils.validators import Validators
from bot.dashboard.routes import DashboardRoutes

DASHBOARD_DIR = Path(__file__).parent


class DashboardApp:
    """Dashboard web application"""
    
    def __init__(self, bot_instance=None):
        """Initialize dashboard"""
        self.config = Config()
        self.storage = get_storage()
        self.logger = Logger()
        self.bot = bot_instance
        self.validators = Validators()
        
        self.app = Flask(
            __name__,
            template_folder=str(DASHBOARD_DIR / 'templates'),
            static_folder=str(DASHBOARD_DIR / 'static')
        )
        self.app.secret_key = self.config.DASHBOARD_SECRET_KEY
        
        # Setup routes
        self.setup_routes()
        
        # Initialize routes handler
        self.routes = DashboardRoutes(self.bot, self.storage, self.logger)
    
    def setup_routes(self):
        """Setup all dashboard routes"""
        
        def login_required(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if not session.get('logged_in'):
                    return redirect(url_for('login'))
                return f(*args, **kwargs)
            return decorated_function
        
        @self.app.route('/')
        @login_required
        def index():
            return self.routes.dashboard()
        
        @self.app.route('/login', methods=['GET', 'POST'])
        def login():
            if request.method == 'POST':
                username = self.validators.sanitize_input(request.form.get('username', ''))
                password = request.form.get('password', '')
                
                if self.storage.verify_admin(username, password):
                    session['logged_in'] = True
                    session['username'] = username
                    return redirect(url_for('index'))
                else:
                    return render_template('login.html', error='Invalid credentials')
            
            return render_template('login.html')
        
        @self.app.route('/logout')
        def logout():
            session.clear()
            return redirect(url_for('login'))
        
        @self.app.route('/products')
        @login_required
        def products():
            return self.routes.products()
        
        @self.app.route('/logs')
        @login_required
        def logs():
            return self.routes.logs()
        
        @self.app.route('/settings')
        @login_required
        def settings():
            return self.routes.settings()
        
        # API endpoints
        @self.app.route('/api/products', methods=['GET', 'POST', 'DELETE'])
        @login_required
        def api_products():
            if request.method == 'GET':
                return self.routes.get_products()
            elif request.method == 'POST':
                return self.routes.add_product(request)
            elif request.method == 'DELETE':
                return self.routes.delete_product(request)
        
        @self.app.route('/api/products/<product_id>/toggle', methods=['POST'])
        @login_required
        def api_toggle_product(product_id):
            return self.routes.toggle_product(product_id)
        
        @self.app.route('/api/statistics')
        @login_required
        def api_statistics():
            return self.routes.get_statistics()
        
        @self.app.route('/api/notifications')
        @login_required
        def api_notifications():
            return self.routes.get_notifications()
        
        @self.app.route('/api/logs')
        @login_required
        def api_logs():
            return self.routes.get_logs()
        
        @self.app.route('/api/settings', methods=['GET', 'POST'])
        @login_required
        def api_settings():
            if request.method == 'GET':
                return self.routes.get_settings()
            else:
                return self.routes.update_settings(request)
        
        @self.app.route('/api/check-now', methods=['POST'])
        @login_required
        def api_check_now():
            return self.routes.trigger_check(self.bot)

        @self.app.route('/api/test-notifications', methods=['POST'])
        @login_required
        def api_test_notifications():
            return self.routes.test_notifications()
    
    def run(self):
        """Run the dashboard server"""
        host = self.config.DASHBOARD_HOST
        port = self.config.DASHBOARD_PORT
        
        self.logger.info(
            f"Dashboard listening at http://{host}:{port}",
            component='dashboard'
        )
        
        try:
            self.app.run(
                host=host,
                port=port,
                debug=False,
                threaded=True,
                use_reloader=False
            )
        except OSError as e:
            self.logger.error(
                f"Failed to start dashboard on port {port}: {e}. "
                f"Port {port} may be blocked on Windows — set DASHBOARD_PORT=8080 in .env",
                component='dashboard'
            )
        except Exception as e:
            self.logger.error(f"Failed to start dashboard: {e}", component='dashboard')
