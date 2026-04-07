import os
import pandas as pd
import streamlit as st
from datetime import datetime

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Explorateur (appcons)", layout="wide")
st.title("🔍 Explorateur de Données Sanctuarisées")

EXPORT_BASE_DIR = "sanctuarisation"

# --- Sidebar ---
with st.sidebar:
    st.header("📂 Sélection du Fichier")

    # 1. Année
    years = sorted([y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))], reverse=True)
    if not years:
        st.warning("Aucune année trouvée dans 'sanctuarisation/'.")
        st.stop()

    target_year = st.selectbox("Année", years)
    year_dir = os.path.join(EXPORT_BASE_DIR, target_year)

    # 2. Fichier
    files = sorted([f for f in os.listdir(year_dir) if f.endswith(".csv")])
    if not files:
        st.warning(f"Aucun CSV trouvé dans {year_dir}.")
        st.stop()

    target_file = st.selectbox("Fichier CSV", files)
    f_path = os.path.join(year_dir, target_file)

    st.divider()
    st.header("📊 Paramètres d'Affichage")

    # Load data for column selection
    try:
        df = pd.read_csv(f_path)
        cols = list(df.columns)

        sort_col = st.selectbox("Trier par", cols, index=0 if "Date" not in cols else cols.index("Date"))
        sort_order = st.radio("Ordre de tri", ["Décroissant (Desc)", "Croissant (Asc)"], index=0)

        st.divider()
        st.info(f"💾 **Stats** : {len(df)} lignes, {len(cols)} colonnes.")
        st.caption(f"Fichier : {target_file}")
    except Exception as e:
        st.error(f"Erreur de lecture : {e}")
        st.stop()

# --- Main App ---
st.subheader(f"📄 Contenu : {target_file}")

# Processing
if not df.empty:
    ascending = (sort_order == "Croissant (Asc)")
    df_display = df.sort_values(by=sort_col, ascending=ascending)

    # UI pour filtrage rapide (Optionnel mais utile)
    search = st.text_input("🔍 Recherche rapide dans tout le tableau", "")
    if search:
        # Recherche insensitive à la casse sur tous les champs
        df_display = df_display[df_display.apply(lambda row: row.astype(str).str.contains(search, case=False).any(), axis=1)]
        st.caption(f"Résultats filtrés : {len(df_display)} lignes.")

    # Affichage avec Data Editor (qui permet le copier-coller natif)
    st.data_editor(
        df_display,
        use_container_width=True,
        num_rows="fixed", # On ne modifie pas ici, on consulte
        disabled=True, # Lecture seule pour l'exploration
        key="cons_editor"
    )

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📥 Télécharger ce CSV",
            data=df_display.to_csv(index=False).encode('utf-8'),
            file_name=f"export_{target_file}",
            mime='text/csv'
        )
    with col2:
        st.info("💡 **Astuce** : Sélectionnez des cellules et utilisez `Ctrl+C` pour copier le contenu directement.")

else:
    st.info("Le fichier est vide.")

st.sidebar.divider()
st.sidebar.caption("Explorateur v1.0 - appcons")
