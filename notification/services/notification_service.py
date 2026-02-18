import logging
from django.utils import timezone
from ..models import Notification, ConfigurationNotification
from .wachap_service import wachap_service
from .alert_system import alert_system

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service de façade pour la gestion des notifications
    """

    @staticmethod
    def send_notification(
        destinataire, message, categorie="autre", titre="", media_url=None
    ):
        """
        Envoie une notification (WhatsApp par défaut)

        Args:
            destinataire: User instance
            message: Texte du message
            categorie: Catégorie métier
            titre: Titre (pour log/historique)
            media_url: URL d'une image/média à joindre (optionnel)
        """
        try:
            # 1. Vérifier si les notifications sont actives globalement
            config = ConfigurationNotification.get_solo()
            # On pourrait ajouter un switch global ici, pour l'instant on suppose actif

            # 2. Créer l'objet Notification
            notification = Notification.objects.create(
                destinataire=destinataire,
                telephone_destinataire=getattr(destinataire, "telephone", "")
                or getattr(destinataire, "phone", ""),
                email_destinataire=getattr(destinataire, "email", ""),
                message=message,
                categorie=categorie,
                titre=titre,
                type_notification="whatsapp",
                statut="en_attente",
            )

            # 3. Envoyer via WaChap
            success = False
            error_msg = ""
            message_id = ""

            phone = notification.telephone_destinataire
            if not phone:
                error_msg = "Pas de numéro de téléphone"
            else:
                # Déterminer si media
                msg_type = "image" if media_url else "text"

                success, error_msg, message_id = wachap_service.send_message_with_type(
                    phone=phone,
                    message=message,
                    message_type=msg_type,
                    media_url=media_url,
                    # Le routage (Chine/Mali) est géré automatiquement par WaChapService
                    # sauf si on veut le forcer ici selon la catégorie
                )

            # 4. Mettre à jour le statut
            if success:
                notification.marquer_comme_envoye(message_id)
                logger.info(f"Notification {notification.id} envoyée à {phone}")
            else:
                notification.marquer_comme_echec(error_msg)
                logger.error(f"Échec notification {notification.id}: {error_msg}")

                # Alerte si échec critique (optionnel, géré par AlertSystem périodique)

            return success, notification

        except Exception as e:
            logger.exception(f"Exception send_notification: {e}")
            # Tenter de sauver l'échec si la notif a été créée
            if "notification" in locals():
                notification.marquer_comme_echec(str(e))
            return False, None

    @staticmethod
    def send_mass_notification(queryset_users, message, categorie="autre"):
        """
        Envoie une notification à une liste d'utilisateurs (utilisé par Celery)
        """
        results = {"success": 0, "failed": 0}
        for user in queryset_users:
            success, _ = NotificationService.send_notification(user, message, categorie)
            if success:
                results["success"] += 1
            else:
                results["failed"] += 1
        return results


# Instance globale
notification_service = NotificationService()
