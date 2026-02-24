import streamlit as st
import pandas as pd
import asyncio
import os
import sys
import json
import subprocess
import plotly.express as px
import plotly.graph_objects as go
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
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        st.error(f"❌ Errore durante il download del browser: {e}")

install_browser()

# --- 3. GESTIONE CREDENZIALI (SECRETS) ---
api_key = st.secrets.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
supa_url = st.secrets.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
supa_key = st.secrets.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")

with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/1/1a/PhotoS%C3%AC_Logo.svg/512px-PhotoS%C3%AC_Logo.svg.png", width=150)
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
    st.warning("⚠️ Inserisci tutte le chiavi (OpenAI e Supabase) nei Secrets di Streamlit per continuare.")
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

# --- FUNZIONE PER CARICARE I TARGET DAL DATABASE ---
def load_targets_from_db():
    try:
        response = supabase.table("target_competitor").select("*").execute()
        if response.data:
            return [{"paese": d["paese"], "competitor": d["competitor"], "url": d["url"]} for d in response.data]
    except Exception as e:
        pass
    
    # Se il DB è vuoto o c'è un errore, restituisce quelli di default
    return [
        {"paese": "GB", "competitor": "Photobox", "url": "https://www.photobox.co.uk/photo-books"},
        {"paese": "IT", "competitor": "Cewe IT", "url": "https://www.cewe.it/fotolibro-cewe.html"},
        {"paese": "IT", "competitor": "Saal Digital", "url": "https://www.saal-digital.it/fotolibro/"},
        {"paese": "IT", "competitor": "Cheerz", "url": "https://www.cheerz.com/it/categories/books"},
        {"paese": "IT", "competitor": "Popsa", "url": "https://popsa.com/it-it/prodotti/fotolibri"}
    ]

# --- 5. INTERFACCIA E TARGET ---
st.title("🚀 PhotoSì Intelligence: Monitor Premium")
st.markdown("Piattaforma di tracciamento prezzi competitor per fotolibri Premium (Rigidi/Layflat).")

if 'targets' not in st.session_state:
    st.session_state.targets = load_targets_from_db()

with st.expander("🌍 Gestione Target Competitor (Salvati su Database)", expanded=False):
    st.info("Aggiungi, modifica o cancella le righe qui sotto. Poi clicca su 'Salva Modifiche' per aggiornare il database per sempre.")
    
    # Tabella modificabile
    df_targets_edit = st.data_editor(pd.DataFrame(st.session_state.targets), num_rows="dynamic", use_container_width=True)
    
    # Bottone di salvataggio
    if st.button("💾 Salva Modifiche nel Database", type="secondary"):
        # Convertiamo il dataframe modificato in lista di dizionari ignorando righe vuote
        new_targets_list = df_targets_edit.to_dict(orient='records')
        clean_targets = [{"paese": r["paese"], "competitor": r["competitor"], "url": r["url"]} 
                         for r in new_targets_list if str(r.get("competitor")).strip() != "nan" and str(r.get("competitor")).strip() != ""]
        
        try:
            # 1. Svuotiamo la tabella vecchia nel DB
            supabase.table("target_competitor").delete().neq("id", 0).execute()
            # 2. Inseriamo i nuovi target
            if clean_targets:
                supabase.table("target_competitor").insert(clean_targets).execute()
            
            st.session_state.targets = clean_targets
            st.success("✅ Lista competitor aggiornata in modo permanente!")
        except Exception as e:
            st.error(f"Errore durante il salvataggio dei target: {e}")
            
    # Usiamo il dataframe modificato per la scansione corrente
    df_targets = pd.DataFrame(st.session_state.targets)

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

# --- VARIABILI DI STATO ---
if "scraped_data" not in st.session_state:
    st.session_state.scraped_data = []

