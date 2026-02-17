from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, TemplateView, UpdateView
from django.contrib.auth.views import PasswordChangeView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.urls import reverse_lazy
from core.models import Colis, Client as ClientModel
from django.db.models import Q

User = get_user_model()


class ClientRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.role == "CLIENT"


class ClientDashboardView(LoginRequiredMixin, ClientRequiredMixin, TemplateView):
    template_name = "customers/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Récupérer le profil client lié
        client_profile = getattr(user, "client_profile", None)

        if client_profile:
            # Colis en cours (non livrés)
            colis_queryset = Colis.objects.filter(client=client_profile)
            context["transit_count"] = colis_queryset.filter(
                status__in=["EXPEDIE", "ARRIVE", "EN_TRANSIT"]
            ).count()
            context["recu_count"] = colis_queryset.filter(status="RECU").count()
            context["livre_count"] = colis_queryset.filter(status="LIVRE").count()
            context["recent_colis"] = colis_queryset.order_by("-created_at")[:20]
        else:
            context["error"] = (
                "Aucun profil client associé. Veuillez contacter l'administrateur."
            )

        return context


class ClientParcelListView(LoginRequiredMixin, ClientRequiredMixin, ListView):
    model = Colis
    template_name = "customers/parcel_list.html"
    context_object_name = "colis_list"
    paginate_by = 10

    def get_queryset(self):
        user = self.request.user
        client_profile = getattr(user, "client_profile", None)
        if not client_profile:
            return Colis.objects.none()

        queryset = Colis.objects.filter(client=client_profile).order_by("-created_at")

        q = self.request.GET.get("q")
        if q:
            queryset = queryset.filter(
                Q(reference__icontains=q) | Q(description__icontains=q)
            )
        return queryset


class ClientParcelDetailView(LoginRequiredMixin, ClientRequiredMixin, DetailView):
    model = Colis
    template_name = "customers/parcel_detail.html"
    context_object_name = "colis"

    def get_queryset(self):
        user = self.request.user
        client_profile = getattr(user, "client_profile", None)
        if not client_profile:
            return Colis.objects.none()
        return Colis.objects.filter(client=client_profile)


class ClientProfileUpdateView(LoginRequiredMixin, ClientRequiredMixin, UpdateView):
    model = ClientModel
    fields = ["nom", "prenom", "telephone", "adresse"]
    template_name = "customers/profile_form.html"
    success_url = reverse_lazy("customers:dashboard")

    def get_object(self):
        return self.request.user.client_profile

    def form_valid(self, form):
        messages.success(self.request, "Profil mis à jour avec succès.")
        return super().form_valid(form)


class ClientPasswordChangeView(
    LoginRequiredMixin, ClientRequiredMixin, PasswordChangeView
):
    template_name = "customers/password_change.html"
    success_url = reverse_lazy("customers:dashboard")

    def form_valid(self, form):
        messages.success(self.request, "Votre mot de passe a été modifié avec succès.")
        return super().form_valid(form)


class ClientSettingsView(LoginRequiredMixin, ClientRequiredMixin, TemplateView):
    template_name = "customers/settings.html"
