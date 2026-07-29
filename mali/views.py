from django.views.generic import TemplateView, ListView, View, DetailView, CreateView
from django.views.generic.edit import UpdateView
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.urls import reverse, reverse_lazy
from django.db.models import (
    Q,
    Count,
    Sum,
    Value,
    F,
    DecimalField,
    DateField,
    ExpressionWrapper,
    Case,
    When,
    OuterRef,
    Subquery,
)
from django.db.models.functions import Concat, Coalesce
from core.mixins import DestinationAgentRequiredMixin, AdminMaliRequiredMixin
from core.models import (
    Country,
    Lot,
    Colis,
    Client,
    User,
    AvanceSalaire,
    ClientLotTarif,
    EncaissementColis,
    AvoirMouvement,
)
from report.models import Depense, TransfertArgent, PaiementAgent
from report.finance_engine import FinanceEngine
from django.contrib import messages

from notification.models import ConfigurationNotification
from .forms import (
    NotificationConfigForm,
    AvanceSalaireForm,
    MaliAgentForm,
    MaliClientLotTarifForm,
    LotBateauMaliForm,
)
from chine.views import get_country_stats

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def apply_flexible_search(queryset, query, search_fields):
    """
    Applique une recherche flexible : chaque mot de la requête doit se trouver
    dans au moins un des champs de recherche (Logique AND entre les mots).
    """
    if not query:
        return queryset

    words = query.split()
    for word in words:
        q_obj = Q()
        for field in search_fields:
            if "__icontains" not in field:
                q_obj |= Q(**{f"{field}__icontains": word})
            else:
                q_obj |= Q(**{field: word})
        queryset = queryset.filter(q_obj)
    return queryset.distinct()


class DashboardView(LoginRequiredMixin, DestinationAgentRequiredMixin, TemplateView):
    template_name = "mali/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Récupérer la destination dynamique
        mali = self.get_current_country()
        if not mali:
            context["error"] = "Destination non configurée"
            return context

        # Date du jour et mois en cours
        today = timezone.now().date()
        first_day_of_month = today.replace(day=1)

        # Note: Le modèle Colis utilise les status: RECU, EXPEDIE, ARRIVE, LIVRE
        # Pas TRANSIT ou STOCK. Nous devons ajuster selon les vrais statuts.

        # 1. Colis Livrés (mois en cours) et Recettes (SEGMENTÉ)
        from django.db.models import Q as Q_filter

        base_qs = Colis.objects.filter(lot__destination=mali, status="LIVRE").filter(
            Q_filter(date_encaissement__year=today.year, date_encaissement__month=today.month)
            | Q_filter(date_encaissement__isnull=True, date_livraison__year=today.year, date_livraison__month=today.month)
        )

        # Totaux Globaux
        context["colis_livres_mois"] = base_qs.count()
        
        # Segmentation utilisant les nouveaux Managers
        colis_avion = base_qs.avion()
        colis_bateau = base_qs.bateau()
        
        context["colis_livres_avion"] = colis_avion.count()
        context["colis_livres_bateau"] = colis_bateau.count()

        def calculate_recettes(qs):
            return qs.aggregate(
                total=Sum(
                    Case(
                        When(paye_en_chine=True, then=Value(0)),
                        When(paye_par_avance=True, then=Value(0)),
                        default=F("prix_final") - F("montant_jc") - F("reste_a_payer"),
                        output_field=DecimalField(),
                    )
                )
            )["total"] or 0

        recettes_avion = calculate_recettes(colis_avion)
        recettes_bateau = calculate_recettes(colis_bateau)
        recettes_mois = recettes_avion + recettes_bateau

        from core.models import AvoirMouvement

        rechargements_avoir_mois = (
            AvoirMouvement.objects.filter(
                client__country=mali,
                type="DEPOT",
                created_at__year=today.year,
                created_at__month=today.month,
            ).aggregate(total=Sum("montant"))["total"]
            or 0
        )

        context["recettes_mois"] = recettes_mois + rechargements_avoir_mois
        context["recettes_avion"] = recettes_avion
        context["recettes_bateau"] = recettes_bateau

        # Poids / Volume
        context["total_poids_mois"] = colis_avion.aggregate(total=Sum("poids"))["total"] or 0
        context["total_cbm_mois"] = colis_bateau.aggregate(total=Sum("cbm"))["total"] or 0

        # 2. Dépenses (mois)
        depenses_base_mois_qs = Depense.objects.filter(
            Q(pays=mali) | Q(is_china_indicative=True),
            date__year=today.year,
            date__month=today.month,
        )
        depenses_classiques_mois_qs = depenses_base_mois_qs.filter(
            is_china_indicative=False
        )
        depenses_classiques_mois = (
            depenses_classiques_mois_qs.aggregate(total=Sum("montant"))["total"] or 0
        )

        # 2b. Transferts (mois) - Considérés comme dépenses
        from report.models import TransfertArgent

        transferts_mois_qs = TransfertArgent.objects.filter(
            pays_expediteur=mali, date__year=today.year, date__month=today.month
        )
        transferts_mois = (
            transferts_mois_qs.aggregate(total=Sum("montant"))["total"] or 0
        )

        # Total Dépenses (Classiques + Transferts)
        depenses_mois = depenses_classiques_mois + transferts_mois

        context["depenses_mois"] = depenses_mois
        context["depenses_classiques_mois"] = (
            depenses_classiques_mois  # Pour info si besoin
        )
        context["transferts_mois"] = transferts_mois  # Pour info si besoin

        # Solde du mois (Recettes - Dépenses Totales)
        context["solde_mois"] = recettes_mois - depenses_mois

        # 3. Colis Perdus (mois en cours)
        colis_perdus_base = Colis.objects.filter(
            lot__destination=mali, status="PERDU", updated_at__gte=first_day_of_month
        )
        context["colis_perdus_mois"] = colis_perdus_base.count()
        context["colis_perdus_avion"] = colis_perdus_base.avion().count()
        context["colis_perdus_bateau"] = colis_perdus_base.bateau().count()

        # 4. Colis en attente de paiement (non payés)
        colis_attente_base = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", est_paye=False
        )
        context["colis_attente_paiement"] = colis_attente_base.count()
        context["colis_attente_paiement_avion"] = colis_attente_base.avion().count()
        context["colis_attente_paiement_bateau"] = colis_attente_base.bateau().count()

        # 5. Colis à Traiter (Arrivés, non livrés)
        colis_a_traiter_base = Colis.objects.filter(
            lot__destination=mali, status="ARRIVE"
        )
        context["colis_a_traiter"] = colis_a_traiter_base.count()
        context["colis_a_traiter_avion"] = colis_a_traiter_base.avion().count()
        context["colis_a_traiter_bateau"] = colis_a_traiter_base.bateau().count()

        # 6. Lots en Transit
        lots_en_transit_base = Lot.objects.filter(
            destination=mali, status="EN_TRANSIT"
        )
        context["lots_en_transit"] = lots_en_transit_base.count()
        context["lots_en_transit_avion"] = lots_en_transit_base.avion().count()
        context["lots_en_transit_bateau"] = lots_en_transit_base.bateau().count()

        # 7. Lots Arrivés (Incomplets) - Au moins 1 colis status ARRIVE
        lots_avec_stock = Lot.objects.filter(
            destination=mali, colis__status="ARRIVE"
        ).distinct()
        context["lots_arrives_incomplets"] = lots_avec_stock.count()
        context["lots_arrives_incomplets_avion"] = lots_avec_stock.avion().count()
        context["lots_arrives_incomplets_bateau"] = lots_avec_stock.bateau().count()

        # 7b. Lots Livrés (Mois) - Lots ayant des colis livrés ce mois ci
        lots_livres_base = Lot.objects.filter(
            destination=mali,
            colis__status="LIVRE",
            colis__updated_at__gte=first_day_of_month,
        ).distinct()
        
        context["lots_livres_mois"] = lots_livres_base.count()
        context["lots_livres_mois_avion"] = lots_livres_base.avion().count()
        context["lots_livres_mois_bateau"] = lots_livres_base.bateau().count()

        # 8. Encaissements du Jour (Montant net collecté sur les livraisons du jour)
        encaissements = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", date_encaissement=today
        ).aggregate(
            total=Sum(
                Case(
                    When(paye_en_chine=True, then=Value(0)),
                    When(paye_par_avance=True, then=Value(0)),
                    default=F("prix_final") - F("montant_jc") - F("reste_a_payer"),
                    output_field=DecimalField(),
                )
            )
        )
        context["encaissements_jour"] = encaissements["total"] or 0

        # Détermination du trimestre en cours pour l'Aérien (Trimestre logistique)
        now_date = timezone.now()
        cur_month = now_date.month
        cur_year = now_date.year
        if 3 <= cur_month <= 5:
            quarter_num = 1
            months_q = [3, 4, 5]
        elif 6 <= cur_month <= 8:
            quarter_num = 2
            months_q = [6, 7, 8]
        elif 9 <= cur_month <= 11:
            quarter_num = 3
            months_q = [9, 10, 11]
        else:
            quarter_num = 4
            months_q = [12, 1, 2]

        context["aerien_quarter_label"] = f"Trimestre T{quarter_num} {cur_year}"

        colis_mali_qs = Colis.objects.filter(lot__destination=mali)
        
        # 1. LOGISTIQUE AVION & BATEAU : GLOBAUX (TOUS LES TEMPS)
        colis_avion_global_qs = colis_mali_qs.avion()
        colis_bateau_global_qs = colis_mali_qs.bateau()

        context["colis_transit_avion"] = colis_avion_global_qs.filter(status="EXPEDIE").count()
        context["colis_stock_avion"] = colis_avion_global_qs.filter(status="ARRIVE").count()
        context["colis_livres_avion_count"] = colis_avion_global_qs.filter(status="LIVRE").count()

        context["colis_transit_bateau"] = colis_bateau_global_qs.filter(status="EXPEDIE").count()
        context["colis_stock_bateau"] = colis_bateau_global_qs.filter(status="ARRIVE").count()
        context["colis_livres_bateau_count"] = colis_bateau_global_qs.filter(status="LIVRE").count()

        # 2. FINANCIER AVION (Carte Verte - Trimestriel)
        colis_avion_quarter_qs = colis_avion_global_qs.filter(
            Q(lot__date_expedition__month__in=months_q) | Q(created_at__month__in=months_q)
        )
        ca_brut_avion = colis_avion_quarter_qs.aggregate(total=Sum("prix_final"))["total"] or 0
        lots_avion_q = Lot.objects.filter(destination=mali).avion().filter(
            Q(date_expedition__month__in=months_q) | Q(created_at__month__in=months_q)
        )
        fret_avion = lots_avion_q.aggregate(total=Sum("frais_transport"))["total"] or 0
        douane_avion = lots_avion_q.aggregate(total=Sum("frais_douane"))["total"] or 0
        depenses_bureau_avion = Depense.objects.filter(pays=mali, type_transport="AERIEN", date__month__in=months_q).aggregate(total=Sum("montant"))["total"] or 0

        # 3. FINANCIER BATEAU (Carte Bleue - Global / All Time)
        ca_brut_bateau = colis_bateau_global_qs.aggregate(total=Sum("prix_final"))["total"] or 0
        lots_bateau_qs = Lot.objects.filter(destination=mali).bateau()
        fret_bateau = lots_bateau_qs.aggregate(total=Sum("frais_transport"))["total"] or 0
        douane_bateau = lots_bateau_qs.aggregate(total=Sum("frais_douane"))["total"] or 0
        depenses_bureau_bateau = Depense.objects.filter(pays=mali, type_transport="BATEAU").aggregate(total=Sum("montant"))["total"] or 0

        from core.models import AvanceSalaire
        total_avances_mali = AvanceSalaire.objects.filter(agent__country=mali).aggregate(total=Sum("montant"))["total"] or 0

        # Ligne 2 : Bénéfice après dépenses (du bureau & frais)
        benefice_apres_depenses_avion = ca_brut_avion - (fret_avion + douane_avion + depenses_bureau_avion)
        benefice_apres_depenses_bateau = ca_brut_bateau - (fret_bateau + douane_bateau + depenses_bureau_bateau)

        # Ligne 3 : Bénéfice après avance salaire ou salaire
        benefice_apres_avances_avion = benefice_apres_depenses_avion - (total_avances_mali / 2)
        benefice_apres_avances_bateau = benefice_apres_depenses_bateau - (total_avances_mali / 2)

        context["ca_brut_avion"] = ca_brut_avion
        context["benefice_apres_depenses_avion"] = benefice_apres_depenses_avion
        context["benefice_apres_avances_avion"] = benefice_apres_avances_avion

        context["ca_brut_bateau"] = ca_brut_bateau
        context["benefice_apres_depenses_bateau"] = benefice_apres_depenses_bateau
        context["benefice_apres_avances_bateau"] = benefice_apres_avances_bateau

        context["total_avances_mali"] = total_avances_mali

        # Activité récente (derniers colis pointés/livrés aujourd'hui)
        # Activité récente (derniers colis pointés/livrés aujourd'hui)
        context["activites_recentes"] = (
            Colis.objects.filter(
                Q(lot__destination=mali),
                Q(status__in=["ARRIVE", "LIVRE", "PERDU"]),
                Q(date_livraison=today) | Q(date_encaissement=today),
            )
            .select_related("client", "lot")
            .annotate(
                sort_date=Coalesce(
                    "date_livraison", "updated_at", output_field=DateField()
                )
            )
            .order_by("-sort_date", "-updated_at")[:10]
        )

        return context


