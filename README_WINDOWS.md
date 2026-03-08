# Guide de résolution "Accès Refusé" sur Windows 11

Si vous rencontrez l'erreur "Accès refusé" lors du lancement de `python` ou `streamlit`, suivez ces étapes dans l'ordre :

### 1. Désactiver les Alias d'exécution (Cause n°1)
Windows 11 redirige parfois `python.exe` vers le Microsoft Store, ce qui provoque ce blocage.
1. Ouvrez les **Paramètres** de Windows.
2. Allez dans **Applications** > **Applications installées** > **Paramètres avancés des applications** > **Alias d'exécution d'application**.
3. Recherchez `python.exe`, `python3.exe` et `pythonw.exe` dans la liste.
4. **Désactivez TOUS les curseurs** correspondants.

### 2. Débloquer le fichier de script
Windows peut bloquer les fichiers `.py` téléchargés ou créés par des outils tiers.
1. Allez dans votre dossier `outpart`.
2. Faites un clic droit sur `1recolte.py` > **Propriétés**.
3. En bas de l'onglet **Général**, si vous voyez une zone "Sécurité" avec une case **"Débloquer"**, cochez-la et validez.

### 3. Réparer les permissions du dossier Python
Si vous utilisez la version installée dans `AppData`, les droits peuvent être corrompus.
1. Allez dans `C:\Users\Pp\AppData\Local\Programs\Python\`.
2. Faites un clic droit sur le dossier `Python312` > **Propriétés**.
3. Allez dans l'onglet **Sécurité** > bouton **Avancé**.
4. Cochez la case en bas : **"Remplacer toutes les entrées d'autorisation des objets enfants par des entrées d'autorisation héritables de cet objet"**.
5. Cliquez sur **OK** et patientez.

### 4. Créer une exception Antivirus
Si vous utilisez Windows Defender ou un Antivirus tiers :
1. Ouvrez votre logiciel de sécurité.
2. Ajoutez le dossier `C:\jules-c\outpart\` à la liste des **Exclusions**.
3. Ajoutez également l'exécutable `C:\Users\Pp\AppData\Local\Programs\Python\Python312\python.exe` aux exclusions.

### 5. Utiliser le Lanceur de Secours
Créez un fichier texte nommé `Lancer.bat` dans votre dossier de travail avec ce contenu :

```batch
@echo off
cd /d "%~dp0"
"C:\Users\Pp\AppData\Local\Programs\Python\Python312\python.exe" -m streamlit run 1recolte.py
pause
```

Double-cliquez sur ce fichier pour lancer l'application.
