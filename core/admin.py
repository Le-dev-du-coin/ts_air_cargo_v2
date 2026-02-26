from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.apps import apps
from django.contrib.auth import get_user_model

User = get_user_model()

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
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

    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Informations Supplémentaires",
            {
                "classes": ("wide",),
                "fields": (
                    "role",
                    "country",
                    "phone",
                    "remuneration_mode",
                    "remuneration_value",
                ),
            },
        ),
    )


app_models = apps.get_app_config("core").get_models()
for model in app_models:
    if model != User:
        try:
            admin.site.register(model)
        except admin.sites.AlreadyRegistered:
            pass
