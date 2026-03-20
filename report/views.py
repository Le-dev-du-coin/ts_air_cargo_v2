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
        user = self.request.user

        # Filtre par mois/année (par défaut mois courant)
        today = timezone.now()
        self.year = int(self.request.GET.get("year", today.year))
        self.month = int(self.request.GET.get("month", today.month))
        qs = qs.filter(date__year=self.year, date__month=self.month)

        # Filtrer par pays de l'utilisateur (si applicable)
        if hasattr(user, "country") and user.country:
            if user.country.code == "ML":
                # Mali voit ses dépenses + les indicatives Chine (globales)
                qs = qs.filter(Q(pays=user.country) | Q(is_china_indicative=True))
            else:
                qs = qs.filter(pays=user.country)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # On récupère le queryset filtré par le mois/année actuel
        qs_base = self.get_queryset()

        # Séparer dépenses réelles Mali et indicatives Chine
        # Très important : utilise les noms attendus par le template
        depenses_mali = qs_base.filter(is_china_indicative=False)
        depenses_indicatives = qs_base.filter(is_china_indicative=True)

        context["depenses_mali"] = depenses_mali
        context["depenses_indicatives"] = depenses_indicatives

        context["total_depenses_mali"] = (
            depenses_mali.aggregate(Sum("montant"))["montant__sum"] or 0
        )
        context["total_depenses_indicatives"] = (
            depenses_indicatives.aggregate(Sum("montant"))["montant__sum"] or 0
        )

        context["current_year"] = self.year
        context["current_month"] = self.month

        # Ajout du total des transferts
        transferts_mois = TransfertArgent.objects.filter(
            date__year=self.year, date__month=self.month
        )
        if hasattr(user, "country") and user.country:
            transferts_mois = transferts_mois.filter(pays_expediteur=user.country)

        context["total_transferts_mois"] = (
            transferts_mois.aggregate(Sum("montant"))["montant__sum"] or 0
        )

        from core.models import Country

        context["countries"] = Country.objects.all()

        return context


