from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Q
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import TemplateView, ListView, CreateView, DetailView, UpdateView

from core.models import Client, Lot, Colis
from .forms import ClientForm, LotForm, ColisForm

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "chine/dashboard.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Stats pour l'Agent Chine
        context['lots_ouverts_count'] = Lot.objects.filter(status=Lot.Status.OUVERT).count()
        context['colis_total_count'] = Colis.objects.count()
        # Liste simplifiée des derniers lots
        context['recent_lots'] = Lot.objects.order_by('-created_at')[:5]
        return context

class ClientListView(LoginRequiredMixin, ListView):
    model = Client
    template_name = "chine/clients/list.html"
    context_object_name = "clients"
    paginate_by = 20
    ordering = ['-created_at']

class ClientCreateView(LoginRequiredMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = "chine/clients/form.html"
    success_url = reverse_lazy('chine:client_list')

    def form_valid(self, form):
        # Assigner le pays (Tenant) de l'agent connecté
        if hasattr(self.request, 'tenant_country') and self.request.tenant_country:
             form.instance.country = self.request.tenant_country
        elif self.request.user.country:
             form.instance.country = self.request.user.country
        return super().form_valid(form)

class LotListView(LoginRequiredMixin, ListView):
    model = Lot
    template_name = "chine/lots/list.html"
    context_object_name = "lots"
    paginate_by = 10
    ordering = ['-created_at']

class LotCreateView(LoginRequiredMixin, CreateView):
    model = Lot
    form_class = LotForm
    template_name = "chine/lots/form.html"
    success_url = reverse_lazy('chine:lot_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        if hasattr(self.request, 'tenant_country') and self.request.tenant_country:
             form.instance.country = self.request.tenant_country
        elif self.request.user.country:
             form.instance.country = self.request.user.country
        return super().form_valid(form)

class LotDetailView(LoginRequiredMixin, DetailView):
    model = Lot
    template_name = "chine/lots/detail.html"
    context_object_name = "lot"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['colis_form'] = ColisForm()
        context['colis_list'] = self.object.colis.all().order_by('-created_at')
        return context

class ColisCreateView(LoginRequiredMixin, CreateView):
    model = Colis
    form_class = ColisForm
    template_name = "chine/lots/detail.html" # En cas d'erreur form

    def get_success_url(self):
        return reverse_lazy('chine:lot_detail', kwargs={'pk': self.object.lot.pk})

    def form_valid(self, form):
        lot = get_object_or_404(Lot, pk=self.kwargs['lot_id'])
        form.instance.lot = lot
        form.instance.country = lot.country
        return super().form_valid(form)

    def form_invalid(self, form):
        lot = get_object_or_404(Lot, pk=self.kwargs['lot_id'])
        return render(self.request, 'chine/lots/detail.html', {
            'lot': lot,
            'colis_form': form,
            'colis_list': lot.colis.all().order_by('-created_at')
        })
