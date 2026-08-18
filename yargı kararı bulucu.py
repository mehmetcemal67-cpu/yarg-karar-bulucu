import re
import time
from urllib.parse import urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from ddgs import DDGS

# ------------------------------------------------------------
# YARGI KARARI BULUCU
# Resmî kaynaklar:
# - Yargıtay Karar Arama
# - Danıştay Karar Arama
# - UYAP Emsal Karar Arama
# - Anayasa Mahkemesi Kararlar Bilgi Bankası
# ------------------------------------------------------------

st.set_page_config(
    page_title="Yargı Kararı Bulucu",
    page_icon="⚖️",
    layout="wide",
)

OFFICIAL_SOURCES = {
    "Yargıtay": {
        "domain": "karararama.yargitay.gov.tr",
        "home": "https://karararama.yargitay.gov.tr/",
    },
    "Danıştay": {
        "domain": "karararama.danistay.gov.tr",
        "home": "https://karararama.danistay.gov.tr/",
    },
    "UYAP Emsal": {
        "domain": "emsal.uyap.gov.tr",
        "home": "https://emsal.uyap.gov.tr/",
    },
    "Anayasa Mahkemesi": {
        "domain": "kararlarbilgibankasi.anayasa.gov.tr",
        "home": "https://kararlarbilgibankasi.anayasa.gov.tr/",
    },
}

# Hukuki sorguları zenginleştirmek için küçük ve güvenli eş anlamlı havuzu.
LEGAL_EXPANSIONS = {
    "işe iade": ["iş sözleşmesinin feshi", "geçersiz fesih", "iş güvencesi"],
    "kıdem tazminatı": ["işçilik alacağı", "kıdem", "fesih"],
    "ihbar tazminatı": ["işçilik alacağı", "ihbar", "fesih"],
    "fazla mesai": ["fazla çalışma", "işçilik alacağı"],
    "mobbing": ["psikolojik taciz", "işyerinde psikolojik taciz"],
    "hakaret": ["TCK 125", "onur şeref saygınlık"],
    "dolandırıcılık": ["TCK 157", "TCK 158", "nitelikli dolandırıcılık"],
    "görevi kötüye kullanma": ["TCK 257"],
    "kasten yaralama": ["TCK 86"],
    "taksirle yaralama": ["TCK 89"],
    "haksız fiil": ["TBK 49", "tazminat"],
    "manevi tazminat": ["TBK 56", "kişilik hakkı"],
    "ayıplı mal": ["6502", "tüketici", "ayıp"],
    "kamulaştırma": ["2942", "kamulaştırma bedeli"],
    "imar": ["imar planı", "3194"],
    "vergi": ["vergi ziyaı", "tarhiyat"],
    "tutuklama": ["kişi hürriyeti ve güvenliği", "ölçülülük"],
    "ifade özgürlüğü": ["Anayasa 26", "ifade hürriyeti"],
    "adil yargılanma": ["Anayasa 36", "adil yargılanma hakkı"],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    )
}


def clean_text(value: str) -> str:
    value = value or ""
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def source_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for name, cfg in OFFICIAL_SOURCES.items():
        if cfg["domain"] in host:
            return name
    return "Diğer"


