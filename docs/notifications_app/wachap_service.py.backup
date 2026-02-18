"""
Service WaChap pour l'envoi de messages WhatsApp
Support double instance : Chine et Mali
Migration Twilio → WaChap pour TS Air Cargo
"""

import requests
import logging
import json
import re
from typing import Optional, Dict, Any, Tuple
from django.conf import settings
from django.core.cache import cache
from urllib.parse import quote
from django.utils import timezone

logger = logging.getLogger(__name__)


class WaChapService:
    """
    Service principal pour l'API WaChap
    Support double instance automatique selon destinataire/contexte
    """
    
    def __init__(self):
        """Initialise le service avec les configurations des trois instances"""
        self.base_url = "https://wachap.app/api"
        
        # Configuration instance Chine
        self.china_config = {
            'access_token': getattr(settings, 'WACHAP_CHINE_ACCESS_TOKEN', ''),
            'instance_id': getattr(settings, 'WACHAP_CHINE_INSTANCE_ID', ''),
            'webhook_url': getattr(settings, 'WACHAP_CHINE_WEBHOOK_URL', ''),
            'active': getattr(settings, 'WACHAP_CHINE_ACTIVE', True)
        }
        
        # Configuration instance Mali
        self.mali_config = {
            'access_token': getattr(settings, 'WACHAP_MALI_ACCESS_TOKEN', ''),
            'instance_id': getattr(settings, 'WACHAP_MALI_INSTANCE_ID', ''),
            'webhook_url': getattr(settings, 'WACHAP_MALI_WEBHOOK_URL', ''),
            'active': getattr(settings, 'WACHAP_MALI_ACTIVE', True)
        }
        
        # Configuration instance Système (OTP et alertes)
        self.system_config = {
            'access_token': getattr(settings, 'WACHAP_SYSTEM_ACCESS_TOKEN', ''),
            'instance_id': getattr(settings, 'WACHAP_SYSTEM_INSTANCE_ID', ''),
            'webhook_url': getattr(settings, 'WACHAP_SYSTEM_WEBHOOK_URL', ''),
            'active': getattr(settings, 'WACHAP_SYSTEM_ACTIVE', True)
        }
        
        # Vérification des configurations
        self._validate_config()
    
    def _validate_config(self) -> None:
        """Valide que les configurations minimales sont présentes"""
        if not self.china_config['access_token'] and not self.mali_config['access_token']:
            logger.warning("Aucun token WaChap configuré. Service en mode simulation.")
            return
        
        if self.china_config['access_token'] and not self.china_config['instance_id']:
            logger.warning("Token Chine configuré mais pas d'instance_id")
            
        if self.mali_config['access_token'] and not self.mali_config['instance_id']:
            logger.warning("Token Mali configuré mais pas d'instance_id")
    
    def determine_instance(self, sender_role: str = None, recipient_phone: str = None, 
                          message_type: str = 'notification') -> str:
        """
        Détermine intelligemment quelle instance utiliser avec logique métier optimisée
        
        LOGIQUE PRIORITAIRE:
        1. Rôle de l'agent détermine son instance (agent_chine → chine, agent_mali → mali)
        2. OTP selon numéro destinataire pour l'authentification
        3. Admins utilisent leur instance régionale
        4. Fallback automatique si instance indisponible
        
        Args:
            sender_role: Rôle de l'expéditeur ('agent_chine', 'agent_mali', etc.)
            recipient_phone: Numéro du destinataire
            message_type: Type de message ('otp', 'notification', etc.)
        
        Returns:
            str: 'chine', 'mali' ou 'system'
        """
        preferred_region = 'mali'  # Défaut global
        
        # PRIORITÉ 0: Messages système (OTP, alertes, évènements système) → Instance Système
        if sender_role == 'system' or message_type in ['otp', 'alert', 'admin_alert', 'system', 'account']:
            preferred_region = 'system'
            logger.debug(f"Message système ({message_type}) → Instance Système")
        
        # PRIORITÉ 1: Agents utilisent TOUJOURS leur instance régionale
        # Logique métier: chaque agent utilise son système WhatsApp régional
        elif sender_role == 'agent_chine':
            preferred_region = 'chine'
            logger.debug(f"Agent Chine → Instance Chine (indépendamment du destinataire)")
        elif sender_role == 'agent_mali':
            preferred_region = 'mali'
            logger.debug(f"Agent Mali → Instance Mali (indépendamment du destinataire)")
        
        # PRIORITÉ 2: Admins utilisent leur instance régionale
        elif sender_role == 'admin_chine':
            preferred_region = 'chine'
        elif sender_role in ['admin_mali']:
            preferred_region = 'mali'
        
        # PRIORITÉ 3: OTP d'authentification selon numéro du destinataire
        # Pour l'authentification, on route selon la géolocalisation du numéro
        elif message_type == 'otp' and recipient_phone:
            clean_phone = recipient_phone.replace('+', '').replace(' ', '')
            if clean_phone.startswith('86'):  # Numéros chinois
                preferred_region = 'chine'
                logger.debug(f"OTP numéro chinois {recipient_phone} → Instance Chine")
            elif clean_phone.startswith('223'):  # Numéros maliens
                preferred_region = 'mali'
                logger.debug(f"OTP numéro malien {recipient_phone} → Instance Mali")
            else:
                # Autres numéros (France, Afrique, etc.) → Mali par défaut
                preferred_region = 'mali'
                logger.debug(f"OTP numéro autre {recipient_phone} → Instance Mali (défaut)")
        
        # PRIORITÉ 4: Si on connaît le numéro du destinataire pour une notification standard, router par indicatif
        elif recipient_phone and message_type in ['notification', 'account', 'creation_compte', 'colis_arrive', 'colis_livre', 'rapport', 'general']:
            clean_phone = recipient_phone.replace('+', '').replace(' ', '')
            if clean_phone.startswith('86'):
                preferred_region = 'chine'
            elif clean_phone.startswith('223'):
                preferred_region = 'mali'
            else:
                preferred_region = 'mali'
        # PRIORITÉ 5: Clients et rôles génériques → Mali par défaut
        elif sender_role in ['client', 'customer', 'user'] or sender_role is None:
            preferred_region = 'mali'
        
        # VÉRIFICATION DISPONIBILITÉ ET FALLBACK
        preferred_config = self.get_config(preferred_region)
        if not preferred_config['access_token'] or not preferred_config['instance_id']:
            # Fallback automatique
            if preferred_region == 'system':
                # Pour système, fallback vers Mali puis Chine
                mali_config = self.get_config('mali')
                if mali_config['access_token'] and mali_config['instance_id']:
                    logger.warning(f"Instance Système non configurée, fallback vers Mali")
                    return 'mali'
                china_config = self.get_config('chine')
                if china_config['access_token'] and china_config['instance_id']:
                    logger.warning(f"Instance Système non configurée, fallback vers Chine")
                    return 'chine'
            elif preferred_region == 'chine':
                # Fallback Chine -> Système -> Mali
                system_config = self.get_config('system')
                if system_config['access_token'] and system_config['instance_id']:
                    logger.warning(f"Instance Chine non configurée, fallback vers Système")
                    return 'system'
                mali_config = self.get_config('mali')
                if mali_config['access_token'] and mali_config['instance_id']:
                    logger.warning(f"Instance Chine non configurée, fallback vers Mali")
                    return 'mali'
            elif preferred_region == 'mali':
                # Fallback Mali -> Système -> Chine
                system_config = self.get_config('system')
                if system_config['access_token'] and system_config['instance_id']:
                    logger.warning(f"Instance Mali non configurée, fallback vers Système")
                    return 'system'
                china_config = self.get_config('chine')
                if china_config['access_token'] and china_config['instance_id']:
                    logger.warning(f"Instance Mali non configurée, fallback vers Chine")
                    return 'chine'
        
        logger.debug(f"Instance finale: {preferred_region.title()}")
        return preferred_region
    
    def get_config(self, region: str) -> Dict[str, Any]:
        """
        Récupère la configuration pour une région
        
        Args:
            region: 'chine', 'mali', ou 'system'
        
        Returns:
            dict: Configuration de la région
        """
        if region == 'chine':
            return self.china_config
        elif region == 'system':
            return self.system_config
        else:
            return self.mali_config
    
    def format_phone_number(self, phone: str) -> str:
        """
        Formate un numéro de téléphone pour WaChap
        
        Args:
            phone: Numéro de téléphone brut
        
        Returns:
            str: Numéro formaté
        """
        # Nettoyer le numéro
        clean_phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        # Ajouter l'indicatif si manquant
        if not clean_phone.startswith('+'):
            if clean_phone.startswith('223') or clean_phone.startswith('86'):
                # Préfixes connus, on ajoute simplement '+'
                clean_phone = '+' + clean_phone
            elif clean_phone.startswith('0') and len(clean_phone) in (9, 10):
                # Numéro local Mali (0XXXXXXXX) → +223XXXXXXXX
                clean_phone = '+223' + clean_phone[1:]
            elif re.match(r'^1[3-9]\d{9}$', clean_phone):
                # Numéro mobile chinois sur 11 chiffres sans indicatif → +86
                clean_phone = '+86' + clean_phone
            elif clean_phone.isdigit():
                # Numéro international avec indicatif sans + → préfixer seulement '+' (ne pas forcer +223)
                clean_phone = '+' + clean_phone
            # sinon: laisser tel quel, sera géré par validation côté provider
        
        return clean_phone
    
    def send_message(self, phone: str, message: str, sender_role: str = None, 
                    region: str = None) -> Tuple[bool, str, Optional[str]]:
        """
        Envoie un message texte via WaChap avec monitoring automatique
        
        Args:
            phone: Numéro de téléphone destinataire
            message: Contenu du message
            sender_role: Rôle de l'expéditeur (pour déterminer l'instance)
            region: Force une région ('chine' ou 'mali'), sinon détection auto
        
        Returns:
            Tuple[bool, str, Optional[str]]: (succès, message_retour, message_id)
        """
        # Formater le numéro
        formatted_phone = self.format_phone_number(phone)
        
        # Déterminer l'instance à utiliser
        if region is None:
            region = self.determine_instance(
                sender_role=sender_role,
                recipient_phone=formatted_phone
            )
        
        # Initialiser le monitoring
        attempt_id = None
        start_time = timezone.now()
        
        try:
            # Import du monitoring (import local pour éviter les imports circulaires)
            from .monitoring import wachap_monitor
            
            # Enregistrer la tentative d'envoi pour le monitoring
            attempt_id = wachap_monitor.record_message_attempt(
                region, formatted_phone, sender_role or 'unknown'
            )
            
            # Récupérer la configuration
            config = self.get_config(region)
            
            # Vérifier que la configuration est valide
            if not config['access_token'] or not config['instance_id']:
                error_msg = f"Configuration WaChap {region.title()} incomplète"
                logger.error(error_msg)
                # Enregistrer l'erreur dans le monitoring
                if attempt_id:
                    response_time = (timezone.now() - start_time).total_seconds() * 1000
                    wachap_monitor.record_message_error(attempt_id, 'config_error', error_msg, response_time)
                return False, error_msg, None
            
            # Vérifier que l'instance est active
            if not config['active']:
                error_msg = f"Instance WaChap {region.title()} désactivée"
                logger.warning(error_msg)
                # Enregistrer l'erreur dans le monitoring
                if attempt_id:
                    response_time = (timezone.now() - start_time).total_seconds() * 1000
                    wachap_monitor.record_message_error(attempt_id, 'instance_inactive', error_msg, response_time)
                return False, error_msg, None
            
            # Préparer les données pour l'API
            payload = {
                "number": formatted_phone.replace('+', ''),  # WaChap sans le +
                "type": "text",
                "message": message,
                "instance_id": config['instance_id'],
                "access_token": config['access_token']
            }
            # Log sécurisé du contexte d'envoi
            try:
                safe_phone = formatted_phone[:-4].replace('+', '*') + formatted_phone[-4:]
                safe_instance = (config['instance_id'][:6] + '...') if config.get('instance_id') else 'missing'
                logger.debug(
                    "WA DEBUG send_message: attempt=%s region=%s role=%s to=%s payload_type=%s instance=%s",
                    attempt_id,
                    region,
                    sender_role,
                    safe_phone,
                    payload.get('type'),
                    safe_instance,
                )
            except Exception:
                pass
            
            # Envoyer via l'API WaChap
            response = requests.post(
                f"{self.base_url}/send",
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            # Calculer le temps de réponse
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            
            # Logger la tentative
            logger.info(f"WaChap {region.title()} - Envoi vers {formatted_phone}: {response.status_code}")
            
            if response.status_code == 200:
                # Tenter de parser la réponse
                try:
                    response_data = response.json()
                except Exception:
                    response_data = {"raw": response.text}

                # Déterminer le succès métier (certaines réponses 200 peuvent contenir status=error)
                top_status = str(response_data.get('status', '')).lower()
                nested_status = ''
                if isinstance(response_data.get('message'), dict):
                    nested_status = str(response_data['message'].get('status', '')).lower()
                success_flag = (top_status == 'success') or (nested_status == 'success')

                # Extraire l'ID du message (peut être imbriqué)
                message_id = (
                    response_data.get('id') or
                    response_data.get('message_id') or
                    (response_data.get('message', {}).get('key', {}).get('id') if isinstance(response_data.get('message'), dict) else None)
                )

                if success_flag:
                    success_msg = f"Message envoyé via WaChap {region.title()}"
                    if attempt_id:
                        wachap_monitor.record_message_success(attempt_id, response_time, message_id)
                    logger.info(f"{success_msg} - ID: {message_id}")
                    if not message_id:
                        logger.warning(
                            "WA WARN: Réponse 200 sans message_id. attempt=%s region=%s resp_keys=%s resp_raw=%s",
                            attempt_id,
                            region,
                            list(response_data.keys()) if isinstance(response_data, dict) else type(response_data).__name__,
                            str(response_data)[:500],
                        )
                    return True, success_msg, message_id
                else:
                    # Statut applicatif non succès malgré HTTP 200
                    error_text = response_data.get('message') if not isinstance(response_data.get('message'), dict) else json.dumps(response_data.get('message'))
                    error_msg = f"Erreur WaChap {region.title()} (200/app): {error_text}"
                    if attempt_id:
                        wachap_monitor.record_message_error(attempt_id, 'app_error', error_msg, response_time)
                    logger.error(error_msg)
                    return False, error_msg, None
            else:
                error_msg = f"Erreur WaChap {region.title()}: {response.status_code} - {response.text}"
                
                # Enregistrer l'erreur dans le monitoring
                if attempt_id:
                    wachap_monitor.record_message_error(attempt_id, f'http_{response.status_code}', error_msg, response_time)
                
                logger.error(error_msg)
                
                return False, error_msg, None
                
        except requests.exceptions.Timeout:
            error_msg = f"Timeout WaChap {region} pour {phone}"
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            logger.error(error_msg)
            if attempt_id:
                try:
                    from .monitoring import wachap_monitor
                    wachap_monitor.record_message_error(attempt_id, 'timeout', error_msg, response_time)
                except ImportError:
                    pass
            return False, error_msg, None
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Erreur réseau WaChap {region} pour {phone}: {str(e)}"
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            logger.error(error_msg)
            if attempt_id:
                try:
                    from .monitoring import wachap_monitor
                    wachap_monitor.record_message_error(attempt_id, 'network_error', error_msg, response_time)
                except ImportError:
                    pass
            return False, error_msg, None
            
        except Exception as e:
            error_msg = f"Erreur générale WaChap {region} pour {phone}: {str(e)}"
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            logger.error(error_msg)
            if attempt_id:
                try:
                    from .monitoring import wachap_monitor
                    wachap_monitor.record_message_error(attempt_id, 'general_error', error_msg, response_time)
                except ImportError:
                    pass
            return False, error_msg, None
    
    def send_message_with_type(self, phone: str, message: str, message_type: str = 'notification',
                             sender_role: str = None, region: str = None) -> Tuple[bool, str, Optional[str]]:
        """
        Envoie un message avec un type spécifique
        
        Args:
            phone: Numéro de téléphone destinataire
            message: Contenu du message
            message_type: Type de message ('otp', 'notification', 'alert', etc.)
            sender_role: Rôle de l'expéditeur
            region: Force une région, sinon détection auto
        
        Returns:
            Tuple[bool, str, Optional[str]]: (succès, message_retour, message_id)
        """
        # Formater le numéro
        formatted_phone = self.format_phone_number(phone)
        
        # Déterminer l'instance à utiliser avec le type de message
        if region is None:
            region = self.determine_instance(
                sender_role=sender_role,
                recipient_phone=formatted_phone,
                message_type=message_type
            )
        
        return self.send_message(formatted_phone, message, sender_role, region)
    
    def send_media(self, phone: str, message: str, media_url: str,
                   filename: str = None, sender_role: str = None, 
                   region: str = None) -> Tuple[bool, str, Optional[str]]:
        """
        Envoie un message avec média via WaChap
        
        Args:
            phone: Numéro de téléphone destinataire
            message: Contenu du message
            media_url: URL du fichier média
            filename: Nom du fichier (optionnel)
            sender_role: Rôle de l'expéditeur
            region: Force une région, sinon détection auto
        
        Returns:
            Tuple[bool, str, Optional[str]]: (succès, message_retour, message_id)
        """
        try:
            formatted_phone = self.format_phone_number(phone)
            
            if region is None:
                region = self.determine_instance(
                    sender_role=sender_role,
                    recipient_phone=formatted_phone
                )
            
            config = self.get_config(region)
            
            if not config['access_token'] or not config['instance_id']:
                error_msg = f"Configuration WaChap {region.title()} incomplète"
                logger.error(error_msg)
                return False, error_msg, None
            
            payload = {
                "number": formatted_phone.replace('+', ''),
                "type": "media",
                "message": message,
                "media_url": media_url,
                "instance_id": config['instance_id'],
                "access_token": config['access_token']
            }
            
            if filename:
                payload["filename"] = filename
            
            response = requests.post(
                f"{self.base_url}/send",
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            logger.info(f"WaChap {region.title()} Media - Envoi vers {formatted_phone}: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                success_msg = f"Média envoyé via WaChap {region.title()}"
                message_id = response_data.get('id') or response_data.get('message_id')
                
                logger.info(f"✅ {success_msg} - ID: {message_id}")
                return True, success_msg, message_id
            else:
                error_msg = f"Erreur WaChap {region.title()} Media: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return False, error_msg, None
                
        except Exception as e:
            error_msg = f"Erreur envoi média WaChap {region} pour {phone}: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, None
    
    def get_qr_code(self, region: str) -> Tuple[bool, str]:
        """
        Récupère le QR code pour connecter WhatsApp Web
        
        Args:
            region: 'chine' ou 'mali'
        
        Returns:
            Tuple[bool, str]: (succès, url_qr_code_ou_erreur)
        """
        try:
            config = self.get_config(region)
            
            if not config['access_token'] or not config['instance_id']:
                return False, f"Configuration WaChap {region.title()} incomplète"
            
            response = requests.get(
                f"{self.base_url}/get_qrcode",
                params={
                    'instance_id': config['instance_id'],
                    'access_token': config['access_token']
                },
                timeout=30
            )
            
            if response.status_code == 200:
                # WaChap peut retourner une URL d'image QR ou les données
                return True, response.text
            else:
                return False, f"Erreur récupération QR {region}: {response.status_code}"
                
        except Exception as e:
            return False, f"Erreur QR code {region}: {str(e)}"
    
    def set_webhook(self, webhook_url: str, region: str, enable: bool = True) -> Tuple[bool, str]:
        """
        Configure le webhook pour une instance
        
        Args:
            webhook_url: URL du webhook à configurer
            region: 'chine' ou 'mali'
            enable: Activer ou désactiver le webhook
        
        Returns:
            Tuple[bool, str]: (succès, message)
        """
        try:
            config = self.get_config(region)
            
            if not config['access_token'] or not config['instance_id']:
                return False, f"Configuration WaChap {region.title()} incomplète"
            
            response = requests.get(
                f"{self.base_url}/set_webhook",
                params={
                    'webhook_url': webhook_url,
                    'enable': 'true' if enable else 'false',
                    'instance_id': config['instance_id'],
                    'access_token': config['access_token']
                },
                timeout=30
            )
            
            if response.status_code == 200:
                action = "configuré" if enable else "désactivé"
                return True, f"Webhook {action} pour instance {region.title()}"
            else:
                return False, f"Erreur webhook {region}: {response.status_code}"
                
        except Exception as e:
            return False, f"Erreur configuration webhook {region}: {str(e)}"
    
    def test_connection(self, region: str = None) -> Dict[str, Any]:
        """
        Teste la connexion aux instances WaChap
        
        Args:
            region: Tester une région spécifique, ou None pour toutes
        
        Returns:
            dict: Résultats des tests par région
        """
        results = {}
        
        regions_to_test = [region] if region else ['chine', 'mali']
        
        for reg in regions_to_test:
            config = self.get_config(reg)
            
            if not config['access_token']:
                results[reg] = {
                    'success': False,
                    'message': 'Token non configuré',
                    'details': None
                }
                continue
            
            try:
                # Test simple avec l'endpoint get_qrcode (ne nécessite pas de numéro)
                response = requests.get(
                    f"{self.base_url}/get_qrcode",
                    params={
                        'instance_id': config['instance_id'],
                        'access_token': config['access_token']
                    },
                    timeout=10
                )
                
                results[reg] = {
                    'success': response.status_code == 200,
                    'message': f"Status: {response.status_code}",
                    'details': {
                        'instance_id': config['instance_id'][:10] + '...' if config['instance_id'] else 'Non configuré',
                        'active': config['active'],
                        'webhook_configured': bool(config['webhook_url'])
                    }
                }
                
            except Exception as e:
                results[reg] = {
                    'success': False,
                    'message': f"Erreur connexion: {str(e)}",
                    'details': None
                }
        
        return results


# Instance globale du service
wachap_service = WaChapService()


# Fonctions utilitaires pour compatibilité
def send_whatsapp_message(phone: str, message: str, sender_role: str = None) -> bool:
    """
    Fonction utilitaire pour envoyer un message WhatsApp
    Compatible avec l'ancienne interface pour les migrations
    
    Args:
        phone: Numéro de téléphone
        message: Message à envoyer
        sender_role: Rôle de l'expéditeur
    
    Returns:
        bool: Succès de l'envoi
    """
    success, msg, msg_id = wachap_service.send_message(phone, message, sender_role)
    return success


def send_whatsapp_otp(phone: str, otp_code: str) -> Tuple[bool, str]:
    """
    Fonction utilitaire pour envoyer un OTP via l'instance système WhatsApp
    Compatible avec l'ancienne interface d'authentification
    
    Args:
        phone: Numéro de téléphone
        otp_code: Code OTP à envoyer
    
    Returns:
        Tuple[bool, str]: (succès, message)
    """
    from django.conf import settings
    
    # Redirection vers numéro de test en mode développement
    dev_mode = getattr(settings, 'DEBUG', False)
    admin_phone = getattr(settings, 'ADMIN_PHONE', '').strip()
    # En dev, ne rediriger que si ADMIN_PHONE est défini explicitement
    test_phone = admin_phone if (dev_mode and admin_phone) else None
    destination_phone = test_phone or phone
    
    # Message OTP avec info du destinataire original en mode dev
    if test_phone and test_phone != phone:
        otp_message = f"""[DEV] Code de vérification TS Air Cargo

Destinataire: {phone}
Code: {otp_code}

Ce code expire dans 10 minutes.
Ne le partagez avec personne.

TS Air Cargo"""
    else:
        otp_message = f"""Code de vérification TS Air Cargo

Code: {otp_code}

Ce code expire dans 10 minutes.
Ne le partagez avec personne.

TS Air Cargo"""
    
    # Utiliser détection automatique avec type OTP
    success, msg, msg_id = wachap_service.send_message_with_type(
        phone=destination_phone, 
        message=otp_message, 
        message_type='otp',  # Force l'instance Système (avec fallback si non configurée)
        sender_role='system'
    )
    
    # Message de retour avec info de redirection
    if success and test_phone and test_phone != phone:
        return success, f"OTP envoyé via instance système vers {destination_phone} (dev mode)"
    else:
        return success, f"OTP envoyé via instance système - {msg}"