class AujourdhuiView(LoginRequiredMixin, DestinationAgentRequiredMixin, TemplateView):
    """Page Aujourd'hui avec statistiques quotidiennes et rapports imprimables"""

    template_name = "mali/aujourdhui.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Récupérer la destination dynamique
        mali = self.get_current_country()
        if not mali:
            context["error"] = "Destination non configurée"
            return context

        # Date du rapport (aujourd'hui par défaut)
        date_str = self.request.GET.get("date")
        if date_str:
            try:
                from datetime import datetime

                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                target_date = timezone.now().date()
        else:
            target_date = timezone.now().date()

        context["target_date"] = target_date
        today = target_date
        today = target_date
        mali = self.get_current_country()
        
        # --- 1. CALCULS FINANCIERS VIA LE MOTEUR CENTRALISÉ ---
        fin_stats = FinanceEngine.get_daily_summary(today, mali)
        
        context["solde_veille"] = fin_stats["solde_veille"]
        context["total_recettes_jour"] = fin_stats["total_recettes_jour"]
        context["total_sorties_jour"] = fin_stats["total_sorties_jour"]
        context["solde_caisse_actuel"] = fin_stats["solde_caisse_actuel"]

        # Caisse Aérien (Cargo + Express)
        fin_stats_aerien = FinanceEngine.get_daily_summary(today, mali, "AERIEN")
        context["aerien_solde_veille"] = fin_stats_aerien["solde_veille"]
        context["aerien_total_recettes_jour"] = fin_stats_aerien["total_recettes_jour"]
        context["aerien_total_sorties_jour"] = fin_stats_aerien["total_sorties_jour"]
        context["aerien_solde_caisse_actuel"] = fin_stats_aerien["solde_caisse_actuel"]

        # Caisse Bateau
        fin_stats_bateau = FinanceEngine.get_daily_summary(today, mali, "BATEAU")
        context["bateau_solde_veille"] = fin_stats_bateau["solde_veille"]
        context["bateau_total_recettes_jour"] = fin_stats_bateau["total_recettes_jour"]
        context["bateau_total_sorties_jour"] = fin_stats_bateau["total_sorties_jour"]
        context["bateau_solde_caisse_actuel"] = fin_stats_bateau["solde_caisse_actuel"]
        
        context["total_depenses_only"] = fin_stats["total_depenses"]
        context["total_transferts_only"] = fin_stats["total_transferts"]
        context["total_paiements_agents"] = fin_stats["total_paiements_agents"]
        
        context["rechargements_avoir_jour"] = fin_stats["total_rechargements_avoir"]
        context["rechargements_avoir_list"] = fin_stats["rechargements_list"]
        context["depenses_jour_reelles"] = fin_stats["depenses_list"]
        context["transferts_list"] = fin_stats["transferts_list"]

        # --- 2. ACTIVITÉ DU JOUR (Cargo, Express, Bateau) ---
        # On définit le périmètre du jour : 
        # Soit un encaissement a été fait aujourd'hui (via EncaissementColis)
        # Soit le colis a été livré gratuitement aujourd'hui (Sortie sous garantie)
        colis_livres_jour = (
            Colis.objects.filter(lot__destination=mali)
            .filter(
                Q(encaissements__date=today) | 
                Q(date_encaissement=today) |
                Q(status="LIVRE", date_livraison=today, date_encaissement__isnull=True) |
                Q(updated_at__date=today, montant_jc__gt=0)
            )
            .distinct()
            .select_related("client", "lot")
        )

        # --- RECHERCHE ---
        query = self.request.GET.get("q")
        if query:
            # Recherche multicritère : Nom, Téléphone, Poids, Référence
            q_filter = Q(client__nom__icontains=query) | \
                      Q(client__prenom__icontains=query) | \
                      Q(client__telephone__icontains=query) | \
                      Q(reference__icontains=query)
            
            # Essayer de chercher par poids si la requête est numérique
            try:
                weight_val = float(query.replace(",", "."))
                q_filter |= Q(poids=weight_val)
            except ValueError:
                pass
                
            colis_livres_jour = colis_livres_jour.filter(q_filter)

        # Annotation pour l'heure de paiement et le montant payé dans la journée
        # On définit une sous-requête pour la somme des encaissements du jour cible
        enc_day_qs = EncaissementColis.objects.filter(
            colis=OuterRef("pk"),
            date=today
        )
        enc_day_hors_avance_qs = enc_day_qs.exclude(methode="AVANCE")
        
        sum_enc_day = enc_day_qs.values("colis").annotate(total=Sum("montant")).values("total")
        sum_enc_day_hors_avance = enc_day_hors_avance_qs.values("colis").annotate(total=Sum("montant")).values("total")
        latest_enc = enc_day_qs.order_by("-created_at")

        colis_livres_jour = colis_livres_jour.annotate(
            heure_paiement=Subquery(latest_enc.values("created_at")[:1]),
            # Somme des encaissements réels du jour (inclus AVANCE pour affichage)
            sum_enc=Coalesce(Subquery(sum_enc_day[:1]), Value(0), output_field=DecimalField()),
            # Somme hors AVANCE pour le calcul des totaux de caisse
            sum_enc_hors_avance=Coalesce(Subquery(sum_enc_day_hors_avance[:1]), Value(0), output_field=DecimalField()),
            # Valeur théorique si c'est un ancien colis (legacy) payé ce jour sans objet EncaissementColis
            val_legacy=Case(
                When(date_encaissement=today, encaissements__isnull=True, then=F("prix_final") - Coalesce(F("montant_jc"), Value(0))),
                default=Value(0),
                output_field=DecimalField()
            ),
            # Le montant payé affiché est la somme des deux (avec avance)
            montant_paye_jour=F("sum_enc") + F("val_legacy"),
            # Le montant pour les totaux (sans avance)
            montant_paye_jour_hors_avance=F("sum_enc_hors_avance") + F("val_legacy")
        )

        # Séparation par type de transport (via le Lot)
        # Note: Lot.type_transport choices: CARGO, EXPRESS, BATEAU

        # A. Cargo (Air)
        colis_cargo = colis_livres_jour.filter(lot__type_transport="CARGO")
        context["colis_cargo_list"] = colis_cargo.annotate(
            # On affiche ce qui a été payé (y compris avance)
            net_price=F("montant_paye_jour"),
            sort_date=Coalesce(
                "date_livraison", "updated_at", output_field=DateField()
            ),
        ).order_by("-heure_paiement", "-sort_date", "-updated_at")
        
        context["recette_cargo_jour"] = (colis_cargo.aggregate(total=Sum("montant_paye_jour_hors_avance"))["total"] or 0)
        context["poids_cargo_jour"] = colis_cargo.aggregate(total=Sum("poids"))["total"] or 0
        context["nb_cargo_jour"] = colis_cargo.count()

        # B. Express (Air)
        colis_express = colis_livres_jour.filter(lot__type_transport="EXPRESS")
        context["colis_express_list"] = colis_express.annotate(
            net_price=F("montant_paye_jour"),
            sort_date=Coalesce(
                "date_livraison", "updated_at", output_field=DateField()
            ),
        ).order_by("-heure_paiement", "-sort_date", "-updated_at")
        
        context["recette_express_jour"] = (colis_express.aggregate(total=Sum("montant_paye_jour_hors_avance"))["total"] or 0)
        context["poids_express_jour"] = colis_express.aggregate(total=Sum("poids"))["total"] or 0
        context["nb_express_jour"] = colis_express.count()

        # C. Bateau (Maritime)
        colis_bateau = colis_livres_jour.filter(lot__type_transport="BATEAU")
        context["colis_bateau_list"] = colis_bateau.annotate(
            net_price=F("montant_paye_jour"),
            sort_date=Coalesce(
                "date_livraison", "updated_at", output_field=DateField()
            ),
        ).order_by("-heure_paiement", "-sort_date", "-updated_at")
        
        context["recette_bateau_jour"] = (colis_bateau.aggregate(total=Sum("montant_paye_jour_hors_avance"))["total"] or 0)
        context["poids_bateau_jour"] = colis_bateau.aggregate(total=Sum("poids"))["total"] or 0
        context["cbm_bateau_jour"] = colis_bateau.aggregate(total=Sum("cbm"))["total"] or 0
        context["nb_bateau_jour"] = colis_bateau.count()

        # Poids Total Jour (Kilos livrés du jour)
        context["total_poids_jour"] = context["poids_cargo_jour"] + context["poids_express_jour"] + context["poids_bateau_jour"]

        # Total JC Jour (Pour info)
        context["total_jc_jour"] = (
            colis_livres_jour.aggregate(total=Sum("montant_jc"))["total"] or 0
        )

        # --- 3. DÉPENSES INDICATIVES (CHINE) ---
        # Note : Les dépenses réelles Mali sont déjà gérées par FinanceEngine
        context["depenses_indicatives_jour"] = Depense.objects.filter(
            is_china_indicative=True, date=today
        ).order_by("-created_at")
        
        context["total_depenses_indicatives"] = (
            context["depenses_indicatives_jour"].aggregate(total=Sum("montant"))["total"] or 0
        )

        # Séparation des transferts pour l'affichage (déjà filtrés par FinanceEngine)
        context["transferts_chine_list"] = context["transferts_list"].filter(destinataire="CHINE")
        context["transferts_gaoussou_list"] = context["transferts_list"].filter(destinataire="GAOUSSOU")

        # --- CALCULS RÉPARTITION VENTES DU JOUR (SÉPARÉS AÉRIEN / BATEAU) ---
        # 1. Aérien (Cargo + Express)
        enc_aerien = EncaissementColis.objects.filter(
            colis__lot__destination=mali,
            colis__lot__type_transport__in=["CARGO", "EXPRESS"],
            date=today
        )
        colis_legacy_aerien = Colis.objects.filter(
            lot__destination=mali,
            lot__type_transport__in=["CARGO", "EXPRESS"],
            date_encaissement=today,
            encaissements__isnull=True
        )

        context["recette_aerien_jour"] = context["recette_cargo_jour"] + context["recette_express_jour"]
        context["nb_aerien_jour"] = context["nb_cargo_jour"] + context["nb_express_jour"]
        context["poids_aerien_jour"] = context["poids_cargo_jour"] + context["poids_express_jour"]

        context["aerien_espece"] = (enc_aerien.filter(methode="ESPECE").aggregate(total=Sum("montant"))["total"] or 0) + \
                                   (colis_legacy_aerien.filter(mode_paiement="ESPECE").aggregate(total=Sum(F("prix_final") - Coalesce(F("montant_jc"), Value(0, output_field=DecimalField()), output_field=DecimalField()), output_field=DecimalField()))["total"] or 0)

        context["aerien_om"] = (enc_aerien.filter(methode="ORANGE_MONEY").aggregate(total=Sum("montant"))["total"] or 0) + \
                                (colis_legacy_aerien.filter(mode_paiement="ORANGE_MONEY").aggregate(total=Sum(F("prix_final") - Coalesce(F("montant_jc"), Value(0, output_field=DecimalField()), output_field=DecimalField()), output_field=DecimalField()))["total"] or 0)

        context["aerien_wave"] = (enc_aerien.filter(methode="WAVE").aggregate(total=Sum("montant"))["total"] or 0) + \
                                 (colis_legacy_aerien.filter(mode_paiement="WAVE").aggregate(total=Sum(F("prix_final") - Coalesce(F("montant_jc"), Value(0, output_field=DecimalField()), output_field=DecimalField()), output_field=DecimalField()))["total"] or 0)

        context["aerien_avance"] = (enc_aerien.filter(methode="AVANCE").aggregate(total=Sum("montant"))["total"] or 0) + \
                                   (colis_legacy_aerien.filter(mode_paiement="AVANCE").aggregate(total=Sum(F("prix_final") - Coalesce(F("montant_jc"), Value(0, output_field=DecimalField()), output_field=DecimalField()), output_field=DecimalField()))["total"] or 0)

        # 2. Bateau
        enc_bateau = EncaissementColis.objects.filter(
            colis__lot__destination=mali,
            colis__lot__type_transport="BATEAU",
            date=today
        )
        colis_legacy_bateau = Colis.objects.filter(
            lot__destination=mali,
            lot__type_transport="BATEAU",
            date_encaissement=today,
            encaissements__isnull=True
        )

        context["bateau_espece"] = (enc_bateau.filter(methode="ESPECE").aggregate(total=Sum("montant"))["total"] or 0) + \
                                   (colis_legacy_bateau.filter(mode_paiement="ESPECE").aggregate(total=Sum(F("prix_final") - Coalesce(F("montant_jc"), Value(0, output_field=DecimalField()), output_field=DecimalField()), output_field=DecimalField()))["total"] or 0)

        context["bateau_om"] = (enc_bateau.filter(methode="ORANGE_MONEY").aggregate(total=Sum("montant"))["total"] or 0) + \
                                (colis_legacy_bateau.filter(mode_paiement="ORANGE_MONEY").aggregate(total=Sum(F("prix_final") - Coalesce(F("montant_jc"), Value(0, output_field=DecimalField()), output_field=DecimalField()), output_field=DecimalField()))["total"] or 0)

        context["bateau_wave"] = (enc_bateau.filter(methode="WAVE").aggregate(total=Sum("montant"))["total"] or 0) + \
                                 (colis_legacy_bateau.filter(mode_paiement="WAVE").aggregate(total=Sum(F("prix_final") - Coalesce(F("montant_jc"), Value(0, output_field=DecimalField()), output_field=DecimalField()), output_field=DecimalField()))["total"] or 0)

        context["bateau_avance"] = (enc_bateau.filter(methode="AVANCE").aggregate(total=Sum("montant"))["total"] or 0) + \
                                   (colis_legacy_bateau.filter(mode_paiement="AVANCE").aggregate(total=Sum(F("prix_final") - Coalesce(F("montant_jc"), Value(0, output_field=DecimalField()), output_field=DecimalField()), output_field=DecimalField()))["total"] or 0)

        return context


class LotsEnTransitView(LoginRequiredMixin, DestinationAgentRequiredMixin, ListView):
    """Liste des lots en transit vers le Mali"""

    template_name = "mali/lots_transit.html"
    context_object_name = "lots"
    paginate_by = 20

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Lot.objects.none()

        query = self.request.GET.get("q")
        if query:
            # RECHERCHE GLOBALE PAR COLIS (Demande utilisateur)
            queryset = Colis.objects.filter(lot__destination=mali, status="EXPEDIE")
            queryset = queryset.select_related("lot", "client", "client__user")
            queryset = queryset.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
                prenom_complet=Concat("client__prenom", Value(" "), "client__nom"),
            )
            search_fields = [
                "reference",
                "lot__numero",
                "client__nom",
                "client__prenom",
                "client__telephone",
                "nom_complet",
                "prenom_complet",
            ]
            queryset = apply_flexible_search(queryset, query, search_fields)

            # Isolation Aérien / Maritime
            if getattr(self.request, "is_maritime", False):
                queryset = queryset.filter(lot__type_transport="BATEAU")
            else:
                queryset = queryset.filter(lot__type_transport__in=["CARGO", "EXPRESS"])

            transport = self.request.GET.get("transport")
            if transport in ["CARGO", "EXPRESS", "BATEAU"]:
                queryset = queryset.filter(lot__type_transport=transport)
            return queryset.order_by("-created_at")

        # AFFICHAGE PAR LOT (Sans recherche)
        queryset = (
            Lot.objects.filter(destination=mali, colis__status="EXPEDIE")
            .select_related("destination")
            .prefetch_related("colis")
            .annotate(
                # On ne compte que les colis en transit pour ce lot dans cette vue
                nb_colis_transit=Count("colis", filter=Q(colis__status="EXPEDIE")),
                poids_total_transit=Sum(
                    "colis__poids", filter=Q(colis__status="EXPEDIE")
                ),
                total_recettes_transit=Sum(
                    "colis__prix_final", filter=Q(colis__status="EXPEDIE")
                ),
                cbm_total_transit=Sum(
                    "colis__cbm", filter=Q(colis__status="EXPEDIE")
                ),
                # Nombre de colis déjà payés en Chine dans ce lot (parmi les colis en transit)
                nb_colis_payes_chine=Count(
                    "colis",
                    filter=Q(colis__status="EXPEDIE", colis__paye_en_chine=True),
                ),
            )
            .annotate(
                benefice_calcule=ExpressionWrapper(
                    Coalesce(
                        F("total_recettes_transit"), 0.0, output_field=DecimalField()
                    )
                    - Coalesce(F("frais_transport"), 0.0, output_field=DecimalField())
                    - Coalesce(F("frais_douane"), 0.0, output_field=DecimalField()),
                    output_field=DecimalField(),
                )
            )
            .filter(nb_colis_transit__gt=0)
            .distinct()
        )

        # Filtrage par type de transport (concerne les lots)
        transport = self.request.GET.get("transport")
        if transport in ["CARGO", "EXPRESS", "BATEAU"]:
            queryset = queryset.filter(type_transport=transport)

        return queryset.order_by("-date_expedition")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        context["active_transport"] = self.request.GET.get("transport", "")
        # On peut aussi ajouter total_lots car il semble utilisé dans le template
        context["total_lots"] = self.get_queryset().count()
        return context


class LotsArrivesView(LotsEnTransitView):
    """Vue historique des lots arrivés au Mali (statut ARRIVE ou LIVRE)"""

    paginate_by = 10
    template_name = "mali/lots_arrives.html"

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Lot.objects.none()

        query = self.request.GET.get("q")
        if query:
            # RECHERCHE GLOBALE PAR COLIS (Demande utilisateur)
            queryset = Colis.objects.filter(lot__destination=mali, status="ARRIVE")
            queryset = queryset.select_related("lot", "client", "client__user")
            queryset = queryset.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
                prenom_complet=Concat("client__prenom", Value(" "), "client__nom"),
            )
            search_fields = [
                "reference",
                "lot__numero",
                "client__nom",
                "client__prenom",
                "client__telephone",
                "nom_complet",
                "prenom_complet",
            ]
            queryset = apply_flexible_search(queryset, query, search_fields)

            # Isolation Aérien / Maritime
            if getattr(self.request, "is_maritime", False):
                queryset = queryset.filter(lot__type_transport="BATEAU")
            else:
                queryset = queryset.filter(lot__type_transport__in=["CARGO", "EXPRESS"])

            transport = self.request.GET.get("transport")
            if transport in ["CARGO", "EXPRESS", "BATEAU"]:
                queryset = queryset.filter(lot__type_transport=transport)
            return queryset.order_by("-updated_at")

        # AFFICHAGE PAR LOT (Sans recherche)
        # Un lot apparaît en arrivés dans deux cas :
        # 1. Il contient au moins un colis au statut ARRIVE (lots standards Chine→Mali)
        # 2. C'est un lot créé localement au Mali (ex: régularisation Bateau) avec statut ARRIVE
        pending_q = Q(colis__status="ARRIVE")
        # Lots locaux Mali avec statut ARRIVE (bateau régularisation, etc.)
        local_arrive_q = Q(status=Lot.Status.ARRIVE, country=mali)

        queryset = (
            Lot.objects.filter(destination=mali)
            .filter(pending_q | local_arrive_q)
            .distinct()
            .select_related("destination")
            .prefetch_related("colis")
            .annotate(
                # Pour les lots locaux sans colis ARRIVE, nb_colis_arrive sera 0
                # mais le lot sera quand même visible grâce au filtre local_arrive_q
                nb_colis_arrive=Count("colis", filter=pending_q),
                poids_total_arrive=Sum("colis__poids", filter=pending_q),
                total_recettes_arrive=Sum("colis__prix_final", filter=pending_q),
                nb_colis_payes_chine=Count(
                    "colis",
                    filter=pending_q & Q(colis__paye_en_chine=True),
                ),
                cbm_total_arrive=Sum("colis__cbm", filter=pending_q),
            )
            .annotate(
                benefice_calcule=ExpressionWrapper(
                    Coalesce(
                        F("total_recettes_arrive"), 0.0, output_field=DecimalField()
                    )
                    - Coalesce(F("frais_transport"), 0.0, output_field=DecimalField())
                    - Coalesce(F("frais_douane"), 0.0, output_field=DecimalField()),
                    output_field=DecimalField(),
                )
            )
            .distinct()
        )

        # Filtrage par type de transport
        transport = self.request.GET.get("transport")
        if transport in ["CARGO", "EXPRESS", "BATEAU"]:
            queryset = queryset.filter(type_transport=transport)

        return queryset.order_by("-date_arrivee", "-created_at")




class LotDetailView(LoginRequiredMixin, DestinationAgentRequiredMixin, DetailView):
    """Vue détaillée d'un lot pour l'agent Mali (avec pointage des colis)"""

    model = Lot
    template_name = "mali/lot_detail.html"
    context_object_name = "lot"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        frais_douane = request.POST.get("frais_douane")
        if frais_douane is not None:
            self.object.frais_douane = frais_douane
            self.object.save()
            messages.success(request, f"Frais de douane mis à jour à {frais_douane} FCFA.")
        return redirect(request.path)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models import Sum, Q

        # Calculs financiers sur TOUS les colis du lot (indépendamment de la recherche)
        aggregates = self.object.colis.aggregate(
            total_poids=Sum("poids"),
            total_cbm=Sum("cbm"),
            total_montant=Sum("prix_final"),
            total_jc=Sum("montant_jc"),
        )
        context["total_poids"] = aggregates["total_poids"] or 0
        context["total_cbm"] = aggregates["total_cbm"] or 0
        context["total_montant_colis"] = (aggregates["total_montant"] or 0) - (
            aggregates["total_jc"] or 0
        )

        # Calcul Bénéfice Net (Recettes - Frais Expédition - Frais Douane)
        frais_exp = self.object.frais_transport or 0
        frais_douane = self.object.frais_douane or 0
        context["benefice"] = context["total_montant_colis"] - frais_exp - frais_douane

        # Colis du lot (avec support recherche et pagination)
        from django.core.paginator import Paginator

        colis_queryset = self.object.colis.select_related("client").order_by(
            "-created_at"
        )

        qc = self.request.GET.get("qc")
        if qc:
            colis_queryset = colis_queryset.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
                prenom_complet=Concat("client__prenom", Value(" "), "client__nom"),
            )
            search_fields = [
                "reference",
                "client__nom",
                "client__prenom",
                "client__telephone",
                "poids",
                "nom_complet",
                "prenom_complet",
            ]
            colis_queryset = apply_flexible_search(colis_queryset, qc, search_fields)
            context["qc"] = qc

        paginator = Paginator(colis_queryset, 20)
        page_number = self.request.GET.get("page")
        context["colis_list"] = paginator.get_page(page_number)

        return context


class LotTransitDetailView(LotDetailView):
    """Vue détaillée pour un lot en TRANSIT (Seulement colis EXPÉDIÉS)"""

    template_name = "mali/lot_transit_detail.html"

    def get_context_data(self, **kwargs):
        # On override pour ne filtrer que les colis EXPEDIE
        context = super().get_context_data(**kwargs)

        # Recalcul des agrégats pour les colis EXPEDIE uniquement
        aggregates = self.object.colis.filter(status="EXPEDIE").aggregate(
            total_poids=Sum("poids"),
            total_montant=Sum("prix_final"),
            total_jc=Sum("montant_jc"),
        )
        context["total_poids"] = aggregates["total_poids"] or 0
        context["total_montant_colis"] = (aggregates["total_montant"] or 0) - (
            aggregates["total_jc"] or 0
        )

        # Filtrage des colis listés
        colis_qs = self.object.colis.filter(status="EXPEDIE")

        qc = self.request.GET.get("qc")
        if qc:
            colis_qs = colis_qs.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
                prenom_complet=Concat("client__prenom", Value(" "), "client__nom"),
            )
            search_fields = [
                "reference",
                "client__nom",
                "client__prenom",
                "client__telephone",
                "poids",
                "nom_complet",
                "prenom_complet",
            ]
            colis_qs = apply_flexible_search(colis_qs, qc, search_fields)
        from django.core.paginator import Paginator

        paginator = Paginator(colis_qs.order_by("-created_at"), 20)
        context["colis_list"] = paginator.get_page(self.request.GET.get("page"))
        context["is_transit_mode"] = True
        return context


