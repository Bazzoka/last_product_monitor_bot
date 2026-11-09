from bot.scrapers.anti_detection import AntiDetection
from bot.scrapers.product_scraper import ProductScraper

AntiDetection.random_delay = staticmethod(lambda *a, **k: None)

scraper = ProductScraper()
scraper.setup_session()
scraper.session.cookies.set("cart_currency", "EGP", domain="www.parisawang.com", path="/")
scraper.session.cookies.set("localization", "EG", domain="www.parisawang.com", path="/")

data = scraper.scrape_product(
    "https://www.parisawang.com/products/gabrielle-east-west-shoulder-bag",
    {"name": "Gabrielle"},
)
print(data.get("price"), data.get("currency"), data.get("stock_status"))
assert data["price"] == 498.0, data["price"]
print("EGP cookie override passed")
