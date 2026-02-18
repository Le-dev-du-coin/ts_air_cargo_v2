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
from .timeout_handler import timeout_handler, circuit_breaker

# Import pour la façade V4
from django.conf import settings
from .wachap_v4_service import wachap_v4_service


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
        if settings.USE_WACHAP_V4:
            # La validation se fait dans le nouveau service
            return
            
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
        2. Messages système (OTP, alertes, évènements système) → Instance Système
        3. OTP selon numéro destinataire pour l'authentification
        4. Notifications standards, router par indicatif du destinataire
        5. Fallback automatique si instance indisponible
        
        Args:
            sender_role: Rôle de l'expéditeur ('agent_chine', 'agent_mali', etc.)
            recipient_phone: Numéro du destinataire
            message_type: Type de message ('otp', 'notification', etc.)
        
        Returns:
            str: 'chine', 'mali' ou 'system'
        """
        preferred_region = 'mali'  # Défaut global
        
        # PRIORITÉ 1: Agents et Admins utilisent TOUJOURS leur instance régionale (la plus haute priorité)
        if sender_role == 'agent_chine' or sender_role == 'admin_chine':
            preferred_region = 'chine'
            logger.debug(f"Rôle {sender_role} → Instance Chine (prioritaire)")
        elif sender_role == 'agent_mali' or sender_role == 'admin_mali':
            preferred_region = 'mali'
            logger.debug(f"Rôle {sender_role} → Instance Mali (prioritaire)")
        
        # PRIORITÉ 2: Messages système (OTP, alertes, évènements système) → Instance Système
        # Cette vérification vient après les rôles spécifiques des agents/admins pour ne pas les surcharger
        elif sender_role == 'system' or message_type in ['otp', 'alert', 'admin_alert', 'system', 'account']:
            preferred_region = 'system'
            logger.debug(f"Message système ({message_type}) → Instance Système")
        
        # PRIORITÉ 3: OTP d'authentification selon numéro du destinataire
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
        
        # PRIORITÉ 4: Notifications standards, router par indicatif du destinataire
        elif recipient_phone and message_type in ['notification', 'creation_compte', 'colis_arrive', 'colis_livre', 'rapport', 'general']:
            # Note: 'account' a été déplacé dans la priorité 2 (système) car souvent lié à OTP/compte
            clean_phone = recipient_phone.replace('+', '').replace(' ', '')
            if clean_phone.startswith('86'):
                preferred_region = 'chine'
            elif clean_phone.startswith('223'):
                preferred_region = 'mali'
            else:
                preferred_region = 'mali'
        
        # PRIORITÉ 5: Clients et rôles génériques (ou si rien d'autre ne correspond) → Mali par défaut
        elif sender_role in ['client', 'customer', 'user'] or sender_role is None:
            preferred_region = 'mali'
        
        # VÉRIFICATION DISPONIBILITÉ ET FALLBACK
        preferred_config = self.get_config(preferred_region)
        if not preferred_config['access_token'] or not preferred_config['instance_id']:
            logger.warning(f"Instance préférée '{preferred_region}' non configurée ou inactive. Tentative de fallback.")
            
            # Ordre de fallback (exclure la région déjà tentée)
            fallback_order = []
            if preferred_region != 'mali': fallback_order.append('mali')
            if preferred_region != 'chine': fallback_order.append('chine')
            if preferred_region != 'system': fallback_order.append('system')
            
            for fallback_reg in fallback_order:
                fallback_config = self.get_config(fallback_reg)
                if fallback_config['access_token'] and fallback_config['instance_id'] and fallback_config['active']:
                    logger.info(f"Fallback réussi vers l'instance '{fallback_reg}'.")
                    return fallback_reg
            
            logger.error(f"Aucune instance WaChap fonctionnelle n'a été trouvée après plusieurs tentatives de fallback. "
                         f"Vérifiez les configurations pour '{preferred_region}' et les fallbacks: {', '.join(fallback_order)}.")
            return preferred_region  # Retourne la région initiale, même si non configurée, pour une erreur explicite.
            
        logger.debug(f"Instance finale utilisée: {preferred_region.title()}")
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
            elif len(clean_phone) == 8 and clean_phone.isdigit():
                # Numéro malien sur 8 chiffres (76543210) → +22376543210
                clean_phone = '+223' + clean_phone
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
        Envoie un message texte via WaChap avec monitoring automatique.
        Cette méthode agit comme une façade pour basculer entre l'ancienne et la nouvelle API.
        """
        # === FAÇADE V4 ===
        if settings.USE_WACHAP_V4:
            logger.debug("Utilisation de WaChap V4 API")
            # Le nouveau service a une logique de détermination de région/compte différente
            return wachap_v4_service.send_message(
                phone=phone,
                message=message,
                sender_role=sender_role,
                region=region
            )
        # =================
        
        # Logique existante de l'ancienne API
        formatted_phone = self.format_phone_number(phone)
        
        if region is None:
            region = self.determine_instance(
                sender_role=sender_role,
                recipient_phone=formatted_phone
            )
        
        attempt_id = None
        start_time = timezone.now()
        
        try:
            from .monitoring import wachap_monitor
            attempt_id = wachap_monitor.record_message_attempt(
                region, formatted_phone, sender_role or 'unknown'
            )
            
            config = self.get_config(region)
            
            if not config['access_token'] or not config['instance_id']:
                error_msg = f"Configuration WaChap {region.title()} incomplète"
                logger.error(error_msg)
                if attempt_id:
                    response_time = (timezone.now() - start_time).total_seconds() * 1000
                    wachap_monitor.record_message_error(attempt_id, 'config_error', error_msg, response_time)
                return False, error_msg, None
            
            if not config['active']:
                error_msg = f"Instance WaChap {region.title()} désactivée"
                logger.warning(error_msg)
                if attempt_id:
                    response_time = (timezone.now() - start_time).total_seconds() * 1000
                    wachap_monitor.record_message_error(attempt_id, 'instance_inactive', error_msg, response_time)
                return False, error_msg, None
            
            payload = {
                "number": formatted_phone.replace('+', ''),
                "type": "text",
                "message": message,
                "instance_id": config['instance_id'],
                "access_token": config['access_token']
            }
            
            try:
                safe_phone = formatted_phone[:-4].replace('+', '*') + formatted_phone[-4:]
                safe_instance = (config['instance_id'][:6] + '...') if config.get('instance_id') else 'missing'
                logger.debug(
                    "WA DEBUG send_message: attempt=%s region=%s role=%s to=%s payload_type=%s instance=%s",
                    attempt_id, region, sender_role, safe_phone, payload.get('type'), safe_instance,
                )
            except Exception:
                pass
            
            response = requests.post(
                f"{self.base_url}/send",
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=15
            )
            
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            
            logger.info(f"WaChap {region.title()} - Envoi vers {formatted_phone}: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    logger.debug(f"WaChap {region} - Réponse API: {json.dumps(response_data, ensure_ascii=False)[:500]}")
                except json.JSONDecodeError as je:
                    logger.error(f"Erreur de décodage JSON de la réponse WaChap: {response.text}")
                    response_data = {"raw": response.text, "error": "invalid_json"}
                except Exception as e:
                    logger.error(f"Erreur inattendue lors du parsing de la réponse: {str(e)}")
                    response_data = {"raw": str(response.text)[:500], "error": "parsing_error"}

                success_flag = False
                top_status = str(response_data.get('status', '')).lower().strip()
                nested_status = ''
                
                if 'message' in response_data and isinstance(response_data['message'], dict):
                    nested_status = str(response_data['message'].get('status', '')).lower().strip()
                
                logger.debug(f"WaChap {region} - Statuts: top={top_status}, nested={nested_status}")
                
                success_flag = (top_status == 'success' or 
                              nested_status == 'success' or 
                              'id' in response_data or 
                              'message_id' in response_data)

                message_id = None
                try:
                    message_id = (
                        response_data.get('id') or
                        response_data.get('message_id') or
                        (response_data.get('message', {}).get('key', {}).get('id') if isinstance(response_data.get('message'), dict) else None) or
                        (response_data.get('data', {}).get('id') if isinstance(response_data.get('data'), dict) else None)
                    )
                    
                    if message_id and not success_flag:
                        success_flag = True
                        logger.info(f"Message considéré comme réussi grâce à la présence d'un ID: {message_id}")
                        
                except Exception as e:
                    logger.error(f"Erreur lors de l'extraction de l'ID du message: {str(e)}")
                    message_id = None

                if success_flag:
                    success_msg = f"Message envoyé via WaChap {region.title()}"
                    if attempt_id:
                        wachap_monitor.record_message_success(attempt_id, response_time, message_id)
                    logger.info(f"{success_msg} - ID: {message_id}")
                    if not message_id:
                        logger.warning(
                            "WA WARN: Réponse 200 sans message_id. attempt=%s region=%s resp_keys=%s resp_raw=%s",
                            attempt_id, region,
                            list(response_data.keys()) if isinstance(response_data, dict) else type(response_data).__name__,
                            str(response_data)[:500],
                        )
                    return True, success_msg, message_id
                else:
                    error_text = response_data.get('message') if not isinstance(response_data.get('message'), dict) else json.dumps(response_data.get('message'))
                    error_msg = f"Erreur WaChap {region.title()} (200/app): {error_text}"
                    if attempt_id:
                        wachap_monitor.record_message_error(attempt_id, 'app_error', error_msg, response_time)
                    logger.error(error_msg)
                    return False, error_msg, None
            else:
                error_msg = f"Erreur WaChap {region.title()}: {response.status_code} - {response.text}"
                if attempt_id:
                    wachap_monitor.record_message_error(attempt_id, f'http_{response.status_code}', error_msg, response_time)
                logger.error(error_msg)
                return False, error_msg, None
                
        except requests.exceptions.Timeout as te:
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            error_type = 'timeout'
            error_details = f"Délai dépassé après {response_time:.0f}ms"
            error_msg = f"{error_type.upper()} - Impossible d'envoyer le message WaChap {region} à {phone}: {error_details}"
            logger.error(error_msg, exc_info=True)
            if attempt_id:
                try:
                    from .monitoring import wachap_monitor
                    wachap_monitor.record_message_error(
                        attempt_id, error_type, f"{error_type.upper()}: {error_details}", response_time
                    )
                except ImportError:
                    logger.error("Impossible d'accéder au module de monitoring")
            return False, error_msg, None
            
        except requests.exceptions.RequestException as re:
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            error_type = 'network_error'
            error_details = f"{type(re).__name__}: {str(re)}"
            error_msg = f"{error_type.upper()} - Échec d'envoi WaChap {region} à {phone}: {error_details}"
            logger.error(error_msg, exc_info=True)
            if isinstance(re, requests.exceptions.ConnectionError):
                error_type = 'connection_error'
            elif isinstance(re, requests.exceptions.SSLError):
                error_type = 'ssl_error'
            
            if attempt_id:
                try:
                    from .monitoring import wachap_monitor
                    wachap_monitor.record_message_error(
                        attempt_id, error_type, f"{error_type.upper()}: {error_details}", response_time
                    )
                except ImportError:
                    logger.error("Impossible d'accéder au module de monitoring")
            return False, error_msg, None
            
        except Exception as e:
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            error_type = 'unexpected_error'
            error_details = f"{type(e).__name__}: {str(e)}"
            error_msg = f"ERREUR INATTENDUE - Échec d'envoi WaChap {region} à {phone}: {error_details}"
            logger.critical(error_msg, exc_info=True)
            
            if attempt_id:
                try:
                    from .monitoring import wachap_monitor
                    wachap_monitor.record_message_error(
                        attempt_id, error_type, f"ERREUR_CRITIQUE: {error_details}", response_time
                    )
                except ImportError:
                    logger.error("Impossible d'accéder au module de monitoring")
            
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
        """
        # === FAÇADE V4 ===
        if settings.USE_WACHAP_V4:
            logger.debug("Utilisation de WaChap V4 API pour send_media")
            return wachap_v4_service.send_media(
                phone=phone,
                message=message,
                media_url=media_url,
                filename=filename,
                sender_role=sender_role,
                region=region
            )
        # =================
        
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
    
    # Messages de retour user-friendly (masquer WaChap)
    if success:
        if test_phone and test_phone != phone:
            return success, f"Code envoyé vers {destination_phone} (mode dev)"
        else:
            return success, "Code de vérification envoyé avec succès"
    else:
        # Masquer les détails techniques dans les messages d'erreur
        if "wachap" in msg.lower():
            # Nettoyer les références à WaChap
            cleaned_msg = msg.replace("WaChap System", "système").replace("WaChap Mali", "système").replace("WaChap Chine", "système")
            cleaned_msg = cleaned_msg.replace("WaChap", "système").replace("wachap", "système")
            return success, cleaned_msg
        else:
            return success, msg
