import streamlit as st
import logging
from typing import List, Dict, Any
import os
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import modules
from config import ANTHROPIC_API_KEY, APP_TITLE, APP_DESCRIPTION
from agents.scraper_agent import ScraperAgent
from agents.competitor_intelligence import CompetitorIntelligenceAgent
from utils.url_processor import validate_url, deduplicate_urls
from utils.file_handler import parse_csv_urls, parse_text_urls, export_products_to_csv
from utils.table_formatter import format_products_as_dataframe, format_summary_statistics, format_errors_as_dataframe
from utils.report_export import export_report_to_docx

# Page configuration
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Global theme & layout CSS
st.markdown(
    """
<style>
    :root {
        --primary-pink: #d03e9d;
        --primary-navy: #08216b;
        --bg-soft: #f5f7fb;
        --card-bg: #ffffff;
        --accent-soft: #fbe7f4;
        --border-subtle: rgba(8, 33, 107, 0.06);
        --text-muted: #4b5878;
    }

    html, body, [data-testid="stApp"] {
        background: radial-gradient(circle at top left, #fbe7f4 0, #f5f7fb 35%, #ffffff 100%);
    }

    .app-header-title {
        color: var(--primary-navy);
        font-size: 2.2rem;
        font-weight: 700;
        letter-spacing: 0.02em;
        margin-bottom: 0.25rem;
    }

    .app-header-subtitle {
        color: var(--text-muted);
        font-size: 0.98rem;
        max-width: 34rem;
        line-height: 1.5;
        margin-bottom: 0.5rem;
    }

    .brand-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.15rem 0.75rem;
        border-radius: 999px;
        background: rgba(208, 62, 157, 0.08);
        color: var(--primary-pink);
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.09em;
        margin-bottom: 0.5rem;
    }

    /* Tweak tabs to feel more like an analytics workspace */
    [data-testid="stTabs"] button {
        font-weight: 600;
        border-radius: 999px !important;
        padding: 0.4rem 1.2rem !important;
    }

    [data-testid="stTabs"] button[aria-selected="true"] {
        background: linear-gradient(90deg, var(--primary-navy), var(--primary-pink));
        color: #ffffff !important;
    }

    [data-testid="stMetricValue"] {
        color: var(--primary-navy);
    }

    [data-testid="stMetricLabel"] {
        color: var(--text-muted);
    }

    /* Softer data frame background */
    [data-testid="stDataFrame"] {
        border-radius: 0.5rem;
        border: 1px solid var(--border-subtle);
        background-color: var(--card-bg);
    }

    .section-header {
        font-weight: 600;
        color: var(--primary-navy);
    }
</style>
""",
    unsafe_allow_html=True,
)

# Initialize session state
if "scraper_agent" not in st.session_state:
    st.session_state.scraper_agent = None
if "extracted_products" not in st.session_state:
    st.session_state.extracted_products = {}
if "extraction_errors" not in st.session_state:
    st.session_state.extraction_errors = []
if "processing_complete" not in st.session_state:
    st.session_state.processing_complete = False
if "intelligence_report" not in st.session_state:
    st.session_state.intelligence_report = None
if "intelligence_report_type" not in st.session_state:
    st.session_state.intelligence_report_type = None