# --- 7. LOGICA DI SCANSIONE E SALVATAGGIO ---
if st.button("🔥 ESEGUI NUOVA SCANSIONE", type="primary"):
    client = OpenAI(api_key=api_key)
    scraped_data_temp = []
    db_records = []
    
    my_bar = st.progress(0, text="Avvio scansione...")
    
    for i, row in df_targets.iterrows():
        with st.status(f"Analizzando {row['competitor']}..."):
            testo_grezzo = asyncio.run(fetch_site_text(row['url']))
            
            if testo_grezzo and "Errore caricamento" not in testo_grezzo:
                prompt = f"""
                Sei un pricing analyst inflessibile. Trova i prezzi dei fotolibri PREMIUM (carta fotografica).
                REGOLE TASSATIVE:
                1. IGNORA categoricamente i fotolibri con copertina morbida (softcover) e i mini fotolibri.
                2. ESTRAI SOLO i fotolibri con COPERTINA RIGIDA (hardcover) o layflat professionali.
                3. Abbinali ESATTAMENTE a: {list(CATALOGO_PHOTOSI.keys())}.
                RESTITUISCI SOLO JSON (nessun testo extra): 
                {{"data": [{{"match": "...", "nome_loro": "...", "prezzo": 0.0, "valuta": "..."}}]}}
                """
                try:
                    res = client.chat.completions.create(
                        model="gpt-4o",
                        temperature=0.0,
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
                            
                            scraped_data_temp.append({
                                "Paese": row['paese'], "Competitor": row['competitor'], 
                                "Categoria": d['match'], "Prodotto Loro": d.get('nome_loro', 'N/D'),
                                "Prezzo Loro (€)": p_eur, "PhotoSì (€)": p_ref, 
                                "Delta (€)": delta, "Status": status_text
                            })
                            
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
        
        my_bar.progress((i + 1) / len(df_targets), text=f"Scansione {i+1}/{len(df_targets)} completata...")
    
    my_bar.empty()
    st.session_state.scraped_data = scraped_data_temp
    
    if db_records:
        try:
            supabase.table("storico_prezzi").insert(db_records).execute()
            st.success("💾 Dati validati e salvati con successo nel Database!")
        except Exception as e:
            st.error(f"Errore salvataggio DB: {e}")

st.divider()

# --- 8. DASHBOARD A SCHEDE (TABS) ---
tab1, tab2, tab3 = st.tabs(["📊 Ultima Scansione", "📈 Analisi di Mercato", "🕰️ Storico & Trend"])

with tab1:
    if st.session_state.scraped_data:
        df_res = pd.DataFrame(st.session_state.scraped_data)
        
        col1, col2, col3, col4 = st.columns(4)
        minaccia = df_res.loc[df_res['Delta (€)'].idxmin()]
        competitor_piu_caro = df_res.loc[df_res['Delta (€)'].idxmax()]
        
        with col1: st.metric("Prodotti Analizzati", len(df_res))
        with col2: st.metric("Prezzo Medio Scansionato", f"€ {df_res['Prezzo Loro (€)'].mean():.2f}")
        with col3: st.metric(f"🔥 Peggior Minaccia ({minaccia['Competitor']})", f"€ {minaccia['Prezzo Loro (€)']:.2f}", f"{minaccia['Delta (€)']:.2f} €", delta_color="inverse")
        with col4: st.metric(f"💎 Competitor Premium ({competitor_piu_caro['Competitor']})", f"€ {competitor_piu_caro['Prezzo Loro (€)']:.2f}", f"+{competitor_piu_caro['Delta (€)']:.2f} €", delta_color="normal")
        
        st.write("### 📋 Dettaglio Completo")
        def color_status(val):
            return 'background-color: #e6ffed; color: #117a35' if 'Conveniente' in val else 'background-color: #ffeef0; color: #b3001b'
        
        st.dataframe(df_res.style.map(color_status, subset=['Status']).format({'Prezzo Loro (€)': "€ {:.2f}", 'PhotoSì (€)': "€ {:.2f}", 'Delta (€)': "€ {:.2f}"}), use_container_width=True, hide_index=True)
    else:
        st.info("Esegui una scansione per popolare questa scheda.")

with tab2:
    if st.session_state.scraped_data:
        df_res = pd.DataFrame(st.session_state.scraped_data)
        
        st.write("### 🥊 Confronto Diretto dei Prezzi (PhotoSì vs Competitor)")
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(x=df_res['Competitor'] + " - " + df_res['Categoria'], y=df_res['PhotoSì (€)'], name='PhotoSì', marker_color='#E50914'))
        fig_bar.add_trace(go.Bar(x=df_res['Competitor'] + " - " + df_res['Categoria'], y=df_res['Prezzo Loro (€)'], name='Competitor', marker_color='#1f77b4'))
        fig_bar.update_layout(barmode='group', xaxis_tickangle=-45, yaxis_title="Prezzo in Euro (€)", margin=dict(b=100))
        st.plotly_chart(fig_bar, use_container_width=True)
        
        st.write("### 🎯 Posizionamento sul Mercato (Scatter Plot)")
        fig_scatter = px.scatter(
            df_res, x="Competitor", y="Prezzo Loro (€)", color="Categoria", size="PhotoSì (€)",
            hover_data=["Prodotto Loro", "Delta (€)"], title="Dove si concentrano i prezzi per ogni categoria?"
        )
        for cat, price in CATALOGO_PHOTOSI.items():
            fig_scatter.add_hline(y=price, line_dash="dot", opacity=0.3, annotation_text=f"Tuo {cat}")
        fig_scatter.update_traces(marker=dict(line=dict(width=1, color='DarkSlateGrey')))
        st.plotly_chart(fig_scatter, use_container_width=True)

    else:
        st.info("Esegui una scansione per visualizzare le analisi di mercato.")

