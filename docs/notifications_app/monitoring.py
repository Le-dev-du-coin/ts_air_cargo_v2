"""
Système de monitoring pour WaChap
Surveillance des envois, métriques, alertes et rapports
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from django.core.cache import cache
from django.conf import settings
from django.db import models
from django.utils import timezone
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class WaChapMetrics:
    """Structure des métriques WaChap"""
    instance: str
    success_count: int = 0
    error_count: int = 0
    total_count: int = 0
    response_times: List[float] = None
    error_types: Dict[str, int] = None
    
    def __post_init__(self):
        if self.response_times is None:
            self.response_times = []
        if self.error_types is None:
            self.error_types = defaultdict(int)
    
    @property
    def success_rate(self) -> float:
        """Taux de succès en pourcentage"""
        if self.total_count == 0:
            return 0.0
        return (self.success_count / self.total_count) * 100
    
    @property
    def avg_response_time(self) -> float:
        """Temps de réponse moyen en millisecondes"""
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)


class WaChapMonitor:
    """
    Moniteur principal pour WaChap
    Collecte les métriques, logs et alertes
    """
    
    def __init__(self):
        self.cache_timeout = getattr(settings, 'WACHAP_METRICS_CACHE_TIMEOUT', 3600)  # 1h
    
    def record_message_attempt(self, instance: str, phone: str, sender_role: str, 
                             message_type: str = 'notification') -> str:
        """
        Enregistre une tentative d'envoi de message
        
        Returns:
            str: ID unique de la tentative
        """
        attempt_id = f"wachap_{instance}_{timezone.now().timestamp()}"
        
        attempt_data = {
            'id': attempt_id,
            'instance': instance,
            'phone': phone,
            'sender_role': sender_role,
            'message_type': message_type,
            'timestamp': timezone.now().isoformat(),
            'status': 'pending'
        }
        
        # Stocker temporairement pour suivi
        cache.set(f"wachap_attempt_{attempt_id}", attempt_data, timeout=3600)
        
        logger.info(f"📤 Tentative d'envoi: {attempt_id} | {instance} | {phone}")
        return attempt_id
    
    def record_message_success(self, attempt_id: str, response_time: float, 
                             message_id: str = None) -> None:
        """Enregistre un succès d'envoi"""
        attempt_data = cache.get(f"wachap_attempt_{attempt_id}")
        if not attempt_data:
            logger.warning(f"Attempt {attempt_id} not found in cache")
            return
        
        # Mettre à jour les données
        attempt_data.update({
            'status': 'success',
            'response_time': response_time,
            'message_id': message_id,
            'completed_at': timezone.now().isoformat()
        })
        
        cache.set(f"wachap_attempt_{attempt_id}", attempt_data, timeout=3600)
        
        # Mettre à jour les métriques
        self._update_metrics(attempt_data['instance'], success=True, 
                           response_time=response_time)
        
        logger.info(f"✅ Succès envoi: {attempt_id} | {response_time:.2f}ms | ID: {message_id}")
    
    def record_message_error(self, attempt_id: str, error_type: str, 
                           error_message: str, response_time: float = None) -> None:
        """Enregistre un échec d'envoi"""
        attempt_data = cache.get(f"wachap_attempt_{attempt_id}")
        if not attempt_data:
            logger.warning(f"Attempt {attempt_id} not found in cache")
            return
        
        # Mettre à jour les données
        attempt_data.update({
            'status': 'error',
            'error_type': error_type,
            'error_message': error_message,
            'response_time': response_time,
            'completed_at': timezone.now().isoformat()
        })
        
        cache.set(f"wachap_attempt_{attempt_id}", attempt_data, timeout=3600)
        
        # Mettre à jour les métriques
        self._update_metrics(attempt_data['instance'], success=False, 
                           error_type=error_type, response_time=response_time)
        
        logger.error(f"❌ Erreur envoi: {attempt_id} | {error_type} | {error_message}")
    
    def _update_metrics(self, instance: str, success: bool, error_type: str = None, 
                       response_time: float = None) -> None:
        """Met à jour les métriques en cache"""
        cache_key = f"wachap_metrics_{instance}"
        metrics_data = cache.get(cache_key, {
            'success_count': 0,
            'error_count': 0,
            'total_count': 0,
            'response_times': [],
            'error_types': {}
        })
        
        # Incrémenter les compteurs
        metrics_data['total_count'] += 1
        if success:
            metrics_data['success_count'] += 1
        else:
            metrics_data['error_count'] += 1
            if error_type:
                metrics_data['error_types'][error_type] = metrics_data['error_types'].get(error_type, 0) + 1
        
        # Ajouter temps de réponse
        if response_time:
            metrics_data['response_times'].append(response_time)
            # Garder seulement les 1000 derniers temps pour éviter la mémoire excessive
            if len(metrics_data['response_times']) > 1000:
                metrics_data['response_times'] = metrics_data['response_times'][-1000:]
        
        cache.set(cache_key, metrics_data, timeout=self.cache_timeout)
    
    def get_metrics(self, instance: str = None) -> Dict[str, WaChapMetrics]:
        """Récupère les métriques actuelles"""
        if instance:
            instances = [instance]
        else:
            instances = ['chine', 'mali']
        
        metrics = {}
        for inst in instances:
            cache_key = f"wachap_metrics_{inst}"
            data = cache.get(cache_key, {})
            
            metrics[inst] = WaChapMetrics(
                instance=inst,
                success_count=data.get('success_count', 0),
                error_count=data.get('error_count', 0),
                total_count=data.get('total_count', 0),
                response_times=data.get('response_times', []),
                error_types=data.get('error_types', {})
            )
        
        return metrics
    
    def get_health_status(self) -> Dict[str, Any]:
        """Évalue l'état de santé du système WaChap"""
        metrics = self.get_metrics()
        
        health = {
            'overall_status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'instances': {}
        }
        
        for instance, metric in metrics.items():
            instance_health = 'healthy'
            issues = []
            
            # Vérifier le taux de succès
            if metric.success_rate < 90:
                instance_health = 'degraded'
                issues.append(f'Taux de succès bas: {metric.success_rate:.1f}%')
            
            if metric.success_rate < 70:
                instance_health = 'unhealthy'
                issues.append('Taux de succès critique')
            
            # Vérifier le temps de réponse
            if metric.avg_response_time > 5000:  # 5 secondes
                instance_health = 'degraded'
                issues.append(f'Temps de réponse élevé: {metric.avg_response_time:.0f}ms')
            
            health['instances'][instance] = {
                'status': instance_health,
                'success_rate': metric.success_rate,
                'avg_response_time': metric.avg_response_time,
                'total_messages': metric.total_count,
                'issues': issues
            }
            
            # Déterminer le statut global
            if instance_health == 'unhealthy':
                health['overall_status'] = 'unhealthy'
            elif instance_health == 'degraded' and health['overall_status'] != 'unhealthy':
                health['overall_status'] = 'degraded'
        
        return health
    
    def reset_metrics(self, instance: str = None) -> None:
        """Remet à zéro les métriques"""
        if instance:
            instances = [instance]
        else:
            instances = ['chine', 'mali']
        
        for inst in instances:
            cache.delete(f"wachap_metrics_{inst}")
        
        logger.info(f"📊 Métriques réinitialisées pour: {', '.join(instances)}")
    
    def export_metrics_report(self, hours: int = 24) -> Dict[str, Any]:
        """Exporte un rapport détaillé des métriques"""
        metrics = self.get_metrics()
        health = self.get_health_status()
        
        report = {
            'report_generated': timezone.now().isoformat(),
            'period_hours': hours,
            'health_status': health,
            'detailed_metrics': {}
        }
        
        for instance, metric in metrics.items():
            report['detailed_metrics'][instance] = {
                'total_messages': metric.total_count,
                'successful_messages': metric.success_count,
                'failed_messages': metric.error_count,
                'success_rate': f"{metric.success_rate:.2f}%",
                'average_response_time': f"{metric.avg_response_time:.2f}ms",
                'error_breakdown': dict(metric.error_types),
                'performance_grade': self._calculate_performance_grade(metric)
            }
        
        return report
    
    def _calculate_performance_grade(self, metric: WaChapMetrics) -> str:
        """Calcule une note de performance"""
        score = 0
        
        # Score basé sur le taux de succès (0-60 points)
        score += min(60, metric.success_rate * 0.6)
        
        # Score basé sur le temps de réponse (0-40 points)
        if metric.avg_response_time <= 1000:  # 1s
            score += 40
        elif metric.avg_response_time <= 3000:  # 3s
            score += 25
        elif metric.avg_response_time <= 5000:  # 5s
            score += 15
        else:
            score += 5
        
        # Convertir en note
        if score >= 90:
            return "A+ (Excellent)"
        elif score >= 80:
            return "A (Très bon)"
        elif score >= 70:
            return "B (Bon)"
        elif score >= 60:
            return "C (Acceptable)"
        elif score >= 50:
            return "D (Médiocre)"
        else:
            return "F (Critique)"


