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


def _ensure_competitor_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure a 'competitor' column exists for display:
    - Prefer existing 'competitor' field (from CSV)
    - Fall back to domain derived from 'source_url' when missing/blank
    """
    if "competitor" not in df.columns:
        if "source_url" in df.columns:
            df["competitor"] = df["source_url"].apply(_provider_from_source_url)
        else:
            df["competitor"] = ""
    else:
        if "source_url" in df.columns:
            df["competitor"] = df.apply(
                lambda row: row["competitor"]
                if isinstance(row.get("competitor"), str) and row["competitor"].strip()
                else _provider_from_source_url(row.get("source_url")),
                axis=1,
            )
    return df


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

    # Ensure competitor column exists (from CSV or URL domain)
    df = _ensure_competitor_column(df)

    # Build combined "Coverage and T&Cs" column from features + terms_conditions
    if "features" in df.columns or "terms_conditions" in df.columns:
        def _combine_coverage(row: Dict[str, Any]) -> str:
            parts = []
            feats = row.get("features")
            if isinstance(feats, list):
                feat_str = "\n".join(f"• {f}" for f in feats)
                if feat_str:
                    parts.append(feat_str)
            elif isinstance(feats, str) and feats.strip():
                parts.append(feats.strip())

            tc = row.get("terms_conditions")
            if isinstance(tc, str) and tc.strip():
                parts.append(tc.strip())

            return "\n\n".join(parts) if parts else ""

        df["coverage_and_tcs"] = df.apply(_combine_coverage, axis=1)

    # Drop internal-only / now-redundant columns we don't want to display
    drop_cols = [
        "provider",
        "source_url",
        "features",
        "terms_conditions",
        "_provider_domain",
        "_source_urls",
    ]
    existing_drop = [c for c in drop_cols if c in df.columns]
    if existing_drop:
        df = df.drop(columns=existing_drop)

    # Define display column order (first column: provider/competitor name)
    preferred_columns = [
        "competitor",
        "product_name",
        "price_monthly",
        "price_annual",
        "excess",
        "special_offers",
        "category",
        "coverage_and_tcs",
    ]

    # Reorder columns
    existing_cols = [col for col in preferred_columns if col in df.columns]
    other_cols = [col for col in df.columns if col not in existing_cols]
    df = df[existing_cols + other_cols]

    # Rename columns for display
    column_mapping = {
        "competitor": "Provider",
        "product_name": "Product Name",
        "price_monthly": "Monthly Price",
        "price_annual": "Annual Price",
        "excess": "Excess",
        "special_offers": "Special Offers",
        "category": "Category",
        "coverage_and_tcs": "Coverage and T&Cs",
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