class LotArriveDetailView(LotDetailView):
    """Vue détaillée pour un lot ARRIVÉ (Seulement colis ARRIVÉS)"""

    template_name = "mali/lot_arrived_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Recalcul des agrégats pour les colis ARRIVE et TRANSIT (non pointés)
        aggregates = self.object.colis.filter(status__in=["TRANSIT", "ARRIVE"]).aggregate(
            total_poids=Sum("poids"),
            total_montant=Sum("prix_final"),
        )
        context["total_poids"] = aggregates["total_poids"] or 0
        context["total_montant_colis"] = aggregates["total_montant"] or 0

        # Filtrage des colis listés (Seul ceux n'ayant AUCUN paiement et non soldés)
        # On ne garde que les colis qui n'ont pas été payés ni imputés
        # On liste tous les colis ARRIVE du lot (Logique Master)
        colis_qs = (
            self.object.colis.select_related("client", "client__user")
            .filter(status="ARRIVE")
            .order_by("-updated_at")
        )
        qc = self.request.GET.get("qc")
        if qc:
            colis_qs = colis_qs.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
            ).filter(
                Q(reference__icontains=qc)
                | Q(client__nom__icontains=qc)
                | Q(nom_complet__icontains=qc)
                | Q(client__telephone__icontains=qc)
                | Q(poids__icontains=qc)
            )

        from django.core.paginator import Paginator

        # Trier: les colis ARRIVE en premier (livrables), puis les LIVRE
        paginator = Paginator(colis_qs.order_by("status", "-created_at"), 20)
        context["colis_list"] = paginator.get_page(self.request.GET.get("page"))
        context["qc"] = qc or ""
        context["is_arrive_mode"] = True
        
        from core.models import PersonneSortie
        context["personnes_sortie"] = PersonneSortie.objects.all().order_by("nom")
        
        return context


class LotLivreDetailView(LotDetailView):
    """Vue détaillée pour un lot LIVRÉ/PERDU"""

    template_name = "mali/lot_livre_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Recalcul des agrégats pour les colis LIVRE/PERDU uniquement
        aggregates = self.object.colis.filter(status__in=["LIVRE", "PERDU"]).aggregate(
            total_montant=Sum("prix_final"),
            total_jc=Sum("montant_jc"),
        )
        context["total_montant_colis"] = (aggregates["total_montant"] or 0) - (
            aggregates["total_jc"] or 0
        )

        # Filtrage des colis listés
        colis_qs = self.object.colis.filter(status__in=["LIVRE", "PERDU"]).annotate(
            net_price=F("prix_final") - F("montant_jc")
        )

        qc = self.request.GET.get("qc")
        if qc:
            colis_qs = colis_qs.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
            ).filter(
                Q(reference__icontains=qc)
                | Q(client__nom__icontains=qc)
                | Q(nom_complet__icontains=qc)
                | Q(client__telephone__icontains=qc)
                | Q(poids__icontains=qc)
            )

        from django.core.paginator import Paginator

        paginator = Paginator(
            colis_qs.annotate(
                sort_date=Coalesce(
                    "date_livraison", "updated_at", output_field=DateField()
                )
            ).order_by("-sort_date", "-updated_at"),
            20,
        )
        context["colis_list"] = paginator.get_page(self.request.GET.get("page"))
        context["is_livre_mode"] = True
        return context


class ColisArriveView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Marquer un colis individuel comme ARRIVÉ (Pointage)"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)

        # Restriction : frais de douane requis pour pointer
        if not colis.lot.frais_douane:
            if request.headers.get("HX-Request"):
                from django.shortcuts import render

                return render(
                    request,
                    "mali/partials/colis_status_badge.html",
                    {"colis": colis, "lot": colis.lot, "error_locked": True},
                )
            messages.error(
                request,
                "Veuillez renseigner les frais de douane du lot avant de pointer les colis.",
            )
            return redirect("mali:lot_transit_detail", pk=colis.lot.pk)

        colis.status = "ARRIVE"
        
        # --- SÉCURITÉ : Colis payé en Chine ---
        if colis.paye_en_chine:
            colis.reste_a_payer = 0
            colis.est_paye = True
        
        # --- SÉCURITÉ : Imputation automatique de l'avoir à l'arrivée (Celery) ---
        if colis.client and colis.client.solde_avoir > 0 and colis.reste_a_payer > 0:
            try:
                from notification.tasks import impute_avoir_colis_async

                impute_avoir_colis_async.delay(colis.id, request.user.id)
            except Exception as e:
                logger.error(
                    f"Erreur déclenchement imputation auto colis {colis.id}: {e}"
                )

        colis.save()

        # Notification immédiate au client avec rappel du prix
        try:
            from notification.tasks import send_notification_async
            from django.contrib.humanize.templatetags.humanize import intcomma

            if colis.client and colis.client.user:
                prix = colis.prix_final or 0
                jc = colis.montant_jc or 0
                montant_a_payer = max(0, prix - jc)
                fmt_prix = f"{montant_a_payer:,.0f}".replace(",", " ")

                date_arrive = timezone.now().strftime("%d/%m/%Y \u00e0 %H:%M")
                nom_pointage = (
                    colis.client.user.get_full_name() or colis.client.user.username
                )
                notif_msg = (
                    f"Bonjour *{nom_pointage}*,\n\n"
                    f"📍 *Bonne nouvelle ! Votre colis est arriv\u00e9 !*\n\n"
                    f"Nous venons de r\u00e9ceptionner votre colis *{colis.reference}* "
                    f"dans notre agence au Mali 🇲🇱 le *{date_arrive}*.\n\n"
                    f"💰 *Montant \u00e0 r\u00e9gler : {fmt_prix} FCFA*\n\n"
                    f"Merci de passer le r\u00e9cup\u00e9rer \u00e0 votre convenance.\n\n"
                    f"🌐 Suivez vos colis : https://ts-aircargo.com/login\n"
                    f"\u2014\u2014\n"
                    f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
                )
                send_notification_async.delay(
                    user_id=colis.client.user.id,
                    message=notif_msg,
                    categorie="colis_arrive",
                    titre=f"Colis {colis.reference} arrivé — {fmt_prix} FCFA à régler",
                    region="mali",
                )
        except Exception as e:
            import logging as _log

            _log.getLogger(__name__).error(
                f"Erreur notif pointage colis {colis.pk}: {e}"
            )

        if request.headers.get("HX-Request"):
            from django.shortcuts import render
            import json

            response = render(
                request,
                "mali/partials/colis_status_badge.html",
                {"colis": colis, "lot": colis.lot},
            )
            # Déclenche l'événement JS "colisArrived" écouté dans lot_transit_detail.html
            # → retire le <li id="colis-item-{pk}"> avec animation de sortie
            response["HX-Trigger"] = json.dumps({"colisArrived": {"pk": colis.pk}})
            return response

        messages.success(request, f"Colis {colis.reference} marqué comme Arrivé.")
        return redirect("mali:lot_transit_detail", pk=colis.lot.pk)


class ColisArriveBulkView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Marquer plusieurs colis comme ARRIVÉ (Pointage Groupé) et envoyer une seule notification par client"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)
        colis_ids = request.POST.getlist("colis_ids")

        if not colis_ids:
            messages.warning(request, "Aucun colis sélectionné.")
            return redirect("mali:lot_transit_detail", pk=lot.pk)

        # Restriction : frais de douane requis pour pointer
        if not lot.frais_douane:
            if request.headers.get("HX-Request"):
                from django.http import HttpResponse

                return HttpResponse(
                    '<div id="bulk-error" class="text-xs font-bold text-red-500 bg-red-50 p-2 rounded border border-red-200 mb-4">'
                    "⚠️ Veuillez renseigner les frais de douane du lot avant de pointer les colis."
                    "</div>",
                    status=400,
                )
            messages.error(
                request,
                "Veuillez renseigner les frais de douane du lot avant de pointer les colis.",
            )
            return redirect("mali:lot_transit_detail", pk=lot.pk)

        colis_qs = Colis.objects.filter(id__in=colis_ids, lot=lot, status="EXPEDIE")

        if not colis_qs.exists():
            if request.headers.get("HX-Request"):
                from django.http import HttpResponse

                return HttpResponse()
            return redirect("mali:lot_transit_detail", pk=lot.pk)

        # Get list of colis objects before updating status
        colis_list = list(colis_qs.select_related("client", "client__user"))

        # Mettre à jour le statut en masse
        for c in colis_list:
            c.status = "ARRIVE"
            if c.paye_en_chine:
                c.reste_a_payer = 0
                c.est_paye = True
            c.save()
        
        # --- NOUVEAU : Imputation automatique lors du pointage groupé (Celery) ---
        try:
            from notification.tasks import impute_avoir_colis_async

            for c in colis_list:
                if c.client and c.client.solde_avoir > 0 and c.reste_a_payer > 0:
                    impute_avoir_colis_async.delay(c.id, request.user.id)
        except Exception as e:
            logger.error(f"Erreur déclenchement imputation bulk lot {lot.id}: {e}")

        # Grouper les notifications par client pour envoi combiné
        from notification.tasks import send_notification_async

        by_client = {}
        for c in colis_list:
            if not c.client or not c.client.user:
                continue
            if c.client.id not in by_client:
                by_client[c.client.id] = {"user": c.client.user, "colis": []}
            by_client[c.client.id]["colis"].append(c)

        for cid, data in by_client.items():
            user = data["user"]
            client_colis = data["colis"]
            nb = len(client_colis)

            lines = []
            total = 0
            for c in client_colis:
                prix = max(0, (c.prix_final or 0) - (c.montant_jc or 0))
                total += prix
                fmt = f"{prix:,.0f}".replace(",", " ")

                details = ""
                if c.type_colis == "TELEPHONE":
                    details = f" - {c.nombre_pieces} unité(s)"
                elif c.poids:
                    details = f" - {c.poids} kg"

                lines.append(f"   \u2022 *{c.reference}*{details} — {fmt} FCFA")

            liste_str = "\n".join(lines)
            fmt_total = f"{total:,.0f}".replace(",", " ")
            nom_notify = user.get_full_name() or user.username

            date_arrive = timezone.now().strftime("%d/%m/%Y \u00e0 %H:%M")
            message = (
                f"Bonjour *{nom_notify}*,\n\n"
                f"📍 *{'Bonne nouvelle ! Votre colis est arrivé !' if nb == 1 else f'Bonne nouvelle ! Vos {nb} colis sont arrivés !'}*\n\n"
                f"Nous venons de réceptionner {'votre colis' if nb == 1 else 'vos colis'} à l'agence au Mali 🇲🇱 le *{date_arrive}* :\n"
                f"{liste_str}\n\n"
                f"💰 *Total \u00e0 r\u00e9gler : {fmt_total} FCFA*\n\n"
                f"Merci de passer {'le' if nb == 1 else 'les'} r\u00e9cup\u00e9rer \u00e0 votre convenance.\n\n"
                f"🌐 Suivez vos colis : https://ts-aircargo.com/login\n"
                f"\u2014\u2014\n"
                f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
            )

            try:
                send_notification_async.delay(
                    user_id=user.id,
                    message=message,
                    categorie="colis_arrive",
                    titre=f"{'Colis arrivé' if nb == 1 else f'{nb} colis arrivés'} — {fmt_total} FCFA à régler",
                    region="mali",
                )

                # Marquer comme notifié (sinon NotifyArrivalsView spammerait à nouveau)
                Colis.objects.filter(id__in=[c.id for c in client_colis]).update(
                    whatsapp_notified=True
                )

            except Exception as e:
                import logging as _log

                _log.getLogger(__name__).error(
                    f"Erreur notif bulk pointage colis lot {lot.pk}: {e}"
                )

        if request.headers.get("HX-Request"):
            from django.http import HttpResponse
            import json

            response = HttpResponse("")
            response["HX-Trigger"] = json.dumps(
                {"colisArrivedBulk": {"pks": [c.id for c in colis_list]}}
            )
            return response

        messages.success(request, f"{len(colis_list)} colis marqués comme Arrivés.")
        return redirect("mali:lot_transit_detail", pk=lot.pk)


class LotArriveView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Vue pour finaliser l'arrivée d'un lot et saisir les frais"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)

        # Mise à jour des frais (optionnel)
        frais_douane = request.POST.get("frais_douane")
        frais_transport = request.POST.get("frais_transport")

        if frais_douane:
            lot.frais_douane = frais_douane
        if frais_transport:
            lot.frais_transport = frais_transport

        # Enregistrer la date d'arrivée si pas encore définie
        if not lot.date_arrivee:
            lot.date_arrivee = timezone.now()

        lot.save()

        messages.success(
            request,
            f"Frais enregistrés pour le lot {lot.numero}. Vous pouvez maintenant pointer les colis.",
        )
        return redirect("mali:lot_transit_detail", pk=lot.pk)


