from django.views.generic import TemplateView, ListView, View, DetailView, CreateView
from django.views.generic.edit import UpdateView
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.urls import reverse, reverse_lazy
from django.db.models import Q, Count, Sum, Value, F, DecimalField, DateField, ExpressionWrapper
from django.db.models.functions import Concat, Coalesce
from core.mixins import DestinationAgentRequiredMixin, AdminMaliRequiredMixin
from core.models import Country, Lot, Colis, Client, User, AvanceSalaire, ClientLotTarif
from report.models import Depense, TransfertArgent, PaiementAgent
from django.contrib import messages

from notification.models import ConfigurationNotification
from .forms import NotificationConfigForm, AvanceSalaireForm, MaliAgentForm, MaliClientLotTarifForm
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

        # 1. Colis Livrés (mois en cours) et Recettes
        colis_livres_mois_qs = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", updated_at__gte=first_day_of_month
        )
        context["colis_livres_mois"] = colis_livres_mois_qs.count()

        # Recettes nettes du mois (déjà payés + livrés)
        recettes_mois = (
            colis_livres_mois_qs.filter(est_paye=True).aggregate(
                total=Sum(F("prix_final") - F("montant_jc"))
            )["total"]
            or 0
        )
        context["recettes_mois"] = recettes_mois

        # Poids total des colis livrés (mois en cours)
        total_poids_mois = (
            colis_livres_mois_qs.aggregate(total=Sum("poids"))["total"] or 0
        )
        context["total_poids_mois"] = total_poids_mois

        # 2. Dépenses (mois)
        depenses_base_mois_qs = Depense.objects.filter(
            Q(pays=mali) | Q(is_china_indicative=True),
            date__year=today.year, date__month=today.month
        )
        depenses_classiques_mois_qs = depenses_base_mois_qs.filter(is_china_indicative=False)
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
        context["colis_perdus_mois"] = Colis.objects.filter(
            lot__destination=mali, status="PERDU", updated_at__gte=first_day_of_month
        ).count()

        # 4. Colis en attente de paiement (non payés)
        context["colis_attente_paiement"] = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", est_paye=False
        ).count()

        # 5. Colis à Traiter (Arrivés, non livrés)
        context["colis_a_traiter"] = Colis.objects.filter(
            lot__destination=mali, status="ARRIVE"
        ).count()

        # 6. Lots en Transit
        context["lots_en_transit"] = Lot.objects.filter(
            destination=mali, status="EN_TRANSIT"
        ).count()

        # 7. Lots Arrivés (Incomplets) - Au moins 1 colis status ARRIVE
        lots_avec_stock = Lot.objects.filter(
            destination=mali, colis__status="ARRIVE"
        ).distinct()
        context["lots_arrives_incomplets"] = lots_avec_stock.count()

        # 7b. Lots Livrés (Mois) - Lots ayant des colis livrés ce mois ci
        context["lots_livres_mois"] = (
            Lot.objects.filter(
                destination=mali,
                colis__status="LIVRE",
                colis__updated_at__gte=first_day_of_month,
            )
            .distinct()
            .count()
        )

        # 8. Encaissements du Jour (Montant total des livraisons du jour)
        encaissements = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", date_encaissement=today
        ).aggregate(total=Sum("prix_final"))
        context["encaissements_jour"] = encaissements["total"] or 0

        # 9. Total Clients Mali
        context["total_clients_mali"] = Client.objects.filter(country=mali).count()

        # Activité récente (derniers colis pointés/livrés aujourd'hui)
        # Activité récente (derniers colis pointés/livrés aujourd'hui)
        context["activites_recentes"] = (
            Colis.objects.filter(
                Q(lot__destination=mali),
                Q(status__in=["ARRIVE", "LIVRE", "PERDU"]),
                Q(date_livraison=today) | Q(date_encaissement=today),
            )
            .select_related("client", "lot")
            .annotate(sort_date=Coalesce("date_livraison", "updated_at", output_field=DateField()))
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
        from report.models import TransfertArgent

        # --- 1. SOLDE VEILLE (Report) ---
        # Calcul : Total Recettes (depuis début) - Total Dépenses (depuis début) jusqu'à hier
        from django.db.models import Sum, F

        recettes_globales = (
            Colis.objects.filter(
                lot__destination=mali,
                status="LIVRE",
            ).filter(
                Q(date_encaissement__lt=today) |
                Q(date_encaissement__isnull=True, date_livraison__lt=today) |
                Q(date_encaissement__isnull=True, date_livraison__isnull=True, updated_at__date__lt=today)
            ).aggregate(total=Sum(F("prix_final") - F("montant_jc") - F("reste_a_payer")))["total"]
            or 0
        )

        depenses_globales = (
            Depense.objects.filter(
                pays=mali,
                is_china_indicative=False,
                date__lt=today
            ).aggregate(total=Sum("montant"))["total"]
            or 0
        )

        # Les transferts sont considérés comme des dépenses (sorties de caisse)
        transferts_globaux = (
            TransfertArgent.objects.filter(
                pays_expediteur=mali, date__lt=today
            ).aggregate(total=Sum("montant"))["total"]
            or 0
        )

        context["solde_veille"] = recettes_globales - (
            depenses_globales + transferts_globaux
        )

        # --- 2. ACTIVITÉ DU JOUR (Cargo, Express, Bateau) ---
        # On définit le périmètre du jour : date_encaissement OU repli historique
        colis_livres_jour = Colis.objects.filter(
            lot__destination=mali, 
            status="LIVRE"
        ).filter(
            Q(date_encaissement=today) |
            Q(date_encaissement__isnull=True, date_livraison=today) |
            Q(date_encaissement__isnull=True, date_livraison__isnull=True, updated_at__date=today)
        ).select_related("client", "lot")

        # Séparation par type de transport (via le Lot)
        # Note: Lot.type_transport choices: CARGO, EXPRESS, BATEAU

        # A. Cargo (Air)
        colis_cargo = colis_livres_jour.filter(lot__type_transport="CARGO")
        recette_cargo = (
            colis_cargo.aggregate(
                total=Sum(F("prix_final") - F("montant_jc") - F("reste_a_payer"))
            )["total"]
            or 0
        )
        poids_cargo = colis_cargo.aggregate(total=Sum("poids"))["total"] or 0

        context["colis_cargo_list"] = colis_cargo.annotate(
            net_price=F("prix_final") - F("montant_jc") - F("reste_a_payer"),
            sort_date=Coalesce("date_livraison", "updated_at", output_field=DateField())
        ).order_by("-sort_date", "-updated_at")
        context["recette_cargo_jour"] = recette_cargo
        context["poids_cargo_jour"] = poids_cargo

        # B. Express (Air)
        colis_express = colis_livres_jour.filter(lot__type_transport="EXPRESS")
        recette_express = (
            colis_express.aggregate(
                total=Sum(F("prix_final") - F("montant_jc") - F("reste_a_payer"))
            )["total"]
            or 0
        )
        poids_express = colis_express.aggregate(total=Sum("poids"))["total"] or 0

        context["colis_express_list"] = colis_express.annotate(
            net_price=F("prix_final") - F("montant_jc") - F("reste_a_payer"),
            sort_date=Coalesce("date_livraison", "updated_at", output_field=DateField())
        ).order_by("-sort_date", "-updated_at")
        context["recette_express_jour"] = recette_express
        context["poids_express_jour"] = poids_express

        # C. Bateau (Maritime)
        colis_bateau = colis_livres_jour.filter(lot__type_transport="BATEAU")
        recette_bateau = (
            colis_bateau.aggregate(
                total=Sum(F("prix_final") - F("montant_jc") - F("reste_a_payer"))
            )["total"]
            or 0
        )
        poids_bateau = colis_bateau.aggregate(total=Sum("poids"))["total"] or 0
        cbm_bateau = colis_bateau.aggregate(total=Sum("cbm"))["total"] or 0

        context["colis_bateau_list"] = colis_bateau.annotate(
            net_price=F("prix_final") - F("montant_jc") - F("reste_a_payer"),
            sort_date=Coalesce("date_livraison", "updated_at", output_field=DateField())
        ).order_by("-sort_date", "-updated_at")
        context["recette_bateau_jour"] = recette_bateau
        context["poids_bateau_jour"] = poids_bateau
        context["cbm_bateau_jour"] = cbm_bateau

        # Total Recettes Jour
        context["total_recettes_jour"] = (
            recette_cargo + recette_express + recette_bateau
        )

        # Poids Total Jour (Kilos livrés du jour)
        context["total_poids_jour"] = poids_cargo + poids_express + poids_bateau

        # Total JC Jour (Pour info)
        context["total_jc_jour"] = (
            colis_livres_jour.aggregate(total=Sum("montant_jc"))["total"] or 0
        )

        # --- 3. DÉPENSES & TRANSFERTS DU JOUR ---
        # Dépenses - On inclut les dépenses indicatives Chine (même avec pays=Chine)
        depenses_jour_qs = Depense.objects.filter(
            Q(pays=mali) | Q(is_china_indicative=True),
            date=today
        ).order_by("-created_at")

        # Dépenses Jour (Réelles Mali)
        context["depenses_jour_reelles"] = depenses_jour_qs.filter(
            is_china_indicative=False
        )
        total_depenses_mali = (
            context["depenses_jour_reelles"].aggregate(total=Sum("montant"))["total"]
            or 0
        )

        # Dépenses Jour (Indicatives Chine)
        context["depenses_indicatives_jour"] = depenses_jour_qs.filter(
            is_china_indicative=True
        )
        context["total_depenses_indicatives"] = (
            context["depenses_indicatives_jour"].aggregate(total=Sum("montant"))[
                "total"
            ]
            or 0
        )

        # Transferts (considérés comme dépenses jour)
        transferts_jour_qs = TransfertArgent.objects.filter(
            pays_expediteur=mali, date=today
        ).order_by("-created_at")

        total_transferts = (
            transferts_jour_qs.aggregate(total=Sum("montant"))["total"] or 0
        )

        context["depenses_jour_list"] = depenses_jour_qs
        context["transferts_jour_list"] = transferts_jour_qs

        # Séparation des transferts pour l'affichage
        context["transferts_chine_list"] = transferts_jour_qs.filter(
            destinataire="CHINE"
        )
        context["transferts_gaoussou_list"] = transferts_jour_qs.filter(
            destinataire="GAOUSSOU"
        )

        # Sorties Jour réelles (pour solde caisse)
        context["total_sorties_jour"] = total_depenses_mali + total_transferts
        context["total_depenses_only"] = total_depenses_mali
        context["total_transferts_only"] = total_transferts

        # --- 4. SOLDE CAISSE ACTUEL ---
        # Solde Veille + Recettes Jour - Sorties Jour (Réelles)
        context["solde_caisse_actuel"] = (
            context["solde_veille"]
            + context["total_recettes_jour"]
            - context["total_sorties_jour"]
        )

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

        # Un lot apparaît en transit s'il a au moins un colis EXPEDIE
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
                # Nombre de colis déjà payés en Chine dans ce lot (parmi les colis en transit)
                nb_colis_payes_chine=Count(
                    "colis",
                    filter=Q(colis__status="EXPEDIE", colis__est_paye=True),
                ),
            )
            .annotate(
                benefice_calcule=ExpressionWrapper(
                    Coalesce(F("total_recettes_transit"), 0.0, output_field=DecimalField()) -
                    Coalesce(F("frais_transport"), 0.0, output_field=DecimalField()) -
                    Coalesce(F("frais_douane"), 0.0, output_field=DecimalField()),
                    output_field=DecimalField()
                )
            )
            .filter(nb_colis_transit__gt=0)
            .distinct()
        )

        query = self.request.GET.get("q")
        if query:
            queryset = queryset.annotate(
                nom_complet=Concat(
                    "colis__client__nom", Value(" "), "colis__client__prenom"
                ),
                prenom_complet=Concat(
                    "colis__client__prenom", Value(" "), "colis__client__nom"
                ),
            )
            search_fields = [
                "numero",
                "colis__client__nom",
                "colis__client__prenom",
                "colis__client__telephone",
                "nom_complet",
                "prenom_complet",
            ]
            queryset = apply_flexible_search(queryset, query, search_fields)

        return queryset.order_by("-date_expedition")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
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

        # Un lot apparaît en arrivés s'il a au moins un colis ARRIVE
        queryset = (
            Lot.objects.filter(destination=mali, colis__status="ARRIVE")
            .select_related("destination")
            .prefetch_related("colis")
            .annotate(
                # On ne compte que les colis arrivés pour ce lot dans cette vue
                nb_colis_arrive=Count("colis", filter=Q(colis__status="ARRIVE")),
                poids_total_arrive=Sum(
                    "colis__poids", filter=Q(colis__status="ARRIVE")
                ),
                total_recettes_arrive=Sum(
                    "colis__prix_final", filter=Q(colis__status="ARRIVE")
                ),
                # Nombre de colis déjà payés en Chine (parmi les colis arrivés)
                nb_colis_payes_chine=Count(
                    "colis",
                    filter=Q(colis__status="ARRIVE", colis__est_paye=True),
                ),
            )
            .annotate(
                benefice_calcule=ExpressionWrapper(
                    Coalesce(F("total_recettes_arrive"), 0.0, output_field=DecimalField()) -
                    Coalesce(F("frais_transport"), 0.0, output_field=DecimalField()) -
                    Coalesce(F("frais_douane"), 0.0, output_field=DecimalField()),
                    output_field=DecimalField()
                )
            )
            .filter(nb_colis_arrive__gt=0)
            .distinct()
        )

        query = self.request.GET.get("q")
        if query:
            queryset = queryset.annotate(
                nom_complet=Concat(
                    "colis__client__nom", Value(" "), "colis__client__prenom"
                ),
                prenom_complet=Concat(
                    "colis__client__prenom", Value(" "), "colis__client__nom"
                ),
            )
            search_fields = [
                "numero",
                "colis__client__nom",
                "colis__client__prenom",
                "colis__client__telephone",
                "nom_complet",
                "prenom_complet",
            ]
            queryset = apply_flexible_search(queryset, query, search_fields)

        return queryset.order_by("-date_arrivee", "-created_at")


