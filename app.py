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
from supabase import create_client, Client

# --- 1. SETUP INIZIALE ---
st.set_page_config(page_title="PhotoSì Intelligence Premium", layout="wide", initial_sidebar_state="expanded")

# --- 2. INSTALLAZIONE BROWSER (Sicura, infallibile) ---
@st.cache_resource
def install_browser():
    try:
        # Non mostriamo più il messaggio ogni volta se è già installato
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        st.error(f"❌ Errore durante il download del browser: {e}")

install_browser()

# --- 3. GESTIONE CREDENZIALI (SECRETS) ---
# OpenAI
api_key = st.secrets.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
# Supabase
supa_url = st.secrets.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
supa_key = st.secrets.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")

with st.sidebar:
    st.header("🔑 Stato Connessioni")
    if not api_key: st.error("❌ OpenAI API Key mancante")
    else: st.success("✅ OpenAI Connesso")
    
    if not supa_url or not supa_key: st.error("❌ Supabase Credenziali mancanti")
    else: st.success("✅ Database Connesso")
    
    st.divider()
    st.header("⚙️ Impostazioni Valute")
    rate_gbp = st.number_input("Tasso Cambio 1 GBP in EUR", value=1.18)
    rate_usd = st.number_input("Tasso Cambio 1 USD in EUR", value=0.94)

if not api_key or not supa_url or not supa_key:
    st.warning("⚠️ Inserisci tutte le chiavi (OpenAI e Supabase) nei Secrets per continuare.")
    st.stop()

# Inizializza client Supabase
supabase: Client = create_client(supa_url, supa_key)

# --- 4. CATALOGO PREMIUM ---
CATALOGO_PHOTOSI = {
    "Racconti (20x20)": 44.90,
    "Eventi (27x20)": 49.90,
    "Attimi (20x30)": 49.90,
    "XL (30x30)": 79.90
}

# --- 5. INTERFACCIA E TARGET ---
st.title("🚀 PhotoSì Intelligence: Monitor Premium")

if 'targets' not in st.session_state:
    st.session_state.targets = [
        {"paese": "GB", "competitor": "Photobox", "url": "https://www.photobox.co.uk/photo-books"},
        {"paese": "IT", "competitor": "Cewe IT", "url": "https://www.cewe.it/fotolibro-cewe.html"},
        {"paese": "IT", "competitor": "Saal Digital", "url": "https://www.saal-digital.it/fotolibro/"},
        {"paese": "IT", "competitor": "Cheerz", "url": "https://www.cheerz.com/it/categories/books"},
        {"paese": "IT", "competitor": "Popsa", "url": "https://popsa.com/it-it/prodotti/fotolibri"}
    ]

with st.expander("🌍 Gestione Target Competitor", expanded=False):
    df_targets = st.data_editor(pd.DataFrame(st.session_state.targets), num_rows="dynamic")

# --- 6. MOTORE DI SCRAPING (Anti-crash) ---
async def fetch_site_text(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"]
        )
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        await page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "media", "font"] else route.continue_())

        try:
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(6)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/3)")
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            for s in soup(["script", "style", "nav", "footer", "header"]): s.extract()
            return soup.get_text(separator=' | ', strip=True)[:15000]
        except Exception as e:
            return f"Errore caricamento: {str(e)}"
        finally:
            await browser.close()

