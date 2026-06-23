import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from animelek_scraper import (
    logger, search_anime, get_homepage_pinned,
    safe_request, parse_search_results, parse_pinned_cards,
    BASE_URL
)

import gradio as gr

logger.info("=" * 60)
logger.info("🚀 Starting AnimeLek Scraper Web App")
logger.info("=" * 60)

CSS = """
.app { max-width: 1000px; margin: auto; padding: 20px; }
table { width: 100%; border-collapse: collapse; }
td, th { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
tr:hover { background-color: #f5f5f5; }
"""

def build_html_table(results, title):
    if not results:
        return "<div style='padding:20px;text-align:center;color:#888;'>No results found.</div>"

    is_pinned = 'episode_url' in results[0] if results else False

    html = f"<h3>{title} ({len(results)})</h3>"
    html += "<table><thead><tr>"
    if is_pinned:
        html += "<th>#</th><th>Anime</th><th>Episode</th><th>Link</th>"
    else:
        html += "<th>#</th><th>Name</th><th>Type</th><th>Year</th><th>Link</th>"
    html += "</tr></thead><tbody>"

    for i, r in enumerate(results[:50], 1):
        html += "<tr>"
        if is_pinned:
            name = r.get('anime_name', '?')
            ep = r.get('episode_name', '')
            url = r.get('anime_url', '')
            html += f"<td>{i}</td>"
            html += f"<td>{name[:60]}</td>"
            html += f"<td>{ep}</td>"
            html += f"<td><a href='{url}' target='_blank'>View</a></td>"
        else:
            name = r.get('name', '?')
            typ = r.get('type', '')
            year = r.get('year', '')
            url = r.get('url', '')
            html += f"<td>{i}</td>"
            html += f"<td>{name[:80]}</td>"
            html += f"<td>{typ}</td>"
            html += f"<td>{year}</td>"
            html += f"<td><a href='{url}' target='_blank'>View</a></td>"
        html += "</tr>"

    html += "</tbody></table>"
    if len(results) > 50:
        html += f"<p><em>Showing 50 of {len(results)} results</em></p>"
    return html

def handle_search(query):
    logger.info(f"🔍 User search: '{query}'")
    if not query or not query.strip():
        return "<div style='padding:20px;color:#888;'>Please enter a search term.</div>"
    results = search_anime(query.strip())
    return build_html_table(results, f"Search results for '{query}'")

def handle_pinned():
    logger.info("📌 User requested latest episodes")
    results = get_homepage_pinned()
    return build_html_table(results, "Latest Episodes")

logger.info("🎨 Building Gradio interface...")

with gr.Blocks(
    title="AnimeLek Scraper",
    css=CSS,
    theme=gr.themes.Soft()
) as demo:
    gr.Markdown("""
    # 🎬 AnimeLek Scraper

    Search for anime on **[AnimeLek](https://animelek.top/)** or browse the latest episodes.
    """)

    with gr.Row():
        search_input = gr.Textbox(
            label="🔍 Search anime",
            placeholder="e.g. one piece, naruto, bleach, attack on titan, solo leveling...",
            scale=4,
        )
        search_btn = gr.Button("Search", variant="primary", scale=1)

    with gr.Row():
        pinned_btn = gr.Button("📌 Latest Episodes", variant="secondary", size="sm")

    output = gr.HTML(label="Results")

    search_btn.click(fn=handle_search, inputs=search_input, outputs=output)
    search_input.submit(fn=handle_search, inputs=search_input, outputs=output)
    pinned_btn.click(fn=handle_pinned, outputs=output)

    gr.Markdown("""
    ---
    ### 📋 Notes
    - Search works with **English** or **Arabic** names
    - Results are scraped live from [AnimeLek](https://animelek.top/)
    - Debug logs are printed to the server console
    """)

logger.info("✅ Interface built, launching...")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
