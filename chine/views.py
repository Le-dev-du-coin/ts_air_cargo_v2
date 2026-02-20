import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Q, Sum
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import (
    TemplateView,
    ListView,
    CreateView,
    DetailView,
    UpdateView,
    View,
)
import os
import uuid
import base64
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.contrib import messages

logger = logging.getLogger(__name__)
from django.views.generic import edit as delete

from core.models import Client, Lot, Colis, BackgroundTask, Country
from report.models import Depense, TransfertArgent
from .forms import ClientForm, LotForm, ColisForm, CountryForm, AgentForm, LotNoteForm
from .tasks import process_colis_creation

from django.contrib.auth import get_user_model

User = get_user_model()


class RoleRequiredMixin(UserPassesTestMixin):
    allowed_roles = []

    def test_func(self):
        if not self.request.user.is_authenticated:
            return False
        return self.request.user.is_superuser or (
            hasattr(self.request.user, "role")
            and self.request.user.role in self.allowed_roles
        )

    def handle_no_permission(self):
        from django.contrib import messages

        messages.error(
            self.request,
            "Accès non autorisé : vous n'avez pas les droits nécessaires pour accéder à cette page.",
        )
        return redirect("index")


class AgentChineRequiredMixin(RoleRequiredMixin):
    allowed_roles = [
        "AGENT_CHINE",
        "ADMIN_CHINE",
    ]  # Admins can generally see agent stuff


class StrictAgentChineRequiredMixin(RoleRequiredMixin):
    allowed_roles = ["AGENT_CHINE"]


class StrictAgentChineRequiredMixin(RoleRequiredMixin):
    allowed_roles = ["AGENT_CHINE"]


class AdminChineRequiredMixin(RoleRequiredMixin):
    allowed_roles = ["ADMIN_CHINE"]


def get_country_stats(country_code, year=None, month=None):
    """Fonction utilitaire pour calculer les stats par pays, avec filtre optionnel par date"""
    lots = Lot.objects.filter(destination__code=country_code)
    colis = Colis.objects.filter(lot__destination__code=country_code)
    depenses = Depense.objects.filter(pays__code=country_code)
    transferts = TransfertArgent.objects.filter(pays_expediteur__code=country_code)

    if year and month:
        # Filtrer par date de création pour lots/colis/dépenses
        lots = lots.filter(created_at__year=year, created_at__month=month)
        colis = colis.filter(created_at__year=year, created_at__month=month)
        depenses = depenses.filter(date__year=year, date__month=month)
        transferts = transferts.filter(date__year=year, date__month=month)

    # Calcul des montants avec déduction des jetons cédés (JC)
    from django.db.models import F

    montant_brut = colis.aggregate(total=Sum("prix_final"))["total"] or 0
    total_jc = colis.aggregate(total=Sum("montant_jc"))["total"] or 0
    montant_net_colis = montant_brut - total_jc

    stats = {}
    stats["montant_colis"] = montant_net_colis
    stats["poids_total"] = colis.aggregate(total=Sum("poids"))["total"] or 0
    stats["cout_transport"] = lots.aggregate(total=Sum("frais_transport"))["total"] or 0
    stats["cout_douane"] = lots.aggregate(total=Sum("frais_douane"))["total"] or 0
    stats["autres_depenses"] = depenses.aggregate(total=Sum("montant"))["total"] or 0
    stats["total_transferts"] = transferts.aggregate(total=Sum("montant"))["total"] or 0

    # Pour le dashboard, on combine Transferts et Autres Dépenses dans "Dépenses"
    # ou on les soustrait simplement du bénéfice.
    # L'utilisateur a dit "ajouter transfert dans les dépénse".
    # Je vais mettre à jour "autres_depenses" pour inclure les transferts pour l'affichage simple
    # Ou garder séparé et sommer pour le bénéfice.

    stats["total_depenses_global"] = (
        stats["autres_depenses"] + stats["total_transferts"]
    )

    stats["benefice"] = (
        stats["montant_colis"]
        - stats["cout_transport"]
        - stats["cout_douane"]
        - stats["total_depenses_global"]
    )
    stats["nb_lots"] = lots.count()
    stats["nb_colis"] = colis.count()

    # Calcul de la rémunération des agents
    agents = User.objects.filter(country__code=country_code).exclude(role="CLIENT")
    agents_remuneration = []
    total_commissions = 0

    for agent in agents:
        montant = 0
        if agent.remuneration_mode == User.RemunerationMode.SALAIRE:
            montant = agent.remuneration_value
        elif agent.remuneration_mode == User.RemunerationMode.COMMISSION:
            # Commission sur le bénéfice positif uniquement
            base_calcul = max(0, stats["benefice"])
            montant = (base_calcul * agent.remuneration_value) / 100
            total_commissions += montant

        agents_remuneration.append(
            {
                "agent": agent,
                "montant": montant,
                "mode": agent.get_remuneration_mode_display(),
                "valeur": agent.remuneration_value,
            }
        )

    stats["agents_remuneration"] = agents_remuneration
    stats["total_commissions"] = total_commissions

    return stats


