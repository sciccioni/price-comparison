import streamlit as st
import pandas as pd
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from openai import OpenAI
import json
import os

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="PhotoSì Intelligence Premium", layout="wide")

# --- 2. RECUPERO CHIAVE API (DA SECRETS) ---
# Questo blocco elimina l'errore se la chiave è nei Secrets di Streamlit
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
else:
    # Se non la trova nei segreti, la cerca nelle variabili d'ambiente (per sicurezza)
    api_key = os.environ.get("OPENAI_API_KEY", "")

# Se ancora non c'è, mostra il box nella sidebar per l'inserimento manuale
if not api_key:
    api_key = st.sidebar.text_input("Inserisci OpenAI API Key manualmente", type="password")

# --- 3. IL TUO CATALOGO PREMIUM (Benchmark) ---
CATALOGO_PHOTOSI = {
    "Racconti (20x20)": {"dim": "20x20", "prezzo": 44.90},
    "Eventi (27x20)": {"dim": "27x20", "prezzo": 49.90},
    "Attimi (20x30)": {"dim": "20x30", "prezzo": 49.90},
    "XL (30x30)": {"dim": "30x30", "prezzo": 79.90}
}

# --- 4. INTERFACCIA UTENTE ---
st.title("🚀 PhotoSì Intelligence: Monitor Premium")
st.markdown("Analisi dei competitor internazionali confrontati con il listino **PhotoSì Premium**.")

with st.sidebar:
    st.header("⚙️ Impostazioni")
    rate_gbp = st.number_input("Tasso Cambio 1 GBP in EUR", value=1.18)
    rate_usd = st.number_input("Tasso Cambio 1 USD in EUR", value=0.94)
    if not api_key:
        st.warning("⚠️ Chiave API mancante. Inseriscila nei Secrets di Streamlit.")

# Target Mercati
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

# --- 5. MOTORE DI SCRAPING ---
async def fetch_site_text(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        try:
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(7)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            for s in soup(["script", "style", "nav", "footer", "header"]): s.extract()
            return soup.get_text(separator=' | ', strip=True)[:15000]
        except: return ""
        finally: await browser.close()

# --- 6. AZIONE DI MONITORAGGIO ---
if st.button("🔥 AVVIA MONITORAGGIO PREZZI"):
    if not api_key:
        st.error("Errore: Manca la chiave API OpenAI.")
    else:
        client = OpenAI(api_key=api_key)
        all_results = []
        
        for i, row in df_targets.iterrows():
            with st.status(f"Analizzando {row['competitor']}..."):
                testo_grezzo = asyncio.run(fetch_site_text(row['url']))
                
                if testo_grezzo:
                    prompt = f"""
                    Analizza il testo del sito {row['competitor']}.
                    Trova i prezzi dei fotolibri PREMIUM (carta fotografica o layflat).
                    Abbinali a queste categorie: {list(CATALOGO_PHOTOSI.keys())}.
                    Restituisci solo JSON: {{"data": [{{"match": "...", "nome_loro": "...", "prezzo": 0.0, "valuta": "..."}}]}}
                    """
                    
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": testo_grezzo}],
                        response_format={"type": "json_object"}
                    )
                    
                    extracted_data = json.loads(response.choices[0].message.content).get('data', [])
                    
                    for d in extracted_data:
                        # Calcolo Valuta e Delta
                        rate = 1.0
                        if "GBP" in d['valuta'].upper(): rate = rate_gbp
                        elif "USD" in d['valuta'].upper(): rate = rate_usd
                        
                        p_eur = round(float(d['prezzo']) * rate, 2)
                        p_ref = CATALOGO_PHOTOSI[d['match']]['prezzo']
                        delta = round(p_eur - p_ref, 2)
                        
                        all_results.append({
                            "Paese": row['paese'],
                            "Competitor": row['competitor'],
                            "Categoria": d['match'],
                            "Prezzo Loro (€)": p_eur,
                            "PhotoSì (€)": p_ref,
                            "Delta (€)": delta,
                            "Status": "🟢 OK" if delta < 0 else "🔴 PIÙ CARO"
                        })
        
        if all_results:
            st.divider()
            st.subheader("🏁 Risultati del Confronto")
            st.dataframe(pd.DataFrame(all_results), use_container_width=True)
            st.download_button("📥 Scarica CSV", pd.DataFrame(all_results).to_csv(index=False), "report.csv")
        else:
            st.error("Non è stato possibile estrarre dati. Riprova o controlla gli URL.")
