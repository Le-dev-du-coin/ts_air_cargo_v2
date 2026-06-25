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
        mali = self.request.user.country
        qs = Colis.objects.filter(status="LIVRE", sortie_sous_garantie=True)
        if mali:
            qs = qs.filter(lot__destination=mali)
            
        personnes_names = qs.exclude(sortie_autorisee_par__isnull=True).exclude(sortie_autorisee_par="").values_list('sortie_autorisee_par', flat=True).distinct()
        return list(personnes_names)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        personnes_data = []
        for nom in self.object_list:
            colis_personne = Colis.objects.filter(status="LIVRE", sortie_sous_garantie=True, sortie_autorisee_par=nom)
            personnes_data.append({
                'nom': nom,
                'nb_colis': colis_personne.count(),
                'total_poids': colis_personne.aggregate(t=Sum('poids'))['t'] or 0,
                'total_cbm': colis_personne.aggregate(t=Sum('cbm'))['t'] or 0,
            })
        
        context["personnes_data"] = personnes_data
        return context

class ColisSortieGarantieDetailView(LoginRequiredMixin, DestinationAgentRequiredMixin, ListView):
    template_name = "mali/personne_sortie_detail.html"
    context_object_name = "colis_list"
    paginate_by = 50

    def get_queryset(self):
        nom_personne = self.kwargs.get('nom')
        qs = Colis.objects.filter(status="LIVRE", sortie_sous_garantie=True, sortie_autorisee_par=nom_personne)
        
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
