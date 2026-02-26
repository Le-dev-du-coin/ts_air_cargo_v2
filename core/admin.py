from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.apps import apps
from django.contrib.auth import get_user_model

User = get_user_model()


class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "Informations Supplémentaires",
            {
                "fields": (
                    "role",
                    "country",
                    "phone",
                    "remuneration_mode",
                    "remuneration_value",
                )
            },
        ),
    )


app_models = apps.get_app_config("core").get_models()
for model in app_models:
    try:
        if model == User:
            admin.site.register(User, CustomUserAdmin)
        else:
            admin.site.register(model)
    except admin.sites.AlreadyRegistered:
        pass
