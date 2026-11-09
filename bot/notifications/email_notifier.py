"""
Email notification service
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional
from bot.config import Config
from bot.utils.logger import Logger


class EmailNotifier:
    """Handles email notifications"""
    
    def __init__(self):
        """Initialize email notifier"""
        self.config = Config()
        self.logger = Logger()
    
    def _connect(self):
        """Create authenticated SMTP connection"""
        host = self.config.EMAIL_HOST
        port = self.config.EMAIL_PORT
        use_ssl = self.config.EMAIL_USE_SSL or port == 465

        if use_ssl:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(host, port, context=context, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.ehlo()
            if self.config.EMAIL_USE_TLS:
                context = ssl.create_default_context()
                server.starttls(context=context)
                server.ehlo()

        server.login(self.config.EMAIL_USERNAME, self.config.EMAIL_PASSWORD)
        return server

    def send_raw_email(self, subject: str, html_body: str, to_address: Optional[str] = None) -> bool:
        """Send a raw HTML email"""
        if not self.config.is_email_configured():
            self.logger.warning("Email not configured, skipping notification", component='notifications')
            return False

        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.config.EMAIL_FROM
            msg['To'] = to_address or self.config.EMAIL_TO
            msg.attach(MIMEText(html_body, 'html'))

            with self._connect() as server:
                server.send_message(msg)

            return True
        except smtplib.SMTPAuthenticationError:
            self.logger.error(
                'Gmail rejected login. Use an App Password (not your normal password). '
                'Create one at https://myaccount.google.com/apppasswords',
                component='notifications'
            )
            return False
        except Exception as e:
            self.logger.error(f"Failed to send email: {e}", component='notifications')
            return False

    def test_connection(self) -> bool:
        """Verify SMTP credentials work"""
        if not self.config.is_email_configured():
            return False
        try:
            with self._connect():
                pass
            return True
        except smtplib.SMTPAuthenticationError:
            self.logger.error(
                'Email test failed: invalid username or app password',
                component='notifications'
            )
            return False
        except Exception as e:
            self.logger.error(f"Email test failed: {e}", component='notifications')
            return False
    
    def send_notification(self, product: Dict, status_data: Dict, changes: Dict) -> bool:
        """Send email notification about product changes"""
        subject = self.create_subject(product, changes)
        body = self.create_email_body(product, status_data, changes)
        if self.send_raw_email(subject, body):
            self.logger.info(f"Email notification sent for {product.get('name')}", component='notifications')
            return True
        return False

    def send_hourly_summary(self, products: List[Dict], changes_list: List[Dict]) -> bool:
        """Send hourly monitoring summary"""
        subject = "📊 Hourly Product Monitor Report"
        if changes_list:
            subject = f"📊 Hourly Report — {len(changes_list)} change(s) detected"

        rows = ""
        for product in products:
            status = product.get('stock_status') or (
                'in_stock' if product.get('in_stock') else 'out_of_stock'
            )
            status_label = {
                'in_stock': '✅ In Stock',
                'low_stock': '⚠️ Low Stock',
                'out_of_stock': '❌ Out of Stock',
                'unknown': '❓ Unknown'
            }.get(status, status)
            price = product.get('current_price', 0) or 0
            currency = product.get('currency', 'USD')
            qty = product.get('quantity')
            qty_text = qty if qty is not None else 'N/A'
            rows += f"""
            <tr>
                <td style="padding:8px;border-bottom:1px solid #eee;">{product.get('name', 'Unknown')}</td>
                <td style="padding:8px;border-bottom:1px solid #eee;">{status_label}</td>
                <td style="padding:8px;border-bottom:1px solid #eee;">{currency} {float(price):.2f}</td>
                <td style="padding:8px;border-bottom:1px solid #eee;">{qty_text}</td>
            </tr>
            """

        changes_html = ""
        if changes_list:
            changes_html = "<h3>Changes This Hour</h3><ul>"
            for item in changes_list:
                changes_html += f"<li><b>{item['name']}</b>: {item['summary']}</li>"
            changes_html += "</ul>"
        else:
            changes_html = "<p><b>No changes detected this hour.</b> All products checked successfully.</p>"

        html = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family:Arial,sans-serif;">
            <div style="max-width:700px;margin:0 auto;padding:20px;">
                <h2>Product Monitor — Hourly Report</h2>
                {changes_html}
                <h3>Current Status ({len(products)} products)</h3>
                <table style="width:100%;border-collapse:collapse;">
                    <tr style="background:#f0f0f0;">
                        <th style="padding:8px;text-align:left;">Product</th>
                        <th style="padding:8px;text-align:left;">Stock</th>
                        <th style="padding:8px;text-align:left;">Price</th>
                        <th style="padding:8px;text-align:left;">Qty</th>
                    </tr>
                    {rows}
                </table>
                <p style="color:#666;font-size:12px;margin-top:20px;">
                    Automated hourly report from Product Availability Monitor Bot.
                </p>
            </div>
        </body>
        </html>
        """
        if self.send_raw_email(subject, html):
            self.logger.info(
                f"Email hourly summary sent ({len(products)} products)",
                component='notifications'
            )
            return True
        return False
    
    def create_subject(self, product: Dict, changes: Dict) -> str:
        """Create email subject line"""
        product_name = product.get('name', 'Product')
        
        if 'stock_status' in changes:
            status = changes['stock_status']['to']
            if status == 'low_stock':
                return f"⚠️ LOW STOCK: {product_name}"
            if status == 'in_stock':
                return f"✅ IN STOCK: {product_name}"
            if status == 'out_of_stock':
                return f"❌ OUT OF STOCK: {product_name}"
        elif 'stock' in changes:
            if changes['stock']['to']:
                return f"✅ IN STOCK: {product_name}"
            else:
                return f"❌ OUT OF STOCK: {product_name}"
        elif 'price' in changes:
            return f"💰 PRICE CHANGE: {product_name}"
        elif 'quantity' in changes:
            return f"📦 QUANTITY CHANGE: {product_name}"
        else:
            return f"📦 Status Update: {product_name}"
    
    def _status_label(self, status_data: Dict) -> str:
        labels = {
            'in_stock': 'In Stock',
            'low_stock': 'Low Stock',
            'out_of_stock': 'Out of Stock',
            'unknown': 'Unknown'
        }
        status = status_data.get('stock_status')
        if status in labels:
            label = labels[status]
            if status == 'low_stock' and status_data.get('quantity') is not None:
                return f"{label} ({status_data['quantity']} left)"
            return label
        return 'In Stock' if status_data.get('in_stock') else 'Out of Stock'
    
    def create_email_body(self, product: Dict, status_data: Dict, changes: Dict) -> str:
        """Create HTML email body"""
        product_name = product.get('name', 'Product')
        product_url = product.get('url', '#')
        
        # Determine status message
        if 'stock_status' in changes:
            status = changes['stock_status']['to']
            if status == 'low_stock':
                status_html = '<h2 style="color: #eab308;">⚠️ Product is LOW IN STOCK!</h2>'
            elif status == 'in_stock':
                status_html = '<h2 style="color: green;">✅ Product is now IN STOCK!</h2>'
            elif status == 'out_of_stock':
                status_html = '<h2 style="color: red;">❌ Product is now OUT OF STOCK!</h2>'
            else:
                status_html = '<h2>📦 Product Status Update</h2>'
        elif 'stock' in changes:
            if changes['stock']['to']:
                status_html = '<h2 style="color: green;">✅ Product is now IN STOCK!</h2>'
            else:
                status_html = '<h2 style="color: red;">❌ Product is now OUT OF STOCK!</h2>'
        elif 'quantity' in changes:
            status_html = '<h2 style="color: #eab308;">📦 Product quantity changed!</h2>'
        else:
            status_html = '<h2>📦 Product Status Update</h2>'
        
        # Build HTML content
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #4CAF50; color: white; padding: 10px; text-align: center; }}
                .content {{ padding: 20px; background-color: #f9f9f9; }}
                .info {{ margin: 10px 0; }}
                .label {{ font-weight: bold; }}
                .button {{ display: inline-block; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; }}
                .footer {{ margin-top: 20px; font-size: 12px; color: #666; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Product Monitor Alert</h1>
                </div>
                <div class="content">
                    {status_html}
                    
                    <div class="info">
                        <span class="label">Product:</span> {product_name}
                    </div>
                    
                    <div class="info">
                        <span class="label">Current Status:</span> {self._status_label(status_data)}
                    </div>
                    
                    <div class="info">
                        <span class="label">Quantity Left:</span> {status_data.get('quantity') if status_data.get('quantity') is not None else 'Unknown'}
                    </div>
                    
                    <div class="info">
                        <span class="label">Current Price:</span> {status_data.get('currency', 'USD')} {status_data.get('price', 0):.2f}
                    </div>
                    
                    <div class="info">
                        <span class="label">Timestamp:</span> {status_data.get('timestamp', 'N/A')}
                    </div>
        """
        
        # Add change details
        if 'price' in changes:
            html += f"""
                    <div class="info">
                        <span class="label">Price Change:</span> {changes['price']['currency']} {changes['price']['from']:.2f} → {changes['price']['currency']} {changes['price']['to']:.2f}
                    </div>
            """
        if 'quantity' in changes:
            html += f"""
                    <div class="info">
                        <span class="label">Quantity Change:</span> {changes['quantity']['from']} → {changes['quantity']['to']}
                    </div>
            """
        
        html += f"""
                    <div style="margin-top: 20px;">
                        <a href="{product_url}" class="button">View Product</a>
                    </div>
                </div>
                <div class="footer">
                    <p>This is an automated message from your Product Availability Monitor Bot.</p>
                    <p>To stop monitoring this product, please visit the dashboard.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html
