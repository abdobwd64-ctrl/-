#!/usr/bin/env python3
# scrape_all.py — ساحب كل الأنمي من AnimeLek.top ويرفع للمستودع
import sys, os, json, time, re, base64, urllib.parse, threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import logging
logging.getLogger('animelek').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from animelek_scraper import (
    BASE_URL, HEADERS, SESSION, safe_request, clean_url, extract_domain,
    get_homepage_pinned, search_anime, get_anime_details,
    get_episode_servers, get_episode_downloads
)

GH_TOKEN = os.environ.get('GH_TOKEN') or (sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith('ghp_') else '')
REPO = 'abdobwd64-ctrl/anime'
BRANCH = 'main'
DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, 'data')
DELAY = 0.5
WORKERS = 4

os.makedirs(DATA, exist_ok=True)
os.makedirs(os.path.join(DATA, 'anime'), exist_ok=True)

stats = {'discovered': 0, 'scraped': 0, 'failed': 0, 'total_eps': 0, 'total_servers': 0, 'total_dls': 0}
stats_lock = threading.Lock()

def log(msg): print(f"  {msg}")

def spinner(seq, label):
    for _ in seq:
        yield _

def discover_anime():
    log("🔍 مرحلة 1: اكتشاف الأنمي...")
    time.sleep(.5)
    known = {}

    from_home = get_homepage_pinned()
    for ep in from_home:
        if ep['anime_url']:
            known[ep['anime_url']] = ep['anime_name']
    log(f"  ✓ من الرئيسية: {len(known)} أنمي")

    terms = ['a','b','c','d','e','f','g','h','i','j','k','l','m','n','o','p','q','r','s','t','u','v','w','x','y','z']
    for t in terms:
        try:
            res = search_anime(t)
            for r in res:
                if r['url'] and r['url'] not in known:
                    known[r['url']] = r['name']
            time.sleep(.8)
        except:
            pass

    log(f"  ✓ بعد البحث: {len(known)} أنمي")
    stats['discovered'] = len(known)
    return [{'url': u, 'name': n} for u, n in known.items()]

def scrape_one(anime):
    """سحب أنمي واحد: تفاصيل + كل حلقاته + سيرفرات + تحميلات"""
    url = anime['url']
    name = anime['name']
    aid = url.rstrip('/').split('/')[-1]

    det = get_anime_details(url)
    if not det:
        with stats_lock: stats['failed'] += 1
        return None

    ep_list = det.get('episodes_list', [])
    eps_data = []
    total = len(ep_list)

    for idx, ep in enumerate(ep_list, 1):
        ep_num = ep.get('number', str(idx))
        ep_url = ep.get('url', '')
        if not ep_url:
            eps_data.append({'number': ep_num, 'title': ep.get('title', ''), 'date': '', 'servers': [], 'downloads': []})
            continue

        try:
            srv, pub_date = get_episode_servers(ep_url)
            dls = get_episode_downloads(ep_url)
        except:
            srv, pub_date, dls = [], '', []

        with stats_lock:
            stats['total_eps'] += 1
            stats['total_servers'] += len(srv)
            stats['total_dls'] += len(dls)

        eps_data.append({
            'number': ep_num,
            'title': ep.get('title', ''),
            'date': pub_date,
            'servers': [{'name': s['name'], 'embed_url': s['embed_url']} for s in srv],
            'downloads': [{'server': d['server'], 'quality': d['quality'], 'language': d['language'], 'url': d['url']} for d in dls],
        })

        # Progress per anime
        pct = idx / total * 100
        srv_cnt = len(srv)
        dl_cnt = len(dls)
        bar_len = 20
        filled = int(bar_len * idx / total)
        bar = '█' * filled + '░' * (bar_len - filled)
        print(f"\r     └─ حلقات [{bar}] {idx}/{total} ({pct:.0f}%) | {srv_cnt} سيرفر | {dl_cnt} تحميلة   ", end='', flush=True)

        time.sleep(DELAY)

    print()

    anime_data = {
        'id': aid,
        'title': det.get('title', name),
        'url': url,
        'poster': det.get('image', ''),
        'status': det.get('status', ''),
        'type': det.get('type', ''),
        'episodes_count': det.get('episodes', str(total)),
        'start_date': det.get('start_date', ''),
        'season': det.get('season', ''),
        'genres': det.get('genres', []),
        'story': det.get('story', ''),
        'episodes': eps_data,
        'last_updated': datetime.utcnow().isoformat(),
    }

    fp = os.path.join(DATA, 'anime', f'{aid}.json')
    with open(fp, 'w', encoding='utf-8') as f:
        json.dump(anime_data, f, ensure_ascii=False, indent=2)

    with stats_lock: stats['scraped'] += 1
    return anime_data

