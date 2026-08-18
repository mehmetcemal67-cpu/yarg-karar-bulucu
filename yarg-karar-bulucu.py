
import io
import re
import html
import json
from urllib.parse import quote

import requests
import streamlit as st
from bs4 import BeautifulSoup
from docx import Document
from docx.shared import Pt


st.set_page_config(
    page_title="Yargıtay Ceza Karar Arama",
    page_icon="⚖️",
    layout="wide",
)

BASE = "https://karararama.yargitay.gov.tr"
SEARCH_URL = f"{BASE}/aramadetaylist"
DOC_URL = f"{BASE}/getDokuman?id={{}}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": BASE,
    "Referer": BASE + "/",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
}


@st.cache_resource
def get_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def build_payload(
    term,
    page,
    chamber="",
    start_date="",
    end_date="",
    esas_year="",
    esas_first="",
    esas_last="",
    karar_year="",
    karar_first="",
    karar_last="",
):
    # Yargıtay arayüzünde fiilen kullanılan sayfa boyutu 10'dur.
    # Tek, sade istek: önceki sürümdeki 3 payload denemesini kaldırdık.
    data = {
        "arananKelime": term,
        "birimYrgKurulDaire": chamber,
        "esasYil": esas_year,
        "esasIlkSiraNo": esas_first,
        "esasSonSiraNo": esas_last,
        "kararYil": karar_year,
        "kararIlkSiraNo": karar_first,
        "kararSonSiraNo": karar_last,
        "baslangicTarihi": start_date,
        "bitisTarihi": end_date,
        "siralama": "3",
        "siralamaDirection": "desc",
        "pageSize": 10,
        "pageNumber": page,
    }

    # Boş alanları gereksiz yere göndermemek isteği hafifletir.
    data = {k: v for k, v in data.items() if v not in ("", None)}
    return {"data": data}


def normalize_decision(row):
    return {
        "id": clean(row.get("id")),
        "daire": clean(row.get("daire")),
        "esas": clean(row.get("esasNo")),
        "karar": clean(row.get("kararNo")),
        "tarih": clean(row.get("kararTarihi")),
    }


@st.cache_data(ttl=600, show_spinner=False)
def search_yargitay(
    term,
    page,
    chamber,
    start_date,
    end_date,
    esas_year,
    esas_first,
    esas_last,
    karar_year,
    karar_first,
    karar_last,
):
    payload = build_payload(
        term,
        page,
        chamber,
        start_date,
        end_date,
        esas_year,
        esas_first,
        esas_last,
        karar_year,
        karar_first,
        karar_last,
    )

    try:
        r = get_session().post(
            SEARCH_URL,
            json=payload,
            timeout=(5, 15),
        )
        r.raise_for_status()
        obj = r.json()

        # Beklenen yapı: data.data = kararlar, data.recordsTotal = toplam
        block = obj.get("data") or {}
        rows_raw = block.get("data") or []
        total = block.get("recordsTotal") or 0

        rows = [normalize_decision(x) for x in rows_raw if isinstance(x, dict)]

        return {
            "ok": True,
            "rows": rows,
            "total": int(total or 0),
            "error": "",
        }

    except Exception as e:
        return {
            "ok": False,
            "rows": [],
            "total": 0,
            "error": str(e),
        }


def extract_document_payload(raw_text):
    """
    getDokuman cevabında karar metni XML/HTML içinde veya escape edilmiş
    HTML olarak gelebilir. En uzun anlamlı içerik bloğunu seçer.
    """
    raw_text = html.unescape(raw_text or "")

    # 1) XML/HTML parser ile aday alanları dene
    soup = BeautifulSoup(raw_text, "html.parser")

    candidates = []

    for tag in soup.find_all(True):
        txt = tag.get_text("\n", strip=True)
        if len(txt) > 500:
            candidates.append(txt)

    # 2) Tüm sayfa metni
    whole = soup.get_text("\n", strip=True)
    if len(whole) > 500:
        candidates.append(whole)

    # 3) Escape edilmiş HTML varsa ikinci kez çöz
    decoded = html.unescape(whole)
    if "<" in decoded and ">" in decoded:
        soup2 = BeautifulSoup(decoded, "html.parser")
        txt2 = soup2.get_text("\n", strip=True)
        if len(txt2) > 500:
            candidates.append(txt2)

    if not candidates:
        # Son çare: tagleri kaldır
        plain = re.sub(r"<br\s*/?>", "\n", raw_text, flags=re.I)
        plain = re.sub(r"<[^>]+>", "", plain)
        plain = html.unescape(plain)
        candidates.append(plain)

    # Genellikle en uzun blok karar metnidir.
    text = max(candidates, key=len)

    lines = []
    junk = {
        "SUCCESS",
        "ADALET_SUCCESS",
        "İşlem başarıyla gerçekleştirildi!",
    }

    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line or line in junk:
            continue
        lines.append(line)

    return "\n".join(lines)


