import streamlit as st
import pandas as pd
import asyncio
import os
import json
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from openai import OpenAI

# --- INSTALLAZIONE BROWSER AUTOMATICA ---
# Questo comando scarica Chromium all'interno del server Streamlit
if "playwright_install" not in st.session_state:
    os.system("playwright install chromium")
    st.session_state.playwright_install = True

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="PhotoSì Intelligence Premium", layout="wide")

# Recupero API Key dai Secrets di Streamlit
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
else:
    api_key = st.sidebar.text_input("OpenAI API Key", type="password")

# Catalogo Premium PhotoSì
CATALOGO_PHOTOSI = {
    "Racconti (20x20)": 44.90,
    "Eventi (27x20)": 49.90,
    "Attimi (20x30)": 49.90,
    "XL (30x30)": 79.90
}

st.title("🚀 Monitor Competitor Premium")

with st.sidebar:
    st.header("⚙️ Cambi Valuta")
    rate_gbp = st.number_input("1 GBP in EUR", value=1.18)
    rate_usd = st.number_input("1 USD in EUR", value=0.94)

# Lista Mercati
if 'targets' not in st.session_state:
    st.session_state.targets = [
        {"paese": "GB", "competitor": "Photobox", "url": "https://www.photobox.co.uk/photo-books"},
        {"paese": "IT", "competitor": "Cewe IT", "url": "https://www.cewe.it/fotolibro-cewe.html"},
        {"paese": "IT", "competitor": "Saal Digital", "url": "https://www.saal-digital.it/fotolibro/"},
        {"paese": "IT", "competitor": "Cheerz", "url": "https://www.cheerz.com/it/categories/books"}
    ]

df_targets = st.data_editor(pd.DataFrame(st.session_state.targets), num_rows="dynamic")

# --- MOTORE DI SCRAPING ---
async def fetch_text(url):
    async with async_playwright() as p:
        # Lancio chromium con parametri di sicurezza per i server
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(5)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            for s in soup(["script", "style"]): s.extract()
            return soup.get_text(separator=' | ', strip=True)[:10000]
        except Exception as e:
            return f"Errore: {e}"
        finally:
            await browser.close()

# --- LOGICA ---
if st.button("🔥 AVVIA SCANSIONE"):
    if not api_key:
        st.error("Inserisci la API Key!")
    else:
        client = OpenAI(api_key=api_key)
        all_data = []
        
        for _, row in df_targets.iterrows():
            with st.status(f"Analizzando {row['competitor']}..."):
                testo = asyncio.run(fetch_text(row['url']))
                
                if "Errore" not in testo:
                    prompt = f"Estrai prezzi Premium per {list(CATALOGO_PHOTOSI.keys())}. Ritorna SOLO JSON: {{\"data\": [{{\"match\": \"...\", \"prezzo\": 0.0, \"valuta\": \"...\"}}]}}"
                    res = client.chat.completions.create(
                        model="gpt-4o", 
                        messages=[{"role": "user", "content": testo}],
                        response_format={"type": "json_object"}
                    )
                    
                    items = json.loads(res.choices[0].message.content).get('data', [])
                    for i in items:
                        val = i['valuta'].upper()
                        r = rate_gbp if "GBP" in val or "£" in val else rate_usd if "USD" in val or "$" in val else 1.0
                        
                        p_eur = round(float(i['prezzo']) * r, 2)
                        p_ref = CATALOGO_PHOTOSI[i['match']]
                        
                        all_data.append({
                            "Paese": row['paese'],
                            "Competitor": row['competitor'],
                            "Categoria": i['match'],
                            "Loro (€)": p_eur,
                            "PhotoSì (€)": p_ref,
                            "Delta (€)": round(p_eur - p_ref, 2)
                        })
        
        if all_data:
            st.table(pd.DataFrame(all_data))
