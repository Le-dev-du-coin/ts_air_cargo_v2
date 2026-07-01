import os
import sys
import django
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

# Configuration de Django
sys.path.append('/Users/sanogodev/Documents/MDS/Projets/TS Air Cargo/ts_air_cargo_v2')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()

from core.models import Colis
from django.db.models import Max

def main():
    print("=== ANALYSE DES COLIS PAYES NON RETIRES ===")
    
    limite_date = timezone.now().date() - timedelta(days=3)
    print(f"Date limite de diagnostic (il y a 3 jours) : {limite_date}\n")
    
    colis_payes_arrive = Colis.objects.filter(status="ARRIVE", est_paye=True)
    
    a_livrer_count = 0
    recent_count = 0
    
    for c in colis_payes_arrive.annotate(date_dernier_encaissement=Max("encaissements__date")):
        date_enc = c.date_dernier_encaissement
        if not date_enc:
            date_enc = c.date_encaissement
        
        # Si la date de paiement est introuvable, on la considère comme ancienne par sécurité
        if not date_enc or date_enc < limite_date:
            a_livrer_count += 1
            if a_livrer_count <= 20:
                print(f"  - [A LIVRER] Ref: {c.reference} | Client: {c.client} | Date Paiement: {date_enc} | Lot: {c.lot.numero}")
        else:
            recent_count += 1
            
    print(f"\nNombre de colis payes il y a plus de 3 jours (a marquer LIVRES) : {a_livrer_count}")
    print(f"Nombre de colis payes recemment (a conserver en stock) : {recent_count}")

if __name__ == '__main__':
    main()
