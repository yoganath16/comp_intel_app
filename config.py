import os
from dotenv import load_dotenv

load_dotenv()

# Anthropic API Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"

# App Configuration
APP_TITLE = "AI Powered Competitor Intelligence"
APP_DESCRIPTION = "Scrape, normalize and benchmark competitor products and pricing with an AI-powered intelligence workspace."

# Scraping Configuration
MAX_URLS_PER_BATCH = 50
URL_FETCH_TIMEOUT = 30
MAX_RETRIES = 2

# Output Configuration
EXPORT_FORMATS = ["CSV"]
CACHE_ENABLED = True
CACHE_TTL = 3600  # 1 hour

# Data Schema
PRODUCT_FIELDS = [
    "product_name",
    "price_monthly",
    "price_annual",
    "excess",
    "features",
    "special_offers",
    "terms_conditions",
    "source_url"
]

# Logging
LOG_LEVEL = "INFO"