with tab3:
    try:
        response = supabase.table("storico_prezzi").select("*").order("data_scansione", desc=False).execute()
        storico_dati = response.data
        
        if storico_dati:
            df_storico = pd.DataFrame(storico_dati)
            df_storico['data_scansione'] = pd.to_datetime(df_storico['data_scansione']).dt.strftime('%d/%m/%Y %H:%M')
            
            st.write("### 📈 Evoluzione Prezzi nel Tempo")
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                cat_scelta = st.selectbox("Seleziona Formato per il Trend", df_storico['categoria'].unique())
            
            df_grafico = df_storico[df_storico['categoria'] == cat_scelta]
            
            fig_storico = px.line(
                df_grafico, x="data_scansione", y="prezzo_loro_eur", color="competitor", markers=True,
                title=f"Trend Prezzi: {cat_scelta}", labels={"prezzo_loro_eur": "Prezzo (€)", "data_scansione": "Data", "competitor": "Competitor"}
            )
            fig_storico.add_hline(y=CATALOGO_PHOTOSI[cat_scelta], line_dash="dash", line_color="red", annotation_text="Listino PhotoSì")
            st.plotly_chart(fig_storico, use_container_width=True)
            
            with st.expander("📚 Consulta l'intero Database", expanded=False):
                df_storico_vista = df_storico.sort_values(by="data_scansione", ascending=False).drop(columns=['id'])
                st.dataframe(df_storico_vista.style.format({'prezzo_loro_eur': "€ {:.2f}", 'prezzo_photosi_eur': "€ {:.2f}", 'delta_eur': "€ {:.2f}"}), use_container_width=True, hide_index=True)
                
                st.download_button(
                    label="📥 Esporta Intero Storico (CSV)",
                    data=df_storico_vista.to_csv(index=False, sep=';', decimal=','),
                    file_name="storico_prezzi_database.csv", mime="text/csv"
                )
        else:
            st.info("Nessun dato storico trovato nel database. I grafici compariranno dopo le prime scansioni.")
    except Exception as e:
        st.error(f"Impossibile caricare lo storico dal Database: {e}")
