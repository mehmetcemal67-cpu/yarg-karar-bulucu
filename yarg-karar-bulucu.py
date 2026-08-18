import itertools
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import unicodedata
from collections import Counter
from urllib.parse import quote_plus, urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from ddgs import DDGS
from rapidfuzz import fuzz

# ============================================================
# YARGI KARARI BULUCU — PROFESYONEL ARAMA SÜRÜMÜ
# ============================================================

st.set_page_config(
    page_title="Yargı Kararı Bulucu",
    page_icon="⚖️",
    layout="wide",
)

# ------------------------------------------------------------
# RESMÎ KAYNAKLAR
# ------------------------------------------------------------

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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
}

# ------------------------------------------------------------
# HUKUKİ KAVRAM ONTOLOJİSİ
#
# Amaç kelimeyi birebir eşleştirmek değil, aynı hukuki problemin
# farklı karar metinlerinde kullanılan ifadelerini yakalamaktır.
# ------------------------------------------------------------

LEGAL_CONCEPTS = {
    # İŞ HUKUKU
    "işe iade": [
        "geçersiz fesih", "iş güvencesi", "geçerli neden",
        "fesih bildirimi", "iş sözleşmesinin feshi",
        "feshin son çare olması", "ultima ratio",
        "işverenin ispat yükü", "işçinin işe başlatılması"
    ],
    "feshin son çare olması": [
        "ultima ratio", "ölçülülük", "orantılılık",
        "daha hafif tedbir", "feshe alternatif",
        "geçerli fesih", "geçersiz fesih", "işe iade"
    ],
    "performans düşüklüğü": [
        "performans yetersizliği", "verim düşüklüğü",
        "objektif performans kriteri", "performans değerlendirmesi",
        "savunma alınması", "geçerli neden", "işe iade"
    ],
    "savunma alınmaması": [
        "işçinin savunması", "fesih öncesi savunma",
        "4857 19", "geçersiz fesih", "işe iade"
    ],
    "kıdem tazminatı": [
        "işçilik alacağı", "haklı fesih", "haksız fesih",
        "iş sözleşmesinin sona ermesi", "1475 14",
        "kıdem süresi"
    ],
    "ihbar tazminatı": [
        "bildirim süresi", "bildirimli fesih", "işçilik alacağı",
        "4857 17", "haksız fesih"
    ],
    "fazla mesai": [
        "fazla çalışma", "fazla sürelerle çalışma",
        "işçilik alacağı", "puantaj", "bordro",
        "tanık beyanı", "ispat yükü"
    ],
    "mobbing": [
        "psikolojik taciz", "psikolojik şiddet",
        "işyerinde psikolojik taciz", "sistematik baskı",
        "kişilik hakkı", "işverenin gözetme borcu",
        "manevi tazminat"
    ],
    "iş kazası": [
        "işçi sağlığı", "iş güvenliği", "işverenin kusuru",
        "kaçınılmazlık", "illiyet bağı", "SGK",
        "maddi tazminat", "manevi tazminat"
    ],
    "sendikal fesih": [
        "sendikal tazminat", "sendikal ayrımcılık",
        "sendikal neden", "işe iade", "6356"
    ],

    # BORÇLAR / TAZMİNAT
    "haksız fiil": [
        "TBK 49", "hukuka aykırı fiil", "kusur",
        "zarar", "illiyet bağı", "nedensellik bağı",
        "maddi tazminat", "manevi tazminat"
    ],
    "manevi tazminat": [
        "kişilik hakkı", "kişilik değerleri", "elem ve ızdırap",
        "TBK 56", "TBK 58", "hakkaniyet",
        "manevi zarar"
    ],
    "sözleşmeye aykırılık": [
        "borca aykırılık", "ifa etmeme", "gereği gibi ifa etmeme",
        "temerrüt", "TBK 112", "zarar", "tazminat"
    ],
    "sebepsiz zenginleşme": [
        "haklı sebep olmaksızın zenginleşme",
        "TBK 77", "iade borcu", "zenginleşen", "fakirleşen"
    ],

    # MEDENİ HUKUK / AİLE / MİRAS
    "boşanma": [
        "evlilik birliğinin temelinden sarsılması",
        "TMK 166", "kusur", "nafaka",
        "maddi tazminat", "manevi tazminat", "velayet"
    ],
    "velayet": [
        "çocuğun üstün yararı", "kişisel ilişki",
        "velayetin değiştirilmesi", "ortak velayet",
        "TMK 182"
    ],
    "nafaka": [
        "yoksulluk nafakası", "iştirak nafakası",
        "tedbir nafakası", "nafakanın artırılması",
        "nafakanın kaldırılması"
    ],
    "miras": [
        "tereke", "mirasçılık", "saklı pay",
        "tenkis", "mirasın reddi", "vasiyetname"
    ],
    "tapu iptal tescil": [
        "tapu iptali ve tescil", "muris muvazaası",
        "yolsuz tescil", "iyiniyet", "TMK 1023"
    ],

    # TÜKETİCİ
    "ayıplı mal": [
        "ayıp", "tüketici", "6502", "seçimlik hak",
        "bedel iadesi", "ücretsiz onarım", "misli ile değişim"
    ],
    "ayıplı hizmet": [
        "hizmet ayıbı", "6502", "tüketici işlemi",
        "bedel indirimi", "sözleşmeden dönme"
    ],
    "tüketici kredisi": [
        "kredi sözleşmesi", "erken ödeme",
        "dosya masrafı", "tüketici", "6502"
    ],

    # TİCARET / ŞİRKETLER
    "haksız rekabet": [
        "TTK 54", "dürüstlük kuralı", "ticari uygulama",
        "yanıltıcı beyan", "rekabet"
    ],
    "şirket müdürünün sorumluluğu": [
        "yönetici sorumluluğu", "şirket yöneticisi",
        "özen yükümlülüğü", "TTK", "zarar"
    ],
    "ticari alacak": [
        "cari hesap", "fatura", "ticari defter",
        "temerrüt faizi", "ticari dava"
    ],

    # İCRA / İFLAS
    "itirazın iptali": [
        "icra takibi", "itiraz", "takibin devamı",
        "icra inkâr tazminatı", "İİK 67"
    ],
    "menfi tespit": [
        "borçlu olmadığının tespiti", "İİK 72",
        "icra takibi", "istirdat"
    ],
    "imzaya itiraz": [
        "kambiyo senedi", "imza incelemesi",
        "bilirkişi", "icra mahkemesi"
    ],

    # CEZA HUKUKU
    "hakaret": [
        "TCK 125", "onur şeref ve saygınlık",
        "sövme", "matufiyet", "ihtilat",
        "haksız fiile tepki"
    ],
    "tehdit": [
        "TCK 106", "korkutma", "sair kötülük",
        "hayat vücut cinsel dokunulmazlık"
    ],
    "dolandırıcılık": [
        "TCK 157", "TCK 158", "hileli davranış",
        "hile", "yarar sağlama", "aldatma",
        "nitelikli dolandırıcılık"
    ],
    "nitelikli dolandırıcılık": [
        "TCK 158", "bilişim sistemleri",
        "banka veya kredi kurumu", "ticari faaliyet",
        "hileli davranış", "haksız yarar"
    ],
    "kasten yaralama": [
        "TCK 86", "TCK 87", "beden veya ruh bakımından zarar",
        "silahla yaralama", "neticesi sebebiyle ağırlaşmış yaralama"
    ],
    "taksirle yaralama": [
        "TCK 89", "taksir", "özen yükümlülüğü",
        "dikkat yükümlülüğü"
    ],
    "kasten öldürme": [
        "TCK 81", "TCK 82", "öldürme kastı",
        "olası kast", "haksız tahrik"
    ],
    "haksız tahrik": [
        "TCK 29", "hiddet", "şiddetli elem",
        "haksız fiil", "tahrik indirimi"
    ],
    "meşru savunma": [
        "meşru müdafaa", "TCK 25", "haksız saldırı",
        "orantılı savunma", "sınırın aşılması"
    ],
    "görevi kötüye kullanma": [
        "TCK 257", "kamu görevlisi", "görevin gereklerine aykırılık",
        "ihmal veya gecikme", "mağduriyet", "haksız menfaat"
    ],
    "zimmet": [
        "TCK 247", "kamu görevlisi", "görevi nedeniyle zilyetlik",
        "mal edinme", "zimmetine geçirme"
    ],
    "rüşvet": [
        "TCK 252", "kamu görevlisi", "menfaat sağlama",
        "görevin ifasıyla ilgili iş"
    ],
    "örgüt": [
        "suç işlemek amacıyla örgüt", "TCK 220",
        "örgüt üyeliği", "hiyerarşik yapı",
        "organik bağ", "süreklilik çeşitlilik yoğunluk"
    ],
    "uyuşturucu ticareti": [
        "TCK 188", "uyuşturucu madde ticareti",
        "kullanmak için uyuşturucu bulundurma",
        "TCK 191", "satma", "nakletme", "depolama"
    ],
    "yağma": [
        "TCK 148", "TCK 149", "cebir veya tehdit",
        "malın teslimi", "nitelikli yağma"
    ],
    "hırsızlık": [
        "TCK 141", "TCK 142", "zilyedin rızası",
        "taşınır mal", "nitelikli hırsızlık"
    ],
    "cinsel saldırı": [
        "TCK 102", "cinsel dokunulmazlık",
        "beden dokunulmazlığı", "rıza"
    ],
    "çocuğun cinsel istismarı": [
        "TCK 103", "cinsel istismar", "çocuk",
        "sarkıntılık", "nitelikli istismar"
    ],
    "kişisel veriler": [
        "kişisel verilerin hukuka aykırı ele geçirilmesi",
        "TCK 135", "TCK 136", "KVKK",
        "kişisel veri", "özel hayat"
    ],

    # CEZA MUHAKEMESİ
    "hukuka aykırı delil": [
        "yasak delil", "CMK 206", "CMK 217",
        "hukuka aykırı elde edilen delil",
        "delil değerlendirme yasağı"
    ],
    "arama kararı": [
        "adli arama", "CMK 116", "makul şüphe",
        "arama emri", "hukuka aykırı arama"
    ],
    "tutuklama": [
        "CMK 100", "kuvvetli suç şüphesi",
        "tutuklama nedeni", "ölçülülük",
        "adli kontrol", "kişi hürriyeti ve güvenliği"
    ],
    "adil yargılanma": [
        "adil yargılanma hakkı", "Anayasa 36",
        "silahların eşitliği", "çelişmeli yargılama",
        "gerekçeli karar", "makul süre"
    ],

    # İDARE HUKUKU
    "idari işlemin iptali": [
        "iptal davası", "yetki", "şekil", "sebep",
        "konu", "maksat", "hukuka aykırılık"
    ],
    "yürütmenin durdurulması": [
        "telafisi güç zarar", "açıkça hukuka aykırılık",
        "2577 27", "idari işlem"
    ],
    "tam yargı davası": [
        "idarenin sorumluluğu", "hizmet kusuru",
        "kusursuz sorumluluk", "maddi tazminat",
        "manevi tazminat"
    ],
    "hizmet kusuru": [
        "idarenin kusuru", "hizmetin geç işlemesi",
        "hizmetin kötü işlemesi", "hizmetin hiç işlememesi",
        "tam yargı"
    ],
    "disiplin cezası": [
        "disiplin soruşturması", "savunma hakkı",
        "ölçülülük", "orantılılık", "657"
    ],
    "memur atama": [
        "atama işlemi", "kamu görevlisi", "takdir yetkisi",
        "liyakat", "kariyer"
    ],
    "imar": [
        "imar planı", "plan değişikliği", "3194",
        "şehircilik ilkeleri", "planlama esasları",
        "kamu yararı"
    ],
    "kamulaştırma": [
        "2942", "kamulaştırma bedeli",
        "acele kamulaştırma", "bedel tespiti",
        "kamulaştırmasız el atma"
    ],
    "kamu ihalesi": [
        "4734", "ihale", "kamu ihale kurumu",
        "yasaklama", "ihale dışı bırakma",
        "aşırı düşük teklif"
    ],

    # VERGİ
    "vergi ziyaı": [
        "vergi ziyaı cezası", "VUK 341", "VUK 344",
        "tarhiyat", "vergi kaybı"
    ],
    "özel usulsüzlük": [
        "özel usulsüzlük cezası", "VUK 353",
        "fatura", "belge düzeni"
    ],
    "sahte fatura": [
        "sahte belge", "muhteviyatı itibarıyla yanıltıcı belge",
        "VUK 359", "kaçakçılık"
    ],
    "tarhiyat": [
        "vergi tarhı", "re'sen tarh", "ikmalen tarh",
        "vergi incelemesi", "matrah"
    ],

    # ANAYASA / TEMEL HAKLAR
    "ifade özgürlüğü": [
        "ifade hürriyeti", "Anayasa 26",
        "düşünceyi açıklama ve yayma hürriyeti",
        "demokratik toplum düzeni", "ölçülülük",
        "zorunlu toplumsal ihtiyaç"
    ],
    "basın özgürlüğü": [
        "basın hürriyeti", "Anayasa 28",
        "ifade özgürlüğü", "gazetecilik",
        "kamusal tartışma"
    ],
    "özel hayat": [
        "özel hayata saygı", "Anayasa 20",
        "mahremiyet", "kişisel veri",
        "aile hayatına saygı"
    ],
    "mülkiyet hakkı": [
        "Anayasa 35", "mülkiyet", "malvarlığı",
        "ölçülülük", "adil denge", "kamulaştırma"
    ],
    "gerekçeli karar": [
        "gerekçeli karar hakkı", "adil yargılanma",
        "Anayasa 36", "mahkeme gerekçesi"
    ],
    "makul süre": [
        "yargılamanın uzun sürmesi", "makul sürede yargılanma",
        "adil yargılanma", "Anayasa 36"
    ],
    "masumiyet karinesi": [
        "suçsuzluk karinesi", "Anayasa 38",
        "kesinleşmiş mahkumiyet", "lekelenmeme hakkı"
    ],
}

