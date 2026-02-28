from notification.models import ConfigurationNotification


def app_config(request):
    try:
        config = ConfigurationNotification.get_solo()
        version = config.app_version
    except Exception:
        version = "V2.0.1"

    return {"APP_VERSION": version}
