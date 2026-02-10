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

# Page configuration
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        color: #1f77b4;
        font-size: 2.5em;
        font-weight: bold;
        margin-bottom: 10px;
    }
    .sub-header {
        color: #666;
        font-size: 1.1em;
        margin-bottom: 20px;
    }
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
        padding: 12px;
        border-radius: 5px;
        margin: 10px 0;
    }
    .error-box {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
        padding: 12px;
        border-radius: 5px;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "scraper_agent" not in st.session_state:
    st.session_state.scraper_agent = None
if "extracted_products" not in st.session_state:
    st.session_state.extracted_products = {}
if "extraction_errors" not in st.session_state:
    st.session_state.extraction_errors = []
if "processing_complete" not in st.session_state:
    st.session_state.processing_complete = False

def main():
    # Header
    st.markdown('<div class="main-header">📊 Market Price - Intelligence Platform</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Scrape, analyze, and gain competitive intelligence for Protection products</div>', unsafe_allow_html=True)
    
    # Check API key
    if not ANTHROPIC_API_KEY:
        st.error("❌ ANTHROPIC_API_KEY not found. Please set it in your environment variables.")
        st.stop()
    
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📥 Upload URLs", "🔍 Scraping Results", "📈 Analysis & Intelligence", "📋 Data Export"])
    
    # TAB 1: URL UPLOAD
    with tab1:
        st.header("Upload URLs for Scraping")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Option 1: Upload CSV File")
            uploaded_file = st.file_uploader(
                "Upload a CSV file with URLs",
                type="csv",
                help="CSV should have a 'url' column with product page URLs"
            )
            
            if uploaded_file:
                urls = parse_csv_urls(uploaded_file)
                st.success(f"✓ Parsed {len(urls)} URLs from CSV")
        
        with col2:
            st.subheader("Option 2: Paste URLs as Text")
            text_input = st.text_area(
                "Paste URLs (one per line)",
                height=150,
                placeholder="https://example.com/page1\nhttps://example.com/page2\n..."
            )
            
            if text_input.strip():
                urls = parse_text_urls(text_input)
                st.success(f"✓ Parsed {len(urls)} URLs from text")
        
        # Get URLs from whichever input was provided
        urls = None
        if uploaded_file:
            urls = parse_csv_urls(uploaded_file)
        elif text_input.strip():
            urls = parse_text_urls(text_input)
        
        if urls:
            # Validate URLs
            st.subheader("URL Validation")
            valid_urls = [u for u in urls if validate_url(u)]
            invalid_urls = [u for u in urls if not validate_url(u)]
            
            col1, col2 = st.columns(2)
            with col1:
                st.success(f"✓ Valid URLs: {len(valid_urls)}")
            with col2:
                if invalid_urls:
                    st.warning(f"⚠ Invalid URLs: {len(invalid_urls)}")
                    with st.expander("Show invalid URLs"):
                        for url in invalid_urls:
                            st.text(url)
            
            # Deduplicate URLs
            final_urls = deduplicate_urls(valid_urls)
            st.info(f"Processing {len(final_urls)} unique URLs")
            
            # Start scraping
            if st.button("🚀 Start Scraping", key="scrape_btn", type="primary"):
                st.session_state.processing_complete = False
                
                with st.spinner("🔄 Initializing scraper..."):
                    st.session_state.scraper_agent = ScraperAgent(api_key=ANTHROPIC_API_KEY)
                
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
                        final_urls,
                        progress_callback=progress_callback
                    )
                
                # Store results in session state
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
                
                st.success("✓ Report generated!")
                st.markdown(report)
                
                # Option to download report as text
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"competitor_intelligence_{timestamp}.txt"
                st.download_button(
                    label="📥 Download Report as Text",
                    data=report.encode('utf-8'),
                    file_name=filename,
                    mime="text/plain"
                )
    
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
            <p>Market Price - Intelligence Platform | Yoga Manickavasakam</p>
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
