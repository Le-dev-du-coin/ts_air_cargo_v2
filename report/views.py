from django.shortcuts import render
from django.http import HttpResponse
from django.views.generic import ListView, CreateView, DeleteView, TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib import messages
from django.utils import timezone
from .models import Depense, TransfertArgent
from django.db.models import Sum, F, Q
from core.models import Colis


class DepenseListView(LoginRequiredMixin, ListView):
    model = Depense
    context_object_name = "depenses"
    paginate_by = 50

    def get_queryset(self):
        qs = super().get_queryset()
        # Filtrer par pays de l'utilisateur (si applicable)
        if hasattr(self.request.user, "country") and self.request.user.country:
            qs = qs.filter(pays=self.request.user.country)

        # Filtre par mois/année (par défaut mois courant)
        today = timezone.now()
        self.year = int(self.request.GET.get("year", today.year))
        self.month = int(self.request.GET.get("month", today.month))

        qs = qs.filter(date__year=self.year, date__month=self.month)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_year"] = self.year
        context["current_month"] = self.month
        context["total_depenses"] = (
            self.object_list.aggregate(Sum("montant"))["montant__sum"] or 0
        )
        return context


class DepenseCreateView(LoginRequiredMixin, CreateView):
    model = Depense
    fields = ["date", "categorie", "description", "montant", "piece_jointe"]

    def form_valid(self, form):
        form.instance.enregistre_par = self.request.user
        if hasattr(self.request.user, "country") and self.request.user.country:
            form.instance.pays = self.request.user.country
        else:
            # Fallback ou erreur si l'utilisateur n'a pas de pays ?
            # Pour l'instant on laisse planter ou on gère plus tard
            pass
        messages.success(self.request, "Dépense ajoutée avec succès.")
        return super().form_valid(form)

    def get_success_url(self):
        # On redirige vers la liste (qui sera dans l'app appelante, ex: mali:depenses_list)
        # Mais comme c'est générique, on doit être malin.
        # Option: passer un parameter 'next' ou utiliser HTTP_REFERER
        return self.request.META.get("HTTP_REFERER", "/")


class DepenseDeleteView(LoginRequiredMixin, DeleteView):
    model = Depense

    def get_success_url(self):
        messages.success(self.request, "Dépense supprimée.")
        return self.request.META.get("HTTP_REFERER", "/")


class RapportFinancierView(LoginRequiredMixin, TemplateView):
    template_name = "mali/finance/rapport.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Date filtering
        today = timezone.now()
        try:
            year = int(self.request.GET.get("year", today.year))
            month = int(self.request.GET.get("month", today.month))
        except ValueError:
            year = today.year
            month = today.month

        context["current_year"] = year
        context["current_month"] = month

        # Country filtering
        country = (
            self.request.user.country if hasattr(self.request.user, "country") else None
        )

        # 1. Recettes (Colis payés)

        colis_qs = Colis.objects.filter(
            est_paye=True, updated_at__year=year, updated_at__month=month
        )

        if country:
            # Filtrer les colis dont le lot est à destination du pays de l'agent
            colis_qs = colis_qs.filter(lot__destination=country)

        # Calcul montant net (Prix final - JC)
        recettes_agg = colis_qs.aggregate(
            total_net=Sum(F("prix_final") - F("montant_jc"))
        )
        total_recettes = recettes_agg["total_net"] or 0

        # 2. Dépenses
        depenses_qs = Depense.objects.filter(date__year=year, date__month=month)
        if country:
            depenses_qs = depenses_qs.filter(pays=country)

        total_depenses = depenses_qs.aggregate(Sum("montant"))["montant__sum"] or 0

        # 3. Solde
        solde = total_recettes - total_depenses

        context.update(
            {
                "total_recettes": total_recettes,
                "total_depenses": total_depenses,
                "solde": solde,
                "depenses_by_category": depenses_qs.values("categorie")
                .annotate(total=Sum("montant"))
                .order_by("-total"),
            }
        )

        return context