class LotsLivresView(LotsEnTransitView):
    """Historique des lots ayant des colis LIVRÉS ou PERDUS"""
    paginate_by = 10
    template_name = "mali/lots_livres.html"

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Lot.objects.none()

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
            )
            .annotate(
                benefice_calcule=ExpressionWrapper(
                    Coalesce(F("total_recettes_livre"), 0.0, output_field=DecimalField()) -
                    Coalesce(F("frais_transport"), 0.0, output_field=DecimalField()) -
                    Coalesce(F("frais_douane"), 0.0, output_field=DecimalField()),
                    output_field=DecimalField()
                )
            )
            .filter(nb_colis_livre__gt=0)
            .distinct()
        )

        # Filtrage par mois/année
        month = self.request.GET.get("month")
        year = self.request.GET.get("year")
        if month and year:
            queryset = queryset.filter(
                colis__date_livraison__month=month, colis__date_livraison__year=year
            )
        elif year:
            queryset = queryset.filter(colis__date_livraison__year=year)

        query = self.request.GET.get("q")
        if query:
            queryset = queryset.annotate(
                nom_complet=Concat(
                    "colis__client__nom", Value(" "), "colis__client__prenom"
                ),
            )
            search_fields = [
                "numero",
                "colis__client__nom",
                "colis__client__telephone",
                "nom_complet",
            ]
            queryset = apply_flexible_search(queryset, query, search_fields)

        return queryset.order_by("-updated_at")


