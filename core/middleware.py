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
