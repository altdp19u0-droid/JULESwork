import os
import pandas as pd
import streamlit as st
from datetime import datetime
from fpdf import FPDF
from io import BytesIO, StringIO
import json
import tempfile
import unicodedata
import traceback

# --- Helpers ---
def pd_read_csv_safe(path):
    """Robust CSV reading for Windows with encoding fallbacks."""
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except:
        try:
            return pd.read_csv(path, encoding="latin-1")
        except:
            return pd.read_csv(path, encoding="utf-8", errors="replace")

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Fiscalité (app3)", layout="wide")
st.title("⚖️ Fiscalité Crypto France (Art. 150 VH bis)")

EXPORT_BASE_DIR = "sanctuarisation"
POSITIONS_FILE = "position_labels.json"

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

def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
                return json.load(f)
        except: return {}
    return {}

def resolve_raw_addr(addr_str):
    if "(" in str(addr_str) and ")" in str(addr_str):
        return str(addr_str).split("(")[-1].split(")")[0].strip().lower()
    return str(addr_str).strip().lower()

def apply_position_labels(df):
    """Remplace l'adresse Counterparty par 'Label (0x...)' si un mapping existe."""
    if df.empty: return df
    labels = load_position_labels()
    if not labels: return df

    def format_cp(cp_str):
        raw = resolve_raw_addr(cp_str)
        if raw in labels:
            return f"{labels[raw]} ({raw})"
        return cp_str

    df["Counterparty"] = df["Counterparty"].apply(format_cp)
    return df

def pdf_safe_str(val):
    """Sanitize string for PDF encoding by preserving visual nuances."""
    if val is None: return ""
    s = str(val)

    # Aggressive mapping of Cyrillic/Lisu/Other look-alikes to ASCII
    # This prevents latin-1 and charmap crashes in environments with restricted codecs.
    nuance_map = {
        "\ua4f4": "U", "\ua4e2": "S", "\ua4d3": "D", "\ua4c1": "G", "\ua4c3": "H",
        "\u0421": "C", "\u0405": "S", "\u0410": "A", "\u0412": "B", "\u0415": "E", "\u041d": "H",
        "\u041a": "K", "\u041c": "M", "\u041e": "O", "\u0420": "P", "\u0422": "T", "\u0425": "X",
        "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0443": "y", "\u0445": "x",
        "\u216d": "C", "\u2160": "I", "\u2164": "V", "\u2169": "X", "\u216c": "L", "\u216f": "M",
        "\u200a": " ", "\u2009": " ", "\u202f": " ", "\u2019": "'", "\u20ac": "EUR"
    }
    for k, v in nuance_map.items():
        s = s.replace(k, v)

    # NFKC Normalization handles standard compatibility characters
    s = unicodedata.normalize('NFKC', s)

    # Try to keep as much as possible for Unicode fonts, but fallback safely
    try:
        # If we use DejaVu, it handles most things, but we want to avoid charmap errors on Windows
        return s.encode('utf-8').decode('utf-8')
    except:
        return s.encode('latin-1', 'replace').decode('latin-1')

