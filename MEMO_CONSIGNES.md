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
- Intègre les importeurs spécialisés (`appNeverless.py`, `appBleap.py`).

### `app.py` (Récolte On-Chain - Step 1)
- Cœur de la récupération des données brutes depuis les blockchains (via Blockscout).
- Produit les fichiers `raw_*.csv` qui alimentent le reste de la suite.

### `app0.py` (Registres Manuels)
- Gestion des Flux Fiat, Positions Manuelles et Swaps Hors-Chaîne.
- Utilise une colonne 'Mod.' pour recharger les données dans le formulaire.

### `app2.py` (Qualification & Nettoyage - Step 2) - **CRITIQUE**
- **Fusion (Sync) :** Fusionne les données brutes avec le journal qualifié existant.
- **Gestion des Doublons :**
    - Détecte les doublons suspects (même montant/asset/compte à la même date).
    - **UX Sanctuarisée :** Affichage d'un expander de revue dédié et **surlignage rouge** des lignes suspectes dans le tableau principal.
- **Réconciliation des Maillons :**
    - Identifie les transferts inter-comptes et maillons (Bridge Out/In).
    - **UX Sanctuarisée :** Système de confirmation manuelle ("Proposed" vs "Confirmed") avec résumé statistique.
- **Gestion des Référentiels (Sidebar) :**
    - **Enregistrement Unifié :** Formulaire sidebar permettant d'assigner une adresse à un registre spécifique (Compte Propriétaire, Position, Circuit, ou Spam).
    - **CRUD Manuel :** Chaque registre dispose de boutons individuels de modification et de suppression.

### `appPriceFix.py` (Collecte des Prix)
- Identifie les manques de prix et permet la sanctuarisation des prix EUR aux dates utiles.

### `appPropri.py` (Visualisation Propriétaire)
- Affiche l'état consolidé et les soldes des comptes identifiés comme "Propriétaires".

### `app2VGP.py` (Audit & Portefeuille)
- Valorisation au 31/12 (Exclut les Spams).
- Calcul de la VGP cumulative (somme factuelle des comptes).

### `app3.py` (Bilan Fiscal)
- Application stricte du ratio d'abattement Art. 150 VH bis (Plafonné à 1.0).
- Génération de PDF fiscaux Unicode (DejaVuSans) et exports CSV d'audit.

### `shared_logic.py` (Le Cœur)
- `get_portfolio_snapshot` : Calcul de VGP factuel avec filtrage automatique.
- `get_safe_opts` : Extraction sécurisée des options pour les widgets (évite les erreurs de type).
- `standardize_asset` : Normalisation unifiée des noms d'actifs (homoglyphes, NFKC).

## 3. Règles d'Interface (UI Standards)
- Afficher systématiquement `✅ Système Opérationnel` dans la sidebar.
- Utiliser `st.rerun()` après chaque action de modification de données.
- Ne jamais utiliser `selection_mode` dans `st.data_editor` (compatibilité versions < 1.35.0).
