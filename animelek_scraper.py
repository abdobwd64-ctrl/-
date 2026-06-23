import requests
from bs4 import BeautifulSoup
import logging
import re
import sys
import os

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('animelek')

BASE_URL = 'https://animelek.top'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def safe_request(url, timeout=15):
    logger.debug(f"Requesting URL: {url}")
    try:
        resp = SESSION.get(url, timeout=timeout)
        logger.debug(f"Response status: {resp.status_code}, size: {len(resp.text)} bytes")
        resp.raise_for_status()
        return resp
    except requests.exceptions.Timeout:
        logger.error(f"Timeout requesting {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed for {url}: {e}")
        return None

def parse_search_results(html):
    logger.debug("Parsing search results HTML")
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    cards = soup.find_all('div', class_='anime-card')
    logger.debug(f"Found {len(cards)} anime-card divs")

    for card in cards:
        try:
            links = card.find_all('a', href=True)
            anime_link = None
            anime_name = None
            anime_type = None
            anime_year = None

            for a in links:
                href = a['href']
                text = a.get_text(strip=True)
                if '/anime/' in href and not anime_link:
                    anime_link = href
                if text and not anime_name:
                    anime_name = text

            spans = card.find_all('span')
            for span in spans:
                txt = span.get_text(strip=True)
                if txt:
                    if not anime_type and re.search(r'[\u0600-\u06FF]', txt):
                        anime_type = txt
                    elif re.match(r'\d{4}', txt):
                        anime_year = txt

            img_tag = card.find('img')
            img_src = img_tag['src'] if img_tag and img_tag.get('src') else None

            entry = {
                'name': anime_name or 'Unknown',
                'url': anime_link or '',
                'type': anime_type or '',
                'year': anime_year or '',
                'image': img_src or '',
            }
            logger.debug(f"Found anime: {entry['name']} - {entry['url']}")
            results.append(entry)
        except Exception as e:
            logger.warning(f"Error parsing anime card: {e}")
            continue

    if not results:
        logger.debug("No anime cards found, looking for alternative containers")
        for alt_cls in ['media-block', 'box-5x1', 'result-item']:
            containers = soup.find_all('div', class_=lambda c: c and alt_cls in c)
            logger.debug(f"Trying class '{alt_cls}': found {len(containers)}")

    logger.info(f"Parsed {len(results)} anime results from search")
    return results

def parse_pinned_cards(html):
    logger.debug("Parsing pinned cards (latest episodes)")
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    cards = soup.find_all('div', class_='pinned-card')
    logger.debug(f"Found {len(cards)} pinned-card divs")

    for card in cards:
        try:
            links = card.find_all('a', href=True)
            ep_link = None
            anime_link = None
            anime_name = None
            ep_name = None
            img_src = None

            for a in links:
                href = a['href']
                text = a.get_text(strip=True)
                if '/episode/' in href:
                    ep_link = href
                    if text:
                        ep_name = text
                elif '/anime/' in href:
                    anime_link = href
                    if text:
                        anime_name = text

            img_tag = card.find('img')
            if img_tag and img_tag.get('src'):
                img_src = img_tag['src']

            if anime_name or ep_link:
                entry = {
                    'anime_name': anime_name or 'Unknown',
                    'anime_url': anime_link or '',
                    'episode_url': ep_link or '',
                    'episode_name': ep_name or '',
                    'image': img_src or '',
                }
                logger.debug(f"Pinned: {entry['anime_name']} - {entry['episode_name']}")
                results.append(entry)
        except Exception as e:
            logger.warning(f"Error parsing pinned card: {e}")
            continue

    logger.info(f"Parsed {len(results)} pinned cards")
    return results

def search_anime(query):
    logger.info(f"=== SEARCH: query='{query}' ===")
    url = f"{BASE_URL}/search/?s={query}"
    resp = safe_request(url)
    if resp is None:
        logger.error("Search request failed, cannot proceed")
        return []
    results = parse_search_results(resp.text)
    logger.info(f"Search completed: found {len(results)} results")
    return results

def get_homepage_pinned():
    logger.info("=== FETCHING HOMEPAGE PINNED CARDS ===")
    resp = safe_request(BASE_URL)
    if resp is None:
        logger.error("Homepage request failed")
        return []
    results = parse_pinned_cards(resp.text)
    logger.info(f"Homepage: found {len(results)} pinned episodes")
    return results

def get_anime_details(anime_url):
    logger.info(f"=== FETCHING ANIME DETAILS: {anime_url} ===")
    if not anime_url.startswith('http'):
        anime_url = BASE_URL + anime_url
    resp = safe_request(anime_url)
    if resp is None:
        return None

    soup = BeautifulSoup(resp.text, 'html.parser')
    details = {}

    title_tag = soup.find('h1')
    details['title'] = title_tag.get_text(strip=True) if title_tag else ''

    desc_tag = soup.find('div', class_='description')
    details['description'] = desc_tag.get_text(strip=True)[:500] if desc_tag else ''

    img_tag = soup.find('div', class_='anime-poster')
    if img_tag:
        img = img_tag.find('img')
        details['image'] = img['src'] if img and img.get('src') else ''
    else:
        details['image'] = ''

    logger.debug(f"Anime details: {details.get('title', 'N/A')}")
    return details

if __name__ == '__main__' and not os.environ.get('GRADIO_MODE'):
    action = sys.argv[1] if len(sys.argv) > 1 else 'pinned'
    logger.info(f"Starting animelek scraper, action={action}")

    if action == 'pinned':
        eps = get_homepage_pinned()
        print(f"\nLatest episodes ({len(eps)}):")
        for ep in eps[:10]:
            print(f"  - {ep['anime_name']}: {ep['episode_name']}")
            print(f"    {ep['episode_url']}")

    elif action == 'search':
        query = sys.argv[2] if len(sys.argv) > 2 else 'naruto'
        results = search_anime(query)
        print(f"\nSearch results for '{query}' ({len(results)}):")
        for r in results[:10]:
            print(f"  - {r['name']} ({r['type']}) [{r['year']}]")
            print(f"    {r['url']}")

    logger.info("Done!")
