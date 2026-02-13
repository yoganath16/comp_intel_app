import logging
from typing import List, Dict, Any, Optional, Tuple
import anthropic
import requests
from agents.llm_utils import extract_product_data, validate_extracted_data
import time

logger = logging.getLogger(__name__)

class ScraperAgent:
    """
    Main agent for coordinating web scraping and product data extraction.
    """
    
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929"):
        self.api_key = api_key
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key)
        self.extracted_data = {}
        self.errors = []
    
    def fetch_url_content(self, url: str) -> Optional[str]:
        """
        Fetch HTML content from URL using requests library.
        Uses browser-like headers to reduce 403 blocks. Some sites block cloud/data-center IPs (e.g. when deployed on Streamlit Cloud).
        """
        try:
            logger.info(f"Fetching content from {url}")
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-GB,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            html_content = response.text
            logger.info(f"Successfully fetched {url}")
            return html_content
        
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                error_msg = (
                    f"403 Forbidden for {url}. The site may block requests from cloud/data-center IPs "
                    "(e.g. Streamlit Cloud). Try running locally or use a URL that allows server access."
                )
            else:
                error_msg = f"Failed to fetch {url}: {str(e)}"
            logger.error(error_msg)
            self.errors.append((url, error_msg))
            return None
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to fetch {url}: {str(e)}"
            logger.error(error_msg)
            self.errors.append((url, error_msg))
            return None
        except Exception as e:
            error_msg = f"Unexpected error fetching {url}: {str(e)}"
            logger.error(error_msg)
            self.errors.append((url, error_msg))
            return None
    
    def scrape_single_url(self, url: str, competitor_name: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Scrape a single URL and extract product data.
        Returns tuple of (products_data, error_message)
        """
        try:
            logger.info(f"Processing URL: {url}")
            
            # Fetch HTML content
            html_content = self.fetch_url_content(url)
            if not html_content:
                error_msg = f"Could not fetch content from {url}"
                return None, error_msg
            
            # Extract product data using Claude (with retry logic for rate limits)
            try:
                products = extract_product_data(html_content, url, self.api_key)
            except Exception as e:
                error_msg = f"Error during extraction from {url}: {str(e)}"
                logger.error(error_msg)
                return None, error_msg
            
            if not products:
                error_msg = f"No products extracted from {url}"
                return None, error_msg
            
            # Validate extracted data
            validated_products = validate_extracted_data(products)

            # Add source URL and competitor name to each product
            for product in validated_products:
                product["source_url"] = url
                if competitor_name:
                    product["competitor"] = competitor_name
            
            logger.info(f"Successfully extracted {len(validated_products)} products from {url}")
            return {"url": url, "products": validated_products}, None
        
        except Exception as e:
            error_msg = f"Error processing {url}: {str(e)}"
            logger.error(error_msg)
            return None, error_msg
    
    def scrape_multiple_urls(self, urls: List[str], progress_callback=None, url_to_competitor: Optional[Dict[str, str]] = None) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
        """
        Scrape multiple URLs and aggregate results.
        Returns tuple of (all_products_by_url, errors)
        progress_callback: Optional function to report progress (url, index, total)
        """
        all_results = {}
        errors = []
        
        for index, url in enumerate(urls):
            if progress_callback:
                progress_callback(url, index, len(urls))
            
            competitor_name = None
            if url_to_competitor:
                competitor_name = url_to_competitor.get(url)

            result, error = self.scrape_single_url(url, competitor_name=competitor_name)
            
            if result:
                all_results[url] = result["products"]
            
            if error:
                errors.append({"url": url, "error": error})
            
            # Increased delay to avoid rate limits (30k tokens/min limit)
            # Wait longer between requests to stay under limit
            if index < len(urls) - 1:  # Don't wait after last URL
                time.sleep(2.0)  # Increased from 0.5s to 2s
        
        self.extracted_data = all_results
        self.errors = errors
        
        return all_results, errors
    
    def get_all_products_flat(self) -> List[Dict[str, Any]]:
        """
        Get all extracted products as a flat list.
        """
        all_products = []
        for url, products in self.extracted_data.items():
            all_products.extend(products)
        return all_products
    
    def get_summary_statistics(self) -> Dict[str, Any]:
        """
        Get summary statistics of extracted data.
        """
        all_products = self.get_all_products_flat()
        
        # Extract prices for analysis
        monthly_prices = [p.get("price_monthly") for p in all_products if p.get("price_monthly")]
        annual_prices = [p.get("price_annual") for p in all_products if p.get("price_annual")]
        
        # Try to extract numeric values from price strings
        def extract_numeric_price(price_str):
            if not price_str:
                return None
            import re
            match = re.search(r'[\d.]+', str(price_str))
            return float(match.group()) if match else None
        
        numeric_monthly = [extract_numeric_price(p) for p in monthly_prices]
        numeric_monthly = [p for p in numeric_monthly if p is not None]
        
        numeric_annual = [extract_numeric_price(p) for p in annual_prices]
        numeric_annual = [p for p in numeric_annual if p is not None]
        
        return {
            "total_urls_scraped": len(self.extracted_data),
            "total_products": len(all_products),
            "errors_count": len(self.errors),
            "urls_with_data": len([u for u, p in self.extracted_data.items() if p]),
            "avg_monthly_price": sum(numeric_monthly) / len(numeric_monthly) if numeric_monthly else None,
            "min_monthly_price": min(numeric_monthly) if numeric_monthly else None,
            "max_monthly_price": max(numeric_monthly) if numeric_monthly else None,
            "avg_annual_price": sum(numeric_annual) / len(numeric_annual) if numeric_annual else None,
            "min_annual_price": min(numeric_annual) if numeric_annual else None,
            "max_annual_price": max(numeric_annual) if numeric_annual else None,
        }