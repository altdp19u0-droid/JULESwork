import os
import time
import pandas as pd
import streamlit as st
from datetime import datetime
import shared_logic as sl

# --- Configuration ---
if "is_hub" not in st.session_state:
    st.set_page_config(page_title="Jules Crypto - Intérêts & Bonus", layout="wide")

st.title("🎁 Gestion des Intérêts & Bonus")

EXPORT_BASE_DIR = "sanctuarisation"

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")

    # Access Unified Processing Year from Hub
    target_year = st.session_state.get("_hub_target_year")
    if target_year is None:
        g_conf = sl.load_global_config()
        target_year = g_conf.get("processing_year") or datetime.now().year
        st.session_state["_hub_target_year"] = target_year

    st.write(f"📅 Année active : **{target_year}**")

    st.divider()
    with st.expander("💎 Registre des Tokens Bonus", expanded=True):
        bonus_tokens = sl.load_bonus_tokens()
        for bt in sorted(list(bonus_tokens)):
            c1, c2 = st.columns([4, 1])
            c1.text(bt)
            if c2.button("🗑️", key=f"del_bt_{bt}"):
                bonus_tokens.remove(bt)
                sl.save_bonus_tokens(bonus_tokens)
                st.rerun()

        new_bt = st.text_input("Ajouter Token Bonus (ex: STRK, OP)", key="new_bt_input").upper().strip()
        if st.button("➕ Ajouter au Registre", key="btn_add_bt"):
            if new_bt:
                bonus_tokens.add(new_bt)
                sl.save_bonus_tokens(bonus_tokens)
                st.rerun()

    st.divider()
    if st.button("🔄 Rafraîchir les données", width='stretch'):
        st.cache_data.clear()
        st.rerun()

    sl.show_status()

# --- Core Logic ---

def load_reward_candidates(year):
    """Loads all potential reward rows (inflows not marked as Fiat Purchase)."""
    # Use CLEAN history to avoid spams
    df = sl.load_clean_history(year)
    if df.empty: return pd.DataFrame()

    # Ensure standard columns exist
    if "Category" not in df.columns: df["Category"] = ""

    # Selection: Inflows (Amount > 0) AND Target Year only
    # Note: df comes from load_clean_history which already filters for Target Year
    mask_inflow = (df["Amount"] > 0)
    # Exclude known Fiat purchases (already in Capital A from Step 0)
    # And exclude Transferts Internes (wealth preservation)
    mask_not_acq = (~df["Category"].str.contains("Achat|Transfert Interne|Position", case=False, na=False))

    df_rew = df[mask_inflow & mask_not_acq].copy()

    # Auto-classification based on Bonus Tokens registry
    bonus_set = sl.load_bonus_tokens()

    def auto_classify(r):
        # High Priority: explicit 'Capital' qualification (user contribution)
        current_cat = str(r.get("Category", "")).strip()
        if current_cat == "Capital": return "Capital"

        # Consult Registry for automatic detection (overrides other labels)
        asset = str(r["Asset"]).upper().strip()
        if asset in bonus_set: return "Bonus"

        # If already categorized as Interest or Bonus but asset not in registry,
        # we respect the existing category if it was manual,
        # or default to Interest for non-bonus assets.
        if current_cat in ["Intérêt", "Bonus"]: return current_cat

        return "Intérêt"

    if not df_rew.empty:
        df_rew["Category"] = df_rew.apply(auto_classify, axis=1)

        # Calculate EUR value at reception
        cache = sl.load_price_cache()
        def get_val_eur(r):
            v_usd = float(r.get("Valeur $", 0.0))
            if v_usd > 0:
                return v_usd * sl.get_fiat_rate("USD", r["Date"])
            return abs(float(r["Amount"])) * sl.get_price_eur(r["Asset"], r["Date"], cache)

        df_rew["Valeur (EUR)"] = df_rew.apply(get_val_eur, axis=1)

    return df_rew

# --- UI Tabs ---
t_editor, t_stats = st.tabs(["📝 Qualification des Récompenses", "📊 Totaux & Exports"])

