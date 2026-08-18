import io
import re
import json
import html
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


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def pick(d, *keys):
    if not isinstance(d, dict):
        return ""
    lower = {str(k).lower(): v for k, v in d.items()}
    for key in keys:
        if key in d and d[key] not in (None, ""):
            return d[key]
        v = lower.get(str(key).lower())
        if v not in (None, ""):
            return v
    return ""


def recursive_lists(obj):
    found = []
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            found.append(obj)
        for x in obj:
            found.extend(recursive_lists(x))
    elif isinstance(obj, dict):
        for v in obj.values():
            found.extend(recursive_lists(v))
    return found


def looks_like_decision(row):
    if not isinstance(row, dict):
        return False
    keys = " ".join(str(k).lower() for k in row.keys())
    return any(x in keys for x in [
        "esas", "karar", "daire", "birim", "dokuman", "document"
    ])


def find_rows(obj):
    candidates = recursive_lists(obj)
    candidates.sort(
        key=lambda lst: sum(1 for r in lst if looks_like_decision(r)),
        reverse=True
    )
    for lst in candidates:
        if any(looks_like_decision(r) for r in lst):
            return lst
    return []


def find_total(obj):
    priority = [
        "recordsTotal", "totalCount", "totalElements",
        "toplamKayit", "toplamKayıt", "toplam", "total"
    ]

    def walk(x):
        if isinstance(x, dict):
            for k in priority:
                if k in x:
                    try:
                        return int(str(x[k]).replace(".", "").replace(",", ""))
                    except Exception:
                        pass
            for v in x.values():
                r = walk(v)
                if r is not None:
                    return r
        elif isinstance(x, list):
            for v in x:
                r = walk(v)
                if r is not None:
                    return r
        return None

    return walk(obj)


def normalize_row(row):
    decision_id = pick(
        row,
        "id", "dokumanId", "dokumanID", "documentId",
        "kararId", "kararID"
    )

    chamber = pick(
        row,
        "daire", "daireAdi", "birimAdi", "birimYrgKurulDaire",
        "kurulDaire", "birim"
    )

    esas = pick(
        row,
        "esasNo", "esas", "esasNumarasi", "esasNumarası"
    )

    karar = pick(
        row,
        "kararNo", "karar", "kararNumarasi", "kararNumarası"
    )

    tarih = pick(
        row,
        "kararTarihi", "tarih", "kararTarih"
    )

    # Bazı cevaplarda esas/karar yıl + sıra ayrı gelebilir
    if not esas:
        ey = pick(row, "esasYil", "esasYılı", "esasYili")
        en = pick(row, "esasSiraNo", "esasSıraNo")
        if ey and en:
            esas = f"{ey}/{en}"

    if not karar:
        ky = pick(row, "kararYil", "kararYılı", "kararYili")
        kn = pick(row, "kararSiraNo", "kararSıraNo")
        if ky and kn:
            karar = f"{ky}/{kn}"

    return {
        "id": clean(decision_id),
        "daire": clean(chamber),
        "esas": clean(esas),
        "karar": clean(karar),
        "tarih": clean(tarih),
        "raw": row,
    }


