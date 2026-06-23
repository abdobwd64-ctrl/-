#!/usr/bin/env python3
# scraper_engine.py — محرك السحب المتقدم (يدعم Streamlit + CLI)
import sys, os, json, time, re, threading, logging, random
from datetime import datetime
import requests

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
    def __init__(self, gh_token=''):
        self.gh_token = gh_token
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
        self._stop = False
        self._thread = None

    @property
    def overall_pct(self):
        if self.phase == 'discover':
            return 0
        if self.phase == 'scrape' and self.total > 0:
            return (self.current / self.total) * 100
        if self.phase == 'save':
            return 95
        if self.phase in ('done', 'pushed'):
            return 100
        return 0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True

    def _run(self):
        os.makedirs(DATA, exist_ok=True)
        os.makedirs(os.path.join(DATA, 'anime'), exist_ok=True)

        try:
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

    def _discover(self):
        self.phase = 'discover'
        self.message = 'جاري اكتشاف الأنمي...'
        known = {}

        eps = get_homepage_pinned()
        for ep in eps:
            if ep['anime_url']:
                known[ep['anime_url']] = ep['anime_name']

        terms = ['a','b','c','d','e','f','g','h','i','j','k','l','m',
                 'n','o','p','q','r','s','t','u','v','w','x','y','z',
                 'one','two','king','love','world','death','naruto','dragon',
                 'gate','time','star','black','blue','red','white']
        for t in terms:
            if self._stop: return
            try:
                res = search_anime(t)
                for r in res:
                    if r['url'] and r['url'] not in known:
                        known[r['url']] = r['name']
                time.sleep(0.5)
            except:
                pass

        self._animes = [{'url': u, 'name': n} for u, n in known.items()]
        random.shuffle(self._animes)
        self.discovered = len(self._animes)
        self.total = len(self._animes)
        self.message = f'تم اكتشاف {len(self._animes)} أنمي'

    def _scrape_all(self):
        self.phase = 'scrape'
        self.current = 0
        for i, anime in enumerate(self._animes, 1):
            if self._stop: return
            self.current = i
            self.current_name = anime['name'][:45]
            self.message = f'({i}/{self.total}) {self.current_name}'
            try:
                ad = self._scrape_one(anime)
                if ad:
                    self._all_data.append(ad)
                    self.done += 1
            except Exception as e:
                self.failed += 1
                self.message = f'فشل: {anime["name"][:30]} - {str(e)[:60]}'
            time.sleep(DELAY)

    def _push_incremental(self, msg):
        if not self.gh_token:
            return
        self.message = f'🔄 رفع إلى GitHub...'
        headers = {'Authorization': f'token {self.gh_token}', 'Accept': 'application/vnd.github.v3+json'}
        api = 'https://api.github.com'
        repo = 'abdobwd64-ctrl/anime'
        branch = 'main'

        try:
            ref = requests.get(f'{api}/repos/{repo}/git/refs/heads/{branch}', headers=headers).json()
            latest = ref['object']['sha']
            base = requests.get(f'{api}/repos/{repo}/git/commits/{latest}', headers=headers).json()['tree']['sha']

            files = {}
            for root, dirs, fs in os.walk(DATA):
                for fn in fs:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, DIR).replace('\\', '/')
                    with open(full, 'rb') as f:
                        files[rel] = f.read().decode('utf-8')

            blobs = []
            for path, content in files.items():
                r = requests.post(f'{api}/repos/{repo}/git/blobs',
                    headers=headers, json={'content': content, 'encoding': 'utf-8'}).json()
                blobs.append({'path': path, 'sha': r['sha'], 'mode': '100644', 'type': 'blob'})

            tree = requests.post(f'{api}/repos/{repo}/git/trees',
                headers=headers, json={'base_tree': base, 'tree': blobs}).json()
            now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
            cm = requests.post(f'{api}/repos/{repo}/git/commits',
                headers=headers, json={
                    'message': f'{msg} — {now}',
                    'tree': tree['sha'], 'parents': [latest],
                }).json()
            requests.patch(f'{api}/repos/{repo}/git/refs/heads/{branch}',
                headers=headers, json={'sha': cm['sha'], 'force': False})
        except:
            pass

    def _scrape_one(self, anime):
        url = anime['url']
        name = anime['name']
        aid = url.rstrip('/').split('/')[-1]
        fp = os.path.join(DATA, 'anime', f'{aid}.json')

        # تحقق إذا كان الأنمي مسحوب قبل كده
        existing_eps = {}
        if os.path.exists(fp):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    old = json.load(f)
                for ep in old.get('episodes', []):
                    existing_eps[str(ep.get('number', ''))] = ep
                self.message = f'استئناف: {name} ({len(existing_eps)} حلقة موجودة)'
            except:
                existing_eps = {}

        det = get_anime_details(url)
        if not det:
            return None

        ep_list = det.get('episodes_list', [])
        eps_data = []
        self.ep_total = len(ep_list)
        self.ep_progress = 0

        # هيكل البيانات الأساسي
        anime_data = {
            'id': aid,
            'title': det.get('title', name),
            'url': url,
            'poster': det.get('image', ''),
            'status': det.get('status', ''),
            'type': det.get('type', ''),
            'episodes_count': det.get('episodes', str(self.ep_total)),
            'start_date': det.get('start_date', ''),
            'season': det.get('season', ''),
            'genres': det.get('genres', []),
            'story': det.get('story', ''),
            'episodes': [],
            'last_updated': datetime.utcnow().isoformat(),
        }

        for idx, ep in enumerate(ep_list, 1):
            if self._stop: return None
            self.ep_progress = idx
            ep_num = str(ep.get('number', str(idx)))

            # تخطي الحلقات الموجودة
            if ep_num in existing_eps:
                eps_data.append(existing_eps[ep_num])
                continue

            ep_url = ep.get('url', '')
            if not ep_url:
                eps_data.append({'number': ep_num, 'title': ep.get('title', ''),
                                 'date': '', 'servers': [], 'downloads': []})
                continue

            try:
                srv, pub_date = get_episode_servers(ep_url)
                dls = get_episode_downloads(ep_url)
            except:
                srv, pub_date, dls = [], '', []

            self.total_eps += 1
            self.total_servers += len(srv)
            self.total_dls += len(dls)
            self.ep_servers = len(srv)
            self.ep_dls = len(dls)

            ep_data = {
                'number': ep_num,
                'title': ep.get('title', ''),
                'date': pub_date,
                'servers': [{'name': s['name'], 'embed_url': s['embed_url']} for s in srv],
                'downloads': [{'server': d['server'], 'quality': d['quality'],
                                'language': d['language'], 'url': d['url']} for d in dls],
            }
            eps_data.append(ep_data)

            # حفظ بعد كل حلقة (حماية من الفشل)
            anime_data['episodes'] = eps_data
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(anime_data, f, ensure_ascii=False, indent=2)

            # رفع الحلقة على GitHub فوراً
            self._push_incremental(f'🎬 الحلقة {ep_num} — {name[:30]}')

            time.sleep(DELAY)

        anime_data['episodes'] = eps_data
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(anime_data, f, ensure_ascii=False, indent=2)

        skipped = len(existing_eps)
        if skipped:
            self.message = f'{name}: {skipped} حلقة موجودة تم تخطيها'
        return anime_data

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
                latest_eps = sorted(ad['episodes'],
                    key=lambda x: str(x.get('number', '0')), reverse=True)[:3]
                for ep in latest_eps:
                    latest.append({
                        'anime_id': ad['id'], 'anime_title': ad['title'],
                        'anime_poster': ad['poster'], 'episode': ep['number'],
                        'date': ep.get('date', ''),
                    })
            score = len(ad.get('episodes', [])) + len(ad.get('genres', []))
            popular.append({**info, 'score': score})

        latest.sort(key=lambda x: x.get('date', ''), reverse=True)
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

        self.message = 'جاري الرفع إلى GitHub...'
        headers = {'Authorization': f'token {self.gh_token}', 'Accept': 'application/vnd.github.v3+json'}
        api = 'https://api.github.com'
        repo = 'abdobwd64-ctrl/anime'
        branch = 'main'

        ref_r = requests.get(f'{api}/repos/{repo}/git/refs/heads/{branch}', headers=headers)
        if ref_r.status_code != 200:
            self.message = f'فشل الوصول للمستودع: {ref_r.status_code}'
            self.phase = 'done'
            return
        latest_commit = ref_r.json()['object']['sha']

        commit_r = requests.get(f'{api}/repos/{repo}/git/commits/{latest_commit}', headers=headers)
        base_tree = commit_r.json()['tree']['sha']

        files_to_push = {}
        for root, dirs, files in os.walk(DATA):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, DIR).replace('\\', '/')
                with open(full, 'rb') as f:
                    files_to_push[rel] = f.read().decode('utf-8')

        blobs = []
        for path, content in files_to_push.items():
            blob_r = requests.post(f'{api}/repos/{repo}/git/blobs',
                headers=headers, json={'content': content, 'encoding': 'utf-8'})
            if blob_r.status_code == 201:
                blobs.append({'path': path, 'sha': blob_r.json()['sha'],
                              'mode': '100644', 'type': 'blob'})

        tree_r = requests.post(f'{api}/repos/{repo}/git/trees',
            headers=headers, json={'base_tree': base_tree, 'tree': blobs})
        if tree_r.status_code != 201:
            self.message = f'فشل إنشاء tree: {tree_r.status_code}'
            self.phase = 'done'
            return

        now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
        commit_r = requests.post(f'{api}/repos/{repo}/git/commits',
            headers=headers, json={
                'message': f'🤖 تحديث بيانات الأنمي — {now}\n\n{self.done} أنمي · {self.total_eps} حلقة',
                'tree': tree_r.json()['sha'], 'parents': [latest_commit],
            })
        if commit_r.status_code != 201:
            self.message = f'فشل إنشاء commit'
            self.phase = 'done'
            return

        requests.patch(f'{api}/repos/{repo}/git/refs/heads/{branch}',
            headers=headers, json={'sha': commit_r.json()['sha'], 'force': False})
        self.message = f'✅ تم رفع {len(files_to_push)} ملف إلى GitHub'
        self.phase = 'pushed'
