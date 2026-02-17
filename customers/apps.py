from django.apps import AppConfig


class CustomersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "customers"

    def ready(self):
        # import customers.signals  # Plus de signaux locaux pour le moment
        pass