def payload_variants(
    term,
    page,
    page_size,
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
    """
    Yargıtay arayüzünün alanlarını kullanır.
    Servis sürümüne göre sayfalama alanlarının konumu değişebildiğinden
    uyumlu birkaç JSON biçimi denenir.
    """
    data = {
        "arananKelime": term,
        "birimYrgKurulDaire": chamber,
        "hukuk": "",
        "ceza": chamber,
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
    }

    return [
        {
            "data": data,
            "pageSize": page_size,
            "pageNumber": page,
        },
        {
            "data": {
                **data,
                "pageSize": page_size,
                "pageNumber": page,
            }
        },
        {
            **data,
            "pageSize": page_size,
            "pageNumber": page,
        },
    ]


@st.cache_data(ttl=900, show_spinner=False)
def search_yargitay(
    term,
    page,
    page_size,
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
    session = requests.Session()
    session.headers.update(HEADERS)

    # Önce ana sayfaya uğrayarak varsa oturum çerezlerini al.
    try:
        session.get(BASE + "/", timeout=15)
    except Exception:
        pass

    errors = []

    for payload in payload_variants(
        term,
        page,
        page_size,
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
        try:
            r = session.post(
                SEARCH_URL,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=30,
            )

            if r.status_code != 200:
                errors.append(f"HTTP {r.status_code}")
                continue

            try:
                obj = r.json()
            except Exception:
                txt = r.text.strip()
                if not txt:
                    errors.append("Boş cevap")
                    continue
                try:
                    obj = json.loads(txt)
                except Exception:
                    errors.append("JSON olmayan cevap")
                    continue

            raw_rows = find_rows(obj)
            total = find_total(obj)

            if raw_rows or total is not None:
                rows = [normalize_row(x) for x in raw_rows]
                rows = [
                    r for r in rows
                    if r["id"] or r["esas"] or r["karar"]
                ]
                return {
                    "ok": True,
                    "rows": rows,
                    "total": total if total is not None else len(rows),
                    "raw": obj,
                    "error": "",
                }

        except Exception as e:
            errors.append(str(e))

    return {
        "ok": False,
        "rows": [],
        "total": 0,
        "raw": None,
        "error": " | ".join(errors[-3:]),
    }


@st.cache_data(ttl=3600, show_spinner=False)
def get_decision_text(decision_id):
    if not decision_id:
        return ""

    url = DOC_URL.format(quote(str(decision_id), safe=""))

    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Referer": BASE + "/",
                "Accept-Language": HEADERS["Accept-Language"],
            },
            timeout=30,
        )
        r.raise_for_status()

        raw = html.unescape(r.text)

        # İçerik çoğu zaman XML/HTML sarmalı içinde HTML karar metnidir.
        soup = BeautifulSoup(raw, "html.parser")

        for tag in soup(["script", "style", "meta"]):
            tag.decompose()

        text = soup.get_text("\n")

        lines = []
        for line in text.splitlines():
            line = re.sub(r"[ \t]+", " ", line).strip()
            if not line:
                continue

            # Teknik cevap metadatasını azalt
            if re.fullmatch(
                r"(SUCCESS|ADALET_SUCCESS|İşlem başarıyla gerçekleştirildi!?)",
                line,
                flags=re.I,
            ):
                continue

            lines.append(line)

        out = "\n".join(lines)

        # HTML metni parser tarafından kaçırıldıysa ikinci yöntem
        if len(out) < 250:
            raw2 = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
            raw2 = re.sub(r"<[^>]+>", "", raw2)
            raw2 = html.unescape(raw2)
            raw2 = re.sub(r"\n{3,}", "\n\n", raw2)
            out = raw2.strip()

        return out[:500000]

    except Exception:
        return ""


def parse_metadata(text, selected):
    data = {
        "daire": selected.get("daire", ""),
        "esas": selected.get("esas", ""),
        "karar": selected.get("karar", ""),
        "tarih": selected.get("tarih", ""),
    }

    if not data["daire"]:
        m = re.search(
            r"((?:Ceza Genel Kurulu|\d{1,2}\.\s*Ceza Dairesi))",
            text[:5000],
            re.I
        )
        if m:
            data["daire"] = clean(m.group(1))

    if not data["esas"]:
        m = re.search(r"(\d{4}/\d+)\s*E\.?", text[:5000], re.I)
        if m:
            data["esas"] = m.group(1)

    if not data["karar"]:
        m = re.search(r"(\d{4}/\d+)\s*K\.?", text[:5000], re.I)
        if m:
            data["karar"] = m.group(1)

    if not data["tarih"]:
        m = re.search(r"\b(\d{1,2}[./]\d{1,2}[./]\d{4})\b", text[:5000])
        if m:
            data["tarih"] = m.group(1)

    return data


def make_word(text, meta, source_url):
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)

    doc.add_heading("Yargıtay Kararı", 1)

    if meta["daire"]:
        doc.add_paragraph(f"Daire/Kurul: {meta['daire']}")
    if meta["esas"]:
        doc.add_paragraph(f"Esas No: {meta['esas']}")
    if meta["karar"]:
        doc.add_paragraph(f"Karar No: {meta['karar']}")
    if meta["tarih"]:
        doc.add_paragraph(f"Karar Tarihi: {meta['tarih']}")

    doc.add_paragraph(f"Resmî Kaynak: {source_url}")

    doc.add_heading("Karar Metni", 2)

    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if para:
            doc.add_paragraph(para)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------

