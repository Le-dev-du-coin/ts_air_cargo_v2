import logging
from decimal import Decimal
from django.db.models import Sum, Q, F, Case, When, Value, DecimalField, Subquery, OuterRef
from django.db.models.functions import Coalesce
from django.utils import timezone
from core.models import Colis, Lot, AvoirMouvement, EncaissementColis, AvanceSalaire
from report.models import Depense, TransfertArgent, PaiementAgent

logger = logging.getLogger(__name__)

class FinanceEngine:
    """
    Moteur financier centralisé pour le calcul de la performance (Bénéfice) 
    et de la trésorerie (Caisse).
    """

    @staticmethod
    def get_daily_summary(target_date, country):
        """
        Calcule les flux financiers pour une journée spécifique dans un pays donné.
        Utilisé pour le Dashboard Mali et les rapports journaliers.
        """
        # 1. ENTRÉES DE CAISSE (Liquidités entrantes)
        # On compte les encaissements de colis RÉELS du jour (hors méthode AVANCE pour éviter les doublons)
        encaissements_jour = EncaissementColis.objects.filter(
            date=target_date,
            colis__lot__destination=country
        ).exclude(methode="AVANCE")

        total_encaissements_colis = encaissements_jour.aggregate(total=Sum("montant"))["total"] or 0

        # On compte les rechargements de portefeuille (DEPOT) du jour
        rechargements_avoir = AvoirMouvement.objects.filter(
            created_at__date=target_date,
            client__country=country,
            type="DEPOT"
        )
        total_rechargements_avoir = rechargements_avoir.aggregate(total=Sum("montant"))["total"] or 0

        total_entrees_jour = Decimal(total_encaissements_colis) + Decimal(total_rechargements_avoir)

        # 2. SORTIES DE CAISSE (Liquidités sortantes)
        # Dépenses réelles du pays (exclut les indicatives Chine)
        depenses_jour = Depense.objects.filter(
            date=target_date,
            pays=country,
            is_china_indicative=False
        )
        total_depenses = depenses_jour.aggregate(total=Sum("montant"))["total"] or 0

        # Transferts sortants
        transferts_jour = TransfertArgent.objects.filter(
            date=target_date,
            pays_expediteur=country
        )
        total_transferts = transferts_jour.aggregate(total=Sum("montant"))["total"] or 0

        # Paiements Agents (Salaires/Avances payés aujourd'hui)
        paiements_agents = PaiementAgent.objects.filter(
            date_paiement__date=target_date,
            agent__country=country
        )
        total_paiements_agents = paiements_agents.aggregate(total=Sum("montant"))["total"] or 0

        total_sorties_jour = Decimal(total_depenses) + Decimal(total_transferts) + Decimal(total_paiements_agents)

        # 3. SOLDE VEILLE (Calcul)
        # Recettes cumulées avant aujourd'hui
        recettes_avant = EncaissementColis.objects.filter(
            date__lt=target_date,
            colis__lot__destination=country
        ).exclude(methode="AVANCE").aggregate(total=Sum("montant"))["total"] or 0
        
        depôts_avant = AvoirMouvement.objects.filter(
            created_at__date__lt=target_date,
            client__country=country,
            type="DEPOT"
        ).aggregate(total=Sum("montant"))["total"] or 0
        
        # Sorties cumulées avant aujourd'hui
        depenses_avant = Depense.objects.filter(
            date__lt=target_date,
            pays=country,
            is_china_indicative=False
        ).aggregate(total=Sum("montant"))["total"] or 0
        
        transferts_avant = TransfertArgent.objects.filter(
            date__lt=target_date,
            pays_expediteur=country
        ).aggregate(total=Sum("montant"))["total"] or 0
        
        paiements_agents_avant = PaiementAgent.objects.filter(
            date_paiement__date__lt=target_date,
            agent__country=country
        ).aggregate(total=Sum("montant"))["total"] or 0

        solde_veille = (Decimal(recettes_avant) + Decimal(depôts_avant)) - \
                       (Decimal(depenses_avant) + Decimal(transferts_avant) + Decimal(paiements_agents_avant))

        return {
            "total_recettes_jour": total_entrees_jour,
            "total_encaissements_colis": total_encaissements_colis,
            "total_rechargements_avoir": total_rechargements_avoir,
            "total_sorties_jour": total_sorties_jour,
            "total_depenses": total_depenses,
            "total_transferts": total_transferts,
            "total_paiements_agents": total_paiements_agents,
            "solde_veille": solde_veille,
            "solde_caisse_actuel": solde_veille + total_entrees_jour - total_sorties_jour,
            "rechargements_list": rechargements_avoir,
            "depenses_list": depenses_jour,
            "transferts_list": transferts_jour,
        }

    @staticmethod
    def get_monthly_performance(year, month, country_code):
        """
        Calcule la performance économique (Bénéfice) pour un mois.
        Utilisé pour l'Admin Chine et les archives mensuelles.
        """
        # 1. CHIFFRE D'AFFAIRES (Recettes théoriques basées sur les arrivées)
        date_filter = {"lot__date_arrivee__year": year, "lot__date_arrivee__month": month}
        if country_code == "CN":
            date_filter = {"lot__date_expedition__year": year, "lot__date_expedition__month": month}
            
        colis_periode = Colis.objects.filter(lot__destination__code=country_code).filter(**date_filter)
        lots_periode = Lot.objects.filter(destination__code=country_code).filter(
            date_arrivee__year=year, date_arrivee__month=month
        ) if country_code != "CN" else Lot.objects.filter(date_expedition__year=year, date_expedition__month=month)

        ca_brut = colis_periode.aggregate(total=Sum("prix_final"))["total"] or 0
        total_jc = colis_periode.aggregate(total=Sum("montant_jc"))["total"] or 0
        ca_net = Decimal(ca_brut) - Decimal(total_jc)

        # 2. COÛTS DIRECTS (Fret + Douane)
        total_fret = lots_periode.aggregate(total=Sum("frais_transport"))["total"] or 0
        total_douane = lots_periode.aggregate(total=Sum("frais_douane"))["total"] or 0
        benefice_brut = ca_net - Decimal(total_fret) - Decimal(total_douane)

        # 3. CHARGES D'EXPLOITATION (Dépenses + RH)
        depenses_exploit = Depense.objects.filter(
            pays__code=country_code, 
            date__year=year, 
            date__month=month,
            is_china_indicative=False
        ).aggregate(total=Sum("montant"))["total"] or 0

        avances_rh = AvanceSalaire.objects.filter(
            agent__country__code=country_code,
            date__year=year,
            date__month=month
        ).aggregate(total=Sum("montant"))["total"] or 0
        
        salaires_rh = PaiementAgent.objects.filter(
            agent__country__code=country_code,
            periode_annee=year,
            periode_mois=month
        ).aggregate(total=Sum("montant"))["total"] or 0

        total_charges = Decimal(depenses_exploit) + Decimal(avances_rh) + Decimal(salaires_rh)
        benefice_net = benefice_brut - total_charges

        # 4. DÉTAILS AVION / BATEAU
        colis_avion = colis_periode.filter(lot__type_transport__in=["CARGO", "EXPRESS"])
        colis_bateau = colis_periode.filter(lot__type_transport="BATEAU")
        lots_avion = lots_periode.filter(type_transport__in=["CARGO", "EXPRESS"])
        lots_bateau = lots_periode.filter(type_transport="BATEAU")

        ca_avion = (colis_avion.aggregate(total=Sum("prix_final"))["total"] or 0) - (colis_avion.aggregate(total=Sum("montant_jc"))["total"] or 0)
        ca_bateau = (colis_bateau.aggregate(total=Sum("prix_final"))["total"] or 0) - (colis_bateau.aggregate(total=Sum("montant_jc"))["total"] or 0)
        
        brut_avion = Decimal(ca_avion) - (lots_avion.aggregate(total=Sum("frais_transport"))["total"] or 0) - (lots_avion.aggregate(total=Sum("frais_douane"))["total"] or 0)
        brut_bateau = Decimal(ca_bateau) - (lots_bateau.aggregate(total=Sum("frais_transport"))["total"] or 0) - (lots_bateau.aggregate(total=Sum("frais_douane"))["total"] or 0)

        return {
            "chiffre_affaires": ca_net,
            "cout_fret": total_fret,
            "cout_douane": total_douane,
            "benefice_brut": benefice_brut,
            "total_depenses": depenses_exploit,
            "total_rh": avances_rh + salaires_rh,
            "benefice_net": benefice_net,
            "nb_colis": colis_periode.count(),
            "nb_lots": lots_periode.count(),
            "ca_avion": ca_avion,
            "ca_bateau": ca_bateau,
            "benefice_brut_avion": brut_avion,
            "benefice_brut_bateau": brut_bateau,
            "nb_colis_avion": colis_avion.count(),
            "nb_colis_bateau": colis_bateau.count(),
            "nb_colis_livres_avion": colis_avion.filter(status="LIVRE").count(),
            "nb_colis_livres_bateau": colis_bateau.filter(status="LIVRE").count(),
            "poids_total": colis_periode.aggregate(total=Sum("poids"))["total"] or 0,
        }