# --- 7. LOGICA DI SCANSIONE E SALVATAGGIO ---
if st.button("🔥 ESEGUI NUOVA SCANSIONE", type="primary"):
    client = OpenAI(api_key=api_key)
    scraped_data = []
    db_records = []
    
    my_bar = st.progress(0, text="Avvio scansione...")
    
    for i, row in df_targets.iterrows():
        with st.status(f"Analizzando {row['competitor']}..."):
            testo_grezzo = asyncio.run(fetch_site_text(row['url']))
            
            if testo_grezzo and "Errore caricamento" not in testo_grezzo:
                prompt = f"""
                Trova i prezzi dei fotolibri PREMIUM (carta fotografica, layflat).
                Abbinali ESATTAMENTE a: {list(CATALOGO_PHOTOSI.keys())}.
                JSON: {{"data": [{{"match": "...", "nome_loro": "...", "prezzo": 0.0, "valuta": "..."}}]}}
                """
                try:
                    res = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": prompt + "\nTesto:\n" + testo_grezzo}],
                        response_format={"type": "json_object"}
                    )
                    
                    extracted = json.loads(res.choices[0].message.content).get('data', [])
                    
                    for d in extracted:
                        rate = rate_gbp if "GBP" in d['valuta'].upper() or "£" in d['valuta'] else rate_usd if "USD" in d['valuta'].upper() or "$" in d['valuta'] else 1.0
                        p_eur = round(float(d['prezzo']) * rate, 2)
                        
                        if d['match'] in CATALOGO_PHOTOSI:
                            p_ref = CATALOGO_PHOTOSI[d['match']]
                            delta = round(p_eur - p_ref, 2)
                            status_text = "🟢 Conveniente" if delta < 0 else "🔴 Più Caro"
                            
                            # Dati per la visualizzazione a schermo
                            scraped_data.append({
                                "Paese": row['paese'], "Competitor": row['competitor'], 
                                "Categoria": d['match'], "Prezzo Loro (€)": p_eur,
                                "PhotoSì (€)": p_ref, "Delta (€)": delta, "Status": status_text
                            })
                            
                            # Dati per il Database (nomi colonne esatti SQL)
                            db_records.append({
                                "paese": row['paese'], "competitor": row['competitor'],
                                "categoria": d['match'], "prodotto_loro": d.get('nome_loro', 'N/D'),
                                "prezzo_loro_eur": p_eur, "prezzo_photosi_eur": p_ref,
                                "delta_eur": delta, "status": status_text
                            })
                except Exception as e:
                    st.error(f"Errore AI su {row['competitor']}: {e}")
            else:
                st.warning(f"Impossibile leggere il sito {row['competitor']}.")
        
        my_bar.progress((i + 1) / len(df_targets), text="Scansione in corso...")
    
    my_bar.empty()
    
    # SALVATAGGIO SU SUPABASE
    if db_records:
        try:
            supabase.table("storico_prezzi").insert(db_records).execute()
            st.success("💾 Dati salvati con successo nel Database!")
        except Exception as e:
            st.error(f"Errore salvataggio DB: {e}")

    # MOSTRA RISULTATI CORRENTI
    if scraped_data:
        st.subheader("📊 Risultati Ultima Scansione")
        df_res = pd.DataFrame(scraped_data)
        
        col1, col2, col3 = st.columns(3)
        minaccia = df_res.loc[df_res['Delta (€)'].idxmin()]
        with col1: st.metric("Prezzo Medio Scansionato", f"€ {df_res['Prezzo Loro (€)'].mean():.2f}")
        with col2: st.metric(f"🔥 Minaccia ({minaccia['Competitor']})", f"€ {minaccia['Prezzo Loro (€)']:.2f}", f"{minaccia['Delta (€)']:.2f} €", delta_color="inverse")
        
        def color_status(val):
            return 'background-color: #e6ffed; color: #117a35' if 'Conveniente' in val else 'background-color: #ffeef0; color: #b3001b'
            
        st.dataframe(df_res.style.map(color_status, subset=['Status']).format({'Prezzo Loro (€)': "€ {:.2f}", 'PhotoSì (€)': "€ {:.2f}", 'Delta (€)': "€ {:.2f}"}), use_container_width=True, hide_index=True)

st.divider()

# --- 8. STORICO DATI (CARICAMENTO DA SUPABASE) ---
st.header("🕰️ Macchina del Tempo: Storico Prezzi")


try:
    # Scarica tutti i dati dal DB
    response = supabase.table("storico_prezzi").select("*").order("data_scansione", desc=False).execute()
    storico_dati = response.data
    
    if storico_dati:
        df_storico = pd.DataFrame(storico_dati)
        # Formatta la data per renderla leggibile
        df_storico['data_scansione'] = pd.to_datetime(df_storico['data_scansione']).dt.strftime('%Y-%m-%d %H:%M')
        
        # Filtri per il grafico
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            cat_scelta = st.selectbox("Seleziona Categoria per il Trend", df_storico['categoria'].unique())
        
        # Filtra i dati per il grafico in base alla categoria
        df_grafico = df_storico[df_storico['categoria'] == cat_scelta]
        
        # Grafico Trend Temporale
        fig_storico = px.line(
            df_grafico, 
            x="data_scansione", 
            y="prezzo_loro_eur", 
            color="competitor",
            markers=True,
            title=f"Trend Prezzi nel Tempo: {cat_scelta}",
            labels={"prezzo_loro_eur": "Prezzo (€)", "data_scansione": "Data Scansione", "competitor": "Competitor"}
        )
        
        # Aggiunge la linea del tuo prezzo fisso
        tuo_prezzo = CATALOGO_PHOTOSI[cat_scelta]
        fig_storico.add_hline(y=tuo_prezzo, line_dash="dash", line_color="red", annotation_text="Tuo Prezzo (Premium)")
        st.plotly_chart(fig_storico, use_container_width=True)
        
        # Tabella Storico Completa con espansore
        with st.expander("📚 Vedi Tabella Completa Storico Database"):
            # Ordina dal più recente al più vecchio
            df_storico_vista = df_storico.sort_values(by="data_scansione", ascending=False).drop(columns=['id'])
            # Formattazione bella
            st.dataframe(
                df_storico_vista.style.format({
                    'prezzo_loro_eur': "€ {:.2f}", 
                    'prezzo_photosi_eur': "€ {:.2f}", 
                    'delta_eur': "€ {:.2f}"
                }),
                use_container_width=True, hide_index=True
            )
    else:
        st.info("Nessun dato storico trovato nel database. Esegui la prima scansione!")
except Exception as e:
    st.error(f"Impossibile caricare lo storico dal Database: {e}")
