import os
import sys
import django
from decimal import Decimal
from django.utils import timezone
from django.db.models import Max

# Configuration de Django
sys.path.append('/Users/sanogodev/Documents/MDS/Projets/TS Air Cargo/ts_air_cargo_v2')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()

from core.models import Colis

def main():
    print("=== ARCHIVAGE DES COLIS LIVRES FANTOMES ===")
    
    colis_payes_arrive = Colis.objects.filter(status="ARRIVE", est_paye=True)
    print(f"Nombre total de colis payes a archiver : {colis_payes_arrive.count()}")
    
    compteur = 0
    for c in colis_payes_arrive.annotate(date_dernier_encaissement=Max("encaissements__date")):
        date_enc = c.date_dernier_encaissement
        if not date_enc:
            date_enc = c.date_encaissement
            
        # Si aucune date de paiement, on prend la date du jour
        date_livraison = date_enc if date_enc else timezone.now().date()
        
        c.status = "LIVRE"
        c.date_livraison = date_livraison
        c.save()
        compteur += 1
        print(f"  - [LIVRE] Ref: {c.reference} | Date Livraison attribuee: {date_livraison}")
        
    print(f"\n=== FIN DE L'ARCHIVAGE ===")
    print(f"Nombre total de colis passes au statut LIVRE : {compteur}")

if __name__ == '__main__':
    main()
