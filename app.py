import streamlit as st
import pandas as pd
import asyncio
import os
import sys
import json
import subprocess
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from openai import OpenAI

# 1. SETUP INIZIALE
st.set_page_config(page_title="PhotoSì Intelligence Premium", layout="wide")

# 2. INSTALLAZIONE BROWSER (Infallibile con sys.executable)
@st.cache_resource
def install_browser():
    try:
        st.info("🔄 Installazione motore browser in corso... (richiede qualche secondo solo al primo avvio)")
        # Usa l'eseguibile Python corretto del server Streamlit
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install-deps", "chromium"], check=True)
        st.success("✅ Browser installato con successo!")
    except subprocess.CalledProcessError as e:
        st.error(f"❌ Errore durante l'installazione del browser: {e}")

install_browser()

# 3. GESTIONE CHIAVE API
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
elif os.environ.get("OPENAI_API_KEY"):
    api_key = os.environ.get("OPENAI_API_KEY")
else:
    api_key = st.sidebar.text_input("Inserisci OpenAI API Key manualmente", type="password")

if not api_key:
    st.warning("⚠️ Inserisci la chiave API OpenAI per continuare.")
    st.stop()

# 4. CATALOGO PREMIUM
CATALOGO_PHOTOSI = {
    "Racconti (20x20)": 44.90,
    "Eventi (27x20)": 49.90,
    "Attimi (20x30)": 49.90,
    "XL (30x30)": 79.90
}

# 5. INTERFACCIA
st.title("🚀 PhotoSì Intelligence: Monitor Premium")

with st.sidebar:
    st.header("⚙️ Impostazioni")
    rate_gbp = st.number_input("Tasso Cambio 1 GBP in EUR", value=1.18)
    rate_usd = st.number_input("Tasso Cambio 1 USD in EUR", value=0.94)

if 'targets' not in st.session_state:
    st.session_state.targets = [
        {"paese": "GB", "competitor": "Photobox", "url": "https://www.photobox.co.uk/photo-books"},
        {"paese": "IT", "competitor": "Cewe IT", "url": "https://www.cewe.it/fotolibro-cewe.html"},
        {"paese": "IT", "competitor": "Saal Digital", "url": "https://www.saal-digital.it/fotolibro/"},
        {"paese": "IT", "competitor": "Cheerz", "url": "https://www.cheerz.com/it/categories/books"},
        {"paese": "IT", "competitor": "Popsa", "url": "https://popsa.com/it-it/prodotti/fotolibri"}
    ]

with st.expander("🌍 Gestione Target Competitor", expanded=True):
    df_targets = st.data_editor(pd.DataFrame(st.session_state.targets), num_rows="dynamic")

# 6. MOTORE DI SCRAPING (Anti-Crash e Salva RAM per Streamlit)
async def fetch_site_text(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
                "--no-zygote"
            ]
        )
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        
        # Blocca caricamento di immagini e CSS (Risparmia il 90% della RAM)
        await page.route("**/*", lambda route: route.abort() 
                         if route.request.resource_type in ["image", "stylesheet", "media", "font"] 
                         else route.continue_())

        try:
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(5)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/3)")
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            for s in soup(["script", "style", "nav", "footer", "header"]): s.extract()
            return soup.get_text(separator=' | ', strip=True)[:15000]
        except Exception as e:
            return f"Errore caricamento: {str(e)}"
        finally:
            await browser.close()

# 7. LOGICA DI ESECUZIONE
if st.button("🔥 AVVIA MONITORAGGIO PREZZI"):
    client = OpenAI(api_key=api_key)
    all_results = []
    
    for i, row in df_targets.iterrows():
        with st.status(f"Analizzando {row['competitor']}..."):
            testo_grezzo = asyncio.run(fetch_site_text(row['url']))
            
            if testo_grezzo and "Errore caricamento" not in testo_grezzo:
                prompt = f"""
                Analizza il testo del sito {row['competitor']}.
                Trova i prezzi dei fotolibri PREMIUM (carta fotografica, layflat, ecc.).
                Abbinali ESATTAMENTE a queste categorie: {list(CATALOGO_PHOTOSI.keys())}.
                Restituisci solo un JSON in questo formato: 
                {{"data": [{{"match": "...", "nome_loro": "...", "prezzo": 0.0, "valuta": "..."}}]}}
                """
                try:
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": prompt + "\n\nTesto:\n" + testo_grezzo}],
                        response_format={"type": "json_object"}
                    )
                    
                    extracted_data = json.loads(response.choices[0].message.content).get('data', [])
                    
                    for d in extracted_data:
                        rate = 1.0
                        if "GBP" in d['valuta'].upper() or "£" in d['valuta']: rate = rate_gbp
                        elif "USD" in d['valuta'].upper() or "$" in d['valuta']: rate = rate_usd
                        
                        p_eur = round(float(d['prezzo']) * rate, 2)
                        
                        if d['match'] in CATALOGO_PHOTOSI:
                            p_ref = CATALOGO_PHOTOSI[d['match']]
                            delta = round(p_eur - p_ref, 2)
                            
                            all_results.append({
                                "Paese": row['paese'],
                                "Competitor": row['competitor'],
                                "Categoria": d['match'],
                                "Prezzo Loro (€)": p_eur,
                                "PhotoSì (€)": p_ref,
                                "Delta (€)": delta,
                                "Status": "🟢 Conveniente" if delta < 0 else "🔴 Più Caro"
                            })
                except Exception as e:
                    st.error(f"Errore AI su {row['competitor']}: {e}")
            else:
                st.warning(f"Impossibile leggere il sito {row['competitor']}.")
    
    if all_results:
        st.divider()
        st.subheader("🏁 Risultati del Confronto")
        st.dataframe(pd.DataFrame(all_results), use_container_width=True)
