import csv
import io
from typing import List, Dict, Any
import pandas as pd
import logging

logger = logging.getLogger(__name__)

from utils.product_cleaner import dedupe_products

def export_products_to_csv(products: List[Dict[str, Any]]) -> bytes:
    """
    Export products list to CSV format.
    Returns bytes that can be downloaded.
    """
    if not products:
        logger.warning("No products to export")
        return b""
    
    try:
        # Remove duplicates for cleaner exports (same product+price across multiple pages)
        products, _ = dedupe_products(products)

        # Create DataFrame
        df = pd.DataFrame(products)
        
        # Reorder columns for better readability
        preferred_columns = [
            "competitor",
            "product_name",
            "price_monthly",
            "price_annual",
            "excess",
            "special_offers",
            "category",
            "source_url"
        ]
        
        # Keep preferred columns that exist, then add any others
        existing_cols = [col for col in preferred_columns if col in df.columns]
        other_cols = [col for col in df.columns if col not in existing_cols]
        
        df = df[existing_cols + other_cols]
        
        # Handle features column (list to string conversion)
        if "features" in df.columns:
            df["features"] = df["features"].apply(
                lambda x: " | ".join(x) if isinstance(x, list) else x
            )
        
        # Convert to CSV
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        
        return csv_buffer.getvalue().encode('utf-8')
    
    except Exception as e:
        logger.error(f"Error exporting to CSV: {e}")
        return b""

def parse_csv_urls(uploaded_file) -> List[Dict[str, Any]]:
    """
    Parse URLs (and optional competitor names) from uploaded CSV file.

    Expects a 'url' column in the CSV, and optionally a 'competitor' (or
    'competitor_name') column. Returns a list of dicts:
      {"url": "<url>", "competitor": "<name or None>"}
    """
    try:
        # Read the uploaded file
        stringio = io.StringIO(uploaded_file.getvalue().decode("utf8"), newline=None)
        data = pd.read_csv(stringio)

        # Look for 'url' or 'URL' column
        url_column = None
        for col in data.columns:
            if col.lower() == "url":
                url_column = col
                break

        if url_column is None:
            logger.error(f"No 'url' column found. Available columns: {list(data.columns)}")
            return []

        # Optional competitor column
        competitor_column = None
        for col in data.columns:
            if col.lower() in ("competitor", "competitor_name"):
                competitor_column = col
                break

        # Extract URLs (and competitor names) and remove duplicates while preserving order
        rows: List[Dict[str, Any]] = []
        seen = set()

        for _, row in data.iterrows():
            raw_url = row.get(url_column)
            if pd.notna(raw_url):
                url_str = str(raw_url).strip()
                if url_str and url_str not in seen:
                    seen.add(url_str)
                    comp_name = None
                    if competitor_column is not None:
                        raw_comp = row.get(competitor_column)
                        if pd.notna(raw_comp):
                            comp_name = str(raw_comp).strip()
                    rows.append({"url": url_str, "competitor": comp_name})

        logger.info(f"Parsed {len(rows)} URL rows from CSV")
        return rows

    except Exception as e:
        logger.error(f"Error parsing CSV: {e}")
        return []

def parse_text_urls(text: str) -> List[str]:
    """
    Parse URLs from plain text (one URL per line).
    """
    urls = []
    seen = set()
    
    for line in text.strip().split('\n'):
        url = line.strip()
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    
    logger.info(f"Parsed {len(urls)} URLs from text")
    return urls

def create_download_link(csv_data: bytes, filename: str = "products.csv") -> str:
    """
    Create a download link for CSV data.
    """
    import base64
    
    csv_base64 = base64.b64encode(csv_data).decode()
    href = f'<a href="data:file/csv;base64,{csv_base64}" download="{filename}">Download CSV</a>'
    return href