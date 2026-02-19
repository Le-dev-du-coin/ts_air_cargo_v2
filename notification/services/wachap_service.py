"""
Service WaChap V4 — API https://api.wachap.com/v1
Auth : Bearer secret_key global + accountId par région.
"""

import requests
import logging
from typing import Optional, Tuple
from django.core.cache import cache
from ..models import ConfigurationNotification

logger = logging.getLogger(__name__)


class WaChapService:
    """
    Service d'intégration WaChap API V4.
    1 clé secrète globale + 1 accountId par région (chine / mali / cote_divoire / system).
    """

    BASE_URL = "https://api.wachap.com/v1"

    # Ordre de fallback par région si accountId non configuré
    FALLBACK_ORDER = {
        "system": ["mali", "chine"],
        "chine": ["mali", "system"],
        "cote_divoire": ["mali", "system"],
        "mali": ["chine", "system"],
    }

    def _get_config(self):
        """Config singleton avec cache 5 min."""
        config = cache.get("config_notification")
        if not config:
            config = ConfigurationNotification.get_solo()
            cache.set("config_notification", config, 300)
        return config

    def _get_accounts(self):
        """Retourne le dict {région: accountId} depuis la config BDD."""
        cfg = self._get_config()
        return {
            "chine": cfg.wachap_account_chine,
            "mali": cfg.wachap_account_mali,
            "cote_divoire": cfg.wachap_account_cote_divoire,
            "system": cfg.wachap_account_system,
        }

    def _get_secret_key(self):
        return self._get_config().wachap_v4_secret_key

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    @staticmethod
    def format_phone(phone: str) -> str:
        """Formate un numéro en +XXXXXXXXXXX (requis par V4)."""
        clean = (
            str(phone)
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )
        if not clean.startswith("+"):
            clean = "+" + clean
        return clean

    def _determine_region(self, phone: str, sender_role: str = None) -> str:
        """Détermine la région depuis le rôle ou le préfixe téléphonique."""
        if sender_role == "system":
            return "system"

        clean = str(phone).replace("+", "").replace(" ", "")
        if clean.startswith("86"):
            return "chine"
        if clean.startswith("225"):
            return "cote_divoire"
        # 223 ou inconnu → mali par défaut
        return "mali"

    def _resolve_account(self, region: str, accounts: dict) -> Tuple[str, str]:
        """
        Résout un accountId pour la région, avec fallback.
        Retourne (account_id, region_utilisée).
        """
        account_id = accounts.get(region, "")
        if account_id:
            return account_id, region

        logger.warning(
            f"[WaChap V4] AccountId manquant pour '{region}', tentative fallback…"
        )
        for fallback in self.FALLBACK_ORDER.get(region, []):
            fb_id = accounts.get(fallback, "")
            if fb_id:
                logger.info(f"[WaChap V4] Fallback '{region}' → '{fallback}'")
                return fb_id, fallback

        return "", region  # Aucun compte dispo

    # ------------------------------------------------------------------
    # Envoi de messages
    # ------------------------------------------------------------------

    def send_message(
        self,
        phone: str,
        message: str,
        sender_role: str = None,
        region: str = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Envoie un message texte via WaChap API V4.

        Returns:
            (success: bool, message: str, message_id: str|None)
        """
        config = self._get_config()
        secret_key = config.wachap_v4_secret_key

        if not secret_key:
            logger.error("[WaChap V4] Clé secrète non configurée.")
            return False, "Clé secrète WaChap V4 non configurée.", None

        # Override téléphone pour les tests locaux
        if config.test_phone_number:
            test_clean = config.test_phone_number.replace(" ", "")
            logger.info(f"[WaChap V4] TEST OVERRIDE: {phone} → {test_clean}")
            phone = test_clean

        formatted_phone = self.format_phone(phone)

        # Résolution région + accountId
        if not region:
            region = self._determine_region(formatted_phone, sender_role)

        accounts = self._get_accounts()
        account_id, used_region = self._resolve_account(region, accounts)

        if not account_id:
            return (
                False,
                f"Aucun accountId configuré pour la région '{region}' (et aucun fallback).",
                None,
            )

        headers = {
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "data": {
                "accountId": account_id,
                "to": formatted_phone,
                "type": "text",
                "content": message,
            }
        }

        logger.info(
            f"[WaChap V4] Envoi → {formatted_phone} | région={used_region} | account={account_id}"
        )

        try:
            response = requests.post(
                f"{self.BASE_URL}/whatsapp/messages/send",
                json=payload,
                headers=headers,
                timeout=20,
            )

            logger.debug(
                f"[WaChap V4] HTTP {response.status_code}: {response.text[:200]}"
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    message_id = data.get("messageId")
                    logger.info(f"[WaChap V4] ✓ Message envoyé. ID={message_id}")
                    return (
                        True,
                        data.get("message", "Message envoyé avec succès."),
                        message_id,
                    )
                else:
                    error = data.get("message", "Erreur applicative inconnue")
                    logger.error(f"[WaChap V4] ✗ Erreur API: {error}")
                    return False, error, None
            else:
                error = f"HTTP {response.status_code}: {response.text[:300]}"
                logger.error(f"[WaChap V4] ✗ {error}")
                return False, error, None

        except requests.exceptions.Timeout:
            logger.error("[WaChap V4] Timeout")
            return False, "Timeout WaChap API (> 20s)", None
        except requests.exceptions.RequestException as e:
            logger.error(f"[WaChap V4] Erreur réseau: {e}")
            return False, f"Erreur réseau: {e}", None
        except Exception as e:
            logger.critical(f"[WaChap V4] Exception inattendue: {e}", exc_info=True)
            return False, str(e), None

    def send_message_with_type(
        self,
        phone: str,
        message: str,
        message_type: str = "text",
        sender_role: str = None,
        region: str = None,
        media_url: str = None,
        media_file=None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Compatibilité avec l'ancien code (le type text est le seul supporté en V4 pour l'instant).
        """
        return self.send_message(phone, message, sender_role=sender_role, region=region)


# Instance globale
wachap_service = WaChapService()