class ColisSortieGarantieView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, ListView
):
    """Liste des colis sortis sous garantie avec filtres de période et stats"""

    template_name = "mali/colis_sortie_garantie.html"
    context_object_name = "colis_list"
    paginate_by = 20

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Colis.objects.none()

        queryset = Colis.objects.filter(
            lot__destination=mali,
            status="LIVRE",
            sortie_sous_garantie=True,
        ).select_related("client", "lot")

        now = timezone.now()
        self.filter_month = self.request.GET.get("month", "")
        self.filter_year = self.request.GET.get("year", "")

        if self.filter_year:
            try:
                queryset = queryset.filter(date_encaissement__year=int(self.filter_year))
            except (ValueError, TypeError):
                pass
        if self.filter_month:
            try:
                queryset = queryset.filter(date_encaissement__month=int(self.filter_month))
            except (ValueError, TypeError):
                pass

        return queryset.annotate(
            sort_date=Coalesce("date_livraison", "updated_at", output_field=DateField())
        ).order_by("-sort_date", "-updated_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        now = timezone.now()

        mali = self.get_current_country()

        # Queryset non paginé pour stats
        base_qs = (
            Colis.objects.filter(
                lot__destination=mali,
                status="LIVRE",
                sortie_sous_garantie=True,
            )
            if mali
            else Colis.objects.none()
        )

        # Stats globales
        total_stats = base_qs.aggregate(
            total_count=Count("id"),
            total_montant=Sum(F("prix_final") - F("montant_jc")),
        )

        # Stats mois en cours
        stats_month = base_qs.filter(
            date_encaissement__year=now.year, date_encaissement__month=now.month
        ).aggregate(
            count=Count("id"),
            montant=Sum(F("prix_final") - F("montant_jc")),
        )

        # Stats année en cours
        stats_year = base_qs.filter(date_encaissement__year=now.year).aggregate(
            count=Count("id"),
            montant=Sum(F("prix_final") - F("montant_jc")),
        )

        context.update(
            {
                "filter_month": self.filter_month,
                "filter_year": self.filter_year,
                "current_year": now.year,
                "current_month": now.month,
                "years_range": range(now.year - 2, now.year + 1),
                "stats_total": {
                    "count": total_stats["total_count"] or 0,
                    "montant": total_stats["total_montant"] or 0,
                },
                "stats_month": {
                    "count": stats_month["count"] or 0,
                    "montant": stats_month["montant"] or 0,
                },
                "stats_year": {
                    "count": stats_year["count"] or 0,
                    "montant": stats_year["montant"] or 0,
                },
            }
        )
        return context


class LotDetailView(LoginRequiredMixin, DestinationAgentRequiredMixin, DetailView):
    """Vue détaillée d'un lot pour l'agent Mali (avec pointage des colis)"""

    model = Lot
    template_name = "mali/lot_detail.html"
    context_object_name = "lot"

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

        # Recalcul des agrégats pour les colis ARRIVE uniquement
        aggregates = self.object.colis.filter(status="ARRIVE").aggregate(
            total_poids=Sum("poids"),
            total_montant=Sum("prix_final"),
        )
        context["total_poids"] = aggregates["total_poids"] or 0
        context["total_montant_colis"] = aggregates["total_montant"] or 0

        # Filtrage des colis listés (ARRIVE + LIVRE pour la pagination visible)
        colis_qs = self.object.colis.all()
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

        paginator = Paginator(colis_qs.annotate(sort_date=Coalesce("date_livraison", "updated_at", output_field=DateField())).order_by("-sort_date", "-updated_at"), 20)
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
        colis_qs.update(status="ARRIVE")

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
                f"📍 *{'Bonne nouvelle ! Votre colis est arriv\u00e9 !' if nb == 1 else f'Bonne nouvelle ! Vos {nb} colis sont arriv\u00e9s !'}*\n\n"
                f"Nous venons de r\u00e9ceptionner {'votre colis' if nb == 1 else 'vos colis'} \u00e0 l'agence au Mali 🇲🇱 le *{date_arrive}* :\n"
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

        # Si le lot était en transit, il passe en ARRIVE (global)
        # MODIF : On ne change PAS le statut automatiquement ici pour permettre le pointage dans la vue Transit.
        # Le statut passera à ARRIVE quand ? Manuellement ou quand tout est pointé ?
        # Pour l'instant on laisse en TRANSIT pour que l'agent puisse voir la liste et pointer.
        # if lot.status == "EN_TRANSIT":
        #    lot.status = "ARRIVE"
        #    lot.date_arrivee = timezone.now()

        lot.save()

        # On peut aussi forcer l'arrivée de tous les colis non pointés si on veut
        # lot.colis.filter(status="EXPEDIE").update(status="ARRIVE")

        messages.success(
            request,
            f"Frais enregistrés pour le lot {lot.numero}. Vous pouvez maintenant pointer les colis.",
        )
        return redirect("mali:lot_transit_detail", pk=lot.pk)


class NotifyArrivalsView(LoginRequiredMixin, AdminMaliRequiredMixin, View):
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
                f"📍 *{'Bonne nouvelle ! Votre colis est arriv\u00e9 !' if nb == 1 else f'Bonne nouvelle ! Vos {nb} colis sont arriv\u00e9s !'}*\n\n"
                f"Nous venons de r\u00e9ceptionner {'votre colis' if nb == 1 else 'vos colis'} \u00e0 l'agence au Mali 🇲🇱 :\n"
                f"{liste_str}\n\n"
                f"💰 *Total \u00e0 r\u00e9gler : {fmt_total} FCFA*\n\n"
                f"Merci de passer {'le' if nb == 1 else 'les'} r\u00e9cup\u00e9rer \u00e0 votre convenance.\n\n"
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
            colis.sortie_autorisee_par = request.POST.get("sortie_autorisee_par", "")
        else:
            colis.sortie_sous_garantie = False
            colis.sortie_autorisee_par = ""

        # Gestion Jeton Cédé
        try:
            jc = request.POST.get("montant_jc", "0")
            colis.montant_jc = float(jc) if jc else 0
        except ValueError:
            colis.montant_jc = 0

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
                    rp = request.POST.get("reste_a_payer", "0")
                    colis.reste_a_payer = float(rp) if rp else 0
                    colis.est_paye = colis.reste_a_payer <= 0
                except ValueError:
                    colis.reste_a_payer = 0
                    colis.est_paye = False
            else:  # ATTENTE ou autre
                colis.est_paye = False
                colis.reste_a_payer = max(
                    0, (colis.prix_final or 0) - (colis.montant_jc or 0)
                )

        colis.mode_paiement = request.POST.get("mode_paiement")
        colis.status = "LIVRE"
        colis.date_livraison = request.POST.get("date_livraison") or timezone.now().date()
        if colis.est_paye or status_paiement == "PARTIEL":
            colis.date_encaissement = request.POST.get("date_encaissement") or timezone.now().date()
        colis.save()

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
        date_encaissement = request.POST.get("date_encaissement") or timezone.now().date()

        if not colis_ids:
            messages.warning(request, "Aucun colis sélectionné pour la livraison.")
            return redirect("mali:lot_arrived_detail", pk=lot.pk)

        colis_qs = Colis.objects.filter(id__in=colis_ids, lot=lot, status="ARRIVE")

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

        for c in colis_list:
            c.status = "LIVRE"
            c.mode_livraison = mode_livraison
            c.mode_paiement = mode_paiement
            c.infos_recepteur = infos_recepteur
            
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
                    # Distribution proportionnelle du reste
                    if total_net_selection > Decimal("0"):
                        part_colis = (c.prix_final or Decimal("0")) - (
                            c.montant_jc or Decimal("0")
                        )
                        share = part_colis / total_net_selection
                        c.reste_a_payer = (reste_global * share).quantize(Decimal("1"))
                    else:
                        c.reste_a_payer = Decimal("0")
                    c.est_paye = c.reste_a_payer <= Decimal("0")
                else:  # ATTENTE
                    c.est_paye = False
                    c.reste_a_payer = max(
                        Decimal("0"),
                        (c.prix_final or Decimal("0")) - (c.montant_jc or Decimal("0")),
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
            ],
        )

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
                f"\u2705 *{'Livraison r\u00e9ussie !' if nb == 1 else f'Livraison r\u00e9ussie pour vos {nb} colis !'}*\n\n"
                f"{'Le colis suivant a' if nb == 1 else 'Les colis suivants ont'} bien \u00e9t\u00e9 livr\u00e9{'s' if nb > 1 else ''} avec succ\u00e8s :\n"
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
            .annotate(sort_date=Coalesce("date_livraison", "updated_at", output_field=DateField())).order_by("-sort_date", "-updated_at")
        )

        query = self.request.GET.get("q")
        if query:
            # (Recherche multi-mots gérée par le reste du code)
            queryset = apply_flexible_search(queryset, query)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Calcul du total des impayés basé sur l'annotation
        total_impaye = (
            self.get_queryset().aggregate(total=Sum("montant_du"))["total"] or 0
        )
        context["total_impaye"] = total_impaye
        context["q"] = self.request.GET.get("q", "")
        return context


