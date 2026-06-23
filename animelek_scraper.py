import requests
from bs4 import BeautifulSoup
import logging
import re
import sys
import os
import urllib.parse

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
    logger.debug(f"Request: {url}")
    try:
        resp = SESSION.get(url, timeout=timeout)
        logger.debug(f"Response: {resp.status_code}, {len(resp.text)}b")
        resp.raise_for_status()
        return resp
    except Exception as e:
        logger.error(f"Failed: {url} - {e}")
        return None

def clean_url(url):
    if not url.startswith('http'):
        return BASE_URL + url if url.startswith('/') else BASE_URL + '/' + url
    return url

def extract_meta_list(soup):
    items = {}
    sidebar = soup.find('div', class_='widget-sidebar')
    if not sidebar:
        return items
    for li in sidebar.find_all('li'):
        text = li.get_text(strip=True)
        a_tag = li.find('a')
        span_tag = li.find('span')
        value = ''
        if a_tag:
            value = a_tag.get_text(strip=True)
        elif span_tag:
            value = span_tag.get_text(strip=True)
        if ':' in text:
            label = text.split(':')[0].strip()
            if value:
                items[label] = value
    return items

def get_anime_details(anime_url):
    logger.info(f"Fetching details: {anime_url}")
    url = clean_url(anime_url)
    resp = safe_request(url)
    if resp is None:
        return None
    soup = BeautifulSoup(resp.text, 'html.parser')
    detail = {}

    detail['url'] = url

    title_tag = soup.find('h1')
    detail['title'] = title_tag.get_text(strip=True) if title_tag else ''

    meta = extract_meta_list(soup)
    detail['status'] = meta.get('\u062d\u0627\u0644\u0629 \u0627\u0644\u0623\u0646\u0645\u064a', '')
    detail['type'] = meta.get('\u0627\u0644\u0646\u0648\u0639', '')
    detail['episodes'] = meta.get('\u0627\u0644\u062d\u0644\u0642\u0627\u062a', '')
    detail['start_date'] = meta.get('\u0628\u062f\u0627\u064a\u0629 \u0627\u0644\u0639\u0631\u0636', '')
    detail['season'] = meta.get('\u0627\u0644\u0645\u0648\u0633\u0645', '')

    genres_div = soup.find('div', class_='genres')
    detail['genres'] = []
    if genres_div:
        for a in genres_div.find_all('a'):
            g = a.get_text(strip=True)
            if g:
                detail['genres'].append(g)

    story_div = soup.find('div', class_='media-story')
    if story_div:
        content_div = story_div.find('div', class_='content')
        if content_div:
            detail['story'] = content_div.get_text(strip=True)
        else:
            detail['story'] = story_div.get_text(strip=True)
    else:
        detail['story'] = ''

    poster_div = soup.find('div', class_='anime-card')
    detail['image'] = ''
    if poster_div:
        img = poster_div.find('img')
        if img and img.get('src'):
            detail['image'] = img['src']

    detail['episodes_list'] = []
    ep_list = soup.find('ul', class_='episodes-lists')
    if ep_list:
        for li in ep_list.find_all('li'):
            num = li.get('data-number', '')
            title_el = li.find('span', class_='episode-title')
            link_el = li.find('a', class_='title')
            img_el = li.find('img')
            ep_url = link_el['href'] if link_el else ''
            ep_title = title_el.get_text(strip=True) if title_el else ''
            ep_img = img_el['src'] if img_el and img_el.get('src') else ''
            detail['episodes_list'].append({
                'number': num,
                'title': ep_title,
                'url': clean_url(ep_url),
                'image': ep_img
            })

    logger.info(f"Details: {detail['title']} - {len(detail['episodes_list'])} eps")
    return detail

