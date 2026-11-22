"""
Tes MangaDex + Streamlit (satu file)
Cari judul (kosong = semua) + filter genre.
Menampilkan: judul_manhwa, jumlah_chapter (ongoing -> chapter terakhir), genre, cover.

Jalankan:  streamlit run app.py
"""

import base64
import os
import time

import pandas as pd
import requests
import streamlit as st

API = os.environ.get("MANGADEX_API", "https://api.mangadex.org")
COVER_CDN = os.environ.get("MANGADEX_COVERS", "https://uploads.mangadex.org/covers")
HEADERS = {"User-Agent": "streamlit-manhwa-test/1.0"}

st.set_page_config(page_title="Tes MangaDex", page_icon="🧪", layout="wide")


# ------------------------------------------------------------------ API
def api_get(path, params=None, retries=4):
    """GET ke MangaDex, retry otomatis saat kena rate limit (429)."""
    last_error = None
    for attempt in range(retries):
        try:
            r = requests.get(f"{API}{path}", params=params, headers=HEADERS, timeout=20)
            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_error = e
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"Gagal menghubungi MangaDex: {last_error or 'rate limit'}")


@st.cache_data(ttl=86400, show_spinner=False)
def get_genre_tags():
    """{nama_genre: tag_id}, hanya tag group 'genre'."""
    data = api_get("/manga/tag")
    genres = {
        t["attributes"]["name"].get("en", ""): t["id"]
        for t in data.get("data", [])
        if t["attributes"].get("group") == "genre"
    }
    return dict(sorted(genres.items()))


def build_params(title, offset, limit, order_field, included, excluded, mode):
    if order_field == "relevance" and not title:
        order_field = "followedCount"
    params = {
        "limit": limit,
        "offset": offset,
        "includes[]": ["cover_art"],
        "originalLanguage[]": ["ko"],  # ko = manhwa
        "contentRating[]": ["safe", "suggestive"],
        f"order[{order_field}]": "desc",
    }
    if title:
        params["title"] = title
    if included:
        params["includedTags[]"] = list(included)
        params["includedTagsMode"] = mode
    if excluded:
        params["excludedTags[]"] = list(excluded)
    return params


@st.cache_data(ttl=600, show_spinner=False)
def search_manga(title, offset, limit, order_field, included, excluded, mode):
    return api_get("/manga", build_params(title, offset, limit, order_field, included, excluded, mode))


@st.cache_data(ttl=3600, show_spinner=False)
def latest_chapter(manga_id, trans_lang):
    """Chapter tertinggi yang tersedia, via /aggregate."""
    params = {} if trans_lang == "all" else {"translatedLanguage[]": [trans_lang]}
    volumes = api_get(f"/manga/{manga_id}/aggregate", params).get("volumes", {})
    if not isinstance(volumes, dict):  # MangaDex kirim [] kalau kosong
        return None
    numbers = {}
    for vol in volumes.values():
        chapters = vol.get("chapters", {})
        if not isinstance(chapters, dict):
            continue
        for key in chapters:
            try:
                numbers[float(key)] = key
            except ValueError:  # "none" = chapter tanpa nomor
                pass
    return numbers[max(numbers)] if numbers else None