class LotResetDouaneView(LoginRequiredMixin, AdminMaliRequiredMixin, View):
    """Vue pour annuler le renseignement des frais de douane et de transport (réinitialisation en Transit strict)"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)

        # Vérification stricte: Aucun colis ne doit être déjà arrivé, livré ou perdu
        pointed_colis_exists = lot.colis.filter(status__in=["ARRIVE", "LIVRE", "PERDU"]).exists()
        
        if pointed_colis_exists:
            messages.error(request, "Impossible d'annuler: des colis de ce lot ont déjà été pointés.")
            return redirect("mali:lot_transit_detail", pk=lot.pk)

        # Réinitialisation
        lot.frais_douane = None
        lot.date_arrivee = None
        lot.save()

        messages.success(request, f"Les frais du lot {lot.numero} ont été réinitialisés avec succès.")
        return redirect("mali:lot_transit_detail", pk=lot.pk)



class NotifyArrivalsView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Déclenche les notifications groupées pour les colis arrivés (pointés)"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)

        # Trouver les colis ARRIVE dans ce lot qui n'ont pas encore été notifiés par WhatsApp
        colis_to_notify = lot.colis.filter(
            status="ARRIVE", whatsapp_notified=False
        ).select_related("client", "client__user")

        if not colis_to_notify.exists():
            messages.warning(request, "Aucun nouveau colis pointé à notifier.")
            return redirect("mali:lot_transit_detail", pk=pk)

        # Grouper par client
        by_client = {}
        for c in colis_to_notify:
            if not c.client or not c.client.user:
                continue
            if c.client.id not in by_client:
                by_client[c.client.id] = {"user": c.client.user, "colis": []}
            by_client[c.client.id]["colis"].append(c)

        count_clients = 0
        from notification.tasks import send_notification_async

        for cid, data in by_client.items():
            user = data["user"]
            colis_list = data["colis"]
            nb = len(colis_list)

            # Construire la liste détaillée avec le prix de chaque colis
            lines = []
            total = 0
            for c in colis_list:
                prix = max(0, (c.prix_final or 0) - (c.montant_jc or 0))
                total += prix
                fmt = f"{prix:,.0f}".replace(",", " ")
                lines.append(f"   \u2022 *{c.reference}* — {fmt} FCFA")

            liste_str = "\n".join(lines)
            fmt_total = f"{total:,.0f}".replace(",", " ")

            nom_notify = user.get_full_name() or user.username
            message = (
                f"Bonjour *{nom_notify}*,\n\n"
                f"📍 *{'Bonne nouvelle ! Votre colis est arrivé !' if nb == 1 else f'Bonne nouvelle ! Vos {nb} colis sont arrivés !'}*\n\n"
                f"Nous venons de réceptionner {'votre colis' if nb == 1 else 'vos colis'} à l'agence au Mali 🇲🇱 :\n"
                f"{liste_str}\n\n"
                f"💰 *Total \u00e0 r\u00e9gler : {fmt_total} FCFA*\n\n"
                f"Merci de passer {'le' if nb == 1 else 'les'} récupérer à votre convenance.\n\n"
                f"🌐 Suivez vos colis : https://ts-aircargo.com/login\n"
                f"\u2014\u2014\n"
                f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
            )

            send_notification_async.delay(
                user_id=user.id,
                message=message,
                categorie="colis_arrive",
                titre=f"{'Colis arrivé' if nb == 1 else f'{nb} colis arrivés'} — {fmt_total} FCFA à régler",
                region="mali",
            )

            # Marquer comme notifié
            lot.colis.filter(id__in=[c.id for c in colis_list]).update(
                whatsapp_notified=True
            )
            count_clients += 1

        messages.success(request, f"Notifications envoyées à {count_clients} clients.")
        return redirect("mali:lot_transit_detail", pk=pk)


class ColisLivreView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Marquer un colis individuel comme LIVRÉ"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)

        # Sauvegarde du montant déjà payé pour calculer le versement du jour
        old_paid = (
            (colis.prix_final or 0)
            - (colis.montant_jc or 0)
            - (colis.reste_a_payer or 0)
        )

        # On ne peut livrer qu'un colis ARRIVÉ
        if colis.status != "ARRIVE":
            messages.error(request, "Seuls les colis déjà arrivés peuvent être livrés.")
            return redirect("mali:lot_arrived_detail", pk=colis.lot.pk)

        # Mise à jour des informations de livraison
        colis.mode_livraison = request.POST.get("mode_livraison", "AGENCE")
        colis.infos_recepteur = request.POST.get("infos_recepteur", "")
        colis.commentaire_livraison = request.POST.get("commentaire", "")

        # Gestion Sortie sous Garantie (Peut être forcé par le bouton dédié ou coché manuellement)
        if (
            request.POST.get("sortie_sous_garantie") == "on"
            or request.POST.get("is_sortie") == "true"
        ):
            colis.sortie_sous_garantie = True
            autorisee = request.POST.get("sortie_autorisee_par", "")
            colis.sortie_autorisee_par = autorisee
            if autorisee:
                from core.models import PersonneSortie
                PersonneSortie.objects.get_or_create(nom=autorisee)
        else:
            colis.sortie_sous_garantie = False
            colis.sortie_autorisee_par = ""

        # Gestion Jeton Cédé (ajout à un éventuel JC existant)
        try:
            jc_input = request.POST.get("montant_jc", "0")
            new_jc = float(jc_input) if jc_input else 0
            colis.montant_jc = (colis.montant_jc or 0) + new_jc
        except ValueError:
            pass

        # Gestion Paiement
        if colis.paye_en_chine:
            colis.est_paye = True
            colis.reste_a_payer = 0
        else:
            status_paiement = request.POST.get("status_paiement")
            if status_paiement == "PAYE":
                colis.est_paye = True
                colis.reste_a_payer = 0
            elif status_paiement == "PARTIEL":
                try:
                    encaisse_input = request.POST.get("montant_encaisse", "0")
                    encaisse = float(encaisse_input) if encaisse_input else 0
                    
                    from core.models import EncaissementColis as _EC
                    from django.db.models import Sum as _Sum
                    deja_encaisse = (
                        _EC.objects.filter(colis=colis).aggregate(t=_Sum("montant"))["t"] or 0
                    )
                    
                    colis.reste_a_payer = max(
                        0,
                        (colis.prix_final or 0) - (colis.montant_jc or 0) - deja_encaisse - encaisse,
                    )
                    colis.est_paye = colis.reste_a_payer <= 0
                except ValueError:
                    colis.reste_a_payer = max(0, (colis.prix_final or 0) - (colis.montant_jc or 0))
                    colis.est_paye = False
            else:  # ATTENTE ou autre
                colis.est_paye = False
                # Calcul absolu : on se base sur ce qui a RÉELLEMENT été encaissé en BDD
                from core.models import EncaissementColis as _EC
                from django.db.models import Sum as _Sum
                deja_encaisse = (
                    _EC.objects.filter(colis=colis).aggregate(t=_Sum("montant"))["t"] or 0
                )
                colis.reste_a_payer = max(
                    0,
                    (colis.prix_final or 0) - (colis.montant_jc or 0) - deja_encaisse,
                )

        colis.mode_paiement = request.POST.get("mode_paiement")
        colis.status = "LIVRE"
        colis.date_livraison = (
            request.POST.get("date_livraison") or timezone.now().date()
        )

        if colis.est_paye or status_paiement == "PARTIEL":
            colis.date_encaissement = (
                request.POST.get("date_encaissement") or timezone.now().date()
            )

        colis.save()

        # Création de l'encaissement si un montant a été versé
        new_paid = (
            (colis.prix_final or 0)
            - (colis.montant_jc or 0)
            - (colis.reste_a_payer or 0)
        )
        amount_paid = new_paid - old_paid

        if amount_paid > 0 and not colis.paye_en_chine:
            EncaissementColis.objects.create(
                colis=colis,
                montant=amount_paid,
                date=colis.date_encaissement or timezone.now().date(),
                methode=colis.mode_paiement or "ESPECE",
                enregistre_par=request.user,
            )

        # Notification... (unchanged logic)

        # Notification Livraison (Async)
        try:
            from notification.tasks import send_notification_async

            if colis.client and colis.client.user:
                nom_livre = (
                    colis.client.user.get_full_name() or colis.client.user.username
                )
                message = (
                    f"Bonjour *{nom_livre}*,\n\n"
                    f"\u2705 *Livraison r\u00e9ussie !*\n\n"
                    f"Votre colis *{colis.reference}* a bien \u00e9t\u00e9 livr\u00e9 avec succ\u00e8s.\n\n"
                    f"Merci d'avoir choisi TS AIR CARGO pour vos envois !\n"
                    f"Nous esp\u00e9rons vous revoir tr\u00e8s prochainement. 😊\n\n"
                    f"🌐 Cr\u00e9ez une nouvelle commande : https://ts-aircargo.com/login\n"
                    f"\u2014\u2014\n"
                    f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
                )
                send_notification_async.delay(
                    user_id=colis.client.user.id,
                    message=message,
                    categorie="colis_livre",
                    titre=f"Livraison effectuée - {colis.reference}",
                    region="mali",
                )
        except Exception as e:
            from chine.views import logger

            logger.error(f"Erreur trigger notification livraison {colis.id}: {e}")

        if request.headers.get("HX-Request"):
            from django.shortcuts import render
            from django.http import HttpResponse

            # Check if we are in transit mode context (sent by hidden input)
            if request.POST.get("context") == "transit":
                return HttpResponse(
                    f'<li id="colis-item-{colis.pk}" hx-swap-oob="delete"></li>'
                )

            return render(
                request,
                "mali/partials/colis_status_badge.html",
                {"colis": colis, "lot": colis.lot},
            )

        messages.success(request, f"Colis {colis.reference} livré avec succès.")
        return redirect("mali:lot_arrived_detail", pk=colis.lot.pk)


class ColisLivreBulkView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Marquer plusieurs colis comme LIVRÉ (Livraison Groupée) avec configuration"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)
        colis_ids = request.POST.getlist("colis_ids")

        status_paiement = request.POST.get("status_paiement", "ATTENTE")
        mode_paiement = request.POST.get("mode_paiement", "ESPECE")
        mode_livraison = request.POST.get("mode_livraison", "AGENCE")
        infos_recepteur = request.POST.get("infos_recepteur", "")

        # New date fields
        date_livraison = request.POST.get("date_livraison") or timezone.now().date()
        date_encaissement = (
            request.POST.get("date_encaissement") or timezone.now().date()
        )

        if not colis_ids:
            messages.warning(request, "Aucun colis sélectionné pour la livraison.")
            return redirect("mali:lot_arrived_detail", pk=lot.pk)

        colis_qs = Colis.objects.filter(id__in=colis_ids, lot=lot, status="ARRIVE")
        
        # Si un seul colis, on peut capturer le montant_jc (remise)
        montant_jc = Decimal("0")
        if len(colis_ids) == 1:
            try:
                montant_jc = Decimal(request.POST.get("montant_jc", "0") or "0")
            except Exception:
                montant_jc = Decimal("0")

        # Sécurité Backend : Un seul client par livraison en masse
        if colis_qs.values("client").distinct().count() > 1:
            messages.error(request, "Erreur de sécurité : Vous ne pouvez pas livrer des colis de clients différents en une seule fois.")
            return redirect("mali:lot_arrived_detail", pk=lot.pk)

        if not colis_qs.exists():
            if request.headers.get("HX-Request"):
                return HttpResponse()
            return redirect("mali:lot_arrived_detail", pk=lot.pk)

        colis_list = list(colis_qs.select_related("client", "client__user"))

        # Calcul pour paiement partiel global
        if status_paiement == "PARTIEL":
            try:
                montant_encaisse_global = Decimal(
                    request.POST.get("montant_encaisse", "0") or "0"
                )
            except Exception:
                montant_encaisse_global = Decimal("0")

            total_net_selection = sum(
                (c.prix_final or Decimal("0")) - (c.montant_jc or Decimal("0"))
                for c in colis_list
                if not c.paye_en_chine
            )
            reste_global = max(
                Decimal("0"), total_net_selection - montant_encaisse_global
            )
        else:
            total_net_selection = Decimal("0")
            reste_global = Decimal("0")

        # Sauvegarde des montants RÉELLEMENT encaissés pour chaque colis (base absolue)
        from core.models import EncaissementColis as _BulkEC
        from django.db.models import Sum as _BulkSum
        encaissement_sums = (
            _BulkEC.objects.filter(colis__in=colis_list)
            .values("colis_id")
            .annotate(total=_BulkSum("montant"))
        )
        old_paid_map = {row["colis_id"]: row["total"] or 0 for row in encaissement_sums}

        for c in colis_list:
            c.status = "LIVRE"
            c.mode_livraison = mode_livraison
            c.mode_paiement = mode_paiement
            c.infos_recepteur = infos_recepteur
            c.updated_at = timezone.now()
            
            # Application de la remise si 1 seul colis
            if len(colis_list) == 1:
                c.montant_jc = (c.montant_jc or Decimal("0")) + montant_jc

            # Application des dates
            if date_livraison:
                c.date_livraison = date_livraison

            if c.paye_en_chine:
                c.est_paye = True
                c.reste_a_payer = 0
            else:
                if status_paiement == "PAYE":
                    c.est_paye = True
                    c.reste_a_payer = 0
                elif status_paiement == "PARTIEL":
                    # Distribution proportionnelle du reste, en prenant en compte le JC
                    total_net_selection = sum(
                        (col.prix_final or Decimal("0")) - (col.montant_jc or Decimal("0"))
                        for col in colis_list if not col.paye_en_chine
                    )
                    
                    if total_net_selection > Decimal("0"):
                        part_colis = (c.prix_final or Decimal("0")) - (
                            c.montant_jc or Decimal("0")
                        )
                        share = part_colis / total_net_selection
                        
                        try:
                            encaisse_global = Decimal(request.POST.get("montant_encaisse", "0") or "0")
                        except Exception:
                            encaisse_global = Decimal("0")
                            
                        reste_global = max(Decimal("0"), total_net_selection - encaisse_global)
                        
                        c.reste_a_payer = (reste_global * share).quantize(Decimal("1"))
                    else:
                        c.reste_a_payer = Decimal("0")
                    c.est_paye = c.reste_a_payer <= Decimal("0")
                else:  # ATTENTE
                    c.est_paye = False
                    # Calcul absolu : on préserve les paiements partiels déjà encaissés en BDD
                    deja_encaisse_c = Decimal(str(old_paid_map.get(c.id, 0)))
                    c.reste_a_payer = max(
                        Decimal("0"),
                        (c.prix_final or Decimal("0"))
                        - (c.montant_jc or Decimal("0"))
                        - deja_encaisse_c,
                    )

                # Assign date_encaissement if paid fully or partially
                if c.est_paye or status_paiement == "PARTIEL":
                    if date_encaissement:
                        c.date_encaissement = date_encaissement

        Colis.objects.bulk_update(
            colis_list,
            [
                "status",
                "mode_livraison",
                "est_paye",
                "reste_a_payer",
                "mode_paiement",
                "infos_recepteur",
                "date_livraison",
                "date_encaissement",
                "montant_jc",
                "updated_at",
            ],
        )

        # Création des encaissements en masse
        encaissements_to_create = []
        for c in colis_list:
            new_paid = (
                (c.prix_final or 0) - (c.montant_jc or 0) - (c.reste_a_payer or 0)
            )
            diff = new_paid - old_paid_map.get(c.id, 0)
            if diff > 0 and not c.paye_en_chine:
                encaissements_to_create.append(
                    EncaissementColis(
                        colis=c,
                        montant=diff,
                        date=c.date_encaissement or timezone.now().date(),
                        methode=c.mode_paiement or "ESPECE",
                        enregistre_par=request.user,
                    )
                )

        if encaissements_to_create:
            EncaissementColis.objects.bulk_create(encaissements_to_create)

        # Grouper les notifications
        from notification.tasks import send_notification_async

        by_client = {}
        for c in colis_list:
            if not c.client or not c.client.user:
                continue
            if c.client.id not in by_client:
                by_client[c.client.id] = {"user": c.client.user, "colis": []}
            by_client[c.client.id]["colis"].append(c)

        for cid, data in by_client.items():
            user = data["user"]
            client_colis = data["colis"]
            nb = len(client_colis)

            nom_livre = user.get_full_name() or user.username
            lines = []
            for c in client_colis:
                details = ""
                if c.type_colis == "TELEPHONE":
                    details = f" - {c.nombre_pieces} unité(s)"
                elif c.poids:
                    details = f" - {c.poids} kg"
                lines.append(f"   \u2022 *{c.reference}*{details}")

            liste_str = "\n".join(lines)
            message = (
                f"Bonjour *{nom_livre}*,\n\n"
                f"✅ *{'Livraison réussie !' if nb == 1 else f'Livraison réussie pour vos {nb} colis !'}*\n\n"
                f"{'Le colis suivant a' if nb == 1 else 'Les colis suivants ont'} bien été livré{'s' if nb > 1 else ''} avec succès :\n"
                f"{liste_str}\n\n"
                f"Merci d'avoir choisi TS AIR CARGO pour vos envois !\n"
                f"Nous esp\u00e9rons vous revoir tr\u00e8s prochainement. 😊\n\n"
                f"🌐 Cr\u00e9ez une nouvelle commande : https://ts-aircargo.com/login\n"
                f"\u2014\u2014\n"
                f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
            )

            try:
                send_notification_async.delay(
                    user_id=user.id,
                    message=message,
                    categorie="colis_livre",
                    titre=f"Livraison effectuée - {nb} colis",
                    region="mali",
                )
            except Exception as e:
                logger.error(f"Erreur notif bulk livraison lot {lot.pk}: {e}")

        if request.headers.get("HX-Request"):
            import json

            response = HttpResponse("")
            response["HX-Trigger"] = json.dumps(
                {"colisLivreBulk": {"pks": [c.id for c in colis_list]}}
            )
            return response

        messages.success(request, f"{len(colis_list)} colis livrés avec succès.")
        return redirect("mali:lot_arrived_detail", pk=lot.pk)


class ColisSortieBulkView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Marquer plusieurs colis en SORTIE SOUS GARANTIE"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)
        colis_ids = request.POST.getlist("colis_ids")
        autorise_par = request.POST.get("sortie_autorisee_par", "")
        date_livraison = request.POST.get("date_livraison") or timezone.now().date()

        if not colis_ids:
            messages.warning(request, "Aucun colis sélectionné.")
            return redirect("mali:lot_arrived_detail", pk=lot.pk)

        colis_qs = Colis.objects.filter(id__in=colis_ids, lot=lot, status="ARRIVE")
        
        # Sécurité Backend : Un seul client par sortie groupée
        if colis_qs.values("client").distinct().count() > 1:
            messages.error(request, "Erreur de sécurité : Les sorties groupées ne sont autorisées que pour un seul client.")
            return redirect("mali:lot_arrived_detail", pk=lot.pk)
            
        colis_list = list(colis_qs)

        for c in colis_list:
            c.status = "LIVRE"
            c.sortie_sous_garantie = True
            c.sortie_autorisee_par = autorise_par
            c.date_livraison = date_livraison
            c.est_paye = False
            c.reste_a_payer = max(0, (c.prix_final or 0) - (c.montant_jc or 0))

        Colis.objects.bulk_update(
            colis_list,
            [
                "status",
                "sortie_sous_garantie",
                "sortie_autorisee_par",
                "date_livraison",
                "est_paye",
                "reste_a_payer",
            ],
        )

        if request.headers.get("HX-Request"):
            import json

            response = HttpResponse("")
            response["HX-Trigger"] = json.dumps(
                {"colisLivreBulk": {"pks": [c.id for c in colis_list]}}
            )
            return response

        messages.success(request, f"{len(colis_list)} colis sortis sous garantie.")
        return redirect("mali:lot_arrived_detail", pk=lot.pk)


class ColisPerduView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Marquer un colis comme PERDU"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)
        colis.status = "PERDU"
        colis.save()

        if request.headers.get("HX-Request"):
            from django.http import HttpResponse

            return HttpResponse(
                f'<li id="colis-item-{colis.pk}" hx-swap-oob="delete"></li>'
            )

        messages.warning(request, f"Colis {colis.reference} marqué comme PERDU.")
        return redirect("mali:lot_arrived_detail", pk=colis.lot.pk)


class ColisAttentePaiementView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, ListView
):
    """Liste des colis LIVRÉS mais NON PAYÉS"""

    template_name = "mali/colis_attente_paiement.html"
    context_object_name = "colis_list"
    paginate_by = 20

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Colis.objects.none()

        from django.db.models import F, Case, When, DecimalField

        queryset = (
            Colis.objects.filter(lot__destination=mali, status="LIVRE", est_paye=False)
            .select_related("client", "lot")
            .annotate(
                montant_du=Case(
                    When(reste_a_payer__gt=0, then=F("reste_a_payer")),
                    default=F("prix_final") - F("montant_jc"),
                    output_field=DecimalField(),
                )
            )
            .annotate(
                sort_date=Coalesce(
                    "date_livraison", "updated_at", output_field=DateField()
                )
            )
            .order_by("-sort_date", "-updated_at")
        )

        # Filtre par mois/année
        year = self.request.GET.get("year")
        month = self.request.GET.get("month")
        if year:
            try:
                queryset = queryset.filter(date_livraison__year=int(year))
            except (ValueError, TypeError):
                pass
        if month:
            try:
                queryset = queryset.filter(date_livraison__month=int(month))
            except (ValueError, TypeError):
                pass

        query = self.request.GET.get("q")
        if query:
            queryset = apply_flexible_search(
                queryset, query, ["client__nom", "client__prenom", "reference"]
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()

        # Calcul du total des impayés basé sur l'annotation
        total_impaye = (
            self.get_queryset().aggregate(total=Sum("montant_du"))["total"] or 0
        )
        context["total_impaye"] = total_impaye
        context["q"] = self.request.GET.get("q", "")
        context["selected_year"] = self.request.GET.get("year", "")
        context["selected_month"] = self.request.GET.get("month", "")
        context["years"] = list(range(now.year, now.year - 5, -1))
        context["months"] = [
            (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"),
            (5, "Mai"), (6, "Juin"), (7, "Juillet"), (8, "Août"),
            (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
        ]
        return context


class ColisEncaissementView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Encaisser un colis (marquer comme payé) avec mise à jour de la date"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)

        # Calcul du montant payé (le reste à payer actuel)
        amount_paid = colis.reste_a_payer or 0

        # Marquer comme payé et solder le reste à payer
        colis.est_paye = True
        colis.reste_a_payer = 0

        # Date d'encaissement (depuis POST ou aujourd'hui)
        date_enc = request.POST.get("date_encaissement")
        if date_enc:
            colis.date_encaissement = date_enc
        else:
            colis.date_encaissement = timezone.now().date()

        # Si le colis était à l'état ARRIVE et est maintenant totalement payé,
        # on le marque automatiquement comme LIVRE (retiré par le client)
        if colis.status == "ARRIVE":
            colis.status = "LIVRE"
            colis.date_livraison = colis.date_encaissement

        # Nom du payeur
        infos_recepteur = request.POST.get("infos_recepteur")
        if infos_recepteur:
            colis.infos_recepteur = infos_recepteur

        colis.save()

        # Création de l'encaissement si un montant a été versé
        if amount_paid > 0 and not colis.paye_en_chine:
            EncaissementColis.objects.create(
                colis=colis,
                montant=amount_paid,
                date=colis.date_encaissement or timezone.now().date(),
                methode=colis.mode_paiement or "ESPECE",
                enregistre_par=request.user,
            )

        messages.success(request, f"Paiement encaissé pour le colis {colis.reference}.")

        # Redirection vers la liste des paiements en attente (ou la page précédente)
        return redirect("mali:colis_attente_paiement")


class ColisSolderJCView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Solder manuellement un reste à payer par Jeton Cédé (JC)"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)
        reste = colis.reste_a_payer or 0

        if reste > 0:
            # On bascule le reste à payer dans le Jeton Cédé
            colis.montant_jc = (colis.montant_jc or 0) + reste
            colis.reste_a_payer = 0
            colis.est_paye = True

            # Note: On ne touche pas à date_encaissement ici pour ne pas 
            # faire apparaître d'encaissement fictif dans le rapport journalier 
            # (particulièrement pour les colis legacy).
            colis.save()
            messages.success(
                request, 
                f"Le colis {colis.reference} a été totalement soldé par Jeton Cédé ({reste:,.0f} FCFA)."
            )
        else:
            messages.warning(request, f"Le colis {colis.reference} n'a pas de reste à payer à solder.")

        return redirect("mali:colis_attente_paiement")


class ColisAnnulerJCView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Annuler un Jeton Cédé (JC) pour remettre le colis en attente de paiement"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)
        montant = colis.montant_jc or 0

        if montant > 0:
            # On remet le montant JC à 0. Le reste à payer et est_paye seront recalculés 
            # automatiquement par save() à partir des encaissements réels restés intacts.
            colis.montant_jc = 0
            colis.save()
            
            messages.success(
                request, 
                f"Le jeton cédé pour le colis {colis.reference} a été annulé ({montant:,.0f} FCFA). Le colis est retourné dans les paiements en attente."
            )
        else:
            messages.warning(request, f"Le colis {colis.reference} n'a pas de jeton cédé à annuler.")

        return redirect("mali:colis_attente_paiement")


class ColisEncaissementBulkView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, View
):
    """Encaisser plusieurs colis en masse avec gestion optionnelle du paiement partiel global"""

    def post(self, request):
        colis_ids = request.POST.getlist("colis_ids")
        mode_paiement = request.POST.get("mode_paiement", "ESPECE")
        date_encaissement = (
            request.POST.get("date_encaissement") or timezone.now().date()
        )
        infos_recepteur = request.POST.get("infos_recepteur", "").strip()

        if not colis_ids:
            messages.warning(request, "Aucun colis sélectionné.")
            return redirect("mali:colis_attente_paiement")

        # Validation : Un seul client autorisé pour l'encaissement en masse
        colis_check_qs = Colis.objects.filter(id__in=colis_ids)
        if colis_check_qs.values("client").distinct().count() > 1:
            messages.error(
                request,
                "L'encaissement en masse n'est possible que pour les colis d'un même client. Veuillez filtrer par client.",
            )
            return redirect("mali:colis_attente_paiement")

        # Récupération du montant total reçu (pour paiement partiel groupé)
        montant_total_recu_str = request.POST.get("montant_total_recu", "").strip()
        if not montant_total_recu_str:
            is_partial_bulk = False
            montant_restant = None
        else:
            try:
                montant_restant = Decimal(montant_total_recu_str)
                is_partial_bulk = True
            except Exception:
                is_partial_bulk = False
                montant_restant = None

        # On trie par montant décroissant (plus gros d'abord)
        colis_qs = colis_check_qs.filter(
            status__in=["LIVRE", "ARRIVE"], 
            est_paye=False
        ).order_by("-reste_a_payer", "-id")
        colis_list = list(colis_qs)

        encaissements_to_create = []
        colis_to_update = []

        total_encaisse_reel = 0
        nb_colis_soldes = 0

        colis_sautes_pour_reliquat = []

        # PREMIÈRE PASSE : Solder ce qu'on peut entièrement en priorité sur les gros montants
        for c in colis_list:
            if not is_partial_bulk:
                # Encaissement total classique (mode normal)
                paiement_colis = c.reste_a_payer or 0
            else:
                attendu = c.reste_a_payer or 0
                if attendu <= montant_restant:
                    # On a assez pour solder entièrement
                    paiement_colis = attendu
                    montant_restant -= paiement_colis
                else:
                    # On n'a pas assez pour solder ENTIEREMENT, on saute pour tester les suivants
                    # (Mais on garde le colis en mémoire s'il est le dernier possible pour le reliquat)
                    colis_sautes_pour_reliquat.append(c)
                    continue

            if paiement_colis > 0:
                # Mise à jour du colis
                c.reste_a_payer = (c.reste_a_payer or 0) - paiement_colis
                if c.reste_a_payer <= 0:
                    c.est_paye = True
                    c.reste_a_payer = 0
                    nb_colis_soldes += 1
                    if c.status == "ARRIVE":
                        c.status = "LIVRE"
                        c.date_livraison = date_encaissement

                c.mode_paiement = mode_paiement
                c.date_encaissement = date_encaissement
                if infos_recepteur:
                    c.infos_recepteur = infos_recepteur
                c.updated_at = timezone.now()
                colis_to_update.append(c)

                # Création de la transaction
                encaissements_to_create.append(
                    EncaissementColis(
                        colis=c,
                        montant=paiement_colis,
                        date=date_encaissement,
                        methode=mode_paiement,
                        enregistre_par=request.user,
                    )
                )
                total_encaisse_reel += paiement_colis

        # DEUXIÈME PASSE : S'il reste un reliquat, on l'applique au plus petit colis possible (le dernier sauté)
        if is_partial_bulk and montant_restant > 0 and colis_sautes_pour_reliquat:
            # On prend le dernier colis de la liste sautée (le plus petit car la liste est décroissante)
            c = colis_sautes_pour_reliquat[-1]
            paiement_colis = montant_restant
            montant_restant = 0  # Tout consommé

            c.reste_a_payer = (c.reste_a_payer or 0) - paiement_colis
            if c.reste_a_payer <= 0:
                c.est_paye = True
                c.reste_a_payer = 0
                nb_colis_soldes += 1
                if c.status == "ARRIVE":
                    c.status = "LIVRE"
                    c.date_livraison = date_encaissement

            c.mode_paiement = mode_paiement
            c.date_encaissement = date_encaissement
            c.updated_at = timezone.now()
            colis_to_update.append(c)

            encaissements_to_create.append(
                EncaissementColis(
                    colis=c,
                    montant=paiement_colis,
                    date=date_encaissement,
                    methode=mode_paiement,
                    enregistre_par=request.user,
                )
            )
            total_encaisse_reel += paiement_colis

        if colis_to_update:
            # Note: il faut s'assurer de ne pas avoir de doublons dans colis_to_update si un colis était traité deux fois (normalement non ici)
            Colis.objects.bulk_update(
                colis_to_update,
                [
                    "est_paye",
                    "reste_a_payer",
                    "mode_paiement",
                    "date_encaissement",
                    "updated_at",
                    "status",
                    "date_livraison",
                ],
            )

        if encaissements_to_create:
            EncaissementColis.objects.bulk_create(encaissements_to_create)

        if is_partial_bulk:
            suffixe = (
                f" ({nb_colis_soldes} soldés totalement)" if nb_colis_soldes > 0 else ""
            )
            msg = f"Encaissement de {total_encaisse_reel:,.0f} FCFA avec priorité aux gros montants{suffixe}."
        else:
            msg = f"{len(colis_list)} colis encaissés totalement ({mode_paiement})."

        messages.success(request, msg)
        return redirect("mali:colis_attente_paiement")


class RapportJourPDFView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Génération du rapport journalier en PDF (xhtml2pdf)"""

    def get(self, request):
        # Date du rapport
        date_str = request.GET.get("date")
        if date_str:
            try:
                from datetime import datetime

                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                target_date = timezone.now().date()
        else:
            target_date = timezone.now().date()

        today = target_date
        report_type = request.GET.get(
            "type", "global"
        )  # global, cargo, express, bateau

        # Titre du rapport selon le type
        titre_rapport = "Rapport Journalier Global"
        if report_type == "cargo":
            titre_rapport = "Rapport Journalier - CARGO"
        elif report_type == "express":
            titre_rapport = "Rapport Journalier - EXPRESS"
        elif report_type == "bateau":
            titre_rapport = "Rapport Journalier - BATEAU"

        # --- 1. CALCULS FINANCIERS VIA LE MOTEUR CENTRALISÉ ---
        mali = self.get_current_country()
        fin_stats = FinanceEngine.get_daily_summary(today, mali)
        
        # --- 2. IDENTIFICATION DES COLIS DU JOUR ---
        colis_livres_jour_base = (
            Colis.objects.filter(lot__destination=mali)
            .filter(
                Q(encaissements__date=today) | 
                Q(date_encaissement=today) |
                Q(status="LIVRE", date_livraison=today, date_encaissement__isnull=True) |
                Q(updated_at__date=today, montant_jc__gt=0)
            )
            .distinct()
        )

        if report_type in ["cargo", "express", "bateau"]:
            colis_livres_jour_base = colis_livres_jour_base.filter(
                lot__type_transport=report_type.upper()
            )

        # Annotation identique à la vue Aujourd'hui
        enc_day_qs = EncaissementColis.objects.filter(colis=OuterRef("pk"), date=today)
        enc_day_hors_avance_qs = enc_day_qs.exclude(methode="AVANCE")

        sum_enc_day = enc_day_qs.values("colis").annotate(total=Sum("montant")).values("total")
        sum_enc_day_hors_avance = enc_day_hors_avance_qs.values("colis").annotate(total=Sum("montant")).values("total")
        latest_enc = enc_day_qs.order_by("-created_at")

        colis_qs = (
            colis_livres_jour_base.select_related("client", "lot")
            .annotate(
                heure_paiement=Subquery(latest_enc.values("created_at")[:1]),
                sum_enc=Coalesce(Subquery(sum_enc_day[:1]), Value(0), output_field=DecimalField()),
                sum_enc_hors_avance=Coalesce(Subquery(sum_enc_day_hors_avance[:1]), Value(0), output_field=DecimalField()),
                val_legacy=Case(
                    When(date_encaissement=today, encaissements__isnull=True, then=F("prix_final") - Coalesce(F("montant_jc"), Value(0))),
                    default=Value(0),
                    output_field=DecimalField()
                ),
                montant_paye_jour=F("sum_enc") + F("val_legacy"),
                montant_paye_jour_hors_avance=F("sum_enc_hors_avance") + F("val_legacy"),
                net_price=F("montant_paye_jour")
            )
            .order_by("-heure_paiement", "-date_livraison", "-updated_at")
        )

        # Totaux pour le rapport
        total_encaissements = Decimal(0)
        if report_type == "global":
            total_encaissements = fin_stats["total_encaissements_colis"]
        else:
            # Pour les rapports spécifiques, on somme les encaissements du jour pour ce type
            total_encaissements = colis_qs.aggregate(total=Sum("montant_paye_jour"))["total"] or 0

        total_jc = colis_qs.aggregate(total=Sum("montant_jc"))["total"] or 0
        total_poids = colis_qs.aggregate(total=Sum("poids"))["total"] or 0
        
        solde_veille = fin_stats["solde_veille"]
        solde_final = fin_stats["solde_caisse_actuel"]
        
        total_depenses = fin_stats["total_depenses"]
        total_transferts = fin_stats["total_transferts"]
        rechargements_avoir_jour = fin_stats["total_rechargements_avoir"]

        # Contexte pour le template
        context = {
            "date": today,
            "report_type": report_type,
            "titre_rapport": titre_rapport,
            "colis_list": colis_qs,
            "total_encaissements": total_encaissements,
            "rechargements_avoir_jour": rechargements_avoir_jour,
            "rechargements_avoir_list": (
                AvoirMouvement.objects.filter(
                    client__country=mali, type="DEPOT", created_at__date=today
                ).select_related("client")
                if report_type == "global"
                else []
            ),
            "total_jc": total_jc,
            "total_depenses": total_depenses,
            "total_transferts": total_transferts,
            "total_poids": total_poids,
            "solde_veille": solde_veille,
            "solde_final": solde_final,
            "user": request.user,
        }

        # Génération du PDF avec Playwright
        from core.utils_pdf import render_to_pdf_playwright

        # Vérifier si le template attend 'colis_livres' ou 'colis_list'
        context["colis_livres"] = colis_qs

        filename = f"rapport_jour_{report_type}_{today}.pdf"
        return render_to_pdf_playwright(
            "mali/pdf/rapport_jour.html", context, request, filename=filename
        )


