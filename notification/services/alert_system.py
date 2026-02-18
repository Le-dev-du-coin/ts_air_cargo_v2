import logging
import traceback
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from ..models import Notification, ConfigurationNotification
from .wachap_service import wachap_service

logger = logging.getLogger(__name__)


class AlertSystem:
    """
    Système unifié d'alertes (Admin + Développeur)
    Fusionne les anciennes fonctionnalités de admin_alerts et alert_system
    """

    FAILURE_RATE_THRESHOLD = 50  # %
    ALERT_COOLDOWN_MINUTES = 60

    def _get_config(self):
        return ConfigurationNotification.get_solo()

    def check_and_alert(self):
        """Vérifie la santé du système et alerte si nécessaire"""
        try:
            self._check_failure_rate()
            # Autres vérifications possibles (DB, Disque, etc.)
        except Exception as e:
            logger.error(f"Erreur check_and_alert: {e}")

    def _check_failure_rate(self):
        """Vérifie le taux d'échec global des notifications (24h)"""
        last_24h = timezone.now() - timedelta(days=1)

        total = Notification.objects.filter(date_creation__gte=last_24h).count()
        if total < 10:
            return  # Pas assez de données

        failed = Notification.objects.filter(
            date_creation__gte=last_24h, statut__in=["echec", "echec_permanent"]
        ).count()

        rate = (failed / total) * 100

        if rate >= self.FAILURE_RATE_THRESHOLD:
            cache_key = "alert_failure_rate"
            if not cache.get(cache_key):
                self.send_critical_alert(
                    title="Taux d'échec élevé",
                    message=f"Taux d'échec: {rate:.1f}% ({failed}/{total})\nVérifiez WaChap et la connectivité.",
                    alert_type="CRITICAL",
                )
                cache.set(cache_key, True, self.ALERT_COOLDOWN_MINUTES * 60)

    def send_critical_alert(
        self, title, message, alert_type="CRITICAL", error_details=None
    ):
        """
        Envoie une alerte critique par Email et WhatsApp (Admin + Dev)
        """
        config = self._get_config()
        admin_email = getattr(settings, "ADMIN_EMAIL", "sanogo7918@proton.me")
        admin_phone = getattr(settings, "ADMIN_PHONE", "+22373451676")
        dev_phone = config.developer_phone

        full_msg = f"🚨 {alert_type}: {title}\n\n{message}"
        if error_details:
            full_msg += f"\n\nDétails: {error_details}"

        timestamp = timezone.now().strftime("%d/%m %H:%M")
        whatsapp_msg = (
            f"🚨 ALERTE {alert_type} - {timestamp}\n\n📋 {title}\n\n{message}"
        )

        # 1. Email Admin
        try:
            send_mail(
                subject=f"[{alert_type}] TS Air Cargo - {title}",
                message=full_msg,
                from_email=getattr(
                    settings, "DEFAULT_FROM_EMAIL", "noreply@ts-aircargo.com"
                ),
                recipient_list=[admin_email],
                fail_silently=True,
            )
            logger.info(f"Alerte Email envoyée à {admin_email}")
        except Exception as e:
            logger.error(f"Erreur envoi Email alerte: {e}")

        # 2. WhatsApp Admin
        if admin_phone:
            self._send_whatsapp_alert(admin_phone, whatsapp_msg)

        # 3. WhatsApp Développeur (si configuré)
        if dev_phone:
            self._send_whatsapp_alert(dev_phone, whatsapp_msg)

    def _send_whatsapp_alert(self, phone, message):
        """Helper pour envoyer l'alerte WhatsApp via instance système"""
        try:
            success, _, _ = wachap_service.send_message(
                phone=phone,
                message=message,
                sender_role="system",
                region="system",  # Force l'instance système
            )
            return success
        except Exception as e:
            logger.error(f"Erreur envoi WhatsApp alerte à {phone}: {e}")
            return False

    def test_alert(self):
        """Méthode pour tester le système d'alerte manuellement"""
        self.send_critical_alert(
            title="Test Système Alerte",
            message="Ceci est un test manuel des alertes (Email + WhatsApp Admin/Dev).",
            alert_type="TEST",
        )
        return True


# Instance globale
alert_system = AlertSystem()
