import os
import sys
import django
from decimal import Decimal
from django.utils import timezone

# Configuration de Django
sys.path.append('/Users/sanogodev/Documents/MDS/Projets/TS Air Cargo/ts_air_cargo_v2')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()

from core.models import Colis, EncaissementColis
from django.db.models import Sum

def main():
    print("=== DIAGNOSTIC DES COLIS DANS L'ENTREPOT ===")
    
    # 1. Colis au statut ARRIVE mais payés (est_paye=True)
    colis_payes_arrive = Colis.objects.filter(status="ARRIVE", est_paye=True)
    print(f"Colis au statut ARRIVE et payes (pret pour retrait) : {colis_payes_arrive.count()}")
    for c in colis_payes_arrive[:15]:
        print(f"  - Ref: {c.reference} | Client: {c.client} | Reste a payer: {c.reste_a_payer} | Mis a jour: {c.updated_at}")
        
    # 2. Colis au statut ARRIVE mais qui ont un reste a payer à 0
    colis_reste_zero = Colis.objects.filter(status="ARRIVE", reste_a_payer=0, est_paye=False)
    print(f"\nColis au statut ARRIVE, reste a payer = 0 mais est_paye=False : {colis_reste_zero.count()}")
    for c in colis_reste_zero[:15]:
        print(f"  - Ref: {c.reference} | Client: {c.client} | Mis a jour: {c.updated_at}")

    # 3. Y a-t-il des colis au statut ARRIVE qui ont une date de livraison ou de retrait ?
    colis_avec_date_livraison = Colis.objects.filter(status="ARRIVE", date_livraison__isnull=False)
    print(f"\nColis au statut ARRIVE ayant une date de livraison renseignee : {colis_avec_date_livraison.count()}")
    for c in colis_avec_date_livraison[:15]:
        print(f"  - Ref: {c.reference} | Client: {c.client} | Date livraison: {c.date_livraison}")

    # 4. Y a-t-il des colis au statut ARRIVE qui ont fait l'objet d'un encaissement complet ?
    print("\n=== FIN DU DIAGNOSTIC ===")

if __name__ == '__main__':
    main()
