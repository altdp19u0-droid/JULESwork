# ARCHITECTURE ET SOLUTIONS TECHNIQUE OPTIMALES POUR L'APPLICATION SANCTUARY

Ce document fournit une analyse approfondie et une recommandation d'architecture logicielle pour l'implémentation de l'application autonome de **Sanctuarisation, Sauvegarde et Totalisation à 2 niveaux (SANCTUARY)**.

---

## 1. STACK TECHNIQUE RECOMMANDÉE

| Composant | Technologie Recommandée | Justification / Avantages |
|---|---|---|
| **Framework UI** | `Streamlit` / `CustomTkinter` | Streamlit permet de construire rapidement des tableaux de bord financiers réactifs, filtres dynamiques, graphiques et vues multi-onglets sans surcoût d'architecture. |
| **Data Engine & Manipulation** | `Pandas` + `Numpy` | Idéal pour le traitement de séries temporelles, le dédoublonnage multi-critères, les groupements/pivotations et l'encodage `utf-8-sig`. |
| **Collecte Blockchain EVM** | `web3.py` + `requests` (Etherscan/Blockscout REST V2 APIs) | Offre une récupération robuste et rapide des transactions natives, transferts ERC-20 et métadonnées de gaz sur Ethereum, Base et Arbitrum. |
| **Taux FX (ECB)** | API REST officielle de la BCE (`https://data-api.ecb.europa.eu/`) ou la bibliothèque `ecbdata` / Frankfurter API | Récupération gratuite, officielle et sans clé d'API des taux quotidiens EUR/USD, EUR/GBP, etc., mis à jour par la Banque Centrale Européenne. |
| **Gestion des Fichiers & Chemins** | `pathlib.Path` | Assure la création dynamique de dossiers `sanctuary/{YEAR}/` et la gestion multi-plateforme (Windows/Linux/macOS) sans risque de séparateurs de chemin. |
| **Visualisation & Dashboards** | `Plotly Express` | Offre des graphiques interactifs pour la répartition par projet, par réseau et l'évolution temporelle des flux. |

---

## 2. ARCHITECTURE MODULAIRE ET ORGANISATION DES FICHIERS

```text
sanctuary_app/
│
├── main.py                     # Point d'entrée principal (Streamlit Hub)
├── PROMPT_S_SAN.md             # Spécification du prompt système
├── ARCHITECTURE_SOLUTIONS.md   # Document d'architecture et recommandations
│
├── modules/
│   ├── __init__.py
│   ├── schema.py              # Enforcing du schéma des 17 colonnes et typages
│   ├── sanctuary_manager.py   # Gestion de la sanctuarisation (sanctuary/{YEAR}/{compte}.csv)
│   ├── fx_collector.py        # Moteur d'extraction des taux ECB (BCE) et conversion EUR
│   ├── evm_collector.py       # Moteur d'extraction Blockchain (Ethereum, Base, Arbitrum)
│   ├── csv_importer.py        # Assistant d'importation et mapping dynamique de CSV
│   └── analytics_engine.py    # Moteur de totalisation à 2 niveaux (Niveau A & Niveau B)
│
└── sanctuary/                 # Dossier sanctuarisé de stockage local
    ├── 2023/
    │   └── 0x123..._Ethereum.csv
    └── 2024/
        ├── 0x123..._Ethereum.csv
        └── Compte_Banque_EUR.csv
```

---

## 3. DESIGN DÉTAILLÉ DES MODULES LOGICIELS

### 3.1 `schema.py` (Validation & Intégrité des Données)
- Définition d'une constante `SANCTUARY_SCHEMA` contenant la liste stricte des **17 colonnes**.
- Validation automatique de tout DataFrame avant écriture sur disque avec `fillna` et formatage ISO pour les dates (`YYYY-MM-DD HH:MM:SS`).

```python
# Exemple de validation
REQUIRED_COLUMNS = [
    "Date de la transaction", "Type de transaction", "ID du projet", "Nom du projet",
    "APR %", "Montant d'origine", "Devise d'origine", "Montant du relevé",
    "Devise du relevé", "Paire FX", "Taux de change appliqué",
    "Date du taux de change appliqué", "Source du taux de change",
    "Statut de la transaction", "Réseau", "Hash de la transaction blockchain",
    "Notes banque fiat d'origine ou de destination"
]
```

---

### 3.2 `fx_collector.py` (Collecte Taux ECB & Valuations)
- **Cache local avec TTL** (ex: `@st.cache_data`) pour éviter de surcharger les serveurs de la BCE lors des requêtes historiques.
- **Principe de dérivation Taux ECB/Crypto** :
  1. Transaction Fiat (ex: USD) : Récupération directe du taux ECB USD/EUR pour la date $D$.
  2. Transaction Crypto (ex: ETH sur Arbitrum) : Récupération du cours USD de l'actif pour la date $D$, puis conversion en EUR via le taux officiel ECB USD/EUR pour la même date.

---

### 3.3 `sanctuary_manager.py` (Gestion du Stockage Local Windows)
- Création automatique du dossier `sanctuary/{YEAR}/` lors de l'insertion.
- Écriture au format `utf-8-sig` avec `index=False`.
- **Dédoublonnage intelligent** :
  ```python
  df_combined = pd.concat([df_existing, df_new]).drop_duplicates(
      subset=["Hash de la transaction blockchain", "Devise d'origine", "Date de la transaction"],
      keep="last"
  )
  ```

---

### 3.4 `analytics_engine.py` (Totalisation à 2 Niveaux)

L'application implémente deux fonctions distinctes pour l'analyse financière :

1. **Totalisation Niveau A (Compte Individuel sur Période)** :
   ```python
   def totalize_level_a(df: pd.DataFrame, account_name: str, start_date, end_date):
       # Filtre sur le compte et la plage de dates choisie
       sub_df = df[(df['Compte'] == account_name) & (df['Date'] >= start_date) & (df['Date'] <= end_date)]
       # Agrégation par Devise d'origine et Total converti EUR
       return sub_df.groupby('Devise d'origine').agg({
           "Montant d'origine": "sum",
           "Montant du relevé": "sum"
       })
   ```

2. **Totalisation Niveau B (Globalisation Multi-Comptes sur Période)** :
   ```python
   def totalize_level_b(df_all_accounts: pd.DataFrame, start_date, end_date):
       # Filtre uniquement sur la plage de dates globale (tous comptes confondus)
       sub_df = df_all_accounts[(df_all_accounts['Date'] >= start_date) & (df_all_accounts['Date'] <= end_date)]
       # Synthèse globale consolidated en EUR + ventilation par compte & réseau
       summary_eur = sub_df["Montant du relevé"].sum()
       by_network = sub_df.groupby("Réseau")["Montant du relevé"].sum()
       by_project = sub_df.groupby("Nom du projet")["Montant du relevé"].sum()
       return summary_eur, by_network, by_project
   ```

---

## 4. CONSEILS ET BONNES PRATIQUES D'EXPÉRIENCEUTILISATEUR (UX)

1. **Rétrocompatibilité Excel Windows** : L'encodage `utf-8-sig` garantit l'ouverture directe des fichiers CSV dans Microsoft Excel Windows sans altération des accents.
2. **Robustesse des APIs Blockchain** : Prévoir une gestion de Rate Limit (`time.sleep` progressif) lors des requêtes d'historiques profonds sur Ethereum, Base et Arbitrum.
3. **Sécurité & Confidentialité** : Traitement 100% local en exécutable ou script Python local, sans stockage ou transfert de données privées sur un serveur tiers.
