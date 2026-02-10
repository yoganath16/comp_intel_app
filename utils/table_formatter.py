import pandas as pd
from typing import List, Dict, Any
from urllib.parse import urlparse

from utils.product_cleaner import dedupe_products


def _provider_from_source_url(source_url: Any) -> str:
    if not source_url:
        return ""
    # source_url may be newline-joined after dedupe; take first URL for provider label
    first = str(source_url).splitlines()[0].strip()
    try:
        return urlparse(first).netloc
    except Exception:
        return ""

def format_products_as_dataframe(products: List[Dict[str, Any]], dedupe: bool = True) -> pd.DataFrame:
    """
    Convert products list to a nicely formatted DataFrame for display.
    """
    if not products:
        return pd.DataFrame()

    if dedupe:
        products, _ = dedupe_products(products)
    
    # Create DataFrame
    df = pd.DataFrame(products)

    # Add provider column (derived from source URL domain) for easier comparisons
    if "source_url" in df.columns and "provider" not in df.columns:
        df.insert(0, "provider", df["source_url"].apply(_provider_from_source_url))
    
    # Define column order
    preferred_columns = [
        "provider",
        "product_name",
        "price_monthly",
        "price_annual",
        "excess",
        "special_offers",
        "category",
        "source_url"
    ]
    
    # Reorder columns
    existing_cols = [col for col in preferred_columns if col in df.columns]
    other_cols = [col for col in df.columns if col not in existing_cols]
    df = df[existing_cols + other_cols]
    
    # Format features column
    if "features" in df.columns:
        df["features"] = df["features"].apply(
            lambda x: "\n".join(f"• {f}" for f in x) if isinstance(x, list) else x
        )
    
    # Rename columns for display
    column_mapping = {
        "provider": "Provider",
        "product_name": "Product Name",
        "price_monthly": "Monthly Price",
        "price_annual": "Annual Price",
        "excess": "Excess",
        "features": "Features",
        "special_offers": "Special Offers",
        "terms_conditions": "Terms & Conditions",
        "category": "Category",
        "source_url": "Source URL"
    }
    
    df = df.rename(columns=column_mapping)
    
    return df

def format_summary_statistics(stats: Dict[str, Any]) -> pd.DataFrame:
    """
    Format summary statistics as a DataFrame.
    """
    stats_list = []
    
    for key, value in stats.items():
        # Format the key
        display_key = key.replace("_", " ").title()
        
        # Format the value
        if isinstance(value, float):
            display_value = f"£{value:.2f}" if "price" in key else f"{value:.2f}"
        else:
            display_value = str(value)
        
        stats_list.append({
            "Metric": display_key,
            "Value": display_value
        })
    
    return pd.DataFrame(stats_list)

def format_errors_as_dataframe(errors: List[Dict[str, str]]) -> pd.DataFrame:
    """
    Format errors list as a DataFrame for display.
    """
    if not errors:
        return pd.DataFrame()
    
    df = pd.DataFrame(errors)
    df = df.rename(columns={"url": "URL", "error": "Error"})
    return df