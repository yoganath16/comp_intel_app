import json
import logging
from typing import Optional, Dict, Any, List
import anthropic
import re

logger = logging.getLogger(__name__)

def _build_extraction_input(html_content: str, max_chars: int = 60000) -> str:
    """
    Build a compact but information-dense HTML/text input for the LLM.

    Problem: many modern pages put pricing/product cards far beyond the first N chars.
    Strategy:
    - Always include a small prefix (title/nav context)
    - Add windows around currency occurrences (e.g. £15.50, $99)
    - Add windows around common product/plan words
    - De-dupe and merge overlapping windows
    """
    if not html_content:
        return ""

    # Always include a small prefix for context (title, H1, etc.)
    prefix_len = min(8000, len(html_content))
    windows: List[tuple[int, int]] = [(0, prefix_len)]

    # Capture windows around currency amounts and common pricing tokens.
    patterns = [
        r"[£$€]\s*\d",                   # currency symbol + digit
        r"\b(per\s+month|a\s+month)\b",  # pricing phrasing
        r"\bmonthly\b",
        r"\bannually\b|\byear\b",
        r"\bexcess\b|\bdeductible\b",
        r"\bcover\b|\bplan\b|\bpremium\b|\boptions\b",
    ]

    # Use fairly small windows to keep total size bounded.
    pre = 1200
    post = 2400

    for pat in patterns:
        try:
            for m in re.finditer(pat, html_content, flags=re.IGNORECASE):
                start = max(0, m.start() - pre)
                end = min(len(html_content), m.end() + post)
                windows.append((start, end))
        except re.error:
            continue

    # Sort and merge overlaps
    windows.sort(key=lambda x: x[0])
    merged: List[tuple[int, int]] = []
    for s, e in windows:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    # Concatenate merged windows until max_chars is reached
    parts: List[str] = []
    total = 0
    for s, e in merged:
        if total >= max_chars:
            break
        chunk = html_content[s:e]
        if not chunk.strip():
            continue
        remaining = max_chars - total
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        parts.append(chunk)
        total += len(chunk)

    return "\n\n<!-- SNIP -->\n\n".join(parts)

def extract_product_data(html_content: str, url: str, api_key: str) -> list:
    """
    Use Claude to intelligently extract product data from HTML.
    Returns list of product dictionaries with extracted information.
    """
    client = anthropic.Anthropic(api_key=api_key)
    
    # Build a compact but relevant input. Avoid naive prefix truncation which often drops prices.
    html_for_analysis = _build_extraction_input(html_content, max_chars=60000)
    
    prompt = f"""You are a data extraction expert. Analyze the following HTML content from {url} and extract ALL product/service offerings.

IMPORTANT: Return ONLY a valid JSON array, nothing else. No explanation, no markdown, just the JSON.

For each product/service, extract these fields:
- product_name: (string) Name of the product/service
- price_monthly: (string or null) Monthly price with currency symbol (e.g., "£15.50")
- price_annual: (string or null) Annual price with currency symbol (e.g., "£186")
- excess: (string or null) Excess/deductible amount
- features: (array of strings) List of features/coverage areas
- special_offers: (string or null) Promotional offers or discounts
- terms_conditions: (string or null) Important terms or restrictions
- category: (string) Product category/type

Return ONLY this format:
```json
[
  {{"product_name": "...", "price_monthly": "...", ...}},
  {{"product_name": "...", "price_monthly": "...", ...}}
]
```

If no products found, return empty array: []

HTML Content:
{html_for_analysis}
"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text or ""

        # Extract JSON from response (handle markdown code blocks and minor deviations)
        json_str = response_text

        # Primary path: strip markdown code fences if present
        if "```json" in json_str:
            try:
                json_str = json_str.split("```json", 1)[1].split("```", 1)[0]
            except Exception:
                pass
        elif "```" in json_str:
            try:
                json_str = json_str.split("```", 1)[1].split("```", 1)[0]
            except Exception:
                pass

        json_str = json_str.strip()

        def _try_parse(s: str):
            s = s.strip()
            if not s:
                return None
            return json.loads(s)

        products = None

        # First attempt: direct parse
        try:
            products = _try_parse(json_str)
        except json.JSONDecodeError:
            products = None

        # Fallback: try to isolate the JSON array using bracket heuristics
        if products is None:
            try:
                # Look for the first "[" and the last "]"
                start = json_str.find("[")
                end = json_str.rfind("]")
                if start != -1 and end != -1 and end > start:
                    bracket_slice = json_str[start : end + 1]
                    products = _try_parse(bracket_slice)
            except json.JSONDecodeError:
                products = None
            except Exception:
                products = None

        # If still not parsed, log and return empty list
        if products is None:
            logger.error(f"JSON decode error for {url}: unable to parse response as JSON array")
            logger.debug(f"Response text (first 800 chars): {response_text[:800]}")
            return []
        
        if not isinstance(products, list):
            logger.warning(f"Response is not a list for {url}, converting to list")
            products = [products] if isinstance(products, dict) else []
        
        logger.info(f"Successfully extracted {len(products)} products from {url}")
        return products
    
    except anthropic.APIError as e:
        logger.error(f"API error while extracting data from {url}: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error extracting data from {url}: {e}")
        return []

def generate_competitor_intelligence(products_data: Dict[str, Any], api_key: str) -> str:
    """
    Generate a comprehensive competitor intelligence summary from extracted product data.
    """
    client = anthropic.Anthropic(api_key=api_key)
    
    # Prepare data summary for the agent
    data_summary = json.dumps(products_data, indent=2)
    
    prompt = f"""You are a business intelligence analyst. Analyze the following product data extracted from multiple competitor websites and provide a comprehensive competitor intelligence report.

Product Data:
{data_summary}

Generate a detailed report covering:

1. **Market Overview**: Summary of products/services offered across competitors
2. **Pricing Analysis**: 
   - Price ranges for similar products
   - Most competitive offerings
   - Premium vs budget options
3. **Feature Comparison**: 
   - Common features across competitors
   - Unique/differentiated features
   - Feature gaps
4. **Promotional Tactics**: 
   - Current offers and incentives
   - Free services or trial periods
5. **Competitive Positioning**: 
   - Market positioning of each competitor
   - Strengths and weaknesses
   - Opportunities and threats
6. **Key Insights & Recommendations**:
   - Critical market insights
   - Strategic recommendations for differentiation
   - Areas for competitive advantage

Format the report with clear sections, bullet points where appropriate, and specific data references."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=3000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return message.content[0].text
    
    except anthropic.APIError as e:
        logger.error(f"API error while generating intelligence report: {e}")
        return "Error generating competitor intelligence report. Please try again."

def validate_extracted_data(products: list) -> list:
    """
    Validate and clean extracted product data.
    """
    validated_products = []
    
    for product in products:
        if not isinstance(product, dict):
            continue
        
        # Ensure required fields exist
        validated_product = {
            "product_name": product.get("product_name", "Unknown"),
            "price_monthly": product.get("price_monthly"),
            "price_annual": product.get("price_annual"),
            "excess": product.get("excess"),
            "features": product.get("features", []) if isinstance(product.get("features"), list) else [],
            "special_offers": product.get("special_offers"),
            "terms_conditions": product.get("terms_conditions"),
            "category": product.get("category", "General")
        }
        
        validated_products.append(validated_product)
    
    return validated_products