# Résolution de l'erreur "Accès refusé" sur Windows 11

Si vous obtenez "Accès refusé" en lançant Streamlit, suivez ces étapes dans l'ordre :

### 1. Désactiver les Alias d'exécution (Cause n°1 - CRITIQUE)
Windows 11 intercepte parfois les commandes `python` avec des alias vides (liens vers le Microsoft Store) au lieu de votre installation Python 3.12.
- Ouvrez le menu **Démarrer** et tapez **"Alias d'exécution"** (ou "Manage app execution aliases").
- Cherchez **python.exe** et **python3.exe** dans la liste.
- **Décochez-les tous** (mettez-les sur "Désactivé").
- **Redémarrez votre terminal (CMD ou PowerShell)**.

### 2. Utiliser le fichier de lancement automatique (`lancer_1recolte.bat`)
J'ai créé un fichier nommé `lancer_1recolte.bat` dans votre dossier.
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
**Note technique :** L'erreur vient généralement du fait que Windows essaie de lancer une version du Microsoft Store (alias) au lieu de votre installation Python 3.12 officielle.