def is_official(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(cfg["domain"] in host for cfg in OFFICIAL_SOURCES.values())


def normalize_number(value: str) -> str:
    value = clean_text(value)
    value = value.replace("E.", "").replace("K.", "").replace("E:", "").replace("K:", "")
    return clean_text(value)


def build_query(
    keywords: str,
    exact_phrase: str,
    legislation: str,
    chamber: str,
    esas_no: str,
    karar_no: str,
    year_from: str,
    year_to: str,
    domain: str,
    smart_expand: bool,
):
    parts = []

    keywords = clean_text(keywords)
    exact_phrase = clean_text(exact_phrase)
    legislation = clean_text(legislation)
    chamber = clean_text(chamber)
    esas_no = normalize_number(esas_no)
    karar_no = normalize_number(karar_no)

    if exact_phrase:
        parts.append(f'"{exact_phrase}"')

    if keywords:
        parts.append(keywords)

        if smart_expand:
            low = keywords.lower()
            extras = []
            for key, vals in LEGAL_EXPANSIONS.items():
                if key in low:
                    extras.extend(vals[:2])
            if extras:
                parts.append("(" + " OR ".join(f'"{x}"' for x in extras) + ")")

    if legislation:
        # Örn: "TCK 158", "4857 18", "HMK 27"
        parts.append(f'"{legislation}"')

    if chamber:
        parts.append(f'"{chamber}"')

    if esas_no:
        parts.append(f'"{esas_no}"')

    if karar_no:
        parts.append(f'"{karar_no}"')

    if year_from and year_to and year_from == year_to:
        parts.append(str(year_from))
    elif year_from:
        parts.append(str(year_from))
    elif year_to:
        parts.append(str(year_to))

    parts.append(f"site:{domain}")
    return " ".join(parts)


def score_result(row, user_terms):
    text = f"{row.get('title','')} {row.get('body','')} {row.get('href','')}".lower()
    score = 0

    # Resmî kaynak ağırlığı
    if row.get("source") in OFFICIAL_SOURCES:
        score += 30

    for term in user_terms:
        term = term.lower().strip()
        if not term:
            continue
        if term in text:
            score += 12

        # Çok kelimeli ifadenin kelimeleri ayrı ayrı da puan kazandırsın
        for token in re.findall(r"\w+", term, flags=re.UNICODE):
            if len(token) >= 4 and token in text:
                score += 2

    # Karar sayfasına benzeyen adresleri öne al
    href = row.get("href", "").lower()
    if "getdokuman" in href or "/bb/" in href or "/kbb/" in href:
        score += 15

    # E/K formatı görünen başlık/snippet
    if re.search(r"\b20\d{2}/\d+\b", text):
        score += 5

    return score


@st.cache_data(ttl=600, show_spinner=False)
def search_official(query: str, max_results: int):
    results = []
    with DDGS() as ddgs:
        for item in ddgs.text(
            query,
            region="tr-tr",
            safesearch="off",
            max_results=max_results,
        ):
            url = item.get("href") or item.get("url") or ""
            if not url or not is_official(url):
                continue

            results.append(
                {
                    "title": clean_text(item.get("title", "")),
                    "body": clean_text(item.get("body", "")),
                    "href": url,
                    "source": source_from_url(url),
                }
            )
    return results


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_decision_text(url: str):
    """
    Resmî karar sayfası doğrudan HTML metni döndürüyorsa metni getirir.
    JavaScript/captcha/oturum isteyen sayfalarda güvenli biçimde başarısız olur.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()

        ctype = r.headers.get("content-type", "").lower()
        if "text/html" not in ctype and "text/plain" not in ctype:
            return ""

        soup = BeautifulSoup(r.text, "html.parser")

        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()

        text = clean_text(soup.get_text(" "))
        if len(text) < 300:
            return ""

        # Sayfa kabuğunun aşırı uzun ve anlamsız olması hâlinde yine de ilk 30k karakter.
        return text[:30000]
    except Exception:
        return ""


def highlight_excerpt(text: str, terms, max_len=1800):
    if not text:
        return ""

    low = text.lower()
    positions = []
    for term in terms:
        term = clean_text(term).lower()
        if term:
            p = low.find(term)
            if p >= 0:
                positions.append(p)

    start = max(0, (min(positions) if positions else 0) - 500)
    excerpt = text[start : start + max_len]

    if start > 0:
        excerpt = "… " + excerpt
    if start + max_len < len(text):
        excerpt += " …"

    return excerpt


def dedupe(rows):
    seen = set()
    out = []
    for r in rows:
        key = r["href"].split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------

st.title("⚖️ Yargı Kararı Bulucu")
st.caption(
    "Yargıtay, Danıştay, UYAP Emsal ve Anayasa Mahkemesi resmî kaynaklarında "
    "tek ekrandan karar araştırması."
)

with st.sidebar:
    st.header("Arama Ayarları")

    selected_sources = st.multiselect(
        "Kaynaklar",
        list(OFFICIAL_SOURCES.keys()),
        default=list(OFFICIAL_SOURCES.keys()),
    )

    max_per_source = st.slider(
        "Kaynak başına sonuç",
        min_value=5,
        max_value=50,
        value=15,
        step=5,
    )

    smart_expand = st.checkbox(
        "Akıllı hukukî sorgu genişletme",
        value=True,
        help="Bazı yaygın hukukî kavramlara eş anlamlı / ilgili kavramlar ekler.",
    )

    fetch_full = st.checkbox(
        "Bulunabilen karar metnini de getir",
        value=False,
        help="Daha yavaş olabilir. Yalnızca doğrudan erişilebilen resmî karar sayfalarında çalışır.",
    )

col1, col2 = st.columns(2)

with col1:
    keywords = st.text_input(
        "Konu / anahtar kelimeler",
        placeholder="Örn: işçinin WhatsApp yazışması nedeniyle fesih",
    )

    exact_phrase = st.text_input(
        "Tam ifade",
        placeholder="Örn: feshin son çare olması ilkesi",
    )

    legislation = st.text_input(
        "Mevzuat / madde",
        placeholder="Örn: 4857 18  veya  TCK 158  veya  HMK 27",
    )

    chamber = st.text_input(
        "Daire / kurul",
        placeholder="Örn: 9. Hukuk Dairesi, Ceza Genel Kurulu",
    )

with col2:
    esas_no = st.text_input(
        "Esas No",
        placeholder="Örn: 2023/1234",
    )

    karar_no = st.text_input(
        "Karar No",
        placeholder="Örn: 2024/5678",
    )

    y1, y2 = st.columns(2)
    with y1:
        year_from = st.text_input("Başlangıç yılı", placeholder="2020")
    with y2:
        year_to = st.text_input("Bitiş yılı", placeholder="2026")

    sort_option = st.selectbox(
        "Sıralama",
        ["En ilgili", "Kaynağa göre"],
    )

st.markdown("#### Örnek aramalar")
examples = st.columns(4)
examples[0].code("mobbing manevi tazminat")
examples[1].code("TCK 158 banka hesabı")
examples[2].code("işe iade feshin son çare olması")
examples[3].code("ifade özgürlüğü sosyal medya")

search_clicked = st.button("🔎 Kararları Ara", type="primary", use_container_width=True)

if search_clicked:
    if not selected_sources:
        st.error("En az bir kaynak seçmelisin.")
        st.stop()

    if not any([
        clean_text(keywords),
        clean_text(exact_phrase),
        clean_text(legislation),
        clean_text(chamber),
        clean_text(esas_no),
        clean_text(karar_no),
    ]):
        st.warning("Arama için en az bir konu, ifade, mevzuat, daire veya karar numarası gir.")
        st.stop()

    user_terms = [
        keywords,
        exact_phrase,
        legislation,
        chamber,
        normalize_number(esas_no),
        normalize_number(karar_no),
    ]
    user_terms = [x for x in user_terms if clean_text(x)]

    all_results = []
    queries_used = []

    progress = st.progress(0)
    status = st.empty()

    for idx, source_name in enumerate(selected_sources, start=1):
        cfg = OFFICIAL_SOURCES[source_name]
        query = build_query(
            keywords=keywords,
            exact_phrase=exact_phrase,
            legislation=legislation,
            chamber=chamber,
            esas_no=esas_no,
            karar_no=karar_no,
            year_from=clean_text(year_from),
            year_to=clean_text(year_to),
            domain=cfg["domain"],
            smart_expand=smart_expand,
        )
        queries_used.append((source_name, query))
        status.write(f"**{source_name}** aranıyor…")

        try:
            rows = search_official(query, max_per_source)
            all_results.extend(rows)
        except Exception as e:
            st.warning(f"{source_name} aranırken geçici hata oluştu: {e}")

        progress.progress(idx / len(selected_sources))
        time.sleep(0.15)

    status.empty()
    progress.empty()

    all_results = dedupe(all_results)

    for row in all_results:
        row["score"] = score_result(row, user_terms)

    if sort_option == "En ilgili":
        all_results.sort(key=lambda x: x["score"], reverse=True)
    else:
        all_results.sort(key=lambda x: (x["source"], -x["score"]))

    st.session_state["last_results"] = all_results
    st.session_state["last_terms"] = user_terms
    st.session_state["queries_used"] = queries_used


results = st.session_state.get("last_results", [])
user_terms = st.session_state.get("last_terms", [])

if results:
    st.success(f"{len(results)} resmî sonuç bulundu.")

    # Filtre
    found_sources = sorted({x["source"] for x in results})
    filter_sources = st.multiselect(
        "Sonuçlarda kaynak filtresi",
        found_sources,
        default=found_sources,
        key="result_source_filter",
    )

    filtered = [r for r in results if r["source"] in filter_sources]

    # CSV dışa aktarım
    export_df = pd.DataFrame(
        [
            {
                "Kaynak": r["source"],
                "Başlık": r["title"],
                "Özet": r["body"],
                "Bağlantı": r["href"],
                "İlgi Puanı": r["score"],
            }
            for r in filtered
        ]
    )

    st.download_button(
        "⬇️ Sonuç listesini CSV indir",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="yargi_karari_sonuclari.csv",
        mime="text/csv",
    )

    st.markdown("---")

    for i, row in enumerate(filtered, start=1):
        title = row["title"] or "Başlıksız karar sonucu"
        with st.expander(
            f"{i}. [{row['source']}] {title}",
            expanded=(i <= 3),
        ):
            c1, c2 = st.columns([3, 1])

            with c1:
                if row["body"]:
                    st.write(row["body"])

                st.markdown(f"**Resmî bağlantı:** {row['href']}")

            with c2:
                st.metric("İlgi puanı", row["score"])
                st.link_button("Kararı resmî sitede aç", row["href"])

            if fetch_full:
                with st.spinner("Karar metni okunuyor…"):
                    full_text = fetch_decision_text(row["href"])

                if full_text:
                    excerpt = highlight_excerpt(full_text, user_terms)
                    st.markdown("**Karar metninden ilgili bölüm:**")
                    st.write(excerpt)

                    with st.expander("Daha uzun metni göster"):
                        st.text(full_text[:15000])
                else:
                    st.info(
                        "Bu sonuçta karar metni doğrudan alınamadı. "
                        "Resmî bağlantıyı açarak görüntüleyebilirsin."
                    )

elif "last_results" in st.session_state:
    st.info(
        "Sonuç bulunamadı. Daha kısa bir hukukî ifade dene veya "
        "tam ifade alanını boşaltıp anahtar kelimelerle ara."
    )

with st.expander("Kullanılan resmî kaynaklar ve arama mantığı"):
    for name, cfg in OFFICIAL_SOURCES.items():
        st.markdown(f"- **{name}:** {cfg['home']}")

    st.write(
        "Uygulama sonuçları resmî yargı alan adlarıyla sınırlar. "
        "Arama motoru yalnızca bu alan adlarındaki herkese açık sayfaları bulmak için kullanılır. "
        "Son karar metni ve doğrulama için daima resmî bağlantı esas alınmalıdır."
    )

with st.expander("Son aramada oluşturulan teknik sorgular"):
    for name, query in st.session_state.get("queries_used", []):
        st.code(f"{name}: {query}")
