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
from django.db.models import Sum, Max

def main():
    print("=== DIAGNOSTIC DES DATES DE PAIEMENT DES COLIS ARRIVE PAYES ===")
    
    colis_payes_arrive = Colis.objects.filter(status="ARRIVE", est_paye=True)
    print(f"Nombre total de colis ARRIVE et payes : {colis_payes_arrive.count()}\n")
    
    for c in colis_payes_arrive.annotate(date_dernier_encaissement=Max("encaissements__date")):
        date_enc = c.date_dernier_encaissement
        # Si pas d'encaissement physique (legacy ou JC direct), regarder date_encaissement
        if not date_enc:
            date_enc = c.date_encaissement
            
        print(f"- Ref: {c.reference} | Client: {c.client} | Date Paiement: {date_enc} | Lot: {c.lot.numero} | Statut: {c.status}")

if __name__ == '__main__':
    main()