def load_data(year):
    paths = {
        'journal': get_file_path(year, 'qualified'),
        'fiat': get_file_path(year, 'fiat'),
        'positions': get_file_path(year, 'positions')
    }

    data = {}
    for key, path in paths.items():
        if os.path.exists(path) and os.path.getsize(path) > 0:
            df = pd_read_csv_safe(path)
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

            if key == 'journal':
                df = apply_position_labels(df)

            data[key] = df
        else:
            data[key] = pd.DataFrame()
    return data

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres Fiscaux")

    # Font Check
    if not os.path.exists("DejaVuSans.ttf"):
        st.warning("⚠️ Police Unicode 'DejaVuSans.ttf' absente. Les caractères spéciaux seront limités dans le PDF.")
    else:
        st.success("✅ Police Unicode détectée.")
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
        accounts = list(journal['Account'].dropna().unique())
        st.write(f"Comptes identifiés dans le journal : `{', '.join(accounts)}`")

        st.divider()
        st.subheader("📍 Positions de Fin d'Année")

        # 1. Chargement du référentiel Protocoles
        pos_labels = load_position_labels()
        protocol_addrs = set(pos_labels.keys())
        my_accounts = set(accounts)

        st.info("Ces positions servent à calculer la Valeur Globale du Portefeuille (VGP).")

        # 2. Calcul des soldes Locaux (Wallets)
        derived_local = journal.groupby(['Account', 'Asset']).agg({'Amount': 'sum'}).reset_index()
        derived_local = derived_local[derived_local['Amount'].abs() > 1e-8]

        # 3. Calcul des soldes Protocoles (Mapping Counterparty)
        # On cherche les flux vers des protocoles qui n'ont pas été retirés
        # Solde Protocole = Sum(Sent to Protocol) - Sum(Received from Protocol)
        protocol_rows = []
        for addr, label in pos_labels.items():
            # Flux ENVOYÉS au protocole (Amount négatif dans le journal car sort du wallet)
            # Mais pour le solde du protocole, c'est une entrée.
            # On simplifie : Solde = - (Somme des Amount du journal dont Counterparty est le protocole)
            mask_prot = journal["Counterparty"].fillna("").apply(resolve_raw_addr) == addr
            if mask_prot.any():
                df_prot = journal[mask_prot].groupby("Asset")["Amount"].sum().reset_index()
                for _, r in df_prot.iterrows():
                    if abs(r["Amount"]) > 1e-8:
                        protocol_rows.append({
                            "Account": label,
                            "Asset": r["Asset"],
                            "Amount": -r["Amount"] # Inversion car c'est une créance sur le protocole
                        })

        df_protocols = pd.DataFrame(protocol_rows)

        # UI Affichage
        st.write("**📱 Portefeuilles (Local) :**")
        for col in derived_local.columns:
            if derived_local[col].dtype == object:
                derived_local[col] = derived_local[col].fillna("").astype(str)
        st.data_editor(derived_local, use_container_width=True, disabled=True, key="local_pos_ed")

        if not df_protocols.empty:
            st.write("**🏦 Protocoles & Staking (Déporté) :**")
            for col in df_protocols.columns:
                if df_protocols[col].dtype == object:
                    df_protocols[col] = df_protocols[col].fillna("").astype(str)
            st.data_editor(df_protocols, use_container_width=True, disabled=True, key="proto_pos_ed")

        st.divider()
        st.write("**Positions déclarées manuellement (Off-chain, CEX, etc.) :**")
        pos_df = data['positions']
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
        def is_imposable_robust(val):
            s = str(val).upper().strip()
            return s in ["TRUE", "1", "1.0", "VRAI"]

        cessions = journal[
            (journal['Imposable'].apply(is_imposable_robust) |
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
                # Crucial: Le calcul doit être fait dans l'ordre chronologique (Ascendant).
                results = []
                temp_acq = total_acq_price

                # Tri chronologique obligatoire pour la fiscalité française
                cessions_sorted = edited_cessions.sort_values("Date", ascending=True)

                for _, row in cessions_sorted.iterrows():
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

        # PDF Export for Fiscality (Full Report)
        def generate_fiscal_pdf_full(year, accounts, local_pos, proto_pos, manual_pos, fiat_df, bilan_df, total_pv, impot):
            pdf = FPDF(orientation='L', unit='mm', format='A4')
            pdf.set_auto_page_break(auto=True, margin=15)

            # Unicode Font Registration
            font_path = "DejaVuSans.ttf"
            font_bold_path = "DejaVuSans-Bold.ttf"
            main_font = "helvetica" # Default fallback

            if os.path.exists(font_path) and os.path.exists(font_bold_path):
                try:
                    pdf.add_font("DejaVu", "", font_path)
                    pdf.add_font("DejaVu", "B", font_bold_path)
                    main_font = "DejaVu"
                except Exception as e:
                    # Silently fallback to helvetica to avoid charmap/pickle crashes on Windows
                    pass

            # --- Page 1: Comptes et Positions ---
            pdf.add_page()
            pdf.set_font(main_font, 'B', 18)
            pdf.cell(0, 15, f"RAPPORT FISCAL CRYPTO - {year}", ln=True, align='C')
            pdf.set_font(main_font, 'B', 14)
            pdf.cell(0, 10, "SECTION 1 : COMPTES & POSITIONS", ln=True)
            pdf.ln(5)

            pdf.set_font(main_font, 'B', 10)
            acc_str = ", ".join([pdf_safe_str(a) for a in accounts]) if accounts else "Aucun"
            pdf.multi_cell(0, 10, f"Comptes identifies : {acc_str}")
            pdf.ln(5)

            # Table Local Wallets
            pdf.set_font(main_font, 'B', 11)
            pdf.cell(0, 10, "Positions Portefeuilles (Local)", ln=True)
            pdf.set_fill_color(220, 220, 220)
            cols_p = ["Account", "Asset", "Quantite"]
            w_p = [140, 60, 60]
            for i, c in enumerate(cols_p): pdf.cell(w_p[i], 8, c, border=1, fill=True)
            pdf.ln()
            pdf.set_font(main_font, '', 10)
            for _, r in local_pos.iterrows():
                pdf.cell(w_p[0], 8, pdf_safe_str(r["Account"])[:60], border=1)
                pdf.cell(w_p[1], 8, pdf_safe_str(r["Asset"]), border=1)
                pdf.cell(w_p[2], 8, f"{r['Amount']:.6f}", border=1)
                pdf.ln()
            pdf.ln(10)

            # Table Protocols
            if not proto_pos.empty:
                pdf.set_font(main_font, 'B', 11)
                pdf.cell(0, 10, "Positions Protocoles (Staking / Vaults)", ln=True)
                for i, c in enumerate(cols_p): pdf.cell(w_p[i], 8, c, border=1, fill=True)
                pdf.ln()
                pdf.set_font(main_font, '', 10)
                for _, r in proto_pos.iterrows():
                    pdf.cell(w_p[0], 8, pdf_safe_str(r["Account"]), border=1)
                    pdf.cell(w_p[1], 8, pdf_safe_str(r["Asset"]), border=1)
                    pdf.cell(w_p[2], 8, f"{r['Amount']:.6f}", border=1)
                    pdf.ln()
                pdf.ln(10)

            # --- Page 2: Prix d'Acquisition ---
            pdf.add_page()
            pdf.set_font(main_font, 'B', 14)
            pdf.cell(0, 10, "SECTION 2 : HISTORIQUE DES ACHATS (FIAT)", ln=True)
            pdf.ln(5)

            pdf.set_font(main_font, 'B', 10)
            # Adjusting widths to avoid overlap: Type needs more space, and total must fit A4 Landscape (~277mm usable)
            cols_f = ["Date", "Compte", "Asset", "Type", "Montant EUR", "Quantite"]
            w_f = [25, 45, 20, 85, 40, 40] # Total: 255mm
            for i, c in enumerate(cols_f): pdf.cell(w_f[i], 8, c, border=1, fill=True)
            pdf.ln()
            pdf.set_font(main_font, '', 9)
            for _, r in fiat_df.iterrows():
                try: ds_f = pd.to_datetime(r["Date"]).strftime("%d/%m/%Y")
                except: ds_f = "N/A"
                pdf.cell(w_f[0], 8, ds_f, border=1)
                pdf.cell(w_f[1], 8, pdf_safe_str(r.get("Account", "Manual"))[:30], border=1)
                pdf.cell(w_f[2], 8, pdf_safe_str(r.get("Asset", "EUR")), border=1)
                pdf.cell(w_f[3], 8, pdf_safe_str(r.get("Type", "")), border=1)
                pdf.cell(w_f[4], 8, f"{r.get('Montant EUR', 0):.2f} EUR", border=1)
                pdf.cell(w_f[5], 8, f"{r.get('Quantité', 0):.6f}", border=1)
                pdf.ln()

            # --- Page 3: Cessions ---
            pdf.add_page()
            pdf.set_font(main_font, 'B', 14)
            pdf.cell(0, 10, "SECTION 3 : DETAIL DES CESSIONS (FORMULAIRE 2086)", ln=True)
            pdf.ln(5)

            pdf.set_font(main_font, 'B', 9)
            cols_c = ["Date", "Asset", "Prix Cession", "VGP", "Abattement Acq", "PV Brute"]
            w_c = [40, 30, 50, 50, 50, 50]
            for i, c in enumerate(cols_c): pdf.cell(w_c[i], 8, c, border=1, fill=True)
            pdf.ln()
            pdf.set_font(main_font, '', 9)
            for _, row in bilan_df.iterrows():
                try: ds_c = pd.to_datetime(row["Date"]).strftime("%d/%m/%Y")
                except: ds_c = str(row["Date"])

                pdf.cell(w_c[0], 8, ds_c, border=1)
                pdf.cell(w_c[1], 8, pdf_safe_str(row["Asset"]), border=1)
                pdf.cell(w_c[2], 8, f"{row['Prix Cession']:.2f} EUR", border=1)
                pdf.cell(w_c[3], 8, f"{row['VGP']:.2f} EUR", border=1)
                pdf.cell(w_c[4], 8, f"{row['Abattement Acq']:.2f} EUR", border=1)
                pdf.cell(w_c[5], 8, f"{row['Plus-Value Brute']:.2f} EUR", border=1)
                pdf.ln()

            # --- Page 4: Bilan Final ---
            pdf.add_page()
            pdf.set_font(main_font, 'B', 16)
            pdf.cell(0, 15, "BILAN FISCAL RECAPITULATIF", ln=True, align='C')
            pdf.ln(10)

            pdf.set_font(main_font, 'B', 14)
            pdf.cell(100, 12, "PLUS-VALUE BRUTE TOTALE :", border=0)
            pdf.cell(0, 12, f"{total_pv:,.2f} EUR", border=0, ln=True, align='R')

            pdf.cell(100, 12, "IMPOT ESTIME (PFU 30%) :", border=0)
            pdf.cell(0, 12, f"{impot:,.2f} EUR", border=0, ln=True, align='R')

            pdf.ln(20)
            # If DejaVu is used, we only have Regular and Bold.
            # Style 'I' would require DejaVuSans-Oblique.ttf
            footer_style = 'I' if main_font == "helvetica" else ""
            pdf.set_font(main_font, footer_style, 10)
            pdf.multi_cell(0, 8, "Ce document est un assistant au calcul fiscal base sur les donnees fournies. Il appartient a l'utilisateur de verifier l'exactitude des montants reportes dans la declaration officielle.")

            # Extraction des bytes (Directement en mémoire pour éviter les erreurs de fichier/encodage sur Windows)
            return bytes(pdf.output())

        # Explicit trigger for PDF generation to ensure data is present
        if st.button("📊 Préparer le Rapport PDF Complet", use_container_width=True):
            if df_bilan.empty:
                st.error("Le bilan est vide, impossible de générer le PDF.")
            else:
                # Clear stale cache
                if "fiscal_pdf_bytes" in st.session_state: del st.session_state.fiscal_pdf_bytes

                try:
                    final_bytes = generate_fiscal_pdf_full(
                        target_year, accounts, derived_local, df_protocols, pos_df, data['fiat'],
                        df_bilan, total_pv, impot
                    )
                    # Convert to bytes if it came as string/bytearray
                    if not isinstance(final_bytes, bytes):
                        final_bytes = bytes(final_bytes)

                    if len(final_bytes) > 1000:
                        st.session_state.fiscal_pdf_bytes = final_bytes
                        st.success(f"Rapport complet prêt ({len(final_bytes)} octets).")
                        st.rerun()
                    else:
                        st.error("Erreur : Le PDF généré est anormalement court.")
                except Exception as e:
                    st.error(f"Erreur de génération : {e}")
                    st.expander("Détails technique de l'erreur").code(traceback.format_exc())

        if "fiscal_pdf_bytes" in st.session_state:
            st.download_button(
                "📄 Télécharger le Rapport Fiscal PDF",
                data=st.session_state.fiscal_pdf_bytes,
                file_name=f"Rapport_Fiscal_{target_year}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
    else:
        st.info("Réalisez le calcul dans l'onglet 'Cessions' pour voir le bilan.")

st.sidebar.divider()
st.sidebar.caption("Fiscalité v1.0 - app3")
