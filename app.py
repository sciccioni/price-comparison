import streamlit as st
import pandas as pd
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from openai import OpenAI
import json

# Configurazione Iniziale
st.set_page_config(page_title="Price Intel Hub", layout="wide")

# Sidebar per le API Key
with st.sidebar:
    st.title("Settings")
    api_key = st.text_input("OpenAI API Key", type="password")
    if not api_key:
        st.warning("Inserisci la API Key per attivare l'Organizzatore AI")

# --- CATALOGO DI RIFERIMENTO (Photosì IT) ---
CATALOGO_RIFERIMENTO = [
    {"prodotto": "Racconti (Quadrato)", "formato": "20x20", "prezzo_it": 19.90},
    {"prodotto": "Eventi (A4 Oriz)", "formato": "27x20", "prezzo_it": 29.90},
    {"prodotto": "Attimi (A4 Vert)", "formato": "20x27", "prezzo_it": 24.90}
]

st.title("📊 Global Price Monitor")

# --- INTERFACCIA CONFIGURAZIONE ---
if 'mercati' not in st.session_state:
    st.session_state.mercati = [
        {"paese": "GB", "competitor": "Photobox", "url": "https://www.photobox.co.uk/price-overview"},
        {"paese": "IT", "competitor": "Cewe", "url": "https://www.cewe.it/prezzi.html"},
        {"paese": "IT", "competitor": "PhotoSì", "url": "https://www.photosi.com/it/prezzi"}
    ]

with st.expander("🌍 Configura Target Mercati", expanded=True):
    df_config = st.data_editor(pd.DataFrame(st.session_state.mercati), num_rows="dynamic")
    if st.button("Salva Target"):
        st.session_state.mercati = df_config.to_dict('records')

# --- MOTORE DI SCRAPING (Puro HTML) ---
async def scrape_site(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(5)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            for s in soup(["script", "style", "nav", "footer"]): s.extract()
            return soup.get_text(separator=' | ', strip=True)[:15000]
        except Exception as e:
            return f"Errore: {e}"
        finally:
            await browser.close()

# --- AI ORGANIZER & COMPARATOR ---
def analyze_with_ai(testo, comp_info, api_key):
    client = OpenAI(api_key=api_key)
    prompt = f"""
    Sei un analista esperto di pricing fotolibri.
    Analizza il testo estratto dal sito {comp_info['competitor']} ({comp_info['paese']}).
    ESTRAI i prezzi per i formati Quadrato 20x20, A4 Orizzontale e A4 Verticale.
    CONFRONTA i risultati con il nostro catalogo riferimento: {json.dumps(CATALOGO_RIFERIMENTO)}
    
    Restituisci ESCLUSIVAMENTE un JSON così:
    {{"analisi": [
        {{"mio_prodotto": "...", "formato_loro": "...", "prezzo_loro": 0.0, "valuta": "...", "differenza_vs_it": "..."}}
    ]}}
    """
    
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": testo}],
        response_format={ "type": "json_object" }
    )
    return json.loads(res.choices[0].message.content).get('analisi', [])

# --- ESECUZIONE ---
if st.button("🚀 AVVIA MONITORAGGIO"):
    if not api_key:
        st.error("Manca la API Key!")
    else:
        all_results = []
        for m in st.session_state.mercati:
            with st.status(f"Analizzando {m['competitor']} {m['paese']}...", expanded=True):
                raw_text = asyncio.run(scrape_site(m['url']))
                st.write("📖 Lettura dati completata. AI al lavoro...")
                analysis = analyze_with_ai(raw_text, m, api_key)
                for item in analysis:
                    item['Competitor'] = m['competitor']
                    item['Paese'] = m['paese']
                    all_results.append(item)
        
        if all_results:
            st.divider()
            st.subheader("🏁 Benchmark Finale")
            final_df = pd.DataFrame(all_results)
            st.dataframe(final_df, use_container_width=True)
            
            st.download_button("📥 Scarica Excel Report", 
                               data=final_df.to_csv(index=False), 
                               file_name="benchmark_prezzi.csv")