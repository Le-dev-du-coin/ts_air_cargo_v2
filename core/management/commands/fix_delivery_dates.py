"""
Commande de migration sécurisée pour assigner la date de livraison manquante
aux colis LIVRE qui n'en ont pas.

Utilisation :
    Dry-run (simulation, aucune modification) :
        poetry run python manage.py fix_delivery_dates --dry-run

    Exécution réelle (applique les changements) :
        poetry run python manage.py fix_delivery_dates
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Colis
from django.db.models import Q


class Command(BaseCommand):
    help = "Assigne date_livraison = updated_at pour les colis LIVRE sans date de livraison."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulation uniquement : affiche les colis concernés sans rien modifier.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Trouver tous les colis LIVRE sans date_livraison (ni date_encaissement)
        qs = Colis.objects.filter(
            status="LIVRE",
            date_livraison__isnull=True,
        )

        total = qs.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS("✅ Aucun colis à corriger. Base de données déjà propre."))
            return

        self.stdout.write(self.style.WARNING(f"\n📦 {total} colis LIVRE sans date_livraison trouvés.\n"))

        # Afficher un aperçu des 10 premiers
        self.stdout.write("── Aperçu (10 premiers) ──")
        for c in qs[:10]:
            self.stdout.write(
                f"  - {c.reference} | Client: {c.client} | "
                f"updated_at: {c.updated_at.date() if c.updated_at else 'N/A'}"
            )
        if total > 10:
            self.stdout.write(f"  ... et {total - 10} autres.\n")

        if dry_run:
            self.stdout.write(
                self.style.NOTICE(
                    "\n⚠️  MODE DRY-RUN : Aucune modification effectuée.\n"
                    "    Pour appliquer les changements, relancez sans --dry-run.\n"
                )
            )
            return

        # Confirmation manuelle en production
        self.stdout.write(
            self.style.WARNING(
                f"\n⚠️  ATTENTION : Vous êtes sur le point de modifier {total} colis en base de données.\n"
                "    Cette opération est irréversible sans sauvegarde préalable.\n"
            )
        )
        confirm = input("    Tapez 'OUI' pour confirmer et exécuter : ")
        if confirm.strip() != "OUI":
            self.stdout.write(self.style.ERROR("❌ Annulé. Aucune modification effectuée."))
            return

        # Exécution atomique (tout ou rien)
        try:
            with transaction.atomic():
                updated_count = 0
                for colis in qs.iterator(chunk_size=500):
                    if colis.updated_at:
                        colis.date_livraison = colis.updated_at.date()
                        colis.save(update_fields=["date_livraison"])
                        updated_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✅ Succès ! {updated_count} colis ont reçu une date_livraison "
                    f"(identique à leur updated_at).\n"
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"\n❌ ERREUR - Aucune modification n'a été sauvegardée.\n    Détail: {e}")
            )