@st.cache_data(ttl=3600, show_spinner=False)
def get_decision_text(decision_id):
    if not decision_id:
        return ""

    try:
        r = get_session().get(
            DOC_URL.format(quote(str(decision_id), safe="")),
            timeout=(5, 20),
        )
        r.raise_for_status()
        return extract_document_payload(r.text)[:500000]
    except Exception:
        return ""


def make_word(text, row):
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)

    doc.add_heading("Yargıtay Kararı", level=1)

    doc.add_paragraph(f"Daire/Kurul: {row.get('daire') or '-'}")
    doc.add_paragraph(f"Esas No: {row.get('esas') or '-'}")
    doc.add_paragraph(f"Karar No: {row.get('karar') or '-'}")
    doc.add_paragraph(f"Karar Tarihi: {row.get('tarih') or '-'}")
    doc.add_paragraph(
        f"Resmî Kaynak: {DOC_URL.format(row.get('id') or '')}"
    )

    doc.add_heading("Karar Metni", level=2)

    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if para:
            doc.add_paragraph(para)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def safe_filename(row):
    e = (row.get("esas") or "esas").replace("/", "_")
    k = (row.get("karar") or "karar").replace("/", "_")
    return f"Yargitay_E_{e}_K_{k}.docx"


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------

st.title("⚖️ Yargıtay Ceza Karar Arama")
st.caption(
    "Hızlı sayfalama, anlık karar önizleme ve Word indirme."
)

term = st.text_input(
    "Aranacak kelime / ifade",
    placeholder='Örn: haksız tahrik   veya   "haksız tahrik"',
)

with st.expander("Detaylı Arama", expanded=False):
    c1, c2 = st.columns(2)

    with c1:
        chamber = st.text_input(
            "Ceza Dairesi / Kurul",
            placeholder="Örn: 1. Ceza Dairesi",
        )
        start_date = st.text_input(
            "Başlangıç tarihi",
            placeholder="GG.AA.YYYY",
        )
        esas_year = st.text_input("Esas yılı", placeholder="2024")
        esas_first = st.text_input("Esas ilk sıra no")
        esas_last = st.text_input("Esas son sıra no")

    with c2:
        end_date = st.text_input(
            "Bitiş tarihi",
            placeholder="GG.AA.YYYY",
        )
        karar_year = st.text_input("Karar yılı", placeholder="2025")
        karar_first = st.text_input("Karar ilk sıra no")
        karar_last = st.text_input("Karar son sıra no")


if "page" not in st.session_state:
    st.session_state.page = 1

if "active_search" not in st.session_state:
    st.session_state.active_search = None

if st.button("🔎 Ara", type="primary", use_container_width=True):
    st.session_state.page = 1
    st.session_state.active_search = {
        "term": term,
        "chamber": chamber,
        "start_date": start_date,
        "end_date": end_date,
        "esas_year": esas_year,
        "esas_first": esas_first,
        "esas_last": esas_last,
        "karar_year": karar_year,
        "karar_first": karar_first,
        "karar_last": karar_last,
    }
    st.session_state.selected_id = None
    st.rerun()


active = st.session_state.active_search

