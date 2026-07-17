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
from django.shortcuts import redirect
from core.context import set_current_transport_mode, clear_current_transport_mode

class TransportMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        
        # Redirection automatique pour les anciennes URLs non préfixées (GET uniquement)
        if request.method == 'GET':
            for prefix in ['chine', 'mali', 'ivoire', 'clients', 'report']:
                if path.startswith(f'/{prefix}/') or path == f'/{prefix}':
                    return redirect(f'/aerien{path}')
        
        # Détermination du mode de transport
        mode = None
        if path.startswith('/maritime/'):
            mode = 'BATEAU'
        elif path.startswith('/aerien/'):
            mode = 'AERIEN'
        else:
            # Pour les anciennes URLs non préfixées qui sont soumises en POST (non redirigées),
            # ou pour les requêtes HTMX, on détecte le mode via le referer (la page d'origine)
            referer = request.META.get('HTTP_REFERER', '')
            if '/maritime/' in referer:
                mode = 'BATEAU'
            elif '/aerien/' in referer:
                mode = 'AERIEN'
            else:
                # Espace client global, admin global, etc. -> pas de filtrage par défaut
                mode = None
            
        if mode == 'BATEAU':
            request.transport_mode = 'BATEAU'
            request.is_maritime = True
            request.is_aerien = False
            request.current_app = 'maritime'
            
            # Vérification des droits d'accès
            if request.user.is_authenticated and not request.user.is_superuser:
                if request.user.role != 'GLOBAL_ADMIN' and not getattr(request.user, 'has_maritime_access', True):
                    raise PermissionDenied("Vous n'avez pas accès à l'espace Maritime.")
                    
        elif mode == 'AERIEN':
            request.transport_mode = 'AERIEN'
            request.is_maritime = False
            request.is_aerien = True
            request.current_app = 'aerien'
            
            # Vérification des droits d'accès si on est explicitement sous /aerien/
            if request.user.is_authenticated and not request.user.is_superuser:
                if request.user.role != 'GLOBAL_ADMIN' and not getattr(request.user, 'has_aerien_access', True):
                    raise PermissionDenied("Vous n'avez pas accès à l'espace Aérien.")
        else:
            request.transport_mode = None
            request.is_maritime = False
            request.is_aerien = False
            request.current_app = None
            
        # Enregistrement dans le contexte global de thread
        token = set_current_transport_mode(mode)
        try:
            response = self.get_response(request)
        finally:
            clear_current_transport_mode(token)
            
        # Correction automatique des redirections pour préserver le mode de transport
        if response.status_code in [301, 302, 307, 308] and 'Location' in response:
            redirect_url = response['Location']
            if redirect_url.startswith('/') and not (redirect_url.startswith('/aerien/') or redirect_url.startswith('/maritime/')):
                for prefix in ['chine', 'mali', 'ivoire', 'clients', 'report']:
                    if redirect_url.startswith(f'/{prefix}/') or redirect_url == f'/{prefix}':
                        if request.is_maritime:
                            response['Location'] = f'/maritime{redirect_url}'
                        else:
                            response['Location'] = f'/aerien{redirect_url}'
                        break
            
        return response
