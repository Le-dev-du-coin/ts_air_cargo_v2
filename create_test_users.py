import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from core.models import User, Country

def create_users():
    print("Creating/Updating Test Users...")
    
    # Countries
    chine, _ = Country.objects.get_or_create(code='CN', defaults={'name': 'Chine', 'currency_symbol': '¥'})
    mali, _ = Country.objects.get_or_create(code='ML', defaults={'name': 'Mali', 'currency_symbol': 'FCFA'})
    rci, _ = Country.objects.get_or_create(code='CI', defaults={'name': 'Côte d\'Ivoire', 'currency_symbol': 'FCFA'})

    # Admin Chine
    admin_chine, created = User.objects.get_or_create(
        username='admin_chine',
        defaults={
            'email': 'admin@chine.com',
            'role': 'ADMIN_CHINE',
            'country': chine
        }
    )
    if created:
        admin_chine.set_password('password123')
        admin_chine.save()
        print(f"Created {admin_chine.username}")
    else:
        print(f"User {admin_chine.username} exists. Updating country.")
        admin_chine.country = chine
        admin_chine.save()

    # Agent Chine
    agent_chine, created = User.objects.get_or_create(
        username='agent_chine',
        defaults={
            'email': 'agent@chine.com',
            'role': 'AGENT_CHINE', # Assuming this role exists or using default
            'country': chine
        }
    )
    if created:
        agent_chine.set_password('password123')
        # If roles are strict and only defined ones allowed, ensure 'AGENT_CHINE' is valid or use 'USER'
        # Let's check permissions. The TarifMixin checks 'ADMIN_CHINE'.
        agent_chine.save()
        print(f"Created {agent_chine.username}")
    else:
        print(f"User {agent_chine.username} exists")

if __name__ == '__main__':
    create_users()