# Madde/kısaltma eşleştirmeleri
ABBREVIATIONS = {
    "tck": "Türk Ceza Kanunu",
    "cmk": "Ceza Muhakemesi Kanunu",
    "hmk": "Hukuk Muhakemeleri Kanunu",
    "tbk": "Türk Borçlar Kanunu",
    "tmk": "Türk Medeni Kanunu",
    "iik": "İcra ve İflas Kanunu",
    "vuk": "Vergi Usul Kanunu",
    "kvkk": "Kişisel Verilerin Korunması Kanunu",
    "ttk": "Türk Ticaret Kanunu",
}

STOP_WORDS = {
    "ve", "veya", "ile", "bir", "bu", "şu", "için", "gibi", "olan",
    "olarak", "de", "da", "mi", "mı", "mu", "mü", "karar", "kararı",
    "yargıtay", "danıştay", "mahkeme", "mahkemesi"
}


# ------------------------------------------------------------
# METİN YARDIMCILARI
# ------------------------------------------------------------

def clean_text(value):
    value = value or ""
    value = re.sub(r"\s+", " ", str(value))
    return value.strip()


def tr_lower(text):
    text = clean_text(text)
    return text.replace("I", "ı").replace("İ", "i").lower()


def ascii_fold(text):
    text = tr_lower(text)
    repl = {
        "ç": "c", "ğ": "g", "ı": "i",
        "ö": "o", "ş": "s", "ü": "u"
    }
    for a, b in repl.items():
        text = text.replace(a, b)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def tokenize(text):
    tokens = re.findall(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]+", clean_text(text))
    return [tr_lower(x) for x in tokens if len(x) > 1]


