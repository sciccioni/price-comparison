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

# --- GESTIONE CHIAVE API (SECRET) ---
# Prova a leggere dai Secrets di Streamlit o dalle variabili d'ambiente
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
elif os.environ.get("OPENAI_API_KEY"):
    api_key = os.environ.get("OPENAI_API_KEY")
else:
    api_key = st.sidebar.text_input("OpenAI API Key", type="password")

if not api_key:
    st.error("❌ Chiave API non trovata. Inseriscila nei Secrets di Streamlit o nella Sidebar.")
    st.stop()

# --- CATALOGO RIFERIMENTO PHOTOSÌ (PREMIUM) ---
CATALOGO_PHOTOSI = {
    "Racconti (20x20)": {"dim": "20x20", "prezzo": 44.90},
    "Eventi (27x20)": {"dim": "27x20", "prezzo": 49.90},
    "Attimi (20x30)": {"dim": "20x30", "prezzo": 49.90},
    "XL (30x30)": {"dim": "30x30", "prezzo": 79.90}
}

# Sidebar per i tassi di cambio
with st.sidebar:
    st.header("💱 Tassi di Cambio")
    rate_gbp = st.number_input("1 GBP in EUR", value=1.18)
    rate_usd = st.number_input("1 USD in EUR", value=0.94)

st.title("📸 Monitor Competitor: Linea Premium")

# --- TARGET MERCATI ---
if 'targets' not in st.session_state:
    st.session_state.targets = [
        {"paese": "GB", "competitor": "Photobox", "url": "https://www.photobox.co.uk/photo-books"},
        {"paese": "IT", "competitor": "Cewe IT", "url": "https://www.cewe.it/fotolibro-cewe.html"},
        {"paese": "IT", "competitor": "PhotoSì", "url": "https://www.photosi.com/it/album-foto/fotolibri"}
    ]

with st.expander("🌍 Gestisci Mercati e URL Target", expanded=True):
    df_targets = st.data_editor(pd.DataFrame(st.session_state.targets), num_rows="dynamic")

# --- FUNZIONE SCRAPING ---
async def fetch_clean_text(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        try:
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(8)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            for s in soup(["script", "style", "nav", "footer", "header"]): s.extract()
            return soup.get_text(separator=' | ', strip=True)[:15000]
        except Exception as e:
            return f"Errore: {e}"
        finally:
            await browser.close()

# --- FUNZIONE AI ---
def analyze_with_ai(text, competitor_name, api_key):
    client = OpenAI(api_key=api_key)
    prompt = f"""
    Analizza il testo del sito {competitor_name}. 
    Trova i prezzi dei fotolibri PREMIUM (carta fotografica, layflat o professional).
    Abbinali a: {list(CATALOGO_PHOTOSI.keys())}.
    Rispondi SOLO JSON: {{"analisi": [{{"match": "...", "nome_loro": "...", "prezzo": 0.0, "valuta": "..."}}]}}
    """
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
        response_format={ "type": "json_object" }
    )
    return json.loads(response.choices[0].message.content).get('analisi', [])

# --- ESECUZIONE ---
if st.button("🚀 AVVIA MONITORAGGIO"):
    all_data = []
    for i, row in df_targets.iterrows():
        with st.status(f"Analizzando {row['competitor']}..."):
            raw_text = asyncio.run(fetch_clean_text(row['url']))
            extracted = analyze_with_ai(raw_text, row['competitor'], api_key)
            for e in extracted:
                rate = 1.0
                if "GBP" in e['valuta']: rate = rate_gbp
                elif "USD" in e['valuta']: rate = rate_usd
                
                p_comp = round(float(e['prezzo']) * rate, 2)
                p_ref = CATALOGO_PHOTOSI[e['match']]['prezzo']
                delta = round(p_comp - p_ref, 2)
                
                all_data.append({
                    "Paese": row['paese'],
                    "Competitor": row['competitor'],
                    "Categoria": e['match'],
                    "Prezzo Loro (€)": p_comp,
                    "PhotoSì (€)": p_ref,
                    "Delta (€)": delta,
                    "Status": "🟢 OK" if delta < 0 else "🔴 CARO"
                })

    if all_data:
        st.divider()
        st.dataframe(pd.DataFrame(all_data), use_container_width=True)
