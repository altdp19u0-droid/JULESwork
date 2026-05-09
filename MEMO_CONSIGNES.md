# MÉMOIRE TECHNIQUE ET CONSIGNES ARCHITECTURALES (SUITE JULES CRYPTO)

Ce document récapitule la structure, les fonctions critiques et les règles de non-régression de la suite logicielle.

**INTERDICTIONS ABSOLUES : D'OMETTRE DE CONSULTER, DE SUPPRIMER OU MODIFIER CE MEMO_CONSIGNES.MD SANS L'ACCORD DE L'UTILISATEUR.**

## 1. Principes Fondamentaux (Droit de Regard de l'Agent)
- **Sanctuarisation :** Chaque année fiscale est isolée dans `/sanctuarisation/{year}/`. Les fichiers `.csv` qualifiés sont la source de vérité pour les calculs fiscaux.
- **Continuité Historique :** Les soldes de fin d'année (EOY) sont portés à l'année suivante.
- **Centralisation :** Toute logique partagée (Calculs fiscaux Art. 150 VH bis, valorisation EUR, normalisation d'adresses) doit résider dans `shared_logic.py`.
- **Non-Régression :** Ne jamais supprimer une fonctionnalité UI (expanders, filtres, outils de détection) lors d'une refactorisation technique.
- **Exclusion des Spams (Zéro Spam) :** Tout actif ou transaction marqué comme 'Spam' dans `app2.py` doit être **strictement exclu** de tous les calculs avals (VGP, Portefeuille, Bilan Fiscal).

## 2. Structure de la Suite

### `main.py` (Hub)
- Orchestre la navigation via `st.sidebar.selectbox`.
- Protège l'état global avec des clés `_hub_`.

### `app.py` (Récolte On-Chain - Step 1)
- Cœur de la récupération des données brutes depuis les blockchains (via Blockscout).
- Gère le scan exhaustif des transactions natives et des transferts de jetons pour une adresse donnée.
- Produit les fichiers `raw_*.csv` qui alimentent le reste de la suite.

### `app0.py` (Registres Manuels)
- Gestion des Flux Fiat, Positions Manuelles et Swaps Hors-Chaîne.
- Utilise une colonne 'Mod.' pour recharger les données dans le formulaire.

### `app2.py` (Qualification & Nettoyage - Step 2) - **CRITIQUE**
- **Fusion (Sync) :** Fusionne les données brutes (harvesting) avec le journal qualifié existant sans écraser les modifications manuelles.
- **Moteur de Fidélité :** Détecte les doublons suspects (même montant/asset/compte à la même date mais Hash différent).
- **Détection Interne :** Identifie les transferts entre comptes "Propriétaires".
- **Réconciliation :** Apparie les "Maillons" (ex: Bridge Out -> Bridge In).
- **Gestion des Référentiels (Sidebar) :** Doit impérativement rester accessible en Sidebar.
    - **Outils :** Spams, Comptes Propriétaires, Circuits, Positions.
    - **Fonctions :** Chaque liste doit disposer de fonctions de **Modification** et **Suppression** manuelles.
    - **Saisie Unifiée :** Permettre l'assignation d'une nouvelle adresse au registre approprié (**Compte Propriétaire**, **Position**, ou **Externe/Circuit**) lors de la saisie.
- **Filtrage :** Applique le statut 'Spam' pour l'exclusion définitive des flux non désirés.

### `appPriceFix.py` (Collecte des Prix)
- Identifie les manques de prix pour les cessions et les inventaires de fin d'année.
- Permet la collecte et la sanctuarisation des prix EUR nécessaires aux dates utiles.

### `appPropri.py` (Visualisation Propriétaire)
- Affiche l'état consolidé et les soldes des comptes identifiés comme "Propriétaires".

### `app2VGP.py` (Audit & Portefeuille)
- Valorisation au 31/12 (Exclut les Spams).
- Calcul de la VGP cumulative (somme factuelle des comptes).
- Correction de prix directe via `st.data_editor` avec mise à jour du cache.

### `app3.py` (Bilan Fiscal)
- Application stricte du ratio d'abattement (Plafonné à 1.0).
- **Zéro Spam :** Aucune transaction marquée 'Spam' ne doit apparaître dans le bilan.
- Génération de PDF fiscaux avec mise en page robuste (Multi-cell).
- Export CSV complet pour audit.

### `appDiagCoh.py` (Diagnostic & Réparation)
- Traçage chronologique des actifs par compte.
- Détection des soldes négatifs et propositions de correction.

### `shared_logic.py` (Le Cœur)
- `get_portfolio_snapshot` : Supporte à la fois les fichiers disque et les DataFrames en mémoire. Filtre automatiquement les Spams.
- `get_price_eur` : Politique "Zéro-Fallback" (pas de taux approximatifs, 0.0 si erreur pour forcer l'audit).
- `resolve_raw_addr` : Extraction robuste des adresses 0x.

## 3. Règles d'Interface (UI Standards)
- Afficher systématiquement `✅ Système Opérationnel` dans la sidebar.
- Utiliser `st.rerun()` après chaque action de modification de données pour garantir la fraîcheur de l'affichage.
- Ne jamais utiliser `selection_mode` dans `st.data_editor` (compatibilité versions < 1.35.0).