def parse_user_terms(text):
    """
    Virgül, noktalı virgül veya yeni satırla ayrılan kavramları korur.
    Tek parça bir doğal dil cümlesiyse tamamını ana kavram olarak da tutar.
    """
    text = clean_text(text.replace("\n", ","))
    if not text:
        return []

    chunks = [clean_text(x) for x in re.split(r"[,;]+", text) if clean_text(x)]

    # Kullanıcı virgül kullanmadıysa bütün cümleyi de koru.
    if len(chunks) == 1:
        phrase = chunks[0]
        result = [phrase]

        # Anlamlı büyük parçaları ayrıca sorgu tohumu yap.
        toks = [t for t in tokenize(phrase) if t not in STOP_WORDS]
        if len(toks) >= 3:
            for n in (2, 3):
                for i in range(len(toks) - n + 1):
                    p = " ".join(toks[i:i+n])
                    if p not in result:
                        result.append(p)
        return result[:8]

    return chunks[:30]


def source_from_url(url):
    host = urlparse(url).netloc.lower()
    for name, cfg in OFFICIAL_SOURCES.items():
        if cfg["domain"] in host:
            return name
    return "Diğer"


def is_official(url):
    host = urlparse(url).netloc.lower()
    return any(cfg["domain"] in host for cfg in OFFICIAL_SOURCES.values())


