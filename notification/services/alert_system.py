import logging
import traceback
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail, EmailMessage
from django.core.mail.backends.smtp import EmailBackend
from ..models import Notification, ConfigurationNotification
from .wachap_service import wachap_service

logger = logging.getLogger(__name__)


class AlertSystem:
    """
    Système unifié d'alertes (Admin + Développeur).
    Envoie chaque alerte critique par WhatsApp + Email.
    La config SMTP et le destinataire sont lus depuis ConfigurationNotification (BDD).
    """

    FAILURE_RATE_THRESHOLD = 50  # %
    ALERT_COOLDOWN_MINUTES = 60

    def _get_config(self):
        return ConfigurationNotification.get_solo()

    # ------------------------------------------------------------------
    # Email dynamique via config BDD (SMTP Hostinger ou autre)
    # ------------------------------------------------------------------

    def _get_email_backend(self, config):
        """
        Construit un EmailBackend SMTP à la volée depuis la config BDD.
        Retourne None si la config est incomplète.
        """
        if not config.smtp_host or not config.smtp_user or not config.smtp_password:
            return None
        try:
            return EmailBackend(
                host=config.smtp_host,
                port=config.smtp_port,
                username=config.smtp_user,
                password=config.smtp_password,
                use_ssl=config.smtp_use_ssl,
                use_tls=not config.smtp_use_ssl,  # TLS si pas SSL
                fail_silently=False,
                timeout=10,
            )
        except Exception as e:
            logger.error(f"[AlertSystem] Impossible de créer l'EmailBackend: {e}")
            return None

    def send_alert_email(self, config, subject, body):
        """
        Envoie un email d'alerte au developer_email via le SMTP configuré en BDD.
        Fallback sur l'EmailBackend Django par défaut (settings) si SMTP BDD absent.
        """
        recipient = config.developer_email
        if not recipient:
            logger.info(
                "[AlertSystem] developer_email non configuré — email d'alerte ignoré."
            )
            return False

        from_email = config.smtp_user or getattr(
            settings, "DEFAULT_FROM_EMAIL", "noreply@ts-aircargo.com"
        )
        backend = self._get_email_backend(config)

        try:
            if backend:
                msg = EmailMessage(
                    subject=subject,
                    body=body,
                    from_email=from_email,
                    to=[recipient],
                    connection=backend,
                )
                msg.send()
                logger.info(
                    f"[AlertSystem] Email alerte envoyé à {recipient} via SMTP BDD ({config.smtp_host})"
                )
            else:
                # Fallback : backend Django par défaut (settings.py)
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=from_email,
                    recipient_list=[recipient],
                    fail_silently=False,
                )
                logger.info(
                    f"[AlertSystem] Email alerte envoyé à {recipient} via backend Django par défaut"
                )
            return True
        except Exception as e:
            logger.error(f"[AlertSystem] Erreur envoi email à {recipient}: {e}")
            return False

    # ------------------------------------------------------------------
    # Alertes globales
    # ------------------------------------------------------------------

    def check_and_alert(self):
        """Vérifie la santé du système et alerte si nécessaire"""
        try:
            self._check_failure_rate()
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
                    message=(
                        f"Taux d'échec : {rate:.1f}% ({failed}/{total})\n"
                        f"Vérifiez les instances WaChap et la connectivité réseau."
                    ),
                    alert_type="CRITICAL",
                )
                cache.set(cache_key, True, self.ALERT_COOLDOWN_MINUTES * 60)

    def send_critical_alert(
        self, title, message, alert_type="CRITICAL", error_details=None
    ):
        """
        Envoie une alerte critique par :
          1. WhatsApp → developer_phone (config BDD)
          2. Email    → developer_email (config BDD, SMTP Hostinger)
        """
        config = self._get_config()
        dev_phone = config.developer_phone
        dev_email = config.developer_email

        timestamp = timezone.now().strftime("%d/%m/%Y %H:%M")
        full_body = (
            f"🚨 ALERTE {alert_type} — {timestamp}\n\n" f"📋 {title}\n\n" f"{message}"
        )
        if error_details:
            full_body += f"\n\n🔍 Détails techniques :\n{error_details}"

        # 1. WhatsApp Développeur
        if dev_phone:
            self._send_whatsapp_alert(dev_phone, full_body)
        else:
            logger.warning(
                "[AlertSystem] developer_phone non configuré — alerte WhatsApp ignorée."
            )

        # 2. Email Développeur
        subject = f"[{alert_type}] TS Air Cargo — {title}"
        self.send_alert_email(config, subject, full_body)

    def _send_whatsapp_alert(self, phone, message):
        """Envoie l'alerte WhatsApp via l'instance système."""
        try:
            success, _, _ = wachap_service.send_message(
                phone=phone,
                message=message,
                sender_role="system",
                region="system",
            )
            if success:
                logger.info(f"[AlertSystem] WhatsApp alerte envoyé à {phone}")
            return success
        except Exception as e:
            logger.error(f"[AlertSystem] Erreur WhatsApp alerte à {phone}: {e}")
            return False

    def test_alert(self):
        """Envoie une alerte de test (WhatsApp + Email)."""
        self.send_critical_alert(
            title="Test Système Alerte",
            message=(
                "Ceci est un test manuel du système d'alertes.\n"
                "Si vous recevez ce message, WhatsApp + Email fonctionnent correctement ✅"
            ),
            alert_type="TEST",
        )
        return True

    @staticmethod
    def send_exception_alert(exception, context=""):
        """Raccourci : envoie une alerte depuis un bloc except."""
        alert_system.send_critical_alert(
            title=f"Exception : {type(exception).__name__}",
            message=f"Contexte : {context}\nErreur : {exception}",
            alert_type="ERROR",
            error_details=traceback.format_exc(),
        )


# Instance globale
alert_system = AlertSystem()
