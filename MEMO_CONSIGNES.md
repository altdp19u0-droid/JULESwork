# MÉMOIRE TECHNIQUE ET CONSIGNES ARCHITECTURALES (SUITE JULES CRYPTO)

Ce document est le référentiel unique de la structure, des fonctions critiques et des règles de non-régression de la suite logicielle.

**INTERDICTIONS ABSOLUES : IL EST STRICTEMENT INTERDIT D'OMETTRE DE CONSULTER, DE SUPPRIMER OU DE MODIFIER CE MÉMOIRE SANS L'ACCORD EXPLICITE ET PRÉALABLE DE L'UTILISATEUR.**

---

## I. GOUVERNANCE & PRINCIPES FONDAMENTAUX
1. **Sanctuarisation Annuelle :** Chaque année fiscale est isolée dans `/sanctuarisation/{year}/`. Les fichiers `.csv` qualifiés sont la source de vérité absolue.
2. **Continuité Historique :** Les soldes de fin d'année (EOY) sont portés à l'année suivante comme point de départ.
3. **Logique Centralisée :** Toute logique partagée (Calculs Art. 150 VH bis, valorisation EUR, normalisation d'adresses, indexation exhaustive) doit résider exclusivement dans `shared_logic.py`.
4. **Protection du Code Réussi :** Il est strictement interdit de modifier les modules désignés comme "code fonctionnel réussi" par l'utilisateur sans une décision de modification concertée et un accord formel.
    - **Modules Sanctuarisés :** `app.py`, `appNeverless.py`.
5. **Non-Régression Fonctionnelle :** Ne jamais supprimer une fonctionnalité UI (expanders, filtres, outils de détection ou de gestion) lors d'une refactorisation.
6. **Zéro Spam Universel :** Tout actif ou transaction marqué comme 'Spam' dans `app2.py` ou via la blacklist globale doit être **strictement exclu** de tous les calculs (VGP, Portefeuille, Bilan Fiscal) et affichages avals.
    - **Procédure :** Utiliser systématiquement `sl.apply_spam_filter(df, drop=True)` lors du chargement des données dans les modules de calcul ou de reporting.

---

## II. MODULES APPLICATIFS & PHASES DU PROCESSUS

### 1. PHASE 1 : RÉCOLTE & STANDARD "RAW" (app.py)
Le fichier `app.py` est le sanctuaire de la récolte. Il doit rester **pur de tout calcul fiscal ou de prix**.

**ALERTE CRITIQUE : IL EST STRICTEMENT INTERDIT DE MODIFIER LES FICHIERS `app.py` ET `appNeverless.py`.** Ces fichiers ont atteint un niveau de fiabilité complexe à obtenir et toute modification risque de dégrader la qualité du traitement.

- **app.py (Harvest) :** Moteur de récolte à 3 voies (Blockscout, Etherscan API V2).
- **appNomplateforme.py (ex: appNeverless.py, appBleap.py) :** Modules spécialisés pour les imports CSV locaux/spécifiques.

#### Architecture du Moteur à 3 Voies (app.py)
- **VOIE 1 (Blockscout Deep Scan) :** Priorité sémantique (extraction des étiquettes From_Label/To_Label et types de processus).
- **VOIE 2 (API Scans) :** Contrôle comptable (Internal Transactions, précision des frais L1/L2 via Etherscan API V2 avec Smart Fallback).
- **VOIE 3 (Imports CEX/Offline) :** Intégration automatique des fichiers `raw_*.csv` locaux.
- **FUSION INTELLIGENTE :** Dédoublonnage scrupuleux par le quadruplet **`(Tx_Hash, Asset, Account, Chain)`**. La fusion doit préserver les labels de la Voie 1 et injecter les frais/méthodes de la Voie 2.
- **NOMMAGE CONSOLIDÉ :** Le fichier final doit impérativement porter le suffixe `_consolidated_` (ex: `raw_transactions_consolidated_*.csv`) pour indiquer le traitement multivoie.
- **IDENTIFICATION DES COMPTES :** Utiliser systématiquement `standardize_address_string` pour discriminer et unifier les identités. Le standard absolu est le format : **`Identifiant_Technique (Nom_Amical)`**.

### 2. Standard de Données Cible (SCHEMA RAW V4)
Tout fichier produit (moteur ou importeur Voie 3) doit utiliser exactement ce schéma de 23 colonnes :
- **Date** (UTC ISO 8601), **Chain**, **Tx_Hash** (ID unique), **Type** (Native, Token, Internal, CEX_Mvt), **Method**, **Account**, **From**, **To**, **From_Label**, **To_Label**, **Counterparty**, **Asset**, **Amount**, **Valeur $**, **USD prix asset reçu**, **USD prix asset envoyé**, **USD prix de fée asset**, **Fee_Asset**, **Fee_Amount**, **Source_Way**, **Audit_Status**, **Fee_Audit_Alert**, **Source_Exchange_Rate**.
- **Zéro Valorisation :** Les fichiers RAW ne contiennent aucune conversion EUR/USD externe.

---

## III. PHASE 2 : QUALIFICATION & NETTOYAGE (app2.py)
C'est l'étape critique de transformation des données brutes en journal comptable.

1. **Agrégation Exhaustive & Fidelity Engine :**
    - **Ingestion Robuste :** Utilisation de `discover_col` pour identifier dynamiquement les colonnes critiques (Date, Compte, Asset, Montant, Hash, Valuations USD) dans divers formats CSV (Blockchain V4, Legacy, Portfolio, Imports tiers).
    - **Fidelity Engine :** Lors de la synchronisation, le système doit impérativement préserver les modifications manuelles de l'utilisateur (Statut, Catégorie, Imposable, VGP, Valuations USD) déjà présentes dans le journal qualifié en utilisant un UID composite exhaustif `(Tx_Hash, Asset, Account, Amount, Date)` pour éviter toute collision sur des transactions identiques (ex: swaps de même montant à la même seconde).
    - **Architecture Clean Gateway :** `app2.py` produit deux versions du journal : `qualif_journal_{year}_FULL.csv` (Audit complet incluant les spams) et `qualif_journal_{year}.csv` (Version nettoyée, labels résolus, prête pour la fiscalité).
2. **Gestion des Référentiels (Sidebar) :**
    - **Enregistrement Unifié :** Formulaire sidebar pour assigner une adresse/label à un registre (Propriétaire, Position, Circuit, Spam).
    - **CRUD Manuel :** Chaque registre (Spams, Propriétaires, Circuits, Positions) doit disposer de fonctions individuelles de **Modification** et **Suppression**.
3. **Audit & Récupération :**
    - Comparaison systématique avec le `sanctuary/`. Restauration par bloc ou sélection.
    - Utilisation d'empreintes temporelles et techniques pour identifier les orphelins.
4. **Outils d'Injection :**
    - **Flux Fiat :** Injection simplifiée vers `manual_fiat_{year}.csv` avec contrepartie par défaut "banq fiat".
    - **Swaps & Internes :** Injection multi-jambes vers `manual_swaps_{year}.csv` pour lier les flux crypto-to-crypto.

---

## IV. PHASE 3 : AUDIT, VGP & FISCALITÉ
Utilisation des données nettoyées pour le reporting final.

1. **VGP Cumulative (app2VGP) :** Calcul par sommation stricte des soldes (Comptes + Positions + Créances).
2. **Bilan Fiscal (app3) :** Application stricte Art. 150 VH bis. Lock automatique si ruptures de stock détectées par `appDiagCoh.py`.
3. **Diagnostic (appDiagCoh) :** Traçage chronologique et détection des soldes négatifs. Utilise `sl.load_clean_history()`.

---

## V. STANDARDS TECHNIQUES & UI
- **Largeur Plein Écran :** `layout="wide"`.
- **Indépendance des Modules :** `if "is_hub" not in st.session_state: st.set_page_config(...)`.
- **Type Safety :** Conversion numérique forcée (`pd.to_numeric`) sur `Amount`, `Value ($)` et `VGP (EUR)`.
- **UTC Timestamps :** Toutes les colonnes 'Date' doivent être converties en format Datetime UTC (`pd.to_datetime(..., utc=True)`) dès l'ingestion pour éviter les `TypeError` lors des tris ou comparaisons.
