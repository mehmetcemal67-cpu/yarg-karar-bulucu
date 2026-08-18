import re
import streamlit as st

# Sayfa Genişliği ve Başlık Ayarı
st.set_page_config(
    page_title="Yargıtay Karar Arama Portal",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Arayüz Stillemesi (Özel CSS - Görsele Uygun Renkler)
st.markdown(
    """
    <style>
    /* Üst Banner Stili */
    .header-bar {
        background-color: #38b2ac;
        padding: 12px 20px;
        border-radius: 6px;
        color: white;
        font-weight: bold;
        font-size: 20px;
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 20px;
    }
    /* Metin Vurgulama Stili */
    mark {
        background-color: #fef08a;
        color: #000000;
        padding: 2px 4px;
        border-radius: 3px;
        font-weight: bold;
    }
    /* Tablo Alanı */
    .stDataFrame {
        border-radius: 8px;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# Üst Başlık Banner
st.markdown(
    '<div class="header-bar">⚖️ Yargıtay Karar Arama</div>',
    unsafe_allow_html=True,
)


# Örnek Veri Seti (İleride burayı bir veritabanı, CSV veya API çağrısına bağlayabilirsiniz)
@st.cache_data
def load_data():
    return [
        {
            "id": 1,
            "daire": "Ceza Genel Kurulu",
            "esas": "2021/179",
            "karar": "2023/229",
            "tarih": "25.04.2023",
            "metin": """Ceza Genel Kurulu 2021/179 E. , 2023/229 K.\n\n"İçtihat Metni"\nMAHKEMESİ : Asliye Ceza Mahkemesi\nSUÇ : Hakaret\nHÜKÜM : Ceza verilmesine yer olmadığı\n\nKARAR:\nSanık hakkında haksız tahrik altında işlenen fiil neticesinde ceza verilmesine yer olmadığı kararı temyiz edilmiştir. İnceleme neticesinde haksız tahrik unsurlarının oluştuğu sabittir.""",
        },
        {
            "id": 2,
            "daire": "18. Ceza Dairesi",
            "esas": "2016/9638",
            "karar": "2018/6863",
            "tarih": "07.05.2018",
            "metin": """18. Ceza Dairesi 2016/9638 E. , 2018/6863 K.\n\n"İçtihat Metni"\nMAHKEMESİ : Asliye Ceza Mahkemesi\nSUÇ : Hakaret\nHÜKÜM : Ceza verilmesine yer olmadığı\n\nKARAR:\nYerel Mahkemece verilen hüküm temyiz edilmekle, başvurunun süresi, kararın niteliği ile suç tarihine göre dosya görüşüldü:\nTemyiz isteğinin reddi nedenleri bulunmadığından işin esasına geçildi.\nHakaret suçunun haksız fiile tepki olarak işlenmesi nedeniyle ceza verilmesine yer olmadığı kararına yönelik Cumhuriyet Savcısının temyiz iddiaları yerinde görülmediğinden HÜKMÜN ONANMASINA oy çokluğuyla karar verildi.\n\nKARŞI OY:\nSayın çoğunluk ile aramızdaki uyuşmazlık sanık hakkında haksız tahrik hükümlerinin uygulanıp uygulanmayacağı noktasındadır. TCK 29. maddesinde haksız tahrik "Haksız bir fiilin meydana getirdiği şiddet veya şiddetli elemin etkisi altında suç işleyen kimseye..." şeklinde düzenlenmiştir.""",
        },
        {
            "id": 3,
            "daire": "1. Ceza Dairesi",
            "esas": "2025/1857",
            "karar": "2025/5064",
            "tarih": "24.06.2025",
            "metin": """1. Ceza Dairesi 2025/1857 E. , 2025/5064 K.\n\n"İçtihat Metni"\nMeşru müdafaa ve haksız tahrik dengesi kurulurken olayın gelişimi ve haksız eylemin ulaştığı boyut göz önüne alınmalıdır.""",
        },
        {
            "id": 4,
            "daire": "14. Ceza Dairesi",
            "esas": "2018/6721",
            "karar": "2018/8399",
            "tarih": "01.11.2018",
            "metin": """14. Ceza Dairesi 2018/6721 E. , 2018/8399 K.\n\nCinsel dokunulmazlığa karşı suçlarda mağdur beyanı ve delillerin değerlendirilmesi.""",
        },
    ]


kararlar = load_data()

# Arama Çubuğu Formu
with st.form("search_form"):
    col_input, col_btn = st.columns([5, 1])
    with col_input:
        query = st.text_input(
            "Arama Kelimesi",
            value="haksız tahrik",
            placeholder="Aramak istediğiniz kavramı yazın (Ör: haksız tahrik)",
            label_visibility="collapsed",
        )
    with col_btn:
        submitted = st.form_submit_button(
            "Ara", use_container_width=True, type="primary"
        )

# Arama Mantığı ve Sonuçları Filtreleme
filtered_kararlar = []
if query.strip():
    words = [w.strip() for w in query.split() if w.strip()]
    for k in kararlar:
        # Aranan kelimelerin metinde geçip geçmediğini kontrol et
        metin_lower = k["metin"].lower()
        if all(word.lower() in metin_lower for word in words):
            filtered_kararlar.append(k)

# İki Sütunlu Düzen (Sol: Liste / Sağ: Detay)
col_left, col_right = st.columns([5, 7])

with col_left:
    st.info(f"**{len(filtered_kararlar)}** adet karar bulundu.")

    if filtered_kararlar:
        # Tablo Verisini Hazırla
        table_data = [
            {
                "Sıra No": idx + 1,
                "Daire": k["daire"],
                "Esas": k["esas"],
                "Karar": k["karar"],
                "Karar Tarihi": k["tarih"],
            }
            for idx, k in enumerate(filtered_kararlar)
        ]

        # Tıklanabilir Seçim Kutusu
        options = [
            f"{k['daire']} | Esas: {k['esas']} - Karar: {k['karar']} ({k['tarih']})"
            for k in filtered_kararlar
        ]
        selected_option = st.radio(
            "İncelemek istediğiniz kararı seçin:",
            options=options,
            index=0,
            label_visibility="collapsed",
        )

        # Seçilen kararın indeksini bul
        selected_idx = options.index(selected_option)
        selected_karar = filtered_kararlar[selected_idx]
    else:
        st.warning("Aramanıza uygun karar bulunamadı.")
        selected_karar = None

with col_right:
    if selected_karar:
        # Başlık Bilgileri ve Butonlar
        st.markdown(
            f"### {selected_karar['daire']} — {selected_karar['esas']} E. , {selected_karar['karar']} K."
        )

        # Karar metninde aranan kelimeleri vurgulama (Highlight)
        text_to_display = selected_karar["metin"]
        if query.strip():
            words = [
                re.escape(w.strip()) for w in query.split() if w.strip()
            ]
            pattern = re.compile(
                r"(" + "|".join(words) + r")", re.IGNORECASE
            )
            text_to_display = pattern.sub(r"<mark>\1</mark>", text_to_display)

        # Karar Metnini Göster (HTML destekli)
        st.markdown(
            f"""
            <div style="background-color: #ffffff; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; height: 550px; overflow-y: auto; white-space: pre-wrap; font-family: sans-serif; line-height: 1.6; color: #1a202c;">
{text_to_display}
            </div>
            """,
            unsafe_allow_html=True,
        )