def is_direct_decision_url(url, source_name=""):
    """
    Yalnızca doğrudan bir karar/doküman sayfasına benzeyen resmî URL'leri kabul eder.
    Kaynak ana sayfası, genel arama ekranı ve sonuç listeleri elenir.
    """
    if not url or not is_official(url):
        return False

    parsed = urlparse(url)
    path = (parsed.path or "").lower().strip("/")
    query = (parsed.query or "").lower()
    full = url.lower()

    # Ana sayfaları ve genel arama ekranlarını ele
    if not path and not query:
        return False

    generic_bad = [
        "search", "arama", "anasayfa", "index",
        "default.aspx", "home"
    ]

    # Açıkça genel arama sayfası olup doküman kimliği taşımıyorsa kabul etme
    if any(x in full for x in generic_bad):
        id_tokens = ["id=", "kararid=", "documentid=", "dokumanid=", "docid="]
        if not any(x in query for x in id_tokens):
            return False

    # Kuvvetli doğrudan-karar göstergeleri
    strong_tokens = [
        "getdokuman", "dokuman", "document",
        "kararid=", "documentid=", "dokumanid=", "docid=",
        "/bb/", "/kbb/", "/karar/", "/kararlar/"
    ]
    if any(x in full for x in strong_tokens):
        return True

    # URL içinde karar/emsal + sayısal kimlik varsa doğrudan sonuç olma ihtimali yüksek
    if ("karar" in full or "emsal" in full) and re.search(r"\d{3,}", full):
        return True

    # Sorgu parametresinde doğrudan kayıt kimliği
    if re.search(r"(?:^|&)(?:id|kararid|documentid|dokumanid|docid)=\d+", query):
        return True

    # AYM karar bilgi bankasında derin sayfaları kabul et
    if "kararlarbilgibankasi.anayasa.gov.tr" in parsed.netloc.lower():
        segments = [x for x in path.split("/") if x]
        if len(segments) >= 2:
            return True

    return False


def normalize_number(value):
    value = clean_text(value)
    value = re.sub(r"\b[EKek]\.?\s*[:\-]?\s*", "", value)
    return value.strip()


# ------------------------------------------------------------
# KAVRAM MOTORU
# ------------------------------------------------------------

def concept_similarity(user_phrase, concept):
    a = ascii_fold(user_phrase)
    b = ascii_fold(concept)

    if not a or not b:
        return 0

    if a == b:
        return 100

    if a in b or b in a:
        return 94

    return max(
        fuzz.token_set_ratio(a, b),
        fuzz.partial_ratio(a, b),
    )


def detect_legal_concepts(user_terms, limit=8):
    """
    Birebir sözcük eşleşmesi yerine fuzzy semantic-like legal concept mapping.
    Harici yapay zekâ servisi gerektirmez.
    """
    scores = []

    joined = " ".join(user_terms)

    for concept, related in LEGAL_CONCEPTS.items():
        variants = [concept] + related
        best = 0

        for user_term in user_terms + [joined]:
            for variant in variants:
                score = concept_similarity(user_term, variant)
                if score > best:
                    best = score

        # Kavramın kelimelerinden biri kullanıcının sorgusunda belirgin biçimde varsa bonus
        concept_tokens = set(tokenize(concept)) - STOP_WORDS
        joined_tokens = set(tokenize(joined)) - STOP_WORDS
        overlap = len(concept_tokens & joined_tokens)
        best += overlap * 7

        if best >= 63:
            scores.append((concept, min(best, 100)))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:limit]


def expand_terms(user_terms, detected_concepts, max_related_per_concept=5):
    """
    Kullanıcının terimlerini kavram ailesi ile genişletir.
    Çok fazla sorgu üretmemek için dengeli sınır kullanılır.
    """
    primary = []
    related = []

    for x in user_terms:
        if x and x not in primary:
            primary.append(x)

    for concept, score in detected_concepts:
        if concept not in primary:
            related.append(concept)

        variants = LEGAL_CONCEPTS.get(concept, [])
        # En yakın varyantları önce seç
        ranked = sorted(
            variants,
            key=lambda v: max(
                [concept_similarity(u, v) for u in user_terms] or [0]
            ),
            reverse=True,
        )
        for item in ranked[:max_related_per_concept]:
            if item not in primary and item not in related:
                related.append(item)

    # Kısaltmaları aç
    joined = tr_lower(" ".join(user_terms))
    for short, long_name in ABBREVIATIONS.items():
        if re.search(rf"\b{re.escape(short)}\b", joined):
            related.append(long_name)

    return primary[:15], related[:35]


# ------------------------------------------------------------
# SORGU PLANI
# ------------------------------------------------------------

def quoted(term):
    term = clean_text(term)
    if not term:
        return ""
    return f'"{term}"'


