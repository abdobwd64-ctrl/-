import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from animelek_scraper import (
    logger, search_anime, get_homepage_pinned, get_anime_details,
    get_episode_servers, get_episode_downloads, BASE_URL
)

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
    go_search = st.button("بحث", type="primary", use_container_width=True)

left, mid, right = st.columns(3)
with left:
    if st.button("🏠 الرئيسية", use_container_width=True):
        st.session_state.page = 'home'
        st.rerun()
with mid:
    if st.button("📌 أحدث الحلقات", use_container_width=True):
        st.session_state.page = 'latest'
        st.rerun()
with right:
    if st.button("🔍 بحث", use_container_width=True):
        st.session_state.page = 'search'

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
                st.image(ep['image'], use_container_width=True)
            st.markdown(f"**{ep['anime_name'][:35]}**")
            st.caption(ep['episode_name'])
            if st.button("📄", key=f"h_{i}", use_container_width=True):
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
            if st.button("📄 التفاصيل", key=f"l_{i}", use_container_width=True):
                st.session_state.detail_url = ep['anime_url']
                st.session_state.page = 'detail'
                st.rerun()
        with col_d:
            if st.button("▶ المشاهدة", key=f"le_{i}", use_container_width=True):
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
                        st.image(r['image'], use_container_width=True)
                    st.markdown(f"**{r['name'][:50]}**")
                    st.caption(f"{r['type']} {r['year']}")
                    if st.button("📄", key=f"s_{i}", use_container_width=True):
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
                    st.image(d['image'], use_container_width=True)
                if d.get('episodes_list'):
                    st.markdown("### 📺 الحلقات")
                    for ep in d['episodes_list']:
                        if st.button(ep['title'][:25], key=f"ep_{ep['number']}", use_container_width=True):
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
            if st.button("🔙 رجوع", use_container_width=True):
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

        if st.button("🔙 رجوع", use_container_width=True):
            st.session_state.page = 'detail'
            st.rerun()
