
import io
import re
import html
import time
import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, quote_plus

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from ddgs import DDGS
from docx import Document
from docx.shared import Pt
from rapidfuzz import fuzz


# ============================================================
# ⚖️ CEZA İÇTİHAT ARAMA SİSTEMİ
# Yargıtay + UYAP Emsal öncelikli
# ============================================================

st.set_page_config(
    page_title="Ceza İçtihat Bulucu",
    page_icon="⚖️",
    layout="wide",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
}

SOURCES = {
    "Yargıtay": {
        "domain": "karararama.yargitay.gov.tr",
        "direct_hint": "getDokuman",
        "priority": 100,
    },
    "UYAP Emsal": {
        "domain": "emsal.uyap.gov.tr",
        "direct_hint": "",
        "priority": 80,
    },
    "AYM": {
        "domain": "kararlarbilgibankasi.anayasa.gov.tr",
        "direct_hint": "/kbb/",
        "priority": 40,
    },
}

# ------------------------------------------------------------
# CEZA HUKUKU KAVRAM HAVUZU
# ------------------------------------------------------------

CRIMINAL_CONCEPTS = {
    "haksız tahrik": {
        "articles": ["TCK 29", "5237 29"],
        "terms": [
            "tahrik indirimi",
            "haksız fiil",
            "hiddet veya şiddetli elem",
            "haksız hareket",
            "tahrik hükümleri",
            "asgari oranda indirim",
            "azami oranda indirim",
            "tahrik derecesi",
            "meşru savunma",
            "karşılıklı hakaret",
            "küfür",
            "yaralama",
        ],
    },
    "meşru savunma": {
        "articles": ["TCK 25", "5237 25"],
        "terms": [
            "meşru müdafaa",
            "haksız saldırı",
            "saldırı ile savunmada orantı",
            "savunmada zorunluluk",
            "sınırın aşılması",
            "TCK 27",
            "haksız tahrik",
        ],
    },
    "kasten öldürme": {
        "articles": ["TCK 81", "TCK 82", "5237 81", "5237 82"],
        "terms": [
            "öldürme kastı",
            "olası kast",
            "doğrudan kast",
            "nitelikli kasten öldürme",
            "tasarlama",
            "canavarca his",
            "haksız tahrik",
            "meşru savunma",
        ],
    },
    "kasten yaralama": {
        "articles": ["TCK 86", "TCK 87", "5237 86", "5237 87"],
        "terms": [
            "yaralama",
            "silahla yaralama",
            "neticesi sebebiyle ağırlaşmış yaralama",
            "kemik kırığı",
            "hayati tehlike",
            "basit tıbbi müdahale",
            "haksız tahrik",
        ],
    },
    "tehdit": {
        "articles": ["TCK 106", "5237 106"],
        "terms": [
            "tehdit suçu",
            "korkutma",
            "sair kötülük",
            "silahla tehdit",
            "birden fazla kişiyle tehdit",
            "mesajla tehdit",
        ],
    },
    "hakaret": {
        "articles": ["TCK 125", "TCK 129", "5237 125", "5237 129"],
        "terms": [
            "onur şeref ve saygınlık",
            "sövme",
            "matufiyet",
            "ihtilat",
            "karşılıklı hakaret",
            "haksız fiile tepki",
            "sosyal medya hakaret",
        ],
    },
    "dolandırıcılık": {
        "articles": ["TCK 157", "TCK 158", "5237 157", "5237 158"],
        "terms": [
            "hileli davranış",
            "aldatma",
            "haksız yarar",
            "nitelikli dolandırıcılık",
            "bilişim sistemleri",
            "banka veya kredi kurumu",
            "internet dolandırıcılığı",
        ],
    },
    "nitelikli dolandırıcılık": {
        "articles": ["TCK 158", "5237 158"],
        "terms": [
            "bilişim sistemlerinin araç olarak kullanılması",
            "banka veya kredi kurumu",
            "ticari faaliyet",
            "hileli davranış",
            "haksız yarar",
            "internet ilanı",
            "banka hesabı",
        ],
    },
    "yağma": {
        "articles": ["TCK 148", "TCK 149", "5237 148", "5237 149"],
        "terms": [
            "cebir veya tehdit",
            "nitelikli yağma",
            "malın teslimi",
            "senedin yağması",
            "silahla yağma",
        ],
    },
    "hırsızlık": {
        "articles": ["TCK 141", "TCK 142", "5237 141", "5237 142"],
        "terms": [
            "zilyedin rızası",
            "taşınır mal",
            "nitelikli hırsızlık",
            "gece vakti",
            "muhafaza altına alınmış eşya",
        ],
    },
    "uyuşturucu ticareti": {
        "articles": ["TCK 188", "5237 188"],
        "terms": [
            "uyuşturucu madde ticareti",
            "satma",
            "nakletme",
            "depolama",
            "ticaret kastı",
            "kullanmak için bulundurma",
            "TCK 191",
        ],
    },
    "uyuşturucu kullanma": {
        "articles": ["TCK 191", "5237 191"],
        "terms": [
            "kullanmak için uyuşturucu bulundurma",
            "uyuşturucu kullanma",
            "tedavi ve denetimli serbestlik",
            "ticaret kastı",
            "TCK 188",
        ],
    },
    "cinsel saldırı": {
        "articles": ["TCK 102", "5237 102"],
        "terms": [
            "cinsel dokunulmazlık",
            "rıza",
            "nitelikli cinsel saldırı",
            "sarkıntılık",
            "beden dokunulmazlığı",
        ],
    },
    "çocuğun cinsel istismarı": {
        "articles": ["TCK 103", "5237 103"],
        "terms": [
            "çocuğun cinsel istismarı",
            "sarkıntılık",
            "nitelikli istismar",
            "çocuk beyanı",
            "mağdur beyanı",
        ],
    },
    "görevi kötüye kullanma": {
        "articles": ["TCK 257", "5237 257"],
        "terms": [
            "görevin gereklerine aykırı davranma",
            "ihmal veya gecikme",
            "kamu görevlisi",
            "mağduriyet",
            "haksız menfaat",
        ],
    },
    "zimmet": {
        "articles": ["TCK 247", "5237 247"],
        "terms": [
            "zimmet suçu",
            "kamu görevlisi",
            "görevi nedeniyle zilyetlik",
            "mal edinme",
            "kullanma zimmeti",
        ],
    },
    "rüşvet": {
        "articles": ["TCK 252", "5237 252"],
        "terms": [
            "rüşvet suçu",
            "kamu görevlisi",
            "menfaat sağlama",
            "görevin ifasıyla ilgili iş",
        ],
    },
    "suç örgütü": {
        "articles": ["TCK 220", "5237 220"],
        "terms": [
            "suç işlemek amacıyla örgüt",
            "örgüt üyeliği",
            "hiyerarşik yapı",
            "organik bağ",
            "süreklilik çeşitlilik yoğunluk",
        ],
    },
    "hukuka aykırı delil": {
        "articles": ["CMK 206", "CMK 217", "5271 206", "5271 217"],
        "terms": [
            "yasak delil",
            "hukuka aykırı elde edilen delil",
            "delil değerlendirme yasağı",
            "hukuka aykırı arama",
            "hukuka aykırı elkoyma",
        ],
    },
    "arama kararı": {
        "articles": ["CMK 116", "CMK 119", "5271 116", "5271 119"],
        "terms": [
            "adli arama",
            "makul şüphe",
            "arama emri",
            "hukuka aykırı arama",
            "önleme araması",
        ],
    },
    "tutuklama": {
        "articles": ["CMK 100", "5271 100"],
        "terms": [
            "kuvvetli suç şüphesi",
            "tutuklama nedeni",
            "ölçülülük",
            "adli kontrol",
            "kaçma şüphesi",
            "delilleri karartma",
        ],
    },
    "şüpheden sanık yararlanır": {
        "articles": [],
        "terms": [
            "in dubio pro reo",
            "her türlü şüpheden uzak",
            "kesin ve inandırıcı delil",
            "mahkumiyete yeter delil",
            "beraat",
        ],
    },
    "olası kast": {
        "articles": ["TCK 21", "5237 21"],
        "terms": [
            "olursa olsun",
            "neticeyi öngörme",
            "kabullenme",
            "bilinçli taksir",
            "doğrudan kast",
        ],
    },
    "bilinçli taksir": {
        "articles": ["TCK 22", "5237 22"],
        "terms": [
            "öngörülen neticeyi istememe",
            "olası kast",
            "taksir",
            "dikkat ve özen yükümlülüğü",
        ],
    },
}


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def tr_lower(value):
    return clean_text(value).replace("I", "ı").replace("İ", "i").lower()


