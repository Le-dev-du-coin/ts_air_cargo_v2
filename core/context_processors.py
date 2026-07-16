from notification.models import ConfigurationNotification


def app_config(request):
    try:
        config = ConfigurationNotification.get_solo()
        version = config.app_version
    except Exception:
        version = "V2.0.1"

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