# Instance globale du moniteur
wachap_monitor = WaChapMonitor()


def log_wachap_activity(message: str, level: str = 'info', extra_data: Dict = None):
    """Fonction utilitaire pour logger l'activité WaChap"""
    log_data = {
        'timestamp': timezone.now().isoformat(),
        'service': 'wachap',
        'message': message
    }
    
    if extra_data:
        log_data.update(extra_data)
    
    if level == 'error':
        logger.error(f"🚨 WaChap: {message}", extra=log_data)
    elif level == 'warning':
        logger.warning(f"⚠️  WaChap: {message}", extra=log_data)
    elif level == 'success':
        logger.info(f"✅ WaChap: {message}", extra=log_data)
    else:
        logger.info(f"ℹ️  WaChap: {message}", extra=log_data)


# Décorateur pour monitorer automatiquement les envois
def monitor_wachap_sending(func):
    """Décorateur pour monitorer automatiquement les fonctions d'envoi"""
    def wrapper(*args, **kwargs):
        # Extraction des paramètres pour le monitoring
        instance = kwargs.get('region', 'mali')
        phone = args[0] if args else kwargs.get('phone', 'unknown')
        sender_role = kwargs.get('sender_role', 'unknown')
        
        # Démarrer le monitoring
        attempt_id = wachap_monitor.record_message_attempt(
            instance, phone, sender_role
        )
        
        start_time = timezone.now()
        
        try:
            # Exécuter la fonction
            result = func(*args, **kwargs)
            
            # Calculer le temps de réponse
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            
            # Enregistrer le succès ou l'échec selon le résultat
            if isinstance(result, tuple) and len(result) >= 2:
                success, message = result[:2]
                if success:
                    message_id = result[2] if len(result) > 2 else None
                    wachap_monitor.record_message_success(attempt_id, response_time, message_id)
                else:
                    wachap_monitor.record_message_error(attempt_id, 'api_error', str(message), response_time)
            
            return result
            
        except Exception as e:
            response_time = (timezone.now() - start_time).total_seconds() * 1000
            wachap_monitor.record_message_error(attempt_id, 'exception', str(e), response_time)
            raise
    
    return wrapper
