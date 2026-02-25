import os
import subprocess
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive


class Command(BaseCommand):
    help = "Exécute un dump de la BDD PostgreSQL et l'envoie vers Google Drive"

    def handle(self, *args, **kwargs):
        # 1. Génération du nom de fichier
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        db_name = settings.DATABASES["default"]["NAME"]
        db_user = settings.DATABASES["default"]["USER"]
        db_host = settings.DATABASES["default"].get("HOST", "localhost")
        db_port = settings.DATABASES["default"].get("PORT", "5432")
        db_pass = settings.DATABASES["default"].get("PASSWORD", "")

        filename = f"tsaircargo_backup_{db_name}_{date_str}.sql.gz"
        filepath = os.path.join(settings.BASE_DIR, filename)

        self.stdout.write(
            self.style.WARNING(f"🚀 Début du backup PostgreSQL (Fichier : {filename})")
        )

        # 2. Exécution du pg_dump en compressant avec gzip
        env = os.environ.copy()
        env["PGPASSWORD"] = str(db_pass)

        # Le pipe avec gzip permet de gagner 80% d'espace
        dump_command = f"pg_dump -h {db_host} -U {db_user} -p {db_port} -d {db_name} | gzip > {filepath}"

        try:
            self.stdout.write(
                "Génération de l'archive SQL (cela peut prendre quelques secondes)..."
            )
            subprocess.run(dump_command, env=env, shell=True, check=True)
            self.stdout.write(
                self.style.SUCCESS(f"✅ Backup local réussi : {filepath}")
            )
        except subprocess.CalledProcessError as e:
            self.stderr.write(
                self.style.ERROR(f"❌ Erreur critique lors du pg_dump : {e}")
            )
            return

        # 3. Connexion au Google Drive
        self.stdout.write(self.style.WARNING("☁️  Connexion à Google Drive..."))
        try:
            gauth = GoogleAuth()

            # Essai de chargement du jeton existant (mycreds.txt)
            gauth.LoadCredentialsFile("mycreds.txt")

            if gauth.credentials is None:
                # S'il n'y a pas de jeton, on invite l'utilisateur
                # En VPS (mode console sans UI), il faut utiliser CommandLineAuth()
                self.stdout.write(
                    self.style.ERROR("⚠️ Aucun jeton (mycreds.txt) trouvé.")
                )
                self.stdout.write(
                    self.style.WARNING(
                        "Veuillez configurer 'client_secrets.json' à la racine et exécuter ce script manuellement une première fois pour générer le lien d'autorisation."
                    )
                )
                gauth.CommandLineAuth()
            elif gauth.access_token_expired:
                # Rafraîchir le token automatiquement
                gauth.Refresh()
            else:
                # S'authentifier avec
                gauth.Authorize()

            # Sauvegarder/mettre à jour le token
            gauth.SaveCredentialsFile("mycreds.txt")

            drive = GoogleDrive(gauth)

            # 4. Upload
            self.stdout.write(
                self.style.WARNING("⬆️  Upload du fichier vers Google Drive en cours...")
            )

            # Optionnel : Si vous avez un ID de dossier spécifique sur Drive (folder_id)
            # folder_id = "1AbcDefGhIjKlMnOpQrStUvWxYz"
            # gfile = drive.CreateFile({'title': filename, 'parents': [{'id': folder_id}]})

            gfile = drive.CreateFile({"title": filename})
            gfile.SetContentFile(filepath)
            gfile.Upload()

            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ Upload Drive réussi ! Fichier Drive ID : {gfile['id']}"
                )
            )

            # 5. Nettoyage local du serveur
            os.remove(filepath)
            self.stdout.write(
                self.style.SUCCESS("🧹 Fichier temporaire local supprimé.")
            )

        except Exception as e:
            self.stderr.write(
                self.style.ERROR(
                    f"❌ Erreur lors de la communication avec Google Drive : {e}"
                )
            )
            self.stderr.write(
                self.style.WARNING(
                    f"💾 Pour des raisons de sécurité, le backup SQL a été conservé sur le serveur à l'emplacement : {filepath}"
                )
            )
