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
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.contrib import messages

logger = logging.getLogger(__name__)
from django.views.generic import edit as delete

from core.models import Client, Lot, Colis, BackgroundTask, Country
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
        return redirect("chine:dashboard")


class AgentChineRequiredMixin(RoleRequiredMixin):
    allowed_roles = [
        "AGENT_CHINE",
        "ADMIN_CHINE",
    ]  # Admins can generally see agent stuff


class StrictAgentChineRequiredMixin(RoleRequiredMixin):
    allowed_roles = ["AGENT_CHINE"]


class AdminChineRequiredMixin(RoleRequiredMixin):
    allowed_roles = ["ADMIN_CHINE"]


class DashboardView(LoginRequiredMixin, AgentChineRequiredMixin, TemplateView):
    template_name = "chine/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Stats pour l'Agent Chine
        context["lots_ouverts_count"] = Lot.objects.filter(
            status=Lot.Status.OUVERT
        ).count()
        context["lots_fermes_count"] = Lot.objects.filter(
            status=Lot.Status.FERME
        ).count()
        context["colis_total_count"] = Colis.objects.count()
        context["total_clients_count"] = Client.objects.count()

        # Stats avancées pour l'Admin Chine
        if self.request.user.role == "ADMIN_CHINE":
            # Lots par Pays/Status
            context["lots_mali_count"] = Lot.objects.filter(
                destination__code="ML"
            ).count()
            context["lots_ci_count"] = Lot.objects.filter(
                destination__code="CI"
            ).count()
            context["lots_transit_count"] = Lot.objects.filter(
                status=Lot.Status.EXPEDIE
            ).count()
            context["lots_chine_count"] = Lot.objects.filter(
                status__in=[Lot.Status.OUVERT, Lot.Status.FERME]
            ).count()

            # Totaux globaux
            context["total_agents_count"] = (
                User.objects.exclude(role="CLIENT").exclude(is_superuser=True).count()
            )

            # Bénéfices mensuels (Mali & CI)
            now = timezone.now()
            start_of_month = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )

            def get_monthly_profit(country_code):
                lots = Lot.objects.filter(
                    destination__code=country_code, created_at__gte=start_of_month
                )
                total_recettes = (
                    Colis.objects.filter(lot__in=lots).aggregate(
                        total=Sum("prix_final")
                    )["total"]
                    or 0
                )
                total_depenses = lots.aggregate(
                    transport=Sum("frais_transport"), douane=Sum("frais_douane")
                )
                depenses = (total_depenses["transport"] or 0) + (
                    total_depenses["douane"] or 0
                )
                return float(total_recettes) - float(depenses)

            context["profit_mali_mensuel"] = get_monthly_profit("ML")
            context["profit_ci_mensuel"] = get_monthly_profit("CI")

            # Données Graphique (Derniers 6 mois)
            chart_data = []
            for i in range(5, -1, -1):
                month_start = (start_of_month - timedelta(days=i * 30)).replace(day=1)
                month_end = (month_start + timedelta(days=32)).replace(day=1)
                count = Colis.objects.filter(
                    created_at__gte=month_start, created_at__lt=month_end
                ).count()
                chart_data.append({"month": month_start.strftime("%b"), "count": count})
            context["chart_data"] = chart_data

        # Liste simplifiée des derniers lots
        context["recent_lots"] = Lot.objects.order_by("-created_at")[:5]
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
        return super().form_valid(form)


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

            lot.status = "EXPEDIE"
            lot.date_expedition = timezone.now()
            lot.save()
            # Also update colis status? Generally yes.
            lot.colis.update(status="EXPEDIE")
            messages.success(
                request, f"Lot {lot.numero} EXPÉDIÉ ! (Mode Lecture Seule activé)"
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
            total_montant=Sum("prix_transport"),
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

        # Preparing parameters for the task
        params = {
            "lot_id": lot.pk,
            "client_id": form.cleaned_data["client"].pk,
            "type_colis": form.cleaned_data["type_colis"],
            "nombre_pieces": form.cleaned_data["nombre_pieces"],
            "description": form.cleaned_data["description"],
            "poids": float(form.cleaned_data["poids"]),
            "longueur": float(form.cleaned_data["longueur"]),
            "largeur": float(form.cleaned_data["largeur"]),
            "hauteur": float(form.cleaned_data["hauteur"]),
            "cbm": float(form.cleaned_data["cbm"]),
            "prix_final": float(form.cleaned_data["prix_final"]),
            "est_paye": form.cleaned_data["est_paye"],
        }

        # Handling photo: Save temporarily
        photo = form.cleaned_data.get("photo")
        if photo:
            # FASTEST SAVE: Just save to tmp and move on
            temp_path = default_storage.save(
                f"tmp/{photo.name}", ContentFile(photo.read())
            )
            params["temp_photo_path"] = default_storage.path(temp_path)

        # Create BackgroundTask record
        task_record = BackgroundTask.objects.create(
            name=f"Création Colis - Lot {lot.numero}",
            parameters=params,
            created_by=self.request.user,
            country=lot.country,
        )

        # Trigger Celery task
        try:
            process_colis_creation.delay(task_record.pk)
            messages.success(self.request, "Colis en cours d'enregistrement...")
        except Exception as e:
            logger.error(f"Error triggering Celery task: {e}")
            # Fallback for reliability but warn user
            process_colis_creation(task_record.pk)
            messages.warning(self.request, "Colis enregistré (Mode secours).")

        # ALWAYS redirect back to the form for extreme speed
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
        from django.db.models import Count

        stats = BackgroundTask.objects.filter(created_by=self.request.user).aggregate(
            pending=Count("id", filter=models.Q(status=BackgroundTask.Status.PENDING)),
            processing=Count(
                "id", filter=models.Q(status=BackgroundTask.Status.PROCESSING)
            ),
            success=Count("id", filter=models.Q(status=BackgroundTask.Status.SUCCESS)),
            failure=Count("id", filter=models.Q(status=BackgroundTask.Status.FAILURE)),
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