class DashboardView(LoginRequiredMixin, AgentChineRequiredMixin, TemplateView):
    template_name = "chine/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Stats communes (Non filtrées par défaut ?) - User said "ne touche pas aux total globaux"
        # The existing code did:
        context["lots_ouverts_count"] = Lot.objects.filter(
            status=Lot.Status.OUVERT
        ).count()
        context["lots_fermes_count"] = Lot.objects.filter(
            status=Lot.Status.FERME
        ).count()
        context["colis_total_count"] = Colis.objects.count()
        context["total_clients_count"] = Client.objects.count()

        # Stats spécifiques Agent Chine (Reste inchangé ?)
        if self.request.user.role == "AGENT_CHINE":
            context["lots_transit_count"] = Lot.objects.filter(
                status="EN_TRANSIT"
            ).count()
            context["lots_arrives_mali_count"] = Lot.objects.filter(
                status__in=[Lot.Status.ARRIVE, Lot.Status.DOUANE, Lot.Status.DISPONIBLE]
            ).count()

            # Stats financières Agent Chine - User didn't specify, assume all time or unchanged.
            context["montant_total_colis_agent"] = (
                Colis.objects.aggregate(total=Sum("prix_final"))["total"] or 0
            )

            context["montant_total_transport_agent"] = (
                Lot.objects.aggregate(total=Sum("frais_transport"))["total"] or 0
            )

        # Stats avancées pour l'Admin Chine
        if self.request.user.role == "ADMIN_CHINE":
            # Récupération des stats séparées (MOIS EN COURS)
            now = timezone.now()
            context["stats_ml"] = get_country_stats("ML", now.year, now.month)
            context["stats_ci"] = get_country_stats("CI", now.year, now.month)

            # Récupération des stats GLOBALES (ALL TIME) pour les totaux
            stats_ml_global = get_country_stats("ML")
            stats_ci_global = get_country_stats("CI")

            # Totaux globaux (somme des deux globaux)
            context["montant_total_colis"] = (
                stats_ml_global["montant_colis"] + stats_ci_global["montant_colis"]
            )
            context["total_poids_kg"] = (
                stats_ml_global["poids_total"] + stats_ci_global["poids_total"]
            )
            context["montant_total_transport"] = (
                stats_ml_global["cout_transport"] + stats_ci_global["cout_transport"]
            )
            context["montant_total_douane"] = (
                stats_ml_global["cout_douane"] + stats_ci_global["cout_douane"]
            )
            context["benefice_global"] = (
                stats_ml_global["benefice"] + stats_ci_global["benefice"]
            )

            context["total_lots"] = Lot.objects.count()
            context["total_colis"] = Colis.objects.count()
            context["total_agents_count"] = (
                User.objects.exclude(role="CLIENT").exclude(is_superuser=True).count()
            )

            # Données Graphique (Derniers 6 mois)
            now = timezone.now()
            start_of_month = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            chart_data = []
            for i in range(5, -1, -1):
                month_start = (start_of_month - timedelta(days=i * 30)).replace(day=1)
                month_end = (month_start + timedelta(days=32)).replace(day=1)
                count = Colis.objects.filter(
                    created_at__gte=month_start, created_at__lt=month_end
                ).count()
                chart_data.append({"month": month_start.strftime("%b"), "count": count})
            context["chart_data"] = chart_data

        # Pagination pour les lots récents
        lots_list = (
            Lot.objects.prefetch_related("colis")
            .annotate(total_recettes=Sum("colis__prix_final"))
            .order_by("-created_at")
        )
        from django.core.paginator import Paginator

        paginator = Paginator(lots_list, 10)  # 10 lots par page
        page_number = self.request.GET.get("page", 1)
        context["recent_lots"] = paginator.get_page(page_number)

        return context


class MonthlyArchivesView(LoginRequiredMixin, AdminChineRequiredMixin, TemplateView):
    template_name = "chine/archives.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Récupération des paramètres ou par défaut mois en cours
        now = timezone.now()
        try:
            selected_year = int(self.request.GET.get("year", now.year))
            selected_month = int(self.request.GET.get("month", now.month))
        except ValueError:
            selected_year = now.year
            selected_month = now.month

        # Validation basique
        if not (2000 <= selected_year <= 2100):
            selected_year = now.year
        if not (1 <= selected_month <= 12):
            selected_month = now.month

        context["selected_year"] = selected_year
        context["selected_month"] = selected_month

        # Stats pour la période sélectionnée
        context["stats_ml"] = get_country_stats("ML", selected_year, selected_month)
        context["stats_ci"] = get_country_stats("CI", selected_year, selected_month)

        # Listes pour les sélecteurs
        context["years"] = range(2023, now.year + 2)
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

        return context


class CountryCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = Country
    form_class = CountryForm
    template_name = "chine/countries/form.html"
    success_url = reverse_lazy("chine:dashboard")  # Ou liste des pays si elle existe

    def test_func(self):
        return self.request.user.role == "ADMIN_CHINE"

    def form_valid(self, form):
        # Logique supplémentaire si besoin
        return super().form_valid(form)