if active:
    with st.spinner("Yargıtay aranıyor…"):
        result = search_yargitay(
            active["term"],
            st.session_state.page,
            active["chamber"],
            active["start_date"],
            active["end_date"],
            active["esas_year"],
            active["esas_first"],
            active["esas_last"],
            active["karar_year"],
            active["karar_first"],
            active["karar_last"],
        )

    if not result["ok"]:
        st.error("Yargıtay arama servisine erişilemedi.")
        with st.expander("Teknik ayrıntı"):
            st.code(result["error"])
        st.stop()

    rows = result["rows"]
    total = result["total"]
    total_pages = max(1, (total + 9) // 10)

    st.success(f"{total:,} adet karar bulundu.".replace(",", "."))

    # İlk karar otomatik önizlenir.
    if rows and not st.session_state.get("selected_id"):
        st.session_state.selected_id = rows[0]["id"]

    nav1, nav2, nav3 = st.columns([1, 2, 1])

    with nav1:
        if st.button(
            "◀ Önceki",
            disabled=st.session_state.page <= 1,
            use_container_width=True,
        ):
            st.session_state.page -= 1
            st.session_state.selected_id = None
            st.rerun()

    with nav2:
        page_choice = st.number_input(
            "Sayfa",
            min_value=1,
            max_value=total_pages,
            value=min(st.session_state.page, total_pages),
            step=1,
            label_visibility="collapsed",
        )
        if int(page_choice) != st.session_state.page:
            st.session_state.page = int(page_choice)
            st.session_state.selected_id = None
            st.rerun()

        st.caption(
            f"Sayfa {st.session_state.page:,} / {total_pages:,}".replace(",", ".")
        )

    with nav3:
        if st.button(
            "Sonraki ▶",
            disabled=st.session_state.page >= total_pages,
            use_container_width=True,
        ):
            st.session_state.page += 1
            st.session_state.selected_id = None
            st.rerun()

    left, right = st.columns([0.47, 0.53], gap="large")

    with left:
        st.markdown("### Karar Listesi")

        if not rows:
            st.info("Bu sayfada kayıt bulunamadı.")

        for i, row in enumerate(rows, 1):
            selected = row["id"] == st.session_state.get("selected_id")

            with st.container(border=True):
                st.markdown(
                    f"**{row['daire'] or 'Yargıtay'}**  \n"
                    f"E. **{row['esas'] or '—'}** · "
                    f"K. **{row['karar'] or '—'}** · "
                    f"{row['tarih'] or '—'}"
                )

                label = "✓ Açık" if selected else "Önizle / Aç"

                if st.button(
                    label,
                    key=f"row_{st.session_state.page}_{i}_{row['id']}",
                    use_container_width=True,
                    disabled=not bool(row["id"]),
                ):
                    st.session_state.selected_id = row["id"]
                    st.rerun()

    with right:
        st.markdown("### Karar Önizleme")

        selected_row = next(
            (x for x in rows if x["id"] == st.session_state.get("selected_id")),
            rows[0] if rows else None,
        )

        if not selected_row:
            st.info("Soldaki listeden bir karar seç.")
        else:
            with st.spinner("Karar metni yükleniyor…"):
                text = get_decision_text(selected_row["id"])

            if not text:
                st.warning(
                    "Karar kaydı bulundu ancak metin bu istekte alınamadı. "
                    "Aynı karara tekrar tıklamak veya kısa süre sonra yeniden denemek gerekebilir."
                )
            else:
                st.markdown(
                    f"**{selected_row['daire'] or ''}**  \n"
                    f"E. {selected_row['esas'] or '—'} · "
                    f"K. {selected_row['karar'] or '—'} · "
                    f"{selected_row['tarih'] or '—'}"
                )

                # Önizleme hemen görünür; tam metin aynı kutuda kopyalanabilir.
                st.text_area(
                    "Karar metni",
                    value=text,
                    height=620,
                    key=f"text_{selected_row['id']}",
                    help="Kutunun içine tıklayıp Ctrl+A → Ctrl+C ile tamamını kopyalayabilirsin.",
                )

                word_bytes = make_word(text, selected_row)

                d1, d2 = st.columns(2)

                with d1:
                    st.download_button(
                        "⬇️ Word İndir",
                        data=word_bytes,
                        file_name=safe_filename(selected_row),
                        mime=(
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                        use_container_width=True,
                    )

                with d2:
                    st.download_button(
                        "⬇️ TXT İndir",
                        data=text.encode("utf-8"),
                        file_name="yargitay_karari.txt",
                        mime="text/plain",
                        use_container_width=True,
                    )

                st.caption(
                    "Karar ayrı sayfaya yönlendirilmez; metin bu panelde açılır."
                )
