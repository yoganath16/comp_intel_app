import re
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)

def validate_url(url: str) -> bool:
    """Validate if a string is a proper URL."""
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return url_pattern.match(url) is not None

def process_urls_from_text(text: str) -> Tuple[List[str], List[str]]:
    """
    Extract URLs from text (one per line).
    Returns tuple of (valid_urls, invalid_urls)
    """
    lines = text.strip().split('\n')
    valid_urls = []
    invalid_urls = []
    
    for line in lines:
        url = line.strip()
        if url:  # Skip empty lines
            if validate_url(url):
                valid_urls.append(url)
            else:
                invalid_urls.append(url)
    
    return valid_urls, invalid_urls

def process_urls_from_csv(csv_content: str, url_column: str = "url") -> Tuple[List[str], List[str]]:
    """
    Extract URLs from CSV content.
    Assumes first row is header with 'url' or specified column name.
    Returns tuple of (valid_urls, invalid_urls)
    """
    import csv
    from io import StringIO
    
    valid_urls = []
    invalid_urls = []
    
    try:
        reader = csv.DictReader(StringIO(csv_content))
        if not reader.fieldnames or url_column not in reader.fieldnames:
            logger.error(f"CSV does not contain '{url_column}' column")
            return valid_urls, invalid_urls
        
        for row in reader:
            url = row.get(url_column, "").strip()
            if url:
                if validate_url(url):
                    valid_urls.append(url)
                else:
                    invalid_urls.append(url)
    
    except Exception as e:
        logger.error(f"Error processing CSV: {e}")
    
    return valid_urls, invalid_urls

def deduplicate_urls(urls: List[str]) -> List[str]:
    """Remove duplicate URLs while preserving order."""
    seen = set()
    result = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result