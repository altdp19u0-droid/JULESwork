import os
import pandas as pd
import streamlit as st
from datetime import datetime

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Fiscalité (app3)", layout="wide")
st.title("⚖️ Fiscalité Crypto France (Art. 150 VH bis)")

EXPORT_BASE_DIR = "sanctuarisation"

# --- Helpers ---
def get_file_path(year, category):
    # category: 'qualified', 'fiat', 'positions'
    if category == 'qualified':
        return os.path.join(EXPORT_BASE_DIR, str(year), f"qualified_journal_{year}.csv")
    if category == 'fiat':
        return os.path.join(EXPORT_BASE_DIR, str(year), f"manual_fiat_{year}.csv")
    if category == 'positions':
        return os.path.join(EXPORT_BASE_DIR, str(year), f"manual_positions_{year}.csv")
    return None

def load_data(year):
    paths = {
        'journal': get_file_path(year, 'qualified'),
        'fiat': get_file_path(year, 'fiat'),
        'positions': get_file_path(year, 'positions')
    }

    data = {}
    for key, path in paths.items():
        if os.path.exists(path) and os.path.getsize(path) > 0:
            df = pd.read_csv(path)
            # Standardisation Date
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], utc=True, errors='coerce')

            # Type Safety: Force numeric types to avoid pyarrow string errors
            num_cols = ["Amount", "Value ($)", "VGP (EUR)", "Prix de Cession (EUR)", "Montant EUR", "Quantité"]
            for col in num_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

            # FILTRAGE ANTI-SPAM GLOBAL (uniquement pour le journal qualifié)
            if key == 'journal' and 'Status' in df.columns:
                df = df[df['Status'] != 'Spam']

            data[key] = df
        else:
            data[key] = pd.DataFrame()
    return data

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres Fiscaux")
    target_year = st.number_input("Année fiscale", min_value=2015, max_value=2030, value=datetime.now().year)

    st.divider()
    flat_tax_rate = st.slider("Taux d'imposition (PFU)", 0.0, 1.0, 0.30, 0.01)
    abattement = st.number_input("Abattement annuel (EUR)", value=305.0)

    st.divider()
    if st.button("🔄 Recalculer tout"):
        st.cache_data.clear()
        st.rerun()

data = load_data(target_year)

# --- Logic: Fiscal calculations ---
def calculate_acquisition_price(year):
    # Somme des flux fiat entrants (Achat) depuis le début (théoriquement cumulé)
    # Pour simplifier ici, on regarde l'année en cours + une saisie manuelle de l'historique
    fiat_df = data['fiat']
    if fiat_df.empty: return 0.0

    # On filtre sur les types "Achat"
    purchases = fiat_df[fiat_df['Type'].str.contains("Achat", na=False)]
    return purchases['Montant EUR'].sum()

# --- Tabs ---
tab_accounts, tab_acq, tab_cessions, tab_bilan = st.tabs([
    "📂 Comptes & Positions",
    "💰 Prix d'Acquisition",
    "📈 Cessions (2086)",
    "📋 Bilan Final"
])

with tab_accounts:
    st.subheader("🏦 Liste des Comptes Propriétaires Détectés")
    journal = data['journal']
    if not journal.empty:
        accounts = journal['Account'].dropna().unique()
        st.write(f"Comptes identifiés dans le journal : `{', '.join(accounts)}`")

        st.divider()
        st.subheader("📍 Positions de Fin d'Année")
        # On peut soit dériver du journal, soit utiliser manual_positions
        pos_df = data['positions']

        st.info("Ces positions servent à calculer la Valeur Globale du Portefeuille (VGP).")

        # Merge manual positions with derived ones
        derived_pos = journal.groupby(['Account', 'Asset']).agg({'Amount': 'sum'}).reset_index()
        derived_pos = derived_pos[derived_pos['Amount'].abs() > 1e-8]

        st.write("**Positions calculées depuis les flux :**")
        # Force string casting for editor
        for col in derived_pos.columns:
            if derived_pos[col].dtype == object:
                derived_pos[col] = derived_pos[col].fillna("").astype(str)

        st.data_editor(derived_pos, use_container_width=True, disabled=True, key="derived_pos_ed")

        st.divider()
        st.write("**Positions déclarées manuellement (Off-chain, CEX, etc.) :**")
        if not pos_df.empty:
            for col in pos_df.columns:
                if pos_df[col].dtype == object:
                    pos_df[col] = pos_df[col].fillna("").astype(str)
            st.data_editor(pos_df, use_container_width=True, key="manual_pos_ed")
        else:
            st.info("Aucune position manuelle saisie dans l'App 0.")

with tab_acq:
    st.subheader("💵 Suivi du Prix d'Acquisition Global")
    st.write("Le prix d'acquisition est le total des montants en Euros investis pour acquérir des actifs numériques.")

    current_acq = calculate_acquisition_price(target_year)

    col_acq1, col_acq2 = st.columns(2)
    with col_acq1:
        hist_acq = st.number_input("Prix d'acquisition historique (années précédentes)", value=0.0, step=100.0)
        total_acq_price = current_acq + hist_acq
        st.metric("Prix d'acquisition Total (A)", f"{total_acq_price:,.2f} €")

    with col_acq2:
        st.info("Cette valeur 'A' est utilisée dans la formule de calcul de la plus-value brute.")

