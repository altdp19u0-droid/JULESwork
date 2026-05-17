# MÉMOIRE TECHNIQUE ET CONSIGNES ARCHITECTURALES (SUITE JULES CRYPTO)

Ce document est le référentiel unique de la structure, des fonctions critiques et des règles de non-régression de la suite logicielle.

**INTERDICTIONS ABSOLUES : IL EST STRICTEMENT INTERDIT D'OMETTRE DE CONSULTER, DE SUPPRIMER OU DE MODIFIER CE MÉMOIRE SANS L'ACCORD EXPLICITE ET PRÉALABLE DE L'UTILISATEUR.**

---

## I. GOUVERNANCE & PRINCIPES FONDAMENTAUX
1. **Sanctuarisation Annuelle :** Chaque année fiscale est isolée dans `/sanctuarisation/{year}/`. Les fichiers `.csv` qualifiés sont la source de vérité absolue.
2. **Continuité Historique :** Les soldes de fin d'année (EOY) sont portés à l'année suivante comme point de départ.
3. **Logique Centralisée :** Toute logique partagée (Calculs Art. 150 VH bis, valorisation EUR, normalisation d'adresses, indexation exhaustive) doit résider exclusivement dans `shared_logic.py`.
4. **Non-Régression Fonctionnelle :** Ne jamais supprimer une fonctionnalité UI (expanders, filtres, outils de détection ou de gestion) lors d'une refactorisation.
5. **Zéro Spam Universel :** Tout actif ou transaction marqué comme 'Spam' dans `app2.py` ou via la blacklist globale doit être **strictement exclu** de tous les calculs (VGP, Portefeuille, Bilan Fiscal) et affichages avals.
    - **Procédure :** Utiliser systématiquement `sl.apply_spam_filter(df, drop=True)` lors du chargement des données dans les modules de calcul ou de reporting.

---

## II. PHASE 1 : RÉCOLTE & STANDARD "RAW" (app.py)
Le fichier `app.py` est le sanctuaire de la récolte. Il doit rester **pur de tout calcul fiscal ou de prix**.

**ALERTE CRITIQUE : IL EST STRICTEMENT INTERDIT DE MODIFIER LE FICHIER `app.py`.** Ce fichier a atteint un niveau de fiabilité complexe à obtenir et toute modification risque de dégrader la qualité de la récolte.

### 1. Architecture du Moteur à 3 Voies
- **VOIE 1 (Blockscout Deep Scan) :** Priorité sémantique (extraction des étiquettes From_Label/To_Label et types de processus).
- **VOIE 2 (API Scans) :** Contrôle comptable (Internal Transactions, précision des frais L1/L2 via Etherscan/BscScan).
- **VOIE 3 (Imports CEX/Offline) :** Intégration automatique des fichiers `raw_*.csv` locaux (ex: Neverless, Bleap).
- **FUSION INTELLIGENTE :** Dédoublonnage scrupuleux par le quadruplet **`(Tx_Hash, Asset, Account, Chain)`**. La fusion doit préserver les labels de la Voie 1 et injecter les frais/méthodes de la Voie 2.
- **NOMMAGE CONSOLIDÉ :** Le fichier final doit impérativement porter le suffixe `_consolidated_` (ex: `raw_transactions_consolidated_*.csv`) pour indiquer le traitement multivoie.
- **UI RÉCOLTE :**
    - **Structure :** L'interface doit obligatoirement afficher trois tableaux distincts : **Portfolio**, **Transactions** (Natives/Internes) et **Tokens** (ERC-20/CEX).
    - **Intégrité :** Chaque tableau doit impérativement afficher les 19 colonnes du standard RAW V4. La colonne `Asset` (nom de l'actif) doit être visible et renseignée pour tous les transferts.
    - **Diagnostic :** Confirmer l'accessibilité de Blockscout et Etherscan avec distinction claire entre succès, vide et erreur.
- **IDENTIFICATION DES COMPTES :** Utiliser systématiquement `standardize_address_string` pour discriminer et unifier les identités. Le standard absolu est le format : **`Identifiant_Technique (Nom_Amical)`**. La suite doit impérativement résoudre les labels en adresses hexadécimales (et vice-versa) via `owner_accounts.json` pour qu'un compte comme "Binance" et son adresse "0x123..." soient traités comme une seule entité. Dédoublonner les listes via `get_owner_display_list`.
- **GESTION DES CLÉS API :**
    - **Clé Universelle (V2 Unifiée) :** Permettre la saisie d'une clé API unique s'appliquant à tous les réseaux.
    - **Standard Etherscan V2 REST :**
        - **Endpoints RESTful :** Utiliser exclusivement la nouvelle structure REST V2 : `https://api.<chain>scan.<tld>/api/v2/accounts/{address}/transactions` (et `/erc20-transfers`, `/internal-transactions`).
        - **Paramètres :** Ne plus utiliser `module` ou `action` (V1). Utiliser uniquement `apikey`, `page`, et `offset`.
        - **Désactivation Fallback V1 :** Le repli vers la V1 est strictement interdit pour éviter les erreurs de dépréciation.
        - **Fidelity Consolidation :** La fusion multivoie (Way 1/2/3) doit utiliser un quadruplet étendu `(Tx_Hash, Asset, Chain, Amount, From, To)` combiné à un index d'occurrence (`cumcount` par hash/asset/chain/amount/from/to) pour préserver chaque mouvement distinct d'une transaction complexe (ex: swap avec plusieurs legs). L'index d'occurrence doit être calculé *avant* la fusion pour permettre l'alignement des données entre les différentes Voies.
        - **Transparence Technique :** Afficher les volumes collectés par "Way" et les messages d'erreur bruts des APIs.
    - **Temporisation FREE Plan :** Appliquer une pause de **400ms** minimum entre chaque appel API et gérer le retry automatique de **5s** en cas de "Rate Limit" pour respecter strictement les quotas des comptes gratuits (5 calls/sec).
    - **Diagnostic Explicite :** Capturer et afficher le message d'erreur brut de l'API (ex: "Invalid API Key") au lieu d'un message générique.

### 2. Standard de Données Cible (SCHEMA RAW V4)
Tout fichier produit (moteur ou importeur Voie 3) doit utiliser exactement ce schéma de 19 colonnes :
- **Date** (UTC ISO 8601), **Chain**, **Tx_Hash** (ID unique), **Type** (Native, Token, Internal, CEX_Mvt), **Method**, **Account**, **From**, **To**, **From_Label**, **To_Label**, **Counterparty**, **Asset**, **Amount** (Valeur algébrique avec signe géré dès la récolte), **Fee_Asset**, **Fee_Amount**, **Source_Way** (Way_1, Way_2, Way_3 ou Way_1+2), **Audit_Status**, **Fee_Audit_Alert**, **Source_Exchange_Rate** (Prix unitaire source).
- **Zéro Valorisation :** Les fichiers RAW ne contiennent aucune conversion EUR/USD externe. Seul le prix fourni par la source est capturé dans `Source_Exchange_Rate`.

### 3. Logique d'Audit & Harmonisation
- **Dédoublonnage :** Fusion par `Tx_Hash`. Priorité à la ligne la plus riche en métadonnées.
- **Audit Bloquant :** Sanctuarisation interdite si des colonnes critiques (`Date`, `Asset`, `Amount`) sont vides ou si des doublons de Hash internes à une voie persistent.

---

## III. PHASE 2 : QUALIFICATION & NETTOYAGE (app2.py)
C'est l'étape critique de transformation des données brutes en journal comptable.

1. **Agrégation Exhaustive & Fidelity Engine :**
    - Doit traiter chaque ligne des fichiers bruts sans exception. Utilise des fallbacks (ex: Date 31/12 pour inventaires si absent).
    - **Fidelity Engine :** Lors de la synchronisation, le système doit impérativement préserver les modifications manuelles de l'utilisateur (Statut, Catégorie, Imposable, VGP) déjà présentes dans le journal qualifié en utilisant un quintuplet de correspondance (Date, Account, Asset, Amount, Hash).
    - **Persistance Directe :** La sanctuarisation dans `app2.py` doit itérer manuellement sur l'éditeur pour reporter chaque modification sur le journal complet en session avant l'écriture disque.
    - **Architecture Clean Gateway :** Lors de la sanctuarisation, `app2.py` génère impérativement un second fichier : `qualified_journal_CLEAN_{year}.csv`. Ce fichier est purgé des spams et doublons, et contient les labels résolus. C'est l'unique source de vérité pour les applications avals.
2. **Gestion des Doublons Suspects :**
    - Détection fine par trio (Montant/Asset/Compte) à date identique.
    - **Interface :** Expander de revue dédié et **surlignage rouge** des lignes suspectes dans le tableau.
3. **Réconciliation des Maillons :**
    - Appariement des transferts (ex: Bridge Out -> Bridge In).
    - **Interface :** Confirmation manuelle ("Proposed" vs "Confirmed") avec résumé statistique.
4. **Gestion des Référentiels (Sidebar) :**
    - **Enregistrement Unifié :** Formulaire sidebar pour assigner une adresse/label à un registre (Propriétaire, Position, Circuit, Spam).
    - **CRUD Manuel :** Chaque registre (Spams, Propriétaires, Circuits, Positions) doit disposer de fonctions individuelles de **Modification** et **Suppression**.

---

## IV. PHASE 3 : AUDIT, VGP & FISCALITÉ
Utilisation des données nettoyées pour le reporting final.

1. **VGP Cumulative (app2VGP) :**
    - **Modèle Comptable Factuel :** Calcul par sommation stricte des soldes (Comptes + Positions + Créances).
    - **Interdiction :** Les méthodes par "Wealth-Change" ou "Ajustements globaux" sont strictement interdites pour garantir l'auditabilité.
    - **Correction :** Correction de prix directe via `st.data_editor` avec mise à jour simultanée du cache global et annuel.
2. **Bilan Fiscal (app3) :**
    - **Sécurité Fiscale (Lock) :** Blocage automatique de la génération de rapport si `appDiagCoh.py` détecte des ruptures de stock (soldes négatifs) sur des cessions.
    - **Calcul Art. 150 VH bis :** Application stricte, ratio d'abattement plafonné à 1.0, exclusion des VGP non positives.
    - **PDF Professionnel :** Génération Unicode (DejaVuSans), gestion du word-wrap pour les adresses longues, synchronisation des hauteurs de lignes.
3. **Diagnostic (appDiagCoh) :** Traçage chronologique par actif/compte et détection des soldes négatifs comme outil de réparation. Utilise `sl.load_clean_history()` pour une vision globale instantanée.
4. **Valorisation (shared_logic) :** Politique "Zéro-Fallback" (0.0 si erreur API) pour forcer l'audit manuel et garantir l'intégrité fiscale. Utilisation des taux BCE (Frankfurter) pour les assets indexés fiat.
5. **Positions & Snapshots :** Le moteur `get_portfolio_snapshot` doit agréger les journaux qualifiés, les positions manuelles (`manual_positions_*.csv`) et les inventaires N-1. Les positions manuelles sont prioritaires pour définir le stock initial d'un compte.

---

## V. STANDARDS TECHNIQUES & UI (TOUTES APPS)
- **Largeur Plein Écran :** Utilisation systématique de `layout="wide"`.
- **Indépendance des Modules :** Chaque module `app*.py` doit pouvoir être exécuté seul (`streamlit run app*.py`). La configuration `st.set_page_config` doit être conditionnée à l'absence de la clé `is_hub` dans le `session_state` pour éviter les collisions lors de l'exécution via le Hub.
- **Intégrité des Widgets :** Pour éviter les conflits de `Session State`, les widgets utilisant des clés globales (ex: `_hub_target_year`) ne doivent pas définir de paramètre `value` ou `index` si la clé existe déjà en session.
- **Navigation Hub (main.py) :** Orchestre l'accès aux modules et protège l'état via les clés `_hub_`.
- **Réactivité :** Appel systématique à `st.rerun()` après chaque modification de données.
- **Système Opérationnel :** Message de succès `✅ Système Opérationnel` permanent en sidebar.
- **Intégrité des Données & Type Safety :**
    - **Conversion Numérique Forcée :** Appliquer systématiquement `pd.to_numeric(..., errors='coerce').fillna(0.0)` sur les colonnes `Amount`, `Value ($)` et `VGP (EUR)` pour éviter les crashs de type Float/String dans Streamlit.
    - **Dates :** Exclusion automatique de toute transaction sans date valide (NaT, None).
    - **Imports :** Mapping CSV insensible à la casse et sans espaces superflus (`strip`).
    - **Indexation :** `get_known_accounts` doit agréger les noms de `owner_accounts.json`, `position_labels.json` et des journaux.
