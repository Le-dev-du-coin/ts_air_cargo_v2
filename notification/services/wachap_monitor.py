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
                "account_id": config.wachap_account_chine,
                "name": "Instance Chine 🇨🇳",
                "description": "Notifications et agents Chine",
            },
            "mali": {
                "account_id": config.wachap_account_mali,
                "name": "Instance Mali 🇲🇱",
                "description": "Notifications et agents Mali",
            },
            "cote_divoire": {
                "account_id": config.wachap_account_cote_divoire,
                "name": "Instance Côte d'Ivoire 🇨🇮",
                "description": "Notifications et agents Côte d'Ivoire",
            },
            "system": {
                "account_id": config.wachap_account_system,
                "name": "Instance Système ⚙️",
                "description": "OTP et alertes administrateur",
            },
        }

    def check_all_instances(self) -> Dict[str, Dict]:
        """Vérifie le statut de toutes les instances en un seul appel API"""
        results = {}
        instances = self._get_instances()
        config = self._get_config()
        secret_key = config.wachap_v4_secret_key

        if not secret_key:
            for region in instances.keys():
                results[region] = {
                    "region": region,
                    "connected": False,
                    "error": "Clé secrète V4 manquante",
                    "timestamp": timezone.now().isoformat(),
                }
            return results

        # Appel API général pour récupérer tous les comptes
        headers = {
            "Authorization": f"Bearer {secret_key}",
        }
        api_accounts = []
        api_error = None

        try:
            response = requests.get(
                "https://api.wachap.com/v1/whatsapp/accounts",
                headers=headers,
                timeout=15,
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    api_accounts = data.get("accounts", [])
                else:
                    api_error = data.get("message", "Erreur API inconnue")
            elif response.status_code in (401, 403):
                api_error = "Clé secrète invalide ou expirée (401/403)"
            else:
                api_error = f"HTTP {response.status_code}"
        except requests.exceptions.Timeout:
            api_error = "Timeout de connexion (>15s)"
        except Exception as e:
            api_error = f"Erreur réseau: {str(e)}"

        for region, instance in instances.items():
            account_id = instance.get("account_id", "")
            if not account_id:
                results[region] = {
                    "region": region,
                    "connected": False,
                    "error": "Account ID non configuré",
                    "timestamp": timezone.now().isoformat(),
                }
                continue

            if api_error:
                results[region] = {
                    "region": region,
                    "connected": False,
                    "error": api_error,
                    "timestamp": timezone.now().isoformat(),
                }
                continue

            # Chercher le compte dans la liste renvoyée par l'API
            account_data = next(
                (acc for acc in api_accounts if acc.get("id") == account_id), None
            )

            if not account_data:
                results[region] = {
                    "region": region,
                    "connected": False,
                    "error": "Introuvable sur WaChap",
                    "timestamp": timezone.now().isoformat(),
                }
                continue

            status = account_data.get("status")
            if status == "connected":
                results[region] = {
                    "region": region,
                    "connected": True,
                    "message": "Connecté",
                    "timestamp": timezone.now().isoformat(),
                }
            else:
                results[region] = {
                    "region": region,
                    "connected": False,
                    "error": f"Déconnecté ({status})",
                    "timestamp": timezone.now().isoformat(),
                }

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
            reconnected_instances = []

            for region, status in all_status.items():
                prev_cache_key = f"wachap_prev_connected_{region}"
                was_connected = cache.get(
                    prev_cache_key, True
                )  # Suppose connecté par défaut

                if status["connected"]:
                    connected_count += 1
                    # Si on était déconnecté avant → reconnexion → déclencher retry
                    if not was_connected:
                        reconnected_instances.append(region)
                        logger.info(
                            f"✅ Instance {region} reconnectée ! Déclenchement du retry..."
                        )
                    cache.set(
                        prev_cache_key,
                        True,
                        timeout=4
                        * 3600,  # 4h pour survivre aux checks toutes les 15min
                    )
                else:
                    disconnected_instances.append((region, status))
                    cache.set(
                        prev_cache_key,
                        False,
                        timeout=4
                        * 3600,  # 4h — évite les fausses alertes au redémarrage
                    )

            # Envoyer alertes pour les instances déconnectées
            for region, status in disconnected_instances:
                self.send_disconnect_alert(region, status)

            # Déclencher le retry des messages en attente pour les instances reconnectées
            if reconnected_instances:
                try:
                    from notification.tasks import retry_failed_notifications_periodic

                    retry_failed_notifications_periodic.delay()
                    logger.info(
                        f"File d'attente relancée suite à reconnexion : {reconnected_instances}"
                    )
                except Exception as e:
                    logger.error(f"Erreur déclenchement retry après reconnexion: {e}")

            total_instances = len(self._get_instances())
            summary = f"Monitoring terminé: {connected_count}/{total_instances} instances connectées"
            logger.info(summary)

            return all_status

        except Exception as e:
            logger.error(f"Erreur monitoring WaChap: {e}")
            return {}


# Instance globale
wachap_monitor = WaChapMonitor()
