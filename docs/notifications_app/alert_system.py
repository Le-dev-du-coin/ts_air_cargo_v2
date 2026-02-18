"""
Système d'alertes pour les notifications WhatsApp
Alerte les admins en cas de défaillance critique du système de notifications
"""

import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Count, Q
from .models import Notification

logger = logging.getLogger(__name__)


class NotificationAlertSystem:
    """
    Système d'alertes pour surveiller la santé des notifications
    """
    
    # Seuils d'alerte
    FAILURE_RATE_THRESHOLD = 50  # % d'échecs sur une période
    CRITICAL_FAILURES_THRESHOLD = 20  # Nombre d'échecs en 1h
    PERMANENT_FAILURES_THRESHOLD = 5  # Échecs permanents avant alerte
    
    # Délais de cooldown pour éviter spam d'alertes
    ALERT_COOLDOWN_MINUTES = 60  # Attendre 1h entre alertes similaires
    
    @classmethod
    def check_and_alert(cls):
        """
        Vérifie l'état des notifications et envoie des alertes si nécessaire
        """
        try:
            # Vérifier les échecs récents
            cls._check_recent_failures()
            
            # Vérifier les échecs permanents
            cls._check_permanent_failures()
            
            # Vérifier le taux global d'échecs
            cls._check_failure_rate()
            
        except Exception as e:
            logger.error(f"Erreur lors de la vérification des alertes notifications: {str(e)}")
    
    @classmethod
    def _check_recent_failures(cls):
        """Vérifie les échecs récents (dernière heure)"""
        one_hour_ago = timezone.now() - timedelta(hours=1)
        
        recent_failures = Notification.objects.filter(
            statut='echec',
            date_creation__gte=one_hour_ago
        ).count()
        
        if recent_failures >= cls.CRITICAL_FAILURES_THRESHOLD:
            # Vérifier le cooldown
            cache_key = 'notif_alert_recent_failures'
            if not cache.get(cache_key):
                cls._send_alert(
                    title='🚨 Alerte: Nombreux échecs de notifications',
                    message=f"{recent_failures} notifications ont échoué dans la dernière heure.\n\n"
                            f"Cela peut indiquer un problème avec l'API WaChap.\n\n"
                            f"Action recommandée:\n"
                            f"- Vérifier l'état de l'API WaChap\n"
                            f"- Vérifier les logs pour identifier la cause\n"
                            f"- Vérifier que l'abonnement WaChap est actif",
                    level='critical'
                )
                # Définir cooldown
                cache.set(cache_key, True, cls.ALERT_COOLDOWN_MINUTES * 60)
    
    @classmethod
    def _check_permanent_failures(cls):
        """Vérifie les échecs permanents récents"""
        one_day_ago = timezone.now() - timedelta(days=1)
        
        permanent_failures = Notification.objects.filter(
            statut='echec_permanent',
            date_creation__gte=one_day_ago
        ).count()
        
        if permanent_failures >= cls.PERMANENT_FAILURES_THRESHOLD:
            cache_key = 'notif_alert_permanent_failures'
            if not cache.get(cache_key):
                # Analyser les types d'erreurs
                error_analysis = cls._analyze_permanent_errors()
                
                cls._send_alert(
                    title='⚠️ Alerte: Échecs permanents de notifications',
                    message=f"{permanent_failures} notifications sont en échec permanent (24h).\n\n"
                            f"Analyse des erreurs:\n{error_analysis}\n\n"
                            f"Action requise:\n"
                            f"- Vérifier les logs d'erreurs\n"
                            f"- Corriger les problèmes identifiés\n"
                            f"- Annuler les notifications obsolètes via le dashboard",
                    level='warning'
                )
                cache.set(cache_key, True, cls.ALERT_COOLDOWN_MINUTES * 60)
    
    @classmethod
    def _check_failure_rate(cls):
        """Vérifie le taux global d'échecs"""
        last_24h = timezone.now() - timedelta(days=1)
        
        total_notifications = Notification.objects.filter(
            date_creation__gte=last_24h
        ).count()
        
        if total_notifications < 10:
            # Pas assez de données pour calculer un taux significatif
            return
        
        failed_notifications = Notification.objects.filter(
            date_creation__gte=last_24h,
            statut__in=['echec', 'echec_permanent']
        ).count()
        
        failure_rate = (failed_notifications / total_notifications) * 100
        
        if failure_rate >= cls.FAILURE_RATE_THRESHOLD:
            cache_key = 'notif_alert_failure_rate'
            if not cache.get(cache_key):
                cls._send_alert(
                    title='📉 Alerte: Taux d\'échec élevé',
                    message=f"Taux d'échec des notifications: {failure_rate:.1f}% (24h)\n\n"
                            f"Total: {total_notifications} | Échecs: {failed_notifications}\n\n"
                            f"Un taux d'échec supérieur à {cls.FAILURE_RATE_THRESHOLD}% "
                            f"indique un problème système.\n\n"
                            f"Action recommandée:\n"
                            f"- Vérifier la configuration WaChap\n"
                            f"- Vérifier la connectivité réseau\n"
                            f"- Consulter le dashboard de monitoring",
                    level='critical'
                )
                cache.set(cache_key, True, cls.ALERT_COOLDOWN_MINUTES * 60 * 2)  # 2h cooldown
    
    @classmethod
    def _analyze_permanent_errors(cls):
        """Analyse les types d'erreurs permanentes"""
        one_day_ago = timezone.now() - timedelta(days=1)
        
        # Compter les erreurs par type (basé sur le contenu du message d'erreur)
        errors = Notification.objects.filter(
            statut='echec_permanent',
            date_creation__gte=one_day_ago
        ).values_list('erreur_envoi', flat=True)
        
        error_types = {}
        for error_msg in errors:
            if not error_msg:
                continue
            
            # Extraire le type d'erreur
            if 'http_401' in error_msg.lower() or 'unauthorized' in error_msg.lower():
                error_types['Autorisation (401/403)'] = error_types.get('Autorisation (401/403)', 0) + 1
            elif 'http_400' in error_msg.lower() or 'invalid' in error_msg.lower():
                error_types['Numéro invalide (400)'] = error_types.get('Numéro invalide (400)', 0) + 1
            elif 'config' in error_msg.lower():
                error_types['Configuration'] = error_types.get('Configuration', 0) + 1
            else:
                error_types['Autres'] = error_types.get('Autres', 0) + 1
        
        # Formater l'analyse
        if error_types:
            analysis = "\n".join([f"  - {k}: {v}" for k, v in error_types.items()])
        else:
            analysis = "  - Aucune analyse disponible"
        
        return analysis
    
    @classmethod
    def _send_alert(cls, title: str, message: str, level: str = 'warning'):
        """
        Envoie une alerte aux administrateurs
        
        Args:
            title: Titre de l'alerte
            message: Contenu détaillé
            level: 'info', 'warning', 'critical'
        """
        logger.warning(f"ALERTE NOTIFICATION: {title}\n{message}")
        
        # 1. Envoyer par email si configuré
        if settings.ALERT_EMAIL_ENABLED:
            cls._send_email_alert(title, message)
        
        # 2. Envoyer par WhatsApp si configuré et critique
        if settings.ALERT_WHATSAPP_ENABLED and level == 'critical':
            cls._send_whatsapp_alert(title, message)
    
    @classmethod
    def _send_email_alert(cls, title: str, message: str):
        """Envoie une alerte par email"""
        try:
            admin_email = settings.ADMIN_EMAIL
            if not admin_email:
                logger.warning("ADMIN_EMAIL non configuré, impossible d'envoyer l'alerte email")
                return
            
            send_mail(
                subject=f"[TS Air Cargo] {title}",
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[admin_email],
                fail_silently=False,
            )
            logger.info(f"✅ Alerte email envoyée à {admin_email}")
        except Exception as e:
            logger.error(f"Erreur envoi alerte email: {str(e)}")
    
    @classmethod
    def _send_whatsapp_alert(cls, title: str, message: str):
        """Envoie une alerte par WhatsApp"""
        try:
            admin_phone = settings.ADMIN_PHONE
            if not admin_phone:
                logger.warning("ADMIN_PHONE non configuré, impossible d'envoyer l'alerte WhatsApp")
                return
            
            from .wachap_service import wachap_service
            
            alert_message = f"🚨 {title}\n\n{message}\n\n⏰ {timezone.now().strftime('%d/%m/%Y %H:%M')}"
            
            success, result, msg_id = wachap_service.send_message_with_type(
                phone=admin_phone,
                message=alert_message,
                message_type='alert',
                sender_role='system'
            )
            
            if success:
                logger.info(f"✅ Alerte WhatsApp envoyée à {admin_phone}")
            else:
                logger.error(f"❌ Échec envoi alerte WhatsApp: {result}")
                
        except Exception as e:
            logger.error(f"Erreur envoi alerte WhatsApp: {str(e)}")


def check_notification_health():
    """
    Fonction utilitaire pour vérifier l'état de santé des notifications
    Peut être appelée par une tâche Celery ou une commande Django
    """
    NotificationAlertSystem.check_and_alert()
