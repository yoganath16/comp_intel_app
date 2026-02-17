import logging
from typing import List, Dict, Any, Optional, Tuple
import anthropic
import requests
import json
import re
import time
from agents.llm_utils import extract_product_data, validate_extracted_data

logger = logging.getLogger(__name__)

class ScraperAgent:
    """
    Production-safe scraping agent for Streamlit Cloud.
    Handles:
    - JS-heavy sites via __NEXT_DATA__ extraction
    - Soft 403 detection
    - Empty JS shell detection
    - Improved logging for debugging
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929"):
        self.api_key = api_key
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key)
        self.extracted_data = {}
        self.errors = []

    # ---------------------------------------------------------
    # FETCH HTML
    # ---------------------------------------------------------

    def fetch_url_content(self, url: str) -> Optional[str]:
        """
        Fetch HTML content.
        Also attempts to extract embedded JSON for React/Next.js sites.
        """
        try:
            logger.info(f"Fetching content from {url}")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-GB,en;q=0.9",
                "Connection": "keep-alive",
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            html = response.text

            # ---- Detect empty JS shell ----
            if "__NEXT_DATA__" in html:
                logger.info(f"Detected Next.js site at {url} – extracting embedded JSON")
                match = re.search(
                    r'<script id="__NEXT_DATA__".*?>(.*?)</script>',
                    html,
                    re.DOTALL,
                )
                if match:
                    try:
                        json_data = json.loads(match.group(1))
                        return json.dumps(json_data)
                    except Exception:
                        logger.warning("Failed to parse __NEXT_DATA__ JSON")

            # ---- Detect obvious JS-only shell ----
            if len(html) < 5000 and "<div id=" in html:
                logger.warning(f"Likely JS-rendered empty shell for {url}")

            return html

        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 403:
                error_msg = (
                    f"403 Forbidden for {url}. "
                    f"Cloud IP may be blocked."
                )
            else:
                error_msg = f"HTTP error fetching {url}: {str(e)}"
            logger.error(error_msg)
            self.errors.append((url, error_msg))
            return None

        except Exception as e:
            error_msg = f"Unexpected fetch error for {url}: {str(e)}"
            logger.error(error_msg)
            self.errors.append((url, error_msg))
            return None

    # ---------------------------------------------------------
    # SCRAPE SINGLE
    # ---------------------------------------------------------

    def scrape_single_url(
        self,
        url: str,
        competitor_name: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:

        try:
            html_content = self.fetch_url_content(url)
            if not html_content:
                return None, f"Could not fetch content from {url}"

            products = extract_product_data(
                html_content,
                url,
                self.api_key
            )

            if not products:
                logger.warning(
                    f"No products extracted. HTML sample:\n"
                    f"{html_content[:1000]}"
                )
                return None, f"No products extracted from {url}"

            validated_products = validate_extracted_data(products)

            for product in validated_products:
                product["source_url"] = url
                if competitor_name:
                    product["competitor"] = competitor_name

            logger.info(f"Extracted {len(validated_products)} products from {url}")

            return {"url": url, "products": validated_products}, None

        except Exception as e:
            error_msg = f"Error processing {url}: {str(e)}"
            logger.error(error_msg)
            return None, error_msg

    # ---------------------------------------------------------
    # SCRAPE MULTIPLE
    # ---------------------------------------------------------

    def scrape_multiple_urls(
        self,
        urls: List[str],
        progress_callback=None,
        url_to_competitor: Optional[Dict[str, str]] = None,
    ) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:

        all_results = {}
        errors = []

        for index, url in enumerate(urls):

            if progress_callback:
                progress_callback(url, index, len(urls))

            competitor_name = (
                url_to_competitor.get(url)
                if url_to_competitor
                else None
            )

            result, error = self.scrape_single_url(
                url,
                competitor_name=competitor_name
            )

            if result:
                all_results[url] = result["products"]

            if error:
                errors.append({"url": url, "error": error})

            # Slight delay to avoid Claude rate limits
            if index < len(urls) - 1:
                time.sleep(6)

        self.extracted_data = all_results
        self.errors = errors

        return all_results, errors

    # ---------------------------------------------------------
    # UTILITIES
    # ---------------------------------------------------------

    def get_all_products_flat(self) -> List[Dict[str, Any]]:
        all_products = []
        for products in self.extracted_data.values():
            all_products.extend(products)
        return all_products

    def get_summary_statistics(self) -> Dict[str, Any]:

        all_products = self.get_all_products_flat()

        def extract_numeric(price):
            if not price:
                return None
            match = re.search(r'[\d.]+', str(price))
            return float(match.group()) if match else None

        monthly = [
            extract_numeric(p.get("price_monthly"))
            for p in all_products
            if p.get("price_monthly")
        ]
        monthly = [m for m in monthly if m is not None]

        return {
            "total_urls_scraped": len(self.extracted_data),
            "total_products": len(all_products),
            "errors_count": len(self.errors),
            "urls_with_data": len(
                [u for u, p in self.extracted_data.items() if p]
            ),
            "avg_monthly_price": (
                sum(monthly) / len(monthly)
                if monthly else None
            ),
        }