def make_search_plans(
    primary,
    related,
    legislation,
    chamber,
    esas_no,
    karar_no,
    year_from,
    year_to,
):
    """
    Üç seviyeli arama:
      1. kesin/dar
      2. dengeli
      3. keşif/geniş

    Böylece tek bir anahtar kelime kombinasyonuna bağımlılık azalır.
    """
    plans = []

    metadata = []
    if legislation:
        metadata.append(quoted(legislation))
    if chamber:
        metadata.append(quoted(chamber))
    if esas_no:
        metadata.append(quoted(normalize_number(esas_no)))
    if karar_no:
        metadata.append(quoted(normalize_number(karar_no)))

    if year_from and year_to and year_from == year_to:
        metadata.append(str(year_from))

    # 1) Ana cümle/kavram
    for term in primary[:6]:
        plans.append({
            "level": "Kesin",
            "terms": [term],
            "query": " ".join([quoted(term)] + metadata),
        })

    # 2) Kullanıcı terimlerinin ikili kombinasyonları
    pair_pool = primary[:8]
    for a, b in itertools.combinations(pair_pool, 2):
        plans.append({
            "level": "Dengeli",
            "terms": [a, b],
            "query": " ".join([quoted(a), quoted(b)] + metadata),
        })
        if len([p for p in plans if p["level"] == "Dengeli"]) >= 10:
            break

    # 3) Ana terim + ilişkili kavram
    for p in primary[:5]:
        for r in related[:8]:
            if concept_similarity(p, r) >= 97:
                continue
            plans.append({
                "level": "Kavramsal",
                "terms": [p, r],
                "query": " ".join([quoted(p), quoted(r)] + metadata),
            })
            if len([x for x in plans if x["level"] == "Kavramsal"]) >= 14:
                break
        if len([x for x in plans if x["level"] == "Kavramsal"]) >= 14:
            break

    # 4) İlişkili kavramların tekli geniş taraması
    for r in related[:12]:
        plans.append({
            "level": "Keşif",
            "terms": [r],
            "query": " ".join([quoted(r)] + metadata),
        })

    # Sadece numara aranıyorsa
    if not plans and metadata:
        plans.append({
            "level": "Numara",
            "terms": metadata,
            "query": " ".join(metadata),
        })

    # Yinelenen query'leri kaldır
    seen = set()
    unique = []
    for p in plans:
        q = clean_text(p["query"])
        if not q or q in seen:
            continue
        seen.add(q)
        unique.append(p)

    return unique[:45]


# ------------------------------------------------------------
# ARAMA SAĞLAYICILARI
# ------------------------------------------------------------

def ddgs_search(query, domain, max_results=10):
    """
    DDGS boş sonuç döndürürse hata fırlatmak yerine [] döndürür.
    """
    full_query = f"{query} site:{domain}"

    try:
        rows = []
        with DDGS() as ddgs:
            raw = ddgs.text(
                full_query,
                region="tr-tr",
                safesearch="off",
                max_results=max_results,
            )
            if raw:
                for item in raw:
                    url = item.get("href") or item.get("url") or ""
                    if not url or domain not in urlparse(url).netloc.lower():
                        continue
                    source_name = source_from_url(url)
                    if not is_direct_decision_url(url, source_name):
                        continue
                    rows.append({
                        "title": clean_text(item.get("title", "")),
                        "body": clean_text(item.get("body", "")),
                        "href": url,
                        "provider": "DDGS",
                    })
        return rows
    except Exception:
        return []


def bing_html_fallback(query, domain, max_results=8):
    """
    Ana sağlayıcı sonuç vermezse ikinci bir genel web dizini denemesi.
    Sonuç yine yalnızca resmî domain ile kabul edilir.
    """
    q = quote_plus(f"{query} site:{domain}")
    url = f"https://www.bing.com/search?q={q}&count={max_results}&setlang=tr"

    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        rows = []

        for item in soup.select("li.b_algo"):
            a = item.select_one("h2 a")
            if not a:
                continue

            href = a.get("href", "")
            if domain not in urlparse(href).netloc.lower():
                continue
            source_name = source_from_url(href)
            if not is_direct_decision_url(href, source_name):
                continue

            p = item.select_one(".b_caption p")
            rows.append({
                "title": clean_text(a.get_text(" ")),
                "body": clean_text(p.get_text(" ") if p else ""),
                "href": href,
                "provider": "Web fallback",
            })

            if len(rows) >= max_results:
                break

        return rows
    except Exception:
        return []


@st.cache_data(ttl=1800, show_spinner=False)
def search_one_query(query, domain, max_results, allow_fallback=False):
    rows = ddgs_search(query, domain, max_results)
    if not rows and allow_fallback:
        rows = bing_html_fallback(query, domain, min(max_results, 8))
    return rows


# ------------------------------------------------------------
# SONUÇ PUANLAMA
# ------------------------------------------------------------

def text_match_score(text, term):
    text_n = ascii_fold(text)
    term_n = ascii_fold(term)

    if not term_n:
        return 0

    if term_n in text_n:
        return 100

    return fuzz.partial_ratio(term_n, text_n)


def score_result(row, primary, related, exact_phrase, legislation, chamber):
    text = clean_text(
        f"{row.get('title','')} {row.get('body','')} {row.get('href','')}"
    )

    score = 0
    matched_primary = []
    matched_related = []

    # Ana kavramlar çok daha yüksek ağırlık
    for term in primary:
        s = text_match_score(text, term)
        if s >= 88:
            score += 18
            matched_primary.append(term)
        elif s >= 72:
            score += 8

    # İlişkili kavramlar destekleyici ağırlık
    for term in related:
        s = text_match_score(text, term)
        if s >= 90:
            score += 5
            matched_related.append(term)

    if exact_phrase and text_match_score(text, exact_phrase) >= 95:
        score += 35

    if legislation and text_match_score(text, legislation) >= 85:
        score += 15

    if chamber and text_match_score(text, chamber) >= 85:
        score += 12

    # Resmî karar linkine benzeyen URL bonusu
    href_low = row.get("href", "").lower()
    if any(x in href_low for x in ["getdokuman", "/bb/", "/kbb/", "karar"]):
        score += 10

    # E./K. formatına benzeyen karar numaraları
    if re.search(r"\b20\d{2}/\d+\b", text):
        score += 4

    # Çeşitlilik bonusu: birden fazla ana kavram eşleşirse
    if len(set(matched_primary)) >= 2:
        score += 12
    if len(set(matched_primary)) >= 3:
        score += 15

    row["matched_primary"] = list(dict.fromkeys(matched_primary))
    row["matched_related"] = list(dict.fromkeys(matched_related))[:8]

    return score


