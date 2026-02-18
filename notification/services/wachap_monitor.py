import requests
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone
from typing import Dict, List, Tuple, Optional
import json
from ..models import ConfigurationNotification

logger = logging.getLogger(__name__)


class WaChapMonitor:
    """
    Système de monitoring des instances WaChap avec alertes automatiques
    """

    def __init__(self):
        """Initialise le monitoring avec les configurations"""
        self.base_url = "https://wachap.app/api"
        # Les instances sont récupérées dynamiquement via _get_config

        # Paramètres d'alerte
        self.check_interval_minutes = 15  # Vérifier toutes les 15 minutes
        self.alert_cooldown_hours = 2  # Éviter le spam d'alertes

    def _get_config(self):
        return ConfigurationNotification.get_solo()

    def _get_instances(self):
        config = self._get_config()
        return {
            "chine": {
                "access_token": config.wachap_chine_access_token,
                "instance_id": config.wachap_chine_instance_id,
                "name": "Instance Chine",
                "description": "Instance WhatsApp pour les agents et notifications Chine",
            },
            "mali": {
                "access_token": config.wachap_mali_access_token,
                "instance_id": config.wachap_mali_instance_id,
                "name": "Instance Mali",
                "description": "Instance WhatsApp pour les agents et notifications Mali",
            },
            "system": {
                "access_token": config.wachap_system_access_token,
                "instance_id": config.wachap_system_instance_id,
                "name": "Instance Système",
                "description": "Instance WhatsApp pour les OTP et alertes administrateur",
            },
        }

    def check_instance_status(self, region: str) -> Dict:
        """
        Vérifie le statut d'une instance WaChap spécifique
        """
        instances = self._get_instances()
        instance = instances.get(region)

        if not instance:
            return {
                "region": region,
                "connected": False,
                "error": "Instance non trouvée",
                "timestamp": timezone.now().isoformat(),
            }

        if not instance["access_token"] or not instance["instance_id"]:
            return {
                "region": region,
                "connected": False,
                "error": "Tokens manquants",
                "timestamp": timezone.now().isoformat(),
            }

        try:
            # Test de connexion avec message test vers admin (ou numero fictif si pas d'admin)
            config = self._get_config()
            admin_phone = config.developer_phone or getattr(
                settings, "ADMIN_PHONE", "22373451676"
            )

            payload = {
                "number": admin_phone.replace("+", ""),
                "type": "text",
                "message": f'[MONITORING] Test connexion {instance["name"]} - {datetime.now().strftime("%H:%M")}',
                "instance_id": instance["instance_id"],
                "access_token": instance["access_token"],
            }

            # NOTE: L'endpoint /send envoie réellement un message. Pour juste checker le status,
            # WaChap a peut-être un endpoint /status ou /profile.
            # V1 utilisait /send. On garde ça pour l'instant.
            response = requests.post(f"{self.base_url}/send", json=payload, timeout=15)

            if response.status_code == 200:
                try:
                    data = response.json()

                    if data.get("status") == "success":
                        return {
                            "region": region,
                            "connected": True,
                            "message": "Instance connectée et fonctionnelle",
                            "response": data,
                            "timestamp": timezone.now().isoformat(),
                        }
                    else:
                        error_msg = data.get("message", "Erreur inconnue")
                        return {
                            "region": region,
                            "connected": False,
                            "error": error_msg,
                            "response": data,
                            "timestamp": timezone.now().isoformat(),
                        }
                except json.JSONDecodeError:
                    return {
                        "region": region,
                        "connected": False,
                        "error": "Réponse non-JSON (page HTML reçue)",
                        "timestamp": timezone.now().isoformat(),
                    }
            else:
                return {
                    "region": region,
                    "connected": False,
                    "error": f"HTTP {response.status_code}",
                    "timestamp": timezone.now().isoformat(),
                }

        except requests.exceptions.Timeout:
            return {
                "region": region,
                "connected": False,
                "error": "Timeout de connexion",
                "timestamp": timezone.now().isoformat(),
            }
        except Exception as e:
            return {
                "region": region,
                "connected": False,
                "error": f"Erreur de connexion: {str(e)}",
                "timestamp": timezone.now().isoformat(),
            }

    def check_all_instances(self) -> Dict[str, Dict]:
        """Vérifie le statut de toutes les instances"""
        results = {}
        instances = self._get_instances()

        for region in instances.keys():
            logger.info(f"Vérification instance {region}...")
            results[region] = self.check_instance_status(region)

        return results

    def should_send_alert(self, region: str) -> bool:
        """Vérifie si une alerte doit être envoyée (anti-spam)"""
        cache_key = f"wachap_alert_sent_{region}"
        last_alert = cache.get(cache_key)

        if last_alert:
            last_alert_time = datetime.fromisoformat(last_alert)
            time_diff = timezone.now() - last_alert_time.replace(
                tzinfo=timezone.now().tzinfo
            )

            if time_diff < timedelta(hours=self.alert_cooldown_hours):
                logger.info(
                    f"Alerte {region} en cooldown encore {self.alert_cooldown_hours - time_diff.total_seconds()/3600:.1f}h"
                )
                return False

        return True

    def mark_alert_sent(self, region: str):
        """Marque qu'une alerte a été envoyée"""
        cache_key = f"wachap_alert_sent_{region}"
        cache.set(
            cache_key,
            timezone.now().isoformat(),
            timeout=self.alert_cooldown_hours * 3600,
        )

    def send_disconnect_alert(self, region: str, status: Dict):
        """Envoie une alerte de déconnexion via AlertSystem"""
        if not self.should_send_alert(region):
            return

        from .alert_system import alert_system

        instances = self._get_instances()
        instance = instances.get(region, {"name": region})

        title = f"Instance WhatsApp {instance['name']} déconnectée"
        message = f"L'instance {region.upper()} est inaccessible.\nErreur: {status.get('error')}\nTimestamp: {status.get('timestamp')}"

        # Envoie l'alerte via le système unifié
        alert_system.send_critical_alert(
            title=title, message=message, alert_type="CRITICAL"
        )

        self.mark_alert_sent(region)

    def run_monitoring_check(self):
        """Exécute une vérification complète du monitoring"""
        logger.info("🔍 Démarrage vérification monitoring WaChap...")

        try:
            all_status = self.check_all_instances()

            connected_count = 0
            disconnected_instances = []

            for region, status in all_status.items():
                if status["connected"]:
                    connected_count += 1
                else:
                    disconnected_instances.append((region, status))

            # Envoyer alertes pour les instances déconnectées
            for region, status in disconnected_instances:
                self.send_disconnect_alert(region, status)

            total_instances = len(self._get_instances())
            summary = f"Monitoring terminé: {connected_count}/{total_instances} instances connectées"
            logger.info(summary)

            return all_status

        except Exception as e:
            logger.error(f"Erreur monitoring WaChap: {e}")
            return {}


# Instance globale
wachap_monitor = WaChapMonitor()
