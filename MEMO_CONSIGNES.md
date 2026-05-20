# MÉMOIRE TECHNIQUE ET CONSIGNES ARCHITECTURALES (SUITE JULES CRYPTO)

Ce document est le référentiel unique de la structure, des fonctions critiques et des règles de non-régression de la suite logicielle.

**INTERDICTIONS ABSOLUES : IL EST STRICTEMENT INTERDIT D'OMETTRE DE CONSULTER, DE SUPPRIMER OU DE MODIFIER CE MÉMOIRE SANS L'ACCORD EXPLICITE ET PRÉALABLE DE L'UTILISATEUR.**

---

## I. GOUVERNANCE & ARCHITECTURE "CLEAN GATEWAY"

1. **Architecture Gateway Absolute :** Le module `app2.py` est l'unique autorité de certification des données. Il doit produire un fichier `qualified_journal_CLEAN_{year}.csv` **strictement et certifié sans spam**.
2. **Principe de Confiance Aveugle (Blind Trust) :** Les applications en aval (`app3`, `appPropri`, `appDiagCoh`, `appPriceFix`) sont interdites d'accès direct aux fichiers RAW. Elles doivent consommer exclusivement le journal CLEAN via le chargeur centralisé `sl.load_clean_history`.
3. **Sécurité de Chargement :** La fonction `sl.load_clean_history` agit comme une barrière de sécurité ultime en forçant la conversion des dates en UTC et en appliquant un second filtre anti-spam systématique.
4. **Sanctuarisation Annuelle :** Chaque année fiscale est isolée dans `/sanctuarisation/{year}/`. Les fichiers qualifiés dans ce dossier sont la source de vérité absolue.
5. **Protection du Code Réussi :** Il est strictement interdit de modifier les modules moteurs sans accord formel.
    - **Modules Sanctuarisés :** `app.py` (Harvest engine), `appNeverless.py`.

---

## II. PHASE 1 : RÉCOLTE & STANDARD "RAW V4" (app.py)

### 1. Standard de Données (23 Colonnes)
Tout fichier produit par le moteur ou les importeurs doit respecter scrupuleusement ce schéma :
- **Identification :** `Date` (UTC), `Chain`, `Tx_Hash`, `Type`, `Method`, `Account`, `From`, `To`, `From_Label`, `To_Label`, `Counterparty`, `Asset`, `Amount`.
- **Valuations USD (Nouveau Standard) :** `Valeur $`, `USD prix asset reçu`, `USD prix asset envoyé`, `USD prix de fée asset`.
- **Audit & Frais :** `Fee_Asset`, `Fee_Amount`, `Source_Way`, `Audit_Status`, `Fee_Audit_Alert`, `Source_Exchange_Rate`.

### 2. Robustesse du Moteur (app.py)
- **Multi-Voies :** Voie 1 (Blockscout - Labels & USD), Voie 2 (API Scans - Frais & Internes), Voie 3 (Imports CSV locaux).
- **Zéro 'NONE' sur Tx_Hash :** Le moteur doit inspecter récursivement les clés `hash`, `tx_hash`, `txHash`, `transaction_hash`, et `transactionHash`.
- **Dédoublonnage :** Groupement strict par le quadruplet **`(Tx_Hash, Asset, Account, Chain)`**.

---

## III. PHASE 2 : QUALIFICATION & CERTIFICATION (app2.py)

### 1. "Fidelity Engine" de Synchronisation
Lors de l'intégration de nouvelles données RAW, le système doit impérativement préserver les décisions de l'utilisateur déjà enregistrées :
- **UID Composite :** La correspondance se fait sur `(Tx_Hash, Asset, Account, Amount, Date)`.
- **Priorité Numérique :** Une valeur existante n'est écrasée que si elle est "vide". Pour les prix et USD, **0.00 est considéré comme vide**, permettant aux nouvelles récoltes Step 1 (Blockscout) d'enrichir les anciens journaux sans perte de données.
- **Colonnes Préservées :** `Audit_Status`, `Category`, `Imposable`, `VGP (EUR)`, `Valeur $`, et les 3 colonnes de prix USD.

### 2. Gestion de l'Exclusion des Spams
- **Zéro Spam CLEAN :** Le bouton "Sauvegarder" doit déclencher un `sl.apply_spam_filter(df, drop=True)` avant l'écriture du fichier CLEAN.
- **Hiérarchie de Filtrage :**
    1. **Statut Manuel :** Si `Audit_Status` est explicitement "Spam" (insensible à la casse), la ligne est bannie.
    2. **Blacklist Globale :** Si l'Asset ou la Contrepartie est dans `spam_blacklist.json`.
    3. **Protection Whitelist :** Les actifs dans `valid_assets.json` sont protégés sauf s'ils sont manuellement marqués "Spam".

### 3. Interface & UX
- **Indicateur de Modification :** Le bouton de sauvegarde doit changer de couleur (Rouge) dès qu'une modification est détectée dans l'éditeur.
- **CRUD Registres :** Les listes (Spams, Assets Valides, Propriétaires, Positions) en sidebar doivent permettre l'ajout et la suppression individuelle via des boutons dédiés.

---

## IV. PHASE 3 : AUDIT, VGP & PATRIMOINE

1. **appPriceFix (Collecteur de Prix) :**
    - Doit scanner exclusivement le journal CLEAN.
    - Priorité aux valuations USD récoltées (converties via taux fiat BCE) avant de solliciter CoinGecko.
    - **Robustesse Date :** Toujours convertir en datetime avant d'utiliser l'accesseur `.dt`.
2. **appPropri (Dashboard) :**
    - Affiche la synthèse des positions protocoles (selon `position_labels.json`).
    - Consomme exclusivement les données via `sl.load_clean_history` pour garantir un affichage sans spam.
3. **app3 (Fiscalité) :**
    - Application stricte de l'Art. 150 VH bis.
    - **Verrou de Sécurité :** Génération PDF interdite si `appDiagCoh` détecte des ruptures de stock (soldes négatifs) pour l'année cible.

---

## V. STANDARDS TECHNIQUES TRANSVERSES (shared_logic.py)

1. **Persistence Globale :** Utilisation de `global_config.json` pour stocker `start_year`, `processing_year`, et les réglages persistants par application (ex: `appPropri_year`).
2. **Encodage CSV :** Export systématique en `utf-8-sig` pour assurer la compatibilité Excel/Windows et la préservation des symboles monétaires.
3. **Nettoyage Automatisé :** Fonction de maintenance en sidebar pour purger les fichiers de travail `raw_*.csv` anciens, en conservant uniquement les deux dates de session les plus récentes.
4. **Type Safety Datetime :** Toute ingestion de donnée doit forcer `pd.to_datetime(..., utc=True)` pour éviter les plantages lors des tris et calculs temporels.
5. **Identité Unifiée :** Format standard `Identifiant (Label)` imposé par `sl.standardize_address_string`.
