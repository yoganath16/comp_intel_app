import json
import logging
import time
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


def _extract_product_objects_from_text(text: str) -> list:
    """
    Find and parse JSON objects that contain "product_name" (e.g. when the model returns
    malformed array or extra text). Returns list of product dicts or empty list.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        # Look for start of object that looks like product
        idx = text.find('"product_name"', i)
        if idx == -1:
            break
        # Find preceding opening brace
        start = text.rfind("{", i, idx + 1)
        if start == -1:
            i = idx + 1
            continue
        # Find matching closing brace
        depth = 0
        end = -1
        for j in range(start, n):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end == -1:
            i = start + 1
            continue
        candidate = text[start : end + 1]
        i = end + 1
        try:
            repaired = re.sub(r",\s*]", "]", re.sub(r",\s*}", "}", candidate))
            repaired = "".join(c for c in repaired if ord(c) >= 32 or c in "\n\r\t")
            obj = json.loads(repaired)
            if isinstance(obj, dict) and obj.get("product_name") is not None:
                out.append(obj)
        except json.JSONDecodeError:
            continue
    return out


def extract_product_data(html_content: str, url: str, api_key: str, max_retries: int = 3) -> list:
    """
    Use Claude to intelligently extract product data from HTML.
    Returns list of product dictionaries with extracted information.
    
    Args:
        html_content: HTML content to analyze
        url: Source URL for logging
        api_key: Anthropic API key
        max_retries: Maximum number of retries for rate limit errors
    """
    client = anthropic.Anthropic(api_key=api_key)
    
    # Smart extraction: includes prefix + windows around every £/$ and pricing phrase (not "first N chars").
    # Use 60k to ensure all price blocks are captured. Rate limiting handled by delays between requests.
    html_for_analysis = _build_extraction_input(html_content, max_chars=120000)
    
    prompt = f"""You are a data extraction expert. Analyze the following HTML content from {url} and extract ALL product/service offerings.

CRITICAL: Your response must be ONLY a valid JSON array. No text before or after. No markdown code fences. No explanation. Use double quotes for keys and strings. Escape any quotes inside strings with backslash. Use null for missing values.

IMPORTANT: Look carefully for product names, prices (look for £, $, currency symbols), plan names, coverage options. Extract even partial information if full details aren't available. Only return empty array [] if you are absolutely certain there are NO products/services mentioned anywhere in the HTML.

Required fields per product (use null if not found):
- product_name (string) - REQUIRED, extract this even if other fields are missing
- price_monthly (string with currency e.g. "£15.50" or null)
- price_annual (string with currency or null)
- excess (string or null)
- features (array of strings)
- special_offers (string or null)
- terms_conditions (string or null)
- category (string)

Example valid response (no other text):
[{{"product_name": "Plan A", "price_monthly": "£10", "price_annual": "£120", "excess": "£50", "features": ["Cover 1"], "special_offers": null, "terms_conditions": null, "category": "Boiler"}}]

