from django.core.management.base import BaseCommand
from core.models import Colis, EncaissementColis
from django.db.models import F
from django.utils import timezone

class Command(BaseCommand):
    help = "Migre les données de paiement existantes vers le modèle EncaissementColis"

    def handle(self, *args, **options):
        # On cherche les colis qui ont déjà été payés (totalement ou partiellement)
        # Mais qui n'ont pas encore d'enregistrements dans EncaissementColis
        colis_paid = Colis.objects.filter(
            encaissements__isnull=True
        ).annotate(
            paid_amount=F('prix_final') - F('montant_jc') - F('reste_a_payer')
        ).filter(paid_amount__gt=0)

        self.stdout.write(f"Trouvé {colis_paid.count()} colis à migrer.")

        encaissements_to_create = []
        for c in colis_paid:
            # Utiliser date_encaissement, ou date_livraison, ou created_at
            date_p = c.date_encaissement or c.date_livraison or c.created_at.date()
            
            encaissements_to_create.append(
                EncaissementColis(
                    colis=c,
                    montant=c.paid_amount,
                    date=date_p,
                    methode=c.mode_paiement or "ESPECE",
                    enregistre_par=c.lot.created_by # Repli sur le créateur du lot
                )
            )

        if encaissements_to_create:
            EncaissementColis.objects.bulk_create(encaissements_to_create)
            self.stdout.write(self.style.SUCCESS(f"Succès : {len(encaissements_to_create)} encaissements créés."))
        else:
            self.stdout.write("Aucun encaissement à créer.")
