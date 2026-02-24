import streamlit as st
import pandas as pd
import asyncio
import os
import sys
import json
import subprocess
import plotly.express as px
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from openai import OpenAI

# --- 1. SETUP INIZIALE ---
st.set_page_config(page_title="PhotoSì Intelligence Premium", layout="wide")

# --- 2. INSTALLAZIONE BROWSER (Sicura, senza errori di root) ---
@st.cache_resource
def install_browser():
    try:
        st.info("🔄 Download del browser in corso... (richiede qualche secondo al primo avvio)")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        st.success("✅ Browser pronto!")
    except subprocess.CalledProcessError as e:
        st.error(f"❌ Errore durante il download del browser: {e}")

install_browser()

# --- 3. GESTIONE CHIAVE API ---
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
elif os.environ.get("OPENAI_API_KEY"):
    api_key = os.environ.get("OPENAI_API_KEY")
else:
    api_key = st.sidebar.text_input("Inserisci OpenAI API Key manualmente", type="password")

if not api_key:
    st.warning("⚠️ Inserisci la chiave API OpenAI per continuare.")
    st.stop()

# --- 4. CATALOGO PREMIUM ---
CATALOGO_PHOTOSI = {
    "Racconti (20x20)": 44.90,
    "Eventi (27x20)": 49.90,
    "Attimi (20x30)": 49.90,
    "XL (30x30)": 79.90
}

# --- 5. INTERFACCIA E IMPOSTAZIONI ---
st.title("🚀 PhotoSì Intelligence: Monitor Premium")
st.markdown("Dashboard di monitoraggio prezzi competitor. I dati sono estratti in tempo reale e confrontati col listino Premium.")

with st.sidebar:
    st.header("⚙️ Impostazioni Valute")
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

# --- 6. MOTORE DI SCRAPING (Ottimizzato per Streamlit Cloud) ---
async def fetch_site_text(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process"
            ]
        )
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        
        # Blocca immagini e CSS per risparmiare RAM ed evitare crash
        await page.route("**/*", lambda route: route.abort() 
                         if route.request.resource_type in ["image", "stylesheet", "media", "font"] 
                         else route.continue_())

        try:
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(6) # Tempo per far caricare i prezzi dinamici
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/3)")
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            for s in soup(["script", "style", "nav", "footer", "header"]): s.extract()
            return soup.get_text(separator=' | ', strip=True)[:15000]
        except Exception as e:
            return f"Errore caricamento: {str(e)}"
        finally:
            await browser.close()

# --- 7. LOGICA DI ESECUZIONE E VISUALIZZAZIONE ---
if st.button("🔥 AVVIA MONITORAGGIO PREZZI", type="primary"):
    client = OpenAI(api_key=api_key)
    all_results = []
    
    # Progress bar estetica
    progress_text = "Scansione siti in corso..."
    my_bar = st.progress(0, text=progress_text)
    
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
        
        # Aggiorna progress bar
        my_bar.progress((i + 1) / len(df_targets), text=progress_text)
    
    my_bar.empty() # Pulisce la barra alla fine
    
    # --- VISUALIZZAZIONE PROFESSIONALE DEI RISULTATI ---
    if all_results:
        st.divider()
        df_res = pd.DataFrame(all_results)
        
        # --- 1. METRICHE KPI ---
        st.subheader("📊 Riepilogo Mercato")
        col1, col2, col3 = st.columns(3)
        
        minaccia = df_res.loc[df_res['Delta (€)'].idxmin()]
        prezzo_medio = df_res['Prezzo Loro (€)'].mean()
        
        with col1:
            st.metric("Prodotti Scansionati", len(df_res))
        with col2:
            st.metric(f"🔥 Minaccia Maggiore ({minaccia['Competitor']})", 
                      f"€ {minaccia['Prezzo Loro (€)']:.2f}", 
                      f"{minaccia['Delta (€)']:.2f} € vs PhotoSì", 
                      delta_color="inverse")
        with col3:
            st.metric("Prezzo Medio Mercato", f"€ {prezzo_medio:.2f}")

        st.divider()

        # --- 2. GRAFICO INTERATTIVO PLOTLY ---
        
        st.subheader("📈 Confronto Delta (Chi costa meno di te?)")
        fig = px.bar(
            df_res, 
            x='Competitor', 
            y='Delta (€)', 
            color='Categoria',
            text_auto='.2f',
            title='Differenza di Prezzo vs PhotoSì Premium (Zero = Stesso Prezzo)',
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="Prezzo PhotoSì")
        fig.update_layout(yaxis_title="Delta in Euro (€)", xaxis_title="Competitor")
        st.plotly_chart(fig, use_container_width=True)

        # --- 3. TABELLA FORMATTATA E DOWNLOAD ---
        st.subheader("📋 Dettaglio Dati")
        
        def color_status(val):
            color = '#e6ffed' if 'Conveniente' in val else '#ffeef0'
            text_color = '#117a35' if 'Conveniente' in val else '#b3001b'
            return f'background-color: {color}; color: {text_color}; font-weight: bold'

        # Creiamo una copia formattata per la visualizzazione a schermo
        df_display = df_res.copy()
        
        # Stile visivo della tabella
        st.dataframe(
            df_display.style.map(color_status, subset=['Status'])
            .format({
                'Prezzo Loro (€)': "€ {:.2f}", 
                'PhotoSì (€)': "€ {:.2f}", 
                'Delta (€)': "€ {:.2f}"
            }), 
            use_container_width=True, 
            hide_index=True
        )
        
        # Bottone Download ottimizzato per l'Italia (virgola per i decimali)
        st.download_button(
            label="📥 Scarica Report Excel/CSV",
            data=df_res.to_csv(index=False, sep=';', decimal=','),
            file_name="benchmark_premium_photosi.csv",
            mime="text/csv"
        )