class ClientListView(LoginRequiredMixin, ListView):
    model = Client
    template_name = "chine/clients/list.html"
    context_object_name = "clients"
    paginate_by = 20
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter by Country (Tabs)
        country_code = self.request.GET.get("country")
        if country_code:
            queryset = queryset.filter(country__code=country_code)

        # Search
        search_query = self.request.GET.get("search")
        if search_query:
            queryset = queryset.filter(
                Q(nom__icontains=search_query)
                | Q(prenom__icontains=search_query)
                | Q(telephone__icontains=search_query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["countries"] = Country.objects.exclude(code="CN")
        context["selected_country"] = self.request.GET.get("country", "")
        context["search_query"] = self.request.GET.get("search", "")
        return context


import csv
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from .forms import ClientImportForm


class ClientExportView(LoginRequiredMixin, ListView):
    model = Client

    def get(self, request, *args, **kwargs):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="clients_export.csv"'

        writer = csv.writer(response)
        writer.writerow(["Nom", "Prénom", "Téléphone", "Pays (Code)", "Adresse"])

        clients = Client.objects.all()
        for client in clients:
            writer.writerow(
                [
                    client.nom,
                    client.prenom,
                    client.telephone,
                    client.country.code if client.country else "",
                    client.adresse,
                ]
            )

        return response


class ClientImportView(LoginRequiredMixin, TemplateView):
    template_name = "chine/clients/import.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = ClientImportForm()
        return context

    def post(self, request, *args, **kwargs):
        form = ClientImportForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES["csv_file"]
            if not csv_file.name.endswith(".csv"):
                messages.error(request, "Ce n'est pas un fichier CSV")
                return redirect("chine:client_import")

            # Read CSV content
            try:
                # Use utf-8-sig to handle BOM if present (common in Excel)
                decoded_file = csv_file.read().decode("utf-8-sig")

                # Detect delimiter (comma or semicolon)
                try:
                    dialect = csv.Sniffer().sniff(decoded_file[:1024])
                except csv.Error:
                    # Fallback to comma if sniffing fails
                    dialect = csv.excel

                # Reset file pointer or just use the string
                # Since we read it into memory (decoded_file), we can split lines
                lines = decoded_file.splitlines()

                # Use DictReader with detected dialect
                reader = csv.DictReader(lines, dialect=dialect)

                # Helper to find key case-insensitive and strip whitespace
                # We normalize headers map first to avoid repeated looping
                # reader.fieldnames might be None if file is empty
                if not reader.fieldnames:
                    messages.error(request, "Fichier CSV vide ou illisible.")
                    return redirect("chine:client_import")

                # Normalize headers: {'nom client': 'Nom', 'tel': 'Telephone', ...}
                # But here we just look up in row using the helper

                def get_value(row, *keys):
                    # Clean keys in row (strip embedded whitespace/quotes if any issue)
                    # But DictReader uses fieldnames.
                    # We iterate over row items.
                    for k in keys:
                        for row_k, row_v in row.items():
                            if row_k and k.lower() in row_k.lower().strip():
                                return row_v.strip() if row_v else ""
                    return ""

                created_count = 0
                updated_count = 0

                with transaction.atomic():
                    for row in reader:
                        # Flexible key search
                        nom = get_value(row, "nom", "name")
                        prenom = get_value(row, "prenom", "prénom", "firstname")
                        telephone = get_value(
                            row, "telephone", "téléphone", "tel", "phone", "mobile"
                        )
                        country_code = get_value(row, "pays", "country", "code")
                        adresse = get_value(row, "adresse", "address", "lieu")

                        # Basic validation: Nom and Phone are required
                        if not nom or not telephone:
                            continue

                        # Resolve Country
                        country = None
                        if country_code:
                            # Try matching by code or name
                            country = Country.objects.filter(
                                Q(code__iexact=country_code)
                                | Q(name__icontains=country_code)
                            ).first()

                        # Use logged-in user's country if not specified
                        if not country:
                            if (
                                hasattr(self.request, "tenant_country")
                                and self.request.tenant_country
                            ):
                                country = self.request.tenant_country
                            elif self.request.user.country:
                                country = self.request.user.country

                        # Check existance by Telephone
                        client, created = Client.objects.update_or_create(
                            telephone=telephone,
                            defaults={
                                "nom": nom,
                                "prenom": prenom,
                                "country": country,  # Can be None if allowed
                                "adresse": adresse,
                            },
                        )

                        if created:
                            created_count += 1
                        else:
                            updated_count += 1

                messages.success(
                    request,
                    f"Import intelligent terminé : {created_count} créés, {updated_count} mis à jour.",
                )
                return redirect("chine:client_list")

            except Exception as e:
                messages.error(request, f"Erreur lors de l'import : {str(e)}")
                return redirect("chine:client_import")

        return render(request, self.template_name, {"form": form})


class ClientCreateView(LoginRequiredMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = "chine/clients/form.html"
    success_url = reverse_lazy("chine:client_list")

    def form_valid(self, form):
        # On respecte le pays choisi dans le formulaire.
        # Si le formulaire n'a pas de champ pays (ex: agent local), on utilise le tenant.
        if "country" not in form.cleaned_data or not form.cleaned_data["country"]:
            if hasattr(self.request, "tenant_country") and self.request.tenant_country:
                form.instance.country = self.request.tenant_country
            elif self.request.user.country:
                form.instance.country = self.request.user.country

        response = super().form_valid(form)

        # Notification Nouveau Client
        try:
            from notification.tasks import send_notification_async

            client = self.object
            if client.telephone and client.user:
                # Récupérer le mot de passe saisi dans le formulaire
                raw_password = form.cleaned_data.get("password", "")
                nom_complet = (
                    f"{client.prenom} {client.nom}".strip() or client.user.username
                )
                date_creation = timezone.now().strftime("%d/%m/%Y à %H:%M")

                message = (
                    f"👋 Bonjour *{nom_complet}*,\n\n"
                    f"Bienvenue chez *TS AIR CARGO* !\n"
                    f"Votre espace client a été créé le {date_creation}.\n\n"
                    f"🔐 *Vos identifiants de connexion :*\n"
                    f"   • Identifiant : *{client.user.username}*\n"
                    f"   • Mot de passe : *{raw_password}*\n\n"
                    f"⚠️ *Important :* Veuillez modifier votre mot de passe dès votre première connexion pour sécuriser votre compte.\n\n"
                    f"🌐 Connectez-vous ici :\n"
                    f"https://ts-aircargo.com/login\n\n"
                    f"Merci de votre confiance !\n"
                    f"——\n"
                    f"*Équipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
                )
                send_notification_async.delay(
                    user_id=client.user.id,
                    message=message,
                    categorie="compte_cree",
                    titre="Bienvenue — Vos identifiants TS AIR CARGO",
                    region="chine",
                )
        except Exception as e:
            logger.error(f"Erreur trigger notification client {self.object.id}: {e}")

        return response


class ClientUpdateView(LoginRequiredMixin, UpdateView):
    model = Client
    form_class = ClientForm
    template_name = "chine/clients/form.html"
    success_url = reverse_lazy("chine:client_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Modifier Client"
        return context


class ClientDeleteView(LoginRequiredMixin, UserPassesTestMixin, delete.DeleteView):
    # django generic DeleteView
    model = Client
    success_url = reverse_lazy("chine:client_list")
    template_name = "chine/clients/confirm_delete.html"

    def test_func(self):
        # Restriction: Seul l'Admin Chine peut supprimer
        return self.request.user.role == "ADMIN_CHINE"

    def handle_no_permission(self):
        messages.error(
            self.request,
            "Action non autorisée. Seul l'Admin Chine peut supprimer des clients.",
        )
        return redirect("chine:client_list")


class ClientBulkDeleteView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.role == "ADMIN_CHINE"

    def handle_no_permission(self):
        messages.error(self.request, "Action non autorisée.")
        return redirect("chine:client_list")

    def post(self, request, *args, **kwargs):
        client_ids = request.POST.getlist("client_ids")
        if not client_ids:
            messages.warning(request, "Aucun client sélectionné.")
            return redirect("chine:client_list")

        # Security: Filter by tenant if needed, currently we assume admin trust
        # or implement checks. For now, delete found ids.
        deleted_count, _ = Client.objects.filter(id__in=client_ids).delete()
        messages.success(request, f"{deleted_count} clients supprimés.")
        return redirect("chine:client_list")


class LotListView(LoginRequiredMixin, ListView):
    model = Lot
    template_name = "chine/lots/list.html"
    context_object_name = "lots"
    paginate_by = 10
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter by Destination Country (Tabs)
        country_code = self.request.GET.get("country")
        if country_code:
            queryset = queryset.filter(destination__code=country_code)

        # Search
        search_query = self.request.GET.get("search")
        if search_query:
            queryset = queryset.filter(Q(numero_lot__icontains=search_query))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["countries"] = Country.objects.exclude(code="CN")
        context["selected_country"] = self.request.GET.get("country", "")
        context["search_query"] = self.request.GET.get("search", "")
        return context


class LotCreateView(LoginRequiredMixin, StrictAgentChineRequiredMixin, CreateView):
    model = Lot
    form_class = LotForm
    template_name = "chine/lots/form.html"
    success_url = reverse_lazy("chine:lot_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        if hasattr(self.request, "tenant_country") and self.request.tenant_country:
            form.instance.country = self.request.tenant_country
        elif self.request.user.country:
            form.instance.country = self.request.user.country
        return super().form_valid(form)


class LotUpdateView(LoginRequiredMixin, StrictAgentChineRequiredMixin, UpdateView):
    model = Lot
    form_class = LotForm
    template_name = "chine/lots/form.html"
    success_url = reverse_lazy("chine:lot_list")

    def get_success_url(self):
        return reverse_lazy("chine:lot_detail", kwargs={"pk": self.object.pk})

    def dispatch(self, request, *args, **kwargs):
        lot = self.get_object()
        # READ-ONLY STRICT si expédié
        if lot.status == "EXPEDIE":
            messages.error(
                request, "Impossible de modifier un lot expédié (Lecture Seule)."
            )
            return redirect("chine:lot_detail", pk=lot.pk)
        return super().dispatch(request, *args, **kwargs)


class LotNoteUpdateView(LoginRequiredMixin, StrictAgentChineRequiredMixin, UpdateView):
    model = Lot
    form_class = LotNoteForm
    template_name = "chine/lots/form_note.html"

    def get_success_url(self):
        messages.success(self.request, "Note mise à jour.")
        return reverse_lazy("chine:lot_detail", kwargs={"pk": self.object.pk})


class LotDeleteView(LoginRequiredMixin, AdminChineRequiredMixin, View):
    def post(self, request, pk):
        logger.info(f"LotDeleteView hit for PK: {pk} by user: {request.user}")
        lot = get_object_or_404(Lot, pk=pk)
        numero = lot.numero
        lot.delete()
        logger.info(f"Lot {numero} deleted successfully.")
        messages.success(request, f"Lot {numero} supprimé avec succès.")
        return redirect("chine:lot_list")


class LotCloseView(LoginRequiredMixin, StrictAgentChineRequiredMixin, View):
    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)
        if lot.status == "OUVERT":
            lot.status = "FERME"
            lot.save()
            messages.success(request, f"Lot {lot.numero} fermé. Prêt pour expédition.")

            # Notification clients du lot : leurs colis sont en cours de conditionnement
            try:
                from notification.tasks import send_notification_async

                # Grouper par client (1 seul message par client)
                by_client = {}
                for colis in lot.colis.all():
                    if not colis.client or not colis.client.user:
                        continue
                    cid = colis.client.id
                    if cid not in by_client:
                        by_client[cid] = {"user": colis.client.user, "colis": []}
                    by_client[cid]["colis"].append(colis)

                for cid, data in by_client.items():
                    user = data["user"]
                    colis_list = data["colis"]
                    nb = len(colis_list)
                    nom_complet = user.get_full_name() or user.username
                    lines = "\n".join(f"   \u2022 {c.reference}" for c in colis_list)
                    msg = (
                        f"Bonjour *{nom_complet}*,\n\n"
                        f"📦 *Lot ferm\u00e9 \u2014 Pr\u00eat \u00e0 exp\u00e9dier !*\n\n"
                        f"Nous venons de fermer le lot *{lot.numero}* contenant "
                        f"{'votre colis' if nb == 1 else f'vos {nb} colis'} :\n"
                        f"{lines}\n\n"
                        f"⏳ L'exp\u00e9dition est pr\u00e9vue prochainement depuis la Chine.\n"
                        f"🔔 Vous recevrez une notification d\u00e8s le d\u00e9part.\n\n"
                        f"🌐 Suivez vos colis : https://ts-aircargo.com/login\n"
                        f"\u2014\u2014\n"
                        f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
                    )
                    send_notification_async.delay(
                        user_id=user.id,
                        message=msg,
                        categorie="lot_ferme",
                        titre=f"Lot {lot.numero} ferm\u00e9 \u2014 Exp\u00e9dition \u00e0 venir",
                        region="chine",
                    )

            except Exception as e:
                logger.error(f"Erreur trigger notification fermeture lot {lot.id}: {e}")
        return redirect("chine:lot_detail", pk=pk)


class LotReopenView(LoginRequiredMixin, StrictAgentChineRequiredMixin, View):
    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)
        if lot.status == "FERME":
            lot.status = "OUVERT"
            lot.save()
            messages.success(
                request, f"Lot {lot.numero} réouvert. Vous pouvez le modifier."
            )
        return redirect("chine:lot_detail", pk=pk)


class LotStatusUpdateView(LoginRequiredMixin, StrictAgentChineRequiredMixin, View):
    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)
        if lot.status == "FERME":
            # Validation : Frais de transport obligatoire
            if not lot.frais_transport or lot.frais_transport <= 0:
                messages.error(
                    request,
                    "Impossible d'expédier : Veuillez renseigner les frais de transport (via 'Modifier' ou 'Réouvrir').",
                )
                return redirect("chine:lot_detail", pk=pk)

            lot.status = "EN_TRANSIT"
            lot.date_expedition = timezone.now()
            lot.save()
            # Also update colis status? Generally yes.
            lot.colis.update(status="EXPEDIE")
            messages.success(
                request, f"Lot {lot.numero} EXPÉDIÉ ! (Mode Lecture Seule activé)"
            )

            # Notification Clients — Groupée par client (1 seul message par client)
            try:
                from notification.tasks import send_notification_async

                by_client = {}
                for colis in lot.colis.all():
                    if not colis.client or not colis.client.user:
                        continue
                    cid = colis.client.id
                    if cid not in by_client:
                        by_client[cid] = {"user": colis.client.user, "colis": []}
                    by_client[cid]["colis"].append(colis)

                for cid, data in by_client.items():
                    user = data["user"]
                    colis_list = data["colis"]
                    nb = len(colis_list)
                    nom_complet = user.get_full_name() or user.username
                    lines = "\n".join(f"   \u2022 {c.reference}" for c in colis_list)
                    date_exp = (
                        lot.date_expedition.strftime("%d/%m/%Y \u00e0 %H:%M")
                        if lot.date_expedition
                        else "date non renseign\u00e9e"
                    )
                    msg = (
                        f"Bonjour *{nom_complet}*,\n\n"
                        f"✈️ *{'Colis exp\u00e9di\u00e9' if nb == 1 else f'{nb} colis exp\u00e9di\u00e9s'} \u2014 En transit !*\n\n"
                        f"Votre {'colis est' if nb == 1 else 'commande est'} en route vers le Mali 🇲🇱 :\n"
                        f"{lines}\n\n"
                        f"📋 Lot : *{lot.numero}*\n"
                        f"📅 Date d'exp\u00e9dition : *{date_exp}*\n"
                        f"📡 Transport : *{lot.get_type_transport_display()}*\n\n"
                        f"🔔 Vous recevrez une notification d\u00e8s l'arriv\u00e9e au Mali.\n\n"
                        f"🌐 Suivez vos colis : https://ts-aircargo.com/login\n"
                        f"\u2014\u2014\n"
                        f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
                    )
                    send_notification_async.delay(
                        user_id=user.id,
                        message=msg,
                        categorie="lot_expedie",
                        titre=f"Exp\u00e9dition Lot {lot.numero} \u2014 {nb} colis en route",
                        region="chine",
                    )

            except Exception as e:
                logger.error(
                    f"Erreur trigger notification exp\u00e9dition lot {lot.id}: {e}"
                )
        return redirect("chine:lot_detail", pk=pk)


class LotDetailView(LoginRequiredMixin, AgentChineRequiredMixin, DetailView):
    model = Lot
    template_name = "chine/lots/detail.html"
    context_object_name = "lot"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Aggregations
        from django.db.models import Sum

        aggregates = self.object.colis.aggregate(
            total_poids=Sum("poids"),
            total_cbm=Sum("cbm"),
            total_montant=Sum(
                "prix_final"
            ),  # Utiliser prix_final pour les recettes réelles
        )

        context["total_poids"] = aggregates["total_poids"] or 0
        context["total_cbm"] = aggregates["total_cbm"] or 0
        context["total_montant_colis"] = aggregates["total_montant"] or 0

        # Calcul Bénéfice = (Total Colis) - (Transport Lot + Douane Lot)
        frais_transport = self.object.frais_transport or 0
        frais_douane = self.object.frais_douane or 0
        context["benefice"] = context["total_montant_colis"] - (
            frais_transport + frais_douane
        )

        # Tarif Data for Frontend Calculation
        # Fetch ALL tarifs for this destination to handle different transport types and Telephone/Elec logic
        from core.models import Tarif

        tarifs = Tarif.objects.filter(destination=self.object.destination)

        tarif_data = {}
        for t in tarifs:
            tarif_data[t.type_transport] = {
                "prix_kilo": float(t.prix_kilo),
                "prix_cbm": float(t.prix_cbm),
                "prix_piece": float(t.prix_piece),
            }

        context["tarif_json"] = tarif_data

        # Warn if no tarifs at all for this destination
        if not tarif_data and self.object.status == "OUVERT":
            messages.warning(
                self.request,
                f"Attention: Aucun tarif configuré vers {self.object.destination}. Le calcul automatique sera désactivé.",
            )

        context["colis_form"] = ColisForm()

        # Pagination for colis_list
        from django.core.paginator import Paginator

        colis_queryset = self.object.colis.all().order_by("-created_at")
        paginator = Paginator(colis_queryset, 10)  # 10 colis per page
        page_number = self.request.GET.get("page")
        context["colis_list"] = paginator.get_page(page_number)

        return context


class ColisCreateView(LoginRequiredMixin, StrictAgentChineRequiredMixin, CreateView):
    model = Colis
    form_class = ColisForm
    template_name = "chine/lots/detail.html"

    def get_success_url(self):
        return reverse_lazy("chine:task_list")

    def form_valid(self, form):
        lot = get_object_or_404(Lot, pk=self.kwargs["lot_id"])

        colis = form.save(commit=False)
        colis.lot = lot
        colis.country = lot.country

        # Handle Base64 photo (Webcam/Compressed)
        compressed_photo_data = self.request.POST.get("compressed_photo")
        if compressed_photo_data and compressed_photo_data.startswith("data:image"):
            try:
                import base64
                from django.core.files.base import ContentFile

                format, imgstr = compressed_photo_data.split(";base64,")
                ext = format.split("/")[-1]
                photo_content = ContentFile(
                    base64.b64decode(imgstr),
                    name=f"colis_{lot.pk}_{colis.client.pk if colis.client else 'anon'}.{ext}",
                )
                colis.photo.save(photo_content.name, photo_content, save=False)
            except Exception as e:
                logger.error(f"Error saving base64 photo: {e}")
                messages.warning(
                    self.request,
                    "Erreur lors de l'enregistrement de la photo (Webcam).",
                )

        colis.save()

        # Notification Client V2 (Async)
        try:
            from notification.tasks import send_notification_async

            if colis.client and colis.client.user:
                # Construire le message
                message = (
                    f"📦 *Colis Reçu en Chine*\n"
                    f"Ref: *{colis.reference}*\n"
                    f"Poids: {colis.poids} kg\n"
                    f"Statut: Reçu à l'entrepôt\n"
                    f"Merci de votre confiance."
                )

                # Envoi asynchrone via Celery
                send_notification_async.delay(
                    user_id=colis.client.user.id,
                    message=message,
                    categorie="colis_recu",
                    titre="Nouveau Colis Reçu",
                    region="chine",
                )
        except Exception as e:
            logger.error(f"Erreur trigger notification colis {colis.reference}: {e}")

        success_msg = "Colis ajouté avec succès !"

        if self.request.headers.get("HX-Request"):
            from django.shortcuts import render

            response = render(
                self.request,
                "chine/partials/messages.html",
                {"success_message": success_msg},
            )
            response["HX-Trigger"] = "colisAdded"
            return response

        messages.success(self.request, success_msg)
        return redirect(
            reverse_lazy("chine:lot_detail", kwargs={"pk": lot.pk})
            + "#colis-calculator"
        )


class TaskMixin(AgentChineRequiredMixin):
    def test_func(self):
        # Strict for Agent only as requested for Tâches
        return self.request.user.is_superuser or (
            hasattr(self.request.user, "role")
            and self.request.user.role == "AGENT_CHINE"
        )


class TaskBulkDeleteView(LoginRequiredMixin, TaskMixin, View):
    def post(self, request):
        task_ids = request.POST.getlist("task_ids")
        if task_ids:
            deleted_count = BackgroundTask.objects.filter(
                id__in=task_ids, created_by=request.user
            ).delete()[0]
            messages.success(request, f"{deleted_count} tâches supprimées avec succès.")
        else:
            messages.warning(request, "Aucune tâche sélectionnée.")
        return redirect("chine:task_list")


class TaskListView(LoginRequiredMixin, TaskMixin, ListView):
    model = BackgroundTask
    template_name = "chine/tasks/list.html"
    context_object_name = "tasks"
    paginate_by = 20

    def get_queryset(self):
        return BackgroundTask.objects.filter(created_by=self.request.user).order_by(
            "-created_at"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models import Count, Q

        stats = BackgroundTask.objects.filter(created_by=self.request.user).aggregate(
            pending=Count("id", filter=Q(status=BackgroundTask.Status.PENDING)),
            processing=Count("id", filter=Q(status=BackgroundTask.Status.PROCESSING)),
            success=Count("id", filter=Q(status=BackgroundTask.Status.SUCCESS)),
            failure=Count("id", filter=Q(status=BackgroundTask.Status.FAILURE)),
        )
        context["stats"] = stats
        return context


class TaskDetailView(LoginRequiredMixin, TaskMixin, DetailView):
    model = BackgroundTask
    template_name = "chine/tasks/detail.html"
    context_object_name = "task"


class TaskRetryView(LoginRequiredMixin, TaskMixin, View):
    def post(self, request, pk):
        task_record = get_object_or_404(BackgroundTask, pk=pk, created_by=request.user)
        if task_record.status == BackgroundTask.Status.FAILURE:
            task_record.status = BackgroundTask.Status.PENDING
            task_record.error_message = None
            task_record.save()
            try:
                process_colis_creation.delay(task_record.pk)
                messages.success(request, "La tâche a été relancée.")
            except Exception as e:
                logger.error(f"Retry task failed, trying sync: {e}")
                try:
                    process_colis_creation(task_record.pk)
                    messages.success(
                        request, "La tâche a été complétée en mode synchrone."
                    )
                except Exception as sync_e:
                    messages.error(request, f"Échec de la relance : {sync_e}")
        return redirect("chine:task_detail", pk=pk)


from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, UpdateView, DeleteView
from core.models import Tarif
from .forms import TarifForm


class TarifMixin(UserPassesTestMixin):
    def test_func(self):
        # Allow ADMIN_CHINE or Superuser
        return self.request.user.is_superuser or (
            hasattr(self.request.user, "role")
            and self.request.user.role == "ADMIN_CHINE"
        )


class TarifListView(LoginRequiredMixin, TarifMixin, ListView):
    model = Tarif
    template_name = "chine/tarifs/list.html"
    context_object_name = "tarifs"

    def get_queryset(self):
        queryset = Tarif.objects.all().order_by("destination", "type_transport")
        country_id = self.request.GET.get("country")
        if country_id:
            queryset = queryset.filter(destination_id=country_id)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        countries = Country.objects.exclude(code="CN").order_by("name")
        context["countries"] = countries

        current_country = self.request.GET.get("country")
        if not current_country:
            mali = countries.filter(code="ML").first()
            if mali:
                current_country = str(mali.id)

        context["current_country"] = current_country
        return context


class TarifCreateView(LoginRequiredMixin, TarifMixin, CreateView):
    model = Tarif
    form_class = TarifForm
    template_name = "chine/tarifs/form.html"
    success_url = reverse_lazy("chine:tarif_list")

    def form_valid(self, form):
        form.instance.country = self.request.user.country  # Set Owner
        messages.success(self.request, "Tarif ajouté avec succès.")
        return super().form_valid(form)


class TarifUpdateView(LoginRequiredMixin, TarifMixin, UpdateView):
    model = Tarif
    form_class = TarifForm
    template_name = "chine/tarifs/form.html"
    success_url = reverse_lazy("chine:tarif_list")

    def form_valid(self, form):
        messages.success(self.request, "Tarif mis à jour.")
        return super().form_valid(form)


class TarifDeleteView(LoginRequiredMixin, TarifMixin, DeleteView):
    model = Tarif
    template_name = "chine/tarifs/confirm_delete.html"
    success_url = reverse_lazy("chine:tarif_list")


class AgentListView(LoginRequiredMixin, AdminChineRequiredMixin, ListView):
    model = User
    template_name = "chine/agents/list.html"
    context_object_name = "agents"

    def get_queryset(self):
        return (
            User.objects.exclude(role="CLIENT")
            .exclude(is_superuser=True)
            .order_by("role", "username")
        )


class AgentCreateView(LoginRequiredMixin, AdminChineRequiredMixin, CreateView):
    model = User
    form_class = AgentForm
    template_name = "chine/agents/form.html"
    success_url = reverse_lazy("chine:agent_list")

    def form_valid(self, form):
        messages.success(
            self.request, f"Agent {form.instance.username} créé avec succès."
        )
        return super().form_valid(form)


class AgentUpdateView(LoginRequiredMixin, AdminChineRequiredMixin, UpdateView):
    model = User
    form_class = AgentForm
    template_name = "chine/agents/form.html"
    success_url = reverse_lazy("chine:agent_list")

    def form_valid(self, form):
        messages.success(self.request, f"Agent {form.instance.username} mis à jour.")
        return super().form_valid(form)


class AgentDeleteView(LoginRequiredMixin, AdminChineRequiredMixin, DeleteView):
    model = User
    template_name = "chine/agents/confirm_delete.html"
    success_url = reverse_lazy("chine:agent_list")

    def delete(self, request, *args, **kwargs):
        user = self.get_object()
        messages.success(request, f"Agent {user.username} supprimé.")
        return super().delete(request, *args, **kwargs)


# --- MODULE FINANCE CHINE ---


class ChinaDepenseListView(LoginRequiredMixin, StrictAgentChineRequiredMixin, ListView):
    model = Depense
    template_name = "chine/finance/depenses.html"
    context_object_name = "depenses"
    paginate_by = 50

    def get_queryset(self):
        # On filtre les dépenses liées à la Chine (ou à l'utilisateur courant)
        queryset = Depense.objects.filter(enregistre_par=self.request.user).order_by(
            "-date"
        )

        # Filtre par mois/année
        today = timezone.now()
        year = self.request.GET.get("year", today.year)
        month = self.request.GET.get("month", today.month)

        try:
            year = int(year)
            month = int(month)
            queryset = queryset.filter(date__year=year, date__month=month)
        except ValueError:
            pass

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now()
        try:
            context["current_year"] = int(self.request.GET.get("year", today.year))
            context["current_month"] = int(self.request.GET.get("month", today.month))
        except ValueError:
            context["current_year"] = today.year
            context["current_month"] = today.month

        context["total_depenses"] = (
            self.object_list.aggregate(Sum("montant"))["montant__sum"] or 0
        )
        return context


class ChinaDepenseCreateView(
    LoginRequiredMixin, StrictAgentChineRequiredMixin, CreateView
):
    model = Depense
    fields = ["date", "categorie", "description", "montant", "piece_jointe"]
    template_name = (
        "chine/finance/depenses.html"  # Réutilise le template liste (modal) ou séparé
    )

    def form_valid(self, form):
        form.instance.enregistre_par = self.request.user
        # Associer au pays de l'user (Chine normalement)
        if self.request.user.country:
            form.instance.pays = self.request.user.country
        else:
            # Fallback chercher Chine
            try:
                chine = Country.objects.get(code="CN")
                form.instance.pays = chine
            except Country.DoesNotExist:
                pass  # Gérer l'erreur si besoin

        messages.success(self.request, "Dépense ajoutée avec succès.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("chine:depenses_list")


class TransfertReceptionView(LoginRequiredMixin, AdminChineRequiredMixin, ListView):
    """Vue pour voir les transferts entrants et les valider (Marquer RECU)"""

    model = TransfertArgent
    template_name = "chine/finance/reception_transferts.html"
    context_object_name = "transferts"
    paginate_by = 20

    def get_queryset(self):
        # On affiche tous les transferts (venant de tous les pays)
        # Idéalement on filtre ceux qui ne sont pas "ANNULE"
        return TransfertArgent.objects.exclude(statut="ANNULE").order_by("-date")

    def post(self, request, *args, **kwargs):
        # Action pour marquer comme RECU
        transfert_id = request.POST.get("transfert_id")
        action = request.POST.get("action")

        if transfert_id and action == "confirmer_reception":
            transfert = get_object_or_404(TransfertArgent, pk=transfert_id)
            if transfert.statut == "EN_ATTENTE":
                transfert.statut = "RECU"
                transfert.save()
                messages.success(
                    request, f"Transfert de {transfert.montant} FCFA marqué comme REÇU."
                )
            else:
                messages.warning(request, "Ce transfert a déjà été traité.")

        return redirect("chine:reception_transferts")
