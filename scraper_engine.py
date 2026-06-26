#!/usr/bin/env python3
# scraper_engine.py — محرك السحب المتقدم (يدعم Streamlit + CLI)
import sys, os, json, time, re, threading, logging, random, io
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# إسكات كل الـ logs المزعجة
for noisy in ['watchdog', 'urllib3', 'requests', 'PIL']:
    logging.getLogger(noisy).setLevel(logging.ERROR)

from animelek_scraper import (
    BASE_URL, HEADERS, SESSION, safe_request, clean_url, extract_domain,
    get_homepage_pinned, search_anime, get_anime_details,
    get_episode_servers, get_episode_downloads
)

DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, 'data')
DELAY = 0.5

class ScraperEngine:
    def __init__(self, gh_token='', parallel=3):
        self.gh_token = gh_token
        self.parallel = parallel
        self.phase = 'idle'
        self.discovered = 0
        self.current = 0
        self.total = 0
        self.current_name = ''
        self.done = 0
        self.failed = 0
        self.total_eps = 0
        self.total_servers = 0
        self.total_dls = 0
        self.ep_progress = 0
        self.ep_total = 0
        self.ep_servers = 0
        self.ep_dls = 0
        self.message = ''
        self._animes = []
        self._all_data = []
        self._lock = threading.Lock()
        self._stop = False
        self._thread = None
        self._dirty = set()
        self._dirty_lock = threading.Lock()
        self._error_count = 0
        self.start_time = None
        self.check_new_anime = 0
        self.check_new_eps = 0
        self.check_new_servers = 0
        self.check_skipped = 0

    @property
    def overall_pct(self):
        if self.phase == 'discover':
            return 0
        if self.phase == 'scrape' and self.total > 0:
            c = min(self.current, self.total)
            return (c / self.total) * 100
        if self.phase == 'save':
            return 95
        if self.phase in ('done', 'pushed'):
            return 100
        return 0

    @property
    def time_elapsed(self):
        if not self.start_time:
            return '—'
        s = int(time.time() - self.start_time)
        h, m = divmod(s, 3600)
        m, s = divmod(m, 60)
        if h:
            return f'{h}:{m:02d}:{s:02d}'
        return f'{m:02d}:{s:02d}'

    @property
    def eta(self):
        if self.phase != 'scrape' or self.current == 0 or self.total <= self.current:
            return '—'
        avg = (time.time() - self.start_time) / self.current
        remaining = int(avg * (self.total - self.current))
        h, m = divmod(remaining, 3600)
        m, s = divmod(m, 60)
        if h:
            return f'{h}:{m:02d}:{s:02d}'
        return f'{m:02d}:{s:02d}'

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self.start_time = time.time()
        self.phase = 'discover'
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def start_check(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self.start_time = time.time()
        self.phase = 'check'
        self._thread = threading.Thread(target=self._run_check, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True

    def _run(self):
        self.start_time = time.time()
        os.makedirs(DATA, exist_ok=True)
        os.makedirs(os.path.join(DATA, 'anime'), exist_ok=True)
        os.makedirs(os.path.join(DATA, 'posters'), exist_ok=True)

        try:
            self._sync_index_from_github()
            self._discover()
            if self._stop: return
            self._scrape_all()
            if self._stop: return
            self._save_indexes()
            if self._stop: return
            self._push_to_github()
            self.phase = 'pushed'
        except Exception as e:
            self.phase = 'error'
            self.message = str(e)
            print(f'[خطأ] {e}', file=sys.stderr)

    def _log_failed_anime(self, aid, name, url, error):
        fp = os.path.join(DATA, 'failed_anime.json')
        fails = []
        if os.path.exists(fp):
            try:
                fails = json.load(open(fp, encoding='utf-8'))
            except:
                fails = []
        fails.append({
            'id': aid, 'name': name, 'url': url,
            'error': str(error)[:200],
            'timestamp': datetime.utcnow().isoformat()
        })
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(fails, f, ensure_ascii=False, indent=2)
        self._mark_dirty(fp)
        self._push_failed_log()

    def _push_failed_log(self):
        fp = os.path.join(DATA, 'failed_anime.json')
        if not os.path.exists(fp):
            return
        if not self.gh_token:
            return
        headers = {'Authorization': f'token {self.gh_token}', 'Accept': 'application/vnd.github.v3+json'}
        api = 'https://api.github.com'
        repo = 'abdobwd64-ctrl/anime_scraper'
        branch = 'main'
        for attempt in range(3):
            try:
                ref = requests.get(f'{api}/repos/{repo}/git/refs/heads/{branch}', headers=headers).json()
                latest = ref['object']['sha']
                base = requests.get(f'{api}/repos/{repo}/git/commits/{latest}', headers=headers).json()['tree']['sha']
                import base64
                with open(fp, 'rb') as f:
                    raw = f.read()
                text = raw.decode('utf-8')
                br = requests.post(f'{api}/repos/{repo}/git/blobs',
                    headers=headers, json={'content': text, 'encoding': 'utf-8'})
                if br.status_code != 201:
                    raise Exception(f'blob: {br.status_code} {br.text[:100]}')
                tr = requests.post(f'{api}/repos/{repo}/git/trees',
                    headers=headers, json={'base_tree': base, 'tree': [{'path': 'data/failed_anime.json', 'sha': br.json()['sha'], 'mode': '100644', 'type': 'blob'}]})
                if tr.status_code != 201:
                    raise Exception(f'tree: {tr.status_code} {tr.text[:100]}')
                now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
                cr = requests.post(f'{api}/repos/{repo}/git/commits',
                    headers=headers, json={'message': f'تحديث سجل الأخطاء — {now}', 'tree': tr.json()['sha'], 'parents': [latest]})
                if cr.status_code != 201:
                    raise Exception(f'commit: {cr.status_code} {cr.text[:100]}')
                requests.patch(f'{api}/repos/{repo}/git/refs/heads/{branch}',
                    headers=headers, json={'sha': cr.json()['sha'], 'force': False})
                return
            except Exception as e:
                print(f'[فشل-سجل] {e}', file=sys.stderr)
                if '403' in str(e) and 'rate limit' in str(e).lower():
                    self.message = '⏳ حد API - انتظار 1.5 ساعة قبل رفع سجل الأخطاء...'
                    for _ in range(5400):
                        if self._stop: return
                        time.sleep(1)
                    continue
                return

    def _handle_github_error(self, e, action, headers, api, repo, branch):
        err_str = str(e)
        if '403' in err_str and ('rate limit' in err_str.lower() or 'API rate limit' in err_str):
            self.message = '⏳ تم تجاوز حد GitHub API — انتظار 1.5 ساعة...'
            print(f'[GitHub] Rate limit reached during {action}, waiting 90 minutes...', file=sys.stderr)
            for _ in range(5400):
                if self._stop:
                    return False
                time.sleep(1)
            print(f'[GitHub] Retrying {action} after rate limit wait...', file=sys.stderr)
            return True
        return False

    def _discover(self):
        self.phase = 'discover'
        self.message = 'جاري اكتشاف الأنمي...'
        known = {}

        anime_dir = os.path.join(DATA, 'anime')
        if os.path.isdir(anime_dir):
            for fn in os.listdir(anime_dir):
                if not fn.endswith('.json'):
                    continue
                ad = self._read_json_safe(os.path.join(anime_dir, fn))
                if ad:
                    known[ad.get('url', '')] = ad.get('title', fn[:-5])
            self.message = f'تم تحميل {len(known)} أنمي من الملفات المحلية'

        eps = get_homepage_pinned()
        for ep in eps:
            if ep['anime_url']:
                known[ep['anime_url']] = ep['anime_name']

        from animelek_scraper import get_anime_list_page, get_anime_list_page_count
        try:
            total_pages = get_anime_list_page_count()
            self.message = f'جاري سحب قائمة الأنمي من {total_pages} صفحة...'
            for p in range(1, total_pages + 1):
                if self._stop: return
                res = get_anime_list_page(p)
                for r in res:
                    if r['url'] and r['url'] not in known:
                        known[r['url']] = r.get('name', r['url'].rstrip('/').split('/')[-1])
                if p % 10 == 0:
                    self.message = f'صفحة {p}/{total_pages} — {len(known)} أنمي'
                time.sleep(0.1)
        except Exception as ex:
            print(f'[اكتشاف-خطأ] فشل سحب القائمة: {ex}', file=sys.stderr)

        self._animes = [{'url': u, 'name': n} for u, n in known.items()]
        random.shuffle(self._animes)
        self.discovered = len(self._animes)
        self.total = len(self._animes)
        self.message = f'تم اكتشاف {len(self._animes)} أنمي'

    def _scrape_all(self):
        self.phase = 'scrape'
        self.current = 0
        self.done = 0
        self.failed = 0
        def _scrape_wrapper(anime):
            if self._stop: return None
            with self._lock:
                self.current += 1
                self.current_name = anime['name'][:45]
            try:
                ad = self._scrape_one(anime)
                with self._lock:
                    if ad is None:
                        self.failed += 1
                        self._error_count += 1
                        self.message = f'❌ {anime["name"][:30]} فشل'
                        print(f'[فشل] {anime["name"][:30]}', file=sys.stderr)
                        aid = anime['url'].rstrip('/').split('/')[-1]
                        self._log_failed_anime(aid, anime['name'], anime['url'], 'فشل سحب التفاصيل')
                    elif ad == 'skipped':
                        self._error_count = 0
                        self.message = f'⏭ {anime["name"][:30]} مكتمل'
                    elif ad == 'poster_only':
                        self._error_count = 0
                        self.message = f'🖼 {anime["name"][:30]} بوستر'
                        self._push_incremental(f'🖼 بوستر — {anime["name"][:30]}')
                    else:
                        self._error_count = 0
                        self._all_data.append(ad)
                        self.done += 1
                        self.message = f'✅ {self.done}/{self.total}'
                return ad if isinstance(ad, dict) else None
            except Exception as e:
                with self._lock:
                    self.failed += 1
                    self._error_count += 1
                    self.message = f'فشل: {anime["name"][:30]} - {str(e)[:60]}'
                    print(f'[فشل] {anime["name"][:30]}: {e}', file=sys.stderr)
                    aid = anime['url'].rstrip('/').split('/')[-1]
                    self._log_failed_anime(aid, anime['name'], anime['url'], str(e))
                return None
        with ThreadPoolExecutor(max_workers=self.parallel) as executor:
            list(executor.map(_scrape_wrapper, self._animes))

    def _read_json_safe(self, path):
        for enc in ['utf-8', 'cp1256', 'latin-1']:
            try:
                with open(path, 'r', encoding=enc) as f:
                    return json.load(f)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        return None

    def _parse_arabic_date(self, date_str):
        if not date_str:
            return ''
        months = {
            'يناير':'01','فبراير':'02','مارس':'03','أبريل':'04','إبريل':'04',
            'مايو':'05','يونيو':'06','يوليو':'07','أغسطس':'08','غشت':'08',
            'سبتمبر':'09','أكتوبر':'10','نوفمبر':'11','ديسمبر':'12',
        }
        import re
        m = re.match(r'(\d+)\s+([^,\s]+),?\s*(\d+)', date_str)
        if m:
            day, month_ar, year = m.group(1), m.group(2), m.group(3)
            month_num = months.get(month_ar, '01')
            return f'{year}-{month_num}-{int(day):02d}'
        return date_str

    def _update_indexes(self):
        latest, popular, index_list = [], [], []
        anime_dir = os.path.join(DATA, 'anime')
        if not os.path.isdir(anime_dir):
            return
        for fn in os.listdir(anime_dir):
            if not fn.endswith('.json'):
                continue
            ad = self._read_json_safe(os.path.join(anime_dir, fn))
            if not ad:
                continue
            info = {
                'id': ad.get('id', ''), 'title': ad.get('title', ''),
                'poster': ad.get('poster', ''),
                'genres': ad.get('genres', []), 'status': ad.get('status', ''),
                'type': ad.get('type', ''), 'episodes_count': ad.get('episodes_count', '0'),
                'season': ad.get('season', ''),
            }
            index_list.append(info)
            if ad.get('episodes'):
                valid_eps = [ep for ep in ad['episodes'] if str(ep.get('number', '')).isdigit()]
                sorted_eps = sorted(valid_eps,
                    key=lambda x: self._parse_arabic_date(x.get('date', '')), reverse=True)[:5]
                for ep in sorted_eps:
                    d = ep.get('date', '')
                    sa = ep.get('saved_at', '')
                    latest.append({
                        'anime_id': ad['id'], 'anime_title': ad['title'],
                        'anime_poster': ad['poster'], 'episode': ep['number'],
                        'date': d,
                        'date_sort': self._parse_arabic_date(d),
                        'saved_at': sa,
                    })
            score = len(ad.get('episodes', [])) + len(ad.get('genres', []))
            popular.append({**info, 'score': score})

        latest.sort(key=lambda x: (x.get('date_sort', ''), x.get('saved_at', '')), reverse=True)
        popular.sort(key=lambda x: x['score'], reverse=True)

        total_eps = sum(len(p.get('episodes', [])) for p in index_list) if False else 0
        for fn in os.listdir(anime_dir):
            if not fn.endswith('.json'): continue
            ad = self._read_json_safe(os.path.join(anime_dir, fn))
            if ad:
                total_eps += len(ad.get('episodes', []))
        for name, data in [
            ('latest.json', latest[:50]),
            ('all-animes.json', index_list),
            ('popular.json', [p for p in popular[:30]]),
            ('meta.json', {
                'total_anime': len(index_list), 'total_episodes': total_eps,
                'last_updated': datetime.utcnow().isoformat(),
            }),
        ]:
            try:
                with open(os.path.join(DATA, name), 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except:
                pass

    def _mark_dirty(self, file_path):
        rp = os.path.relpath(file_path, DIR).replace('\\', '/')
        with self._dirty_lock:
            self._dirty.add(rp)

    def _sync_index_from_github(self):
        if not self.gh_token:
            return
        headers = {'Authorization': f'token {self.gh_token}', 'Accept': 'application/vnd.github.v3+json'}
        repo = 'abdobwd64-ctrl/anime'
        branch = 'main'
        raw_base = f'https://raw.githubusercontent.com/{repo}/{branch}'
        os.makedirs(os.path.join(DATA, 'anime'), exist_ok=True)
        # 1. Download all-animes.json to know what exists remotely
        r = requests.get(f'{raw_base}/data/all-animes.json', headers=headers)
        remote_ids = set()
        if r.status_code == 200:
            try:
                remote_list = r.json()
                remote_ids = {x['id'] for x in remote_list if x.get('id')}
            except:
                remote_list = []
            local_list_path = os.path.join(DATA, 'all-animes.json')
            if os.path.exists(local_list_path):
                try:
                    local_list = json.load(open(local_list_path, encoding='utf-8'))
                    local_ids = {x['id'] for x in local_list if x.get('id')}
                except:
                    local_list, local_ids = [], set()
            else:
                local_list, local_ids = [], set()
            merged = []
            seen = set()
            for item in local_list + remote_list:
                iid = item.get('id')
                if iid and iid not in seen:
                    seen.add(iid)
                    merged.append(item)
            with open(local_list_path, 'w', encoding='utf-8') as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
        # 2. Download anime JSON files that don't exist locally
        for rid in remote_ids:
            local_fp = os.path.join(DATA, 'anime', f'{rid}.json')
            if not os.path.exists(local_fp):
                ar = requests.get(f'{raw_base}/data/anime/{rid}.json', headers=headers)
                if ar.status_code == 200:
                    try:
                        with open(local_fp, 'w', encoding='utf-8') as f:
                            f.write(ar.text)
                    except Exception as ex_d:
                        print(f'[مزامنة-خطأ] {rid}: {ex_d}', file=sys.stderr)
        # 3. Sync remaining index files
        for name in ('latest.json', 'popular.json', 'meta.json'):
            r = requests.get(f'{raw_base}/data/{name}', headers=headers)
            if r.status_code == 200:
                local = os.path.join(DATA, name)
                try:
                    existing = json.load(open(local, encoding='utf-8')) if os.path.exists(local) else []
                except:
                    existing = []
                try:
                    remote = r.json()
                except:
                    continue
                if isinstance(remote, list) and isinstance(existing, list):
                    existing_ids = {x.get('id') or x.get('anime_id') for x in existing}
                    merged = list(existing)
                    for item in remote:
                        item_id = item.get('id') or item.get('anime_id')
                        if item_id and item_id not in existing_ids:
                            merged.append(item)
                            existing_ids.add(item_id)
                    with open(local, 'w', encoding='utf-8') as f:
                        json.dump(merged, f, ensure_ascii=False, indent=2)
                elif isinstance(remote, dict) and isinstance(existing, dict):
                    if not existing.get('total_anime', 0) or remote.get('total_anime', 0) > existing.get('total_anime', 0):
                        with open(local, 'w', encoding='utf-8') as f:
                            json.dump(remote, f, ensure_ascii=False, indent=2)

    def _push_incremental(self, msg):
        if not self.gh_token:
            return
        self._sync_index_from_github()
        self._update_indexes()
        with self._dirty_lock:
            for idx_name in ('latest.json', 'all-animes.json', 'popular.json', 'meta.json'):
                self._dirty.add(f'data/{idx_name}')
        headers = {'Authorization': f'token {self.gh_token}', 'Accept': 'application/vnd.github.v3+json'}
        api = 'https://api.github.com'
        repo = 'abdobwd64-ctrl/anime'
        branch = 'main'

        for _ in range(3):
            try:
                ref = requests.get(f'{api}/repos/{repo}/git/refs/heads/{branch}', headers=headers).json()
                latest = ref['object']['sha']
                base = requests.get(f'{api}/repos/{repo}/git/commits/{latest}', headers=headers).json()['tree']['sha']

                import base64
                with self._dirty_lock:
                    dirty_snapshot = sorted(self._dirty)
                    self._dirty.clear()
                files = []
                for rel in dirty_snapshot:
                    full = os.path.join(DIR, rel)
                    if not os.path.exists(full):
                        continue
                    with open(full, 'rb') as f:
                        raw = f.read()
                    rel_clean = rel.lstrip('/')
                    if rel_clean != rel:
                        print(f'WARN: stripped leading slash: {rel} -> {rel_clean}', file=sys.stderr)
                    if rel_clean.endswith('.webp'):
                        content_b64 = base64.b64encode(raw).decode('ascii')
                        files.append({'path': rel_clean, 'content': content_b64, 'encoding': 'base64'})
                    else:
                        try:
                            text = raw.decode('utf-8')
                        except UnicodeDecodeError:
                            text = raw.decode('cp1256', errors='replace')
                        files.append({'path': rel_clean, 'content': text, 'encoding': 'utf-8'})

                if not files:
                    self.message = '⚠️ لا توجد ملفات جديدة للرفع'
                    self._error_count = 0
                    return

                blobs = []
                for f in files:
                    br = requests.post(f'{api}/repos/{repo}/git/blobs',
                        headers=headers, json={'content': f['content'], 'encoding': f['encoding']})
                    if br.status_code != 201:
                        raise Exception(f'blob {f["path"]}: {br.status_code} {br.text[:100]}')
                    blobs.append({'path': f['path'], 'sha': br.json()['sha'], 'mode': '100644', 'type': 'blob'})

                tr = requests.post(f'{api}/repos/{repo}/git/trees',
                    headers=headers, json={'base_tree': base, 'tree': blobs})
                if tr.status_code != 201:
                    paths = [b['path'] for b in blobs]
                    raise Exception(f'tree: {tr.status_code} {tr.text[:300]} | paths: {paths[:10]}')
                now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
                cr = requests.post(f'{api}/repos/{repo}/git/commits',
                    headers=headers, json={
                        'message': f'{msg} — {now}',
                        'tree': tr.json()['sha'], 'parents': [latest],
                    })
                if cr.status_code != 201:
                    raise Exception(f'commit: {cr.status_code} {cr.text[:100]}')
                requests.patch(f'{api}/repos/{repo}/git/refs/heads/{branch}',
                    headers=headers, json={'sha': cr.json()['sha'], 'force': False})
                self._error_count = 0
                return
            except Exception as e:
                print(f'[رفع-خطأ] {e}', file=sys.stderr)
                if self._handle_github_error(e, 'push_incremental', headers, api, repo, branch):
                    continue
                self.message = f'خطأ في الرفع: {e}'
                self._error_count += 1
                break

    def _download_poster(self, aid, poster_url):
        if not poster_url or not poster_url.startswith('http'):
            return poster_url
        local = os.path.join(DATA, 'posters', f'{aid}.webp')
        if os.path.exists(local):
            try:
                Image.open(local).verify()
                return f'data/posters/{aid}.webp'
            except:
                os.remove(local)
        try:
            r = requests.get(poster_url, timeout=15)
            img = Image.open(io.BytesIO(r.content))
            img.save(local, 'WEBP', quality=85)
            return f'data/posters/{aid}.webp'
        except:
            return poster_url

    def _scrape_one(self, anime):
        url = anime['url']
        name = anime['name']
        aid = url.rstrip('/').split('/')[-1]
        fp = os.path.join(DATA, 'anime', f'{aid}.json')
        poster_fp = os.path.join(DATA, 'posters', f'{aid}.webp')

        # تحميل البيانات القديمة إن وجدت
        old_data = None
        existing_eps = {}
        poster_ok = os.path.exists(poster_fp)
        if os.path.exists(fp):
            old_data = self._read_json_safe(fp)
            if old_data:
                for ep in old_data.get('episodes', []):
                    existing_eps[str(ep.get('number', ''))] = ep
            else:
                existing_eps = {}

        # سحب صفحة التفاصيل
        det = get_anime_details(url)
        if not det:
            return None

        ep_list = det.get('episodes_list', [])
        total_on_site = len(ep_list)
        total_old = len(existing_eps)
        self.ep_total = total_on_site

        poster_url = det.get('image', '')

        # ذكي: لو كل حاجه موجودة → تخطي
        if total_old >= total_on_site and poster_ok and old_data:
            self.message = f'⏭ {name}: مكتمل ({total_old} حلقة + WebP)'
            return 'skipped'

        # ذكي: لو الصورة بس ناقصة → نزلها وخلاص
        if total_old >= total_on_site and not poster_ok and old_data:
            poster_local = self._download_poster(aid, poster_url)
            old_data['poster'] = poster_local
            old_data['last_updated'] = datetime.utcnow().isoformat()
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(old_data, f, ensure_ascii=False, indent=2)
            self._mark_dirty(fp)
            if os.path.exists(poster_fp):
                self._mark_dirty(poster_fp)
            self.message = f'🖼 {name}: تم تحديث البوستر'
            return 'poster_only'

        # سحب كامل أو استئناف
        eps_data = []
        for ep in old_data.get('episodes', []) if old_data else []:
            eps_data.append(ep)
        self.ep_progress = len(eps_data)

        to_scrape = []
        for idx, ep in enumerate(ep_list, 1):
            if self._stop: return None
            ep_num = str(ep.get('number', str(idx)))
            if ep_num in existing_eps:
                continue
            ep_url = ep.get('url', '')
            to_scrape.append((ep_num, ep, ep_url))

        if to_scrape:
            with ThreadPoolExecutor(max_workers=self.parallel) as ex:
                def _scrape_ep(ep_num, ep, ep_url):
                    now = datetime.utcnow().isoformat()
                    if not ep_url:
                        return {'number': ep_num, 'title': ep.get('title', ''), 'date': '', 'servers': [], 'downloads': [], 'saved_at': now}
                    try:
                        srv, pub_date = get_episode_servers(ep_url)
                        dls = get_episode_downloads(ep_url)
                    except:
                        srv, pub_date, dls = [], '', []
                    with self._lock:
                        self.total_eps += 1
                        self.total_servers += len(srv)
                        self.total_dls += len(dls)
                    self.ep_servers = len(srv)
                    self.ep_dls = len(dls)
                    return {
                        'number': ep_num,
                        'title': ep.get('title', ''),
                        'date': pub_date,
                        'servers': [{'name': s['name'], 'embed_url': s['embed_url']} for s in srv],
                        'downloads': [{'server': d['server'], 'quality': d['quality'],
                                        'language': d['language'], 'url': d['url']} for d in dls],
                        'saved_at': now,
                    }
                for i, f in enumerate(as_completed([ex.submit(_scrape_ep, num, e, u) for num, e, u in to_scrape])):
                    eps_data.append(f.result())
                    self.ep_progress = len(eps_data)

        anime_data = {
            'id': aid, 'title': det.get('title', name), 'url': url,
            'poster': self._download_poster(aid, poster_url),
            'status': det.get('status', ''), 'type': det.get('type', ''),
            'episodes_count': det.get('episodes', str(total_on_site)),
            'start_date': det.get('start_date', ''), 'season': det.get('season', ''),
            'genres': det.get('genres', []), 'story': det.get('story', ''),
            'episodes': eps_data,
            'last_updated': datetime.utcnow().isoformat(),
        }
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(anime_data, f, ensure_ascii=False, indent=2)
        self._mark_dirty(fp)
        if os.path.exists(poster_fp):
            self._mark_dirty(poster_fp)
        return anime_data

    def _check_new(self, entries):
        """Check a batch of pinned entries: scrape any new anime/episodes/servers."""
        from animelek_scraper import get_episode_servers, get_episode_downloads
        new_anime = 0
        new_eps = 0
        new_servers = 0
        for ep in entries:
            if self._stop:
                return
            anime_url = ep.get('anime_url', '')
            ep_url = ep.get('episode_url', '')
            if not anime_url:
                continue
            aid = anime_url.rstrip('/').split('/')[-1]
            fp = os.path.join(DATA, 'anime', f'{aid}.json')
            old_data = None
            existing_eps = {}
            if os.path.exists(fp):
                old_data = self._read_json_safe(fp)
                if old_data:
                    for e in old_data.get('episodes', []):
                        existing_eps[str(e.get('number', ''))] = e
            ep_num = ''
            if '/episode/' in ep_url:
                m = re.search(r'(\d+)(?:/\s*|$)', ep.get('episode_name', ''))
                if m:
                    ep_num = m.group(1)
                else:
                    import urllib.parse
                    decoded = urllib.parse.unquote(ep_url.rstrip('/').rsplit('-', 1)[-1])
                    m2 = re.search(r'(\d+)', decoded)
                    if m2:
                        ep_num = m2.group(1)
            if not old_data:
                ad = self._scrape_one({'url': anime_url, 'name': ep.get('anime_name', aid)})
                if ad and isinstance(ad, dict):
                    new_anime += 1
                    self.check_new_anime += 1
                    self._all_data.append(ad)
                    self.done += 1
                    continue
                ep_num = ''
                if '/episode/' in ep_url:
                    m = re.search(r'(\d+)(?:/\s*|$)', ep.get('episode_name', ''))
                    if m:
                        ep_num = m.group(1)
                    else:
                        import urllib.parse
                        decoded = urllib.parse.unquote(ep_url.rstrip('/').rsplit('-', 1)[-1])
                        m2 = re.search(r'(\d+)', decoded)
                        if m2:
                            ep_num = m2.group(1)
                try:
                    srv, pub_date = get_episode_servers(ep_url)
                    dls = get_episode_downloads(ep_url)
                    if not srv and not dls:
                        continue
                    poster_local = self._download_poster(aid, ep.get('image', ''))
                    poster_fp_check = os.path.join(DATA, 'posters', f'{aid}.webp')
                    if os.path.exists(poster_fp_check):
                        self._mark_dirty(poster_fp_check)
                    new_ad = {
                        'id': aid,
                        'title': ep.get('anime_name', ep.get('episode_name', aid)),
                        'url': anime_url,
                        'poster': poster_local,
                        'status': '', 'type': '', 'episodes_count': '1',
                        'start_date': '', 'season': '', 'genres': [], 'story': '',
                        'episodes': [{
                            'number': ep_num,
                            'title': ep.get('episode_name', ''),
                            'date': pub_date,
                            'servers': [{'name': s['name'], 'embed_url': s['embed_url']} for s in srv],
                            'downloads': [{'server': d['server'], 'quality': d['quality'],
                                            'language': d['language'], 'url': d['url']} for d in dls],
                            'saved_at': datetime.utcnow().isoformat(),
                        }],
                        'last_updated': datetime.utcnow().isoformat(),
                    }
                    with open(fp, 'w', encoding='utf-8') as f:
                        json.dump(new_ad, f, ensure_ascii=False, indent=2)
                    self._mark_dirty(fp)
                    new_anime += 1
                    self.check_new_anime += 1
                    self.message = f'🆕 أنمي جديد: {new_ad["title"]}'
                except Exception as ex:
                    self._error_count += 1
                    print(f'[فحص-خطأ] أنمي جديد: {ep.get("anime_name", aid)}: {ex}', file=sys.stderr)
                    continue
            if ep_num and ep_num not in existing_eps:
                try:
                    srv, pub_date = get_episode_servers(ep_url)
                    dls = get_episode_downloads(ep_url)
                    if not srv and not dls:
                        continue
                    old_data['episodes'].append({
                        'number': ep_num,
                        'title': ep.get('episode_name', ''),
                        'date': pub_date,
                        'servers': [{'name': s['name'], 'embed_url': s['embed_url']} for s in srv],
                        'downloads': [{'server': d['server'], 'quality': d['quality'],
                                        'language': d['language'], 'url': d['url']} for d in dls],
                        'saved_at': datetime.utcnow().isoformat(),
                    })
                    old_data['last_updated'] = datetime.utcnow().isoformat()
                    with open(fp, 'w', encoding='utf-8') as f:
                        json.dump(old_data, f, ensure_ascii=False, indent=2)
                    self._mark_dirty(fp)
                    new_eps += 1
                    self.check_new_eps += 1
                    self.message = f'🆕 حلقة جديدة: {old_data.get("title",aid)} - الحلقة {ep_num}'
                except Exception as ex2:
                    self._error_count += 1
                    print(f'[فحص-خطأ] حلقة جديدة: {old_data.get("title",aid)} حلقة {ep_num}: {ex2}', file=sys.stderr)
                    continue
            elif ep_num and ep_num in existing_eps:
                old_servers = existing_eps[ep_num].get('servers', [])
                old_count = len(old_servers)
                try:
                    srv, pub_date = get_episode_servers(ep_url)
                    if len(srv) > old_count:
                        existing_eps[ep_num]['servers'] = [
                            {'name': s['name'], 'embed_url': s['embed_url']} for s in srv
                        ]
                        if pub_date:
                            existing_eps[ep_num]['date'] = pub_date
                        old_data['last_updated'] = datetime.utcnow().isoformat()
                        with open(fp, 'w', encoding='utf-8') as f:
                            json.dump(old_data, f, ensure_ascii=False, indent=2)
                        self._mark_dirty(fp)
                        new_servers += 1
                        self.check_new_servers += 1
                        self.message = f'🆕 سيرفر جديد: {old_data.get("title",aid)} - الحلقة {ep_num}'
                    else:
                        self.check_skipped += 1
                except Exception as ex3:
                    self._error_count += 1
                    print(f'[فحص-خطأ] سيرفر: {old_data.get("title",aid)} حلقة {ep_num}: {ex3}', file=sys.stderr)
                    pass
            time.sleep(0.15)
        self._push_incremental(f'🔄 فحص: {new_anime} أنمي + {new_eps} حلقة + {new_servers} سيرفر')

    def _run_check(self):
        """Periodically check latest episodes every 30 minutes."""
        from animelek_scraper import get_latest_episodes_page
        self.start_time = time.time()
        os.makedirs(DATA, exist_ok=True)
        os.makedirs(os.path.join(DATA, 'anime'), exist_ok=True)
        os.makedirs(os.path.join(DATA, 'posters'), exist_ok=True)
        self.phase = 'check'
        self._error_count = 0
        self.check_new_anime = 0
        self.check_new_eps = 0
        self.check_new_servers = 0
        self.check_skipped = 0
        while not self._stop:
            try:
                self.message = '🔍 جاري فحص الحلقات الجديدة...'
                all_eps = get_latest_episodes_page()
                if all_eps:
                    self._error_count = 0
                    self.check_new_anime = 0
                    self.check_new_eps = 0
                    self.check_new_servers = 0
                    self.check_skipped = 0
                    total = len(all_eps)
                    self.total = total
                    self.current = 0
                    for start in range(0, total, 5):
                        if self._stop:
                            return
                        batch = all_eps[start:start+5]
                        self.current = start + len(batch)
                        self.message = f'🔎 فحص {start+1}-{min(start+5,total)} من {total} | 🆕ج:{self.check_new_anime} 🆕ح:{self.check_new_eps} 🆕س:{self.check_new_servers} ✅ك:{self.check_skipped}'
                        self._check_new(batch)
                    self.message = f'✅ تم فحص {total} حلقة | 🆕 أنمي: {self.check_new_anime} | 🆕 حلقات: {self.check_new_eps} | 🆕 سيرفرات: {self.check_new_servers} | ✅ موجود: {self.check_skipped}'
                else:
                    self._error_count += 1
                    self.message = f'⚠️ لا توجد حلقات جديدة ({self._error_count})'
                    print(f'[فحص-تحذير] لا توجد حلقات جديدة ({self._error_count})', file=sys.stderr)
            except Exception as e:
                self._error_count += 1
                self.message = f'خطأ في الفحص ({self._error_count}): {e}'
                print(f'[فحص-خطأ] {e}', file=sys.stderr)
            if self._stop:
                break
            self.message = '⏳ انتظار 30 دقيقة للفحص التالي...'
            for _ in range(1800):
                if self._stop:
                    break
                time.sleep(1)
        self.phase = 'idle'
        self.message = 'تم إيقاف الفحص الدوري'

    def _save_indexes(self):
        self.phase = 'save'
        self.message = 'جاري حفظ الفهارس...'

        latest, popular, index_list = [], [], []
        for ad in self._all_data:
            if not ad: continue
            info = {
                'id': ad['id'], 'title': ad['title'], 'poster': ad['poster'],
                'genres': ad.get('genres', []), 'status': ad.get('status', ''),
                'type': ad.get('type', ''), 'episodes_count': ad.get('episodes_count', '0'),
            }
            index_list.append(info)
            if ad.get('episodes'):
                def _parse(d):
                    if not d: return ''
                    import re
                    months = {'يناير':'01','فبراير':'02','مارس':'03','أبريل':'04','إبريل':'04','مايو':'05','يونيو':'06','يوليو':'07','أغسطس':'08','غشت':'08','سبتمبر':'09','أكتوبر':'10','نوفمبر':'11','ديسمبر':'12'}
                    m = re.match(r'(\d+)\s+([^,\s]+),?\s*(\d+)', d)
                    if m: return f'{m.group(3)}-{months.get(m.group(2),"01")}-{int(m.group(1)):02d}'
                    return ''
                valid_eps = [ep for ep in ad['episodes'] if str(ep.get('number', '')).isdigit()]
                latest_eps = sorted(valid_eps,
                    key=lambda x: _parse(x.get('date', '')), reverse=True)[:5]
                for ep in latest_eps:
                    d = ep.get('date', '')
                    sa = ep.get('saved_at', '')
                    latest.append({
                        'anime_id': ad['id'], 'anime_title': ad['title'],
                        'anime_poster': ad['poster'], 'episode': ep['number'],
                        'date': d,
                        'date_sort': _parse(d),
                        'saved_at': sa,
                    })
            score = len(ad.get('episodes', [])) + len(ad.get('genres', []))
            popular.append({**info, 'score': score})

        latest.sort(key=lambda x: (x.get('date_sort', ''), x.get('saved_at', '')), reverse=True)
        popular.sort(key=lambda x: x['score'], reverse=True)

        for name, data in [
            ('latest.json', latest[:50]),
            ('all-animes.json', index_list),
            ('popular.json', [p for p in popular[:30]]),
            ('meta.json', {
                'total_anime': self.done, 'total_episodes': self.total_eps,
                'total_servers': self.total_servers, 'total_downloads': self.total_dls,
                'last_updated': datetime.utcnow().isoformat(),
            }),
        ]:
            with open(os.path.join(DATA, name), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _push_to_github(self):
        if not self.gh_token:
            self.message = '⚠️ لا يوجد GitHub Token — البيانات محفوظة محلياً فقط'
            self.phase = 'done'
            return

        self._sync_index_from_github()
        self._update_indexes()
        
        headers = {'Authorization': f'token {self.gh_token}', 'Accept': 'application/vnd.github.v3+json'}
        api = 'https://api.github.com'
        repo = 'abdobwd64-ctrl/anime'
        branch = 'main'

        for attempt in range(3):
            self.message = f'🔄 رفع إلى GitHub...'
            try:
                ref_r = requests.get(f'{api}/repos/{repo}/git/refs/heads/{branch}', headers=headers)
                if ref_r.status_code != 200:
                    if self._handle_github_error(Exception(f'{ref_r.status_code} {ref_r.text[:100]}'), 'push_ref', headers, api, repo, branch):
                        continue
                    self.message = f'فشل الوصول للمستودع: {ref_r.status_code}'
                    self.phase = 'done'
                    return
                latest_commit = ref_r.json()['object']['sha']

                commit_r = requests.get(f'{api}/repos/{repo}/git/commits/{latest_commit}', headers=headers)
                base_tree = commit_r.json()['tree']['sha']

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

                if not files_to_push:
                    self.message = '⚠️ لا توجد ملفات للرفع'
                    self.phase = 'done'
                    return

                blobs = []
                for f in files_to_push:
                    blob_r = requests.post(f'{api}/repos/{repo}/git/blobs',
                        headers=headers, json={'content': f['content'], 'encoding': f['encoding']})
                    if blob_r.status_code != 201:
                        raise Exception(f'blob {f["path"]}: {blob_r.status_code} {blob_r.text[:100]}')
                    blobs.append({'path': f['path'], 'sha': blob_r.json()['sha'],
                                  'mode': '100644', 'type': 'blob'})

                tree_r = requests.post(f'{api}/repos/{repo}/git/trees',
                    headers=headers, json={'base_tree': base_tree, 'tree': blobs})
                if tree_r.status_code != 201:
                    paths = [b['path'] for b in blobs[:10]]
                    self.message = f'فشل إنشاء tree: {tree_r.status_code} {tree_r.text[:200]} | paths: {paths}'
                    self.phase = 'done'
                    return

                now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
                commit_r = requests.post(f'{api}/repos/{repo}/git/commits',
                    headers=headers, json={
                        'message': f'🤖 تحديث بيانات الأنمي — {now}\n\n{self.done} أنمي · {self.total_eps} حلقة',
                        'tree': tree_r.json()['sha'], 'parents': [latest_commit],
                    })
                if commit_r.status_code != 201:
                    if self._handle_github_error(Exception(f'commit {commit_r.status_code} {commit_r.text[:100]}'), 'push_commit', headers, api, repo, branch):
                        continue
                    self.message = f'فشل إنشاء commit'
                    self.phase = 'done'
                    return

                requests.patch(f'{api}/repos/{repo}/git/refs/heads/{branch}',
                    headers=headers, json={'sha': commit_r.json()['sha'], 'force': False})
                self.message = f'✅ تم رفع {len(files_to_push)} ملف إلى GitHub'
                self.phase = 'pushed'
                return
            except Exception as e:
                print(f'[رفع-خطأ] {e}', file=sys.stderr)
                if self._handle_github_error(e, 'push_to_github', headers, api, repo, branch):
                    continue
                self.message = f'خطأ في الرفع: {e}'
                self.phase = 'error'
                return
