#!/bin/bash
# Script de Déploiement Production (TS Air Cargo V2)
set -e # Arrête le script dès la première erreur

echo "====================================="
echo "🚀 Déploiement de TS Air Cargo V2..."
echo "====================================="

echo "1. Téléchargement des dernières mises à jour GitHub..."
git pull origin master

echo "2. Installation des dépendances Python (Poetry)..."
poetry install --only main --no-interaction --no-ansi

echo "3. Compilation des assets Tailwind CSS..."
npm run build --prefix ./theme/static_src

echo "4. Exécution des migrations BDD (PostgreSQL)..."
poetry run python manage.py migrate --noinput

echo "5. Collecte des fichiers statiques..."
poetry run python manage.py collectstatic --noinput

echo "6. Redémarrage des services systèmes..."
# Modifiez ces noms selon votre configuration Systemd
sudo systemctl restart gunicorn
sudo systemctl restart daphne
sudo systemctl restart celery

echo "✅ Déploiement terminé avec succès."
