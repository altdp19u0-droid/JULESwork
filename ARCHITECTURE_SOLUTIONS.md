# ARCHITECTURE ET SOLUTIONS TECHNIQUE OPTIMALES POUR L'APPLICATION SANCTUARY

Ce document fournit une analyse approfondie et une recommandation d'architecture logicielle pour l'implémentation de l'application autonome de **Sanctuarisation, Sauvegarde et Totalisation à 2 niveaux (SANCTUARY)**.

---

## 1. STACK TECHNIQUE RECOMMANDÉE (SOLUTIONS 100% GRATUITES)

| Composant | Technologie Recommandée | Justification / Avantages Gratuité |
|---|---|---|
| **Framework UI** | `Streamlit` | Gratuit, open-source et idéal pour construire rapidement des tableaux de bord financiers interactifs. |
| **Data Engine & Manipulation** | `Pandas` + `Numpy` | Moteur libre de traitement de séries temporelles, dédoublonnage multi-critères et encodage `utf-8-sig`. |
| **Collecte Blockchain EVM** | **Blockscout V2 API (Priorité 1)** + APIs Etherscan Free Tier | **Blockscout est 100% gratuit, illimité et ne nécessite aucune clé d'API** pour extraire transactions natives, ERC-20, internes et soldes sur Ethereum, Base, et Arbitrum. |
| **Taux FX (Fiat/EUR)** | API Officielle BCE (`data-api.ecb.europa.eu`) & API Frankfurter | 100% gratuit et sans clé d'API. Taux quotidiens officiels de la Banque Centrale Européenne. |
| **Taux Crypto (USD/EUR)** | **DefiLlama LlamaCoins API** + CoinGecko Public API | DefiLlama LlamaCoins est 100% gratuit sans clé d'API pour les prix historiques crypto. |
| **Gestion des Fichiers & Chemins** | `pathlib.Path` | Traitement des dossiers `sanctuary/{YEAR}/` sans dépendance externe, compatible Windows/Linux/macOS. |
| **Visualisation & Dashboards** | `Plotly Express` | Graphiques interactifs open-source et gratuits. |

---

## 2. STRATÉGIE DE COLLECTE BLOCKCHAIN : PRIORITÉ BLOCKSCOUT V2

Blockscout V2 fournit une suite d'endpoints REST extrêmement puissants et libres d'accès.

### Endpoints Blockscout V2 Gratuits Utilisés :
1. **Transactions Natives** : `GET https://{network}.blockscout.com/api/v2/addresses/{address}/transactions`
2. **Transferts de Tokens ERC-20** : `GET https://{network}.blockscout.com/api/v2/addresses/{address}/token-transfers`
3. **Transactions Internes** : `GET https://{network}.blockscout.com/api/v2/addresses/{address}/internal-transactions`
4. **Découverte de Balances** : `GET https://{network}.blockscout.com/api/v2/addresses/{address}/token-balances`

### Hôtes Blockscout par Réseau :
- **Ethereum** : `https://eth.blockscout.com/api/v2`
- **Base** : `https://base.blockscout.com/api/v2`
- **Arbitrum** : `https://arbitrum.blockscout.com/api/v2`

---

## 3. ARCHITECTURE MODULAIRE ET ORGANISATION DES FICHIERS

```text
sanctuary_app/
│
├── main.py                     # Point d'entrée principal (Streamlit Hub)
├── PROMPT_S_SAN.md             # Spécification du prompt système (Blockscout Priority)
├── ARCHITECTURE_SOLUTIONS.md   # Document d'architecture et recommandations
│
├── modules/
│   ├── __init__.py
│   ├── schema.py              # Enforcing du schéma des 17 colonnes et typages
│   ├── sanctuary_manager.py   # Gestion de la sanctuarisation (sanctuary/{YEAR}/{compte}.csv)
│   ├── fx_collector.py        # Moteur d'extraction des taux ECB (BCE) & DefiLlama
│   ├── blockscout_collector.py# Moteur d'extraction Blockscout V2 (Priorité) & fallback EVM
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

## 4. DESIGN DÉTAILLÉ DES MODULES LOGICIELS

### 4.1 `blockscout_collector.py` (Moteur Gratuit Principal)

```python
import requests
import time

BLOCKSCOUT_HOSTS = {
    "ETHEREUM": "https://eth.blockscout.com/api/v2",
    "BASE": "https://base.blockscout.com/api/v2",
    "ARBITRUM": "https://arbitrum.blockscout.com/api/v2"
}

def fetch_blockscout_transactions(address: str, network: str):
    """
    Récupération 100% gratuite via Blockscout V2 sans aucune clé d'API.
    """
    base_url = BLOCKSCOUT_HOSTS.get(network.upper())
    if not base_url:
        return []

    url = f"{base_url}/addresses/{address}/transactions"
    all_txs = []

    while url:
        res = requests.get(url, timeout=15)
        if res.status_code != 200:
            break
        data = res.json()
        items = data.get("items", [])
        all_txs.extend(items)

        # Gestion de la pagination Blockscout V2
        next_params = data.get("next_page_params")
        if next_params:
            q_str = "&".join([f"{k}={v}" for k, v in next_params.items()])
            url = f"{base_url}/addresses/{address}/transactions?{q_str}"
        else:
            url = None
        time.sleep(0.1) # Respect courtoisie

    return all_txs
```

---

### 4.2 `analytics_engine.py` (Totalisation à 2 Niveaux)

1. **Totalisation Niveau A (Compte Individuel sur Période)** :
   - Filtre ciblé sur un fichier `sanctuary/{YEAR}/{compte}.csv` et plage de dates.
   - Synthèse des entrées/sorties brutes + contre-valeur EUR.

2. **Totalisation Niveau B (Globalisation Multi-Comptes sur Période)** :
   - Agrégation de tous les fichiers du dossier `sanctuary/{YEAR}/` pour la période choisie.
   - Consolidation multi-comptes, répartition par projet et par réseau.

---

## 5. RECOMMANDATIONS ET BONNES PRATIQUES

1. **Gratuité Totale** : Utilisation combinée de Blockscout V2, ECB/Frankfurter API et DefiLlama LlamaCoins API pour garantir un fonctionnement sans aucun abonnement payant ni clé API obligatoire.
2. **Compatibilité Windows** : Utilisation systématique de `utf-8-sig` lors des exports CSV pour une ouverture optimale dans Excel.
3. **Pérennité & Autonomie** : L'architecture autonome garantit que l'utilisateur conserve 100% du contrôle local sur ses données sanctuarisées.
