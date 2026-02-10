from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse


def _domain_from_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _normalize_money(value: Any) -> str:
    """
    Normalize price/excess strings to improve dedupe stability.
    Examples:
      "£15.50 a month" -> "£15.50"
      "15.5" -> "15.5"
      None -> ""
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # Pick first currency symbol if present
    currency_match = re.search(r"[£$€]", s)
    currency = currency_match.group(0) if currency_match else ""
    num_match = re.search(r"[\d]+(?:\.[\d]+)?", s.replace(",", ""))
    num = num_match.group(0) if num_match else ""
    if currency and num:
        # Preserve original precision but normalize trivial trailing dots/spaces
        return f"{currency}{num}"
    return s


def dedupe_products(products: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Remove duplicates that come from the same provider but different pages.
    Keyed by: provider_domain + product_name + monthly/annual price + excess.

    Returns: (deduped_products, stats)
    - deduped rows merge `source_url` into a newline-joined list for traceability.
    """
    if not products:
        return [], {"input_count": 0, "output_count": 0, "duplicates_removed": 0}

    seen: dict[tuple[str, str, str, str, str], Dict[str, Any]] = {}

    for p in products:
        if not isinstance(p, dict):
            continue

        src = p.get("source_url")
        provider = _domain_from_url(src)
        key = (
            provider,
            _normalize_text(p.get("product_name")),
            _normalize_money(p.get("price_monthly")),
            _normalize_money(p.get("price_annual")),
            _normalize_money(p.get("excess")),
        )

        if key not in seen:
            # Copy so we don't mutate the original list in session state
            new_p = dict(p)
            new_p["_provider_domain"] = provider
            new_p["_source_urls"] = [src] if src else []
            seen[key] = new_p
        else:
            existing = seen[key]
            if src and src not in existing.get("_source_urls", []):
                existing["_source_urls"].append(src)

            # Opportunistically fill blanks from later duplicates
            for field in ("special_offers", "terms_conditions", "category"):
                if not existing.get(field) and p.get(field):
                    existing[field] = p.get(field)
            if (not existing.get("features")) and p.get("features"):
                existing["features"] = p.get("features")

    deduped = list(seen.values())
    # Replace source_url with merged URLs for display/export
    for p in deduped:
        urls = p.get("_source_urls") or []
        if urls:
            p["source_url"] = "\n".join(urls)

    input_count = len([p for p in products if isinstance(p, dict)])
    output_count = len(deduped)
    return deduped, {
        "input_count": input_count,
        "output_count": output_count,
        "duplicates_removed": max(0, input_count - output_count),
    }

