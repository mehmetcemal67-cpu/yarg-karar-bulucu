import io
import re
import html
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import streamlit as st
from bs4 import BeautifulSoup
from docx import Document
from docx.shared import Pt


# ============================================================
# SAYFA
# ============================================================

st.set_page_config(
    page_title="Yargı Kararı Çalışma Alanı",
    page_icon="⚖️",
    layout="wide",
)

PAGE_SIZE = 10

SOURCES = {
    "Yargıtay": {
        "base": "https://karararama.yargitay.gov.tr",
        "arama": "https://karararama.yargitay.gov.tr/arama",
        "aramalist": "https://karararama.yargitay.gov.tr/aramalist",
        "dokuman": "https://karararama.yargitay.gov.tr/getDokuman?id={id}",
    },
    "UYAP Emsal": {
        "base": "https://emsal.uyap.gov.tr",
        "arama": "https://emsal.uyap.gov.tr/arama",
        "aramalist": "https://emsal.uyap.gov.tr/aramalist",
        "dokuman": "https://emsal.uyap.gov.tr/getDokuman?id={id}",
    },
}


# ============================================================
# TASARIM
# ============================================================

st.markdown(
    """
<style>

.block-container {
    max-width: 1800px;
    padding-top: 1.2rem;
    padding-bottom: 2rem;
}

div[data-testid="stMetric"] {
    border: 1px solid rgba(128,128,128,.20);
    border-radius: 10px;
    padding: 8px 12px;
}

.karar-metni {
    height: 680px;
    overflow-y: auto;

    font-family: Georgia, "Times New Roman", serif;
    font-size: 17px;
    line-height: 1.72;

    padding: 24px 28px;

    border: 1px solid rgba(130,130,130,.28);
    border-radius: 10px;

    background: rgba(128,128,128,.035);
}

.arama-vurgu {
    background: #ffd900;
    color: #111;

    padding: 0 2px;

    font-weight: 650;

    text-decoration: underline 2px #d58e00;
    text-underline-offset: 3px;

    border-radius: 2px;
}

.kaynak-baslik {
    font-size: 14px;
    opacity: .72;
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# SESSION STATE
# ============================================================

if "query" not in st.session_state:
    st.session_state.query = ""

if "active_query" not in st.session_state:
    st.session_state.active_query = ""

if "pages" not in st.session_state:
    st.session_state.pages = {
        "Yargıtay": 1,
        "UYAP Emsal": 1,
    }

if "selected" not in st.session_state:
    st.session_state.selected = {}

if "search_cache" not in st.session_state:
    st.session_state.search_cache = {}

if "document_cache" not in st.session_state:
    st.session_state.document_cache = {}

if "http_sessions" not in st.session_state:
    st.session_state.http_sessions = {}


# ============================================================
# HTTP
# ============================================================

def create_session(source):
    cfg = SOURCES[source]

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
        "Origin": cfg["base"],
        "Referer": cfg["base"] + "/",
        "X-Requested-With": "XMLHttpRequest",
    })

    return session


def get_sessions():
    """
    BU FONKSİYON ANA STREAMLIT THREAD'İNDE ÇALIŞIR.
    Worker thread içinde session_state kullanılmaz.
    """

    sessions = {}

    for source in SOURCES:
        if source not in st.session_state.http_sessions:
            st.session_state.http_sessions[source] = create_session(source)

        sessions[source] = st.session_state.http_sessions[source]

    return sessions


# ============================================================
# RESMÎ SİTE PAYLOAD'I
# ============================================================

def build_payload(query, ui_page):
    """
    DevTools ile doğrulanan gerçek format.

    İlk sayfa:
    {
      "data": {
        "aranan": "...",
        "arananKelime": "..."
      }
    }

    2. sayfa:
    {
      "data": {
        "aranan": "...",
        "arananKelime": "...",
        "pageNumber": 1,
        "pageSize": 10
      }
    }
    """

    data = {
        "aranan": query,
        "arananKelime": query,
    }

    service_page = ui_page - 1

    if service_page > 0:
        data["pageNumber"] = service_page
        data["pageSize"] = PAGE_SIZE

    return {
        "data": data
    }


# ============================================================
# KARAR ALANLARI
# ============================================================

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def pick(row, *names):
    if not isinstance(row, dict):
        return ""

    lower = {
        str(k).lower(): v
        for k, v in row.items()
    }

    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]

        value = lower.get(name.lower())

        if value not in (None, ""):
            return value

    return ""


def normalize_decision(row):
    return {
        "id": clean(
            pick(
                row,
                "id",
                "dokumanId",
                "documentId",
                "kararId",
            )
        ),

        "daire": clean(
            pick(
                row,
                "daire",
                "daireAdi",
                "birimAdi",
                "birim",
                "mahkeme",
            )
        ),

        "esas": clean(
            pick(
                row,
                "esas",
                "esasNo",
                "esasNoStr",
                "esasNumarasi",
            )
        ),

        "karar": clean(
            pick(
                row,
                "karar",
                "kararNo",
                "kararNoStr",
                "kararNumarasi",
            )
        ),

        "tarih": clean(
            pick(
                row,
                "kararTarihi",
                "kararTarih",
                "tarih",
                "kararTarihiStr",
            )
        ),
    }


# ============================================================
# RESMÎ ARAMA
# ============================================================

def official_search(
    source,
    session,
    query,
    ui_page,
    new_search=False,
):
    """
    Tarayıcıdaki gerçek akışı taklit eder.

    Yeni aramada:
        POST /arama
        POST /aramalist

    Sayfa değişiminde:
        POST /aramalist
    """

    cfg = SOURCES[source]
    payload = build_payload(query, ui_page)

    try:

        # ----------------------------------------------------
        # 1. /arama
        # ----------------------------------------------------

        if new_search:

            response = session.post(
                cfg["arama"],
                json=payload,
                timeout=(4, 12),
            )

            response.raise_for_status()

        # ----------------------------------------------------
        # 2. /aramalist
        # ----------------------------------------------------

        response = session.post(
            cfg["aramalist"],
            json=payload,
            timeout=(4, 12),
        )

        response.raise_for_status()

        obj = response.json()

        root = obj.get("data", {})

        raw_rows = root.get("data", [])

        total = root.get("recordsTotal", 0)

        rows = [
            normalize_decision(row)
            for row in raw_rows
            if isinstance(row, dict)
        ]

        return {
            "ok": True,
            "rows": rows,
            "total": int(total or 0),
            "error": "",
        }

    except Exception as exc:

        return {
            "ok": False,
            "rows": [],
            "total": 0,
            "error": (
                f"{type(exc).__name__}: {exc}"
            ),
        }


# ============================================================
# KARAR METNİ
# ============================================================

def html_to_text(document_html):
    if not document_html:
        return ""

    raw = html.unescape(
        str(document_html)
    )

    soup = BeautifulSoup(
        raw,
        "html.parser",
    )

    for tag in soup([
        "script",
        "style",
        "meta",
        "link",
        "noscript",
    ]):
        tag.decompose()

    text = soup.get_text(
        "\n",
        strip=True,
    )

    lines = []

    for line in text.splitlines():

        line = re.sub(
            r"[ \t]+",
            " ",
            line,
        ).strip()

        if line:
            lines.append(line)

    return "\n".join(lines)


def official_document(
    source,
    session,
    decision_id,
):
    """
    DevTools ile doğrulanan gerçek getDokuman çağrısı.

    GET /getDokuman?id=...
    JSON cevabındaki obj["data"] HTML karar metnidir.
    """

    if not decision_id:
        return ""

    cfg = SOURCES[source]

    try:

        response = session.get(
            cfg["dokuman"].format(
                id=decision_id
            ),
            timeout=(4, 15),
        )

        response.raise_for_status()

        obj = response.json()

        document_html = obj.get(
            "data",
            "",
        )

        return html_to_text(
            document_html
        )

    except Exception:
        return ""


# ============================================================
# VURGULAMA
# ============================================================

def highlight_terms(query):
    query = clean(query)

    if not query:
        return []

    # "haksız tahrik"
    quoted = re.findall(
        r'"([^"]+)"',
        query,
    )

    if quoted:
        return [
            clean(item)
            for item in quoted
            if clean(item)
        ]

    # haksız tahrik
    return re.findall(
        r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]+",
        query,
    )


def make_highlighted_html(
    decision_text,
    query,
):
    safe = html.escape(
        decision_text
    )

    terms = highlight_terms(
        query
    )

    terms.sort(
        key=len,
        reverse=True,
    )

    for term in terms:

        escaped = html.escape(
            term
        )

        regex = re.compile(
            re.escape(escaped),
            flags=re.I,
        )

        safe = regex.sub(
            lambda match:
            (
                '<mark class="arama-vurgu">'
                + match.group(0)
                + "</mark>"
            ),
            safe,
        )

    safe = safe.replace(
        "\n",
        "<br>"
    )

    return (
        '<div class="karar-metni">'
        + safe
        + "</div>"
    )


# ============================================================
# WORD
# ============================================================

def create_word(
    source,
    row,
    text,
    query,
):
    document = Document()

    style = document.styles[
        "Normal"
    ]

    style.font.name = "Arial"
    style.font.size = Pt(11)

    document.add_heading(
        f"{source} Kararı",
        level=1,
    )

    document.add_paragraph(
        f"Daire / Kurul: "
        f"{row.get('daire') or '-'}"
    )

    document.add_paragraph(
        f"Esas No: "
        f"{row.get('esas') or '-'}"
    )

    document.add_paragraph(
        f"Karar No: "
        f"{row.get('karar') or '-'}"
    )

    document.add_paragraph(
        f"Karar Tarihi: "
        f"{row.get('tarih') or '-'}"
    )

    document.add_paragraph(
        f"Arama: {query}"
    )

    document.add_heading(
        "Karar Metni",
        level=2,
    )

    for paragraph in re.split(
        r"\n{2,}",
        text,
    ):

        paragraph = paragraph.strip()

        if paragraph:
            document.add_paragraph(
                paragraph
            )

    buffer = io.BytesIO()

    document.save(
        buffer
    )

    return buffer.getvalue()


def word_filename(
    source,
    row,
):
    prefix = (
        "Yargitay"
        if source == "Yargıtay"
        else "UYAP"
    )

    esas = (
        row.get("esas")
        or "Esas"
    ).replace("/", "_")

    karar = (
        row.get("karar")
        or "Karar"
    ).replace("/", "_")

    return (
        f"{prefix}_"
        f"E_{esas}_"
        f"K_{karar}.docx"
    )


# ============================================================
# ÜST ARAMA
# ============================================================

st.title(
    "⚖️ Yargı Kararı Çalışma Alanı"
)

st.caption(
    "Yargıtay ve UYAP Emsal'in kendi arama mekanizmasını "
    "kullanan karar çalışma alanı."
)


search_col, button_col = st.columns(
    [8, 1]
)

with search_col:

    query = st.text_input(
        "Karar ara",
        value=st.session_state.query,
        placeholder=(
            'haksız tahrik   '
            'veya   '
            '"haksız tahrik"'
        ),
        label_visibility="collapsed",
    )

with button_col:

    search_clicked = st.button(
        "🔎 Ara",
        type="primary",
        use_container_width=True,
    )


# ============================================================
# YENİ ARAMA
# ============================================================

if search_clicked:

    query = query.strip()

    if not query:

        st.warning(
            "Bir arama kelimesi veya ifade yaz."
        )

        st.stop()

    st.session_state.query = query
    st.session_state.active_query = query

    st.session_state.pages = {
        "Yargıtay": 1,
        "UYAP Emsal": 1,
    }

    st.session_state.selected = {}

    # Yeni aramada eski sayfa cache'lerini temizle.
    st.session_state.search_cache = {}

    st.rerun()


active_query = (
    st.session_state.active_query
)


# ============================================================
# AKTİF ARAMA
# ============================================================

if active_query:

    # --------------------------------------------------------
    # SESSION'LARI ANA THREAD'DE AL
    # --------------------------------------------------------

    sessions = get_sessions()

    # --------------------------------------------------------
    # SAYFA NUMARALARINI ANA THREAD'DE KOPYALA
    # --------------------------------------------------------

    page_numbers = {
        "Yargıtay": int(
            st.session_state.pages[
                "Yargıtay"
            ]
        ),

        "UYAP Emsal": int(
            st.session_state.pages[
                "UYAP Emsal"
            ]
        ),
    }

    results = {}

    missing_sources = []

    # --------------------------------------------------------
    # CACHE KONTROLÜ
    # --------------------------------------------------------

    for source in SOURCES:

        cache_key = (
            source,
            active_query,
            page_numbers[source],
        )

        cached = (
            st.session_state
            .search_cache
            .get(cache_key)
        )

        if cached is not None:
            results[source] = cached
        else:
            missing_sources.append(
                source
            )

    # --------------------------------------------------------
    # YARGITAY + UYAP PARALEL
    # --------------------------------------------------------

    if missing_sources:

        def worker(
            source,
            session,
            query_value,
            page_value,
        ):
            # Worker içinde st.session_state YOK.
            return (
                source,
                official_search(
                    source=source,
                    session=session,
                    query=query_value,
                    ui_page=page_value,
                    new_search=(
                        page_value == 1
                    ),
                ),
            )

        with st.spinner(
            "Yargıtay ve UYAP Emsal aranıyor..."
        ):

            with ThreadPoolExecutor(
                max_workers=2
            ) as executor:

                futures = []

                for source in missing_sources:

                    future = executor.submit(
                        worker,
                        source,
                        sessions[source],
                        active_query,
                        page_numbers[source],
                    )

                    futures.append(
                        future
                    )

                for future in as_completed(
                    futures
                ):

                    try:

                        source, result = (
                            future.result()
                        )

                    except Exception as exc:

                        continue

                    results[source] = result

                    cache_key = (
                        source,
                        active_query,
                        page_numbers[source],
                    )

                    st.session_state.search_cache[
                        cache_key
                    ] = result


    # ========================================================
    # KAYNAK RENDER
    # ========================================================

    def render_source(
        source,
        result,
    ):

        if not result:

            st.error(
                "Sonuç alınamadı."
            )

            return

        if not result["ok"]:

            st.error(
                f"{source} bağlantısı kurulamadı."
            )

            with st.expander(
                "Teknik ayrıntı"
            ):

                st.code(
                    result["error"]
                )

            return


        rows = result["rows"]
        total = result["total"]

        # ----------------------------------------------------
        # TOPLAM
        # ----------------------------------------------------

        st.success(
            f"{total:,} adet karar bulundu."
            .replace(",", ".")
        )

        total_pages = max(
            1,
            (
                total
                + PAGE_SIZE
                - 1
            )
            // PAGE_SIZE
        )


        # ----------------------------------------------------
        # SAYFALAMA
        # ----------------------------------------------------

        p1, p2, p3 = st.columns(
            [1, 3, 1]
        )

        with p1:

            if st.button(
                "◀ Önceki",
                key=f"prev_{source}",
                disabled=(
                    st.session_state
                    .pages[source]
                    <= 1
                ),
                use_container_width=True,
            ):

                st.session_state.pages[
                    source
                ] -= 1

                st.session_state.selected.pop(
                    source,
                    None,
                )

                st.rerun()


        with p2:

            new_page = st.number_input(
                "Sayfa",
                min_value=1,
                max_value=total_pages,
                value=min(
                    st.session_state
                    .pages[source],
                    total_pages,
                ),
                step=1,
                key=f"page_input_{source}",
            )

            if (
                int(new_page)
                !=
                st.session_state
                .pages[source]
            ):

                st.session_state.pages[
                    source
                ] = int(new_page)

                st.session_state.selected.pop(
                    source,
                    None,
                )

                st.rerun()

            st.caption(
                (
                    f"Sayfa "
                    f"{st.session_state.pages[source]:,}"
                    f" / "
                    f"{total_pages:,}"
                )
                .replace(",", ".")
            )


        with p3:

            if st.button(
                "Sonraki ▶",
                key=f"next_{source}",
                disabled=(
                    st.session_state
                    .pages[source]
                    >= total_pages
                ),
                use_container_width=True,
            ):

                st.session_state.pages[
                    source
                ] += 1

                st.session_state.selected.pop(
                    source,
                    None,
                )

                st.rerun()


        # ----------------------------------------------------
        # İLK KARAR OTOMATİK SEÇ
        # ----------------------------------------------------

        if (
            rows
            and source
            not in st.session_state.selected
        ):

            first = next(
                (
                    row
                    for row in rows
                    if row.get("id")
                ),
                None,
            )

            if first:

                st.session_state.selected[
                    source
                ] = first


        # ----------------------------------------------------
        # SOL / SAĞ
        # ----------------------------------------------------

        left, right = st.columns(
            [0.44, 0.56],
            gap="large",
        )


        # ====================================================
        # KARAR LİSTESİ
        # ====================================================

        with left:

            st.markdown(
                "### Karar Listesi"
            )

            if not rows:

                st.info(
                    "Bu sayfada karar bulunamadı."
                )

                return

            start_number = (
                (
                    st.session_state
                    .pages[source]
                    - 1
                )
                * PAGE_SIZE
            )

            for index, row in enumerate(
                rows,
                start=1,
            ):

                selected_row = (
                    st.session_state
                    .selected.get(source)
                )

                is_selected = (
                    selected_row
                    and
                    selected_row.get("id")
                    ==
                    row.get("id")
                )

                with st.container(
                    border=True
                ):

                    st.markdown(
                        f"**"
                        f"{start_number + index}. "
                        f"{row['daire'] or source}"
                        f"**"
                    )

                    st.markdown(
                        f"E. **{row['esas'] or '—'}** "
                        f" · "
                        f"K. **{row['karar'] or '—'}**"
                    )

                    st.caption(
                        row["tarih"]
                        or "Tarih bilgisi yok"
                    )

                    if st.button(
                        (
                            "✓ Açık"
                            if is_selected
                            else "📄 Önizle"
                        ),
                        key=(
                            f"{source}_"
                            f"{st.session_state.pages[source]}_"
                            f"{index}_"
                            f"{row.get('id')}"
                        ),
                        disabled=(
                            not bool(
                                row.get("id")
                            )
                        ),
                        use_container_width=True,
                    ):

                        st.session_state.selected[
                            source
                        ] = row

                        st.rerun()


        # ====================================================
        # KARAR ÖNİZLEME
        # ====================================================

        with right:

            st.markdown(
                "### Karar Önizleme"
            )

            row = (
                st.session_state
                .selected
                .get(source)
            )

            if not row:

                st.info(
                    "Soldaki listeden bir karar seç."
                )

                return


            # ------------------------------------------------
            # DOKÜMAN CACHE
            # ------------------------------------------------

            doc_key = (
                source,
                row["id"],
            )

            text = (
                st.session_state
                .document_cache
                .get(doc_key)
            )

            if text is None:

                with st.spinner(
                    "Karar metni yükleniyor..."
                ):

                    text = official_document(
                        source=source,
                        session=sessions[source],
                        decision_id=row["id"],
                    )

                st.session_state.document_cache[
                    doc_key
                ] = text


            if not text:

                st.warning(
                    "Karar listelendi ancak tam metin alınamadı."
                )

                return


            # ------------------------------------------------
            # KARAR BİLGİLERİ
            # ------------------------------------------------

            st.markdown(
                f"### {row['daire'] or source}"
            )

            info1, info2, info3 = (
                st.columns(3)
            )

            info1.metric(
                "Esas",
                row["esas"] or "—",
            )

            info2.metric(
                "Karar",
                row["karar"] or "—",
            )

            info3.metric(
                "Tarih",
                row["tarih"] or "—",
            )


            # ------------------------------------------------
            # OKUNABİLİR VURGULU METİN
            # ------------------------------------------------

            st.markdown(
                make_highlighted_html(
                    text,
                    active_query,
                ),
                unsafe_allow_html=True,
            )


            # ------------------------------------------------
            # KOPYALANABİLİR METİN
            # ------------------------------------------------

            with st.expander(
                "📋 Kopyalanabilir tam metin"
            ):

                st.caption(
                    "Kutunun içine tıkla → Ctrl+A → Ctrl+C"
                )

                st.text_area(
                    "Tam karar metni",
                    value=text,
                    height=450,
                    key=(
                        f"text_"
                        f"{source}_"
                        f"{row['id']}"
                    ),
                )


            # ------------------------------------------------
            # WORD
            # ------------------------------------------------

            word_bytes = create_word(
                source=source,
                row=row,
                text=text,
                query=active_query,
            )

            download1, download2 = (
                st.columns(2)
            )

            with download1:

                st.download_button(
                    "⬇️ Word Olarak İndir",
                    data=word_bytes,
                    file_name=word_filename(
                        source,
                        row,
                    ),
                    mime=(
                        "application/"
                        "vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    use_container_width=True,
                    key=(
                        f"word_"
                        f"{source}_"
                        f"{row['id']}"
                    ),
                )

            with download2:

                st.download_button(
                    "⬇️ TXT Olarak İndir",
                    data=text.encode(
                        "utf-8"
                    ),
                    file_name=(
                        "yargi_karari.txt"
                    ),
                    mime="text/plain",
                    use_container_width=True,
                    key=(
                        f"txt_"
                        f"{source}_"
                        f"{row['id']}"
                    ),
                )


    # ========================================================
    # SEKME
    # ========================================================

    tab1, tab2, tab3 = st.tabs([
        "⚖️ Yargıtay",
        "🏛️ UYAP Emsal",
        "📊 Birleşik",
    ])


    with tab1:

        render_source(
            "Yargıtay",
            results.get(
                "Yargıtay"
            ),
        )


    with tab2:

        render_source(
            "UYAP Emsal",
            results.get(
                "UYAP Emsal"
            ),
        )


    # ========================================================
    # BİRLEŞİK ÇALIŞMA ALANI
    # ========================================================

    with tab3:

        y = results.get(
            "Yargıtay",
            {}
        )

        u = results.get(
            "UYAP Emsal",
            {}
        )

        c1, c2 = st.columns(2)

        with c1:

            if y.get("ok"):

                st.metric(
                    "Yargıtay Sonuçları",
                    f"{y['total']:,}"
                    .replace(",", "."),
                )

            else:

                st.error(
                    "Yargıtay sonucu alınamadı."
                )


        with c2:

            if u.get("ok"):

                st.metric(
                    "UYAP Emsal Sonuçları",
                    f"{u['total']:,}"
                    .replace(",", "."),
                )

            else:

                st.error(
                    "UYAP sonucu alınamadı."
                )


        st.info(
            "Bu alan daha sonra seçili karar sepeti, "
            "karar karşılaştırma, emsal benzerliği, "
            "TCK/CMK madde analizi, lehe/aleyhe karar ayrımı "
            "ve toplu Word raporu için kullanılacak."
        )


# ============================================================
# ARAMA DAVRANIŞI
# ============================================================

with st.expander(
    "ℹ️ Arama mantığı"
):

    st.markdown(
        """
**Tırnaksız:**

`haksız tahrik`

Yargıtay ve UYAP'a aynen `haksız tahrik` olarak gönderilir.

**Tırnaklı:**

`"haksız tahrik"`

Tırnak işaretleri korunur ve resmî sistemlere aynen gönderilir.

Uygulama kendi eş anlamlılarını veya tahmini arama mantığını devreye sokmaz.  
**Kararı hangi mantıkla bulacağına Yargıtay ve UYAP'ın kendi arama motoru karar verir.**

Bu nedenle amaç, resmî sitelerde gördüğün sonuçlarla Streamlit çalışma alanındaki sonuçların aynı olmasıdır.
"""
    )