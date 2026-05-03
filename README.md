1. Préparer l'environnement (Commun aux deux) ⭐
   
Avant de compiler, assure-toi que ton script fonctionne et que les bibliothèques nécessaires sont installées dans ton environnement :
pip install pygame numpy pyinstaller

2. Compiler sur Windows (.exe) ⭐
   
Sous Windows, PyInstaller va créer un fichier exécutable autonome.

Ouvre un Terminal (PowerShell ou CMD) dans le dossier de ton script.

Lance la commande suivante :pyinstaller --noconsole --onefile --name "NexusSimulator" horizon_noir.py

Explication des options :

--noconsole : Empêche une fenêtre de commande noire de s'ouvrir en arrière-plan pendant que tu joues. ⭐

--onefile : Paquette tout (Python + Pygame + ton code) dans un seul fichier .exe.

--name : Donne le nom que tu veux à l'exécutable.

Résultat : Une fois terminé, ton jeu se trouvera dans un nouveau dossier nommé dist/.

3. Compiler sur Linux (Binaire) ⭐
   
Sur Linux, le processus est identique, mais le résultat sera un fichier binaire exécutable (sans extension .exe).

Ouvre ton terminal dans le dossier du projet.

Lance la même commande :
pyinstaller --noconsole --onefile --name "NexusSimulator" nexus.py

Une fois la compilation finie dans le dossier dist/, vous devez parfois donner les droits d'exécution au fichier: chmod +x dist/NexusSimulator
./dist/NexusSimulator
