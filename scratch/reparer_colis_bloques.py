import os
import sys
import django
from decimal import Decimal

# Configuration de Django
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()

from core.models import Colis, EncaissementColis
from django.db.models import Sum

def main():
    print("=== REPARATION DES COLIS EN BASE DE DONNEES ===")
    
    colis_modifies = 0
    arrive_colis = Colis.objects.filter(status="ARRIVE")
    
    print(f"Total de colis au statut ARRIVE à vérifier : {arrive_colis.count()}")
    
    for c in arrive_colis:
        # 1. Calcul du montant total encaissé via EncaissementColis
        tot_enc = EncaissementColis.objects.filter(colis=c).aggregate(total=Sum("montant"))["total"] or Decimal("0")
        
        # 2. Calcul du reste à payer théorique
        prix_final = c.prix_final or Decimal("0")
        montant_jc = c.montant_jc or Decimal("0")
        reste_theorique = max(Decimal("0"), prix_final - montant_jc - tot_enc)
        est_paye_theorique = reste_theorique <= 0
        
        # 3. Comparaison avec les données actuelles
        needs_update = False
        updates_desc = []
        
        if c.reste_a_payer != reste_theorique:
            updates_desc.append(f"reste_a_payer: {c.reste_a_payer} -> {reste_theorique}")
            c.reste_a_payer = reste_theorique
            needs_update = True
            
        if c.est_paye != est_paye_theorique:
            updates_desc.append(f"est_paye: {c.est_paye} -> {est_paye_theorique}")
            c.est_paye = est_paye_theorique
            needs_update = True
            
        if needs_update:
            colis_modifies += 1
            c.save()
            print(f"  - [CORRIGE] Ref: {c.reference} | Client: {c.client} | Modifs: {', '.join(updates_desc)}")
            
    print(f"\n=== FIN DE LA REPARATION ===")
    print(f"Nombre total de colis mis à jour : {colis_modifies}")

if __name__ == '__main__':
    main()
