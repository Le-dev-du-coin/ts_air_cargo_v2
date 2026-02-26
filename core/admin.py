from django.contrib import admin
from django.apps import apps

# Enregistrement automatique de tous les modèles de l'application 'core'
app_models = apps.get_app_config("core").get_models()
for model in app_models:
    try:
        admin.site.register(model)
    except admin.sites.AlreadyRegistered:
        pass
