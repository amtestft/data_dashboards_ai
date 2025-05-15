import os
import streamlit as st
from gum import load_gum_data, render_gum_dashboard
from ttt import load_ttt_data, render_ttt_dashboard
from chiesi_budget import load_budget_data, render_budget_dashboard
from chiesi_sessions import load_sessions_data, render_sessions_dashboard
import google.generativeai as genai
from streamlit_chat import message
import html
import markdown

# Imposta la password corretta (puoi anche leggerla da st.secrets)
PASSWORD = st.secrets.get("app_password", "testftam")

def check_password():
    """Chiede la password e blocca l'accesso se errata."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🔒 Accesso riservato")
        password = st.text_input("Inserisci la password:", type="password")
        if st.button("Entra"):
            if password == PASSWORD:
                st.session_state.authenticated = True
                st.rerun()  # ✅ nuovo metodo corretto
            else:
                st.error("❌ Password errata")
        st.stop()

# Chiamalo all'inizio della tua app
check_password()

def get_available_gemini_models(api_key):
    try:
        genai.configure(api_key=api_key)
        models = genai.list_models()
        # Filtra solo quelli che supportano 'generateContent'
        valid_models = [
            m.name for m in models
            if "generateContent" in m.supported_generation_methods
        ]
        return sorted(valid_models)
    except Exception as e:
        return [f"Errore nel recupero modelli: {e}"]

def gemini_response(prompt: str, model_name: str) -> str:
    genai.configure(api_key=st.secrets["google"]["api_key"])
    try:
        model = genai.GenerativeModel(model_name=model_name)
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Errore durante la generazione dell'insight: {e}"

# Config & CSS
st.set_page_config(page_title="DATA Dashboards AI", layout="wide")
css_path = os.path.join(os.path.dirname(__file__), "style.css")
with open(css_path) as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

logo_path = "imgs/loghi png-04.png"
footer_logo_path = "imgs/loghi png_Tavola disegno 1.png"
primary_color = "#38D430"

# Sidebar: selezione del brand
brands = {
    #"GUM": {
    #    "loader": load_gum_data,
   #     "renderer": render_gum_dashboard,
    #    "logo": "imgs/gum_logo.png"
    #},
    #"TTT": {
   #     "loader": load_ttt_data,
   #     "renderer": render_ttt_dashboard,
   #     "logo": "imgs/ttt_logo.png"
   # },
    "Chiesi [Budget]": {
        "loader": load_budget_data,
        "renderer": render_budget_dashboard,
        "logo": "imgs/chiesi_logo.png"
    },
    "Chiesi [Sessions]": {
        "loader": load_sessions_data,
        "renderer": render_sessions_dashboard,
        "logo": "imgs/chiesi_logo.png"
    }
}

# place logo in alto a sinistra nel sidebar
import base64
from pathlib import Path
def img_to_bytes(img_path):
    img_bytes = Path(img_path).read_bytes()
    encoded = base64.b64encode(img_bytes).decode()
    return encoded
def img_to_html(img_path):
    img_html = "<img src='data:image/png;base64,{}' class='img-fluid'>".format(
      img_to_bytes(img_path)
    )
    return img_html

st.sidebar.markdown(
    f"{img_to_html(logo_path)}"
    "<h1 style='text-align:center; font-family:Gotham HTF, sans-serif; justify-content: center;'>"
    "<span style='color:#38D430;'>DATA</span> Dashboards AI"
    "</h1>",
    unsafe_allow_html=True
)


selected = st.sidebar.selectbox("CLIENTE", list(brands.keys()))
conf = brands[selected]


# Carica e renderizza
df = conf["loader"]()
conf["renderer"](df, primary_color=primary_color,
                    logo_url=conf["logo"])

# Funzione che crea il contesto testuale per Gemini
def build_contextual_prompt(user_input, df):
    # Riassunto delle colonne e dimensioni
    columns_info = f"Colonne disponibili: {df.columns.tolist()}"
    shape_info = f"Il dataset contiene {df.shape[0]} righe e {df.shape[1]} colonne."

    # Eventuale anteprima
    sample_info = f"Dataset:\n{df.to_markdown()}"

    summary_info = df.describe(include='all').transpose().reset_index().head(3).to_string(index=False)
    prompt = (
        f"Stai analizzando un dataset cliente.\n"
        f"{columns_info}. {shape_info}\n\n"
        f"{sample_info}\n\n"
        f"Statistiche generali:\n{summary_info}\n\n"
        f"Domanda dell'utente: {user_input}"
    )
    return prompt

import markdown

# Inizializzazione session state sicura
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "user_input_buffer" not in st.session_state:
    st.session_state.user_input_buffer = ""

if "send_message" not in st.session_state:
    st.session_state.send_message = False

with st.expander("💬 Chat con AI", expanded=True):

    # Modello
    model_list = get_available_gemini_models(st.secrets["google"]["api_key"])
    if model_list and not model_list[0].startswith("Errore"):
        selected_model = st.selectbox("Seleziona il modello Gemini", model_list, index=0)
    else:
        st.error("❌ Impossibile caricare i modelli Gemini. Controlla la tua API Key.")
        selected_model = None

    # Input normale gestito da session_state
    st.text_input("Fai una domanda sui dati...", key="user_input_buffer")

    # Bottone che setta un flag
    if st.button("Invia"):
        st.session_state.send_message = True

    # Solo se cliccato il bottone e c'è input e modello valido
    if st.session_state.send_message and st.session_state.user_input_buffer and selected_model:
        input_to_process = st.session_state.user_input_buffer

        st.session_state.chat_history.append({"role": "user", "content": input_to_process})

        with st.spinner("Gemini sta analizzando..."):
            contextual_prompt = build_contextual_prompt(input_to_process, df)
            bot_response = gemini_response(contextual_prompt, model_name=selected_model)

        st.session_state.chat_history.append({"role": "bot", "content": bot_response})

        # Resetta il buffer in modo sicuro nel flusso corretto al prossimo rerun
        st.session_state.user_input_buffer = ""
        st.session_state.send_message = False

    # Visualizzazione chat
    st.markdown("""
        <style>
            .chat-markdown {
                height: 400px;
                overflow-y: auto;
                border: 1px solid #ccc;
                padding: 10px;
                background-color: #f9f9f9;
                border-radius: 8px;
                margin-top: 20px;
            }
        </style>
    """, unsafe_allow_html=True)

    chat_md = ""
    if len(st.session_state.chat_history) == 0:
        chat_md += "**La chat è vuota. Fai una domanda per iniziare.**\n"
    else:
        for chat in st.session_state.chat_history:
            if chat["role"] == "user":
                chat_md += f"**Tu:**\n\n{chat['content']}\n\n"
            else:
                chat_md += f"**Gemini:**\n\n{chat['content']}\n\n"

    chat_html_converted = markdown.markdown(chat_md)
    st.markdown(f'<div class="chat-markdown">{chat_html_converted}</div>', unsafe_allow_html=True)


