import requests
import logging
import json
import base64
from django.conf import settings
from django.core.cache import cache
from ..models import ConfigurationNotification

logger = logging.getLogger(__name__)


class WaChapService:
    """
    Service d'intégration avec l'API WaChap (WhatsApp)
    Gère le routage vers les différentes instances (Chine, Mali, Système)
    """

    BASE_URL = "https://wachap.app/api"

    def _get_config(self):
        """Récupère la configuration (avec cache 5 minutes)"""
        config = cache.get("config_notification")
        if not config:
            config = ConfigurationNotification.get_solo()
            cache.set("config_notification", config, 300)
        return config

    def _get_instance_credentials(self, region="mali"):
        """
        Récupère les identifiants pour une région donnée

        Args:
            region: 'chine', 'mali' ou 'system'

        Returns:
            tuple: (access_token, instance_id)
        """
        config = self._get_config()

        if region == "chine":
            return config.wachap_chine_access_token, config.wachap_chine_instance_id
        elif region == "system":
            return config.wachap_system_access_token, config.wachap_system_instance_id
        else:  # Default to mali
            return config.wachap_mali_access_token, config.wachap_mali_instance_id

    def _determine_instance_by_phone(self, phone):
        """Détermine l'instance à utiliser selon le numéro"""
        if not phone:
            return "mali"

        phone = str(phone).replace("+", "").replace(" ", "")

        if phone.startswith("86"):
            return "chine"
        elif phone.startswith("223"):
            return "mali"
        else:
            return "mali"  # Default

    def send_message(self, phone, message, sender_role=None, region=None):
        """
        Envoie un message texte simple

        Args:
            phone: Numéro de téléphone destinataire
            message: Contenu du message
            sender_role: Rôle de l'expéditeur (pour info log)
            region: Force une région spécifique ('chine', 'mali', 'system')
        """
        return self.send_message_with_type(phone, message, "text", sender_role, region)

    def send_message_with_type(
        self,
        phone,
        message,
        message_type="text",
        sender_role=None,
        region=None,
        media_url=None,
        media_file=None,
    ):
        """
        Envoie un message typé (text, image, etc.)
        """
        try:
            # 1. Déterminer l'instance
            if not region:
                if sender_role == "system":
                    region = "system"
                else:
                    region = self._determine_instance_by_phone(phone)

            # 2. Récupérer les credentials
            access_token, instance_id = self._get_instance_credentials(region)

            if not access_token or not instance_id:
                return False, f"Instance {region} non configurée", None

            # 3. Préparer payload
            clean_phone = str(phone).replace("+", "").replace(" ", "")

            payload = {
                "number": clean_phone,
                "instance_id": instance_id,
                "access_token": access_token,
            }

            endpoint = "/send"

            if (
                message_type == "text" or not media_url
            ):  # Fallback a text si pas de media
                payload["type"] = "text"
                payload["message"] = message
            elif message_type == "image" or message_type == "media":
                endpoint = "/send-media"
                payload["type"] = "media"
                payload["message"] = message  # Caption
                if media_url:
                    payload["media_url"] = media_url
                    # media_type is usually inferred or required. WaChap API might require 'media_type' ('image', 'video', 'document')
                    # Assuming 'image' generic or auto-detect. Checking V1 docs if available...
                    # V1 docs suggest 'type': 'media' and 'media_url'.

            # 4. Envoyer requête
            try:
                response = requests.post(
                    f"{self.BASE_URL}{endpoint}", json=payload, timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        message_id = data.get("data", {}).get("message_id") or data.get(
                            "message_id"
                        )
                        logger.info(
                            f"WaChap Sent ({region}): {clean_phone} - ID: {message_id}"
                        )
                        return True, "Envoyé avec succès", message_id
                    else:
                        error_msg = data.get("message", "Erreur inconnue")
                        logger.error(f"WaChap Error ({region}): {error_msg}")
                        return False, error_msg, None
                else:
                    logger.error(
                        f"WaChap HTTP Error ({region}): {response.status_code} - {response.text}"
                    )
                    return False, f"HTTP {response.status_code}", None

            except requests.exceptions.Timeout:
                return False, "Timeout WaChap API", None
            except requests.exceptions.RequestException as e:
                return False, f"Erreur connexion: {str(e)}", None

        except Exception as e:
            logger.exception(f"Exception WaChap send: {str(e)}")
            return False, str(e), None


# Instance globale
wachap_service = WaChapService()