def normalize_for_match(value):
    value = tr_lower(value)
    repl = {"ç":"c", "ğ":"g", "ı":"i", "ö":"o", "ş":"s", "ü":"u"}
    for a, b in repl.items():
        value = value.replace(a, b)
    return value


def concept_score(query, concept):
    q = normalize_for_match(query)
    c = normalize_for_match(concept)
    if not q or not c:
        return 0
    if c in q or q in c:
        return 100
    return fuzz.token_set_ratio(q, c)


def detect_concepts(query, limit=5):
    scored = []
    for concept in CRIMINAL_CONCEPTS:
        s = concept_score(query, concept)
        if s >= 55:
            scored.append((concept, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def expand_criminal_query(query):
    query = clean_text(query)
    primary = [query]
    related = []
    articles = []

    detected = detect_concepts(query)

    for concept, _ in detected:
        if concept not in primary:
            related.append(concept)
        data = CRIMINAL_CONCEPTS[concept]
        related.extend(data["terms"])
        articles.extend(data["articles"])

    # Kullanıcı doğrudan TCK/CMK maddesi yazdıysa aynen koru
    for m in re.findall(r"\b(?:TCK|CMK)\s*\d+\b", query, flags=re.I):
        articles.append(clean_text(m.upper()))

    def unique(seq):
        out = []
        seen = set()
        for x in seq:
            k = tr_lower(x)
            if k and k not in seen:
                seen.add(k)
                out.append(clean_text(x))
        return out

    return unique(primary), unique(related)[:30], unique(articles)[:12], detected


def is_direct_decision_url(url):
    if not url:
        return False

    host = urlparse(url).netloc.lower()
    low = url.lower()

    if "karararama.yargitay.gov.tr" in host:
        return "getdokuman" in low and "id=" in low

    if "kararlarbilgibankasi.anayasa.gov.tr" in host:
        return "/kbb/" in low and "/search/" not in low

    if "emsal.uyap.gov.tr" in host:
        # UYAP bağlantıları farklılaşabildiği için kayıt kimliği/karar göstergesi aranır.
        return any(x in low for x in ["id=", "karar", "dokuman", "getdocument"])

    return False


def source_from_url(url):
    host = urlparse(url).netloc.lower()
    if "yargitay.gov.tr" in host:
        return "Yargıtay"
    if "uyap.gov.tr" in host:
        return "UYAP Emsal"
    if "anayasa.gov.tr" in host:
        return "AYM"
    return "Diğer"


def build_search_queries(query, related, articles, start_year, end_year, depth):
    """
    Ceza kararlarını çok daha geniş yakalamak için sorguyu:
    - doğrudan ifade
    - madde
    - ilişkili ceza kavramları
    - yıl dilimleri
    - Ceza Dairesi / Ceza Genel Kurulu
    şeklinde çoğaltır.
    """
    queries = []

    base_terms = [query] + articles[:6] + related[:10]

    # Ana sorgular
    for term in base_terms:
        queries.append(f'"{term}"')

    # Asıl kavram + ilişkili kavram kombinasyonları
    for term in (articles[:4] + related[:8]):
        queries.append(f'"{query}" "{term}"')

    # Yıllara bölmek arama motoru indeksinden daha fazla benzersiz karar çekebilir.
    years = list(range(int(start_year), int(end_year) + 1))
    if depth == "Hızlı":
        sampled_years = years[-5:]
    elif depth == "Dengeli":
        sampled_years = years[-10:]
    else:
        sampled_years = years

    for y in sampled_years:
        queries.append(f'"{query}" {y} "Ceza Dairesi"')
        queries.append(f'"{query}" {y} "Ceza Genel Kurulu"')

        # Maddelerle yıl taraması
        for article in articles[:2]:
            queries.append(f'"{article}" {y} "Ceza Dairesi"')

    # Ceza dairelerine yönelik ek tarama
    if depth == "Derin":
        for daire in range(1, 24):
            queries.append(f'"{query}" "{daire}. Ceza Dairesi"')

    # Tekilleştir
    out = []
    seen = set()
    for q in queries:
        q = clean_text(q)
        if q and q not in seen:
            seen.add(q)
            out.append(q)

    limits = {"Hızlı": 20, "Dengeli": 45, "Derin": 100}
    return out[:limits[depth]]


def ddgs_search_one(search_query, domain, max_results=25):
    # Yargıtay'da yalnız doğrudan getDokuman sonuçlarını hedefle
    if domain == "karararama.yargitay.gov.tr":
        q = f'{search_query} site:{domain}/getDokuman'
    else:
        q = f'{search_query} site:{domain}'

    rows = []

    try:
        with DDGS() as ddgs:
            results = ddgs.text(
                q,
                region="tr-tr",
                safesearch="off",
                max_results=max_results,
            )
            if not results:
                return []

            for item in results:
                url = item.get("href") or item.get("url") or ""
                if not is_direct_decision_url(url):
                    continue

                rows.append({
                    "title": clean_text(item.get("title", "")),
                    "snippet": clean_text(item.get("body", "")),
                    "url": url,
                    "source": source_from_url(url),
                })
    except Exception:
        return []

    return rows


def bing_fallback(search_query, domain, max_results=20):
    if domain == "karararama.yargitay.gov.tr":
        q = quote_plus(f'{search_query} site:{domain}/getDokuman')
    else:
        q = quote_plus(f'{search_query} site:{domain}')

    url = f"https://www.bing.com/search?q={q}&count={max_results}&setlang=tr"

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        rows = []

        for item in soup.select("li.b_algo"):
            a = item.select_one("h2 a")
            if not a:
                continue

            href = a.get("href", "")
            if not is_direct_decision_url(href):
                continue

            p = item.select_one(".b_caption p")

            rows.append({
                "title": clean_text(a.get_text(" ")),
                "snippet": clean_text(p.get_text(" ") if p else ""),
                "url": href,
                "source": source_from_url(href),
            })

        return rows[:max_results]
    except Exception:
        return []


@st.cache_data(ttl=1800, show_spinner=False)
def cached_search(search_query, domain, max_results):
    rows = ddgs_search_one(search_query, domain, max_results)

    # Her sorguda fallback yapmayarak hız korunur.
    return rows


def dedupe_results(rows):
    out = []
    seen_urls = set()

    for row in rows:
        key = row["url"].split("#")[0]
        if key in seen_urls:
            continue
        seen_urls.add(key)
        out.append(row)

    return out


def relevance_score(row, query, related, articles):
    text = normalize_for_match(
        f"{row.get('title','')} {row.get('snippet','')}"
    )

    score = 0

    q = normalize_for_match(query)
    if q and q in text:
        score += 50
    else:
        score += int(fuzz.partial_ratio(q, text) * 0.25)

    for article in articles:
        if normalize_for_match(article) in text:
            score += 12

    related_hits = 0
    for term in related[:20]:
        if normalize_for_match(term) in text:
            related_hits += 1

    score += min(related_hits * 5, 35)

    if row["source"] == "Yargıtay":
        score += 20
    elif row["source"] == "UYAP Emsal":
        score += 10

    return score


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_decision_text(url):
    """
    Doğrudan resmî karar bağlantısını okuyup temiz metne çevirir.
    Yargıtay getDokuman çıktısı XML/HTML benzeri içerik döndürebilir.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()

        raw = r.text

        # HTML entity'lerini çöz
        raw = html.unescape(raw)

        # XML/HTML temizliği
        soup = BeautifulSoup(raw, "html.parser")

        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()

        # Satır yapısını mümkün olduğunca koru
        text = soup.get_text("\n")

        lines = []
        for line in text.splitlines():
            line = re.sub(r"[ \t]+", " ", line).strip()
            if line:
                lines.append(line)

        cleaned = "\n".join(lines)

        # Eğer parser çok az metin çıkardıysa tagleri regex ile temizleyerek tekrar dene
        if len(cleaned) < 200:
            cleaned = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
            cleaned = re.sub(r"<[^>]+>", "", cleaned)
            cleaned = html.unescape(cleaned)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            cleaned = cleaned.strip()

        return cleaned[:250000]
    except Exception as e:
        return ""


def parse_metadata(text, fallback_title=""):
    sample = f"{fallback_title}\n{text[:5000]}"

    chamber = ""
    esas = ""
    karar = ""
    date = ""

    m = re.search(
        r"((?:Ceza Genel Kurulu|\d{1,2}\.\s*Ceza Dairesi|Ceza Dairesi))",
        sample,
        flags=re.I,
    )
    if m:
        chamber = clean_text(m.group(1))

    m = re.search(r"(\d{4}/\d+)\s*E\.?", sample, flags=re.I)
    if m:
        esas = m.group(1)

    m = re.search(r"(\d{4}/\d+)\s*K\.?", sample, flags=re.I)
    if m:
        karar = m.group(1)

    # dd.mm.yyyy veya dd/mm/yyyy
    m = re.search(r"\b(\d{1,2}[./]\d{1,2}[./]\d{4})\b", sample)
    if m:
        date = m.group(1)

    return {
        "chamber": chamber,
        "esas": esas,
        "karar": karar,
        "date": date,
    }


def make_docx(title, url, text, metadata):
    doc = Document()

    styles = doc.styles
    styles["Normal"].font.name = "Arial"
    styles["Normal"].font.size = Pt(11)

    doc.add_heading("Yargı Kararı", level=1)

    if metadata.get("chamber"):
        doc.add_paragraph(f"Daire/Kurul: {metadata['chamber']}")
    if metadata.get("esas"):
        doc.add_paragraph(f"Esas No: {metadata['esas']}")
    if metadata.get("karar"):
        doc.add_paragraph(f"Karar No: {metadata['karar']}")
    if metadata.get("date"):
        doc.add_paragraph(f"Tarih: {metadata['date']}")

    doc.add_paragraph(f"Kaynak: {url}")

    doc.add_heading("Karar Metni", level=2)

    # Çok uzun metni paragraf/parça bazında ekle
    for block in re.split(r"\n{2,}", text):
        block = block.strip()
        if block:
            doc.add_paragraph(block)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def safe_filename(metadata):
    parts = ["yargi_karari"]

    if metadata.get("chamber"):
        parts.append(re.sub(r"[^A-Za-z0-9]+", "_", normalize_for_match(metadata["chamber"])))
    if metadata.get("esas"):
        parts.append("E_" + metadata["esas"].replace("/", "_"))
    if metadata.get("karar"):
        parts.append("K_" + metadata["karar"].replace("/", "_"))

    return "_".join(parts)[:150] + ".docx"


# ============================================================
# UI
# ============================================================

st.title("⚖️ Ceza İçtihat Bulucu")
st.caption(
    "Ceza yargılaması öncelikli; Yargıtay ve UYAP Emsal kararlarını geniş kavram havuzuyla tarar."
)

with st.sidebar:
    st.header("Tarama Ayarları")

    sources = st.multiselect(
        "Kaynaklar",
        ["Yargıtay", "UYAP Emsal", "AYM"],
        default=["Yargıtay", "UYAP Emsal"],
    )

    depth = st.selectbox(
        "Tarama derinliği",
        ["Hızlı", "Dengeli", "Derin"],
        index=1,
        help=(
            "Derin tarama yıllara ve Ceza Dairelerine bölünmüş daha fazla sorgu üretir. "
            "Daha fazla karar bulabilir ancak daha uzun sürer."
        ),
    )

    max_results_per_query = st.slider(
        "Sorgu başına aday",
        10, 50, 30, 5
    )

    workers = st.slider(
        "Paralel sorgu",
        4, 16, 10, 1
    )

    st.divider()

    st.caption(
        "Not: Arama motorlarının resmî karar sitelerini indeksleme kapsamı sınırlı olabilir. "
        "Bu nedenle bulunan sayı, resmî veri tabanındaki toplam eşleşme sayısından daha düşük olabilir."
    )


query = st.text_area(
    "Ceza hukuku konusu / doğal dilde olay",
    height=110,
    placeholder=(
        "Örn: haksız tahrik\n"
        "veya: sanık mağdurun küfür etmesi üzerine bıçakla yaralıyor, tahrik indirimi"
    ),
)

c1, c2, c3 = st.columns(3)

with c1:
    start_year = st.number_input("Başlangıç yılı", 2000, 2030, 2015)

with c2:
    end_year = st.number_input("Bitiş yılı", 2000, 2030, 2026)

with c3:
    target_count = st.selectbox(
        "Hedeflenen karar havuzu",
        [50, 100, 200, 300, 500],
        index=2,
        help="Bu bir hedef üst sınırdır; indeks kapsamına göre daha az sonuç bulunabilir."
    )

search_button = st.button(
    "🔎 Ceza Kararlarını Tara",
    type="primary",
    use_container_width=True,
)


if search_button:
    if not clean_text(query):
        st.warning("Bir ceza hukuku konusu veya olay yaz.")
        st.stop()

    if start_year > end_year:
        st.error("Başlangıç yılı bitiş yılından büyük olamaz.")
        st.stop()

    primary, related, articles, detected = expand_criminal_query(query)

    st.session_state["query"] = query
    st.session_state["related"] = related
    st.session_state["articles"] = articles
    st.session_state["detected"] = detected

    search_queries = build_search_queries(
        query=query,
        related=related,
        articles=articles,
        start_year=start_year,
        end_year=end_year,
        depth=depth,
    )

    domains = []
    for name in sources:
        domains.append((name, SOURCES[name]["domain"]))

    tasks = []
    for source_name, domain in domains:
        for q in search_queries:
            tasks.append((source_name, domain, q))

    progress = st.progress(0)
    status = st.empty()

    all_rows = []
    total = max(1, len(tasks))
    completed = 0

    def worker(source_name, domain, q):
        rows = cached_search(q, domain, max_results_per_query)
        return source_name, q, rows

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(worker, s, d, q): (s, q)
            for s, d, q in tasks
        }

        for future in as_completed(futures):
            completed += 1
            progress.progress(completed / total)

            source_name, sq = futures[future]
            status.caption(f"{source_name} taranıyor • {completed}/{total}")

            try:
                _, used_query, rows = future.result()
            except Exception:
                rows = []
                used_query = sq

            for row in rows:
                row["search_query"] = used_query
                all_rows.append(row)

            # Hedef sayıya ulaşıldığında devam eden taskler yine tamamlanabilir;
            # fakat gösterimde target_count ile sınırlarız.

    progress.empty()
    status.empty()

    rows = dedupe_results(all_rows)

    for row in rows:
        row["score"] = relevance_score(
            row,
            query,
            related,
            articles,
        )

    rows.sort(
        key=lambda r: (
            r["source"] == "Yargıtay",
            r["score"]
        ),
        reverse=True,
    )

    rows = rows[:target_count]

    st.session_state["results"] = rows
    st.session_state.pop("selected_url", None)
    st.session_state.pop("selected_title", None)


# ------------------------------------------------------------
# KAVRAM GENİŞLETMESİ
# ------------------------------------------------------------

detected = st.session_state.get("detected", [])
related = st.session_state.get("related", [])
articles = st.session_state.get("articles", [])

if detected:
    with st.expander("🧠 Ceza hukuku kavram genişletmesi"):
        st.write(
            "**Tespit edilen kavramlar:** " +
            ", ".join([x[0] for x in detected])
        )

        if articles:
            st.write("**İlgili maddeler:** " + ", ".join(articles))

        if related:
            st.write("**İlişkili terimler:** " + ", ".join(related))


# ------------------------------------------------------------
# KARAR LİSTESİ
# ------------------------------------------------------------

results = st.session_state.get("results", [])

if results:
    st.success(f"{len(results)} benzersiz doğrudan karar bağlantısı bulundu.")

    # Sonuçları tablo görünümünde özetle
    preview = pd.DataFrame([
        {
            "No": i,
            "Kaynak": r["source"],
            "Karar": r["title"][:120],
            "İlgi": r["score"],
        }
        for i, r in enumerate(results, 1)
    ])

    st.dataframe(
        preview,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Kararlar")

    for i, row in enumerate(results, 1):
        title = row["title"] or f"Karar {i}"

        col_a, col_b = st.columns([5, 1])

        with col_a:
            st.markdown(f"**{i}. {title}**")
            if row.get("snippet"):
                st.caption(row["snippet"][:450])

        with col_b:
            if st.button(
                "Kararı Aç",
                key=f"open_{i}_{abs(hash(row['url']))}",
                use_container_width=True,
            ):
                st.session_state["selected_url"] = row["url"]
                st.session_state["selected_title"] = title
                st.rerun()

        st.divider()

elif "results" in st.session_state:
    st.warning(
        "Doğrudan açılabilen karar bağlantısı bulunamadı. "
        "Derin taramayı veya daha geniş yıl aralığını dene."
    )


# ------------------------------------------------------------
# KARAR GÖRÜNTÜLEYİCİ
# ------------------------------------------------------------

selected_url = st.session_state.get("selected_url")
selected_title = st.session_state.get("selected_title", "Yargı Kararı")

if selected_url:
    st.markdown("---")
    st.markdown("## 📄 Karar Görüntüleyici")

    with st.spinner("Karar metni resmî kaynaktan alınıyor…"):
        decision_text = fetch_decision_text(selected_url)

    if not decision_text:
        st.error(
            "Karar bağlantısı bulundu ancak karar metni bu oturumda otomatik okunamadı. "
            "Kaynak sunucu geçici olarak bağlantıyı engelliyor olabilir."
        )
    else:
        metadata = parse_metadata(decision_text, selected_title)

        info_cols = st.columns(4)

        info_cols[0].metric(
            "Daire/Kurul",
            metadata["chamber"] or "—"
        )
        info_cols[1].metric(
            "Esas",
            metadata["esas"] or "—"
        )
        info_cols[2].metric(
            "Karar",
            metadata["karar"] or "—"
        )
        info_cols[3].metric(
            "Tarih",
            metadata["date"] or "—"
        )

        # Kopyalanabilir metin kutusu
        st.markdown("### Karar Metni")
        st.caption(
            "Metin kutusuna tıklayıp Ctrl+A → Ctrl+C ile kararın tamamını kopyalayabilirsin."
        )

        st.text_area(
            "Tam karar metni",
            value=decision_text,
            height=650,
            key=f"decision_text_{abs(hash(selected_url))}",
        )

        # Word dosyası
        docx_bytes = make_docx(
            selected_title,
            selected_url,
            decision_text,
            metadata,
        )

        d1, d2 = st.columns(2)

        with d1:
            st.download_button(
                "⬇️ Kararı Word (.docx) İndir",
                data=docx_bytes,
                file_name=safe_filename(metadata),
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                use_container_width=True,
            )

        with d2:
            st.download_button(
                "⬇️ Düz Metin (.txt) İndir",
                data=decision_text.encode("utf-8"),
                file_name="yargi_karari.txt",
                mime="text/plain",
                use_container_width=True,
            )

        st.caption(
            "Kaynak: resmî karar veri tabanından alınan doğrudan karar metni."
        )


with st.expander("ℹ️ Bu sürüm neden daha fazla karar bulur?"):
    st.markdown(
        """
- Ceza hukuku kavramlarını ve ilgili TCK/CMK maddelerini otomatik genişletir.
- Aynı konuyu yıllara bölerek ayrı sorgular.
- Ceza Dairesi ve Ceza Genel Kurulu ifadeleriyle ek taramalar yapar.
- Derin modda Ceza Daireleri bazında da sorgu üretir.
- Sonuçları yalnızca doğrudan karar bağlantılarından toplar.
- Aynı kararı URL üzerinden tekilleştirir.
- Karar açıldığında kullanıcı uygulamadan ayrılmaz; metin uygulamanın içinde gösterilir.
        """
    )