df_rewards = load_reward_candidates(target_year)

# Visibility filter: exclude dust rewards (likely spams) from the qualifying view
# User instruction: Make it visible but filtered if needed.
DUST_THRESHOLD_EUR = 0.0001 # Extremely low to show almost everything

with t_editor:
    st.subheader(f"🔍 Flux entrants à qualifier ({target_year})")
    st.info("Les revenus qualifiés comme 'Intérêt' ou 'Bonus' s'ajouteront automatiquement au Capital Global Investi (A) à leur valeur du jour.")

    if not df_rewards.empty:
        # User selection for dust visibility
        show_dust = st.checkbox("Afficher la poussière (< 0.01 €)", value=False)

        if show_dust:
            df_view = df_rewards.copy()
        else:
            df_view = df_rewards[df_rewards["Valeur (EUR)"] >= 0.01].copy()
            num_dust = len(df_rewards) - len(df_view)
            if num_dust > 0:
                st.caption(f"💡 {num_dust} transactions de faible valeur sont masquées. Cochez la case ci-dessus pour les voir.")

    if df_rewards.empty:
        st.warning("Aucun flux entrant détecté pour cette année.")
    else:
        # Data Editor for classification
        edited_df = st.data_editor(
            df_view.sort_values("Date", ascending=False),
            column_config={
                "Category": st.column_config.SelectboxColumn(
                    "Nature Fiscale",
                    options=["Intérêt", "Bonus", "Capital", "Transfert Interne", "Spam"],
                    help="Bonus = Airdrops/Gifts, Intérêt = Staking/Lending, Capital = Apport propre."
                ),
                "Date": st.column_config.DatetimeColumn(disabled=True),
                "Asset": st.column_config.TextColumn(disabled=True),
                "Amount": st.column_config.NumberColumn("Quantité", format="%.8f", disabled=True),
                "Valeur (EUR)": st.column_config.NumberColumn("Valeur € (Réception)", format="%.2f €"),
                "Account": st.column_config.TextColumn("Compte", disabled=True),
                "Tx_Hash": st.column_config.TextColumn("Hash", disabled=True),
            },
            disabled=["Date", "Chain", "Tx_Hash", "Account", "Asset", "Amount", "Source_Way", "Audit_Status", "Fee_Audit_Alert"],
            width='stretch', hide_index=True, key="rewards_editor"
        )

        if st.button("💾 Sauvegarder les Qualifications & Valeurs", type="primary", width='stretch'):
            # Update the main Qualified Full journal
            j_full_path = sl.get_file_path(target_year, 'qualified_full')
            df_master = sl.pd_read_csv_safe(j_full_path)

            if not df_master.empty:
                # Use composite key for matching
                for _, r in edited_df.iterrows():
                    mask = (df_master["Tx_Hash"] == r["Tx_Hash"]) & (df_master["Asset"] == r["Asset"]) & (df_master["Account"] == r["Account"])
                    if mask.any():
                        df_master.loc[mask, "Category"] = r["Category"]
                        # Update Valeur $ based on Valeur EUR if changed
                        # (Simplified: we just store the category, app3/sl use get_total_acquisition_value which handles valuation)

                df_master.to_csv(j_full_path, index=False, encoding="utf-8-sig")

                # Sync CLEAN
                clean_path = sl.get_file_path(target_year, 'qualified_clean')
                sl.apply_spam_filter(df_master, drop=True).to_csv(clean_path, index=False, encoding="utf-8-sig")

                st.success("Qualifications enregistrées.")
                st.rerun()

