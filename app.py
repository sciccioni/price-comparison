import streamlit as st
import pandas as pd
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from openai import OpenAI
import json
import os

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="PhotoSì Premium Intelligence", layout="wide")

# --- GESTIONE CHIAVE API (SEGRETI) ---
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
else:
    api_key = st.sidebar.text_input("OpenAI API Key", type="password")

# --- CATALOGO RIFERIMENTO PHOTOSÌ (PREMIUM) ---
# Prezzi basati sul listino che mi hai fornito (Carta Fotografica 20 pag)
CATALOGO_PHOTOSI = {
    "Racconti (Quadrato)": {"formato": "20x20", "prezzo": 44.90},
    "Eventi (A4 Oriz)": {"formato": "27x20", "prezzo": 49.90},
    "Attimi (A4 Vert)": {"formato": "20x30", "prezzo": 49.90},
    "XL (30x30)": {"formato": "30x30", "prezzo": 79.90}
}

# Sidebar per i tassi di cambio (personalizzabili)
with st.sidebar:
    st.header("💱 Tassi di Cambio")
    rate_gbp = st.number_input("1 GBP in EUR", value=1.18)
    rate_usd = st.number_input("1 USD in EUR", value=0.94)

st.title("📸 Monitor Competitor: Linea Premium")
st.markdown("Analisi automatica dei prezzi internazionali confrontati con il listino **PhotoSì Premium**.")

# --- DEFINIZIONE TARGET (MERCATI) ---
if 'targets' not in st.session_state:
    st.session_state.targets = [
        {"paese": "GB", "competitor": "Photobox", "url": "https://www.photobox.co.uk/photo-books"},
        {"paese": "GB", "competitor": "Cewe UK", "url": "https://www.cewe.co.uk/photo-books.html"},
        {"paese": "IT", "competitor": "Cewe IT", "url": "https://www.cewe.it/fotolibro-cewe.html"},
        {"paese": "IT", "competitor": "Saal Digital", "url": "https://www.saal-digital.it/fotolibro/"},
        {"paese": "IT", "competitor": "Cheerz", "url": "https://www.cheerz.com/it/categories/books"},
        {"paese": "IT", "competitor": "Popsa", "url": "https://popsa.com/it-it/prodotti/fotolibri"}
    ]

with st.expander("🌍 Configura Mercati e URL Target", expanded=True):
    df_targets = st.data_editor(pd.DataFrame(st.session_state.targets), num_rows="dynamic")

# --- FUNZIONE SCRAPING ---
async def fetch_clean_text(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        try:
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(8) # Attesa per render prezzi dinamici
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            # Rimuovo spazzatura
            for s in soup(["script", "style", "nav", "footer", "header"]): s.extract()
            return soup.get_text(separator=' | ', strip=True)[:15000]
        except Exception as e:
            return f"Errore: {e}"
        finally:
            await browser.close()

# --- FUNZIONE ANALISI AI ---
def analyze_with_ai(text, competitor_name, api_key):
    client = OpenAI(api_key=api_key)
    prompt = f"""
    Analizza il testo del sito {competitor_name}. 
    Trova i prezzi dei fotolibri PREMIUM (carta fotografica, layflat o professional).
    Abbinali a una di queste categorie PhotoSì: {list(CATALOGO_PHOTOSI.keys())}.
    
    Estrai SOLO:
    - Match Categoria
    - Nome Prodotto Competitor
    - Prezzo Numerico (usa il punto per i decimali)
    - Valuta (EUR, GBP, USD)

    Restituisci esclusivamente un JSON:
    {{"analisi": [{{"match": "...", "nome_loro": "...", "prezzo": 0.0, "valuta": "..."}}]}}
    """
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
        response_format={ "type": "json_object" }
    )
    return json.loads(response.choices[0].message.content).get('analisi', [])

# --- LOGICA DI ESECUZIONE ---
if st.button("🚀 AVVIA MONITORAGGIO"):
    if not api_key:
        st.error("❌ Chiave API non trovata. Inseriscila nei Secrets o nella Sidebar.")
    else:
        all_data = []
        progress_bar = st.progress(0)
        
        for i, row in df_targets.iterrows():
            with st.status(f"Analizzando {row['competitor']} ({row['paese']})..."):
                raw_text = asyncio.run(fetch_clean_text(row['url']))
                
                if "Errore" not in raw_text:
                    extracted = analyze_with_ai(raw_text, row['competitor'], api_key)
                    
                    for e in extracted:
                        # Conversione Valuta
                        valuta = e.get('valuta', 'EUR').upper()
                        rate = 1.0
                        if "GBP" in valuta or "£" in valuta: rate = rate_gbp
                        elif "USD" in valuta or "$" in valuta: rate = rate_usd
                        
                        prezzo_eur = round(float(e['prezzo']) * rate, 2)
                        match_cat = e['match']
                        
                        if match_cat in CATALOGO_PHOTOSI:
                            prezzo_ref = CATALOGO_PHOTOSI[match_cat]['prezzo']
                            delta = round(prezzo_eur - prezzo_ref, 2)
                            
                            all_data.append({
                                "Paese": row['paese'],
                                "Competitor": row['competitor'],
                                "Categoria": match_cat,
                                "Prodotto Loro": e['nome_loro'],
                                "Prezzo Loro (€)": prezzo_eur,
                                "PhotoSì (€)": prezzo_ref,
                                "Delta (€)": delta,
                                "Status": "🟢 Più economico" if delta < 0 else "🔴 Più caro"
                            })
            progress_bar.progress((i + 1) / len(df_targets))

        if all_data:
            st.divider()
            st.subheader("🏁 Risultati del Benchmark")
            df_final = pd.DataFrame(all_data)
            
            # Formattazione tabella
            st.dataframe(df_final.style.applymap(
                lambda x: 'color: green' if x == "🟢 Più economico" else 'color: red' if x == "🔴 Più caro" else '',
                subset=['Status']
            ), use_container_width=True)
            
            # Download
            st.download_button("📥 Scarica Report Excel (CSV)", df_final.to_csv(index=False), "benchmark_premium.csv")
        else:
            st.warning("Nessun dato estratto. Controlla gli URL o la struttura dei siti.")
