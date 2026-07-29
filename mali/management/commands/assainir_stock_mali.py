from django.core.management.base import BaseCommand
from django.db.models import Q
from core.models import Colis, Country

class Command(BaseCommand):
    help = "Assainit le stock magasin Mali en ré-attribuant le statut LIVRE aux anciens colis payés ou déjà livrés."

    def handle(self, *args, **options):
        mali = Country.objects.filter(code="ML").first()
        if not mali:
            self.stdout.write(self.style.ERROR("Pays Mali non trouvé."))
            return

        # 1. Colis ayant un encaissement ou un mouvement d'avoir/garantie ou une date_livraison mais un statut non LIVRE
        colis_a_corriger = Colis.objects.filter(
            lot__destination=mali
        ).exclude(status="LIVRE").filter(
            Q(encaissements__isnull=False) |
            Q(date_livraison__isnull=False) |
            Q(date_encaissement__isnull=False) |
            Q(est_paye=True) |
            Q(paye_par_avance=True) |
            Q(sortie_sous_garantie=True)
        ).distinct()

        count = colis_a_corriger.count()
        self.stdout.write(f"Trouvé {count} colis à assainir dans le stock Mali...")

        updated = 0
        for colis in colis_a_corriger:
            colis.status = "LIVRE"
            colis.reste_a_payer = 0
            colis.est_paye = True
            colis.save()
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"Succès ! {updated} colis du stock Mali ont été passés en statut LIVRE."))