class ColisEncaissementView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Encaisser un colis (marquer comme payé) avec mise à jour de la date"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)

        # Marquer comme payé et solder le reste à payer
        colis.est_paye = True
        colis.reste_a_payer = 0
        
        # Date d'encaissement (depuis POST ou aujourd'hui)
        date_enc = request.POST.get("date_encaissement")
        if date_enc:
            colis.date_encaissement = date_enc
        else:
            colis.date_encaissement = timezone.now().date()

        colis.save()

        messages.success(request, f"Paiement encaissé pour le colis {colis.reference}.")

        # Redirection vers la liste des paiements en attente (ou la page précédente)
        return redirect("mali:colis_attente_paiement")


class ColisEncaissementBulkView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, View
):
    """Encaisser plusieurs colis en masse"""

    def post(self, request):
        colis_ids = request.POST.getlist("colis_ids")
        mode_paiement = request.POST.get("mode_paiement", "ESPECE")
        date_encaissement = request.POST.get("date_encaissement") or timezone.now().date()
        
        if not colis_ids:
            messages.warning(request, "Aucun colis sélectionné.")
            return redirect("mali:colis_attente_paiement")

        colis_qs = Colis.objects.filter(
            id__in=colis_ids, status="LIVRE", est_paye=False
        )
        colis_list = list(colis_qs)

        now = timezone.now()
        for c in colis_list:
            c.est_paye = True
            c.reste_a_payer = 0
            c.mode_paiement = mode_paiement
            c.date_encaissement = date_encaissement
            c.updated_at = timezone.now()

        Colis.objects.bulk_update(
            colis_list, ["est_paye", "reste_a_payer", "mode_paiement", "date_encaissement", "updated_at"]
        )

        messages.success(
            request,
            f"{len(colis_list)} paiements encaissés avec succès ({mode_paiement}).",
        )
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

        # Base QuerySet : Colis livrés aujourd'hui au Mali (incluant repli historique)
        colis_qs = (
            Colis.objects.filter(
                lot__destination__code="ML",
                status="LIVRE"
            ).filter(
                Q(date_encaissement=today) |
                Q(date_encaissement__isnull=True, date_livraison=today) |
                Q(date_encaissement__isnull=True, date_livraison__isnull=True, updated_at__date=today)
            )
            .select_related("client", "lot")
            .annotate(net_price=F("prix_final") - F("montant_jc") - F("reste_a_payer"))
            .order_by("-date_livraison", "-updated_at")
        )

        # Filtrage par type
        if report_type in ["cargo", "express", "bateau"]:
            colis_qs = colis_qs.filter(lot__type_transport=report_type.upper())

        # Calcul des totaux pour ces colis filtrés
        encaissements = colis_qs.aggregate(total=Sum("net_price"))["total"] or 0
        total_jc = colis_qs.aggregate(total=Sum("montant_jc"))["total"] or 0

        # Récupération des dépenses et transferts (Uniquement pour le rapport Global ?)
        # Décision : On affiche les dépenses/transferts uniquement sur le rapport Global
        # Car il est difficile de les attribuer à une activité spécifique (sauf si on catégorise les transferts)
        total_depenses = 0
        total_transferts = 0
        solde_veille = 0

        if report_type == "global":
            # Solde Veille cumulé (Recettes - Dépenses - Transferts jusqu'à hier)
            recettes_globales_veille = (
                Colis.objects.filter(
                    lot__destination__code="ML",
                    status="LIVRE",
                ).filter(
                    Q(date_encaissement__lt=today) |
                    Q(date_encaissement__isnull=True, date_livraison__lt=today) |
                    Q(date_encaissement__isnull=True, date_livraison__isnull=True, updated_at__date__lt=today)
                ).aggregate(
                    total=Sum(F("prix_final") - F("montant_jc") - F("reste_a_payer"))
                )["total"]
                or 0
            )

            # Dépenses cumulées Mali uniquement (Exclut indicatif Chine)
            depenses_globales_veille = (
                Depense.objects.filter(
                    pays__code="ML", 
                    is_china_indicative=False, 
                    date__lt=today
                ).aggregate(total=Sum("montant"))["total"]
                or 0
            )
            from report.models import TransfertArgent

            transferts_globaux_veille = (
                TransfertArgent.objects.filter(
                    pays_expediteur__code="ML", date__lt=today
                ).aggregate(total=Sum("montant"))["total"]
                or 0
            )
            solde_veille = recettes_globales_veille - (
                depenses_globales_veille + transferts_globaux_veille
            )

            # Dépenses Jour Mali uniquement
            total_depenses = (
                Depense.objects.filter(
                    pays__code="ML", date=today, is_china_indicative=False
                ).aggregate(total=Sum("montant"))["total"]
                or 0
            )
            # Transferts Jour
            total_transferts = (
                TransfertArgent.objects.filter(
                    pays_expediteur__code="ML", date=today
                ).aggregate(total=Sum("montant"))["total"]
                or 0
            )

        # Calcul du solde final (pour ce rapport)
        solde_final = 0
        if report_type == "global":
            solde_final = (
                solde_veille + encaissements - (total_depenses + total_transferts)
            )
        else:
            solde_final = (
                encaissements  # Pour un rapport spécifique, le solde est le CA généré
            )

        # Calcul du poids total pour le rapport
        total_poids = colis_qs.aggregate(total=Sum("poids"))["total"] or 0

        # Contexte pour le template
        context = {
            "date": today,
            "report_type": report_type,
            "titre_rapport": titre_rapport,
            "colis_list": colis_qs,
            "total_encaissements": encaissements,
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


class NotificationConfigView(
    LoginRequiredMixin, AdminMaliRequiredMixin, UpdateView
):
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


class MaliRetryNotificationsView(
    LoginRequiredMixin, AdminMaliRequiredMixin, View
):
    """Relance toutes les notifications en échec pour la région Mali"""

    def post(self, request):
        from notification.tasks import retry_failed_notifications_periodic

        retry_failed_notifications_periodic.delay(force_retry_all=True)
        messages.success(request, "Les relances WhatsApp Mali ont été déclenchées.")
        return redirect("mali:notification_list")


from django.views.generic import UpdateView
from .forms import ColisUpdateMaliForm


class ColisUpdateMaliView(LoginRequiredMixin, AdminMaliRequiredMixin, UpdateView):
    """Permet à l'administrateur Mali de corriger le poids, le CBM ou le prix d'un colis."""

    model = Colis
    form_class = ColisUpdateMaliForm
    template_name = "mali/colis_update.html"

    def get_success_url(self):
        messages.success(
            self.request,
            f"Le carton {self.object.reference} a été corrigé avec succès.",
        )
        return reverse("mali:admin_correction_lot_detail", kwargs={"pk": self.object.lot.pk})

    def form_valid(self, form):
        # On sauvegarde les anciennes valeurs pour recalculer le reste à payer si besoin
        old_colis = self.get_object()
        deja_paye = old_colis.prix_final - old_colis.reste_a_payer

        # Sauvegarde du formulaire (sans commit pour ajuster le type)
        colis = form.save(commit=False)
        
        # Si un prix au kilo manuel est saisi, on force le type MANUEL
        if colis.prix_kilo_manuel:
            colis.type_colis = "MANUEL"
            
        # Recalculer les prix via la méthode centrale du modèle
        colis.recalculate_prices()
        
        # Ajuster le reste à payer en fonction du nouveau prix
        # On repart du prix final et on enlève ce qui a déjà été payé
        colis.reste_a_payer = colis.prix_final - deja_paye
        
        # Si le reste à payer devient négatif (baisse de prix), on le remet à 0
        if colis.reste_a_payer < 0:
            colis.reste_a_payer = 0
            
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

        # 1. Querysets complets pour les calculs
        lots_qs = Lot.objects.filter(destination__code="ML").order_by(
            "-date_arrivee", "-created_at"
        )
        transferts_qs = TransfertArgent.objects.filter(
            pays_expediteur__code="ML", destinataire="GAOUSSOU"
        ).order_by("-date", "-created_at")

        # 2. Pagination des Lots
        paginator_lots = Paginator(lots_qs, 15)
        page_lots_num = self.request.GET.get("page_lots")
        lots_page = paginator_lots.get_page(page_lots_num)

        # 3. Pagination des Transferts
        paginator_trans = Paginator(transferts_qs, 10)
        page_trans_num = self.request.GET.get("page_trans")
        trans_page = paginator_trans.get_page(page_trans_num)

        # 4. Calculs financiers
        total_douane = lots_qs.aggregate(total=Sum("frais_douane"))["total"] or 0
        total_paye = (
            transferts_qs.filter(statut="RECU").aggregate(total=Sum("montant"))["total"]
            or 0
        )
        total_en_attente = (
            transferts_qs.filter(statut="EN_ATTENTE").aggregate(total=Sum("montant"))[
                "total"
            ]
            or 0
        )

        context.update(
            {
                "lots": lots_page,
                "transferts_gaoussou": trans_page,
                "total_douane": total_douane,
                "total_paye": total_paye,
                "total_en_attente": total_en_attente,
                "reste_a_payer": total_douane - total_paye,
            }
        )
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
            messages.error(self.request, "La tarification spéciale n'est pas disponible pour les lots de type BATEAU.")
            # On pourrait lever une exception ou rediriger, mais ici on va juste informer via le contexte si besoin
        
        kwargs["lot"] = self.lot
        return kwargs

    def form_valid(self, form):
        form.instance.admin_mali = self.request.user
        # Plus besoin de forcer form.instance.lot si on veut que ce soit global, 
        # mais on peut le garder optionnel ou le mettre à None.
        # Ici on va garder le tarif global (sans lot spécifique dans la recherche)
        
        # Gérer l'unicité (Update si existe déjà pour ce client vers cette destination)
        existing = ClientLotTarif.objects.filter(
            client=form.instance.client, 
            destination=self.request.user.country
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

        # Recalculer les prix de TOUS les colis du client vers CETTE destination
        from core.models import Colis
        colis_list = Colis.objects.filter(client=tarif.client, lot__destination=tarif.destination)
        count = colis_list.count()
        for colis in colis_list:
            colis.recalculate_prices()
            colis.save()

        messages.success(
            self.request,
            f"Le tarif GLOBAL de {tarif.prix_kilo} FCFA/kg a été appliqué aux {count} colis de {tarif.client} dans le système.",
        )
        # Redirection vers la même page pour voir la liste mise à jour
        return redirect("mali:admin_client_lot_tarif", lot_pk=self.lot.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self.lot = getattr(self, "lot", get_object_or_404(Lot, pk=self.kwargs.get("lot_pk")))
        context["lot"] = self.lot
        # Liste des tarifs existants pour le pays de l'admin (Clients du Mali)
        context["existing_tarifs"] = ClientLotTarif.objects.filter(
            destination=self.request.user.country,
            client__country=self.request.user.country
        ).select_related("client")
        return context

class MaliClientLotTarifDeleteView(AdminMaliRequiredMixin, View):
    def post(self, request, lot_pk, pk):
        tarif = get_object_or_404(ClientLotTarif, pk=pk, destination=request.user.country)
        client = tarif.client
        
        # Supprimer le tarif
        tarif.delete()
        
        # Recalculer les prix pour ce client dans TOUT le système (reviendra au tarif standard)
        from core.models import Colis
        colis_list = Colis.objects.filter(client=client, lot__destination=request.user.country)
        for colis in colis_list:
            colis.recalculate_prices()
            colis.save()
            
        messages.warning(request, f"La convention tarifaire pour {client} a été supprimée. Les prix de tous ses colis vers {request.user.country} ont été rétablis au tarif standard.")
        return redirect("mali:admin_client_lot_tarif", lot_pk=lot_pk)


class MaliAdminDashboardView(AdminMaliRequiredMixin, TemplateView):
    template_name = "mali/admin/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mali = self.request.user.country
        now = timezone.now()
        
        # Stats globales
        context["total_agents"] = User.objects.filter(country=mali, role="AGENT_MALI").count()
        context["total_colis_mois"] = Colis.objects.filter(lot__destination=mali, created_at__month=now.month).count()
        
        # Lots par statut
        context["lots_en_cours"] = Lot.objects.filter(destination=mali, status=Lot.Status.OUVERT).count()
        context["lots_en_route"] = Lot.objects.filter(destination=mali, status=Lot.Status.FERME).count() # Fermé = en cours d'expédition/transit
        context["lots_recus"] = Lot.objects.filter(destination=mali, status=Lot.Status.ARRIVE).count()
        
        # Finances - Recettes du mois
        colis_livres = Colis.objects.filter(
            lot__destination=mali,
            status="LIVRE",
            updated_at__year=now.year,
            updated_at__month=now.month
        ).exclude(paye_en_chine=True)

        recette_brute = sum(c.prix_final - getattr(c, 'reste_a_payer', 0) - getattr(c, 'montant_jc', 0) for c in colis_livres)
        context["recettes_mois"] = recette_brute

        # Dépenses
        dep = Depense.objects.filter(pays=mali, date__year=now.year, date__month=now.month)
        total_depenses = dep.aggregate(t=Sum("montant"))["t"] or 0
        context["depenses_mois"] = total_depenses

        # Transferts
        transf = TransfertArgent.objects.filter(pays_expediteur=mali, date__year=now.year, date__month=now.month)
        total_transferts = transf.aggregate(t=Sum("montant"))["t"] or 0
        context["transferts_mois"] = total_transferts

        # RH / Salaires & Avances
        av = AvanceSalaire.objects.filter(agent__country=mali, date__year=now.year, date__month=now.month)
        total_avances = av.aggregate(t=Sum("montant"))["t"] or 0
        
        salaires = PaiementAgent.objects.filter(agent__country=mali, date_paiement__year=now.year, date_paiement__month=now.month)
        total_salaires = salaires.aggregate(t=Sum("montant"))["t"] or 0
        
        context["rh_mois"] = total_avances + total_salaires

        # Caisse nette de l'agence
        context["caisse_nette"] = recette_brute - total_depenses - total_transferts - context["rh_mois"]
        
        # Dernières livraisons
        context["recent_deliveries"] = Colis.objects.filter(
            lot__destination=mali, status="LIVRE"
        ).annotate(
            sort_date=Coalesce("date_livraison", "updated_at", output_field=DateField())
        ).order_by("-sort_date", "-updated_at")[:10]

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
            (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"),
            (5, "Mai"), (6, "Juin"), (7, "Juillet"), (8, "Août"),
            (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
        ]

        # Stats du Mali pour la liste des agents
        stats_ml = get_country_stats("ML", selected_year, selected_month)
        context["agents_data"] = stats_ml.get("agents_remuneration", [])

        # Liste des paiements
        context["paiements"] = PaiementAgent.objects.filter(
            agent__country=self.request.user.country,
            agent__role="AGENT_MALI",
            periode_annee=selected_year,
            periode_mois=selected_month,
        ).order_by("-date_paiement")

        # Liste des avances
        context["avances"] = AvanceSalaire.objects.filter(
            agent__country=self.request.user.country,
            agent__role="AGENT_MALI",
            date__year=selected_year,
            date__month=selected_month,
        ).order_by("-date")

        return context

class MaliAgentAvanceCreateView(AdminMaliRequiredMixin, CreateView):
    model = AvanceSalaire
    form_class = AvanceSalaireForm
    template_name = "mali/admin/avance_form.html"
    success_url = reverse_lazy("mali:admin_remunerations")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['country'] = self.request.user.country
        return kwargs

    def form_valid(self, form):
        avance = form.save(commit=False)
        avance.save()
        messages.success(self.request, f"Avance de {avance.montant} ajoutée pour l'agent {avance.agent.username}.")
        return super().form_valid(form)

class MaliAgentAvanceUpdateView(AdminMaliRequiredMixin, UpdateView):
    model = AvanceSalaire
    form_class = AvanceSalaireForm
    template_name = "mali/admin/avance_form.html"
    success_url = reverse_lazy("mali:admin_remunerations")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['country'] = self.request.user.country
        return kwargs

    def form_valid(self, form):
        avance = form.save(commit=False)
        avance.save()
        messages.success(self.request, f"Avance de {avance.montant} mise à jour pour l'agent {avance.agent.username}.")
        return super().form_valid(form)

class MaliAgentAvanceDeleteView(AdminMaliRequiredMixin, View):
    def post(self, request, pk):
        avance = get_object_or_404(AvanceSalaire, pk=pk, agent__country=request.user.country)
        avance.delete()
        messages.success(request, "L'avance a été supprimée avec succès.")
        return redirect("mali:admin_remunerations")

class MaliCorrectionLotListView(AdminMaliRequiredMixin, ListView):
    model = Lot
    template_name = "mali/admin/correction_lot_list.html"
    context_object_name = "lots_list"
    paginate_by = 20

    def get_queryset(self):
        mali = self.request.user.country
        qs = Lot.objects.filter(destination=mali).order_by("-date_arrivee", "-created_at")
        search = self.request.GET.get("q")
        if search:
            qs = qs.filter(numero__icontains=search)
        tab = self.request.GET.get("tab", "arrive")
        if tab == "transit":
            qs = qs.filter(colis__status="EXPEDIE").distinct()
        elif tab == "livre":
            qs = qs.filter(colis__status__in=["LIVRE", "PERDU"]).distinct()
        else:  # arrive (default)
            qs = qs.filter(colis__status="ARRIVE").distinct()
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        context["active_tab"] = self.request.GET.get("tab", "arrive")
        mali = self.request.user.country
        # Comptes par statut pour les badges de nav
        qs_base = Lot.objects.filter(destination=mali)
        search = self.request.GET.get("q")
        if search:
            qs_base = qs_base.filter(numero__icontains=search)
        context["count_transit"] = qs_base.filter(colis__status="EXPEDIE").distinct().count()
        context["count_arrive"] = qs_base.filter(colis__status="ARRIVE").distinct().count()
        context["count_livre"] = qs_base.filter(colis__status__in=["LIVRE", "PERDU"]).distinct().count()
        return context

class MaliCorrectionLotDetailView(AdminMaliRequiredMixin, DetailView):
    model = Lot
    template_name = "mali/admin/correction_lot_detail.html"
    context_object_name = "lot"

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
        context["lot_has_arrived_colis"] = self.object.colis.filter(status="ARRIVE").exists()
        return context

class MaliActionRevertView(AdminMaliRequiredMixin, View):
    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk, lot__destination=request.user.country)
        action = request.POST.get("action")

        if action == "revert_to_transit" and colis.status == "ARRIVE":
            # Repasser en EXPEDIE (transit)
            colis.status = "EXPEDIE"
            colis.date_livraison = None
            colis.date_encaissement = None
            colis.est_paye = False
            colis.reste_a_payer = 0
            colis.montant_jc = 0
            colis.sortie_sous_garantie = False
            colis.sortie_autorisee_par = ""
            colis.save()
            messages.success(
                request, f"Le carton {colis.reference} est repassé en TRANSIT."
            )

        elif action == "revert_to_arrive" and colis.status == "LIVRE":
            # Annuler la livraison et l'encaissement et repasser en ARRIVE
            colis.status = "ARRIVE"
            colis.date_livraison = None
            colis.date_encaissement = None
            colis.est_paye = False
            colis.reste_a_payer = 0
            colis.montant_jc = 0
            colis.sortie_sous_garantie = False
            colis.sortie_autorisee_par = ""
            colis.save()
            messages.warning(request, f"Le carton {colis.reference} est repassé en ARRIVÉ. Les données de livraison et de paiement ont été effacées.")

        # Revert complet d'un colis perdu
        elif action == "revert_perdu" and colis.status == "PERDU":
            colis.status = "ARRIVE" # Par défaut on repasse à arrivé
            colis.save()
            messages.success(request, f"Le carton {colis.reference} n'est plus marqué comme PERDU. Il est maintenant ARRIVÉ.")

        # Revert encaissement partiel ou modification paiement tout en restant en attente etc n'est pas nécessaire si on reverse à Arrivé, ça annule tout.
            
        return redirect("mali:admin_correction_lot_detail", pk=colis.lot.pk)
class MaliColisAddToArrivalView(AdminMaliRequiredMixin, View):
    """Permet à l'Admin Mali d'ajouter un colis manquant dans un lot arrivé.
    Ces colis seront marqués 'ajoute_par_mali=True' et auront un badge spécial."""

    def get(self, request, lot_pk):
        from .forms import MaliAddColisForm
        lot = get_object_or_404(Lot, pk=lot_pk, destination=request.user.country)
        form = MaliAddColisForm(country=request.user.country)
        return render(request, "mali/admin/add_colis_to_lot.html", {"lot": lot, "form": form})

    def post(self, request, lot_pk):
        from .forms import MaliAddColisForm
        lot = get_object_or_404(Lot, pk=lot_pk, destination=request.user.country)
        form = MaliAddColisForm(request.POST, country=request.user.country)

        if form.is_valid():
            data = form.cleaned_data
            colis = Colis(
                lot=lot,
                client=data["client"],
                type_colis=data["type_colis"],
                poids=data.get("poids") or 0,
                cbm=data.get("cbm") or 0,
                nombre_pieces=data.get("nombre_pieces") or 1,
                prix_final=data["prix_final"],
                prix_transport=data["prix_final"],  # On garde le prix saisi
                description=data.get("description", ""),
                status=Colis.Status.ARRIVE,
                ajoute_par_mali=True,
            )
            colis.save()

            # Essaie d'envoyer la notification WhatsApp si configurée
            try:
                from notification.tasks import send_whatsapp_notification
                send_whatsapp_notification.delay(
                    colis_pk=colis.pk,
                    event_type="ARRIVE",
                    phone=colis.client.telephone,
                )
            except Exception:
                pass  # Notification non bloquante

            messages.success(
                request,
                f"✅ Colis {colis.reference} ajouté avec succès dans le lot {lot.numero}. [Ajouté Mali]"
            )
            return redirect("mali:admin_correction_lot_detail", pk=lot.pk)

        return render(request, "mali/admin/add_colis_to_lot.html", {"lot": lot, "form": form})


