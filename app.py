import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from animelek_scraper import (
    logger, search_anime, get_homepage_pinned
)

import streamlit as st

st.set_page_config(
    page_title="AnimeLek Scraper",
    page_icon="🎬",
    layout="centered"
)

st.markdown("""
<style>
    .main > div { padding: 1rem; }
    .stTable { width: 100%; }
    .ep-link { color: #4da6ff; text-decoration: none; }
    .ep-link:hover { text-decoration: underline; }
    .result-count { font-size: 0.9rem; color: #888; margin-bottom: 1rem; }
</style>
""", unsafe_allow_html=True)

st.title("🎬 AnimeLek Scraper")
st.markdown("Search for anime on **AnimeLek** or browse the latest episodes.")

col1, col2 = st.columns([4, 1])
with col1:
    query = st.text_input("Search anime", placeholder="e.g. one piece, naruto, bleach...")
with col2:
    search_clicked = st.button("🔍 Search", type="primary", use_container_width=True)

if st.button("📌 Latest Episodes", type="secondary"):
    with st.spinner("Fetching latest episodes..."):
        logger.info("User clicked Latest Episodes")
        results = get_homepage_pinned()
        if results:
            st.markdown(f"<div class='result-count'>Latest episodes ({len(results)})</div>", unsafe_allow_html=True)
            data = []
            for r in results:
                data.append({
                    "Anime": r['anime_name'],
                    "Episode": r['episode_name'],
                    "Link": f"[View]({r['anime_url']})",
                })
            st.dataframe(data, use_container_width=True, hide_index=True)
        else:
            st.error("No episodes found or failed to fetch.")

if search_clicked and query:
    with st.spinner(f"Searching for '{query}'..."):
        logger.info(f"User searched: {query}")
        results = search_anime(query.strip())
        if results:
            st.markdown(f"<div class='result-count'>Search results for '{query}' ({len(results)})</div>", unsafe_allow_html=True)
            data = []
            for r in results:
                data.append({
                    "Name": r['name'],
                    "Type": r['type'],
                    "Year": r['year'],
                    "Link": f"[View]({r['url']})",
                })
            st.dataframe(data, use_container_width=True, hide_index=True)
        else:
            st.warning(f"No results found for '{query}'.")

st.markdown("---")
st.markdown("🔍 Search works with **English** or **Arabic** names | Data scraped live from [AnimeLek](https://animelek.top/)")
