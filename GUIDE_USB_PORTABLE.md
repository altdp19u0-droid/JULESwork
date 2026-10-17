# 🔑 GUIDE : CRÉER ET UTILISER SANCTUARY APP SUR UNE CLÉ USB PORTABLE

Oui, **il est parfaitement possible et très avantageux de créer et d'exécuter l'application `SanctuaryApp` directement depuis une Clé USB** (ou disque SSD externe) sous Windows.

---

## 1. AVANTAGES DE LA VERSION CLÉ USB

1. **Portabilité Totale** : Vous pouvez brancher la clé USB sur n'importe quel ordinateur Windows (PC bureau, ordinateur portable, PC de secours) et lancer l'application immédiatement.
2. **Confidentialité & Sécurité Légale** : Vos fichiers de sanctuarisation (`sanctuary/{YEAR}/{compte}.csv`), l'historique complet de vos comptes et vos clés ne quittent jamais votre clé USB.
3. **Zéro Empreinte Système** : Aucune donnée n'est envoyée dans le cloud ni enregistrée dans le registre de Windows de l'ordinateur hôte.

---

## 2. ARBORESCENCE PORTABLE SUR LA CLÉ USB

Sur votre clé USB (ex: lecteur `E:\` ou `F:\`), créez le dossier `SanctuaryApp` à la racine :

```text
E:\SanctuaryApp\                     <-- Racine sur votre Clé USB
│
├── lancer_sanctuary_usb.bat        <-- SCRIPT LANCEMENT SANCTUARY
├── lancer_apptrait.bat             <-- SCRIPT LANCEMENT APPTRAIT (Qualification & Anti-Spam)
├── lancer_viderCaches.bat          <-- SCRIPT NETTOYAGE DES CACHES
├── apptrait.py                     <-- Wrapper racine AppTrait
├── PROMPT_S_SAN.md
├── PROMPT_APPTRAIT.md
├── ARCHITECTURE_SOLUTIONS.md
├── GUIDE_INSTALLATION_WINDOWS.md
├── GUIDE_USB_PORTABLE.md           <-- Le présent guide
├── requirements.txt
│
├── venv\                           <-- Environnement Python autonome (sur la clé)
│
├── sanctuary_app\                  <-- Code des Applications
│   ├── app.py                      <-- Sanctuary Backup & Exploration
│   ├── apptrait.py                 <-- Qualification Anti-Spam & Soldes
│   └── modules/
│       ├── schema.py
│       ├── sanctuary_manager.py
│       ├── fx_collector.py
│       ├── blockscout_collector.py
│       ├── csv_importer.py
│       ├── analytics_engine.py
│       └── trait_manager.py
│
├── sanctuary/                      <-- Dossier Sanctuarisé BRUT (Lecture seule)
└── trait_legit/                    <-- Dossier de Travail QUALIFIÉ (Duplication isolée)
```

---

## 3. ÉTAPES D'INSTALLATION DE LA CLÉ USB PORTABLE

### Étape 1 : Copier les fichiers sur la clé USB
- Branchez votre clé USB sur votre PC (ex: `E:\`).
- Copiez le dossier `SanctuaryApp` complet sur la clé USB.

### Étape 2 : Créer l'environnement Python portable sur la clé USB (Une seule fois)
- Ouvrez l'invite de commande (`cmd.exe`) et déplacez-vous sur la clé USB :
  ```cmd
  E:
  cd SanctuaryApp
  ```
- Créez l'environnement virtuel directement sur la clé :
  ```cmd
  python -m venv venv
  ```
- Activez et installez les dépendances sur la clé USB :
  ```cmd
  venv\Scripts\activate
  pip install -r requirements.txt
  ```

---

## 4. UTILISATION AU QUOTIDIEN (LANCEMENT EN UN CLIC)

Chaque fois que vous branchez votre clé USB sur un PC Windows :

1. Ouvrez le dossier `SanctuaryApp` situé sur votre clé USB.
2. **Double-cliquez simplement sur `lancer_sanctuary_usb.bat`** pour démarrer l'application.
3. **Script de secours (`lancer_viderCaches.bat`)** : Si vous rencontrez un blocage de cache Python ou après une modification de code, double-cliquez sur `lancer_viderCaches.bat` pour remettre à neuf le cache Python et Streamlit de la clé USB.

---

## 5. CONSEILS ET BONNES PRATIQUES POUR LA CLÉ USB

- **Type de Clé USB** : Utilisez de préférence une clé USB 3.0/3.1 ou un petit SSD externe USB-C/USB-A pour des vitesses de lecture/écriture rapides.
- **Sauvegarde de la Clé (Backup)** : Conservez régulièrement une copie de secours du dossier `sanctuary/` de votre clé USB sur un autre support sécurisé.