st.title("⚖️ Yargıtay Ceza Karar Arama")
st.caption(
    "Resmî Yargıtay karar veri tabanında doğrudan arama ve karar görüntüleme."
)

with st.sidebar:
    st.header("Sonuç Ayarları")

    page_size = st.selectbox(
        "Sayfa başına karar",
        [10, 20, 50, 100],
        index=2,
    )

    st.info(
        "Yüz binlerce karar tek seferde indirilmez. "
        "Toplam sonuç sayısı gösterilir ve kararlar sayfalar hâlinde açılır. "
        "Bu yöntem çok daha hızlıdır."
    )


search_term = st.text_input(
    "Aranacak kelime / ifade",
    placeholder='Örn: haksız tahrik   veya   "haksız tahrik"',
)

with st.expander("Detaylı Arama", expanded=False):
    a, b = st.columns(2)

    with a:
        chamber = st.text_input(
            "Ceza Dairesi / Kurul",
            placeholder="Örn: Ceza Genel Kurulu veya 1. Ceza Dairesi",
        )

        start_date = st.text_input(
            "Başlangıç tarihi",
            placeholder="GG.AA.YYYY",
        )

        esas_year = st.text_input(
            "Esas yılı",
            placeholder="Örn: 2024",
        )

        esas_first = st.text_input(
            "Esas ilk sıra no",
            placeholder="",
        )

        esas_last = st.text_input(
            "Esas son sıra no",
            placeholder="",
        )

    with b:
        end_date = st.text_input(
            "Bitiş tarihi",
            placeholder="GG.AA.YYYY",
        )

        karar_year = st.text_input(
            "Karar yılı",
            placeholder="Örn: 2025",
        )

        karar_first = st.text_input(
            "Karar ilk sıra no",
            placeholder="",
        )

        karar_last = st.text_input(
            "Karar son sıra no",
            placeholder="",
        )


if "page" not in st.session_state:
    st.session_state.page = 1

c1, c2 = st.columns([5, 1])

with c1:
    do_search = st.button(
        "🔎 Ara",
        type="primary",
        use_container_width=True,
    )

with c2:
    if st.button("Temizle", use_container_width=True):
        st.session_state.clear()
        st.rerun()