class LotTransitPDFView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Génération du manifeste de lot en PDF"""

    def get(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)

        # Colis du lot triés par référence ou client
        colis_list = lot.colis.all().select_related("client").order_by("reference")

        context = {
            "lot": lot,
            "colis_list": colis_list,
            "total_poids": lot.colis.aggregate(Sum("poids"))["poids__sum"] or 0,
            "total_cbm": lot.colis.aggregate(Sum("cbm"))["cbm__sum"] or 0,
            "total_colis": lot.colis.count(),
            "user": request.user,
            "date_impression": timezone.now(),
        }

        from core.utils_pdf import render_to_pdf_playwright

        filename = f"manifeste_lot_{lot.numero}.pdf"
        # Utilisation de l'orientation paysage si nécessaire pour les manifestes (souvent plus large)
        return render_to_pdf_playwright(
            "mali/pdf/manifeste_lot.html", context, request, filename=filename
        )


class NotificationConfigView(LoginRequiredMixin, AdminMaliRequiredMixin, UpdateView):
    """
    Permet à l'agent Mali de configurer les rappels automatiques.
    NB : La configuration des credentials API WaChap est gestion de l'admin_app.
    """

    model = ConfigurationNotification
    form_class = NotificationConfigForm  # Rappels uniquement
    template_name = "mali/config_notifications.html"
    success_url = reverse_lazy("mali:dashboard")

    def get_object(self, queryset=None):
        return ConfigurationNotification.get_solo()

    def form_valid(self, form):
        messages.success(self.request, "✅ Configuration des rappels mise à jour.")
        return super().form_valid(form)


class MaliNotificationListView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, ListView
):
    """Gestionnaire de notifications WhatsApp pour l'agent Mali (region='mali')"""

    template_name = "mali/notifications/list.html"
    context_object_name = "notifications"
    paginate_by = 50

    def get_queryset(self):
        from notification.models import Notification

        queryset = Notification.objects.filter(region="mali").order_by("-date_creation")

        # Filtres
        status = self.request.GET.get("status")
        date_start = self.request.GET.get("date_start")
        date_end = self.request.GET.get("date_end")
        q = self.request.GET.get("q")

        if status:
            queryset = queryset.filter(statut=status)
        if date_start:
            queryset = queryset.filter(date_creation__date__gte=date_start)
        if date_end:
            queryset = queryset.filter(date_creation__date__lte=date_end)
        if q:
            queryset = queryset.filter(
                Q(telephone_destinataire__icontains=q)
                | Q(message__icontains=q)
                | Q(erreur_envoi__icontains=q)
            )
        return queryset

    def get_context_data(self, **kwargs):
        from notification.models import Notification

        context = super().get_context_data(**kwargs)
        context["stats_notif"] = Notification.objects.filter(region="mali").aggregate(
            total=Count("id"),
            envoye=Count("id", filter=Q(statut="envoye")),
            echec=Count("id", filter=Q(statut="echec")),
            echec_permanent=Count("id", filter=Q(statut="echec_permanent")),
        )
        return context

    def post(self, request, *args, **kwargs):
        from notification.models import Notification

        action = request.POST.get("action")
        selected_ids = request.POST.getlist("selected_ids")

        single_id = request.POST.get("notification_id")
        if single_id and not selected_ids:
            selected_ids = [single_id]

        next_url = request.POST.get("next")
        base_url = reverse_lazy("mali:notification_list")

        if not selected_ids:
            messages.warning(request, "Aucune notification sélectionnée.")
            return redirect(f"{base_url}?{next_url}" if next_url else base_url)

        if action == "delete":
            deleted_count, _ = Notification.objects.filter(
                id__in=selected_ids, region="mali"
            ).delete()
            messages.success(request, f"{deleted_count} notification(s) supprimée(s).")

        elif action == "retry":
            from notification.tasks import retry_failed_notifications_periodic

            updated = Notification.objects.filter(
                id__in=selected_ids, region="mali"
            ).update(
                statut="echec", nombre_tentatives=0, prochaine_tentative=timezone.now()
            )
            retry_failed_notifications_periodic.delay(force_retry_all=True)
            messages.success(request, f"{updated} notification(s) relancée(s).")

        return redirect(f"{base_url}?{next_url}" if next_url else base_url)


