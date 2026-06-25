#!/usr/bin/env python3
"""sync_index.py — سريع: ينزل بيانات GitHub ويجدد latest.json ويرفعه فقط (بدون سحب)"""
import sys, os, json, time, base64, re
from datetime import datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper_engine import DIR, DATA

GH_TOKEN = os.environ.get('GH_TOKEN') or (sys.argv[1] if len(sys.argv) > 1 else '')
if not GH_TOKEN:
    print('⚠️  لا يوجد GitHub Token')
    print('   استخدم: $env:GH_TOKEN="ghp_..."')
    sys.exit(1)

REPO = 'abdobwd64-ctrl/anime'
BRANCH = 'main'
raw_base = f'https://raw.githubusercontent.com/{REPO}/{BRANCH}'
api = 'https://api.github.com'
headers = {'Authorization': f'token {GH_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}

os.makedirs(os.path.join(DATA, 'anime'), exist_ok=True)

print('1/4 جاري تحميل قائمة الأنمي من GitHub...')
r = requests.get(f'{raw_base}/data/all-animes.json', headers=headers)
if r.status_code != 200:
    print(f'  ✗ فشل تحميل all-animes.json: {r.status_code}')
    sys.exit(1)
anime_list = r.json()
print(f'  ✓ {len(anime_list)} أنمي')

print('2/4 جاري تحميل ملفات الأنمي الناقصة...')
downloaded = 0
for a in anime_list:
    aid = a.get('id')
    if not aid:
        continue
    local_fp = os.path.join(DATA, 'anime', f'{aid}.json')
    if not os.path.exists(local_fp):
        ar = requests.get(f'{raw_base}/data/anime/{aid}.json', headers=headers)
        if ar.status_code == 200:
            with open(local_fp, 'w', encoding='utf-8') as f:
                f.write(ar.text)
            downloaded += 1
            print(f'  ✓ {aid}', flush=True)
print(f'  ✓ تم تحميل {downloaded} ملف جديد')

print('3/4 جاري بناء الفهارس (latest, all-animes, popular, meta)...')

def parse_arabic_date(date_str):
    if not date_str: return ''
    months = {
        'يناير':'01','فبراير':'02','مارس':'03','أبريل':'04','إبريل':'04',
        'مايو':'05','يونيو':'06','يوليو':'07','أغسطس':'08','غشت':'08',
        'سبتمبر':'09','أكتوبر':'10','نوفمبر':'11','ديسمبر':'12',
    }
    m = re.match(r'(\d+)\s+([^,\s]+),?\s*(\d+)', date_str)
    if m:
        return f'{m.group(3)}-{months.get(m.group(2),"01")}-{int(m.group(1)):02d}'
    return ''

latest = []
popular = []
index_list = []
anime_dir = os.path.join(DATA, 'anime')
for fn in os.listdir(anime_dir):
    if not fn.endswith('.json'):
        continue
    try:
        with open(os.path.join(anime_dir, fn), encoding='utf-8') as f:
            ad = json.load(f)
    except:
        continue
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
            key=lambda x: parse_arabic_date(x.get('date', '')), reverse=True)[:5]
        for ep in sorted_eps:
            d = ep.get('date', '')
            sa = e.get('saved_at', '')
            latest.append({
                'anime_id': ad['id'], 'anime_title': ad['title'],
                'anime_poster': ad['poster'], 'episode': ep['number'],
                'date': d,
                'date_sort': parse_arabic_date(d),
                'saved_at': sa,
            })
    score = len(ad.get('episodes', [])) + len(ad.get('genres', []))
    popular.append({**info, 'score': score})

latest.sort(key=lambda x: (x.get('date_sort', ''), x.get('saved_at', '')), reverse=True)
popular.sort(key=lambda x: x['score'], reverse=True)

total_eps = 0
for fn in os.listdir(anime_dir):
    if not fn.endswith('.json'): continue
    try:
        with open(os.path.join(anime_dir, fn), encoding='utf-8') as f:
            ad = json.load(f)
        if ad:
            total_eps += len(ad.get('episodes', []))
    except:
        pass

meta = {
    'total_anime': len(index_list), 'total_episodes': total_eps,
    'last_updated': datetime.utcnow().isoformat(),
}

with open(os.path.join(DATA, 'latest.json'), 'w', encoding='utf-8') as f:
    json.dump(latest[:50], f, ensure_ascii=False, indent=2)
with open(os.path.join(DATA, 'all-animes.json'), 'w', encoding='utf-8') as f:
    json.dump(index_list, f, ensure_ascii=False, indent=2)
with open(os.path.join(DATA, 'popular.json'), 'w', encoding='utf-8') as f:
    json.dump([{k:v for k,v in p.items() if k != 'score'} for p in popular[:30]], f, ensure_ascii=False, indent=2)
with open(os.path.join(DATA, 'meta.json'), 'w', encoding='utf-8') as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print('  ✓ تم حفظ الفهارس محلياً')

print('4/4 جاري رفع الفهارس إلى GitHub...')

ref = requests.get(f'{api}/repos/{REPO}/git/refs/heads/{BRANCH}', headers=headers).json()
latest_sha = ref['object']['sha']
base_tree = requests.get(f'{api}/repos/{REPO}/git/commits/{latest_sha}', headers=headers).json()['tree']['sha']

files_to_push = []
for name in ('latest.json', 'all-animes.json', 'popular.json', 'meta.json'):
    fp = os.path.join(DATA, name)
    with open(fp, 'rb') as f:
        text = f.read().decode('utf-8')
    files_to_push.append({'path': f'data/{name}', 'content': text, 'encoding': 'utf-8'})

blobs = []
for f in files_to_push:
    br = requests.post(f'{api}/repos/{REPO}/git/blobs',
        headers=headers, json={'content': f['content'], 'encoding': 'utf-8'})
    if br.status_code != 201:
        print(f'  ✗ فشل رفع blob {f["path"]}: {br.status_code} {br.text[:100]}')
        sys.exit(1)
    blobs.append({'path': f['path'], 'sha': br.json()['sha'], 'mode': '100644', 'type': 'blob'})

tree_r = requests.post(f'{api}/repos/{REPO}/git/trees',
    headers=headers, json={'base_tree': base_tree, 'tree': blobs})
if tree_r.status_code != 201:
    print(f'  ✗ فشل إنشاء tree: {tree_r.status_code} {tree_r.text[:200]}')
    sys.exit(1)

now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
commit_r = requests.post(f'{api}/repos/{REPO}/git/commits',
    headers=headers, json={
        'message': f'🤖 تحديث الفهارس — {now}',
        'tree': tree_r.json()['sha'], 'parents': [latest_sha],
    })
if commit_r.status_code != 201:
    print(f'  ✗ فشل إنشاء commit: {commit_r.status_code}')
    sys.exit(1)

requests.patch(f'{api}/repos/{REPO}/git/refs/heads/{BRANCH}',
    headers=headers, json={'sha': commit_r.json()['sha'], 'force': False})

print(f'  ✅ تم رفع 4 فهارس إلى GitHub')
print(f'\nالموقع هيحتاج دقيقة عشان يتحدث')