def dedupe(rows):
    """
    Aynı URL ve çok benzer başlıkları tekilleştirir.
    """
    out = []
    seen_urls = set()
    seen_titles = []

    for r in rows:
        url_key = r["href"].split("#")[0].rstrip("/")

        if url_key in seen_urls:
            continue

        title_key = ascii_fold(r.get("title", ""))
        duplicate_title = False

        if title_key:
            for old in seen_titles[-80:]:
                if fuzz.ratio(title_key, old) >= 96:
                    duplicate_title = True
                    break

        if duplicate_title:
            continue

        seen_urls.add(url_key)
        if title_key:
            seen_titles.append(title_key)
        out.append(r)

    return out


# ------------------------------------------------------------
# KARAR METNİNİ OKUMA
# ------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_decision_text(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()

        ctype = r.headers.get("content-type", "").lower()
        if "html" not in ctype and "text" not in ctype:
            return ""

        soup = BeautifulSoup(r.text, "html.parser")

        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()

        text = clean_text(soup.get_text(" "))

        if len(text) < 300:
            return ""

        return text[:40000]
    except Exception:
        return ""


def best_excerpt(text, terms, max_len=2200):
    if not text:
        return ""

    low = ascii_fold(text)
    positions = []

    for term in terms:
        t = ascii_fold(term)
        if not t:
            continue
        p = low.find(t)
        if p >= 0:
            positions.append(p)

    start = max(0, (min(positions) if positions else 0) - 650)
    excerpt = text[start:start + max_len]

    if start > 0:
        excerpt = "… " + excerpt
    if start + max_len < len(text):
        excerpt += " …"

    return excerpt


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------

st.title("⚖️ Yargı Kararı Bulucu")
st.caption(
    "Yargıtay, Danıştay, UYAP Emsal ve Anayasa Mahkemesi resmî kaynaklarında "
    "kavramsal ve çok aşamalı içtihat araştırması."
)

with st.sidebar:
    st.header("Arama Ayarları")

    selected_sources = st.multiselect(
        "Kaynaklar",
        list(OFFICIAL_SOURCES.keys()),
        default=list(OFFICIAL_SOURCES.keys()),
    )

    search_depth = st.select_slider(
        "Arama derinliği",
        options=["Hızlı", "Dengeli", "Derin"],
        value="Dengeli",
        help=(
            "Hızlı: az sorgu. Dengeli: önerilen. "
            "Derin: daha fazla kavram kombinasyonu ve daha uzun tarama."
        ),
    )

    results_per_query = st.slider(
        "Sorgu başına sonuç",
        5, 20, 8, 1
    )

    max_workers = st.slider(
        "Paralel arama sayısı",
        4, 16, 10, 1,
        help="Daha yüksek değer aramayı hızlandırır; 8-12 arası önerilir."
    )

    fetch_full = st.checkbox(
        "Bulunabilen karar metnini de oku",
        value=False,
        help="Karar sayfası doğrudan erişilebiliyorsa ilgili metin bölümünü gösterir.",
    )

    st.divider()
    st.caption(
        "Arama yalnızca seçili resmî yargı alan adlarından gelen sonuçları kabul eder."
    )

left, right = st.columns(2)

with left:
    keywords = st.text_area(
        "Konu / anahtar kelimeler",
        height=125,
        placeholder=(
            "Doğal dille yazabilir veya virgülle ayırabilirsin.\n"
            "Örn: işe iade, performans düşüklüğü, savunma alınmaması\n"
            "veya: İşveren performans düşüklüğü nedeniyle işçiyi çıkardı"
        ),
    )

    exact_phrase = st.text_input(
        "Mutlaka geçmesini istediğin tam ifade",
        placeholder="Örn: feshin son çare olması ilkesi",
    )

    legislation = st.text_input(
        "Mevzuat / madde",
        placeholder="Örn: 4857 18, TCK 158, HMK 27",
    )

    chamber = st.text_input(
        "Daire / kurul",
        placeholder="Örn: 9. Hukuk Dairesi, Ceza Genel Kurulu",
    )

with right:
    c1, c2 = st.columns(2)
    with c1:
        esas_no = st.text_input("Esas No", placeholder="2023/1234")
    with c2:
        karar_no = st.text_input("Karar No", placeholder="2024/5678")

    y1, y2 = st.columns(2)
    with y1:
        year_from = st.text_input("Başlangıç yılı", placeholder="2020")
    with y2:
        year_to = st.text_input("Bitiş yılı", placeholder="2026")

    sort_option = st.selectbox(
        "Sıralama",
        ["En ilgili", "Kaynağa göre", "En çok kavram eşleşen"],
    )

    show_concepts = st.checkbox(
        "Sistemin bulduğu ilişkili hukuk kavramlarını göster",
        value=True,
    )

st.markdown("#### Örnek aramalar")
examples = st.columns(4)
examples[0].code("işe iade, performans düşüklüğü")
examples[1].code("TCK 158, banka hesabı, hile")
examples[2].code("mobbing, istifa, manevi tazminat")
examples[3].code("ifade özgürlüğü, sosyal medya")