HTML Content:
{html_for_analysis}
"""

    # Retry logic for rate limit errors
    for attempt in range(max_retries):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            break  # Success, exit retry loop
        except anthropic.APIError as e:
            # Check if it's a rate limit error (429)
            is_rate_limit = (
                hasattr(e, 'status_code') and e.status_code == 429
            ) or (
                hasattr(e, 'response') and hasattr(e.response, 'status_code') and e.response.status_code == 429
            ) or (
                "rate_limit" in str(e).lower() or "429" in str(e)
            )
            
            if is_rate_limit and attempt < max_retries - 1:
                # Longer backoff so rate limit window can reset (30k tokens/min)
                wait_time = (8, 25, 60)[min(attempt, 2)]
                logger.warning(
                    f"Rate limit hit for {url} (attempt {attempt + 1}/{max_retries}). "
                    f"Waiting {wait_time}s before retry..."
                )
                time.sleep(wait_time)
            else:
                # Last attempt failed or non-rate-limit error
                if is_rate_limit:
                    logger.error(f"Rate limit error for {url} after {max_retries} attempts: {e}")
                else:
                    logger.error(f"API error while extracting data from {url}: {e}")
                return []

    try:
        
        response_text = message.content[0].text or ""

        def _repair_json(s: str) -> str:
            """Apply common repairs to malformed JSON."""
            s = s.strip()
            # Remove trailing commas before ] or }
            s = re.sub(r",\s*]", "]", s)
            s = re.sub(r",\s*}", "}", s)
            # Replace unescaped newlines inside double-quoted strings (simplified: replace \n not preceded by \)
            # Match "...." and replace literal newlines with \n
            def fix_newlines_in_quotes(m):
                return m.group(0).replace("\n", " ").replace("\r", " ")
            s = re.sub(r'"(?:[^"\\]|\\.)*"', fix_newlines_in_quotes, s, flags=re.DOTALL)
            s = re.sub(r"'(?:[^'\\]|\\.)*'", fix_newlines_in_quotes, s, flags=re.DOTALL)
            # Strip control characters
            s = "".join(c for c in s if ord(c) >= 32 or c in "\n\r\t")
            return s

        def _try_parse_json(s: str):
            """Try to parse JSON string, return None if fails."""
            s = s.strip()
            if not s:
                return None
            for candidate in (s, _repair_json(s)):
                try:
                    out = json.loads(candidate)
                    if isinstance(out, list):
                        return out
                    if isinstance(out, dict):
                        return [out]
                    return None
                except json.JSONDecodeError:
                    continue
            try:
                import ast
                value = ast.literal_eval(s)
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    return [value]
                return None
            except Exception:
                return None

        def _find_array_bounds(text: str) -> tuple:
            """Find start/end of top-level JSON array, respecting strings. Returns (start, end) or (-1, -1)."""
            n = len(text)
            # First pass: find candidate "[" that are not inside a string
            in_str = False
            q = None
            escape = False
            candidates = []
            i = 0
            while i < n:
                c = text[i]
                if escape:
                    escape = False
                    i += 1
                    continue
                if in_str:
                    if c == "\\":
                        escape = True
                        i += 1
                        continue
                    if c == q:
                        in_str = False
                    i += 1
                    continue
                if c in '"\'':
                    in_str = True
                    q = c
                    i += 1
                    continue
                if c == "[":
                    candidates.append(i)
                i += 1
            # For first candidate, run string-aware bracket match
            for start in candidates:
                i = start + 1
                depth = 1
                in_double = False
                in_single = False
                escape = False
                quote_char = None
                while i < n and depth > 0:
                    c = text[i]
                    if escape:
                        escape = False
                        i += 1
                        continue
                    if (in_double or in_single) and c == "\\":
                        escape = True
                        i += 1
                        continue
                    if not in_double and not in_single:
                        if c == "[":
                            depth += 1
                        elif c == "]":
                            depth -= 1
                            if depth == 0:
                                return (start, i)
                        elif c == '"':
                            in_double = True
                            quote_char = '"'
                        elif c == "'":
                            in_single = True
                            quote_char = "'"
                    elif c == quote_char:
                        in_double = False
                        in_single = False
                    i += 1
                if depth == 0:
                    return (start, i - 1)
            return (-1, -1)

        products = None

        # Strategy 1: Direct parse
        logger.debug(f"Strategy 1: Trying direct parse of response (length: {len(response_text)})")
        products = _try_parse_json(response_text)
        if products:
            logger.debug(f"Strategy 1 SUCCESS: Found {len(products)} products")
        else:
            logger.debug("Strategy 1 FAILED: Direct parse returned None")

        # Strategy 2: Markdown code blocks
        if products is None:
            logger.debug("Strategy 2: Trying markdown code block extraction")
            for marker in ["```json", "```"]:
                if marker in response_text:
                    logger.debug(f"Found markdown marker: {marker}")
                    try:
                        parts = response_text.split(marker, 1)
                        if len(parts) > 1:
                            code_block = parts[1].split("```", 1)[0].strip()
                            # Remove "json" prefix if present (from ```json marker)
                            if code_block.startswith("json"):
                                code_block = code_block[4:].strip()
                            logger.debug(f"Extracted code block (length: {len(code_block)}, first 200: {code_block[:200]})")
                            products = _try_parse_json(code_block)
                            if products is not None:
                                logger.debug(f"Strategy 2 SUCCESS with {marker}: Found {len(products)} products")
                                break
                            else:
                                logger.debug(f"Strategy 2 FAILED with {marker}: _try_parse_json returned None, trying repair")
                                # Try with repair
                                repaired = _repair_json(code_block)
                                products = _try_parse_json(repaired)
                                if products is not None:
                                    logger.debug(f"Strategy 2 SUCCESS with {marker} (after repair): Found {len(products)} products")
                                    break
                                else:
                                    logger.debug(f"Strategy 2 FAILED with {marker} (even after repair)")
                    except Exception as e:
                        logger.debug(f"Strategy 2 exception with {marker}: {e}")
                        continue

        # Strategy 3: String-aware bracket matching for [...]
        if products is None:
            logger.debug("Strategy 3: Trying string-aware bracket matching")
            start, end = _find_array_bounds(response_text)
            if start != -1 and end > start:
                json_candidate = response_text[start : end + 1]
                logger.debug(f"Found array bounds: start={start}, end={end}, length={len(json_candidate)}")
                products = _try_parse_json(json_candidate)
                if products:
                    logger.debug(f"Strategy 3 SUCCESS: Found {len(products)} products")
                else:
                    logger.debug("Strategy 3 FAILED: _try_parse_json returned None, trying repair")
                    repaired = _repair_json(json_candidate)
                    products = _try_parse_json(repaired)
                    if products:
                        logger.debug(f"Strategy 3 SUCCESS (after repair): Found {len(products)} products")
                    else:
                        logger.debug("Strategy 3 FAILED: Even after repair")
            else:
                logger.debug(f"Strategy 3 FAILED: No array bounds found (start={start}, end={end})")

        # Strategy 4: Repair and retry bracket slice
        if products is None and "[" in response_text and "{" in response_text:
            start, end = _find_array_bounds(response_text)
            if start != -1 and end > start:
                json_candidate = _repair_json(response_text[start : end + 1])
                products = _try_parse_json(json_candidate)

        # Strategy 5: Extract product-like JSON objects and merge into list (handles truncated/malformed array)
        if products is None and '"product_name"' in response_text:
            logger.debug("Strategy 5: Trying object extraction")
            _extracted = _extract_product_objects_from_text(response_text)
            if _extracted:
                logger.debug(f"Strategy 5 SUCCESS: Found {len(_extracted)} products")
                products = _extracted
            else:
                logger.debug("Strategy 5 FAILED: No objects extracted")

        # If still not parsed, log and return empty list
        if products is None:
            logger.error(f"JSON decode error for {url}: unable to parse response as JSON array")
            logger.info(f"Response sample (first 1200 chars): {response_text[:1200]!r}")
            return []
        
        if not isinstance(products, list):
            logger.warning(f"Response is not a list for {url}, converting to list")
            products = [products] if isinstance(products, dict) else []

        if len(products) == 0:
            logger.warning(f"No products extracted from {url} - checking if HTML contains price/product indicators...")
            # Check if HTML actually has price/product content before retrying
            has_prices = bool(re.search(r"[£$€]\s*\d", html_content))
            has_product_words = bool(re.search(r"\b(product|plan|cover|premium|option)", html_content, re.IGNORECASE))
            
            if has_prices or has_product_words:
                logger.info(f"HTML contains price/product indicators - retrying with focused extraction")
                # Retry with a more focused extraction (still 50k to capture price blocks)
                html_retry = _build_extraction_input(html_content, max_chars=50000)
                try:
                    prompt_retry = prompt.replace(html_for_analysis, html_retry)
                    msg = client.messages.create(
                        model="claude-sonnet-4-5-20250929",
                        max_tokens=2000,
                        messages=[{"role": "user", "content": prompt_retry}],
                    )
                    response_retry = (msg.content[0].text or "").strip()
                    # Try all parsing strategies on retry response
                    products = _try_parse_json(response_retry)
                    if not products:
                        start, end = _find_array_bounds(response_retry)
                        if start != -1 and end > start:
                            products = _try_parse_json(response_retry[start : end + 1])
                    if not products:
                        products = _extract_product_objects_from_text(response_retry)
                    if products:
                        logger.info(f"Retry extracted {len(products)} products from {url}")
                    else:
                        logger.warning(f"Retry also returned 0 products. Response sample: {response_retry[:800]!r}")
                except Exception as retry_err:
                    logger.debug(f"Retry failed: {retry_err}")
            else:
                logger.info(f"HTML does not appear to contain price/product content - skipping retry")
        else:
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