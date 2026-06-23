import sys, os, json, time, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# إسكات كل الـ logs المزعجة
logging.getLogger().setLevel(logging.ERROR)
for noisy in ['watchdog', 'urllib3', 'requests', 'streamlit', 'PIL', 'animelek']:
    logging.getLogger(noisy).setLevel(logging.ERROR)

from animelek_scraper import (
    logger, search_anime, get_homepage_pinned, get_anime_details,
    get_episode_servers, get_episode_downloads, BASE_URL
)
from scraper_engine import ScraperEngine

import streamlit as st

st.set_page_config(page_title="AnimeLek Viewer", page_icon="🎬", layout="wide")

st.markdown("""
<style>
    .main { padding: 1rem; direction: rtl; }
    .detail-label { font-weight: bold; color: #666; }
    .detail-value { color: #1a1a1a; }
    .genre-badge {
        display: inline-block; background: #e8f0fe; color: #1967d2;
        padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; margin: 2px 4px;
    }
    .server-btn {
        display: inline-block; background: #1a73e8; color: #fff;
        padding: 8px 20px; border-radius: 8px; text-decoration: none;
        margin: 4px; font-weight: bold;
    }
    .server-btn:hover { background: #1557b0; }
    .scraper-progress { font-family: monospace; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

st.title("🎬 AnimeLek Viewer")
st.markdown("تصفح وابحث في الأنمي من AnimeLek")

if 'page' not in st.session_state:
    st.session_state.page = 'home'
if 'detail_url' not in st.session_state:
    st.session_state.detail_url = ''
if 'episode_url' not in st.session_state:
    st.session_state.episode_url = ''

col1, col2 = st.columns([3, 1])
with col1:
    query = st.text_input("🔍", placeholder="اسم الأنمي...", label_visibility="collapsed")
with col2:
    go_search = st.button("بحث", type="primary", width='stretch')

b1, b2, b3, b4 = st.columns(4)
with b1:
    if st.button("🏠 الرئيسية", width='stretch'):
        st.session_state.page = 'home'
        st.rerun()
with b2:
    if st.button("📌 أحدث الحلقات", width='stretch'):
        st.session_state.page = 'latest'
        st.rerun()
with b3:
    if st.button("🔍 بحث", width='stretch'):
        st.session_state.page = 'search'
with b4:
    if st.button("🤖 ساحب", width='stretch'):
        st.session_state.page = 'scraper'

if go_search or (query and st.session_state.page == 'search'):
    st.session_state.page = 'search'

st.markdown("---")

# ===== HOME =====
if st.session_state.page == 'home':
    st.subheader("📌 أحدث الحلقات المضافة")
    with st.spinner("جاري التحميل..."):
        eps = get_homepage_pinned()
    unique = {}
    for ep in eps:
        key = ep['anime_url']
        if key not in unique:
            unique[key] = ep
    top_anime = list(unique.values())[:20]
    cols = st.columns(4)
    for i, ep in enumerate(top_anime):
        with cols[i % 4]:
            if ep.get('image'):
                st.image(ep['image'], width='stretch')
            st.markdown(f"**{ep['anime_name'][:35]}**")
            st.caption(ep['episode_name'])
            if st.button("📄", key=f"h_{i}", width='stretch'):
                st.session_state.detail_url = ep['anime_url']
                st.session_state.page = 'detail'
                st.rerun()

# ===== LATEST =====
elif st.session_state.page == 'latest':
    st.subheader("📌 جميع الحلقات الأخيرة")
    with st.spinner("جاري التحميل..."):
        eps = get_homepage_pinned()
    st.caption(f"إجمالي: {len(eps)} حلقة")
    for i, ep in enumerate(eps):
        col_a, col_b, col_c, col_d = st.columns([2, 4, 2, 2])
        with col_a:
            if ep.get('image'):
                st.image(ep['image'], width=80)
        with col_b:
            st.markdown(f"**{ep['anime_name']}**  \n{ep['episode_name']}")
        with col_c:
            if st.button("📄 التفاصيل", key=f"l_{i}", width='stretch'):
                st.session_state.detail_url = ep['anime_url']
                st.session_state.page = 'detail'
                st.rerun()
        with col_d:
            if st.button("▶ المشاهدة", key=f"le_{i}", width='stretch'):
                st.session_state.episode_url = ep['episode_url']
                st.session_state.page = 'episode'
                st.rerun()
        st.divider()

# ===== SEARCH =====
elif st.session_state.page == 'search':
    if query:
        st.subheader(f"نتائج البحث عن: {query}")
        with st.spinner("جاري البحث..."):
            results = search_anime(query.strip())
        if results:
            st.caption(f"تم العثور على {len(results)} نتيجة")
            cols = st.columns(3)
            for i, r in enumerate(results):
                with cols[i % 3]:
                    if r.get('image'):
                        st.image(r['image'], width='stretch')
                    st.markdown(f"**{r['name'][:50]}**")
                    st.caption(f"{r['type']} {r['year']}")
                    if st.button("📄", key=f"s_{i}", width='stretch'):
                        st.session_state.detail_url = r['url']
                        st.session_state.page = 'detail'
                        st.rerun()
        else:
            st.warning("لا توجد نتائج")
    else:
        st.info("اكتب اسم الأنمي للبحث")

# ===== DETAIL =====
elif st.session_state.page == 'detail':
    url = st.session_state.detail_url
    if not url:
        st.error("لا يوجد رابط")
    else:
        with st.spinner("جاري تحميل التفاصيل..."):
            d = get_anime_details(url)
        if not d:
            st.error("فشل التحميل")
        else:
            left_col, right_col = st.columns([1, 2])
            with left_col:
                if d.get('image'):
                    st.image(d['image'], width='stretch')
                if d.get('episodes_list'):
                    st.markdown("### 📺 الحلقات")
                    for ep in d['episodes_list']:
                        if st.button(ep['title'][:25], key=f"ep_{ep['number']}", width='stretch'):
                            st.session_state.episode_url = ep['url']
                            st.session_state.page = 'episode'
                            st.rerun()
            with right_col:
                st.subheader(d.get('title', ''))
                for label, key in [("حالة الأنمي",'status'),("النوع",'type'),
                    ("الحلقات",'episodes'),("بداية العرض",'start_date'),("الموسم",'season')]:
                    val = d.get(key, '')
                    if val:
                        st.markdown(f"<span class='detail-label'>{label}:</span> <span class='detail-value'>{val}</span>", unsafe_allow_html=True)
                if d.get('genres'):
                    st.markdown("**التصنيفات:** " + " ".join(f"<span class='genre-badge'>{g}</span>" for g in d['genres']), unsafe_allow_html=True)
            st.divider()
            if d.get('story'):
                st.markdown("### 📖 القصة")
                st.markdown(d['story'])
            st.divider()
            if st.button("🔙 رجوع", width='stretch'):
                st.session_state.page = 'home'
                st.rerun()

# ===== EPISODE PLAYER =====
elif st.session_state.page == 'episode':
    url = st.session_state.episode_url
    if not url:
        st.error("لا يوجد رابط")
    else:
        st.subheader("🎥 مشاهدة الحلقة")
        with st.spinner("جاري تحميل السيرفرات..."):
            servers, pub_date = get_episode_servers(url)
        if pub_date:
            st.caption(f"📅 {pub_date}")
        if servers:
            tabs = st.tabs([s['name'][:20] for s in servers])
            for i, (tab, srv) in enumerate(zip(tabs, servers)):
                with tab:
                    embed = srv.get('embed_url', '')
                    video_url = srv.get('video_url', '')
                    if video_url:
                        if 'youtube' in video_url or 'youtu.be' in video_url:
                            st.video(video_url)
                        else:
                            st.markdown(f'<iframe src="{embed}" width="100%" height="500" frameborder="0" allowfullscreen></iframe>', unsafe_allow_html=True)
                            st.markdown(f"[📺 فتح في نافذة منفصلة]({embed})")
                            if video_url:
                                st.caption(f"رابط الفيديو المباشر: {video_url[:100]}")
        else:
            st.warning("لا توجد سيرفرات متاحة")
            st.markdown(f"[🔗 الرابط الأصلي]({url})")

        st.divider()
        st.markdown("### 📥 روابط التحميل")
        with st.spinner("جاري تحميل روابط التحميل..."):
            dls = get_episode_downloads(url)
        if dls:
            for dl in dls:
                col_a, col_b, col_c = st.columns([4, 2, 4])
                with col_a:
                    st.markdown(f"**{dl['server']}**")
                with col_b:
                    st.markdown(f"`{dl['quality']}`")
                with col_c:
                    st.markdown(f"[⬇ تحميل]({dl['url']})")
                st.divider()
        else:
            st.info("لا توجد روابط تحميل متاحة")

        if st.button("🔙 رجوع", width='stretch'):
            st.session_state.page = 'detail'
            st.rerun()

# ===== SCRAPER =====
elif st.session_state.page == 'scraper':
    st.subheader("🤖 ساحب الأنمي من AnimeLek.top")
    
    try:
        gh_token = os.environ.get('GH_TOKEN') or st.secrets.get('GH_TOKEN', '')
    except:
        gh_token = os.environ.get('GH_TOKEN', '')
    
    @st.cache_resource
    def get_engine():
        return ScraperEngine(gh_token, parallel=3)
    
    engine = get_engine()
    
    live_phases = ('scrape', 'discover', 'save', 'check')
    # لو thread مات والطور لسه حي → ارجع idle
    if engine.phase in live_phases and not (engine._thread and engine._thread.is_alive()):
        engine.phase = 'idle'
    
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    with col_s1:
        if engine.phase == 'idle' and st.button("🚀 ابدأ السحب", type="primary", width='stretch'):
            engine.start()
            st.rerun()
    with col_s2:
        if engine.phase == 'idle' and st.button("🔍 فحص الجديد", width='stretch'):
            engine.start_check()
            st.rerun()
    with col_s3:
        if engine.phase in live_phases and st.button("⏹ إيقاف", width='stretch'):
            engine.stop()
            st.rerun()
    with col_s4:
        if engine.phase in ('done', 'pushed', 'error') and st.button("🔄 تصفير", width='stretch'):
            st.cache_resource.clear()
            st.rerun()
    
    st.divider()
    
    if engine.phase == 'idle':
        st.info("اضغط 'ابدأ السحب' لبدء سحب كل الأنمي من AnimeLek.top وحفظه في GitHub")
    
    elif engine.phase == 'discover':
        st.markdown(f"**🔍 المرحلة 1/4:** اكتشاف الأنمي...")
        st.progress(0)
        st.info("جاري البحث في الموقع...")
        time.sleep(1.5)
        st.rerun()
    
    elif engine.phase == 'scrape':
        pct = engine.overall_pct
        st.markdown(f"**📥 المرحلة 2/4:** سحب التفاصيل والحلقات")
        st.progress(pct / 100)
        
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1: st.metric("تم", engine.done)
        with col_m2: st.metric("فشل", engine.failed)
        with col_m3: st.metric("حلقات", engine.total_eps)
        with col_m4: st.metric("سيرفرات", engine.total_servers)
        
        bar_len = 25
        filled = int(bar_len * engine.current / engine.total) if engine.total > 0 else 0
        bar = '█' * filled + '░' * (bar_len - filled)
        st.code(f"[{bar}] {engine.current}/{engine.total} ({engine.overall_pct:.0f}%) — {engine.current_name}")
        
        if engine.ep_total > 0:
            ep_filled = int(bar_len * engine.ep_progress / engine.ep_total)
            ep_bar = '█' * ep_filled + '░' * (bar_len - ep_filled)
            st.code(f"     └─ حلقات [{ep_bar}] {engine.ep_progress}/{engine.ep_total} | {engine.ep_servers} سيرفر | {engine.ep_dls} تحميلة")
        
        st.caption(f"{engine.message}")
        time.sleep(1.5)
        st.rerun()
    
    elif engine.phase == 'save':
        st.markdown(f"**💾 المرحلة 3/4:** حفظ الفهارس ورفع إلى GitHub...")
        st.progress(0.95)
        st.info(engine.message)
        time.sleep(1)
        st.rerun()
    
    elif engine.phase == 'check':
        st.markdown(f"**🔍 فحص الحلقات الجديدة...**")
        if engine.total > 0:
            st.progress(min(engine.current / engine.total, 1.0))
        st.info(engine.message)
        time.sleep(1.5)
        st.rerun()
    
    elif engine.phase == 'pushed':
        st.success("✅ **تم بنجاح!**")
        st.balloons()
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1: st.metric("أنمي", engine.done)
        with col_f2: st.metric("حلقات", engine.total_eps)
        with col_f3: st.metric("سيرفرات", engine.total_servers)
        st.code(f"📥 تحميلات: {engine.total_dls}")
        st.markdown(f"_{engine.message}_")
    
    elif engine.phase == 'error':
        st.error(f"❌ خطأ: {engine.message}")
    
    elif engine.phase == 'done':
        st.warning(f"⚠️ {engine.message}")
        st.code(f"تم: {engine.done} | فشل: {engine.failed} | حلقات: {engine.total_eps}")