with t_stats:
    st.subheader("📈 Récapitulatif Annuel des Revenus")

    # Diagnostic Block
    if not df_rewards.empty:
        with st.expander("🔍 Diagnostic des données récoltées", expanded=False):
            st.write(f"- Total flux entrants détectés (Step 2 CLEAN) : **{len(df_rewards)}**")
            # Count per category
            cat_counts = df_rewards["Category"].value_counts().to_dict()
            st.write("- Répartition par catégorie actuelle :")
            st.json(cat_counts)
            st.info("💡 Seules les catégories 'Intérêt' et 'Bonus' sont comptabilisées dans les totaux ci-dessous.")

    if not df_rewards.empty:
        # Filter only for Interest and Bonus for stats (case-insensitive for legacy data)
        # We also filter out dust from stats to keep them clean
        mask_final = df_rewards["Category"].str.contains("Intérêt|Interest|Bonus|Airdrop|Revenu|Staking", case=False, na=False)
        df_stats = df_rewards[mask_final & (df_rewards["Valeur (EUR)"] >= DUST_THRESHOLD_EUR)].copy()

        # Map categories to standard display
        def map_cat_stats(c):
            cl = str(c).lower()
            if "bonus" in cl or "airdrop" in cl: return "Bonus"
            return "Intérêt"

        if not df_stats.empty:
            df_stats["Category"] = df_stats["Category"].apply(map_cat_stats)
            c1, c2 = st.columns(2)
            tot_int = df_stats[df_stats["Category"]=="Intérêt"]["Valeur (EUR)"].sum()
            tot_bon = df_stats[df_stats["Category"]=="Bonus"]["Valeur (EUR)"].sum()

            c1.metric("Total Intérêts (Année)", f"{tot_int:,.2f} €")
            c2.metric("Total Bonus (Année)", f"{tot_bon:,.2f} €")

            st.divider()
            st.write("**Détail quotidien des revenus :**")

            df_stats["Jour"] = df_stats["Date"].dt.date
            daily_stats = df_stats.groupby(["Jour", "Category"]).agg({
                "Valeur (EUR)": "sum",
                "Asset": lambda x: ", ".join(x.unique())
            }).reset_index()

            st.dataframe(daily_stats.sort_values("Jour", ascending=False), width='stretch', hide_index=True)

            csv = daily_stats.to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                "📥 Exporter le journal des revenus (CSV)",
                data=csv,
                file_name=f"revenus_crypto_{target_year}.csv",
                mime="text/csv",
                width='stretch'
            )

            # Historical Cumulative Calculation
            st.divider()
            st.subheader("⏳ Cumul Historique (Report)")
            with st.spinner("Calcul du cumul historique..."):
                all_acq_details = sl.get_total_acquisition_value(target_year, return_details=True)[1]
                if not all_acq_details.empty:
                    # Robustness: ensure Category column exists to avoid KeyError
                    if "Category" not in all_acq_details.columns: all_acq_details["Category"] = ""
                    # Categories might vary based on source file
                    hist_int = all_acq_details[all_acq_details["Category"].str.contains("Intérêt", case=False, na=False)]["Montant EUR"].sum()
                    hist_bon = all_acq_details[all_acq_details["Category"].str.contains("Bonus", case=False, na=False)]["Montant EUR"].sum()

                    ch1, ch2 = st.columns(2)
                    ch1.metric("Cumul Intérêts Historique", f"{hist_int:,.2f} €", help="Total des intérêts perçus depuis le début de l'activité (basé sur toutes les années qualifiées).")
                    ch2.metric("Cumul Bonus Historique", f"{hist_bon:,.2f} €", help="Total des bonus/airdrops perçus depuis le début de l'activité.")

            st.info("💡 Les cumuls historiques scannent tous vos journaux qualifiés depuis le début de l'activité.")
        else:
            st.info("Aucune récompense qualifiée (Intérêt/Bonus) pour le moment.")
            with st.expander("Pourquoi les totaux sont à 0 ?"):
                st.write(f"- Total flux entrants détectés : **{len(df_rewards)}**")
                st.write(f"- Catégories présentes dans vos données : {df_rewards['Category'].unique().tolist()}")
                st.write("- Pour apparaître ici, une transaction doit être qualifiée comme 'Intérêt' ou 'Bonus' (ou équivalent) dans l'onglet de gauche.")
    else:
        st.info("En attente de données qualifiées.")

st.sidebar.divider()
st.sidebar.caption("Rewards & Airdrops v1.0 - appInteretBonus")