class DepenseCreateView(LoginRequiredMixin, CreateView):
    model = Depense
    fields = ["date", "categorie", "description", "montant", "piece_jointe", "pays"]

    def form_valid(self, form):
        user = self.request.user
        self.object = form.save(commit=False)
        self.object.enregistre_par = user

        # 1. Définir le pays par défaut si non saisi (au cas où le champ soit omis)
        if not self.object.pays:
            if hasattr(user, "country") and user.country:
                self.object.pays = user.country

        # 2. Automatisme de marquage indicatif (Chine)
        current_role = str(user.role).upper()
        
        if current_role in ["ADMIN_CHINE", "AGENT_CHINE"]:
            self.object.is_china_indicative = True
        else:
            self.object.is_china_indicative = False

        self.object.save()
        messages.success(self.request, "Dépense ajoutée avec succès.")
        from django.shortcuts import HttpResponseRedirect
        return HttpResponseRedirect(self.get_success_url())

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

        # 1. Recettes (Colis livrés ET payés — status LIVRE obligatoire)
        colis_qs = Colis.objects.filter(
            status="LIVRE",
            est_paye=True,
            date_encaissement__year=year,
            date_encaissement__month=month,
        )

        if country:
            # Filtrer les colis dont le lot est à destination du pays de l'agent
            colis_qs = colis_qs.filter(lot__destination=country)

        # Calcul montant net (Prix final - JC)
        recettes_agg = colis_qs.aggregate(
            total_net=Sum(F("prix_final") - F("montant_jc"))
        )
        total_recettes = recettes_agg["total_net"] or 0

        # 2. Dépenses (Mali uniquement)
        depenses_qs = Depense.objects.filter(
            date__year=year, date__month=month, is_china_indicative=False
        )
        if country:
            depenses_qs = depenses_qs.filter(pays=country)

        total_depenses_reelles = (
            depenses_qs.aggregate(Sum("montant"))["montant__sum"] or 0
        )

        # 3. Transferts (considérés comme dépenses)
        transferts_qs = TransfertArgent.objects.filter(
            date__year=year, date__month=month
        )
        if country:
            transferts_qs = transferts_qs.filter(pays_expediteur=country)

        total_transferts = transferts_qs.aggregate(Sum("montant"))["montant__sum"] or 0

        # Total Transferts par destination
        total_transferts_chine = (
            transferts_qs.filter(destinataire="CHINE").aggregate(Sum("montant"))[
                "montant__sum"
            ]
            or 0
        )
        total_transferts_gaoussou = (
            transferts_qs.filter(destinataire="GAOUSSOU").aggregate(Sum("montant"))[
                "montant__sum"
            ]
            or 0
        )

        # 4. Solde
        # Solde = Recettes - (Dépenses Réelles + Transferts)
        solde = total_recettes - (total_depenses_reelles + total_transferts)

        context.update(
            {
                "total_recettes": total_recettes,
                "total_depenses": total_depenses_reelles,
                "total_transferts_chine": total_transferts_chine,
                "total_transferts_gaoussou": total_transferts_gaoussou,
                "total_transferts": total_transferts,
                "total_sorties": total_depenses_reelles + total_transferts,
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

        # Filtre par mois/année (par défaut mois courant)
        today = timezone.now()
        try:
            self.year = int(self.request.GET.get("year", today.year))
            self.month = int(self.request.GET.get("month", today.month))
        except (ValueError, TypeError):
            self.year = today.year
            self.month = today.month

        qs = qs.filter(date__year=self.year, date__month=self.month)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_year"] = self.year
        context["current_month"] = self.month

        # Totaux basés sur le queryset filtré
        qs_all = self.get_queryset()
        context["total_transferts"] = (
            qs_all.aggregate(Sum("montant"))["montant__sum"] or 0
        )

        # Séparation des transferts
        context["transferts_chine"] = qs_all.filter(destinataire="CHINE")
        context["transferts_gaoussou"] = qs_all.filter(destinataire="GAOUSSOU")

        context["total_chine"] = (
            context["transferts_chine"].aggregate(Sum("montant"))["montant__sum"] or 0
        )
        context["total_gaoussou"] = (
            context["transferts_gaoussou"].aggregate(Sum("montant"))["montant__sum"]
            or 0
        )

        # Années pour le filtre (3 dernières années)
        today = timezone.now()
        context["years"] = range(today.year, today.year - 4, -1)
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


class TransfertCreateView(LoginRequiredMixin, CreateView):
    model = TransfertArgent
    fields = ["date", "destinataire", "montant", "description", "preuve_image"]

    def form_valid(self, form):
        form.instance.enregistre_par = self.request.user
        if hasattr(self.request.user, "country") and self.request.user.country:
            form.instance.pays_expediteur = self.request.user.country

        # Auto-validation : statut RECU par défaut car considéré comme sortie de caisse immédiate
        form.instance.statut = "RECU"

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
        # 1. Recettes (Colis livrés ET payés — status LIVRE obligatoire)
        colis_qs = Colis.objects.filter(
            status="LIVRE",
            est_paye=True,
            date_encaissement__year=year,
            date_encaissement__month=month,
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

        total_depenses_reelles = (
            depenses_qs.aggregate(Sum("montant"))["montant__sum"] or 0
        )

        # 3. Transferts (considérés comme dépenses)
        transferts_qs = TransfertArgent.objects.filter(
            date__year=year, date__month=month
        )
        if country:
            transferts_qs = transferts_qs.filter(pays_expediteur=country)

        total_transferts = transferts_qs.aggregate(Sum("montant"))["montant__sum"] or 0
        total_transferts_chine = (
            transferts_qs.filter(destinataire="CHINE").aggregate(Sum("montant"))[
                "montant__sum"
            ]
            or 0
        )
        total_transferts_gaoussou = (
            transferts_qs.filter(destinataire="GAOUSSOU").aggregate(Sum("montant"))[
                "montant__sum"
            ]
            or 0
        )

        # 4. Solde
        solde = total_recettes - (total_depenses_reelles + total_transferts)

        context = {
            "year": year,
            "month": month,
            "total_recettes": total_recettes,
            "total_depenses": total_depenses_reelles,
            "total_transferts": total_transferts,
            "total_transferts_chine": total_transferts_chine,
            "total_transferts_gaoussou": total_transferts_gaoussou,
            "solde": solde,
            "depenses_by_category": depenses_qs.values("categorie")
            .annotate(total=Sum("montant"))
            .order_by("-total"),
            "depenses": depenses_qs.order_by("date"),
            "country": country,
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
            writer.writerow(["Total Transferts", total_transferts])
            writer.writerow(["Solde Période", solde])
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
            from core.utils_pdf import render_to_pdf_playwright

            filename = f"rapport_financier_{month}_{year}.pdf"
            return render_to_pdf_playwright(
                "mali/pdf/rapport_financier.html", context, request, filename=filename
            )
