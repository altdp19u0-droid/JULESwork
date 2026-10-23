# 📘 GUIDE D'INSTALLATION ET D'EXÉCUTION SUR WINDOWS — SANCTUARY APP

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
├── lancer_sanctuary_usb.bat        <-- SCRIPT LANCEMENT SANCTUARY (Backup/Exploration)
├── lancer_apptrait.bat             <-- SCRIPT LANCEMENT APPTRAIT (Qualification & Anti-Spam)
├── lancer_viderCaches.bat          <-- SCRIPT NETTOYAGE DES CACHES
├── apptrait.py                     <-- Wrapper racine AppTrait
├── PROMPT_S_SAN.md                 <-- Cahier des charges Sanctuary
├── PROMPT_APPTRAIT.md              <-- Cahier des charges AppTrait
├── ARCHITECTURE_SOLUTIONS.md       <-- Architecture technique globale
├── GUIDE_INSTALLATION_WINDOWS.md   <-- Le présent guide
├── GUIDE_USB_PORTABLE.md           <-- Guide Clé USB
├── requirements.txt                <-- Bibliothèques Python requises
│
├── sanctuary_app/                  <-- DOSSIER CODE APPLICATION
│   ├── app.py                      <-- Point d'entrée principal Sanctuary
│   ├── apptrait.py                 <-- Application AppTrait Streamlit
│   └── modules/
│       ├── schema.py               <-- Schema 19 colonnes & dates UTC
│       ├── sanctuary_manager.py    <-- Sauvegarde & Dédoublonnage CSV
│       ├── fx_collector.py         <-- Taux BCE et prix crypto DefiLlama
│       ├── blockscout_collector.py <-- Collecte Blockscout V2
│       ├── csv_importer.py         <-- Mapping CSV dynamique
│       ├── analytics_engine.py     <-- Totalisation à 2 niveaux (A et B)
│       └── trait_manager.py       <-- Anti-Spam, Homoglyphes & Soldes Teval
│
├── sanctuary/                      <-- Dossier Sanctuarisé BRUT (Lecture seule)
└── trait_legit/                    <-- Dossier de Travail QUALIFIÉ (Duplication isolée)
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

## 5. LANCEMENT ET UTILISATION DES SCRIPTS BAT

1. **Lancement standard de l'application** :
   Double-cliquez sur `lancer_sanctuary_usb.bat` ou exécutez :
   ```cmd
   streamlit run sanctuary_app\app.py
   ```
2. **Nettoyage des Caches (`lancer_viderCaches.bat`)** :
   En cas d'erreur d'importation, de mise à jour de code ou de ralentissement, double-cliquez sur `lancer_viderCaches.bat` pour vider instantanément tous les fichiers de cache Python (`.pyc`, `__pycache__`) et le cache temporaire de Streamlit.

---

## 6. FONCTIONNEMENT ET ACCÈS AUX FICHIERS PRODUITS

- Toutes les données sanctuarisées sont stockées localement dans `C:\SanctuaryApp\sanctuary\{ANNÉE}\`.
- Les fichiers CSV sont directement écrits au format **UTF-8 avec BOM (`utf-8-sig`)**, ce qui permet d'ouvrir directement n'importe quel fichier CSV dans **Microsoft Excel sous Windows** sans aucun problème d'accentuation ni de mise en page.
