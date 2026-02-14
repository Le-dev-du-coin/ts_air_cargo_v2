from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from core.models import Country

User = get_user_model()

class Command(BaseCommand):
    help = 'Creates test users and countries'

    def handle(self, *args, **options):
        # 1. Ensure Countries exist
        self.stdout.write("Creating countries...")
        ci, _ = Country.objects.get_or_create(code="CI", defaults={"name": "Côte d'Ivoire", "currency_symbol": "FCFA"})
        ml, _ = Country.objects.get_or_create(code="ML", defaults={"name": "Mali", "currency_symbol": "FCFA"})
        cn, _ = Country.objects.get_or_create(code="CN", defaults={"name": "Chine", "currency_symbol": "¥"})

        # 2. Create Users
        users_data = [
            {
                "username": "admin_global",
                "email": "admin@tsaircargo.com",
                "password": "password123",
                "role": User.Role.GLOBAL_ADMIN,
                "country": None,
                "is_staff": True,
                "is_superuser": True
            },
            {
                "username": "agent_chine",
                "email": "chine@tsaircargo.com",
                "password": "password123",
                "role": User.Role.AGENT_CHINE,
                "country": cn,
                "is_staff": False,
                "is_superuser": False
            },
            {
                "username": "agent_mali",
                "email": "mali@tsaircargo.com",
                "password": "password123",
                "role": User.Role.AGENT_MALI,
                "country": ml,
                "is_staff": False,
                "is_superuser": False
            },
            {
                "username": "agent_rci",
                "email": "rci@tsaircargo.com",
                "password": "password123",
                "role": User.Role.AGENT_RCI,
                "country": ci,
                "is_staff": False,
                "is_superuser": False
            }
        ]

        for u_data in users_data:
            username = u_data.pop("username")
            password = u_data.pop("password")
            user, created = User.objects.get_or_create(username=username, defaults=u_data)
            
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Created user: {username} ({u_data['role']})"))
            else:
                self.stdout.write(f"User {username} already exists.")

        self.stdout.write(self.style.SUCCESS("Test data initialization complete."))
