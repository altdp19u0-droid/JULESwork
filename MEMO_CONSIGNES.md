# MÉMOIRE TECHNIQUE ET CONSIGNES ARCHITECTURALES (SUITE JULES CRYPTO)

Ce document est le référentiel unique de la structure, des fonctions critiques et des règles de non-régression de la suite logicielle.

**INTERDICTIONS ABSOLUES : IL EST STRICTEMENT INTERDIT D'OMETTRE DE CONSULTER, DE SUPPRIMER OU DE MODIFIER CE MÉMOIRE SANS L'ACCORD EXPLICITE ET PRÉALABLE DE L'UTILISATEUR.**

---

## I. GOUVERNANCE & PRINCIPES FONDAMENTAUX
1. **Sanctuarisation Annuelle :** Chaque année fiscale est isolée dans `/sanctuarisation/{year}/`. Les fichiers `.csv` qualifiés sont la source de vérité absolue.
2. **Continuité Historique :** Les soldes de fin d'année (EOY) sont portés à l'année suivante comme point de départ.
3. **Logique Centralisée :** Toute logique partagée (Calculs Art. 150 VH bis, valorisation EUR, normalisation d'adresses, indexation exhaustive) doit résider exclusivement dans `shared_logic.py`.
4. **Non-Régression Fonctionnelle :** Ne jamais supprimer une fonctionnalité UI (expanders, filtres, outils de détection ou de gestion) lors d'une refactorisation.
5. **Zéro Spam Universel :** Tout actif ou transaction marqué comme 'Spam' dans `app2.py` ou via la blacklist globale doit être **strictement exclu** de tous les calculs (VGP, Portefeuille, Bilan Fiscal) et affichages avals, y compris dans le module "Live Harvest".

---

## II. PHASE 1 : RÉCOLTE & STANDARD "RAW" (app.py)
Le fichier `app.py` est le sanctuaire de la récolte. Il doit rester **pur de tout calcul fiscal ou de prix**.

### 1. Architecture du Moteur à 3 Voies
- **VOIE 1 (Blockscout Deep Scan) :** Priorité sémantique (extraction des étiquettes From_Label/To_Label et types de processus).
- **VOIE 2 (API Scans) :** Contrôle comptable (Internal Transactions, précision des frais L1/L2 via Etherscan/BscScan).
- **VOIE 3 (Imports CEX/Offline) :** Intégration automatique des fichiers `raw_*.csv` locaux (ex: Neverless, Bleap).
- **FUSION INTELLIGENTE :** Dédoublonnage par le triplet `(Tx_Hash, Asset, Account)`. La fusion doit préserver les labels de la Voie 1 et injecter les frais/méthodes de la Voie 2.
- **NOMMAGE CONSOLIDÉ :** Le fichier final doit impérativement porter le suffixe `_consolidated_` (ex: `raw_transactions_consolidated_*.csv`) pour indiquer le traitement multivoie.
- **UI RÉCOLTE :** L'interface doit obligatoirement afficher trois tableaux distincts en conclusion de récolte par compte, même s'ils sont vides : **Portfolio**, **Transactions** et **Tokens**. Un message d'état doit confirmer l'accessibilité de Blockscout et Etherscan.
- **IDENTIFICATION DES COMPTES :** Utiliser systématiquement `format_owner_display` pour discriminer et unifier les identités. Un compte avec hex + label doit être fusionné en : **`Adresse (Nom)`**. Un compte label + nom doit être : **`Nom (Label)`**. La suite doit dédoublonner les listes pour qu'une même identité n'apparaisse qu'une fois. Un suivi incrémental des comptes collectés doit être visible.
- **CLÉ UNIVERSELLE :** Permettre la saisie d'une clé API unique en UI s'appliquant à tous les réseaux par défaut.

### 2. Standard de Données Cible (SCHEMA RAW V4)
Tout fichier produit (moteur ou importeur Voie 3) doit utiliser exactement ce schéma de 19 colonnes :
- **Date** (UTC ISO 8601), **Chain**, **Tx_Hash** (ID unique), **Type** (Native, Token, Internal, CEX_Mvt), **Method**, **Account**, **From**, **To**, **From_Label**, **To_Label**, **Counterparty**, **Asset**, **Amount** (Valeur algébrique), **Fee_Asset**, **Fee_Amount**, **Source_Way** (Way_1, Way_2, Way_3 ou Way_1+2), **Audit_Status**, **Fee_Audit_Alert**, **Source_Exchange_Rate** (Prix unitaire source).
- **Zéro Valorisation :** Les fichiers RAW ne contiennent aucune conversion EUR/USD externe. Seul le prix fourni par la source est capturé dans `Source_Exchange_Rate`.

### 3. Logique d'Audit & Harmonisation
- **Dédoublonnage :** Fusion par `Tx_Hash`. Priorité à la ligne la plus riche en métadonnées.
- **Audit Bloquant :** Sanctuarisation interdite si des colonnes critiques (`Date`, `Asset`, `Amount`) sont vides ou si des doublons de Hash internes à une voie persistent.

---

## III. PHASE 2 : QUALIFICATION & NETTOYAGE (app2.py)
C'est l'étape critique de transformation des données brutes en journal comptable.

1. **Agrégation Exhaustive :** Doit traiter chaque ligne des fichiers bruts sans exception. Utilise des fallbacks (ex: Date 31/12 pour inventaires si absent).
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

1. **VGP Cumulative (app2VGP) :** Calcul factuel par sommation des comptes. Correction de prix directe via `st.data_editor` avec mise à jour du cache.
2. **Bilan Fiscal (app3) :**
    - Application stricte de l'Art. 150 VH bis.
    - Ratio d'abattement plafonné à 1.0.
    - Génération de PDF Unicode (via DejaVuSans) et export CSV d'audit complet.
3. **Diagnostic (appDiagCoh) :** Traçage chronologique par actif et détection des soldes négatifs.
4. **Valorisation (shared_logic) :** Politique "Zéro-Fallback" (0.0 si erreur API) pour forcer l'audit manuel et garantir l'intégrité fiscale.

---

## V. STANDARDS TECHNIQUES & UI (TOUTES APPS)
- **Largeur Plein Écran :** Utilisation systématique de `layout="wide"`.
- **Navigation Hub (main.py) :** Orchestre l'accès aux modules et protège l'état via les clés `_hub_`.
- **Réactivité :** Appel systématique à `st.rerun()` après chaque modification de données.
- **Système Opérationnel :** Message de succès `✅ Système Opérationnel` permanent en sidebar.
- **Intégrité des Données :**
    - **Dates :** Exclusion automatique de toute transaction sans date valide (NaT, None).
    - **Imports :** Mapping CSV insensible à la casse et sans espaces superflus (`strip`).
    - **Indexation :** `get_known_accounts` doit agréger les noms de `owner_accounts.json`, `position_labels.json` et des journaux.
