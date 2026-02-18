"""
Commande Django pour le monitoring automatique des instances WaChap
Usage: python manage.py monitor_wachap [options]
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from notifications_app.wachap_monitoring import wachap_monitor, get_wachap_alert_history
import time
import signal
import sys


class Command(BaseCommand):
    help = """
    Surveille l'état des instances WaChap et envoie des alertes automatiques
    
    Exemples:
    python manage.py monitor_wachap --once          # Une vérification unique
    python manage.py monitor_wachap --continuous    # Monitoring continu
    python manage.py monitor_wachap --history       # Afficher l'historique
    python manage.py monitor_wachap --status        # Afficher le statut actuel
    """
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Effectuer une seule vérification puis quitter',
        )
        
        parser.add_argument(
            '--continuous',
            action='store_true',
            help='Monitoring continu avec vérifications régulières',
        )
        
        parser.add_argument(
            '--interval',
            type=int,
            default=15,
            help='Intervalle en minutes entre les vérifications (défaut: 15)',
        )
        
        parser.add_argument(
            '--history',
            action='store_true',
            help='Afficher l\'historique des alertes',
        )
        
        parser.add_argument(
            '--status',
            action='store_true',
            help='Afficher le statut du dernier monitoring',
        )
        
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='Mode silencieux (moins de sortie console)',
        )
    
    def handle(self, *args, **options):
        """Point d'entrée principal de la commande"""
        
        if options['history']:
            self.show_alert_history()
            return
        
        if options['status']:
            self.show_monitoring_status()
            return
        
        if options['continuous']:
            self.run_continuous_monitoring(options)
        else:
            # Une seule vérification par défaut
            self.run_single_check(options)
    
    def run_single_check(self, options):
        """Effectue une seule vérification"""
        if not options['quiet']:
            self.stdout.write(
                self.style.SUCCESS('🔍 Lancement d\'une vérification unique...')
            )
        
        try:
            status = wachap_monitor.run_monitoring_check()
            
            if not options['quiet']:
                self.display_check_results(status)
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Erreur lors de la vérification: {e}')
            )
            raise CommandError(f'Monitoring failed: {e}')
    
    def run_continuous_monitoring(self, options):
        """Lance le monitoring en continu"""
        interval_minutes = options['interval']
        interval_seconds = interval_minutes * 60
        
        if not options['quiet']:
            self.stdout.write(
                self.style.SUCCESS(
                    f'🚀 Démarrage monitoring continu WaChap (intervalle: {interval_minutes}min)'
                )
            )
            self.stdout.write('Appuyez sur Ctrl+C pour arrêter...')
        
        # Gestion propre de l'arrêt avec Ctrl+C
        def signal_handler(sig, frame):
            self.stdout.write(
                self.style.WARNING('\n🛑 Arrêt du monitoring demandé...')
            )
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        try:
            while True:
                check_start = timezone.now()
                
                if not options['quiet']:
                    self.stdout.write(
                        f'\n⏰ {check_start.strftime("%d/%m/%Y %H:%M:%S")} - Vérification en cours...'
                    )
                
                try:
                    status = wachap_monitor.run_monitoring_check()
                    
                    if not options['quiet']:
                        self.display_check_results(status, compact=True)
                    
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'❌ Erreur lors de la vérification: {e}')
                    )
                
                # Attendre l'intervalle spécifié
                if not options['quiet']:
                    next_check = check_start + timezone.timedelta(minutes=interval_minutes)
                    self.stdout.write(
                        f'😴 Prochaine vérification: {next_check.strftime("%H:%M:%S")}'
                    )
                
                time.sleep(interval_seconds)
                
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING('\n🛑 Monitoring arrêté par l\'utilisateur')
            )
    
    def display_check_results(self, status, compact=False):
        """Affiche les résultats d'une vérification"""
        if not status:
            self.stdout.write(self.style.ERROR('❌ Aucun résultat de monitoring'))
            return
        
        connected_count = 0
        total_count = len(status)
        disconnected_instances = []
        
        for region, region_status in status.items():
            if region_status.get('connected'):
                connected_count += 1
                if not compact:
                    self.stdout.write(
                        self.style.SUCCESS(f'✅ {region.upper()}: Connectée')
                    )
            else:
                disconnected_instances.append((region, region_status))
                error = region_status.get('error', 'Erreur inconnue')
                if not compact:
                    self.stdout.write(
                        self.style.ERROR(f'❌ {region.upper()}: Déconnectée - {error}')
                    )
        
        # Résumé
        if disconnected_instances:
            summary = f'🚨 {connected_count}/{total_count} instances connectées'
            self.stdout.write(self.style.ERROR(summary))
            if compact:
                disconnected_list = [r for r, s in disconnected_instances]
                self.stdout.write(f'   Déconnectées: {disconnected_list}')
        else:
            summary = f'✅ {connected_count}/{total_count} instances connectées - Tout fonctionne'
            self.stdout.write(self.style.SUCCESS(summary))
    
    def show_alert_history(self):
        """Affiche l'historique des alertes"""
        self.stdout.write(self.style.SUCCESS('📋 HISTORIQUE DES ALERTES WACHAP'))
        self.stdout.write('=' * 50)
        
        history = get_wachap_alert_history()
        
        if not history:
            self.stdout.write('Aucune alerte enregistrée.')
            return
        
        for alert in reversed(history[-10:]):  # 10 dernières alertes
            timestamp = alert.get('timestamp', 'N/A')
            region = alert.get('region', 'N/A')
            instance_name = alert.get('instance_name', 'N/A')
            error = alert.get('error', 'N/A')
            email_sent = '✅' if alert.get('email_sent') else '❌'
            whatsapp_sent = '✅' if alert.get('whatsapp_sent') else '❌'
            
            try:
                dt = timezone.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                formatted_time = dt.strftime('%d/%m/%Y %H:%M:%S')
            except:
                formatted_time = timestamp
            
            self.stdout.write(f'\n🚨 {formatted_time}')
            self.stdout.write(f'   Instance: {instance_name} ({region.upper()})')
            self.stdout.write(f'   Erreur: {error}')
            self.stdout.write(f'   Email: {email_sent} | WhatsApp: {whatsapp_sent}')
        
        self.stdout.write(f'\nTotal des alertes: {len(history)}')
    
    def show_monitoring_status(self):
        """Affiche le statut du dernier monitoring"""
        self.stdout.write(self.style.SUCCESS('📊 STATUT DU MONITORING WACHAP'))
        self.stdout.write('=' * 50)
        
        status = wachap_monitor.get_monitoring_status()
        
        if not status:
            self.stdout.write('Aucun monitoring effectué récemment.')
            self.stdout.write('Lancez: python manage.py monitor_wachap --once')
            return
        
        timestamp = status.get('timestamp', 'N/A')
        connected_count = status.get('connected_count', 0)
        total_instances = status.get('total_instances', 0)
        disconnected = status.get('disconnected_instances', [])
        
        try:
            dt = timezone.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            formatted_time = dt.strftime('%d/%m/%Y %H:%M:%S')
        except:
            formatted_time = timestamp
        
        self.stdout.write(f'Dernier check: {formatted_time}')
        self.stdout.write(f'Instances connectées: {connected_count}/{total_instances}')
        
        if disconnected:
            self.stdout.write(f'Instances déconnectées: {disconnected}')
            self.stdout.write(self.style.ERROR('⚠️ Action requise: reconnectez les instances déconnectées'))
        else:
            self.stdout.write(self.style.SUCCESS('✅ Toutes les instances sont connectées'))
        
        # Détails par instance
        all_status = status.get('all_status', {})
        if all_status:
            self.stdout.write('\nDétails par instance:')
            for region, region_status in all_status.items():
                connected = region_status.get('connected', False)
                error = region_status.get('error', 'N/A')
                icon = '✅' if connected else '❌'
                self.stdout.write(f'  {icon} {region.upper()}: {error if not connected else "OK"}')
