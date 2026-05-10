# MÉMOIRE TECHNIQUE ET CONSIGNES ARCHITECTURALES (SUITE JULES CRYPTO)

Ce document récapitule la structure, les fonctions critiques et les règles de non-régression de la suite logicielle.

**INTERDICTIONS ABSOLUES : D'OMETTRE DE CONSULTER, DE SUPPRIMER OU MODIFIER CE MEMO_CONSIGNES.MD SANS L'ACCORD DE L'UTILISATEUR.**

## 1. Principes Fondamentaux (Droit de Regard de l'Agent)
- **Sanctuarisation :** Chaque année fiscale est isolée dans `/sanctuarisation/{year}/`. Les fichiers `.csv` qualifiés sont la source de vérité pour les calculs fiscaux.
- **Continuité Historique :** Les soldes de fin d'année (EOY) sont portés à l'année suivante.
- **Centralisation :** Toute logique partagée (Calculs fiscaux Art. 150 VH bis, valorisation EUR, normalisation d'adresses, indexation) doit résider dans `shared_logic.py`.
- **Non-Régression :** Ne jamais supprimer une fonctionnalité UI (expanders, filtres, outils de détection) lors d'une refactorisation technique.
- **Exclusion des Spams (Zéro Spam) :** Tout actif ou transaction marqué comme 'Spam' doit être **strictement exclu** de tous les calculs avals (VGP, Portefeuille, Bilan Fiscal). Cette règle s'applique impérativement au module "Live Harvest" de `main.py`.

## 2. Moteur de Collecte 3-Voies & Standard "RAW" (Sanctuarisation V4)
Ce protocole définit la gestion de la récolte de données pour garantir une complétude absolue (Zéro Omission) et une harmonisation totale entre Blockchain et Plateformes.

### A. Architecture du Moteur (app.py)
Le fichier `app.py` est le sanctuaire de la récolte. Il doit rester **pur de tout calcul fiscal ou de prix**.
- **VOIE 1 (Blockscout Deep Scan) :** Priorité sémantique (étiquettes de contrats From_Label/To_Label).
- **VOIE 2 (API Scans) :** Contrôle comptable (Internal Transactions, précision des frais L1/L2).
- **VOIE 3 (Imports CEX/Offline) :** Intégration des fichiers `raw_*.csv` produits par les apps spécialisées (ex: `appNeverless.py`, `appBleap.py`).

### B. Standard de Données Cible (SCHEMA RAW V4)
Tout fichier produit par le moteur ou par un importeur Voie 3 doit utiliser ce schéma :
- **Colonnes :** Date (UTC ISO 8601), Chain, Tx_Hash (ID unique), Type (Native, Token, Internal, CEX_Mvt), Method, Account, From, To, From_Label, To_Label, Counterparty, Asset, Amount (Positif), Fee_Asset, Fee_Amount, Source_Way, Audit_Status, Fee_Audit_Alert.
- **Zéro Valorisation :** Les fichiers RAW ne contiennent aucune conversion EUR/USD.

### C. Logique d'Audit & Harmonisation
- **Dédoublonnage :** Fusion par `Tx_Hash`. Priorité à la ligne la plus riche.
- **Audit Bloquant :** Sanctuarisation interdite tant que des conflits de frais ou transferts orphelins subsistent.
- **Agrégation Exhaustive (app2.py) :** Le moteur de qualification doit traiter chaque ligne possible des fichiers bruts. En cas de colonne manquante, utiliser des fallbacks (ex: Date par défaut au 31/12 pour inventaires).

## 3. Structure de la Suite Logicielle

### `main.py` (Hub)
- Navigation unifiée. Protège l'état global via clés `_hub_`.
- **Live Harvest :** Utilise obligatoirement la liste des spams qualifiés (`shared_logic.load_spam_list`) pour le filtrage temps réel.

### `app2.py` (Qualification & Nettoyage - Step 2) - **CRITIQUE**
- **Fusion (Sync) :** Intégration exhaustive des données brutes avec protection contre la perte de date.
- **Gestion des Doublons :** Expander de revue et **surlignage rouge** des lignes suspectes.
- **Réconciliation :** Confirmation manuelle des liens inter-comptes.
- **Référentiels (Sidebar) :** Enregistrement unifié et fonctions CRUD (Edit/Delete).

## 4. Règles d'Interface (UI Standards)
- **Largeur Plein Écran :** Utilisation systématique de `layout="wide"`.
- **Système Opérationnel :** Succès `✅ Système Opérationnel` permanent en sidebar.
- **Réactivité :** Appel à `st.rerun()` après toute modification.
- **Intégrité Temporelle :** Exclusion de toute transaction sans date valide (NaT, None).
- **Robustesse des Imports :** Mapping CSV insensible à la casse et sans espaces (strip).
