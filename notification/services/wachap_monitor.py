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

    def check_instance_status(self, region: str) -> Dict:
        """
        Vérifie le statut d'un compte WaChap V4 via un appel API léger.
        On utilise l'endpoint /whatsapp/messages/send avec un envoi réel (vers developer_phone).
        """
        instances = self._get_instances()
        instance = instances.get(region)

        if not instance:
            return {
                "region": region,
                "connected": False,
                "error": "Région inconnue",
                "timestamp": timezone.now().isoformat(),
            }

        config = self._get_config()
        secret_key = config.wachap_v4_secret_key
        account_id = instance.get("account_id", "")

        if not secret_key:
            return {
                "region": region,
                "connected": False,
                "error": "Clé secrète V4 manquante",
                "timestamp": timezone.now().isoformat(),
            }

        if not account_id:
            return {
                "region": region,
                "connected": False,
                "error": "Account ID non configuré",
                "timestamp": timezone.now().isoformat(),
            }

        try:
            # Vérification légère : on tente un envoi vers le developer_phone
            # (WaChap V4 n'expose pas d'endpoint /status standalone)
            admin_phone = config.developer_phone or "+22300000000"
            clean_phone = admin_phone.replace(" ", "")
            if not clean_phone.startswith("+"):
                clean_phone = "+" + clean_phone

            headers = {
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "data": {
                    "accountId": account_id,
                    "to": clean_phone,
                    "type": "text",
                    "content": f"[Monitor V4] Vérification {instance['name']}",
                }
            }

            response = requests.post(
                "https://api.wachap.com/v1/whatsapp/messages/send",
                json=payload,
                headers=headers,
                timeout=15,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return {
                        "region": region,
                        "connected": True,
                        "message": "Connecté",
                        "timestamp": timezone.now().isoformat(),
                    }
                return {
                    "region": region,
                    "connected": False,
                    "error": data.get("message", "Erreur API"),
                    "timestamp": timezone.now().isoformat(),
                }

            if response.status_code == 400:
                # 400 = l'API répond → l'instance est joignable.
                # "Numéro invalide" est normal pour un numéro de test fictif.
                # Ce n'est PAS une déconnexion — seul le destinataire est inconnu.
                try:
                    data = response.json()
                    err = data.get("error", {})
                    err_code = err.get("code", "") if isinstance(err, dict) else ""
                    err_msg = (
                        err.get("message", "") if isinstance(err, dict) else str(err)
                    )
                    send_errors = ("SEND_ERROR", "INVALID_PHONE", "RECIPIENT_NOT_FOUND")
                    if (
                        err_code in send_errors
                        or "numéro" in err_msg.lower()
                        or "invalid" in err_msg.lower()
                    ):
                        return {
                            "region": region,
                            "connected": True,
                            "message": "Connecté (compte actif)",
                            "timestamp": timezone.now().isoformat(),
                        }
                    return {
                        "region": region,
                        "connected": False,
                        "error": err_msg or "Erreur 400",
                        "timestamp": timezone.now().isoformat(),
                    }
                except Exception:
                    # Réponse 400 mais parsable → l'API répond = connecté
                    return {
                        "region": region,
                        "connected": True,
                        "message": "Connecté",
                        "timestamp": timezone.now().isoformat(),
                    }

            if response.status_code in (401, 403):
                return {
                    "region": region,
                    "connected": False,
                    "error": "Clé secrète invalide ou expirée (401/403)",
                    "timestamp": timezone.now().isoformat(),
                }

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