search_clicked = st.button(
    "🔎 Kararları Ara",
    type="primary",
    use_container_width=True
)

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
        st.warning("Arama için en az bir konu, mevzuat, daire veya karar numarası gir.")
        st.stop()

    user_terms = parse_user_terms(keywords)

    # Tam ifade ayrıca ana kavram olarak aramaya katılır.
    if clean_text(exact_phrase) and exact_phrase not in user_terms:
        user_terms.insert(0, clean_text(exact_phrase))

    detected = detect_legal_concepts(user_terms)
    primary, related = expand_terms(user_terms, detected)

    plans = make_search_plans(
        primary=primary,
        related=related,
        legislation=clean_text(legislation),
        chamber=clean_text(chamber),
        esas_no=clean_text(esas_no),
        karar_no=clean_text(karar_no),
        year_from=clean_text(year_from),
        year_to=clean_text(year_to),
    )

    # Arama derinliğine göre sorgu sayısı
    plan_limit = {
        "Hızlı": 6,
        "Dengeli": 14,
        "Derin": 24,
    }[search_depth]

    plans = plans[:plan_limit]

    st.session_state["detected"] = detected
    st.session_state["primary"] = primary
    st.session_state["related"] = related
    st.session_state["plans"] = plans

    all_results = []
    source_stats = Counter()

    # HIZLI ARAMA MİMARİSİ
    fast_plan_limit = {
        "Hızlı": min(6, len(plans)),
        "Dengeli": min(12, len(plans)),
        "Derin": min(20, len(plans)),
    }[search_depth]
    primary_plans = plans[:fast_plan_limit]

    tasks = []
    for source_name in selected_sources:
        domain = OFFICIAL_SOURCES[source_name]["domain"]
        for plan in primary_plans:
            tasks.append((source_name, domain, plan))

    total_steps = max(1, len(tasks))
    done = 0
    progress = st.progress(0)
    status = st.empty()

    def run_fast_search(source_name, domain, plan):
        rows = search_one_query(
            plan["query"], domain, results_per_query, allow_fallback=False
        )
        return source_name, plan, rows

    # Kaynak ve sorgular paralel çalışır.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(run_fast_search, source_name, domain, plan):
            (source_name, plan)
            for source_name, domain, plan in tasks
        }

        for future in as_completed(future_map):
            source_name, plan = future_map[future]
            done += 1
            progress.progress(min(done / total_steps, 1.0))
            status.caption(
                f"{source_name} • {plan['level']} • "
                f"{' + '.join(plan['terms'][:2])}"
            )

            try:
                _, finished_plan, rows = future.result()
            except Exception:
                rows = []
                finished_plan = plan

            for row in rows:
                row["source"] = source_name
                row["search_level"] = finished_plan["level"]
                row["trigger_terms"] = finished_plan["terms"]
                all_results.append(row)
                source_stats[source_name] += 1

    # Fallback sadece hiç sonuç veremeyen kaynaklarda ve en güçlü 3 sorguda çalışır.
    missing_sources = [
        name for name in selected_sources if source_stats[name] == 0
    ]
    fallback_plans = primary_plans[:3]

    if missing_sources and fallback_plans:
        fallback_tasks = []
        for source_name in missing_sources:
            domain = OFFICIAL_SOURCES[source_name]["domain"]
            for plan in fallback_plans:
                fallback_tasks.append((source_name, domain, plan))

        with ThreadPoolExecutor(max_workers=min(max_workers, 6)) as executor:
            future_map = {
                executor.submit(
                    search_one_query,
                    plan["query"],
                    domain,
                    min(results_per_query, 8),
                    True,
                ): (source_name, plan)
                for source_name, domain, plan in fallback_tasks
            }

            for future in as_completed(future_map):
                source_name, plan = future_map[future]
                try:
                    rows = future.result()
                except Exception:
                    rows = []

                for row in rows:
                    row["source"] = source_name
                    row["search_level"] = f"{plan['level']}+"
                    row["trigger_terms"] = plan["terms"]
                    all_results.append(row)
                    source_stats[source_name] += 1

    progress.empty()
    status.empty()

    all_results = dedupe(all_results)

    # Son savunma filtresi:
    # Kullanıcıya yalnızca doğrudan karar/doküman bağlantısı göster.
    all_results = [
        row for row in all_results
        if is_direct_decision_url(row.get("href", ""), row.get("source", ""))
    ]

    for row in all_results:
        row["score"] = score_result(
            row,
            primary,
            related,
            clean_text(exact_phrase),
            clean_text(legislation),
            clean_text(chamber),
        )
        row["concept_count"] = (
            len(row.get("matched_primary", [])) +
            len(row.get("matched_related", []))
        )

    # Çok düşük ilgisiz sonuçları temizle; numara aramasında tut.
    is_number_search = bool(clean_text(esas_no) or clean_text(karar_no))
    if not is_number_search:
        all_results = [r for r in all_results if r["score"] >= 10]

    if sort_option == "En ilgili":
        all_results.sort(key=lambda x: x["score"], reverse=True)
    elif sort_option == "En çok kavram eşleşen":
        all_results.sort(
            key=lambda x: (x["concept_count"], x["score"]),
            reverse=True
        )
    else:
        all_results.sort(key=lambda x: (x["source"], -x["score"]))

    st.session_state["last_results"] = all_results
    st.session_state["source_stats"] = dict(source_stats)


# ------------------------------------------------------------
# KAVRAM ANALİZİ
# ------------------------------------------------------------

detected = st.session_state.get("detected", [])
primary = st.session_state.get("primary", [])
related = st.session_state.get("related", [])

if show_concepts and (primary or related):
    with st.expander("🧠 Hukukî kavram analizi", expanded=True):
        if detected:
            st.markdown("**Sistem tarafından tespit edilen kavram aileleri:**")
            st.write(
                " • ".join(
                    [f"{name} (%{int(score)})" for name, score in detected]
                )
            )

        if primary:
            st.markdown("**Ana arama kavramları:**")
            st.write(" • ".join(primary))

        if related:
            st.markdown("**Otomatik genişletilen ilişkili kavramlar:**")
            st.write(" • ".join(related))

        st.caption(
            "İlişkili kavramlar, sonuçları doğrudan kabul etmek için değil; "
            "arama alanını genişletmek ve farklı karar yazım biçimlerini yakalamak için kullanılır."
        )


