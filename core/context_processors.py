import subprocess
from django.conf import settings
from notification.models import ConfigurationNotification


def get_git_version():
    try:
        out = subprocess.check_output(["git", "describe", "--tags", "--always"], stderr=subprocess.DEVNULL)
        v_str = out.decode("utf-8").strip()
        if v_str:
            return v_str
    except Exception:
        pass
    return getattr(settings, "ERP_VERSION", "v2.5.0")


def app_config(request):
    version = getattr(settings, "ERP_VERSION", None)
    if not version:
        version = get_git_version()

    # Préfixe de transport pour les URLs dans les templates
    if getattr(request, "is_maritime", False):
        transport_prefix = "/maritime"
    else:
        transport_prefix = "/aerien"

    return {
        "APP_VERSION": version,
        "transport_prefix": transport_prefix,
    }