def main():
    # Header with branding
    with st.container():
        left, right = st.columns([3, 2])
        with left:
            if os.path.exists("logo.svg"):
                st.image("logo.svg", width=170)
            st.markdown(
                "<div class='brand-pill'>AI workspace</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div class='app-header-title'>AI Powered Competitor Intelligence</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div class='app-header-subtitle'>Scrape, normalise and benchmark competitor propositions, pricing and coverage with an AI-assisted analysis environment.</div>",
                unsafe_allow_html=True,
            )
        with right:
            if os.path.exists("things.png"):
                st.image("things.png", width ="content")
    
    # Check API key
    if not ANTHROPIC_API_KEY:
        st.error("❌ ANTHROPIC_API_KEY not found. Please set it in your environment variables.")
        st.stop()
    
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📥 Upload URLs", "🔍 Scraping Results", "📈 Analysis & Intelligence", "📋 Data Export"])
    
    # TAB 1: URL UPLOAD
    with tab1:
        st.header("Upload URLs for Scraping")
        
        if st.session_state.processing_complete:
            st.success(
                "**Scraping complete.** All requested pages have been processed successfully. "
                "Go to the **Scraping Results** tab to view the extracted products and summary."
            )
            st.divider()
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Option 1: Upload CSV File")
            uploaded_file = st.file_uploader(
                "Upload a CSV file with URLs",
                type="csv",
                help="CSV should have a 'url' column with product page URLs and an optional 'competitor' column"
            )
            
            csv_rows = None
            if uploaded_file:
                csv_rows = parse_csv_urls(uploaded_file)
                st.success(f"✓ Parsed {len(csv_rows)} rows from CSV")
        
        with col2:
            st.subheader("Option 2: Paste URLs as Text")
            text_input = st.text_area(
                "Paste URLs (one per line)",
                height=150,
                placeholder="https://example.com/page1\nhttps://example.com/page2\n..."
            )
            
            text_urls = None
            if text_input.strip():
                text_urls = parse_text_urls(text_input)
                st.success(f"✓ Parsed {len(text_urls)} URLs from text")
        
        # Prefer CSV workflow when a file is uploaded; otherwise fall back to text URLs
        if uploaded_file and csv_rows:
            # Validate URLs from CSV
            st.subheader("URL Validation")
            valid_rows = [row for row in csv_rows if validate_url(row["url"])]
            invalid_rows = [row for row in csv_rows if not validate_url(row["url"])]
            
            col1, col2 = st.columns(2)
            with col1:
                st.success(f"✓ Valid URLs: {len(valid_rows)}")
            with col2:
                if invalid_rows:
                    st.warning(f"⚠ Invalid URLs: {len(invalid_rows)}")
                    with st.expander("Show invalid URLs"):
                        for row in invalid_rows:
                            st.text(row["url"])

            # Deduplicate by URL while preserving competitor names
            seen = set()
            final_rows = []
            for row in valid_rows:
                url_val = row["url"]
                if url_val not in seen:
                    seen.add(url_val)
                    final_rows.append(row)

            st.info(f"Processing {len(final_rows)} unique URLs")

            # Build competitor list for selection (exclude British Gas, which is always included)
            competitor_names = sorted(
                {
                    (row.get("competitor") or "").strip()
                    for row in final_rows
                    if row.get("competitor") and "british gas" not in row.get("competitor", "").strip().lower()
                }
            )

            selected_competitors = []
            if competitor_names:
                selected_competitors = st.multiselect(
                    "Choose competitors to scrape (British Gas will always be included):",
                    options=competitor_names,
                    default=competitor_names,
                    key="competitor_multiselect",
                )

            # Start scraping
            if st.button("🚀 Start Scraping", key="scrape_btn", type="primary"):
                st.session_state.processing_complete = False
                
                with st.spinner("🔄 Initializing scraper..."):
                    st.session_state.scraper_agent = ScraperAgent(api_key=ANTHROPIC_API_KEY)
                
                # Decide which URLs to scrape based on competitor selection
                from urllib.parse import urlparse

                def is_british_gas(row: Dict[str, Any]) -> bool:
                    comp = (row.get("competitor") or "").lower()
                    if "british gas" in comp:
                        return True
                    domain = urlparse(row["url"]).netloc.lower()
                    return "britishgas.co.uk" in domain

                urls_to_scrape = []
                url_to_competitor = {}

                for row in final_rows:
                    url_val = row["url"]
                    comp_name = (row.get("competitor") or "").strip()
                    bg = is_british_gas(row)

                    # Always include British Gas URLs; for others, filter by selected competitors (if any)
                    if bg or not selected_competitors or comp_name in selected_competitors:
                        urls_to_scrape.append(url_val)
                        label = comp_name or ("British Gas" if bg else "")
                        url_to_competitor[url_val] = label

                # Progress tracking
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                def progress_callback(url, index, total):
                    progress = (index + 1) / total
                    progress_bar.progress(progress)
                    status_text.text(f"Processing {index + 1}/{total}: {url[:50]}...")
                
                # Scrape URLs
                with st.spinner("📡 Scraping and extracting product data..."):
                    results, errors = st.session_state.scraper_agent.scrape_multiple_urls(
                        urls_to_scrape,
                        progress_callback=progress_callback,
                        url_to_competitor=url_to_competitor,
                    )
                
                # Store results in session state
                st.session_state.extracted_products = results
                st.session_state.extraction_errors = errors
                st.session_state.processing_complete = True
                
                progress_bar.empty()
                status_text.empty()
                
                st.success("✓ Scraping complete!")
                st.rerun()

        elif text_urls:
            # Text-based workflow (no competitor metadata)
            st.subheader("URL Validation")
            valid_urls = [u for u in text_urls if validate_url(u)]
            invalid_urls = [u for u in text_urls if not validate_url(u)]

            col1, col2 = st.columns(2)
            with col1:
                st.success(f"✓ Valid URLs: {len(valid_urls)}")
            with col2:
                if invalid_urls:
                    st.warning(f"⚠ Invalid URLs: {len(invalid_urls)}")
                    with st.expander("Show invalid URLs"):
                        for url in invalid_urls:
                            st.text(url)

            final_urls = deduplicate_urls(valid_urls)
            st.info(f"Processing {len(final_urls)} unique URLs")

            if st.button("🚀 Start Scraping", key="scrape_btn_text", type="primary"):
                st.session_state.processing_complete = False

                with st.spinner("🔄 Initializing scraper..."):
                    st.session_state.scraper_agent = ScraperAgent(api_key=ANTHROPIC_API_KEY)

                progress_bar = st.progress(0)
                status_text = st.empty()

                def progress_callback(url, index, total):
                    progress = (index + 1) / total
                    progress_bar.progress(progress)
                    status_text.text(f"Processing {index + 1}/{total}: {url[:50]}...")

                with st.spinner("📡 Scraping and extracting product data..."):
                    results, errors = st.session_state.scraper_agent.scrape_multiple_urls(
                        final_urls,
                        progress_callback=progress_callback,
                    )

                st.session_state.extracted_products = results
                st.session_state.extraction_errors = errors
                st.session_state.processing_complete = True

                progress_bar.empty()
                status_text.empty()

                st.success("✓ Scraping complete!")
                st.rerun()
    
    # TAB 2: SCRAPING RESULTS
    with tab2:
        st.header("Scraping Results")
        
        if not st.session_state.processing_complete or not st.session_state.scraper_agent:
            st.info("👈 Start by uploading URLs in the first tab")
        else:
            # Summary statistics
            st.subheader("📊 Summary Statistics")
            stats = st.session_state.scraper_agent.get_summary_statistics()
            
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("URLs Processed", stats["total_urls_scraped"])
            with col2:
                st.metric("Products Found", stats["total_products"])
            with col3:
                st.metric("Successful", stats["urls_with_data"])
            with col4:
                st.metric("Errors", stats["errors_count"])
            with col5:
                avg_price = stats.get("avg_monthly_price")
                if avg_price:
                    st.metric("Avg Monthly Price", f"£{avg_price:.2f}")
            
            # Products table
            st.subheader("📋 Extracted Products")
            
            all_products = st.session_state.scraper_agent.get_all_products_flat()
            
            if all_products:
                df = format_products_as_dataframe(all_products, dedupe=True)
                st.dataframe(df, use_container_width=True, height=400)
            else:
                st.warning("No products extracted from the URLs")
            
            # Errors
            if st.session_state.extraction_errors:
                st.subheader("⚠️ Extraction Errors")
                errors_df = format_errors_as_dataframe(st.session_state.extraction_errors)
                st.dataframe(errors_df, use_container_width=True)
    
    # TAB 3: ANALYSIS & INTELLIGENCE
    with tab3:
        st.header("Competitor Intelligence Analysis")
        
        if not st.session_state.processing_complete or not st.session_state.extracted_products:
            st.info("👈 Complete scraping first to generate analysis")
        else:
            st.subheader("Generate Competitive Intelligence Report")
            
            report_type = st.radio(
                "Report Type",
                ["Full Detailed Report", "Executive Summary"]
            )
            
            if st.button("📈 Generate Report", type="primary"):
                with st.spinner("🤖 Generating competitive intelligence report..."):
                    intelligence_agent = CompetitorIntelligenceAgent(api_key=ANTHROPIC_API_KEY)
                    
                    if report_type == "Full Detailed Report":
                        report = intelligence_agent.generate_report(st.session_state.extracted_products)
                    else:
                        report = intelligence_agent.generate_summary_report(st.session_state.extracted_products)
                    
                    st.session_state.intelligence_report = report
                    st.session_state.intelligence_report_type = report_type
                
                st.rerun()
            
            # Show last generated report and download options
            if st.session_state.intelligence_report:
                report = st.session_state.intelligence_report
                st.success("✓ Report generated!")
                st.markdown(report)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                logo_path = "logo.svg" if os.path.exists("logo.svg") else None
                report_title = "AI Powered Competitor Intelligence"
                
                st.subheader("Download report")
                try:
                    docx_bytes = export_report_to_docx(report, logo_path=logo_path, title=report_title)
                    st.download_button(
                        label="📝 Download Word (.docx)",
                        data=docx_bytes,
                        file_name=f"competitor_intelligence_{timestamp}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key="dl_docx",
                    )
                except Exception as e:
                    st.caption(f"Word export unavailable: {e}")
    
    # TAB 4: DATA EXPORT
    with tab4:
        st.header("Export Data")
        
        if not st.session_state.processing_complete or not st.session_state.extracted_products:
            st.info("👈 Complete scraping first to export data")
        else:
            all_products = st.session_state.scraper_agent.get_all_products_flat()
            
            if all_products:
                st.subheader("Download Products as CSV")
                
                csv_data = export_products_to_csv(all_products)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"products_{timestamp}.csv"
                
                st.download_button(
                    label="📥 Download CSV File",
                    data=csv_data,
                    file_name=filename,
                    mime="text/csv"
                )
                
                st.success(f"✓ Ready to export {len(all_products)} products")
            else:
                st.warning("No products to export")
    
    # Footer
    st.divider()
    st.markdown(
        """
        <div style='text-align: center; color: #666; margin-top: 20px;'>
            <p>AI Powered Competitor Intelligence | Yoga Manickavasakam</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

if __name__ == "__main__":
    main()