class MaliRetryNotificationsView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Relance toutes les notifications en échec pour la région Mali"""

    def post(self, request):
        from notification.tasks import retry_failed_notifications_periodic

        retry_failed_notifications_periodic.delay(force_retry_all=True, region="mali")
        messages.success(request, "Les relances WhatsApp Mali ont été déclenchées.")
        return redirect("mali:notification_list")


from django.views.generic import UpdateView
from .forms import ColisUpdateMaliForm


class ColisUpdateMaliView(LoginRequiredMixin, DestinationAgentRequiredMixin, UpdateView):
    """Permet aux agents Mali de corriger le poids, le CBM ou le prix d'un colis."""

    model = Colis
    form_class = ColisUpdateMaliForm
    template_name = "mali/colis_update.html"

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        # Autoriser la modification si le lot a quitté la Chine et n'est pas encore livré
        if obj.lot.status in ["OUVERT", "FERME"]:
            messages.error(
                request,
                "La modification n'est pas possible tant que le lot est encore en préparation en Chine.",
            )
            return redirect("mali:admin_dashboard")

        if obj.status == "LIVRE":
            messages.error(
                request,
                "La modification est interdite pour les colis déjà livrés.",
            )
            return redirect("mali:lot_livre_detail", pk=obj.lot.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        lot = self.object.lot
        messages.success(
            self.request,
            f"Le carton {self.object.reference} a été corrigé avec succès.",
        )
        # Redirection systématique vers le détail du lot arrivé au Mali
        return reverse("mali:lot_arrived_detail", kwargs={"pk": lot.pk})

    def form_valid(self, form):
        # On sauvegarde les anciennes valeurs pour conserver ce qui a été encaissé
        old_colis = self.get_object()

        # Calcul absolu : somme des encaissements RÉELS enregistrés en BDD pour ce colis
        from core.models import EncaissementColis as _UpdateEC
        from django.db.models import Sum as _UpdateSum
        deja_encaisse = (
            _UpdateEC.objects.filter(colis=old_colis).aggregate(t=_UpdateSum("montant"))["t"] or 0
        )

        # Sauvegarde du formulaire (sans commit pour ajuster le type)
        colis = form.save(commit=False)

        # Si un prix manuel est saisi, on adapte le type de colis si nécessaire
        if colis.prix_kilo_manuel:
            if colis.type_colis not in ["TELEPHONE", "ELECTRONIQUE"] and colis.lot.type_transport != "BATEAU":
                colis.type_colis = "MANUEL"

        # Recalculer les prix via la méthode centrale du modèle
        colis.recalculate_prices()

        # Ajuster le reste à payer en fonction du nouveau prix et de ce qui a RÉELLEMENT été encaissé
        colis.reste_a_payer = (colis.prix_final or 0) - (colis.montant_jc or 0) - deja_encaisse

        # Si le reste à payer devient négatif (baisse de prix importante), on le remet à 0
        # Cela signifie que le client a un trop-perçu sur ce colis (géré manuellement ou via avoir plus tard)
        if colis.reste_a_payer < 0:
            colis.reste_a_payer = 0

        # Mise à jour de est_paye si le nouveau reste est 0
        if colis.reste_a_payer == 0 and colis.prix_final > 0:
            colis.est_paye = True
        elif colis.reste_a_payer > 0:
            colis.est_paye = False

        colis.save()
        return super().form_valid(form)


# --- VUES ADMIN MALI ---


class MaliDouaneGestionView(AdminMaliRequiredMixin, TemplateView):
    """
    Gestion des frais de douane : cumule les frais de douane des lots Mali
    et déduit les transferts envoyés à GAOUSSOU.
    Gère la pagination pour les lots et les transferts.
    """

    template_name = "mali/admin/gestion_douane.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.core.paginator import Paginator
        from django.db.models import Sum

        # 1. Querysets Lots (ML uniquement)
        lots_base = Lot.objects.filter(destination__code="ML")
        
        # Séparation Cargo / Express
        cargo_lots_qs = lots_base.filter(type_transport="CARGO").order_by("-date_arrivee", "-created_at")
        express_lots_qs = lots_base.filter(type_transport="EXPRESS").order_by("-date_arrivee", "-created_at")
        bateau_lots_qs = lots_base.filter(type_transport="BATEAU").order_by("-date_arrivee", "-created_at")

        # 2. Querysets Transferts
        transferts_base = TransfertArgent.objects.filter(pays_expediteur__code="ML")
        
        tc_qs = transferts_base.filter(destinataire="GAOUSSOU").order_by("-date", "-created_at")
        te_qs = transferts_base.filter(destinataire="GUISSE").order_by("-date", "-created_at")

        # 3. Pagination
        p_lots_c = Paginator(cargo_lots_qs, 10)
        p_lots_e = Paginator(express_lots_qs, 10)
        p_trans_c = Paginator(tc_qs, 5)
        p_trans_e = Paginator(te_qs, 5)

        context["cargo_lots"] = p_lots_c.get_page(self.request.GET.get("page_lots_c"))
        context["express_lots"] = p_lots_e.get_page(self.request.GET.get("page_lots_e"))
        context["cargo_trans"] = p_trans_c.get_page(self.request.GET.get("page_trans_c"))
        context["express_trans"] = p_trans_e.get_page(self.request.GET.get("page_trans_e"))

        # 4. Calculs Financiers CARGO
        c_douane = cargo_lots_qs.aggregate(total=Sum("frais_douane"))["total"] or 0
        c_paye = tc_qs.filter(statut="RECU").aggregate(total=Sum("montant"))["total"] or 0
        c_attente = tc_qs.filter(statut="EN_ATTENTE").aggregate(total=Sum("montant"))["total"] or 0

        # 5. Calculs Financiers EXPRESS
        e_douane = express_lots_qs.aggregate(total=Sum("frais_douane"))["total"] or 0
        e_paye = te_qs.filter(statut="RECU").aggregate(total=Sum("montant"))["total"] or 0
        e_attente = te_qs.filter(statut="EN_ATTENTE").aggregate(total=Sum("montant"))["total"] or 0

        context.update({
            "c_total_douane": c_douane,
            "c_total_paye": c_paye,
            "c_total_en_attente": c_attente,
            "c_reste_a_payer": c_douane - c_paye,
            
            "e_total_douane": e_douane,
            "e_total_paye": e_paye,
            "e_total_en_attente": e_attente,
            "e_reste_a_payer": e_douane - e_paye,
        })
        return context


class MaliAdminDashboardView(AdminMaliRequiredMixin, TemplateView):
    template_name = "mali/admin/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from core.models import Country
        mali = Country.objects.get(code="ML")
        now = timezone.now()

        # Stats globales
        context["total_agents"] = User.objects.filter(
            country=mali, role="AGENT_MALI"
        ).count()
        context["total_colis_mois"] = Colis.objects.filter(
            lot__destination=mali,
            lot__date_arrivee__year=now.year,
            lot__date_arrivee__month=now.month,
        ).count()

        # Lots par statut
        context["lots_en_cours"] = Lot.objects.filter(
            destination=mali, status=Lot.Status.OUVERT
        ).count()
        context["lots_en_route"] = Lot.objects.filter(
            destination=mali, status=Lot.Status.FERME
        ).count()  # Fermé = en cours d'expédition/transit
        context["lots_recus"] = Lot.objects.filter(
            destination=mali, status=Lot.Status.ARRIVE
        ).count()

        # CA Engagement du mois (Valeur totale des colis arrivés ce mois-ci)
        colis_arrives_mois = Colis.objects.filter(
            lot__destination=mali,
            lot__date_arrivee__year=now.year,
            lot__date_arrivee__month=now.month,
        )

        ca_engagement_agg = colis_arrives_mois.aggregate(
            total=Sum(F("prix_final") - F("montant_jc"))
        )
        ca_engagement = ca_engagement_agg["total"] or 0
        context["recettes_mois"] = ca_engagement

        # Recette Réelle (Caisse) pour le calcul du solde net
        recette_reelle = (
            EncaissementColis.objects.filter(
                colis__lot__destination=mali, date__year=now.year, date__month=now.month
            ).aggregate(total=Sum("montant"))["total"]
            or 0
        )

        # Dépenses (sans indicatif Chine)
        dep = Depense.objects.filter(
            pays=mali,
            date__year=now.year,
            date__month=now.month,
            is_china_indicative=False,
        )
        total_depenses = dep.aggregate(t=Sum("montant"))["t"] or 0
        context["depenses_mois"] = total_depenses

        # Transferts
        transf = TransfertArgent.objects.filter(
            pays_expediteur=mali, date__year=now.year, date__month=now.month
        )
        total_transferts = transf.aggregate(t=Sum("montant"))["t"] or 0
        context["transferts_mois"] = total_transferts

        # RH / Salaires & Avances
        av = AvanceSalaire.objects.filter(
            agent__country=mali, date__year=now.year, date__month=now.month
        )
        total_avances = av.aggregate(t=Sum("montant"))["t"] or 0

        salaires = PaiementAgent.objects.filter(
            agent__country=mali,
            periode_annee=now.year,
            periode_mois=now.month,
        )
        total_salaires = salaires.aggregate(t=Sum("montant"))["t"] or 0

        context["rh_mois"] = total_avances + total_salaires

        # Caisse nette de l'agence (Basée sur le bénéfice théorique du mois)
        # On utilise recettes_mois (théorique) pour être cohérent avec les autres cartes du dashboard
        context["caisse_nette"] = (
            context["recettes_mois"]
            - total_depenses
            - total_transferts
            - context["rh_mois"]
        )

        # Dernières livraisons
        context["recent_deliveries"] = (
            Colis.objects.filter(lot__destination=mali, status="LIVRE")
            .annotate(
                sort_date=Coalesce(
                    "date_livraison", "updated_at", output_field=DateField()
                )
            )
            .order_by("-sort_date", "-updated_at")[:10]
        )

        return context


class MaliAgentListView(AdminMaliRequiredMixin, ListView):
    model = User
    template_name = "mali/admin/agents_list.html"
    context_object_name = "agents"

    def get_queryset(self):
        return User.objects.filter(country=self.request.user.country, role="AGENT_MALI")


class MaliAgentCreateView(AdminMaliRequiredMixin, CreateView):
    model = User
    template_name = "mali/admin/agent_form.html"
    form_class = MaliAgentForm
    success_url = reverse_lazy("mali:admin_agents")

    def form_valid(self, form):
        user = form.save(commit=False)
        user.role = "AGENT_MALI"
        user.country = self.request.user.country

        if form.cleaned_data.get("acces_systeme"):
            user.is_active = True
        else:
            user.is_active = False

        if form.cleaned_data.get("password") and not user.pk:
            user.set_password(form.cleaned_data["password"])

        user.save()
        messages.success(self.request, f"Agent {user.username} créé avec succès.")
        return super().form_valid(form)


class MaliAgentUpdateView(AdminMaliRequiredMixin, UpdateView):
    model = User
    template_name = "mali/admin/agent_form.html"
    form_class = MaliAgentForm
    success_url = reverse_lazy("mali:admin_agents")

    def form_valid(self, form):
        messages.success(self.request, "Profil agent mis à jour.")
        return super().form_valid(form)


class MaliAgentRemunerationView(AdminMaliRequiredMixin, TemplateView):
    template_name = "mali/admin/remuneration_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()

        try:
            selected_year = int(self.request.GET.get("year", now.year))
            selected_month = int(self.request.GET.get("month", now.month))
        except ValueError:
            selected_year = now.year
            selected_month = now.month

        context["selected_year"] = selected_year
        context["selected_month"] = selected_month
        context["years"] = range(2025, now.year + 2)
        context["months"] = [
            (1, "Janvier"),
            (2, "Février"),
            (3, "Mars"),
            (4, "Avril"),
            (5, "Mai"),
            (6, "Juin"),
            (7, "Juillet"),
            (8, "Août"),
            (9, "Septembre"),
            (10, "Octobre"),
            (11, "Novembre"),
            (12, "Décembre"),
        ]

        # Stats du Mali pour la liste des agents
        stats_ml = get_country_stats("ML", selected_year, selected_month)
        context["stats_ml"] = stats_ml
        context["agents_data"] = stats_ml.get("agents_remuneration", [])

        # Liste des paiements
        context["paiements"] = PaiementAgent.objects.filter(
            agent__country=self.request.user.country,
            agent__role__in=["AGENT_MALI", "ADMIN_MALI"],
            periode_annee=selected_year,
            periode_mois=selected_month,
        ).order_by("-date_paiement")

        # Liste des avances
        context["avances"] = AvanceSalaire.objects.filter(
            agent__country=self.request.user.country,
            agent__role__in=["AGENT_MALI", "ADMIN_MALI"],
            date__year=selected_year,
            date__month=selected_month,
        ).order_by("-date")

        return context


class MaliAgentAvanceListView(LoginRequiredMixin, DestinationAgentRequiredMixin, CreateView):
    """Page permettant à l'agent Mali de consulter et d'enregistrer les avances sur salaire."""
    model = AvanceSalaire
    form_class = AvanceSalaireForm
    template_name = "mali/avances_list.html"
    success_url = reverse_lazy("mali:avances_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        mali = self.get_current_country()
        kwargs["country"] = mali
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mali = self.get_current_country()
        avances = AvanceSalaire.objects.filter(agent__country=mali).order_by("-date", "-created_at")
        context["avances"] = avances
        context["total_avances"] = avances.aggregate(total=Sum("montant"))["total"] or 0
        return context

    def form_valid(self, form):
        avance = form.save(commit=False)
        avance.save()
        messages.success(
            self.request,
            f"Avance de {avance.montant} FCFA enregistrée avec succès pour {avance.agent.get_full_name() or avance.agent.username}.",
        )
        return super().form_valid(form)


class MaliSoldeInitialView(LoginRequiredMixin, AdminMaliRequiredMixin, DestinationAgentRequiredMixin, TemplateView):
    """
    Interface d'enregistrement et de consultation du Solde Initial / Date Pivot de la Caisse.
    """
    template_name = "mali/finance/solde_initial.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mali = self.get_current_country()
        context["soldes_initiaux"] = SoldeInitialCaisse.objects.filter(country=mali).order_by("-date_pivot", "-created_at")
        context["solde_actuel_pivot"] = SoldeInitialCaisse.objects.filter(country=mali).order_by("-date_pivot").first()
        return context

    def post(self, request, *args, **kwargs):
        mali = self.get_current_country()
        date_pivot_str = request.POST.get("date_pivot")
        montant_str = request.POST.get("montant_initial")
        note = request.POST.get("note", "")
        type_transport = request.POST.get("type_transport", "GLOBAL")

        if date_pivot_str and montant_str:
            try:
                from datetime import datetime
                date_pivot = datetime.strptime(date_pivot_str, "%Y-%m-%d").date()
                montant = Decimal(montant_str)

                SoldeInitialCaisse.objects.create(
                    country=mali,
                    date_pivot=date_pivot,
                    montant_initial=montant,
                    type_transport=type_transport,
                    note=note,
                    created_by=request.user
                )
                messages.success(
                    request,
                    f"✅ Reprise de solde certifiée à {montant} FCFA au {date_pivot.strftime('%d/%m/%Y')} enregistrée avec succès."
                )
            except Exception as e:
                messages.error(request, f"Erreur lors de l'enregistrement du solde initial : {e}")

        return redirect("mali:solde_initial")


class MaliAgentAvanceCreateView(AdminMaliRequiredMixin, CreateView):
    model = AvanceSalaire
    form_class = AvanceSalaireForm
    template_name = "mali/admin/avance_form.html"
    success_url = reverse_lazy("mali:admin_remunerations")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["country"] = self.request.user.country
        return kwargs

    def form_valid(self, form):
        avance = form.save(commit=False)
        avance.save()
        messages.success(
            self.request,
            f"Avance de {avance.montant} ajoutée pour l'agent {avance.agent.username}.",
        )
        return super().form_valid(form)


class MaliAgentAvanceUpdateView(AdminMaliRequiredMixin, UpdateView):
    model = AvanceSalaire
    form_class = AvanceSalaireForm
    template_name = "mali/admin/avance_form.html"
    success_url = reverse_lazy("mali:admin_remunerations")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["country"] = self.request.user.country
        return kwargs

    def form_valid(self, form):
        avance = form.save(commit=False)
        avance.save()
        messages.success(
            self.request,
            f"Avance de {avance.montant} mise à jour pour l'agent {avance.agent.username}.",
        )
        return super().form_valid(form)


class MaliAgentAvanceDeleteView(AdminMaliRequiredMixin, View):
    def post(self, request, pk):
        avance = get_object_or_404(
            AvanceSalaire, pk=pk, agent__country=request.user.country
        )
        avance.delete()
        messages.success(request, "L'avance a été supprimée avec succès.")
        return redirect("mali:admin_remunerations")


class MaliCorrectionLotListView(AdminMaliRequiredMixin, ListView):
    model = Lot
    template_name = "mali/admin/correction_lot_list.html"
    context_object_name = "lots_list"
    paginate_by = 20

    def get_queryset(self):
        from core.models import Country
        mali = Country.objects.get(code="ML")
        qs = (
            Lot.objects.filter(destination=mali)
            .annotate(
                total_poids_colis=Sum("colis__poids"),
                total_cbm_colis=Sum("colis__cbm"),
            )
            .order_by("-date_arrivee", "-created_at")
        )
        search = self.request.GET.get("q")
        from django.db.models import Q
        if search:
            qs = qs.filter(numero__icontains=search)
        tab = self.request.GET.get("tab", "arrive")
        if tab == "transit":
            qs = qs.filter(Q(colis__status="EXPEDIE") | Q(status="EN_TRANSIT") | Q(status="EXPEDIE")).distinct()
        elif tab == "livre":
            qs = qs.filter(Q(colis__status__in=["LIVRE", "PERDU"]) | Q(status="FERME")).distinct()
        else:  # arrive (default)
            qs = qs.filter(Q(colis__status="ARRIVE") | Q(status="ARRIVE")).distinct()

        # Filtrage par type de transport
        transport = self.request.GET.get("transport")
        if transport in ["CARGO", "EXPRESS", "BATEAU"]:
            qs = qs.filter(type_transport=transport)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        context["active_tab"] = self.request.GET.get("tab", "arrive")
        context["active_transport"] = self.request.GET.get("transport", "")
        from core.models import Country
        mali = Country.objects.get(code="ML")
        # Comptes par statut pour les badges de nav
        qs_base = Lot.objects.filter(destination=mali)
        search = self.request.GET.get("q")
        if search:
            qs_base = qs_base.filter(numero__icontains=search)
        context["count_transit"] = (
            qs_base.filter(colis__status="EXPEDIE").distinct().count()
        )
        context["count_arrive"] = (
            qs_base.filter(colis__status="ARRIVE").distinct().count()
        )
        context["count_livre"] = (
            qs_base.filter(colis__status__in=["LIVRE", "PERDU"]).distinct().count()
        )
        return context


class MaliCorrectionLotDetailView(AdminMaliRequiredMixin, DetailView):
    model = Lot
    template_name = "mali/admin/correction_lot_detail.html"
    context_object_name = "lot"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        frais_douane = request.POST.get("frais_douane")
        if frais_douane is not None:
            self.object.frais_douane = frais_douane
            self.object.save()
            messages.success(request, f"Frais de douane mis à jour à {frais_douane} FCFA.")
        return redirect("mali:admin_correction_lot_detail", pk=self.object.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models import Prefetch

        colis_qs = (
            self.object.colis.select_related("client")
            .prefetch_related(
                Prefetch(
                    "client__tarifs_speciaux",
                    queryset=ClientLotTarif.objects.all(),
                    to_attr="special_agreement",
                )
            )
            .all()
            .order_by("-updated_at")
        )

        search = self.request.GET.get("q")
        if search:
            colis_qs = apply_flexible_search(
                colis_qs, search, ["reference", "client__nom", "client__telephone"]
            )

        from django.core.paginator import Paginator

        paginator = Paginator(colis_qs, 50)
        context["colis_list"] = paginator.get_page(self.request.GET.get("page"))
        context["q"] = search or ""
        # Variable clé : le lot a-t-il des colis déjà ARRIVE ? (indépendant du statut du lot)
        context["lot_has_arrived_colis"] = self.object.colis.filter(
            status="ARRIVE"
        ).exists()
        return context


class MaliActionRevertView(DestinationAgentRequiredMixin, View):
    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk, lot__destination=request.user.country)
        action = request.POST.get("action")

        if action == "revert_to_transit" and colis.status == "ARRIVE":
            # Repasser en EXPEDIE (transit)
            colis.status = "EXPEDIE"
            colis.date_livraison = None
            colis.date_encaissement = None
            colis.est_paye = False
            colis.reste_a_payer = colis.prix_final or 0
            colis.montant_jc = 0
            colis.sortie_sous_garantie = False
            colis.sortie_autorisee_par = ""
            colis.save()

            # Notification d'excuse
            if colis.client and colis.client.user:
                try:
                    from notification.tasks import send_notification_async

                    message = (
                        f"Cher client, une erreur s'est glissée dans le suivi de votre colis {colis.reference}. "
                        "Il n'est pas encore arrivé. Nous vous prions de nous excuser. "
                        "Vous recevrez une nouvelle notification dès qu'il sera disponible."
                    )
                    send_notification_async.delay(
                        user_id=colis.client.user.id,
                        message=message,
                        categorie="autre",
                        titre=f"Correction Suivi - {colis.reference}",
                        region="mali",
                    )
                except Exception:
                    pass

            messages.success(
                request, f"Le carton {colis.reference} est repassé en TRANSIT."
            )

        elif action == "revert_to_arrive" and colis.status == "LIVRE":
            # Annuler la livraison : nettoyage atomique des encaissements et des avoirs
            from django.db import transaction as db_transaction
            from core.models import AvoirMouvement, EncaissementColis as EC

            with db_transaction.atomic():
                # 1. Rembourser les mouvements d'avoir de type CONSOMMATION liés à ce colis
                if colis.client:
                    from django.db.models import Sum as _Sum
                    avoir_consommes = AvoirMouvement.objects.filter(
                        colis=colis, type="CONSOMMATION"
                    )
                    total_avoir_a_rembourser = (
                        avoir_consommes.aggregate(t=_Sum("montant"))["t"] or 0
                    )
                    if total_avoir_a_rembourser > 0:
                        # Verrouiller le client et recréditer l'avoir
                        client = colis.client.__class__.objects.select_for_update().get(
                            pk=colis.client.pk
                        )
                        client.solde_avoir += total_avoir_a_rembourser
                        client.save()
                    # Supprimer les mouvements d'avoir associés à ce colis
                    avoir_consommes.delete()

                # 2. Supprimer tous les encaissements liés à ce colis
                EC.objects.filter(colis=colis).delete()

                # 3. Réinitialiser proprement le colis
                colis.status = "ARRIVE"
                colis.date_livraison = None
                colis.date_encaissement = None
                colis.est_paye = False
                colis.paye_par_avance = False
                colis.montant_jc = 0
                colis.reste_a_payer = colis.prix_final or 0
                colis.sortie_sous_garantie = False
                colis.sortie_autorisee_par = ""
                colis.mode_paiement = None
                colis.save()

            # Notification d'excuse
            if colis.client and colis.client.user:
                try:
                    from notification.tasks import send_notification_async

                    message = (
                        f"Cher client, une erreur s'est glissée dans le suivi de votre colis {colis.reference}. "
                        "Celui-ci est marqué comme 'Non Livré' pour correction. "
                        "Nous vous prions de nous excuser pour ce désagrément."
                    )
                    send_notification_async.delay(
                        user_id=colis.client.user.id,
                        message=message,
                        categorie="autre",
                        titre=f"Correction Livraison - {colis.reference}",
                        region="mali",
                    )
                except Exception:
                    pass

            messages.warning(
                request,
                f"Le carton {colis.reference} est repassé en ARRIVÉ. Les encaissements et avoirs associés ont été annulés.",
            )

        # Revert complet d'un colis perdu
        elif action == "revert_perdu" and colis.status == "PERDU":
            colis.status = "ARRIVE"  # Par défaut on repasse à arrivé
            colis.save()
            messages.success(
                request,
                f"Le carton {colis.reference} n'est plus marqué comme PERDU. Il est maintenant ARRIVÉ.",
            )

        # Revert encaissement partiel ou modification paiement tout en restant en attente etc n'est pas nécessaire si on reverse à Arrivé, ça annule tout.

        referer = request.META.get('HTTP_REFERER')
        if referer:
            return redirect(referer)

        # Fallback
        if request.user.role in ["GLOBAL_ADMIN", "ADMIN_MALI"]:
            return redirect("mali:admin_correction_lot_detail", pk=colis.lot.pk)
        return redirect("mali:lot_arrived_detail", pk=colis.lot.pk)


class MaliColisAddToArrivalView(DestinationAgentRequiredMixin, View):
    """Permet à l'Admin Mali d'ajouter un colis manquant dans un lot arrivé.
    Ces colis seront marqués 'ajoute_par_mali=True' et auront un badge spécial."""

    def get(self, request, lot_pk):
        from .forms import MaliAddColisForm

        lot = get_object_or_404(Lot, pk=lot_pk, destination=request.user.country)

        form = MaliAddColisForm(country=request.user.country, lot=lot)
        return render(
            request, "mali/admin/add_colis_to_lot.html", {"lot": lot, "form": form}
        )

    def post(self, request, lot_pk):
        from .forms import MaliAddColisForm
        from django.http import JsonResponse

        lot = get_object_or_404(Lot, pk=lot_pk, destination=request.user.country)
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.POST.get("_ajax") == "1"

        form = MaliAddColisForm(
            request.POST, request.FILES, country=request.user.country, lot=lot
        )

        if form.is_valid():
            data = form.cleaned_data
            colis = Colis(
                lot=lot,
                client=data["client"],
                country=lot.destination,
                type_colis=data.get("type_colis") or Colis.TypeColis.STANDARD,
                poids=data.get("poids") or 0,
                cbm=data.get("cbm") or 0,
                nombre_pieces=data.get("nombre_pieces") or 1,
                description=data.get("description", ""),
                photo=data.get("photo"),
                status=Colis.Status.ARRIVE,
                ajoute_par_mali=True,
            )

            # Handle Base64 photo (Webcam/Compressed)
            compressed_photo_data = request.POST.get("compressed_photo")
            if compressed_photo_data and compressed_photo_data.startswith("data:image"):
                try:
                    import base64
                    from django.core.files.base import ContentFile
                    import uuid

                    format, imgstr = compressed_photo_data.split(";base64,")
                    ext = format.split("/")[-1]
                    photo_content = ContentFile(
                        base64.b64decode(imgstr),
                        name=f"colis_mali_{uuid.uuid4().hex[:8]}.{ext}",
                    )
                    colis.photo.save(photo_content.name, photo_content, save=False)
                except Exception:
                    pass

            colis.save()

            # Si un prix final est saisi manuellement, on l'utilise (après le save pour éviter l'écrasement auto)
            if data.get("prix_final"):
                colis.prix_final = data["prix_final"]
                colis.prix_transport = data["prix_final"]
                Colis.objects.filter(pk=colis.pk).update(
                    prix_final=colis.prix_final, prix_transport=colis.prix_transport
                )

            # Essaie d'envoyer la notification WhatsApp si configurée
            try:
                from notification.tasks import send_notification_async

                if colis.client and colis.client.user:
                    transport_icon = "⛵" if lot.type_transport == "BATEAU" else "✈️"
                    message = (
                        f"{transport_icon} Votre colis {colis.reference} est arrivé à Bamako !\n"
                        f"Montant à payer : {colis.prix_final} FCFA\n\n"
                        "Vous pouvez passer le récupérer à l'agence."
                    )

                    send_notification_async.delay(
                        user_id=colis.client.user.id,
                        message=message,
                        categorie="lot_arrive",
                        titre=f"Arrivée Colis {colis.reference}",
                        region="mali",
                    )
            except Exception:
                pass  # Notification non bloquante

            success_msg = f"✅ Colis {colis.reference} ajouté avec succès dans le lot {lot.numero}. [Ajouté Mali]"

            if is_ajax:
                return JsonResponse({
                    "success": True,
                    "message": success_msg,
                    "colis_reference": colis.reference,
                    "redirect_url": reverse_lazy("mali:lot_arrived_detail", kwargs={"pk": lot.pk}),
                })

            messages.success(request, success_msg)
            return redirect("mali:lot_arrived_detail", pk=lot.pk)

        if is_ajax:
            errors = {field: list(errs) for field, errs in form.errors.items()}
            return JsonResponse({"success": False, "errors": errors}, status=400)

        return render(
            request, "mali/admin/add_colis_to_lot.html", {"lot": lot, "form": form}
        )


from django.http import JsonResponse


class MaliCalculatePriceView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """
    API pour calculer le prix d'un colis en temps réel via AJAX.
    """

    def get(self, request):
        client_id = request.GET.get("client_id")
        lot_id = request.GET.get("lot_id")
        type_colis = request.GET.get("type_colis", "STANDARD")
        poids = request.GET.get("poids", 0)
        cbm = request.GET.get("cbm", 0)
        nombre_pieces = request.GET.get("nombre_pieces", 1)

        if not all([client_id, lot_id]):
            return JsonResponse({"error": "Paramètres manquants"}, status=400)

        try:
            from core.models import Client, Lot, Colis
            from decimal import Decimal

            client = Client.objects.get(pk=client_id)
            lot = Lot.objects.get(pk=lot_id)

            # Conversion sécurisée (évite erreurs si virgule ou vide) - Utilise Decimal pour éviter TypeError avec les modèles
            try:
                p_val = (
                    Decimal(str(poids).replace(",", "."))
                    if poids and str(poids).strip()
                    else Decimal("0")
                )
                c_val = (
                    Decimal(str(cbm).replace(",", "."))
                    if cbm and str(cbm).strip()
                    else Decimal("0")
                )
                n_val = int(nombre_pieces) if nombre_pieces else 1
            except (ValueError, TypeError, Exception):
                p_val = Decimal("0")
                c_val = Decimal("0")
                n_val = 1

            temp_colis = Colis(
                client=client,
                lot=lot,
                type_colis=type_colis,
                poids=p_val,
                cbm=c_val,
                nombre_pieces=n_val,
            )
            temp_colis.recalculate_prices()

            return JsonResponse(
                {
                    "prix_final": float(temp_colis.prix_final or 0),
                    "prix_transport": float(temp_colis.prix_transport or 0),
                    "success": True,
                }
            )
        except Exception as e:
            return JsonResponse(
                {"error": str(e), "prix_final": 0, "success": False}, status=400
            )


class MaliClientAvoirView(DestinationAgentRequiredMixin, TemplateView):
    """
    Interface pour gérer l'avoir (portefeuille) d'un client au Mali.
    Permet de recharger le compte.
    """

    template_name = "mali/client_avoir.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from core.models import Client, AvoirMouvement
        from django.db.models import Q

        q = self.request.GET.get("q", "").strip()
        clients = Client.objects.filter(country=self.request.user.country)
        if q:
            # Recherche intelligente : chaque mot doit se trouver soit dans le nom, le prénom ou le tel
            mots = q.split()
            for mot in mots:
                clients = clients.filter(
                    Q(nom__icontains=mot)
                    | Q(prenom__icontains=mot)
                    | Q(telephone__icontains=mot)
                )

        context["clients"] = clients.order_by("nom", "prenom")[:20]
        context["search_query"] = q

        # Si un client spécifique est sélectionné
        client_id = self.request.GET.get("client_id")
        if client_id:
            try:
                selected_client = Client.objects.get(
                    pk=client_id, country=self.request.user.country
                )
                context["selected_client"] = selected_client
                context["mouvements"] = AvoirMouvement.objects.filter(
                    client=selected_client
                ).order_by("-created_at")[:50]
            except Client.DoesNotExist:
                pass

        return context

    def post(self, request, *args, **kwargs):
        from core.models import Client, AvoirMouvement
        from decimal import Decimal

        client_id = request.POST.get("client_id")
        montant = request.POST.get("montant")
        commentaire = request.POST.get("commentaire", "")

        if not client_id or not montant:
            messages.error(request, "Veuillez sélectionner un client et un montant.")
            return redirect("mali:client_avoir")

        try:
            client = Client.objects.get(pk=client_id, country=request.user.country)
            montant_dec = Decimal(montant.replace(",", "."))

            if montant_dec <= 0:
                messages.error(request, "Le montant doit être supérieur à 0.")
                return redirect(f"{reverse('mali:client_avoir')}?client_id={client_id}")

            # Mise à jour du solde
            client.solde_avoir += montant_dec
            client.save()

            # Tracer le mouvement
            AvoirMouvement.objects.create(
                client=client,
                montant=montant_dec,
                type="DEPOT",
                enregistre_par=request.user,
                commentaire=commentaire,
            )

            messages.success(
                request,
                f"✅ {montant_dec:,.0f} FCFA ajoutés avec succès au compte de {client}.".replace(
                    ",", " "
                ),
            )
            return redirect(f"{reverse('mali:client_avoir')}?client_id={client_id}")

        except Exception as e:
            messages.error(request, f"Erreur : {str(e)}")
            return redirect("mali:client_avoir")


class ManualImputeView(DestinationAgentRequiredMixin, View):
    """
    Déclencher manuellement l'imputation des avoirs pour TOUS les colis en attente d'un client.
    """
    def post(self, request, client_id):
        from core.models import Client, Colis
        from notification.tasks import perform_avoir_imputation_colis
        
        client = get_object_or_404(Client, pk=client_id)
        
        if client.solde_avoir <= 0:
            messages.warning(request, f"Le client {client} n'a pas de solde d'avance disponible.")
            return redirect(reverse("mali:client_avoir") + f"?client_id={client_id}")
            
        # On cherche tous les colis non payés du client à destination du Mali
        colis_en_attente = Colis.objects.filter(
            client=client, 
            est_paye=False,
            reste_a_payer__gt=0,
            lot__destination=request.user.country
        ).order_by("created_at") # Du plus ancien au plus récent
        
        if not colis_en_attente.exists():
            messages.info(request, f"Aucun colis en attente de paiement trouvé pour {client}.")
            return redirect(reverse("mali:client_avoir") + f"?client_id={client_id}")
            
        count = 0
        total_impute = 0
        
        for colis in colis_en_attente:
            if client.solde_avoir <= 0:
                break
                
            mt, success, err = perform_avoir_imputation_colis(colis, request.user)
            if success and mt > 0:
                count += 1
                total_impute += mt
                client.refresh_from_db()

        if count > 0:
            messages.success(request, f"Imputation réussie : {count} colis traités pour un total de {total_impute} FCFA.")
        else:
            messages.warning(request, "Aucune imputation n'a pu être effectuée (Solde insuffisant ou erreur).")
            
        return redirect(reverse("mali:client_avoir") + f"?client_id={client_id}")


class LotManualImputeView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """
    Déclencher l'imputation des avoirs pour TOUS les colis d'un lot spécifique.
    """

    def post(self, request, pk):
        from core.models import Lot
        from notification.tasks import perform_avoir_imputation_colis

        lot = get_object_or_404(Lot, pk=pk)

        # On cherche tous les colis non payés du lot
        colis_in_lot = lot.colis.filter(est_paye=False, reste_a_payer__gt=0).select_related(
            "client"
        )

        if not colis_in_lot.exists():
            messages.info(
                request, f"Aucun colis en attente de paiement dans le lot {lot.numero}."
            )
            return redirect("mali:lot_arrived_detail", pk=pk)

        count = 0
        total_impute = 0

        for colis in colis_in_lot:
            if not colis.client or colis.client.solde_avoir <= 0:
                continue

            mt, success, err = perform_avoir_imputation_colis(colis, request.user)
            if success and mt > 0:
                count += 1
                total_impute += mt

        if count > 0:
            messages.success(
                request,
                f"Imputation du lot réussie : {count} colis traités pour {total_impute} FCFA.",
            )
        else:
            messages.warning(
                request,
                "Aucune imputation n'a pu être effectuée pour ce lot (Soldes clients insuffisants).",
            )

        return redirect("mali:lot_arrived_detail", pk=pk)


class MaliPretsRetraitView(LoginRequiredMixin, DestinationAgentRequiredMixin, ListView):
    """
    Affiche la liste des colis déjà payés (par avance/avoir) qui sont à l'entrepôt au Mali
    et qui attendent d'être retirés par le client.
    """

    model = Colis
    template_name = "mali/prets_retrait.html"
    context_object_name = "colis_list"
    paginate_by = 50

    def get_queryset(self):
        mali = self.get_current_country()
        queryset = (
            Colis.objects.filter(lot__destination=mali, status="ARRIVE", est_paye=True)
            .select_related("client", "lot")
            .order_by("client__nom", "-updated_at")
        )

        q = self.request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(reference__icontains=q)
                | Q(client__nom__icontains=q)
                | Q(client__prenom__icontains=q)
                | Q(client__telephone__icontains=q)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "")
        if "paginator" in context and context["paginator"]:
            context["total_colis"] = context["paginator"].count
        else:
            context["total_colis"] = len(context.get("colis_list", []))
        return context


class MaliConfirmerRetraitBulkView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, View
):
    """Version groupée pour marquer les colis comme LIVRES (retirés)"""

    def post(self, request):
        colis_ids = request.POST.getlist("colis_ids")
        if not colis_ids:
            messages.warning(request, "Aucun colis sélectionné.")
            return redirect("mali:prets_retrait")

        updated = Colis.objects.filter(
            id__in=colis_ids, status="ARRIVE", est_paye=True
        ).update(
            status="LIVRE",
            date_livraison=timezone.now().date(),
            updated_at=timezone.now(),
        )

        messages.success(request, f"{updated} colis marqués comme retirés (Livrés).")
        return redirect("mali:prets_retrait")