@st.cache_data(ttl=86400, show_spinner=False, max_entries=500)
def fetch_cover(url):
    """Unduh cover di server, supaya browser pengguna tidak perlu akses ke MangaDex."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.content
    except requests.RequestException:
        return None


def to_data_uri(url):
    img = fetch_cover(url) if url else None
    return f"data:image/jpeg;base64,{base64.b64encode(img).decode()}" if img else None


# ------------------------------------------------------------------ Parsing
def pick_title(attrs):
    titles = attrs.get("title", {})
    if "en" in titles:
        return titles["en"]
    for alt in attrs.get("altTitles", []):
        if "en" in alt:
            return alt["en"]
    return next(iter(titles.values()), "(tanpa judul)")


def build_row(m, trans_lang, with_chapters):
    a = m["attributes"]
    status = a.get("status") or "-"

    genres = sorted(
        t["attributes"]["name"].get("en", "")
        for t in a.get("tags", [])
        if t["attributes"].get("group") == "genre"
    )

    cover_rel = next((r for r in m.get("relationships", []) if r["type"] == "cover_art"), None)
    file_name = (cover_rel or {}).get("attributes", {}).get("fileName")
    cover = f"{COVER_CDN}/{m['id']}/{file_name}.256.jpg" if file_name else None

    # tamat -> lastChapter metadata; ongoing -> chapter terbaru dari /aggregate
    last_meta = a.get("lastChapter")
    last_meta = last_meta if last_meta and last_meta != "0" else None
    if status == "completed" and last_meta:
        jumlah = last_meta
    elif with_chapters:
        jumlah = latest_chapter(m["id"], trans_lang) or last_meta or "-"
    else:
        jumlah = last_meta or "-"

    return {
        "judul_manhwa": pick_title(a),
        "jumlah_chapter": jumlah,
        "status": status,
        "genre": ", ".join(genres) if genres else "-",
        "cover": cover,
        "link": f"https://mangadex.org/title/{m['id']}",
    }


# ------------------------------------------------------------------ UI
st.title("🧪 Tes MangaDex")
st.caption("Kosongkan judul untuk menampilkan semua manhwa (urut paling banyak diikuti).")

try:
    genre_map = get_genre_tags()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

with st.form("filter"):
    query = st.text_input("Judul", placeholder="Kosong = semua judul")

    c1, c2 = st.columns(2)
    inc_names = c1.multiselect("Genre disertakan", list(genre_map))
    exc_names = c2.multiselect("Genre dikecualikan", list(genre_map))

    c3, c4, c5, c6 = st.columns(4)
    mode = c3.radio("Mode genre", ["AND", "OR"], horizontal=True,
                    format_func={"AND": "Semua genre", "OR": "Salah satu"}.get)
    order_field = c4.selectbox(
        "Urutkan",
        ["followedCount", "latestUploadedChapter", "rating", "relevance"],
        format_func={"followedCount": "Paling diikuti",
                     "latestUploadedChapter": "Update terbaru",
                     "rating": "Rating tertinggi",
                     "relevance": "Relevansi (butuh judul)"}.get,
    )
    per_page = c5.select_slider("Per halaman", options=[8, 12, 16, 20], value=12)
    page = c6.number_input("Halaman", min_value=1, value=1, step=1)

    c7, c8, c9 = st.columns(3)
    trans_lang = c7.selectbox("Bahasa chapter", ["en", "id", "all"],
                              format_func={"en": "Inggris", "id": "Indonesia", "all": "Semua bahasa"}.get)
    with_chapters = c8.checkbox("Ambil chapter terakhir (lebih lambat)", value=True)
    cover_via_server = c9.checkbox("Muat cover lewat server", value=True,
                                   help="Browser pengguna tidak perlu akses langsung ke MangaDex.")

    st.form_submit_button("🔍 Cari", type="primary")

overlap = set(inc_names) & set(exc_names)
if overlap:
    st.error(f"Genre ada di 'disertakan' dan 'dikecualikan': {', '.join(sorted(overlap))}")
    st.stop()

offset = (page - 1) * per_page
if offset + per_page > 10000:
    st.warning("MangaDex hanya mengizinkan 10.000 hasil pertama. Perkecil halaman.")
    st.stop()

args = (query.strip(), offset, per_page, order_field,
        tuple(genre_map[n] for n in inc_names),
        tuple(genre_map[n] for n in exc_names), mode)

try:
    with st.spinner("Mencari di MangaDex…"):
        result = search_manga(*args)
    items = result.get("data", [])
    total = result.get("total", 0)

    rows = []
    if items:
        bar = st.progress(0.0, text="Memproses hasil…")
        for i, m in enumerate(items, start=1):
            row = build_row(m, trans_lang, with_chapters)
            if cover_via_server and row["cover"]:
                fetch_cover(row["cover"])
            rows.append(row)
            bar.progress(i / len(items), text=f"Memproses hasil… ({i}/{len(items)})")
        bar.empty()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

with st.expander("🔧 Detail request (debug)"):
    st.json(build_params(*args))

if not rows:
    st.info("Tidak ada hasil untuk kombinasi filter ini.")
    st.stop()

st.write(f"**{total:,}** hasil · menampilkan {offset + 1}–{offset + len(rows)}")

tab_table, tab_cards = st.tabs(["📋 Tabel", "🖼️ Kartu"])

with tab_table:
    df = pd.DataFrame(rows)
    if cover_via_server:
        df["cover"] = df["cover"].map(to_data_uri)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "cover": st.column_config.ImageColumn("cover", width="small"),
            "link": st.column_config.LinkColumn("link", display_text="Buka"),
        },
    )

with tab_cards:
    COLS = 4
    for start in range(0, len(rows), COLS):
        for col, row in zip(st.columns(COLS), rows[start:start + COLS]):
            with col:
                img = fetch_cover(row["cover"]) if cover_via_server and row["cover"] else row["cover"]
                if img:
                    st.image(img, use_container_width=True)
                st.markdown(f"**[{row['judul_manhwa']}]({row['link']})**")
                st.caption(f"Chapter: **{row['jumlah_chapter']}** · {row['status']}")
                st.caption(row["genre"])