"""
Service d'envoi SMS via Orange API (Mali/Sénégal/Côte d'Ivoire)
Documentation: https://developer.orange.com/apis/sms/
"""

import requests
import logging
from typing import Tuple, Optional, Dict, Any
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
import base64

logger = logging.getLogger(__name__)


class OrangeSMSService:
    """
    Service pour l'envoi de SMS via l'API Orange
    Gère l'authentification OAuth2 et l'envoi de SMS
    """
    
    # URLs de l'API Orange (Production)
    AUTH_URL = "https://api.orange.com/oauth/v3/token"
    SMS_URL = "https://api.orange.com/smsmessaging/v1/outbound/{sender}/requests"
    
    # URLs de test (Sandbox)
    AUTH_URL_SANDBOX = "https://api.orange.com/oauth/v3/token"
    SMS_URL_SANDBOX = "https://api.orange.com/smsmessaging/v1/outbound/{sender}/requests"
    
    def __init__(self):
        """Initialise le service avec les configurations"""
        self.client_id = getattr(settings, 'ORANGE_SMS_CLIENT_ID', '').strip()
        self.client_secret = getattr(settings, 'ORANGE_SMS_CLIENT_SECRET', '').strip()
        self.sender_name = getattr(settings, 'ORANGE_SMS_SENDER_NAME', '').strip()
        self.sender_phone = getattr(settings, 'ORANGE_SMS_SENDER_PHONE', '').strip()
        self.use_sender_name = getattr(settings, 'ORANGE_SMS_USE_SENDER_NAME', False)
        self.use_sandbox = getattr(settings, 'ORANGE_SMS_USE_SANDBOX', True)
        
        # Sélectionner les URLs selon l'environnement
        if self.use_sandbox:
            self.auth_url = self.AUTH_URL_SANDBOX
            self.sms_url_template = self.SMS_URL_SANDBOX
        else:
            self.auth_url = self.AUTH_URL
            self.sms_url_template = self.SMS_URL
    
    def is_configured(self) -> bool:
        """Vérifie si le service est configuré"""
        return bool(self.client_id and self.client_secret)
    
    def get_access_token(self) -> Optional[str]:
        """
        Obtient un token d'accès OAuth2 depuis Orange API
        Cache le token pour éviter les appels répétés
        
        Returns:
            str: Access token ou None si erreur
        """
        # Vérifier le cache d'abord
        cache_key = 'orange_sms_access_token'
        cached_token = cache.get(cache_key)
        
        if cached_token:
            logger.debug("Token Orange SMS récupéré du cache")
            return cached_token
        
        # Obtenir un nouveau token
        try:
            # Encoder les credentials en Base64
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded_credentials}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'client_credentials'
            }
            
            logger.debug(f"Demande de token OAuth2 à Orange API (sandbox={self.use_sandbox})")
            response = requests.post(
                self.auth_url,
                headers=headers,
                data=data,
                timeout=10
            )
            
            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get('access_token')
                expires_in = token_data.get('expires_in', 3600)  # Défaut 1h
                
                # Mettre en cache le token (expiration - 5 minutes de sécurité)
                cache.set(cache_key, access_token, expires_in - 300)
                
                logger.info(f"Token Orange SMS obtenu (expire dans {expires_in}s)")
                return access_token
            else:
                logger.error(f"Erreur obtention token Orange: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Exception lors de l'obtention du token Orange: {str(e)}")
            return None
    
    def send_sms(self, phone: str, message: str) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Envoie un SMS via Orange API
        En mode dev (DEBUG=True), redirige vers ADMIN_PHONE si configuré
        
        Args:
            phone: Numéro de téléphone au format international (+223XXXXXXXX)
            message: Contenu du SMS (max 160 caractères standard, 70 pour unicode)
            
        Returns:
            Tuple[bool, Optional[str], Optional[Dict]]: (succès, message_id, données_complètes)
        """
        if not self.is_configured():
            logger.error("Orange SMS non configuré (CLIENT_ID ou CLIENT_SECRET manquant)")
            return False, "Configuration manquante", None
        
        # Obtenir le token d'accès
        access_token = self.get_access_token()
        if not access_token:
            return False, "Impossible d'obtenir le token d'accès", None
        
        try:
            # En mode dev, rediriger vers le numéro de test (comme WaChap)
            original_phone = phone
            dev_mode = getattr(settings, 'DEBUG', False)
            admin_phone = getattr(settings, 'ADMIN_PHONE', '').strip()
            
            if dev_mode and admin_phone:
                phone = admin_phone
                # Enrichir le message pour identifier le destinataire réel
                message = f"[DEV - Destinataire réel: {original_phone}]\n\n{message}"
                logger.info(f"Mode DEV: SMS redirigé de {original_phone} vers {admin_phone}")
            
            # Formater le numéro de téléphone
            formatted_phone = self._format_phone_number(phone)
            
            # Déterminer le sender
            sender = self._get_sender()
            
            # Extraire le sender pour l'URL (sans tel: et sans +)
            sender_for_url = sender.replace('tel:', '').replace('+', '')
            
            # Préparer la requête SMS
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Le senderAddress doit avoir le format tel:+ selon Orange API
            payload = {
                'outboundSMSMessageRequest': {
                    'address': f'tel:+{formatted_phone}',
                    'senderAddress': f'tel:+{sender_for_url}',  # Format standard REST
                    'outboundSMSTextMessage': {
                        'message': message
                    }
                }
            }
            
            # URL avec le sender - doit correspondre au senderAddress (avec tel:+)
            # On URL-encode le sender pour gérer les caractères spéciaux
            import urllib.parse
            sender_for_url_encoded = urllib.parse.quote(f'tel:+{sender_for_url}', safe='')
            sms_url = self.sms_url_template.format(sender=sender_for_url_encoded)
            
            logger.info(f"Envoi SMS Orange vers {formatted_phone}")
            logger.debug(f"URL: {sms_url}")
            
            response = requests.post(
                sms_url,
                headers=headers,
                json=payload,
                timeout=15
            )
            
            if response.status_code in [200, 201]:
                response_data = response.json()
                
                # Extraire les informations de la réponse
                resource_url = response_data.get('outboundSMSMessageRequest', {}).get('resourceURL', '')
                delivery_info = response_data.get('outboundSMSMessageRequest', {}).get('deliveryInfoList', {})
                
                # Extraire le message ID
                message_id = None
                if delivery_info and 'deliveryInfo' in delivery_info:
                    delivery_list = delivery_info['deliveryInfo']
                    if delivery_list and len(delivery_list) > 0:
                        message_id = delivery_list[0].get('messageId')
                
                logger.info(f"✅ SMS Orange envoyé avec succès - ID: {message_id}")
                logger.debug(f"Resource URL: {resource_url}")
                
                return True, message_id, response_data
            else:
                error_msg = f"Erreur {response.status_code}: {response.text}"
                logger.error(f"❌ Échec envoi SMS Orange - {error_msg}")
                return False, error_msg, None
                
        except requests.exceptions.Timeout:
            error_msg = "Timeout lors de l'envoi SMS Orange"
            logger.error(error_msg)
            return False, error_msg, None
        except Exception as e:
            error_msg = f"Exception lors de l'envoi SMS Orange: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, None
    
    def _format_phone_number(self, phone: str) -> str:
        """
        Formate un numéro de téléphone pour l'API Orange
        
        Args:
            phone: Numéro brut
            
        Returns:
            str: Numéro formaté (sans le +)
        """
        # Nettoyer le numéro
        clean_phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        # Retirer le + si présent
        if clean_phone.startswith('+'):
            clean_phone = clean_phone[1:]
        
        # Ajouter l'indicatif Mali si manquant
        if not clean_phone.startswith('223') and len(clean_phone) == 8:
            clean_phone = '223' + clean_phone
        
        return clean_phone
    
    def _get_sender(self) -> str:
        """
        Retourne le sender à utiliser
        
        Returns:
            str: Sender au format tel:+223XXXXXXXX ou sender name si activé
        """
        # Si le Sender Name est activé ET configuré
        if self.use_sender_name and self.sender_name:
            logger.info(f"Utilisation du Sender Name: {self.sender_name}")
            return self.sender_name
        
        # Sinon utiliser le numéro de téléphone sender
        if self.sender_phone:
            formatted = self._format_phone_number(self.sender_phone)
            sender = f'tel:+{formatted}'
            logger.debug(f"Utilisation du numéro sender: {sender}")
            return sender
        
        # Fallback : erreur - pas de sender configuré
        logger.error("❌ Aucun sender configuré (ni SENDER_PHONE ni SENDER_NAME)")
        raise ValueError("Orange SMS: Aucun sender configuré. Définissez ORANGE_SMS_SENDER_PHONE ou ORANGE_SMS_SENDER_NAME")
    
    def get_balance(self) -> Optional[Dict[str, Any]]:
        """
        Récupère le solde du compte Orange (si disponible via l'API)
        
        Returns:
            dict: Informations sur le solde ou None
        """
        # Note: Cette fonctionnalité dépend de l'API Orange
        # Certains comptes peuvent avoir accès au balance endpoint
        access_token = self.get_access_token()
        if not access_token:
            return None
        
        try:
            # URL potentielle (à vérifier selon la doc Orange)
            balance_url = "https://api.orange.com/smsmessaging/v1/balance"
            
            headers = {
                'Authorization': f'Bearer {access_token}'
            }
            
            response = requests.get(balance_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Balance endpoint non disponible: {response.status_code}")
                return None
                
        except Exception as e:
            logger.debug(f"Balance Orange non disponible: {str(e)}")
            return None


# Instance globale du service
orange_sms_service = OrangeSMSService()


# Fonction utilitaire pour l'envoi simple
def send_orange_sms(phone: str, message: str) -> Tuple[bool, Optional[str]]:
    """
    Fonction utilitaire pour envoyer un SMS via Orange
    
    Args:
        phone: Numéro de téléphone
        message: Message à envoyer
        
    Returns:
        Tuple[bool, Optional[str]]: (succès, message_id ou erreur)
    """
    success, message_id, _ = orange_sms_service.send_sms(phone, message)
    return success, message_id


# Fonction de test
def test_orange_sms_configuration():
    """
    Teste la configuration Orange SMS
    """
    print("\n" + "="*60)
    print("TEST CONFIGURATION ORANGE SMS")
    print("="*60)
    
    service = orange_sms_service
    
    print(f"\n📋 Configuration:")
    print(f"  - Client ID: {'✅ Configuré' if service.client_id else '❌ Manquant'}")
    print(f"  - Client Secret: {'✅ Configuré' if service.client_secret else '❌ Manquant'}")
    print(f"  - Sender Phone: {service.sender_phone if service.sender_phone else '❌ Non configuré'}")
    print(f"  - Sender Name: {service.sender_name if service.sender_name else '❌ Non configuré'}")
    print(f"  - Utiliser Sender Name: {'✅ Oui' if service.use_sender_name else '❌ Non (utilise numéro)'}")
    print(f"  - Environnement: {'🧪 Sandbox (Test)' if service.use_sandbox else '🚀 Production'}")
    print(f"  - Service configuré: {'✅ Oui' if service.is_configured() else '❌ Non'}")
    
    if service.is_configured():
        print(f"\n🔑 Test d'authentification...")
        token = service.get_access_token()
        if token:
            print(f"  ✅ Token obtenu: {token[:20]}...")
        else:
            print(f"  ❌ Échec d'obtention du token")
    else:
        print(f"\n⚠️  Configuration incomplète. Ajoutez dans .env:")
        print(f"  ORANGE_SMS_CLIENT_ID=votre_client_id")
        print(f"  ORANGE_SMS_CLIENT_SECRET=votre_client_secret")
        print(f"  ORANGE_SMS_SENDER_PHONE=+223XXXXXXXX (requis pour commencer)")
        print(f"  ORANGE_SMS_SENDER_NAME=TSAIRCARGO (optionnel, après validation Orange)")
        print(f"  ORANGE_SMS_USE_SENDER_NAME=False (True après validation du Sender Name)")
        print(f"  ORANGE_SMS_USE_SANDBOX=True (False pour production)")
    
    print("\n" + "="*60 + "\n")


if __name__ == '__main__':
    test_orange_sms_configuration()