class TransfertListView(LoginRequiredMixin, ListView):
    model = TransfertArgent
    context_object_name = "transferts"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request.user, "country") and self.request.user.country:
            qs = qs.filter(pays_expediteur=self.request.user.country)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["total_transferts"] = (
            self.object_list.aggregate(Sum("montant"))["montant__sum"] or 0
        )
        return context


class TransfertCreateView(LoginRequiredMixin, CreateView):
    model = TransfertArgent
    fields = ["date", "montant", "description", "preuve_image"]

    def form_valid(self, form):
        form.instance.enregistre_par = self.request.user
        if hasattr(self.request.user, "country") and self.request.user.country:
            form.instance.pays_expediteur = self.request.user.country

        messages.success(self.request, "Transfert enregistré avec succès.")
        return super().form_valid(form)

    def get_success_url(self):
        return self.request.META.get("HTTP_REFERER", "/")


class RapportExportView(LoginRequiredMixin, View):
    def get(self, request):
        today = timezone.now()
        try:
            year = int(request.GET.get("year", today.year))
            month = int(request.GET.get("month", today.month))
        except ValueError:
            year = today.year
            month = today.month

        export_format = request.GET.get("format", "pdf")

        # Filtre par pays de l'utilisateur
        country = request.user.country if hasattr(request.user, "country") else None

        # --- Récupération des données (Similaire à RapportFinancierView) ---
        # 1. Recettes
        colis_qs = Colis.objects.filter(
            est_paye=True, updated_at__year=year, updated_at__month=month
        )
        if country:
            colis_qs = colis_qs.filter(lot__destination=country)

        recettes_agg = colis_qs.aggregate(
            total_net=Sum(F("prix_final") - F("montant_jc"))
        )
        total_recettes = recettes_agg["total_net"] or 0

        # 2. Dépenses
        depenses_qs = Depense.objects.filter(date__year=year, date__month=month)
        if country:
            depenses_qs = depenses_qs.filter(pays=country)

        total_depenses = depenses_qs.aggregate(Sum("montant"))["montant__sum"] or 0

        # 3. Solde
        solde = total_recettes - total_depenses

        context = {
            "year": year,
            "month": month,
            "total_recettes": total_recettes,
            "total_depenses": total_depenses,
            "solde": solde,
            "depenses": depenses_qs.order_by("date"),
            "user": request.user,
            "date_generation": timezone.now(),
        }

        if export_format == "csv":
            import csv

            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = (
                f'attachment; filename="rapport_financier_{month}_{year}.csv"'
            )
            response.write("\ufeff".encode("utf8"))  # BOM pour Excel

            writer = csv.writer(response)
            writer.writerow(["Rapport Financier", f"{month}/{year}"])
            writer.writerow(["Généré par", request.user.get_full_name()])
            writer.writerow([])
            writer.writerow(["Total Recettes", total_recettes])
            writer.writerow(["Total Dépenses", total_depenses])
            writer.writerow(["Solde", solde])
            writer.writerow([])
            writer.writerow(["Détail des Dépenses"])
            writer.writerow(["Date", "Catégorie", "Description", "Montant"])

            for depense in depenses_qs.order_by("date"):
                writer.writerow(
                    [
                        depense.date,
                        depense.get_categorie_display(),
                        depense.description,
                        depense.montant,
                    ]
                )
            return response

        else:  # PDF by default
            from django.template.loader import render_to_string
            from xhtml2pdf import pisa

            html_string = render_to_string("mali/pdf/rapport_financier.html", context)

            response = HttpResponse(content_type="application/pdf")
            response["Content-Disposition"] = (
                f'inline; filename="rapport_financier_{month}_{year}.pdf"'
            )

            pisa_status = pisa.CreatePDF(html_string, dest=response)
            if pisa_status.err:
                return HttpResponse("Erreur lors de la génération du PDF", status=500)
            return response
