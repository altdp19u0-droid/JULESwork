# 📘 GUIDE D'INSTALLATION ET D'EXÉCUTION SOBRE WINDOWS — SANCTUARY APP

Ce guide explique pas à pas comment télécharger, organiser et installer l'application **Sanctuary App** sur votre ordinateur sous **Windows** pour un fonctionnement optimal.

---

## 1. PRÉREQUIS SYSTÈME (LOGICIELS À INSTALLER)

1. **Python 3.10 ou supérieur** (ex: Python 3.12)
   - **Téléchargement** : [https://www.python.org/downloads/](https://www.python.org/downloads/)
   - ⚠️ **IMPORTANT lors de l'installation Windows** : Cochez la case **"Add python.exe to PATH"** au tout début de l'installateur.

2. **Un éditeur de code ou Terminal Windows** (Optionnel)
   - L'application s'exécute directement depuis l'invite de commande (`cmd.exe`) ou **PowerShell**.

---

## 2. ARBORESCENCE ET EMPLACEMENT DES FICHIERS

Créez un dossier principal sur votre disque dur (ex: `C:\SanctuaryApp\`).
Placez-y les fichiers et dossiers exactement selon la structure suivante :

```text
C:\SanctuaryApp\
│
├── PROMPT_S_SAN.md                 <-- Cahier des charges / Spécifications du prompt
├── ARCHITECTURE_SOLUTIONS.md       <-- Architecture technique
├── GUIDE_INSTALLATION_WINDOWS.md   <-- Le présent guide
├── requirements.txt                <-- Liste des bibliothèques requises
│
├── sanctuary_app/                  <-- DOSSIER CODE APPLICATION
│   ├── app.py                      <-- FICHIER PRINCIPAL STREAMLIT (Point d'entrée)
│   └── modules/
│       ├── __init__.py
│       ├── schema.py               <-- Validation du schéma des 17 colonnes
│       ├── sanctuary_manager.py    <-- Sauvegarde & Dédoublonnage CSV Windows
│       ├── fx_collector.py         <-- Taux BCE (ECB) et prix crypto DefiLlama
│       ├── blockscout_collector.py <-- Collecte Blockscout V2
│       ├── csv_importer.py         <-- Assistant d'importation CSV
│       └── analytics_engine.py     <-- Totalisation à 2 niveaux (A et B)
│
└── sanctuary/                      <-- DOSSIER DE SANCTUARISATION (Généré automatiquement)
    ├── 2023/                       <-- (Créé auto lors des sauvegardes de 2023)
    └── 2024/                       <-- (Créé auto lors des sauvegardes de 2024)
        ├── MonCompte_Ethereum.csv  <-- Vos fichiers de compte au format UTF-8-SIG
        └── Banque_Principale.csv
```

---

## 3. FICHIER `requirements.txt`

Créez un fichier nommé `requirements.txt` à la racine de `C:\SanctuaryApp\` avec le contenu suivant :

```text
streamlit>=1.30.0
pandas>=2.0.0
requests>=2.28.0
python-dateutil>=2.8.2
```

---

## 4. ÉTAPES D'INSTALLATION SUR WINDOWS (PAS À PAS)

### Étape 1 : Ouvrir l'invite de commande Windows (cmd)
- Appuyez sur `Touche Windows + R`, tapez `cmd` et appuyez sur `Entrée`.

### Étape 2 : Se déplacer dans le dossier de l'application
```cmd
cd C:\SanctuaryApp
```

### Étape 3 : Créer un environnement virtuel Python (Recommandé)
```cmd
python -m venv venv
```

### Étape 4 : Activer l'environnement virtuel
```cmd
venv\Scripts\activate
```
*(Vous verrez `(venv)` apparaître au début de votre ligne de commande).*

### Étape 5 : Installer les bibliothèques requises
```cmd
pip install -r requirements.txt
```

---

## 5. LANCEMENT DE L'APPLICATION STREAMLIT

Pour lancer l'application, exécutez la commande suivante depuis `C:\SanctuaryApp` :

```cmd
streamlit run sanctuary_app\app.py
```

🎉 **C'est prêt !** Votre navigateur web par défaut s'ouvrira automatiquement à l'adresse locale :
👉 `http://localhost:8501`

---

## 6. FONCTIONNEMENT ET ACCÈS AUX FICHIERS PRODUITS

- Toutes les données sanctuarisées sont stockées localement dans `C:\SanctuaryApp\sanctuary\{ANNÉE}\`.
- Les fichiers CSV sont directement écrits au format **UTF-8 avec BOM (`utf-8-sig`)**, ce qui permet d'ouvrir directement n'importe quel fichier CSV dans **Microsoft Excel sous Windows** sans aucun problème d'accentuation ni de mise en page.
