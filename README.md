# Product Availability Monitoring Bot

A production-ready Python application that monitors product availability and price changes across multiple websites, sends alerts via Email and Telegram, and provides a secure web dashboard for management.

## Features

- **Multi-site monitoring** — Track products from Amazon, Walmart, Best Buy, and any custom URL
- **Change detection** — In stock, out of stock, and price change alerts
- **Dual notifications** — Email (HTML) and Telegram with product name, URL, status, price, and timestamp
- **Anti-detection scraping** — Rotating user agents, random delays, session persistence, optional proxy
- **JavaScript support** — Selenium WebDriver for JS-rendered pages
- **Concurrent checks** — Monitor multiple products in parallel
- **JSON storage** — No database required; all data in JSON files
- **Web dashboard** — Modern responsive UI with authentication

## Project Structure

```
product-monitor-bot/
├── main.py                  # Root entry point
├── config.py                # Configuration re-export
├── run.py                   # Alternative entry point
├── requirements.txt
├── .env                     # Environment variables (create from .env.example)
├── .env.example
├── README.md
├── data/                    # Auto-created JSON storage
│   ├── products.json
│   ├── notifications.json
│   ├── logs.json
│   ├── settings.json
│   └── session/             # Browser session cookies
├── bot/
│   ├── main.py              # Bot coordinator
│   ├── config.py            # Configuration loader
│   ├── scrapers/            # Web scraping modules
│   ├── notifications/       # Email & Telegram
│   ├── dashboard/           # Flask web UI
│   │   ├── templates/
│   │   └── static/
│   ├── storage/             # JSON file operations
│   ├── utils/               # Logging, validation, helpers
│   └── logs/                # application.log
```

## Requirements

- Python 3.8+
- Google Chrome (for Selenium WebDriver on JS-rendered sites)

## Installation

### 1. Clone and enter the project

```bash
cd product-monitor-bot
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
copy .env.example .env    # Windows
# cp .env.example .env  # macOS/Linux
```

Edit `.env` with your credentials:

| Variable | Description |
|----------|-------------|
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_TO` | SMTP email alerts |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram bot alerts |
| `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD` | Dashboard login |
| `DASHBOARD_SECRET_KEY` | Flask session secret (use a random string) |
| `USE_PROXY`, `PROXY_HTTP`, `PROXY_HTTPS` | Optional proxy |
| `CHECK_INTERVAL_HOURS` | Scan interval (default: 1 hour) |
| `MAX_CONCURRENT_CHECKS` | Parallel product checks (default: 3) |
| `HEADLESS_BROWSER` | Run Chrome headless (default: true) |

### 5. Run the bot

```bash
python main.py
# or
python run.py
```

Open the dashboard at **http://127.0.0.1:8080**

> **Windows note:** Port 5000 is often reserved by Windows (Hyper-V). The default port is **8080**. If needed, change `DASHBOARD_PORT` in `.env`.

Default login: `admin` / value of `DASHBOARD_PASSWORD` in `.env`

## Dashboard

| Page | Description |
|------|-------------|
| **Dashboard** | Stats, recent notifications, last scan time, manual "Check Now" |
| **Products** | Add/remove URLs, enable/disable monitoring, view status & price |
| **Logs** | System activity and error history |
| **Settings** | Price change threshold, notification preferences |

## Adding Products

1. Go to **Products** → **Add Product**
2. Enter a name and product URL
3. Optionally add custom CSS selectors for stock, price, and title
4. Toggle monitoring on/off per product

### Custom CSS Selectors (Advanced)

For sites where auto-detection fails, provide selectors in the add form:

- **Stock selector** — Element containing stock status text
- **Price selector** — Element containing the price
- **Title selector** — Product title element

## Notification Setup

### Email (Gmail example)

1. Enable 2FA on your Google account
2. Create an [App Password](https://myaccount.google.com/apppasswords)
3. Set in `.env`:

```
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USERNAME=your@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_FROM=your@gmail.com
EMAIL_TO=recipient@example.com
```

### Telegram

1. Message [@BotFather](https://t.me/BotFather) to create a bot and get a token
2. Get your chat ID from [@userinfobot](https://t.me/userinfobot)
3. Set in `.env`:

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=your_chat_id
```

## How Monitoring Works

1. Every `CHECK_INTERVAL_HOURS`, the bot scrapes all enabled products
2. Current status is compared against the cached/previous state
3. On change (stock or price), notifications are sent via configured channels
4. Duplicate notifications within 60 minutes are suppressed
5. All history is saved to JSON files

## Anti-Detection Features

- Rotating user agents on every request
- Random delays between requests (1–5 seconds)
- Browser-like HTTP headers (Sec-Fetch-*, Accept-Language, etc.)
- Session cookie persistence across runs
- Optional HTTP/HTTPS proxy support
- Selenium stealth options (disable automation flags)

## Data Files

| File | Contents |
|------|----------|
| `data/products.json` | Monitored products, status, price history |
| `data/notifications.json` | Sent notification log |
| `data/logs.json` | Structured application logs |
| `data/settings.json` | Dashboard settings |
| `bot/logs/application.log` | Detailed file log |

## Security Notes

- Never commit `.env` to version control
- Change default dashboard credentials before deploying
- Use a strong `DASHBOARD_SECRET_KEY`
- The dashboard requires login for all routes

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Chrome/WebDriver errors | Install Chrome; webdriver-manager auto-downloads the driver |
| Scraping returns wrong data | Add custom CSS selectors for the target site |
| No notifications | Verify `.env` credentials; check Logs page |
| 403/blocked requests | Enable proxy; increase delays; use custom selectors |
| Dashboard won't load | On Windows, port 5000 is often blocked — use `DASHBOARD_PORT=8080` in `.env` |

## License

MIT
