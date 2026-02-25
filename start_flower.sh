#!/bin/bash
# Lancement de Celery Flower pour le monitoring du backend TS Air Cargo
echo "Démarrage de Flower sur le port 5555..."

# Utilisation de nohup pour exécuter en arrière-plan et ne pas bloquer le terminal
nohup poetry run celery -A config flower --port=5555 > flower.log 2>&1 &

echo "✅ Flower s'exécute en arrière-plan ! Vous pouvez fermer ce terminal."
echo "Les logs sont disponibles dans le fichier 'flower.log'."