with tab_cessions:
    st.subheader("📝 Calcul des Cessions Imposables (Formulaire 2086)")
    journal = data['journal']

    if journal.empty:
        st.warning("Le journal qualifié est vide. Terminez l'étape 2 d'abord.")
    else:
        # On cherche les lignes marquées comme Imposable ou étant des retraits Fiat (Vente)
        # Mais on exclut formellement les lignes EUR (Fiat pur)
        def is_imposable(val):
            s = str(val).upper()
            return s == "TRUE" or s == "1" or s == "1.0"

        cessions = journal[
            (journal['Imposable'].apply(is_imposable) |
             journal['Category'].fillna("").str.contains("Vente", case=False)) &
            (journal['Asset'] != 'EUR')
        ].copy()

        if cessions.empty:
            st.info("Aucune cession imposable détectée dans le journal.")
        else:
            st.write("Pour chaque cession, saisissez la **Valeur Globale du Portefeuille (VGP)** à la date de l'opération.")

            # On ajoute des colonnes pour le calcul fiscal
            cessions['Prix de Cession (EUR)'] = cessions['Value ($)'] * 0.92 # Conversion simplifiée ou saisie

            # Récupération automatique de la VGP calculée dans app2VGP si elle existe
            if 'VGP (EUR)' not in cessions.columns:
                cessions['VGP (EUR)'] = 0.0
            else:
                cessions['VGP (EUR)'] = cessions['VGP (EUR)'].fillna(0.0)

            # Type safety
            for col in ["Account", "Counterparty", "Asset", "Tx Hash", "Category", "Status"]:
                if col in cessions.columns:
                    cessions[col] = cessions[col].fillna("").astype(str)

            edited_cessions = st.data_editor(
                cessions,
                column_config={
                    "VGP (EUR)": st.column_config.NumberColumn("VGP (EUR)", format="%.2f", required=True),
                    "Prix de Cession (EUR)": st.column_config.NumberColumn("Prix Cession (EUR)", format="%.2f"),
                    "Date": st.column_config.DatetimeColumn(disabled=True),
                    "Amount": st.column_config.NumberColumn(disabled=True),
                },
                use_container_width=True,
                key="cessions_ed"
            )

            if st.button("🧮 Calculer les Plus-Values"):
                # Formule: PV = Prix Cession - [Total Acq * (Prix Cession / VGP)]
                # Note: Le Total Acq doit théoriquement être mis à jour après chaque cession.
                # Ici on implémente la version simplifiée (une cession à la fois ou cumulée).
                results = []
                temp_acq = total_acq_price

                for _, row in edited_cessions.iterrows():
                    pc = row['Prix de Cession (EUR)']
                    vgp = row['VGP (EUR)']

                    if vgp > 0:
                        fraction_acq = temp_acq * (pc / vgp)
                        pv = pc - fraction_acq
                        results.append({
                            "Date": row['Date'],
                            "Asset": row['Asset'],
                            "Prix Cession": pc,
                            "VGP": vgp,
                            "Abattement Acq": fraction_acq,
                            "Plus-Value Brute": pv
                        })
                        # En fiscalité réelle, on soustrait fraction_acq du temp_acq pour la cession suivante
                        temp_acq -= fraction_acq
                    else:
                        st.error(f"VGP manquante pour la cession du {row['Date']}")

                if results:
                    st.session_state.bilan_fiscale = pd.DataFrame(results)
                    st.success("Calcul terminé. Voir l'onglet Bilan.")
                else:
                    st.warning("Aucune plus-value n'a pu être calculée. Vérifiez les valeurs VGP.")

with tab_bilan:
    st.subheader("📊 Bilan Annuel & Impôt Estimé")

    if "bilan_fiscale" in st.session_state and not st.session_state.bilan_fiscale.empty:
        df_bilan = st.session_state.bilan_fiscale
        st.table(df_bilan)

        total_pv = df_bilan['Plus-Value Brute'].sum()
        total_cessions = df_bilan['Prix Cession'].sum()

        col_b1, col_b2, col_b3 = st.columns(3)
        col_b1.metric("Plus-Value Totale Brute", f"{total_pv:,.2f} €")

        # Logique fiscale : exonération si total des prix de cession <= abattement (305€)
        if total_cessions <= abattement:
            pv_nette = 0.0
            st.warning(f"💡 Exonération appliquée : Le total des cessions ({total_cessions:.2f}€) est inférieur au seuil de {abattement}€.")
        else:
            pv_nette = total_pv

        col_b2.metric("Plus-Value Nette Imposable", f"{pv_nette:,.2f} €")

        impot = pv_nette * flat_tax_rate if pv_nette > 0 else 0.0
        col_b3.metric(f"Impôt Estimé ({int(flat_tax_rate*100)}%)", f"{impot:,.2f} €", delta_color="inverse")

        st.divider()
        st.write("📝 **Montant à reporter dans la case 3AN (ou 3BN si moins-value) :**")
        st.code(f"{round(total_pv)}")

        st.info("💡 N'oubliez pas de joindre l'annexe 2086 à votre déclaration de revenus.")
    else:
        st.info("Réalisez le calcul dans l'onglet 'Cessions' pour voir le bilan.")

st.sidebar.divider()
st.sidebar.caption("Fiscalité v1.0 - app3")
