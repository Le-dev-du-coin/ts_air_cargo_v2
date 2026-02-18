"""
Service d'envoi de SMS avec support de plusieurs providers
Support: Twilio, AWS SNS, Orange Mali
"""

import logging
from django.conf import settings
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class SMSService:
    """
    Service centralisé pour l'envoi de SMS via différents providers
    """
    
    @staticmethod
    def get_provider():
        """Récupère le provider SMS configuré"""
        return getattr(settings, 'SMS_PROVIDER', 'twilio')
    
    @staticmethod
    def send_sms(phone_number: str, message: str) -> Tuple[bool, Optional[str]]:
        """
        Envoie un SMS via le provider configuré
        
        Args:
            phone_number: Numéro de téléphone au format international (+22312345678)
            message: Contenu du SMS
            
        Returns:
            Tuple[bool, Optional[str]]: (succès, message_id ou erreur)
        """
        provider = SMSService.get_provider()
        
        try:
            if provider == 'twilio':
                return SMSService._send_via_twilio(phone_number, message)
            elif provider == 'aws_sns':
                return SMSService._send_via_aws_sns(phone_number, message)
            elif provider == 'orange_mali':
                return SMSService._send_via_orange_mali(phone_number, message)
            else:
                logger.error(f"Provider SMS inconnu: {provider}")
                return False, f"Provider inconnu: {provider}"
                
        except Exception as e:
            logger.error(f"Erreur envoi SMS vers {phone_number}: {str(e)}")
            return False, str(e)
    
    @staticmethod
    def _send_via_twilio(phone_number: str, message: str) -> Tuple[bool, Optional[str]]:
        """
        Envoie un SMS via Twilio
        """
        try:
            from twilio.rest import Client
            
            account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '').strip()
            auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '').strip()
            from_number = getattr(settings, 'TWILIO_PHONE_NUMBER', '').strip()
            
            if not all([account_sid, auth_token, from_number]):
                logger.warning("Configuration Twilio incomplète, SMS non envoyé")
                return False, "Configuration Twilio manquante"
            
            # Initialiser le client Twilio
            client = Client(account_sid, auth_token)
            
            # Envoyer le SMS
            twilio_message = client.messages.create(
                body=message,
                from_=from_number,
                to=phone_number
            )
            
            logger.info(f"SMS Twilio envoyé à {phone_number}, SID: {twilio_message.sid}")
            return True, twilio_message.sid
            
        except ImportError:
            logger.error("Module 'twilio' non installé. Exécutez: pip install twilio")
            return False, "Module twilio non installé"
        except Exception as e:
            logger.error(f"Erreur Twilio pour {phone_number}: {str(e)}")
            return False, str(e)
    
    @staticmethod
    def _send_via_aws_sns(phone_number: str, message: str) -> Tuple[bool, Optional[str]]:
        """
        Envoie un SMS via AWS SNS
        """
        try:
            import boto3
            
            region = getattr(settings, 'AWS_SNS_REGION', 'us-east-1')
            access_key = getattr(settings, 'AWS_ACCESS_KEY_ID', '').strip()
            secret_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', '').strip()
            
            if not all([access_key, secret_key]):
                logger.warning("Configuration AWS SNS incomplète, SMS non envoyé")
                return False, "Configuration AWS SNS manquante"
            
            # Initialiser le client SNS
            sns_client = boto3.client(
                'sns',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
            
            # Envoyer le SMS
            response = sns_client.publish(
                PhoneNumber=phone_number,
                Message=message,
                MessageAttributes={
                    'AWS.SNS.SMS.SMSType': {
                        'DataType': 'String',
                        'StringValue': 'Transactional'  # Pour messages critiques
                    }
                }
            )
            
            message_id = response.get('MessageId')
            logger.info(f"SMS AWS SNS envoyé à {phone_number}, MessageId: {message_id}")
            return True, message_id
            
        except ImportError:
            logger.error("Module 'boto3' non installé. Exécutez: pip install boto3")
            return False, "Module boto3 non installé"
        except Exception as e:
            logger.error(f"Erreur AWS SNS pour {phone_number}: {str(e)}")
            return False, str(e)
    
    @staticmethod
    def _send_via_orange_mali(phone_number: str, message: str) -> Tuple[bool, Optional[str]]:
        """
        Envoie un SMS via Orange Mali API (vraie implémentation OAuth2)
        """
        try:
            from .orange_sms_service import orange_sms_service
            
            # Utiliser le service Orange SMS complet
            success, message_id, response_data = orange_sms_service.send_sms(phone_number, message)
            
            if success:
                logger.info(f"SMS Orange envoyé à {phone_number} - ID: {message_id}")
                return True, message_id
            else:
                logger.error(f"Échec SMS Orange pour {phone_number}: {message_id}")
                return False, message_id
                
        except ImportError as e:
            logger.error(f"Module orange_sms_service non disponible: {str(e)}")
            return False, "Service Orange SMS non disponible"
        except Exception as e:
            logger.error(f"Erreur SMS Orange pour {phone_number}: {str(e)}")
            return False, str(e)
    
    @staticmethod
    def is_configured() -> bool:
        """
        Vérifie si un provider SMS est configuré
        """
        provider = SMSService.get_provider()
        
        if provider == 'twilio':
            return all([
                getattr(settings, 'TWILIO_ACCOUNT_SID', '').strip(),
                getattr(settings, 'TWILIO_AUTH_TOKEN', '').strip(),
                getattr(settings, 'TWILIO_PHONE_NUMBER', '').strip()
            ])
        elif provider == 'aws_sns':
            return all([
                getattr(settings, 'AWS_ACCESS_KEY_ID', '').strip(),
                getattr(settings, 'AWS_SECRET_ACCESS_KEY', '').strip()
            ])
        elif provider == 'orange_mali':
            # Utiliser le service Orange SMS complet
            try:
                from .orange_sms_service import orange_sms_service
                return orange_sms_service.is_configured()
            except ImportError:
                return False
        
        return False


# Fonction de test pour vérifier la configuration
def test_sms_configuration():
    """
    Teste la configuration SMS
    """
    provider = SMSService.get_provider()
    is_configured = SMSService.is_configured()
    
    print(f"Provider SMS configuré: {provider}")
    print(f"Configuration complète: {is_configured}")
    
    if not is_configured:
        print("⚠️ Configuration SMS incomplète. Veuillez configurer:")
        if provider == 'twilio':
            print("  - TWILIO_ACCOUNT_SID")
            print("  - TWILIO_AUTH_TOKEN")
            print("  - TWILIO_PHONE_NUMBER")
        elif provider == 'aws_sns':
            print("  - AWS_ACCESS_KEY_ID")
            print("  - AWS_SECRET_ACCESS_KEY")
            print("  - AWS_SNS_REGION (optionnel)")
        elif provider == 'orange_mali':
            print("  - ORANGE_MALI_API_KEY")
            print("  - ORANGE_MALI_SENDER_ID (optionnel)")
    
    return is_configured


if __name__ == '__main__':
    test_sms_configuration()