def parse_search_results(html):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    cards = soup.find_all('div', class_='anime-card')
    for card in cards:
        try:
            links = card.find_all('a', href=True)
            anime_link = None
            anime_name = None
            for a in links:
                href = a['href']
                text = a.get_text(strip=True)
                if '/anime/' in href and not anime_link:
                    anime_link = href
                if text and not anime_name:
                    anime_name = text
            spans = card.find_all('span')
            anime_type = ''
            anime_year = ''
            for span in spans:
                txt = span.get_text(strip=True)
                if txt:
                    if not anime_type and re.search(r'[\u0600-\u06FF]', txt):
                        anime_type = txt
                    elif re.match(r'\d{4}', txt):
                        anime_year = txt
            img_tag = card.find('img')
            img_src = img_tag['src'] if img_tag and img_tag.get('src') else ''
            if anime_link:
                results.append({
                    'name': anime_name or '',
                    'url': clean_url(anime_link),
                    'type': anime_type,
                    'year': anime_year,
                    'image': img_src
                })
        except Exception as e:
            logger.warning(f"Parse card error: {e}")
    logger.info(f"Parsed {len(results)} search results")
    return results

def parse_pinned_cards(html):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    cards = soup.find_all('div', class_='pinned-card')
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
            results.append({
                'anime_name': anime_name or '',
                'anime_url': clean_url(anime_link) if anime_link else '',
                'episode_url': clean_url(ep_link) if ep_link else '',
                'episode_name': ep_name or '',
                'image': img_src or ''
            })
        except Exception as e:
            logger.warning(f"Parse pinned error: {e}")
    logger.info(f"Parsed {len(results)} pinned cards")
    return results

def get_episode_servers(episode_url):
    logger.info(f"Fetching servers: {episode_url}")
    url = clean_url(episode_url)
    resp = safe_request(url)
    if resp is None:
        return []
    soup = BeautifulSoup(resp.text, 'html.parser')
    servers = []

    server_list = soup.find('ul', class_='server-list')
    if not server_list:
        server_list = soup.find('div', class_='player-options')
    if not server_list:
        for div in soup.find_all('div'):
            cls = ' '.join(div.get('class', []))
            if 'option' in cls or 'server' in cls:
                server_list = div
                break

    if server_list:
        for a in server_list.find_all('a', attrs={'data-embed': True}):
            embed = a['data-embed']
            name_el = a.find('span', class_='server')
            if not name_el:
                spans = a.find_all('span')
                name_el = spans[-1] if spans else None
            name = name_el.get_text(strip=True) if name_el else a.get_text(strip=True)
            parsed = urllib.parse.urlparse(embed)
            rand_param = urllib.parse.parse_qs(parsed.query).get('random', [''])[0]
            servers.append({
                'name': name,
                'embed_url': clean_url(embed),
                'video_url': rand_param,
            })
    logger.info(f"Found {len(servers)} servers")
    return servers

def search_anime(query):
    logger.info(f"Search: {query}")
    url = f"{BASE_URL}/search/?s={urllib.parse.quote(query)}"
    resp = safe_request(url)
    if resp is None:
        return []
    return parse_search_results(resp.text)

def get_homepage_pinned():
    logger.info("Fetching homepage pinned")
    resp = safe_request(BASE_URL)
    if resp is None:
        return []
    return parse_pinned_cards(resp.text)

if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'pinned'
    if action == 'pinned':
        eps = get_homepage_pinned()
        print(f"Latest episodes: {len(eps)}")
        for ep in eps[:5]:
            print(f"  {ep['anime_name']} - {ep['episode_name']}")
    elif action == 'detail':
        url = sys.argv[2] if len(sys.argv) > 2 else 'https://animelek.top/anime/naruto/'
        d = get_anime_details(url)
        if d:
            print(f"Title: {d['title']}")
            print(f"Status: {d['status']}")
            print(f"Type: {d['type']}")
            print(f"Episodes: {d['episodes']}")
            print(f"Season: {d['season']}")
            print(f"Genres: {', '.join(d['genres'])}")
            print(f"Episodes list: {len(d['episodes_list'])} eps")
    elif action == 'search':
        query = sys.argv[2] if len(sys.argv) > 2 else 'naruto'
        results = search_anime(query)
        print(f"Search '{query}': {len(results)}")
        for r in results[:5]:
            print(f"  {r['name']} - {r['type']} {r['year']}")
