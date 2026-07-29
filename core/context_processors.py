from django.conf import settings
from notification.models import ConfigurationNotification


def app_config(request):
    # Version automatique centralisée de l'ERP
    version = getattr(settings, "ERP_VERSION", "v2.5.0")
    try:
        config = ConfigurationNotification.get_solo()
        if config and config.app_version:
            version = config.app_version
    except Exception:
        pass

    # Préfixe de transport pour les URLs dans les templates
    # Évite de recourir à des templatetags personnalisés
    if getattr(request, "is_maritime", False):
        transport_prefix = "/maritime"
    else:
        transport_prefix = "/aerien"

    return {
        "APP_VERSION": version,
        "transport_prefix": transport_prefix,
    }
