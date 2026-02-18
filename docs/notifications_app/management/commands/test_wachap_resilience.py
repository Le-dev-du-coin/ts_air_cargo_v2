"""
Commande pour tester la résilience du système WaChap
"""

from django.core.management.base import BaseCommand
from notifications_app.wachap_service import WaChapService
from notifications_app.timeout_handler import timeout_handler, circuit_breaker
import time

class Command(BaseCommand):
    help = 'Teste la résilience et la gestion des timeouts WaChap'

    def add_arguments(self, parser):
        parser.add_argument(
            '--phone',
            type=str,
            default='+8615112223234',
            help='Numéro de téléphone pour le test'
        )
        parser.add_argument(
            '--region',
            type=str,
            default='system',
            choices=['system', 'chine', 'mali'],
            help='Instance WaChap à tester'
        )
        parser.add_argument(
            '--attempts',
            type=int,
            default=3,
            help='Nombre de tentatives d\'envoi'
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('=== TEST DE RÉSILIENCE WACHAP ===')
        )
        
        phone = options['phone']
        region = options['region']
        attempts = options['attempts']
        
        service = WaChapService()
        
        # Afficher la configuration
        self.stdout.write(f"📱 Numéro: {phone}")
        self.stdout.write(f"🌐 Région: {region}")
        self.stdout.write(f"🔄 Tentatives: {attempts}")
        self.stdout.write("")
        
        # Afficher l'état initial des circuit breakers
        self.stdout.write("📊 État initial des Circuit Breakers:")
        for r in ['system', 'chine', 'mali']:
            is_open = circuit_breaker.is_circuit_open(f'wachap_{r}')
            status = self.style.ERROR('OUVERT') if is_open else self.style.SUCCESS('FERMÉ')
            self.stdout.write(f"   WaChap {r.title()}: {status}")
        
        self.stdout.write("")
        
        # Tests d'envoi
        successes = 0
        failures = 0
        
        for i in range(attempts):
            self.stdout.write(f"🧪 Test {i+1}/{attempts}:")
            
            try:
                start_time = time.time()
                success, message, msg_id = service.send_message(
                    phone=phone,
                    message=f'Test résilience #{i+1} - {int(time.time())}',
                    sender_role='system',
                    region=region
                )
                duration = time.time() - start_time
                
                if success:
                    successes += 1
                    self.stdout.write(
                        f"   ✅ Succès ({duration:.2f}s) - ID: {msg_id}"
                    )
                else:
                    failures += 1
                    self.stdout.write(
                        self.style.ERROR(f"   ❌ Échec ({duration:.2f}s): {message}")
                    )
                    
            except Exception as e:
                failures += 1
                self.stdout.write(
                    self.style.ERROR(f"   💥 Exception: {e}")
                )
            
            # Pause entre les tests
            if i < attempts - 1:
                time.sleep(2)
        
        # Résultats finaux
        self.stdout.write("")
        self.stdout.write("📈 RÉSULTATS FINAUX:")
        self.stdout.write(f"   ✅ Succès: {successes}/{attempts}")
        self.stdout.write(f"   ❌ Échecs: {failures}/{attempts}")
        
        success_rate = (successes / attempts) * 100
        if success_rate >= 80:
            status_style = self.style.SUCCESS
        elif success_rate >= 50:
            status_style = self.style.WARNING
        else:
            status_style = self.style.ERROR
            
        self.stdout.write(f"   📊 Taux de réussite: {status_style(f'{success_rate:.1f}%')}")
        
        # État final des circuit breakers
        self.stdout.write("")
        self.stdout.write("📊 État final des Circuit Breakers:")
        for r in ['system', 'chine', 'mali']:
            is_open = circuit_breaker.is_circuit_open(f'wachap_{r}')
            status = self.style.ERROR('OUVERT') if is_open else self.style.SUCCESS('FERMÉ')
            self.stdout.write(f"   WaChap {r.title()}: {status}")
