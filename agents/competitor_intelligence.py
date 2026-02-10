import logging
from typing import Dict, Any, List
import anthropic
import json
from urllib.parse import urlparse

from utils.product_cleaner import dedupe_products

logger = logging.getLogger(__name__)

class CompetitorIntelligenceAgent:
    """
    Agent for generating competitive intelligence reports from scraped product data.
    """
    
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929"):
        self.api_key = api_key
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key)
    
    def generate_report(self, products_by_url: Dict[str, List[Dict[str, Any]]]) -> str:
        """
        Generate a comprehensive competitor intelligence report from scraped data.
        """
        try:
            # Prepare data for analysis
            report_data = self._prepare_data_for_analysis(products_by_url)
            
            # Create the analysis prompt
            prompt = self._create_analysis_prompt(report_data)
            
            # Call Claude to generate the report
            message = self.client.messages.create(
                model=self.model,
                max_tokens=3000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            report = message.content[0].text
            logger.info("Successfully generated competitor intelligence report")
            return report
        
        except anthropic.APIError as e:
            logger.error(f"Error generating intelligence report: {e}")
            return "Error generating competitor intelligence report. Please try again."
    
    def _prepare_data_for_analysis(self, products_by_url: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Prepare and structure data for analysis.
        """
        # Group by domain (provider) and aggregate products across multiple URLs.
        providers: Dict[str, Dict[str, Any]] = {}

        for url, products in (products_by_url or {}).items():
            if not products:
                continue
            domain = urlparse(url).netloc.lower()
            if domain not in providers:
                providers[domain] = {"urls": [], "products": []}
            providers[domain]["urls"].append(url)
            providers[domain]["products"].extend(products)

        analysis_data: Dict[str, Any] = {}
        for domain, data in providers.items():
            merged_products, dedupe_stats = dedupe_products(data["products"])
            analysis_data[domain] = {
                "provider_domain": domain,
                "urls": data["urls"],
                "product_count": len(merged_products),
                "dedupe": dedupe_stats,
                "products": merged_products,
                "categories": self._extract_categories(merged_products),
                "price_range": self._calculate_price_range(merged_products),
                "unique_features": self._extract_unique_features(merged_products),
                "is_british_gas": ("britishgas.co.uk" in domain),
            }

        return analysis_data
    
    def _extract_categories(self, products: List[Dict[str, Any]]) -> List[str]:
        """Extract unique product categories."""
        categories = set()
        for product in products:
            if product.get("category"):
                categories.add(product["category"])
        return list(categories)
    
    def _calculate_price_range(self, products: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate price ranges from products."""
        import re
        
        monthly_prices = []
        annual_prices = []
        
        for product in products:
            # Extract numeric value from price strings
            if product.get("price_monthly"):
                match = re.search(r'[\d.]+', str(product["price_monthly"]))
                if match:
                    monthly_prices.append(float(match.group()))
            
            if product.get("price_annual"):
                match = re.search(r'[\d.]+', str(product["price_annual"]))
                if match:
                    annual_prices.append(float(match.group()))
        
        return {
            "monthly": {
                "min": min(monthly_prices) if monthly_prices else None,
                "max": max(monthly_prices) if monthly_prices else None,
                "avg": sum(monthly_prices) / len(monthly_prices) if monthly_prices else None,
            },
            "annual": {
                "min": min(annual_prices) if annual_prices else None,
                "max": max(annual_prices) if annual_prices else None,
                "avg": sum(annual_prices) / len(annual_prices) if annual_prices else None,
            }
        }
    
    def _extract_unique_features(self, products: List[Dict[str, Any]]) -> Dict[str, int]:
        """Extract and count unique features across products."""
        feature_count = {}
        
        for product in products:
            if product.get("features") and isinstance(product["features"], list):
                for feature in product["features"]:
                    if isinstance(feature, str):
                        # Normalize feature string
                        normalized = feature.strip().lower()
                        feature_count[normalized] = feature_count.get(normalized, 0) + 1
        
        # Sort by frequency
        return dict(sorted(feature_count.items(), key=lambda x: x[1], reverse=True))
    
    def _create_analysis_prompt(self, analysis_data: Dict[str, Any]) -> str:
        """Create the prompt for competitive analysis."""
        
        # Format data as JSON for clarity
        data_json = json.dumps(analysis_data, indent=2, default=str)

        # Baseline provider for comparison
        has_bg = any(v.get("is_british_gas") for v in analysis_data.values()) if analysis_data else False
        
        prompt = f"""You are a strategic business analyst specializing in competitive intelligence.
Your task is to create a comparison report where **British Gas is the baseline** and all other market players are compared against it.

If British Gas data is missing, clearly state that British Gas is not present in the dataset and fall back to a general market comparison.
British Gas present in dataset: {has_bg}

DATA COLLECTED:
{data_json}

Generate a detailed report with the following sections:

## 1. EXECUTIVE SUMMARY
- Brief overview of the competitive landscape
- Number of providers analyzed and total unique products found (after dedupe)
- Key headline differences vs British Gas (pricing, coverage breadth, offers)

## 2. BRITISH GAS BASELINE (if present)
- Summarize British Gas product lineup, price ranges, and top features/coverage
- Note any prominent offers or terms

## 3. MARKET PLAYERS VS BRITISH GAS (provider-by-provider)
For each non–British Gas provider:
- Closest comparable products vs British Gas (by category/name/features)
- Price comparison (cheaper / similar / more expensive) with approximate deltas when possible
- Feature/coverage differences (what they include/exclude vs British Gas)
- Promotions/incentives differences
- Clear "Who wins?" callout per provider (Pricing / Features / Simplicity / Offer)

## 4. PRICING & VALUE MATRIX
- A table-like section (in text) grouping comparable categories/plans and showing British Gas vs others
- Identify budget leaders and premium leaders relative to British Gas

## 5. FEATURE / COVERAGE GAP ANALYSIS (vs British Gas)
- Features competitors commonly offer that British Gas lacks (if any)
- Features British Gas offers that are uncommon elsewhere (if any)
- Notable terms/exclusions that shift value vs British Gas

## 6. STRATEGIC IMPLICATIONS FOR BRITISH GAS
- Where British Gas is over/under-priced vs market
- Bundling or feature adjustments to defend/attack key rivals
- Offer strategy recommendations
- Messaging/positioning vs the strongest alternatives

Format the response with clear headings, bullet points where appropriate, and specific data references from the collected information. Be analytical and data-driven in your insights."""
        
        return prompt
    
    def generate_summary_report(self, products_by_url: Dict[str, List[Dict[str, Any]]]) -> str:
        """
        Generate a shorter summary report for quick insights.
        """
        try:
            # Prepare data
            analysis_data = self._prepare_data_for_analysis(products_by_url)
            data_json = json.dumps(analysis_data, indent=2, default=str)
            has_bg = any(v.get("is_british_gas") for v in analysis_data.values()) if analysis_data else False
            
            prompt = f"""Provide a concise comparison summary where British Gas is the baseline (if present).
If British Gas is missing, state that and provide a general summary.
British Gas present in dataset: {has_bg}

{data_json}

Include:
1. British Gas snapshot (or "not present")
2. Top 3 threats to British Gas (which providers and why)
3. Top 3 opportunities for British Gas (pricing/features/offers)
4. One primary recommendation (actionable)

Keep it brief and actionable."""
            
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            return message.content[0].text
        
        except anthropic.APIError as e:
            logger.error(f"Error generating summary report: {e}")
            return "Error generating summary report."