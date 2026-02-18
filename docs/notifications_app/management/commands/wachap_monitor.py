"""
Commande Django pour le monitoring WaChap
Usage: python manage.py wachap_monitor [options]
"""

from django.core.management.base import BaseCommand, CommandError
import json
import time
from notifications_app.monitoring import wachap_monitor, log_wachap_activity


class Command(BaseCommand):
    help = 'Commandes de monitoring pour WaChap'

    def add_arguments(self, parser):
        parser.add_argument(
            '--action',
            type=str,
            choices=['status', 'metrics', 'report', 'reset', 'watch'],
            default='status',
            help='Action à effectuer'
        )
        parser.add_argument(
            '--instance',
            type=str,
            choices=['chine', 'mali'],
            help='Instance spécifique (optionnel)'
        )
        parser.add_argument(
            '--watch-interval',
            type=int,
            default=30,
            help='Intervalle de surveillance en secondes (défaut: 30)'
        )
        parser.add_argument(
            '--export-json',
            action='store_true',
            help='Exporter les données en format JSON'
        )

    def handle(self, *args, **options):
        action = options['action']
        
        if action == 'status':
            self.show_health_status(options)
        elif action == 'metrics':
            self.show_metrics(options)
        elif action == 'report':
            self.generate_report(options)
        elif action == 'reset':
            self.reset_metrics(options)
        elif action == 'watch':
            self.watch_metrics(options)

    def show_health_status(self, options):
        """Affiche l'état de santé du système"""
        self.stdout.write("🏥 ÉTAT DE SANTÉ WACHAP")
        self.stdout.write("=" * 50)
        
        health = wachap_monitor.get_health_status()
        
        # Statut global
        status_emoji = {
            'healthy': '✅',
            'degraded': '⚠️',
            'unhealthy': '🚨'
        }
        
        overall_emoji = status_emoji.get(health['overall_status'], '❓')
        self.stdout.write(f"{overall_emoji} Statut global: {health['overall_status'].upper()}")
        self.stdout.write(f"📅 Timestamp: {health['timestamp']}")
        self.stdout.write()
        
        # Détails par instance
        for instance, data in health['instances'].items():
            instance_emoji = status_emoji.get(data['status'], '❓')
            self.stdout.write(f"{instance_emoji} Instance {instance.title()}:")
            self.stdout.write(f"   📊 Taux de succès: {data['success_rate']:.1f}%")
            self.stdout.write(f"   ⏱️  Temps de réponse moyen: {data['avg_response_time']:.0f}ms")
            self.stdout.write(f"   📨 Messages total: {data['total_messages']}")
            
            if data['issues']:
                self.stdout.write(f"   ⚠️  Problèmes:")
                for issue in data['issues']:
                    self.stdout.write(f"      • {issue}")
            else:
                self.stdout.write(f"   ✅ Aucun problème détecté")
            
            self.stdout.write()

        if options['export_json']:
            json_output = json.dumps(health, indent=2, ensure_ascii=False)
            self.stdout.write("📄 JSON Export:")
            self.stdout.write(json_output)

    def show_metrics(self, options):
        """Affiche les métriques détaillées"""
        self.stdout.write("📊 MÉTRIQUES WACHAP")
        self.stdout.write("=" * 50)
        
        instance = options.get('instance')
        metrics = wachap_monitor.get_metrics(instance)
        
        for inst, metric in metrics.items():
            self.stdout.write(f"🔧 Instance {inst.title()}:")
            self.stdout.write(f"   📈 Messages total: {metric.total_count}")
            self.stdout.write(f"   ✅ Succès: {metric.success_count}")
            self.stdout.write(f"   ❌ Échecs: {metric.error_count}")
            self.stdout.write(f"   📊 Taux de succès: {metric.success_rate:.2f}%")
            self.stdout.write(f"   ⏱️  Temps de réponse moyen: {metric.avg_response_time:.2f}ms")
            
            if metric.error_types:
                self.stdout.write(f"   🚨 Types d'erreurs:")
                for error_type, count in metric.error_types.items():
                    self.stdout.write(f"      • {error_type}: {count}")
            
            self.stdout.write()

        if options['export_json']:
            # Convertir les métriques en format JSON sérialisable
            json_data = {}
            for inst, metric in metrics.items():
                json_data[inst] = {
                    'total_count': metric.total_count,
                    'success_count': metric.success_count,
                    'error_count': metric.error_count,
                    'success_rate': metric.success_rate,
                    'avg_response_time': metric.avg_response_time,
                    'error_types': dict(metric.error_types)
                }
            
            json_output = json.dumps(json_data, indent=2, ensure_ascii=False)
            self.stdout.write("📄 JSON Export:")
            self.stdout.write(json_output)

    def generate_report(self, options):
        """Génère un rapport complet"""
        self.stdout.write("📋 RAPPORT COMPLET WACHAP")
        self.stdout.write("=" * 50)
        
        report = wachap_monitor.export_metrics_report()
        
        self.stdout.write(f"📅 Rapport généré: {report['report_generated']}")
        self.stdout.write(f"⏰ Période: {report['period_hours']} heures")
        self.stdout.write(f"🏥 Statut global: {report['health_status']['overall_status'].upper()}")
        self.stdout.write()
        
        # Métriques détaillées
        for instance, data in report['detailed_metrics'].items():
            self.stdout.write(f"🔧 Instance {instance.title()}:")
            self.stdout.write(f"   📊 Performance: {data['performance_grade']}")
            self.stdout.write(f"   📈 Messages total: {data['total_messages']}")
            self.stdout.write(f"   ✅ Succès: {data['successful_messages']}")
            self.stdout.write(f"   ❌ Échecs: {data['failed_messages']}")
            self.stdout.write(f"   📊 Taux de succès: {data['success_rate']}")
            self.stdout.write(f"   ⏱️  Temps de réponse: {data['average_response_time']}")
            
            if data['error_breakdown']:
                self.stdout.write(f"   🚨 Répartition des erreurs:")
                for error_type, count in data['error_breakdown'].items():
                    self.stdout.write(f"      • {error_type}: {count}")
            
            self.stdout.write()

        if options['export_json']:
            json_output = json.dumps(report, indent=2, ensure_ascii=False)
            self.stdout.write("📄 JSON Export:")
            self.stdout.write(json_output)

    def reset_metrics(self, options):
        """Remet à zéro les métriques"""
        instance = options.get('instance')
        
        if instance:
            confirm_msg = f"Êtes-vous sûr de vouloir réinitialiser les métriques de l'instance {instance}?"
        else:
            confirm_msg = "Êtes-vous sûr de vouloir réinitialiser TOUTES les métriques?"
        
        # En mode non-interactif, on assume que c'est voulu
        confirm = input(f"{confirm_msg} (y/N): ").lower().strip()
        
        if confirm in ['y', 'yes', 'oui']:
            wachap_monitor.reset_metrics(instance)
            
            if instance:
                self.stdout.write(self.style.SUCCESS(f"✅ Métriques réinitialisées pour l'instance {instance}"))
            else:
                self.stdout.write(self.style.SUCCESS("✅ Toutes les métriques ont été réinitialisées"))
        else:
            self.stdout.write("❌ Opération annulée")

    def watch_metrics(self, options):
        """Mode surveillance continue"""
        interval = options['watch_interval']
        instance = options.get('instance')
        
        self.stdout.write(f"👁️  MODE SURVEILLANCE WACHAP")
        self.stdout.write(f"⏰ Intervalle: {interval}s")
        if instance:
            self.stdout.write(f"🔧 Instance: {instance}")
        self.stdout.write("Appuyez sur Ctrl+C pour arrêter")
        self.stdout.write("=" * 50)
        
        try:
            while True:
                # Effacer l'écran (fonctionne sur la plupart des terminaux)
                self.stdout.write('\033[2J\033[H')
                
                # Afficher l'heure actuelle
                from django.utils import timezone
                now = timezone.now().strftime('%H:%M:%S')
                self.stdout.write(f"🕐 Dernière mise à jour: {now}")
                self.stdout.write()
                
                # Afficher le statut de santé
                health = wachap_monitor.get_health_status()
                
                status_emoji = {
                    'healthy': '✅',
                    'degraded': '⚠️',
                    'unhealthy': '🚨'
                }
                
                overall_emoji = status_emoji.get(health['overall_status'], '❓')
                self.stdout.write(f"{overall_emoji} Statut: {health['overall_status'].upper()}")
                self.stdout.write()
                
                # Métriques en temps réel
                metrics = wachap_monitor.get_metrics(instance)
                for inst, metric in metrics.items():
                    self.stdout.write(f"🔧 {inst.title()}: {metric.total_count} msgs | {metric.success_rate:.1f}% | {metric.avg_response_time:.0f}ms")
                
                self.stdout.write()
                self.stdout.write(f"⏳ Prochaine mise à jour dans {interval}s...")
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self.stdout.write()
            self.stdout.write("👋 Surveillance arrêtée par l'utilisateur")

    def style_text(self, text, style=''):
        """Applique un style au texte si disponible"""
        if hasattr(self.style, style.upper()):
            return getattr(self.style, style.upper())(text)
        return text