if do_search:
    st.session_state.page = 1
    st.session_state.active_search = {
        "term": search_term,
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
    st.session_state.pop("selected", None)


active = st.session_state.get("active_search")

if active:
    if not clean(active["term"]) and not any([
        clean(active["chamber"]),
        clean(active["esas_year"]),
        clean(active["karar_year"]),
        clean(active["start_date"]),
        clean(active["end_date"]),
    ]):
        st.warning("En az bir arama kriteri gir.")
        st.stop()

    with st.spinner("Yargıtay karar veri tabanı sorgulanıyor…"):
        result = search_yargitay(
            active["term"],
            st.session_state.page,
            page_size,
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
        st.error(
            "Yargıtay arama servisine bağlanılamadı. "
            "Servis geçici olarak cevap vermiyor veya istek biçimi değişmiş olabilir."
        )
        if result["error"]:
            with st.expander("Teknik ayrıntı"):
                st.code(result["error"])
    else:
        rows = result["rows"]
        total = result["total"]

        st.success(f"{total:,} adet karar bulundu.".replace(",", "."))

        total_pages = max(1, (total + page_size - 1) // page_size)

        top_prev, top_page, top_next = st.columns([1, 3, 1])

        with top_prev:
            if st.button(
                "◀ Önceki",
                disabled=st.session_state.page <= 1,
                use_container_width=True,
                key="prev_top",
            ):
                st.session_state.page -= 1
                st.session_state.pop("selected", None)
                st.rerun()

        with top_page:
            new_page = st.number_input(
                "Sayfa",
                min_value=1,
                max_value=total_pages,
                value=min(st.session_state.page, total_pages),
                step=1,
            )

            if int(new_page) != st.session_state.page:
                st.session_state.page = int(new_page)
                st.session_state.pop("selected", None)
                st.rerun()

            st.caption(
                f"{st.session_state.page:,} / {total_pages:,} sayfa".replace(",", ".")
            )

        with top_next:
            if st.button(
                "Sonraki ▶",
                disabled=st.session_state.page >= total_pages,
                use_container_width=True,
                key="next_top",
            ):
                st.session_state.page += 1
                st.session_state.pop("selected", None)
                st.rerun()

        st.markdown("### Kararlar")

        if not rows:
            st.info("Bu sayfada karar kaydı dönmedi.")
        else:
            header = st.columns([0.5, 2.2, 1.4, 1.4, 1.3, 1])
            header[0].markdown("**No**")
            header[1].markdown("**Daire/Kurul**")
            header[2].markdown("**Esas**")
            header[3].markdown("**Karar**")
            header[4].markdown("**Tarih**")
            header[5].markdown("**Metin**")

            base_no = (st.session_state.page - 1) * page_size

            for i, row in enumerate(rows, 1):
                cols = st.columns([0.5, 2.2, 1.4, 1.4, 1.3, 1])

                cols[0].write(base_no + i)
                cols[1].write(row["daire"] or "—")
                cols[2].write(row["esas"] or "—")
                cols[3].write(row["karar"] or "—")
                cols[4].write(row["tarih"] or "—")

                with cols[5]:
                    if st.button(
                        "Aç",
                        key=f"open_{st.session_state.page}_{i}_{row['id']}",
                        disabled=not bool(row["id"]),
                        use_container_width=True,
                    ):
                        st.session_state.selected = row
                        st.rerun()

                st.divider()


selected = st.session_state.get("selected")

if selected:
    st.markdown("---")
    st.markdown("## 📄 Karar Metni")

    source_url = DOC_URL.format(quote(str(selected["id"]), safe=""))

    with st.spinner("Kararın tam metni yükleniyor…"):
        full_text = get_decision_text(selected["id"])

    if not full_text:
        st.error(
            "Karar kaydı bulundu ancak tam metin şu anda alınamadı. "
            "Yargıtay sunucusu geçici olarak doküman isteğini reddetmiş olabilir."
        )
    else:
        meta = parse_metadata(full_text, selected)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Daire/Kurul", meta["daire"] or "—")
        m2.metric("Esas", meta["esas"] or "—")
        m3.metric("Karar", meta["karar"] or "—")
        m4.metric("Tarih", meta["tarih"] or "—")

        st.caption(
            "Aşağıdaki alan doğrudan kopyalanabilir. "
            "Kutunun içine tıkla → Ctrl+A → Ctrl+C."
        )

        st.text_area(
            "Tam karar metni",
            value=full_text,
            height=700,
            key=f"decision_{selected['id']}",
        )

        word = make_word(full_text, meta, source_url)

        d1, d2 = st.columns(2)

        with d1:
            filename = (
                f"Yargitay_{meta['esas'].replace('/', '_') or 'karar'}_"
                f"{meta['karar'].replace('/', '_') or ''}.docx"
            )

            st.download_button(
                "⬇️ Word Olarak İndir",
                data=word,
                file_name=filename,
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                use_container_width=True,
            )

        with d2:
            st.download_button(
                "⬇️ TXT Olarak İndir",
                data=full_text.encode("utf-8"),
                file_name="yargitay_karari.txt",
                mime="text/plain",
                use_container_width=True,
            )

        st.caption(f"Resmî kaynak: {source_url}")