class PaiementsHistoriqueView(LoginRequiredMixin, DestinationAgentRequiredMixin, ListView):
    """Historique global des paiements et dépôts d'avoir pour audit"""
    template_name = "mali/historique_paiements.html"
    context_object_name = "paiements"
    paginate_by = 50

    def get_queryset(self):
        mali = self.get_current_country()
        qs = EncaissementColis.objects.filter(colis__lot__destination=mali).select_related("colis", "colis__client", "enregistre_par")
        
        # Filtre par type de transport (Maritime vs Aérien)
        if getattr(self.request, "is_maritime", False):
            qs = qs.filter(colis__lot__type_transport="BATEAU")
        else:
            qs = qs.filter(colis__lot__type_transport__in=["CARGO", "EXPRESS"])

        # Recherche par texte
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(
                Q(colis__reference__icontains=q) |
                Q(colis__client__nom__icontains=q) |
                Q(colis__client__prenom__icontains=q) |
                Q(colis__client__telephone__icontains=q)
            )
        # Filtre par date
        date_start = self.request.GET.get("date_start")
        if date_start:
            qs = qs.filter(date__gte=date_start)
            
        date_end = self.request.GET.get("date_end")
        if date_end:
            qs = qs.filter(date__lte=date_end)
            
        return qs.order_by("-date", "-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mali = self.get_current_country()
        context["depots_avoir"] = AvoirMouvement.objects.filter(client__country=mali, type="DEPOT").select_related("client", "enregistre_par").order_by("-created_at")[:50]
        return context


class JetonsCedesListView(LoginRequiredMixin, DestinationAgentRequiredMixin, ListView):
    """Traçabilité des Jetons Cédés (JC) — colis avec remises."""

    template_name = "mali/jetons_cedes.html"
    context_object_name = "colis_list"
    paginate_by = 30

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Colis.objects.none()

        queryset = (
            Colis.objects.filter(lot__destination=mali, montant_jc__gt=0)
            .select_related("client", "lot")
            .order_by("-date_livraison", "-updated_at")
        )

        # Filtres mois/année
        year = self.request.GET.get("year")
        month = self.request.GET.get("month")
        if year:
            try:
                queryset = queryset.filter(date_encaissement__year=int(year))
            except (ValueError, TypeError):
                pass
        if month:
            try:
                queryset = queryset.filter(date_encaissement__month=int(month))
            except (ValueError, TypeError):
                pass

        # Recherche client
        q = self.request.GET.get("q")
        if q:
            queryset = apply_flexible_search(
                queryset, q,
                ["client__nom", "client__prenom", "client__telephone", "reference"]
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()

        # Totaux de la période filtrée
        full_qs = self.get_queryset()
        agg = full_qs.aggregate(
            nb_colis_jc=Count("id"),
            total_jc=Sum("montant_jc"),
        )
        context["nb_colis_jc"] = agg["nb_colis_jc"] or 0
        context["total_jc"] = agg["total_jc"] or 0

        context["selected_year"] = self.request.GET.get("year", "")
        context["selected_month"] = self.request.GET.get("month", "")
        context["q"] = self.request.GET.get("q", "")
        context["years"] = list(range(now.year, now.year - 5, -1))
        context["months"] = [
            (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"),
            (5, "Mai"), (6, "Juin"), (7, "Juillet"), (8, "Août"),
            (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
        ]
        return context


class ClientListMaliView(LoginRequiredMixin, DestinationAgentRequiredMixin, ListView):
    """Liste des clients Mali avec classement top 5 et recherche."""

    template_name = "mali/client_list.html"
    context_object_name = "clients"
    paginate_by = 20

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Client.objects.none()

        queryset = (
            Client.objects.filter(country=mali)
            .annotate(
                total_colis=Count("colis", filter=Q(colis__lot__destination=mali)),
                total_ca=Sum("colis__prix_final", filter=Q(colis__lot__destination=mali)),
                colis_en_stock=Count("colis", filter=Q(colis__status="ARRIVE", colis__lot__destination=mali)),
                colis_livres=Count("colis", filter=Q(colis__status="LIVRE", colis__lot__destination=mali)),
                total_creances=Sum("colis__reste_a_payer", filter=Q(colis__est_paye=False, colis__lot__destination=mali)),
            )
        )

        q = self.request.GET.get("q")
        if q:
            queryset = apply_flexible_search(
                queryset, q,
                ["nom", "prenom", "telephone"]
            )

        return queryset.order_by("-total_ca")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mali = self.get_current_country()

        # Top 5 meilleurs clients par CA
        context["top_clients"] = (
            Client.objects.filter(country=mali)
            .annotate(
                total_ca=Sum("colis__prix_final", filter=Q(colis__lot__destination=mali)),
                total_colis=Count("colis", filter=Q(colis__lot__destination=mali)),
            )
            .filter(total_ca__gt=0)
            .order_by("-total_ca")[:5]
        )

        context["q"] = self.request.GET.get("q", "")
        context["total_clients"] = Client.objects.filter(country=mali).count()
        return context


class ClientDetailMaliView(LoginRequiredMixin, DestinationAgentRequiredMixin, DetailView):
    """Fiche client enrichie pour l'agent Mali avec 4 onglets par statut."""

    model = Client
    template_name = "mali/client_detail.html"
    context_object_name = "client"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mali = self.get_current_country()
        client = self.object

        # 4 querysets de colis filtrés par client, destination et type de transport
        base_qs = Colis.objects.filter(client=client, lot__destination=mali).select_related("lot")

        if getattr(self.request, "is_maritime", False):
            base_qs = base_qs.filter(lot__type_transport="BATEAU")
        else:
            base_qs = base_qs.filter(lot__type_transport__in=["CARGO", "EXPRESS"])

        en_chine = base_qs.filter(status="RECU")
        en_expedition = base_qs.filter(status="EXPEDIE")
        au_mali = base_qs.filter(status="ARRIVE")
        livres = base_qs.filter(status="LIVRE")

        def stats_for(qs):
            agg = qs.aggregate(
                count=Count("id"),
                poids=Sum("poids"),
                valeur=Sum("prix_final"),
            )
            return {
                "qs": qs.order_by("-created_at"),
                "count": agg["count"] or 0,
                "poids": agg["poids"] or 0,
                "valeur": agg["valeur"] or 0,
            }

        context["en_chine"] = stats_for(en_chine)
        context["en_expedition"] = stats_for(en_expedition)
        context["au_mali"] = stats_for(au_mali)
        context["livres"] = stats_for(livres)

        # Créances totales (reste_a_payer)
        context["total_creances"] = (
            base_qs.filter(est_paye=False).aggregate(total=Sum("reste_a_payer"))["total"] or 0
        )

        # Historique paiements récents
        paiements_qs = EncaissementColis.objects.filter(colis__client=client, colis__lot__destination=mali)
        if getattr(self.request, "is_maritime", False):
            paiements_qs = paiements_qs.filter(colis__lot__type_transport="BATEAU")
        else:
            paiements_qs = paiements_qs.filter(colis__lot__type_transport__in=["CARGO", "EXPRESS"])
            
        context["paiements_recents"] = (
            paiements_qs.select_related("colis")
            .order_by("-date", "-created_at")[:10]
        )

        return context


class StockMaliView(LoginRequiredMixin, DestinationAgentRequiredMixin, ListView):
    """Vue du stock de colis arrivés au Mali, groupés par lot."""

    template_name = "mali/stock.html"
    context_object_name = "colis_list"
    paginate_by = 30

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Colis.objects.none()

        from django.db.models.functions import Now, Coalesce as CoalesceFunc
        from datetime import date

        queryset = (
            Colis.objects.filter(lot__destination=mali, status="ARRIVE")
            .select_related("client", "lot")
        )

        # Filtre par type de transport
        transport = self.request.GET.get("transport")
        if transport in ("CARGO", "EXPRESS", "BATEAU"):
            queryset = queryset.filter(lot__type_transport=transport)

        # Recherche
        q = self.request.GET.get("q")
        if q:
            queryset = apply_flexible_search(
                queryset, q,
                ["client__nom", "client__prenom", "client__telephone", "reference", "lot__numero"]
            )

        return queryset.order_by("lot__date_arrivee", "-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mali = self.get_current_country()

        # Stats globales sur le stock
        stock_qs = Colis.objects.filter(lot__destination=mali, status="ARRIVE")
        from django.db.models import Avg
        from datetime import date

        agg = stock_qs.aggregate(
            nb_colis=Count("id"),
            poids_total=Sum("poids"),
            valeur_totale=Sum("prix_final"),
        )
        context["nb_colis_stock"] = agg["nb_colis"] or 0
        context["poids_total_stock"] = agg["poids_total"] or 0
        context["valeur_totale_stock"] = agg["valeur_totale"] or 0
        
        context["valeur_cargo"] = stock_qs.filter(lot__type_transport="CARGO").aggregate(v=Sum("prix_final"))["v"] or 0
        context["valeur_express"] = stock_qs.filter(lot__type_transport="EXPRESS").aggregate(v=Sum("prix_final"))["v"] or 0
        context["valeur_bateau"] = stock_qs.filter(lot__type_transport="BATEAU").aggregate(v=Sum("prix_final"))["v"] or 0

        # Ancienneté moyenne (jours depuis date_arrivee du lot)
        today = date.today()
        lots_arrives = Lot.objects.filter(
            destination=mali, colis__status="ARRIVE", date_arrivee__isnull=False
        ).distinct()
        if lots_arrives.exists():
            total_days = sum(
                (today - lot.date_arrivee.date()).days
                for lot in lots_arrives if lot.date_arrivee
            )
            context["anciennete_moyenne"] = round(total_days / lots_arrives.count(), 1)
        else:
            context["anciennete_moyenne"] = 0

        context["active_transport"] = self.request.GET.get("transport", "")
        context["q"] = self.request.GET.get("q", "")
        return context


class LotBateauMaliCreateView(LoginRequiredMixin, DestinationAgentRequiredMixin, CreateView):
    """Permet à l'agent Mali de créer un lot bateau pour régulariser des anciens envois"""
    model = Lot
    form_class = LotBateauMaliForm
    template_name = "mali/lot_bateau_create.html"
    success_url = reverse_lazy("mali:lots_arrives")

    def form_valid(self, form):
        mali = self.get_current_country()
        
        # Génération automatique du numéro : ML-BT-ANNÉE-SÉQUENCE
        year = timezone.now().year
        prefix = f"ML-BT-{year}-"
        last_lot = Lot.objects.filter(numero__startswith=prefix).order_by("-numero").first()
        
        if last_lot:
            try:
                last_seq = int(last_lot.numero.split("-")[-1])
                new_seq = last_seq + 1
            except (ValueError, IndexError):
                new_seq = 1
        else:
            new_seq = 1
            
        from core.models import Country
        chine = Country.objects.get(code="CN")
            
        form.instance.numero = f"{prefix}{new_seq:03d}"
        form.instance.country = chine 
        form.instance.destination = mali
        form.instance.type_transport = "BATEAU"
        form.instance.status = "ARRIVE"
        form.instance.created_by = self.request.user
        messages.success(self.request, f"Lot Bateau {form.instance.numero} créé avec succès (Badge créé au Mali).")
        return super().form_valid(form)
class LotsLivresView(LotsEnTransitView):
    """Historique des lots ayant des colis LIVRÉS ou PERDUS"""

    paginate_by = 10
    template_name = "mali/lots_livres.html"

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Lot.objects.none()

        query = self.request.GET.get("q")
        if query:
            # RECHERCHE GLOBALE PAR COLIS (Demande utilisateur)
            queryset = Colis.objects.filter(
                lot__destination=mali, status__in=["LIVRE", "PERDU"]
            )
            queryset = queryset.select_related("lot", "client", "client__user")
            queryset = queryset.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
                prenom_complet=Concat("client__prenom", Value(" "), "client__nom"),
            )
            search_fields = [
                "reference",
                "lot__numero",
                "client__nom",
                "client__prenom",
                "client__telephone",
                "nom_complet",
                "prenom_complet",
            ]
            queryset = apply_flexible_search(queryset, query, search_fields)

            # Isolation Aérien / Maritime
            if getattr(self.request, "is_maritime", False):
                queryset = queryset.filter(lot__type_transport="BATEAU")
            else:
                queryset = queryset.filter(lot__type_transport__in=["CARGO", "EXPRESS"])

            transport = self.request.GET.get("transport")
            if transport in ["CARGO", "EXPRESS", "BATEAU"]:
                queryset = queryset.filter(lot__type_transport=transport)
            
            month = self.request.GET.get("month")
            year = self.request.GET.get("year")
            if month and year:
                queryset = queryset.filter(updated_at__month=month, updated_at__year=year)

            return queryset.order_by("-updated_at")

        # AFFICHAGE PAR LOT (Sans recherche)
        # Un lot apparaît en livrés s'il a au moins un colis LIVRE ou PERDU
        queryset = (
            Lot.objects.filter(destination=mali, colis__status__in=["LIVRE", "PERDU"])
            .select_related("destination")
            .prefetch_related("colis")
            .annotate(
                nb_colis_livre=Count(
                    "colis", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                ),
                total_recettes_livre=Sum(
                    "colis__prix_final", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                )
                - Sum(
                    "colis__montant_jc", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                ),
                # Nombre de colis payés en Chine parmi les livrés/perdus
                nb_colis_payes_chine=Count(
                    "colis",
                    filter=Q(
                        colis__status__in=["LIVRE", "PERDU"], colis__paye_en_chine=True
                    ),
                ),
                cbm_total_livre=Sum(
                    "colis__cbm", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                ),
                poids_total_livre=Sum(
                    "colis__poids", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                ),
            )
            .annotate(
                benefice_calcule=ExpressionWrapper(
                    Coalesce(
                        F("total_recettes_livre"), 0.0, output_field=DecimalField()
                    )
                    - Coalesce(F("frais_transport"), 0.0, output_field=DecimalField())
                    - Coalesce(F("frais_douane"), 0.0, output_field=DecimalField()),
                    output_field=DecimalField(),
                )
            )
            .filter(nb_colis_livre__gt=0)
            .distinct()
        )

        # Filtrage par type de transport
        transport = self.request.GET.get("transport")
        if transport in ["CARGO", "EXPRESS", "BATEAU"]:
            queryset = queryset.filter(type_transport=transport)

        # Filtrage par mois/année
        month = self.request.GET.get("month")
        year = self.request.GET.get("year")
        if month and year:
            queryset = queryset.filter(
                colis__date_livraison__month=month, colis__date_livraison__year=year
            )
        elif year:
            queryset = queryset.filter(colis__date_livraison__year=year)

        return queryset.order_by("-updated_at")


from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Q
from core.models import Colis
from mali.views import DestinationAgentRequiredMixin

class ColisSortieGarantieView(LoginRequiredMixin, DestinationAgentRequiredMixin, ListView):
    """
    Page Sortie Garantie : Affiche les colis sortis sous garantie, regroupés par personne autorisée.
    """
    template_name = "mali/colis_sortie_garantie.html"
    context_object_name = "personnes"
    
    def get_queryset(self):
        mali = self.get_current_country()
        qs = Colis.objects.filter(status="LIVRE", sortie_sous_garantie=True)
        if mali:
            qs = qs.filter(lot__destination=mali)
            
        # Isolation Aérien / Maritime
        if getattr(self.request, "is_maritime", False):
            qs = qs.filter(lot__type_transport="BATEAU")
        else:
            qs = qs.filter(lot__type_transport__in=["CARGO", "EXPRESS"])
            
        q = self.request.GET.get('q')
        date_debut = self.request.GET.get('date_debut')
        date_fin = self.request.GET.get('date_fin')
        
        if q:
            qs = qs.filter(sortie_autorisee_par__icontains=q)
        if date_debut:
            qs = qs.filter(date_livraison__date__gte=date_debut)
        if date_fin:
            qs = qs.filter(date_livraison__date__lte=date_fin)
            
        personnes_names = qs.exclude(sortie_autorisee_par__isnull=True).exclude(sortie_autorisee_par="").values_list('sortie_autorisee_par', flat=True).distinct()
        return list(personnes_names)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # We need to apply the same date filters to the aggregates!
        date_debut = self.request.GET.get('date_debut')
        date_fin = self.request.GET.get('date_fin')
        
        personnes_data = []
        for nom in self.object_list:
            colis_personne = Colis.objects.filter(status="LIVRE", sortie_sous_garantie=True, sortie_autorisee_par=nom)
            if date_debut:
                colis_personne = colis_personne.filter(date_livraison__date__gte=date_debut)
            if date_fin:
                colis_personne = colis_personne.filter(date_livraison__date__lte=date_fin)
                
            personnes_data.append({
                'nom': nom,
                'nb_colis': colis_personne.count(),
                'total_poids': colis_personne.aggregate(t=Sum('poids'))['t'] or 0,
                'total_cbm': colis_personne.aggregate(t=Sum('cbm'))['t'] or 0,
            })
        
        context["personnes_data"] = personnes_data
        context["q"] = self.request.GET.get('q', '')
        context["date_debut"] = self.request.GET.get('date_debut', '')
        context["date_fin"] = self.request.GET.get('date_fin', '')
        return context

class ColisSortieGarantieDetailView(LoginRequiredMixin, DestinationAgentRequiredMixin, ListView):
    template_name = "mali/personne_sortie_detail.html"
    context_object_name = "colis_list"
    paginate_by = 50

    def get_queryset(self):
        nom_personne = self.kwargs.get('nom')
        qs = Colis.objects.filter(status="LIVRE", sortie_sous_garantie=True, sortie_autorisee_par=nom_personne)
        
        # Isolation Aérien / Maritime
        if getattr(self.request, "is_maritime", False):
            qs = qs.filter(lot__type_transport="BATEAU")
        else:
            qs = qs.filter(lot__type_transport__in=["CARGO", "EXPRESS"])
            
        q = self.request.GET.get('q')
        date_debut = self.request.GET.get('date_debut')
        date_fin = self.request.GET.get('date_fin')
        
        if q:
            qs = qs.filter(Q(reference__icontains=q) | Q(client__nom__icontains=q) | Q(client__telephone__icontains=q))
        if date_debut:
            qs = qs.filter(date_livraison__date__gte=date_debut)
        if date_fin:
            qs = qs.filter(date_livraison__date__lte=date_fin)
            
        return qs.select_related("lot", "client", "client__user").order_by("-date_livraison")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["nom_personne"] = self.kwargs.get('nom')
        context["q"] = self.request.GET.get('q', '')
        context["date_debut"] = self.request.GET.get('date_debut', '')
        context["date_fin"] = self.request.GET.get('date_fin', '')
        return context

class MaliClientLotTarifCreateView(AdminMaliRequiredMixin, CreateView):
    """
    Attribue un tarif spécial à un client pour un lot spécifique.
    Recalcule automatiquement les prix de tous les colis du client dans ce lot.
    """

    model = ClientLotTarif
    form_class = MaliClientLotTarifForm
    template_name = "mali/admin/client_lot_tarif_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        self.lot = get_object_or_404(Lot, pk=self.kwargs.get("lot_pk"))

        if self.lot.type_transport == "BATEAU":
            messages.error(
                self.request,
                "La tarification spéciale n'est pas disponible pour les lots de type BATEAU.",
            )

        kwargs["lot"] = self.lot
        return kwargs

    def form_valid(self, form):
        form.instance.admin_mali = self.request.user

        existing = ClientLotTarif.objects.filter(
            client=form.instance.client, destination=self.request.user.country
        ).first()

        if existing:
            existing.prix_kilo = form.instance.prix_kilo
            existing.admin_mali = self.request.user
            existing.destination = self.request.user.country
            existing.save()
            tarif = existing
        else:
            form.instance.destination = self.request.user.country
            tarif = form.save()

        from core.models import Colis
        colis_list = Colis.objects.filter(
            client=tarif.client, lot__destination=tarif.destination
        )
        count = colis_list.count()
        for colis in colis_list:
            colis.recalculate_prices()
            colis.save()

        messages.success(
            self.request,
            f"Le tarif GLOBAL de {tarif.prix_kilo} FCFA/kg a été appliqué aux {count} colis de {tarif.client} dans le système.",
        )
        return redirect("mali:admin_client_lot_tarif", lot_pk=self.lot.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self.lot = getattr(
            self, "lot", get_object_or_404(Lot, pk=self.kwargs.get("lot_pk"))
        )
        context["lot"] = self.lot
        context["existing_tarifs"] = ClientLotTarif.objects.filter(
            destination=self.request.user.country,
            client__country=self.request.user.country,
        ).select_related("client")
        return context


class MaliClientLotTarifDeleteView(AdminMaliRequiredMixin, View):
    def post(self, request, lot_pk, pk):
        tarif = get_object_or_404(
            ClientLotTarif, pk=pk, destination=request.user.country
        )
        client = tarif.client

        tarif.delete()

        from core.models import Colis
        colis_list = Colis.objects.filter(
            client=client, lot__destination=request.user.country
        )
        for colis in colis_list:
            colis.recalculate_prices()
            colis.save()

        messages.warning(
            request,
            f"La convention tarifaire pour {client} a été supprimée. Les prix de tous ses colis vers {request.user.country} ont été rétablis au tarif standard.",
        )
        return redirect("mali:admin_client_lot_tarif", lot_pk=lot_pk)

