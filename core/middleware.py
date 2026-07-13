from .models import Country

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Global Admin bypasses tenancy
            if request.user.role == 'GLOBAL_ADMIN' or request.user.is_superuser:
                request.tenant_country = None
            else:
                # Regular users are scoped to their country
                request.tenant_country = request.user.country
        else:
            # Anonymous users have no country context
            request.tenant_country = None

        response = self.get_response(request)
        return response


from django.core.exceptions import PermissionDenied
from core.context import set_current_transport_mode, clear_current_transport_mode

class TransportMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        
        # Détermination du mode de transport
        if path.startswith('/maritime/'):
            mode = 'BATEAU'
            request.transport_mode = 'BATEAU'
            request.is_maritime = True
            request.is_aerien = False
            
            # Vérification des droits d'accès
            if request.user.is_authenticated and not request.user.is_superuser:
                if request.user.role != 'GLOBAL_ADMIN' and not getattr(request.user, 'has_maritime_access', True):
                    raise PermissionDenied("Vous n'avez pas accès à l'espace Maritime.")
                    
        else:
            # Tout autre chemin (y compris /aerien/ ou racine) est traité en AERIEN
            mode = 'AERIEN'
            request.transport_mode = 'AERIEN'
            request.is_maritime = False
            request.is_aerien = True
            
            # Vérification des droits d'accès si on est explicitement sous /aerien/
            if path.startswith('/aerien/'):
                if request.user.is_authenticated and not request.user.is_superuser:
                    if request.user.role != 'GLOBAL_ADMIN' and not getattr(request.user, 'has_aerien_access', True):
                        raise PermissionDenied("Vous n'avez pas accès à l'espace Aérien.")
            
        # Enregistrement dans le contexte global de thread
        token = set_current_transport_mode(mode)
        try:
            response = self.get_response(request)
        finally:
            clear_current_transport_mode(token)
            
        return response
