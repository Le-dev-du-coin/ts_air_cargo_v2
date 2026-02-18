"""
Service de monitoring des instances WaChap avec alertes automatiques
Surveille l'état des connexions WhatsApp et envoie des alertes admin
"""

import requests
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone
from typing import Dict, List, Tuple, Optional
import json

logger = logging.getLogger(__name__)


class WaChapMonitor:
    """
    Système de monitoring des instances WaChap avec alertes automatiques
    """
    
    def __init__(self):
        """Initialise le monitoring avec les configurations"""
        self.base_url = "https://wachap.app/api"
        self.instances = {
            'chine': {
                'access_token': getattr(settings, 'WACHAP_CHINE_ACCESS_TOKEN', ''),
                'instance_id': getattr(settings, 'WACHAP_CHINE_INSTANCE_ID', ''),
                'name': 'Instance Chine',
                'description': 'Instance WhatsApp pour les agents et notifications Chine'
            },
            'mali': {
                'access_token': getattr(settings, 'WACHAP_MALI_ACCESS_TOKEN', ''),
                'instance_id': getattr(settings, 'WACHAP_MALI_INSTANCE_ID', ''),
                'name': 'Instance Mali', 
                'description': 'Instance WhatsApp pour les agents et notifications Mali'
            },
            'system': {
                'access_token': getattr(settings, 'WACHAP_SYSTEM_ACCESS_TOKEN', ''),
                'instance_id': getattr(settings, 'WACHAP_SYSTEM_INSTANCE_ID', ''),
                'name': 'Instance Système',
                'description': 'Instance WhatsApp pour les OTP et alertes administrateur'
            }
        }
        
        # Configuration des alertes admin
        self.admin_email = getattr(settings, 'ADMIN_EMAIL', '')
        self.admin_phone = getattr(settings, 'ADMIN_PHONE', '')
        self.admin_name = getattr(settings, 'ADMIN_NAME', 'Admin TS Air Cargo')
        
        # Paramètres d'alerte
        self.check_interval_minutes = 15  # Vérifier toutes les 15 minutes
        self.alert_cooldown_hours = 2     # Éviter le spam d'alertes
        
    def check_instance_status(self, region: str) -> Dict:
        """
        Vérifie le statut d'une instance WaChap spécifique
        
        Args:
            region: 'chine', 'mali' ou 'system'
            
        Returns:
            dict: État de l'instance avec détails
        """
        instance = self.instances.get(region)
        if not instance:
            return {
                'region': region,
                'connected': False,
                'error': 'Instance non configurée',
                'timestamp': timezone.now().isoformat()
            }
        
        if not instance['access_token'] or not instance['instance_id']:
            return {
                'region': region,
                'connected': False,
                'error': 'Tokens manquants',
                'timestamp': timezone.now().isoformat()
            }
        
        try:
            # Test de connexion avec message test
            payload = {
                'number': '22373451676',  # Numéro admin pour test
                'type': 'text',
                'message': f'[MONITORING] Test connexion {instance["name"]} - {datetime.now().strftime("%H:%M")}',
                'instance_id': instance['instance_id'],
                'access_token': instance['access_token']
            }
            
            response = requests.post(
                f"{self.base_url}/send",
                json=payload,
                timeout=15
            )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    if data.get('status') == 'success':
                        return {
                            'region': region,
                            'connected': True,
                            'message': 'Instance connectée et fonctionnelle',
                            'response': data,
                            'timestamp': timezone.now().isoformat()
                        }
                    else:
                        error_msg = data.get('message', 'Erreur inconnue')
                        return {
                            'region': region,
                            'connected': False,
                            'error': error_msg,
                            'response': data,
                            'timestamp': timezone.now().isoformat()
                        }
                except json.JSONDecodeError:
                    return {
                        'region': region,
                        'connected': False,
                        'error': 'Réponse non-JSON (page HTML reçue)',
                        'timestamp': timezone.now().isoformat()
                    }
            else:
                return {
                    'region': region,
                    'connected': False,
                    'error': f'HTTP {response.status_code}',
                    'timestamp': timezone.now().isoformat()
                }
                
        except requests.exceptions.Timeout:
            return {
                'region': region,
                'connected': False,
                'error': 'Timeout de connexion',
                'timestamp': timezone.now().isoformat()
            }
        except Exception as e:
            return {
                'region': region,
                'connected': False,
                'error': f'Erreur de connexion: {str(e)}',
                'timestamp': timezone.now().isoformat()
            }
    
    def check_all_instances(self) -> Dict[str, Dict]:
        """
        Vérifie le statut de toutes les instances
        
        Returns:
            dict: État de toutes les instances
        """
        results = {}
        
        for region in self.instances.keys():
            logger.info(f"Vérification instance {region}...")
            results[region] = self.check_instance_status(region)
            
        return results
    
    def should_send_alert(self, region: str) -> bool:
        """
        Vérifie si une alerte doit être envoyée (évite le spam)
        
        Args:
            region: Instance concernée
            
        Returns:
            bool: True si alerte doit être envoyée
        """
        cache_key = f"wachap_alert_sent_{region}"
        last_alert = cache.get(cache_key)
        
        if last_alert:
            last_alert_time = datetime.fromisoformat(last_alert)
            time_diff = timezone.now() - last_alert_time.replace(tzinfo=timezone.now().tzinfo)
            
            if time_diff < timedelta(hours=self.alert_cooldown_hours):
                logger.info(f"Alerte {region} en cooldown encore {self.alert_cooldown_hours - time_diff.total_seconds()/3600:.1f}h")
                return False
        
        return True
    
    def mark_alert_sent(self, region: str):
        """
        Marque qu'une alerte a été envoyée pour éviter le spam
        
        Args:
            region: Instance concernée
        """
        cache_key = f"wachap_alert_sent_{region}"
        cache.set(cache_key, timezone.now().isoformat(), timeout=self.alert_cooldown_hours * 3600)
    
    def send_disconnect_alert(self, region: str, status: Dict):
        """
        Envoie une alerte de déconnexion par email et console
        
        Args:
            region: Instance déconnectée
            status: Détails du statut
        """
        if not self.should_send_alert(region):
            return
        
        instance = self.instances[region]
        
        # Préparer le message d'alerte
        subject = f"🚨 ALERTE: Instance WhatsApp {instance['name']} déconnectée"
        
        message = f"""
🚨 ALERTE SYSTÈME TS AIR CARGO

Instance WhatsApp déconnectée détectée !

📋 DÉTAILS:
• Instance: {instance['name']} ({region.upper()})
• Description: {instance['description']}
• Statut: DÉCONNECTÉE ❌
• Erreur: {status.get('error', 'Inconnue')}
• Timestamp: {status.get('timestamp', 'Non disponible')}

🔧 ACTION REQUISE:
1. Connectez-vous sur https://wachap.app
2. Allez dans votre dashboard
3. Trouvez l'instance {instance['name']}
4. Cliquez sur "QR Code" ou "Reconnecter"
5. Scannez avec WhatsApp (Paramètres > Appareils connectés)

⚠️ IMPACT:
Cette déconnexion affecte:
- Les codes OTP pour l'authentification
- Les notifications clients
- Les alertes système

🕐 Prochaine vérification dans {self.check_interval_minutes} minutes.

---
TS Air Cargo - Système de monitoring automatique
{timezone.now().strftime('%d/%m/%Y à %H:%M:%S')}
        """.strip()
        
        # Envoyer par email si configuré
        email_sent = False
        if self.admin_email:
            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@ts-aircargo.com'),
                    recipient_list=[self.admin_email],
                    fail_silently=False,
                )
                email_sent = True
                logger.info(f"Alerte email envoyée à {self.admin_email}")
            except Exception as e:
                logger.error(f"Erreur envoi email d'alerte: {e}")
        
        # Envoyer par WhatsApp via autre instance si possible
        whatsapp_sent = False
        if self.admin_phone:
            whatsapp_sent = self.send_whatsapp_alert(region, message)
        
        # Log système
        alert_summary = f"🚨 ALERTE: Instance {region.upper()} déconnectée | Email: {'✅' if email_sent else '❌'} | WhatsApp: {'✅' if whatsapp_sent else '❌'}"
        logger.critical(alert_summary)
        print(f"\n{alert_summary}")
        print(f"Erreur: {status.get('error')}")
        
        # Marquer comme envoyé
        self.mark_alert_sent(region)
        
        # Sauvegarder l'historique des alertes
        self.save_alert_history(region, status, email_sent, whatsapp_sent)
    
    def send_whatsapp_alert(self, failed_region: str, message: str) -> bool:
        """
        Envoie l'alerte par WhatsApp via une autre instance fonctionnelle
        
        Args:
            failed_region: Instance qui a échoué
            message: Message d'alerte
            
        Returns:
            bool: Succès de l'envoi
        """
        # Trouver une instance fonctionnelle pour envoyer l'alerte
        for region, instance in self.instances.items():
            if region == failed_region:
                continue  # Éviter l'instance défaillante
                
            if not instance['access_token'] or not instance['instance_id']:
                continue
            
            try:
                payload = {
                    'number': self.admin_phone.replace('+', ''),
                    'type': 'text',
                    'message': f"🚨 ALERTE WHATSAPP DÉCONNECTÉ\n\n{message}",
                    'instance_id': instance['instance_id'],
                    'access_token': instance['access_token']
                }
                
                response = requests.post(
                    f"{self.base_url}/send",
                    json=payload,
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'success':
                        logger.info(f"Alerte WhatsApp envoyée via instance {region}")
                        return True
                        
            except Exception as e:
                logger.warning(f"Impossible d'envoyer alerte via instance {region}: {e}")
                continue
        
        logger.warning("Aucune instance WhatsApp disponible pour envoyer l'alerte")
        return False
    
    def save_alert_history(self, region: str, status: Dict, email_sent: bool, whatsapp_sent: bool):
        """
        Sauvegarde l'historique des alertes dans le cache
        
        Args:
            region: Instance concernée
            status: Statut de l'instance
            email_sent: Si email envoyé
            whatsapp_sent: Si WhatsApp envoyé
        """
        history_key = "wachap_alert_history"
        history = cache.get(history_key, [])
        
        alert_record = {
            'timestamp': timezone.now().isoformat(),
            'region': region,
            'instance_name': self.instances[region]['name'],
            'error': status.get('error'),
            'email_sent': email_sent,
            'whatsapp_sent': whatsapp_sent,
            'admin_email': self.admin_email,
            'admin_phone': self.admin_phone
        }
        
        history.append(alert_record)
        
        # Garder seulement les 50 dernières alertes
        if len(history) > 50:
            history = history[-50:]
        
        # Sauvegarder pour 7 jours
        cache.set(history_key, history, timeout=7 * 24 * 3600)
    
    def get_alert_history(self) -> List[Dict]:
        """
        Récupère l'historique des alertes
        
        Returns:
            list: Historique des alertes
        """
        return cache.get("wachap_alert_history", [])
    
    def run_monitoring_check(self):
        """
        Exécute une vérification complète du monitoring
        """
        logger.info("🔍 Démarrage vérification monitoring WaChap...")
        
        try:
            # Vérifier toutes les instances
            all_status = self.check_all_instances()
            
            connected_count = 0
            disconnected_instances = []
            
            for region, status in all_status.items():
                if status['connected']:
                    connected_count += 1
                    logger.info(f"✅ Instance {region}: Connectée")
                else:
                    disconnected_instances.append((region, status))
                    logger.warning(f"❌ Instance {region}: Déconnectée - {status.get('error')}")
            
            # Envoyer alertes pour les instances déconnectées
            for region, status in disconnected_instances:
                self.send_disconnect_alert(region, status)
            
            # Résumé
            total_instances = len(self.instances)
            summary = f"Monitoring terminé: {connected_count}/{total_instances} instances connectées"
            
            if disconnected_instances:
                logger.critical(summary)
                logger.critical(f"Instances déconnectées: {[r for r, s in disconnected_instances]}")
            else:
                logger.info(summary)
            
            # Sauvegarder le dernier check
            cache.set('last_wachap_monitoring_check', {
                'timestamp': timezone.now().isoformat(),
                'connected_count': connected_count,
                'total_instances': total_instances,
                'disconnected_instances': [r for r, s in disconnected_instances],
                'all_status': all_status
            }, timeout=24 * 3600)
            
            return all_status
            
        except Exception as e:
            logger.error(f"Erreur lors du monitoring WaChap: {e}")
            return {}
    
    def get_monitoring_status(self) -> Dict:
        """
        Récupère le statut du dernier monitoring
        
        Returns:
            dict: Statut du monitoring
        """
        return cache.get('last_wachap_monitoring_check', {})


# Instance globale du monitor
wachap_monitor = WaChapMonitor()


def run_wachap_monitoring():
    """
    Fonction utilitaire pour lancer le monitoring
    """
    return wachap_monitor.run_monitoring_check()


def get_wachap_monitoring_status():
    """
    Fonction utilitaire pour récupérer le statut
    """
    return wachap_monitor.get_monitoring_status()


def get_wachap_alert_history():
    """
    Fonction utilitaire pour récupérer l'historique des alertes
    """
    return wachap_monitor.get_alert_history()