def save_indexes(all_data):
    log("\n💾 مرحلة 3: حفظ الفهارس...")

    latest = []
    popular = []
    index_list = []

    for ad in all_data:
        if not ad: continue
        info = {
            'id': ad['id'],
            'title': ad['title'],
            'poster': ad['poster'],
            'genres': ad.get('genres', []),
            'status': ad.get('status', ''),
            'type': ad.get('type', ''),
            'episodes_count': ad.get('episodes_count', '0'),
        }
        index_list.append(info)

        if ad.get('episodes'):
            latest_eps = sorted(ad['episodes'], key=lambda x: str(x.get('number', '0')), reverse=True)[:3]
            for ep in latest_eps:
                latest.append({
                    'anime_id': ad['id'],
                    'anime_title': ad['title'],
                    'anime_poster': ad['poster'],
                    'episode': ep['number'],
                    'date': ep.get('date', ''),
                    'url': f"{ad['url']}episode/{ep['number']}/",
                })

        score = len(ad.get('episodes', [])) + len(ad.get('genres', []))
        popular.append({**info, 'score': score})

    latest.sort(key=lambda x: x.get('date', ''), reverse=True)
    popular.sort(key=lambda x: x['score'], reverse=True)

    with open(os.path.join(DATA, 'latest.json'), 'w', encoding='utf-8') as f:
        json.dump(latest[:50], f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA, 'all-animes.json'), 'w', encoding='utf-8') as f:
        json.dump(index_list, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA, 'popular.json'), 'w', encoding='utf-8') as f:
        json.dump([{k:v for k,v in p.items() if k != 'score'} for p in popular[:30]], f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'total_anime': stats['scraped'],
            'total_episodes': stats['total_eps'],
            'total_servers': stats['total_servers'],
            'total_downloads': stats['total_dls'],
            'last_updated': datetime.utcnow().isoformat(),
        }, f, ensure_ascii=False, indent=2)

    log(f"  ✓ latest.json ({len(latest[:50])} حلقة)")
    log(f"  ✓ all-animes.json ({len(index_list)} أنمي)")
    log(f"  ✓ popular.json ({min(30,len(popular))} أنمي)")
    log(f"  ✓ meta.json")

