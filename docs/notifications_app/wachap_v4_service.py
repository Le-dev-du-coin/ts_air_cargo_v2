"""
Service WaChap V4 pour l'envoi de messages WhatsApp
"""

import requests
import logging
import json
import re
from typing import Optional, Dict, Any, Tuple
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class WaChapV4Service:
    """
    Service pour la nouvelle API WaChap V4.
    """

    def __init__(self):
        """Initialise le service avec les nouvelles configurations."""
        self.base_url = "https://api.wachap.com/v1"  # Selon la documentation
        self.secret_key = getattr(settings, 'WACHAP_V4_SECRET_KEY', '')
        self.accounts = getattr(settings, 'WACHAP_V4_ACCOUNTS', {})
        self._validate_config()

    def _validate_config(self) -> None:
        """Valide que les configurations minimales sont présentes."""
        if not self.secret_key:
            logger.warning("Clé secrète WaChap V4 (WACHAP_V4_SECRET_KEY) non configurée.")
        if not self.accounts:
            logger.warning("Comptes WaChap V4 (WACHAP_V4_ACCOUNTS) non configurés.")

    def format_phone_number(self, phone: str) -> str:
        """
        Formate un numéro de téléphone pour l'API.
        """
        clean_phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not clean_phone.startswith('+'):
            if clean_phone.startswith('223') or clean_phone.startswith('86'):
                clean_phone = '+' + clean_phone
            elif len(clean_phone) == 8 and clean_phone.isdigit():
                clean_phone = '+223' + clean_phone
            else:
                # Pour les autres cas, on ne peut pas deviner, on suppose que c'est un numéro international sans le +
                clean_phone = '+' + clean_phone
        return clean_phone

    def determine_region(self, sender_role: str = None, recipient_phone: str = None, message_type: str = 'notification') -> str:
        """
        Détermine la région à utiliser ('chine', 'mali', 'system').
        Cette logique est une simplification de l'ancienne `determine_instance`.
        """
        if sender_role == 'system' or message_type in ['otp', 'alert', 'admin_alert', 'system', 'account']:
            return 'system'
        if sender_role == 'agent_chine':
            return 'chine'
        if sender_role == 'agent_mali':
            return 'mali'
        
        if recipient_phone:
            clean_phone = recipient_phone.replace('+', '').replace(' ', '')
            if clean_phone.startswith('86'):
                return 'chine'
            if clean_phone.startswith('223'):
                return 'mali'
        
        # Par défaut, on utilise le Mali pour les clients et autres.
        return 'mali'

    def send_message(self, phone: str, message: str, sender_role: str = None, 
                     region: str = None, message_type: str = 'notification') -> Tuple[bool, str, Optional[str]]:
        """
        Envoie un message texte via la nouvelle API WaChap V4.
        """
        if not self.secret_key or not self.accounts:
            return False, "Configuration WaChap V4 incomplète.", None

        formatted_phone = self.format_phone_number(phone)
        
        if region is None:
            region = self.determine_region(sender_role, formatted_phone, message_type)
        
        # Logique de sélection de compte avec fallback robuste
        account_id = self.accounts.get(region)
        fallback_region = None

        if not account_id:
            logger.warning(f"AccountId non trouvé pour la région '{region}'. Tentative de fallback.")
            
            # Définir l'ordre de fallback en fonction de la région initiale
            if region == 'system':
                fallback_order = ['mali', 'chine']
            elif region == 'chine':
                fallback_order = ['mali', 'system']
            else: # mali ou autre
                fallback_order = ['chine', 'system']

            for fallback in fallback_order:
                account_id = self.accounts.get(fallback)
                if account_id:
                    fallback_region = fallback
                    logger.info(f"Utilisation du compte de fallback '{fallback_region}' pour la région '{region}'.")
                    break
        
        if not account_id:
            return False, f"Aucun accountId trouvé pour la région '{region}' et aucun fallback disponible.", None


        headers = {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            "data": {
                "accountId": account_id,
                "to": formatted_phone,
                "type": "text",
                "content": message
            }
        }

        start_time = timezone.now()
        try:
            response = requests.post(
                f"{self.base_url}/whatsapp/messages/send",
                json=payload,
                headers=headers,
                timeout=20
            )
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            
            logger.info(f"WaChap V4 - Envoi vers {formatted_phone} via account {account_id}: {response.status_code}")

            if response.status_code == 200:
                response_data = response.json()
                if response_data.get('success'):
                    message_id = response_data.get('messageId')
                    logger.info(f"Message V4 envoyé avec succès. ID: {message_id}")
                    return True, response_data.get('message', 'Message envoyé avec succès.'), message_id
                else:
                    error_msg = f"Erreur applicative V4: {response_data.get('message', 'Erreur inconnue')}"
                    logger.error(error_msg)
                    return False, error_msg, None
            else:
                error_msg = f"Erreur HTTP V4 {response.status_code}: {response.text}"
                logger.error(error_msg)
                return False, error_msg, None

        except requests.exceptions.Timeout as te:
            error_msg = f"Timeout V4 lors de l'envoi du message: {te}"
            logger.error(error_msg)
            return False, error_msg, None
        except requests.exceptions.RequestException as re:
            error_msg = f"Erreur réseau V4 lors de l'envoi du message: {re}"
            logger.error(error_msg)
            return False, error_msg, None
        except Exception as e:
            error_msg = f"Erreur inattendue V4 lors de l'envoi du message: {e}"
            logger.critical(error_msg, exc_info=True)
            return False, error_msg, None

    def send_media(self, phone: str, message: str, media_url: str,
                   filename: str = None, sender_role: str = None, 
                   region: str = None) -> Tuple[bool, str, Optional[str]]:
        """
        Envoie un message avec média via la nouvelle API WaChap V4.
        (Implémentation à venir, nécessite la documentation)
        """
        logger.warning("La méthode send_media n'est pas documentée dans la V4 pour le moment.")
        return False, "Non implémenté (documentation manquante)", None


# Instance globale du nouveau service
wachap_v4_service = WaChapV4Service()
