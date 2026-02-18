"""
Commande Django pour relancer automatiquement les notifications échouées
Usage: python manage.py retry_failed_notifications [--max-retries=10] [--dry-run]
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from notifications_app.models import Notification
from notifications_app.tasks import send_individual_notification
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Relance automatiquement les notifications échouées qui sont prêtes pour un nouveau retry'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--max-retries',
            type=int,
            default=10,
            help='Nombre maximum de tentatives avant abandon définitif (défaut: 10)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mode simulation : affiche les notifications à relancer sans les envoyer'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Nombre maximum de notifications à traiter par exécution (défaut: 100)'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Affichage détaillé des opérations'
        )
    
    def handle(self, *args, **options):
        max_retries = options['max_retries']
        dry_run = options['dry_run']
        limit = options['limit']
        verbose = options['verbose']
        
        self.stdout.write(
            self.style.HTTP_INFO(
                f"\n{'='*60}\n"
                f"🔄 RETRY NOTIFICATIONS ÉCHOUÉES\n"
                f"{'='*60}\n"
            )
        )
        
        if dry_run:
            self.stdout.write(self.style.WARNING("⚠️  MODE SIMULATION (DRY-RUN) - Aucun envoi réel\n"))
        
        # Récupérer les notifications éligibles au retry
        now = timezone.now()
        
        notifications_to_retry = Notification.objects.filter(
            Q(statut='echec') &  # Seulement échecs temporaires
            Q(prochaine_tentative__lte=now) &  # Délai de retry écoulé
            Q(nombre_tentatives__lt=max_retries)  # Pas encore au max
        ).select_related('destinataire').order_by('prochaine_tentative')[:limit]
        
        total_count = notifications_to_retry.count()
        
        if total_count == 0:
            self.stdout.write(
                self.style.SUCCESS("✅ Aucune notification à relancer pour le moment\n")
            )
            return
        
        self.stdout.write(
            self.style.HTTP_INFO(
                f"📊 Notifications trouvées : {total_count}\n"
                f"📅 Date/Heure actuelle : {now.strftime('%d/%m/%Y %H:%M:%S')}\n"
                f"🔢 Limite de tentatives : {max_retries}\n"
                f"{'='*60}\n"
            )
        )
        
        # Statistiques
        stats = {
            'total': total_count,
            'queued': 0,
            'skipped': 0,
            'errors': 0
        }
        
        # Traiter chaque notification
        for notification in notifications_to_retry:
            try:
                tentative_num = notification.nombre_tentatives + 1
                prochaine = notification.prochaine_tentative.strftime('%d/%m/%Y %H:%M')
                
                if verbose or dry_run:
                    self.stdout.write(
                        f"\n📧 Notification #{notification.id}\n"
                        f"   Destinataire: {notification.destinataire.get_full_name()} "
                        f"({notification.destinataire.telephone})\n"
                        f"   Tentatives: {notification.nombre_tentatives}/{max_retries}\n"
                        f"   Prochaine tentative prévue: {prochaine}\n"
                        f"   Catégorie: {notification.get_categorie_display()}\n"
                        f"   Dernière erreur: {notification.erreur_envoi[:100] if notification.erreur_envoi else 'N/A'}\n"
                    )
                
                if not dry_run:
                    # Lancer la tâche Celery asynchrone
                    send_individual_notification.delay(notification.id)
                    stats['queued'] += 1
                    
                    if verbose:
                        self.stdout.write(
                            self.style.SUCCESS(f"   ✅ Mise en file d'attente (tentative {tentative_num})\n")
                        )
                else:
                    stats['queued'] += 1
                    self.stdout.write(
                        self.style.WARNING(f"   🔸 [DRY-RUN] Serait mise en file (tentative {tentative_num})\n")
                    )
                    
            except Exception as e:
                stats['errors'] += 1
                self.stdout.write(
                    self.style.ERROR(f"   ❌ Erreur : {str(e)}\n")
                )
                logger.error(f"Erreur retry notification {notification.id}: {str(e)}")
        
        # Afficher le résumé
        self.stdout.write(
            self.style.HTTP_INFO(
                f"\n{'='*60}\n"
                f"📊 RÉSUMÉ DE L'EXÉCUTION\n"
                f"{'='*60}\n"
            )
        )
        
        self.stdout.write(f"Total traité       : {stats['total']}\n")
        
        if dry_run:
            self.stdout.write(self.style.WARNING(f"Seraient relancées : {stats['queued']}\n"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Mises en file      : {stats['queued']}\n"))
        
        if stats['errors'] > 0:
            self.stdout.write(self.style.ERROR(f"Erreurs            : {stats['errors']}\n"))
        
        self.stdout.write(f"\n{'='*60}\n")
        
        # Vérifier les notifications abandonnées (max retries atteints)
        abandoned = Notification.objects.filter(
            statut='echec',
            nombre_tentatives__gte=max_retries
        ).count()
        
        if abandoned > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"\n⚠️  ATTENTION : {abandoned} notification(s) ont atteint le nombre "
                    f"maximum de tentatives ({max_retries})\n"
                    f"   Recommandation : Vérifier ces notifications et les traiter manuellement\n"
                    f"   ou les annuler via le dashboard admin.\n"
                )
            )
        
        # Vérifier les échecs permanents
        permanent_failures = Notification.objects.filter(statut='echec_permanent').count()
        
        if permanent_failures > 0:
            self.stdout.write(
                self.style.ERROR(
                    f"\n🚨 {permanent_failures} notification(s) en échec permanent nécessitent "
                    f"une intervention manuelle\n"
                )
            )
        
        if not dry_run and stats['queued'] > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✅ {stats['queued']} notification(s) mise(s) en file d'attente "
                    f"pour envoi asynchrone\n"
                )
            )