def push_to_github():
    if not GH_TOKEN:
        log("\n⚠️  لا يوجد GitHub Token — تم الحفظ محلياً فقط")
        log("   عشان ترفع للمستودع: $env:GH_TOKEN=\"ghp_...\"")
        return

    log(f"\n📤 مرحلة 4: رفع إلى GitHub ...")
    headers = {'Authorization': f'token {GH_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    api = 'https://api.github.com'

    # 1. آخر commit
    ref_url = f'{api}/repos/{REPO}/git/refs/heads/{BRANCH}'
    ref_r = requests.get(ref_url, headers=headers)
    if ref_r.status_code != 200:
        log(f"  ✗ فشل الوصول للمستودع: {ref_r.status_code}")
        return
    latest_commit = ref_r.json()['object']['sha']
    log(f"  ✓ آخر commit: {latest_commit[:8]}")

    # 2. Base tree
    commit_url = f'{api}/repos/{REPO}/git/commits/{latest_commit}'
    base_tree = requests.get(commit_url, headers=headers).json()['tree']['sha']

    # 3. Blobs
    import base64
    files_to_push = []
    for root, dirs, files in os.walk(DATA):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, DIR).replace('\\', '/').lstrip('/')
            with open(full, 'rb') as f:
                raw = f.read()
            if rel.endswith('.webp'):
                files_to_push.append({'path': rel, 'content': base64.b64encode(raw).decode('ascii'), 'encoding': 'base64'})
            else:
                try:
                    text = raw.decode('utf-8')
                except UnicodeDecodeError:
                    text = raw.decode('cp1256', errors='replace')
                files_to_push.append({'path': rel, 'content': text, 'encoding': 'utf-8'})

    blobs = []
    for i, f in enumerate(files_to_push):
        blob_r = requests.post(f'{api}/repos/{REPO}/git/blobs',
            headers=headers, json={'content': f['content'], 'encoding': f['encoding']})
        if blob_r.status_code == 201:
            blobs.append({'path': f['path'], 'sha': blob_r.json()['sha'], 'mode': '100644', 'type': 'blob'})
        pct = (i+1)/len(files_to_push)*100
        bar = '█' * int(20*(i+1)/len(files_to_push)) + '░' * (20 - int(20*(i+1)/len(files_to_push)))
        print(f'\r     └─ أرفع ملفات [{bar}] {i+1}/{len(files_to_push)} ({pct:.0f}%)', end='', flush=True)
    print()

    # 4. New tree
    tree_r = requests.post(f'{api}/repos/{REPO}/git/trees',
        headers=headers, json={'base_tree': base_tree, 'tree': blobs})
    if tree_r.status_code != 201:
        log(f"  ✗ فشل إنشاء tree: {tree_r.status_code} {tree_r.text[:200]}")
        return
    new_tree_sha = tree_r.json()['sha']

    # 5. Commit
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    commit_r = requests.post(f'{api}/repos/{REPO}/git/commits',
        headers=headers, json={
            'message': f'🤖 تحديث بيانات الأنمي — {now}\n\n{stats["scraped"]} أنمي · {stats["total_eps"]} حلقة · {stats["total_servers"]} سيرفر · {stats["total_dls"]} تحميلة',
            'tree': new_tree_sha,
            'parents': [latest_commit],
        })
    if commit_r.status_code != 201:
        log(f"  ✗ فشل إنشاء commit: {commit_r.status_code}")
        return
    new_commit_sha = commit_r.json()['sha']

    # 6. Update branch
    update_r = requests.patch(f'{api}/repos/{REPO}/git/refs/heads/{BRANCH}',
        headers=headers, json={'sha': new_commit_sha, 'force': False})
    if update_r.status_code == 200:
        log(f"  ✅ رفع {len(files_to_push)} ملف في commit واحد — {new_commit_sha[:8]}")
    else:
        log(f"  ✗ فشل تحديث الفرع: {update_r.status_code}")

def main():
    print("\n" + "═" * 55)
    print("  🍥 AnimeLek Scraper v2.0 — ساحب كل الأنمي")
    print("═" * 55 + "\n")

    t_start = time.time()

    # Step 1: Discover
    animes = discover_anime()
    if not animes:
        log("✗ ما لقيت أي أنمي!")
        return

    # Step 2: Scrape
    log(f"\n📥 مرحلة 2: سحب {len(animes)} أنمي...\n")
    all_data = []
    for i, a in enumerate(animes, 1):
        pct = (i-1)/len(animes)*100
        bar = '█' * int(20*(i-1)/len(animes)) + '░' * (20 - int(20*(i-1)/len(animes)))
        print(f"\n  [{bar}] {i}/{len(animes)} ({pct:.0f}%) — {a['name'][:40]}")
        ad = scrape_one(a)
        if ad:
            all_data.append(ad)
        print(f"  ──── {stats['scraped']} تم ✓ | {stats['failed']} فشل ✗ | {stats['total_eps']} حلقة ────")

    # Step 3: Save
    save_indexes(all_data)

    # Step 4: Push
    push_to_github()

    elapsed = time.time() - t_start
    print("\n" + "═" * 55)
    print(f"  ✅ تم بنجاح!")
    print(f"     • {stats['scraped']} أنمي")
    print(f"     • {stats['total_eps']} حلقة")
    print(f"     • {stats['total_servers']} سيرفر")
    print(f"     • {stats['total_dls']} تحميلة")
    print(f"     • {elapsed/60:.1f} دقيقة")
    print("═" * 55 + "\n")

if __name__ == '__main__':
    main()
