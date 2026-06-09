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

        total_encaissements_colis_reels = encaissements_jour.aggregate(total=Sum("montant"))["total"] or 0

        # On ajoute les encaissements "Legacy" (anciens colis sans objets EncaissementColis)
        # Un colis est considéré legacy s'il a une date_encaissement mais AUCUN objet EncaissementColis lié.
        legacy_encaissements_jour = Colis.objects.filter(
            date_encaissement=target_date,
            lot__destination=country,
            encaissements__isnull=True
        ).annotate(
            net_val=F("prix_final") - Coalesce(F("montant_jc"), Value(0), output_field=DecimalField())
        ).aggregate(total=Sum("net_val"))["total"] or 0

        total_encaissements_colis = Decimal(total_encaissements_colis_reels) + Decimal(legacy_encaissements_jour)

        # On compte les rechargements de portefeuille (DEPOT) du jour
        rechargements_avoir = AvoirMouvement.objects.filter(
            created_at__date=target_date,
            client__country=country,
            type="DEPOT"
        )
        total_rechargements_avoir = rechargements_avoir.aggregate(total=Sum("montant"))["total"] or 0

        total_entrees_jour = Decimal(total_encaissements_colis) + Decimal(total_rechargements_avoir)

        # 2. SORTIES DE CAISSE (Liquidités sortantes)
        # Dépenses réelles du pays (exclut les indicatives Chine ET celles saisies par le staff Chine)
        depenses_jour = Depense.objects.filter(
            date=target_date,
            pays=country,
            is_china_indicative=False
        ).exclude(enregistre_par__role__in=["ADMIN_CHINE", "AGENT_CHINE"])
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
        recettes_reelles_avant = EncaissementColis.objects.filter(
            date__lt=target_date,
            colis__lot__destination=country
        ).exclude(methode="AVANCE").aggregate(total=Sum("montant"))["total"] or 0
        
        # Recettes Legacy : On prend ce qui a une date_encaissement < target_date
        # ET les "Ghost payments" (colis payés mais sans aucune date ni objet encaissement)
        legacy_recettes_avant = Colis.objects.filter(
            Q(date_encaissement__lt=target_date) | Q(est_paye=True, date_encaissement__isnull=True),
            lot__destination=country,
            encaissements__isnull=True
        ).annotate(
            net_val=F("prix_final") - Coalesce(F("montant_jc"), Value(0), output_field=DecimalField())
        ).aggregate(total=Sum("net_val"))["total"] or 0

        recettes_avant = Decimal(recettes_reelles_avant) + Decimal(legacy_recettes_avant)
        
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
        ).exclude(enregistre_par__role__in=["ADMIN_CHINE", "AGENT_CHINE"]).aggregate(total=Sum("montant"))["total"] or 0
        
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
        Calcule la performance économique (Bénéfice) pour une période.
        Utilisé pour l'Admin Chine et les archives mensuelles.
        """
        # 1. CHIFFRE D'AFFAIRES (Recettes locales basées sur les arrivées)
        # On ne compte que les colis qui ne sont PAS payés en Chine car c'est la performance locale
        date_filter_colis = {}
        date_filter_lots = {}

        if year and month and str(year) != "all" and str(month) != "all":
            if country_code == "CN":
                date_filter_colis = {"lot__date_expedition__year": year, "lot__date_expedition__month": month}
                date_filter_lots = {"date_expedition__year": year, "date_expedition__month": month}
            else:
                date_filter_colis = {"lot__date_arrivee__year": year, "lot__date_arrivee__month": month}
                date_filter_lots = {"date_arrivee__year": year, "date_arrivee__month": month}
        elif year and str(year) != "all":
             if country_code == "CN":
                date_filter_colis = {"lot__date_expedition__year": year}
                date_filter_lots = {"date_expedition__year": year}
             else:
                date_filter_colis = {"lot__date_arrivee__year": year}
                date_filter_lots = {"date_arrivee__year": year}

        colis_periode = Colis.objects.filter(lot__destination__code=country_code).filter(**date_filter_colis)
        # La performance inclut TOUS les colis du lot (payés en Chine ou au Mali) car le fret est payé pour tous.
        
        lots_periode = Lot.objects.filter(destination__code=country_code).filter(**date_filter_lots)

        ca_brut = colis_periode.aggregate(total=Sum("prix_final"))["total"] or 0
        total_jc = colis_periode.aggregate(total=Sum("montant_jc"))["total"] or 0
        total_reste = colis_periode.aggregate(total=Sum("reste_a_payer"))["total"] or 0
        
        # CA Net = Total théorique - Jetons de présence (base engagement)
        # Le reste à payer est suivi séparément comme indicateur d'encaissement.
        ca_net = Decimal(ca_brut) - Decimal(total_jc)

        # 2. COÛTS DIRECTS (Fret + Douane)
        total_fret = lots_periode.aggregate(total=Sum("frais_transport"))["total"] or 0
        total_douane = lots_periode.aggregate(total=Sum("frais_douane"))["total"] or 0
        benefice_brut = ca_net - Decimal(total_fret) - Decimal(total_douane)

        # 3. CHARGES D'EXPLOITATION (Dépenses + RH)
        depenses_exploit_qs = Depense.objects.filter(pays__code=country_code, is_china_indicative=False)
        avances_rh_qs = AvanceSalaire.objects.filter(agent__country__code=country_code)
        salaires_rh_qs = PaiementAgent.objects.filter(agent__country__code=country_code)

        if year and str(year) != "all":
            depenses_exploit_qs = depenses_exploit_qs.filter(date__year=year)
            avances_rh_qs = avances_rh_qs.filter(date__year=year)
            salaires_rh_qs = salaires_rh_qs.filter(periode_annee=year)
            if month and str(month) != "all":
                depenses_exploit_qs = depenses_exploit_qs.filter(date__month=month)
                avances_rh_qs = avances_rh_qs.filter(date__month=month)
                salaires_rh_qs = salaires_rh_qs.filter(periode_mois=month)

        depenses_exploit = depenses_exploit_qs.aggregate(total=Sum("montant"))["total"] or 0
        avances_rh = avances_rh_qs.aggregate(total=Sum("montant"))["total"] or 0
        salaires_rh = salaires_rh_qs.aggregate(total=Sum("montant"))["total"] or 0

        total_charges = Decimal(depenses_exploit) + Decimal(avances_rh) + Decimal(salaires_rh)
        benefice_net = benefice_brut - total_charges

        # 4. DÉTAILS AVION / BATEAU
        colis_avion = colis_periode.filter(lot__type_transport__in=["CARGO", "EXPRESS"])
        colis_bateau = colis_periode.filter(lot__type_transport="BATEAU")
        
        # Pour le détail Avion/Bateau, on applique la même logique en base engagement
        lots_avion = lots_periode.filter(type_transport__in=["CARGO", "EXPRESS"])
        lots_bateau = lots_periode.filter(type_transport="BATEAU")
        
        ca_avion = (
            (colis_avion.aggregate(total=Sum("prix_final"))["total"] or 0) - 
            (colis_avion.aggregate(total=Sum("montant_jc"))["total"] or 0)
        )
        ca_bateau = (
            (colis_bateau.aggregate(total=Sum("prix_final"))["total"] or 0) - 
            (colis_bateau.aggregate(total=Sum("montant_jc"))["total"] or 0)
        )
        
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
            "total_reste_a_payer": total_reste,
            "total_encaisse": ca_net - Decimal(total_reste),
            "taux_encaissement": round((float(ca_net - Decimal(total_reste)) / float(ca_net)) * 100, 1) if ca_net else 0,
        }
