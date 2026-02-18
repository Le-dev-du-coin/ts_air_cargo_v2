"""
Système de monitoring avec alertes automatiques pour TS Air Cargo
Surveille les métriques critiques et envoie des alertes admin automatiquement

Métriques surveillées:
- Échecs OTP répétés
- Pannes instances WhatsApp  
- Erreurs de base de données
- Exceptions système non gérées
- Performance dégradée
"""

import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from django.utils import timezone
from django.core.cache import cache
from django.db import connections
from .admin_alerts import admin_alerts

logger = logging.getLogger(__name__)


class SystemMonitor:
    """
    Moniteur système principal avec alertes automatiques
    """
    
    def __init__(self):
        """Initialise le moniteur"""
        self.is_monitoring = False
        self.monitor_thread = None
        
        # Compteurs pour les métriques
        self.otp_failures = deque(maxlen=100)  # Derniers 100 échecs OTP
        self.whatsapp_failures = defaultdict(int)  # Échecs par instance
        self.db_errors = deque(maxlen=50)  # Dernières 50 erreurs DB
        self.system_exceptions = deque(maxlen=50)  # Dernières 50 exceptions
        
        # Métriques de performance
        self.response_times = defaultdict(lambda: deque(maxlen=100))
        self.last_health_check = timezone.now()
        
        # États des alertes pour éviter le spam
        self.alert_states = {
            'otp_failures': False,
            'whatsapp_china_down': False,
            'whatsapp_mali_down': False,
            'whatsapp_system_down': False,
            'db_errors': False,
            'high_exception_rate': False
        }
    
    def start_monitoring(self):
        """Démarre le monitoring en arrière-plan"""
        if self.is_monitoring:
            logger.warning("Monitoring déjà en cours")
            return
        
        self.is_monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("🔍 Monitoring système démarré")
        
        # Alerte de démarrage
        admin_alerts.send_critical_alert(
            title="Monitoring Système Démarré",
            message="Le système de monitoring et d'alertes automatiques a été démarré avec succès.",
            alert_type="INFO"
        )
    
    def stop_monitoring(self):
        """Arrête le monitoring"""
        if not self.is_monitoring:
            return
        
        self.is_monitoring = False
        logger.info("🔍 Monitoring système arrêté")
    
    def _monitor_loop(self):
        """Boucle principale de monitoring"""
        while self.is_monitoring:
            try:
                self._check_otp_failures()
                self._check_whatsapp_health()
                self._check_database_health()
                self._check_exception_rate()
                self._update_health_status()
                
                # Pause entre vérifications
                time.sleep(60)  # Vérification toutes les minutes
                
            except Exception as e:
                logger.error(f"Erreur dans la boucle de monitoring: {str(e)}")
                self.record_system_exception(e, "Monitoring Loop")
                time.sleep(30)  # Pause plus courte en cas d'erreur
    
    def record_otp_failure(self, phone: str, reason: str = "Unknown"):
        """Enregistre un échec d'OTP"""
        failure_data = {
            'timestamp': timezone.now(),
            'phone': phone,
            'reason': reason
        }
        self.otp_failures.append(failure_data)
        logger.debug(f"OTP échec enregistré: {phone} - {reason}")
    
    def record_whatsapp_failure(self, instance: str, error_message: str = ""):
        """Enregistre un échec WhatsApp"""
        self.whatsapp_failures[instance] += 1
        failure_key = f"whatsapp_failure_{instance}_{timezone.now().date()}"
        cache.set(failure_key, self.whatsapp_failures[instance], timeout=86400)  # 24h
        logger.debug(f"Échec WhatsApp enregistré: {instance} - {error_message}")
    
    def record_whatsapp_success(self, instance: str):
        """Enregistre un succès WhatsApp (reset compteur)"""
        if self.whatsapp_failures[instance] > 0:
            self.whatsapp_failures[instance] = max(0, self.whatsapp_failures[instance] - 1)
        
        # Reset état d'alerte si retour à la normale
        alert_key = f'whatsapp_{instance}_down'
        if alert_key in self.alert_states and self.alert_states[alert_key]:
            self.alert_states[alert_key] = False
            admin_alerts.send_critical_alert(
                title=f"Instance WhatsApp {instance.title()} Récupérée",
                message=f"L'instance WhatsApp {instance} fonctionne à nouveau normalement.",
                alert_type="INFO"
            )
    
    def record_db_error(self, error_message: str, query_info: str = None):
        """Enregistre une erreur de base de données"""
        error_data = {
            'timestamp': timezone.now(),
            'message': error_message,
            'query': query_info
        }
        self.db_errors.append(error_data)
        logger.warning(f"Erreur DB enregistrée: {error_message}")
    
    def record_system_exception(self, exception: Exception, context: str = None):
        """Enregistre une exception système"""
        exception_data = {
            'timestamp': timezone.now(),
            'exception': str(exception),
            'type': type(exception).__name__,
            'context': context
        }
        self.system_exceptions.append(exception_data)
        logger.error(f"Exception système enregistrée: {str(exception)}")
    
    def record_response_time(self, operation: str, response_time_ms: float):
        """Enregistre un temps de réponse"""
        self.response_times[operation].append({
            'timestamp': timezone.now(),
            'response_time': response_time_ms
        })
    
    def _check_otp_failures(self):
        """Vérifie les échecs OTP répétés"""
        if not self.otp_failures:
            return
        
        # Compter les échecs dans la dernière heure
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_failures = [f for f in self.otp_failures if f['timestamp'] > one_hour_ago]
        
        if len(recent_failures) >= admin_alerts.failed_otp_threshold:
            if not self.alert_states['otp_failures']:
                self.alert_states['otp_failures'] = True
                admin_alerts.alert_failed_otp_threshold(len(recent_failures), "1 heure")
        else:
            self.alert_states['otp_failures'] = False
    
    def _check_whatsapp_health(self):
        """Vérifie l'état des instances WhatsApp"""
        instances = ['chine', 'mali', 'system']
        
        for instance in instances:
            consecutive_failures = self.whatsapp_failures.get(instance, 0)
            alert_key = f'whatsapp_{instance}_down'
            
            if consecutive_failures >= admin_alerts.whatsapp_failure_threshold:
                if not self.alert_states[alert_key]:
                    self.alert_states[alert_key] = True
                    admin_alerts.alert_whatsapp_instance_down(instance.title(), consecutive_failures)
            elif consecutive_failures == 0:
                self.alert_states[alert_key] = False
    
    def _check_database_health(self):
        """Vérifie l'état de la base de données"""
        try:
            # Test simple de connexion
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                
            # Si nous arrivons ici, la DB fonctionne
            if self.alert_states.get('db_connection_lost', False):
                self.alert_states['db_connection_lost'] = False
                admin_alerts.send_critical_alert(
                    title="Connexion Base de Données Récupérée",
                    message="La connexion à la base de données fonctionne à nouveau normalement.",
                    alert_type="INFO"
                )
                
        except Exception as e:
            if not self.alert_states.get('db_connection_lost', False):
                self.alert_states['db_connection_lost'] = True
                admin_alerts.alert_database_error(str(e), "Test de connexion monitoring")
    
    def _check_exception_rate(self):
        """Vérifie le taux d'exceptions système"""
        if not self.system_exceptions:
            return
        
        # Compter les exceptions dans les 10 dernières minutes
        ten_minutes_ago = timezone.now() - timedelta(minutes=10)
        recent_exceptions = [e for e in self.system_exceptions if e['timestamp'] > ten_minutes_ago]
        
        # Si plus de 5 exceptions en 10 minutes, c'est critique
        if len(recent_exceptions) >= 5:
            if not self.alert_states['high_exception_rate']:
                self.alert_states['high_exception_rate'] = True
                admin_alerts.send_critical_alert(
                    title="Taux d'Exceptions Système Élevé",
                    message=f"{len(recent_exceptions)} exceptions système en 10 minutes. Investigation requise.",
                    error_details=f"Dernières exceptions: {[e['exception'] for e in recent_exceptions[-3:]]}",
                    alert_type="CRITICAL"
                )
        else:
            self.alert_states['high_exception_rate'] = False
    
    def _update_health_status(self):
        """Met à jour le statut général de santé du système"""
        self.last_health_check = timezone.now()
        
        # Statistiques générales
        cache.set('system_health_last_check', self.last_health_check, timeout=300)
        cache.set('system_health_otp_failures_hour', len([
            f for f in self.otp_failures 
            if f['timestamp'] > timezone.now() - timedelta(hours=1)
        ]), timeout=300)
        cache.set('system_health_active_alerts', sum(1 for state in self.alert_states.values() if state), timeout=300)
    
    def get_system_status(self) -> Dict[str, Any]:
        """Retourne le statut complet du système"""
        one_hour_ago = timezone.now() - timedelta(hours=1)
        ten_minutes_ago = timezone.now() - timedelta(minutes=10)
        
        return {
            'monitoring_active': self.is_monitoring,
            'last_health_check': self.last_health_check,
            'alerts_active': sum(1 for state in self.alert_states.values() if state),
            'metrics': {
                'otp_failures_last_hour': len([f for f in self.otp_failures if f['timestamp'] > one_hour_ago]),
                'whatsapp_failures': dict(self.whatsapp_failures),
                'db_errors_last_hour': len([e for e in self.db_errors if e['timestamp'] > one_hour_ago]),
                'exceptions_last_10min': len([e for e in self.system_exceptions if e['timestamp'] > ten_minutes_ago])
            },
            'alert_states': self.alert_states
        }
    
    def get_health_summary(self) -> str:
        """Retourne un résumé textuel de l'état du système"""
        status = self.get_system_status()
        
        if status['alerts_active'] == 0:
            return "🟢 Système en bonne santé"
        elif status['alerts_active'] <= 2:
            return "🟡 Système avec alertes mineures"
        else:
            return "🔴 Système avec problèmes critiques"


# Instance globale du moniteur
system_monitor = SystemMonitor()


# Décorateur pour monitorer automatiquement les fonctions
def monitor_performance(operation_name: str):
    """
    Décorateur pour monitorer la performance d'une opération
    
    Usage:
    @monitor_performance("envoi_otp")
    def send_otp(phone, code):
        # code de la fonction
        pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                response_time = (time.time() - start_time) * 1000  # en ms
                system_monitor.record_response_time(operation_name, response_time)
                return result
            except Exception as e:
                system_monitor.record_system_exception(e, f"Fonction: {func.__name__}")
                raise
        return wrapper
    return decorator


# Fonctions utilitaires
def start_system_monitoring():
    """Démarre le monitoring système"""
    system_monitor.start_monitoring()


def stop_system_monitoring():
    """Arrête le monitoring système"""
    system_monitor.stop_monitoring()


def get_system_health() -> Dict[str, Any]:
    """Retourne l'état de santé du système"""
    return system_monitor.get_system_status()


def send_test_alert():
    """Envoie une alerte de test"""
    return admin_alerts.test_alert_system()