# ------------------------------------------------------------
# SONUÇLAR
# ------------------------------------------------------------

results = st.session_state.get("last_results", [])

if results:
    st.success(f"{len(results)} benzersiz resmî karar sonucu bulundu.")

    stats = st.session_state.get("source_stats", {})
    stat_cols = st.columns(max(1, len(stats)))

    for col, (name, count) in zip(stat_cols, stats.items()):
        with col:
            st.metric(name, count)

    found_sources = sorted({x["source"] for x in results})

    filter_sources = st.multiselect(
        "Sonuçlarda kaynak filtresi",
        found_sources,
        default=found_sources,
        key="result_sources",
    )

    min_score = st.slider(
        "Minimum ilgi puanı",
        0,
        max(100, min(250, max([r["score"] for r in results] or [100]))),
        10,
    )

    filtered = [
        r for r in results
        if r["source"] in filter_sources and r["score"] >= min_score
    ]

    export_df = pd.DataFrame([
        {
            "Kaynak": r["source"],
            "Başlık": r["title"],
            "Özet": r["body"],
            "Ana Kavram Eşleşmeleri": ", ".join(r.get("matched_primary", [])),
            "İlişkili Kavramlar": ", ".join(r.get("matched_related", [])),
            "Arama Seviyesi": r.get("search_level", ""),
            "İlgi Puanı": r["score"],
            "Bağlantı": r["href"],
        }
        for r in filtered
    ])

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
            expanded=(i <= 5)
        ):
            top1, top2, top3 = st.columns([1, 1, 1])
            top1.metric("İlgi puanı", row["score"])
            top2.metric("Kavram eşleşmesi", row["concept_count"])
            top3.write(f"**Tarama:** {row.get('search_level', '')}")

            # Başlığın kendisi doğrudan karar bağlantısıdır.
            st.markdown(
                f"### [{title}]({row['href']})"
            )

            if row.get("body"):
                st.write(row["body"])

            if row.get("matched_primary"):
                st.markdown(
                    "**Ana eşleşmeler:** " +
                    ", ".join(row["matched_primary"])
                )

            if row.get("matched_related"):
                st.markdown(
                    "**İlişkili kavramlar:** " +
                    ", ".join(row["matched_related"])
                )

            st.link_button(
                "⚖️ Kararı Aç",
                row["href"],
                use_container_width=True,
            )

            st.caption(
                "Bu bağlantı genel arama ekranına değil, bulunan doğrudan resmî karar/doküman sayfasına gider."
            )

            if fetch_full:
                with st.spinner("Karar metni inceleniyor…"):
                    full_text = fetch_decision_text(row["href"])

                if full_text:
                    excerpt = best_excerpt(
                        full_text,
                        row.get("matched_primary", []) +
                        row.get("matched_related", []) +
                        primary
                    )

                    st.markdown("**Karar metninden ilgili bölüm:**")
                    st.write(excerpt)

                    with st.expander("Daha uzun karar metnini göster"):
                        st.text(full_text[:18000])
                else:
                    st.info(
                        "Bu kararın metni otomatik olarak okunamadı. "
                        "Yukarıdaki resmî bağlantıdan kararı açabilirsin."
                    )

elif "last_results" in st.session_state:
    st.warning(
        "Bu taramada doğrudan açılabilen resmî karar bağlantısı bulunamadı. "
        "Genel arama ve yönlendirme sayfaları özellikle listeden çıkarılmıştır. "
        "Bu durum mutlaka karar olmadığı anlamına gelmez. "
        "Arama Derinliği'ni 'Derin' seçebilir, tarih/daire kısıtlarını kaldırabilir "
        "veya konuyu daha doğal bir cümleyle yazabilirsin."
    )

    # Sonuç yoksa resmi sitelere doğrudan geçiş sun
    st.markdown("#### Resmî kaynaklarda manuel devam et")
    cols = st.columns(4)
    for col, (name, cfg) in zip(cols, OFFICIAL_SOURCES.items()):
        with col:
            st.link_button(name, cfg["home"], use_container_width=True)


# ------------------------------------------------------------
# TEKNİK / ŞEFFAFLIK
# ------------------------------------------------------------

with st.expander("🔬 Oluşturulan arama planını göster"):
    plans = st.session_state.get("plans", [])

    if plans:
        for idx, plan in enumerate(plans, start=1):
            st.code(
                f"{idx:02d} | {plan['level']} | {plan['query']}"
            )
    else:
        st.caption("Henüz arama yapılmadı.")

with st.expander("ℹ️ Sistem nasıl çalışıyor?"):
    st.markdown(
        """
Bu uygulama bir kararın yalnızca birebir yazılan anahtar kelimeyi
içermesine bağlı değildir.

1. Kullanıcının doğal dilde yazdığı hukukî problemi parçalara ayırır.
2. Yakın hukukî kavram ailelerini tespit eder.
3. Eş anlamlı ve ilişkili hukuk terimleriyle aramayı genişletir.
4. Kesin, dengeli, kavramsal ve keşif düzeylerinde ayrı sorgular üretir.
5. Sonuç olarak yalnızca resmî yargı alan adlarını kabul eder.
6. Aynı kararları tekilleştirir.
7. Ana kavram eşleşmelerini ilişkili kavramlardan daha yüksek ağırlıkla puanlar.
8. En ilgili kararları üst sıraya taşır.

Kavramsal genişletme araştırmayı kolaylaştırır; hukukî değerlendirme yerine
geçmez. Nihai karar metni resmî kaynaktan kontrol edilmelidir.
        """
    )
