"""
Service d'alertes administrateur pour TS Air Cargo
Envoie des alertes critiques par email ET WhatsApp en cas de problème système

Cas d'usage:
- Erreurs critiques en production
- Échecs répétés d'OTP
- Problèmes de connexion WhatsApp
- Erreurs de base de données
- Pannes système
"""

import logging
import traceback
from typing import Dict, Any, Optional, List
from datetime import timedelta, datetime
from django.conf import settings
from django.core.mail import send_mail
from django.core.cache import cache
from django.utils import timezone
from .wachap_service import wachap_service

logger = logging.getLogger(__name__)


class AdminAlertsService:
    """
    Service principal pour les alertes administrateur
    """
    
    def __init__(self):
        """Initialise le service avec les configurations admin"""
        self.admin_email = getattr(settings, 'ADMIN_EMAIL', 'sanogo7918@proton.me')
        self.admin_phone = getattr(settings, 'ADMIN_PHONE', '+22373451676')
        self.admin_name = getattr(settings, 'ADMIN_NAME', 'Admin TS Air Cargo')
        
        # Configuration des alertes
        self.alert_enabled = getattr(settings, 'ALERT_SYSTEM_ENABLED', True)
        self.email_enabled = getattr(settings, 'ALERT_EMAIL_ENABLED', True)
        self.whatsapp_enabled = getattr(settings, 'ALERT_WHATSAPP_ENABLED', True)
        
        # Seuils d'alerte
        self.failed_otp_threshold = getattr(settings, 'ALERT_FAILED_OTP_THRESHOLD', 10)
        self.whatsapp_failure_threshold = getattr(settings, 'ALERT_WHATSAPP_FAILURE_THRESHOLD', 5)
        self.db_error_threshold = getattr(settings, 'ALERT_DB_ERROR_THRESHOLD', 3)
    
    def send_critical_alert(self, title: str, message: str, error_details: str = None, 
                           alert_type: str = 'CRITICAL', include_traceback: bool = False) -> Dict[str, bool]:
        """
        Envoie une alerte critique par email ET WhatsApp
        
        Args:
            title: Titre de l'alerte
            message: Message principal
            error_details: Détails techniques de l'erreur
            alert_type: Type d'alerte (CRITICAL, WARNING, ERROR)
            include_traceback: Inclure le traceback Python
            
        Returns:
            dict: Statut d'envoi {'email': bool, 'whatsapp': bool}
        """
        if not self.alert_enabled:
            logger.debug("Système d'alertes désactivé")
            return {'email': False, 'whatsapp': False}
        
        # Vérifier les doublons (pas plus d'une alerte identique par 5 minutes)
        alert_key = f"admin_alert_{hash(f'{title}_{message}')}"
        if cache.get(alert_key):
            logger.debug(f"Alerte déjà envoyée récemment: {title}")
            return {'email': False, 'whatsapp': False}
        
        # Marquer l'alerte comme envoyée
        cache.set(alert_key, True, timeout=300)  # 5 minutes
        
        results = {'email': False, 'whatsapp': False}
        
        # Préparer le contenu complet
        full_message = self._prepare_alert_content(title, message, error_details, alert_type, include_traceback)
        
        # Envoyer par email
        if self.email_enabled:
            results['email'] = self._send_email_alert(title, full_message, alert_type)
        
        # Envoyer par WhatsApp
        if self.whatsapp_enabled:
            results['whatsapp'] = self._send_whatsapp_alert(title, message, alert_type)
        
        # Logger le résultat
        logger.warning(f"Alerte admin envoyée - {title}: Email={results['email']}, WhatsApp={results['whatsapp']}")
        
        return results
    
    def _prepare_alert_content(self, title: str, message: str, error_details: str = None, 
                              alert_type: str = 'CRITICAL', include_traceback: bool = False) -> str:
        """Prépare le contenu complet de l'alerte pour l'email"""
        
        timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')
        
        content = f"""
🚨 ALERTE SYSTÈME TS AIR CARGO - {alert_type}
=============================================

📅 Horodatage: {timestamp}
🏢 Système: TS Air Cargo - Transport International
👤 Destinataire: {self.admin_name}

📋 TITRE: {title}

📝 MESSAGE:
{message}
"""
        
        if error_details:
            content += f"""
🔍 DÉTAILS TECHNIQUES:
{error_details}
"""
        
        if include_traceback:
            try:
                tb = traceback.format_exc()
                if tb and tb != "NoneType: None\n":
                    content += f"""
📊 TRACEBACK PYTHON:
{tb}
"""
            except Exception:
                pass
        
        content += f"""
🔧 ACTIONS RECOMMANDÉES:
- Vérifiez les logs système immédiatement
- Contrôlez l'état des services (base de données, WhatsApp, etc.)
- Si nécessaire, redémarrez les services concernés
- Surveillez les métriques système

⚠️  Cette alerte est automatique. Intervention requise si problème persistant.

--
TS Air Cargo - Système d'Alertes Automatiques
Email: {self.admin_email}
Téléphone: {self.admin_phone}
"""
        return content
    
    def _send_email_alert(self, title: str, full_message: str, alert_type: str) -> bool:
        """Envoie l'alerte par email"""
        try:
            subject = f"🚨 [{alert_type}] TS Air Cargo - {title}"
            
            send_mail(
                subject=subject,
                message=full_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@ts-aircargo.com'),
                recipient_list=[self.admin_email],
                fail_silently=False
            )
            
            logger.info(f"Alerte email envoyée à {self.admin_email}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur envoi email alerte: {str(e)}")
            return False
    
    def _send_whatsapp_alert(self, title: str, message: str, alert_type: str) -> bool:
        """Envoie l'alerte par WhatsApp via l'instance système"""
        try:
            # Préparer message WhatsApp court et efficace
            timestamp = timezone.now().strftime('%H:%M')
            
            whatsapp_message = f"""🚨 ALERTE TS AIR CARGO
{alert_type} - {timestamp}

📋 {title}

{message}

👤 Intervention requise
📧 Détails par email

⚡ Alerte automatique"""
            
            # Envoyer via l'instance système
            success, msg, msg_id = wachap_service.send_message(
                phone=self.admin_phone,
                message=whatsapp_message,
                sender_role='system',
                region='system'
            )
            
            if success:
                logger.info(f"Alerte WhatsApp envoyée à {self.admin_phone} - ID: {msg_id}")
                return True
            else:
                logger.error(f"Erreur envoi WhatsApp alerte: {msg}")
                return False
                
        except Exception as e:
            logger.error(f"Exception envoi WhatsApp alerte: {str(e)}")
            return False
    
    def alert_failed_otp_threshold(self, failed_count: int, time_period: str = "1 heure"):
        """Alerte pour trop d'échecs OTP"""
        self.send_critical_alert(
            title="Échecs OTP répétés détectés",
            message=f"Nombre d'échecs OTP: {failed_count} en {time_period}. Seuil: {self.failed_otp_threshold}",
            alert_type="WARNING"
        )
    
    def alert_whatsapp_instance_down(self, instance_name: str, consecutive_failures: int):
        """Alerte pour instance WhatsApp hors service"""
        self.send_critical_alert(
            title=f"Instance WhatsApp {instance_name} hors service",
            message=f"Échecs consécutifs: {consecutive_failures}. L'instance semble déconnectée.",
            alert_type="CRITICAL"
        )
    
    def alert_database_error(self, error_message: str, query_info: str = None):
        """Alerte pour erreur de base de données"""
        details = f"Erreur: {error_message}"
        if query_info:
            details += f"\nRequête: {query_info}"
        
        self.send_critical_alert(
            title="Erreur Base de Données",
            message="Erreur critique détectée dans la base de données",
            error_details=details,
            alert_type="CRITICAL",
            include_traceback=True
        )
    
    def alert_system_exception(self, exception: Exception, context: str = None):
        """Alerte pour exception système non gérée"""
        error_details = f"Exception: {type(exception).__name__}: {str(exception)}"
        if context:
            error_details += f"\nContexte: {context}"
        
        self.send_critical_alert(
            title="Exception Système Non Gérée",
            message="Exception critique interceptée par le système d'alertes",
            error_details=error_details,
            alert_type="CRITICAL",
            include_traceback=True
        )
    
    def alert_service_startup(self, service_name: str, status: str = "DÉMARRÉ"):
        """Alerte informative pour démarrage de service"""
        self.send_critical_alert(
            title=f"Service {service_name} {status}",
            message=f"Le service {service_name} a été {status.lower()} avec succès.",
            alert_type="INFO"
        )
    
    def test_alert_system(self) -> Dict[str, bool]:
        """Teste le système d'alertes"""
        return self.send_critical_alert(
            title="Test du Système d'Alertes",
            message="Ceci est un test automatique du système d'alertes administrateur.",
            error_details="Configuration: Email activé, WhatsApp activé",
            alert_type="TEST"
        )
    
    def get_alert_stats(self) -> Dict[str, Any]:
        """Statistiques du système d'alertes"""
        return {
            'enabled': self.alert_enabled,
            'email_enabled': self.email_enabled,
            'whatsapp_enabled': self.whatsapp_enabled,
            'admin_email': self.admin_email,
            'admin_phone': self.admin_phone,
            'thresholds': {
                'failed_otp': self.failed_otp_threshold,
                'whatsapp_failures': self.whatsapp_failure_threshold,
                'db_errors': self.db_error_threshold
            }
        }


# Instance globale du service
admin_alerts = AdminAlertsService()


# Décorateur pour capturer automatiquement les exceptions
def alert_on_exception(alert_title: str = None, context: str = None):
    """
    Décorateur pour envoyer automatiquement une alerte en cas d'exception
    
    Usage:
    @alert_on_exception("Erreur dans la fonction critique", "Module de paiement")
    def ma_fonction_critique():
        # code qui peut lever une exception
        pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                title = alert_title or f"Exception dans {func.__name__}"
                admin_alerts.alert_system_exception(e, context or f"Fonction: {func.__name__}")
                raise  # Re-lever l'exception après l'alerte
        return wrapper
    return decorator


# Fonctions utilitaires
def send_admin_alert(title: str, message: str, alert_type: str = 'INFO') -> Dict[str, bool]:
    """
    Fonction utilitaire pour envoyer rapidement une alerte admin
    
    Args:
        title: Titre de l'alerte
        message: Message principal
        alert_type: Type d'alerte
        
    Returns:
        dict: Résultats d'envoi
    """
    return admin_alerts.send_critical_alert(title, message, alert_type=alert_type)


def test_admin_alerts() -> Dict[str, bool]:
    """Teste le système d'alertes admin"""
    return admin_alerts.test_alert_system()
