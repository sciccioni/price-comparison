import streamlit as st
import pandas as pd
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from openai import OpenAI
import json

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="PhotoSì Intelligence", layout="wide")

# Sidebar per API Key e Cambi Valuta
with st.sidebar:
    st.title("Impostazioni")
    api_key = st.text_input("OpenAI API Key", type="password")
    st.divider()
    rate_gbp = st.number_input("Cambio 1 GBP in EUR", value=1.18)
    rate_usd = st.number_input("Cambio 1 USD in EUR", value=0.94)

# --- IL TUO CATALOGO PREMIUM (Benchmark) ---
CATALOGO_PHOTOSI = {
    "Racconti (20x20)": {"dim": "20x20", "prezzo": 44.90},
    "Eventi (27x20)": {"dim": "27x20", "prezzo": 49.90},
    "Attimi (20x30)": {"dim": "20x30", "prezzo": 49.90},
    "XL (30x30)": {"dim": "30x30", "prezzo": 79.90}
}

st.title("📸 Monitor Prezzi Competitor: Linea Premium")
st.markdown("Confronto automatico dei competitor internazionali con il listino **PhotoSì Premium**.")

# --- SELEZIONE TARGET (Mercati) ---
if 'targets' not in st.session_state:
    st.session_state.targets = [
        {"paese": "GB", "competitor": "Photobox", "url": "https://www.photobox.co.uk/photo-books"},
        {"paese": "IT", "competitor": "Cewe", "url": "https://www.cewe.it/fotolibro-cewe.html"},
        {"paese": "DE", "competitor": "Saal-Digital", "url": "https://www.saal-digital.de/fotobuch/"},
        {"paese": "IT", "competitor": "Cheerz", "url": "https://www.cheerz.com/it/categories/books"}
    ]

with st.expander("🌍 Gestisci Mercati e URL", expanded=True):
    df_targets = st.data_editor(pd.DataFrame(st.session_state.targets), num_rows="dynamic")

# --- MOTORE DI SCRAPING (Sfondo la porta) ---
async def fetch_html(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent="Mozilla/5.0")
        try:
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(7)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            for s in soup(["script", "style", "nav", "footer"]): s.extract()
            return soup.get_text(separator=' | ', strip=True)[:15000]
        except: return "Errore caricamento"
        finally: await browser.close()

# --- ORGANIZZATORE AI ---
def analyze_data(text, api_key):
    client = OpenAI(api_key=api_key)
    prompt = f"""
    Trova i fotolibri PREMIUM (carta fotografica/layflat) nel testo.
    Abbinali a: {list(CATALOGO_PHOTOSI.keys())}.
    Estrai: Nome, Prezzo numerico, Valuta (EUR, GBP, USD).
    Rispondi SOLO JSON: {{"data": [{{"match": "...", "nome_loro": "...", "prezzo": 0.0, "valuta": "..."}}]}}
    """
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
        response_format={ "type": "json_object" }
    )
    return json.loads(res.choices[0].message.content).get('data', [])

# --- ESECUZIONE ---
if st.button("🚀 AVVIA MONITORAGGIO"):
    if not api_key:
        st.error("Inserisci la OpenAI API Key nella barra laterale!")
    else:
        all_results = []
        for _, row in df_targets.iterrows():
            with st.status(f"Analizzando {row['competitor']} ({row['paese']})..."):
                raw_text = asyncio.run(fetch_html(row['url']))
                extracted = analyze_data(raw_text, api_key)
                
                for e in extracted:
                    # Calcolo Valuta e Delta
                    rate = 1.0
                    if e['valuta'] == "GBP": rate = rate_gbp
                    elif e['valuta'] == "USD": rate = rate_usd
                    
                    p_comp = round(e['prezzo'] * rate, 2)
                    p_ref = CATALOGO_PHOTOSI[e['match']]['prezzo']
                    delta = round(p_comp - p_ref, 2)
                    
                    all_results.append({
                        "Paese": row['paese'],
                        "Competitor": row['competitor'],
                        "Categoria": e['match'],
                        "Prezzo Loro (€)": p_comp,
                        "PhotoSì (€)": p_ref,
                        "Delta (€)": delta,
                        "Status": "🟢 Più economico" if delta < 0 else "🔴 Più caro"
                    })
        
        if all_results:
            st.divider()
            st.subheader("🏁 Report di Confronto")
            st.dataframe(pd.DataFrame(all_results), use_container_width=True)
            st.download_button("📥 Scarica Excel", pd.DataFrame(all_results).to_csv(index=False), "benchmark.csv")
