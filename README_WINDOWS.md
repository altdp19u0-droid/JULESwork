# Résolution de l'erreur "Accès refusé" sur Windows 11

Si vous obtenez "Accès refusé" en lançant Streamlit, suivez ces étapes dans l'ordre :

### 1. Désactiver les Alias d'exécution (Cause n°1 - CRITIQUE)
Windows 11 intercepte parfois les commandes `python` avec des alias vides (liens vers le Microsoft Store) au lieu de votre installation Python 3.12.
- Ouvrez le menu **Démarrer** et tapez **"Alias d'exécution"** (ou "Manage app execution aliases").
- Cherchez **TOUTES** les lignes contenant **python**, **python3**, **pip**, **streamlit**.
- **Décochez-les toutes** (mettez-les sur "Désactivé").
- **Redémarrez votre ordinateur** (certains alias restent en cache mémoire).

### 1b. Erreur "%1 n'est pas une application Win32 valide"
Cette erreur signifie que le fichier `python.exe` est soit corrompu (0 Ko), soit bloqué par un antivirus.
- Allez dans `C:\Users\Pp\AppData\Local\Programs\Python\Python312\`
- Vérifiez la taille de `python.exe`. S'il fait **0 Ko**, votre installation est cassée : **Désinstallez et réinstallez Python 3.12**.

### 2. Utiliser le fichier de lancement automatique (`lanceur_1recolte.bat`)
J'ai créé un fichier nommé `lanceur_1recolte.bat` dans votre dossier.
- Faites un **clic droit** dessus et choisissez **"Exécuter en tant qu'administrateur"**.
- Cela forcera les droits d'accès nécessaires.

### 3. Vérifier les permissions du dossier
Assurez-vous que votre utilisateur a les droits complets sur le dossier `C:\jules-c\outpart\`.
- Faites un clic droit sur le dossier `outpart`.
- Propriétés > Sécurité.
- Vérifiez que "Utilisateurs authentifiés" ou votre nom d'utilisateur a le "Contrôle total".

### 4. Vérifier l'Antivirus
Parfois, Windows Defender bloque le lancement de scripts Python téléchargés ou créés par un agent.
- Vérifiez dans l'Historique de protection de Windows Defender si une action a été bloquée récemment.

---
## Cas particulier : `where python` affiche `C:\Windows\System32\python`

Si votre commande `where python` renvoie ce chemin, c'est que Windows a activé un **leurre** (Alias).
Ce leurre ne contient pas Python mais ouvre le Microsoft Store, ce qui provoque l'erreur **"Accès refusé"** quand on essaie de l'utiliser en ligne de commande.

### La Solution Permanente :
1. Allez dans **Paramètres** > **Applications** > **Paramètres d'application avancés** > **Alias d'exécution**.
2. Désactivez **"Installateur Python"** (python.exe et python3.exe).
3. Une fois désactivé, `where python` devrait afficher votre vrai chemin dans `AppData\Local\Programs\Python\Python312\`.

**Note technique :** Votre installation Python 3.12 locale est la seule valide. Le fichier `lanceur_1recolte.bat` est configuré pour ignorer le leurre de System32 et appeler directement votre vrai Python.

### Alerte : Conflit avec Python 3.14 (Scripts Pip)
Si des chemins vers **Python 3.14** réapparaissent dans votre `PATH` (ex: `AppData\Roaming\Python\Python314\Scripts`), cela va provoquer des erreurs "Accès Refusé" ou des conflits de modules.

**Action recommandée :**
1. Désinstallez proprement toute version de Python 3.14 via le Panneau de Configuration.
2. **Nettoyage Manuel (CRITIQUE) :** Supprimez les dossiers suivants s'ils existent :
   - `C:\Users\Pp\AppData\Roaming\Python\Python314\`
   - `C:\Users\Pp\AppData\Local\Python\Python314\` (si présent)
3. **Pourquoi ?** Si Pip reste lié à 3.14, il va continuer à créer des scripts qui pointent vers un interpréteur inexistant, ce qui recrée la ligne dans le PATH et cause des "Accès Refusés".

 ### 4. Réparer / Réinstaller Pip (Si `pip` n'est pas reconnu)
 Si la commande `pip` ne fonctionne toujours pas, ne réinstallez pas tout Windows. Utilisez la fonction d'auto-réparation de Python :
 1. Ouvrez un terminal (CMD) en Administrateur.
 2. Tapez cette commande pour restaurer Pip proprement sur la version 3.12 :
    `py -3.12 -m ensurepip --default-pip`
 3. Puis mettez-le à jour :
    `py -3.12 -m pip install --upgrade pip`

 ### 5. Réinstallation Propre des modules
   **Note :** N'utilisez pas la commande `pip` seule (elle est souvent cassée par les conflits). Utilisez toujours `py -3.12 -m pip`.

   Commande à copier/coller :
   `py -3.12 -m pip install --upgrade --force-reinstall streamlit pandas requests fpdf2`
