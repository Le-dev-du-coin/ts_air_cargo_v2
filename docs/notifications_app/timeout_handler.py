"""
Gestionnaire de timeout et retry pour les API WaChap
Améliore la robustesse des envois de messages
"""

import time
import logging
import requests
from typing import Tuple, Optional, Dict, Any
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

class TimeoutHandler:
    """
    Gestionnaire de timeout avec retry intelligent et fallback
    """
    
    def __init__(self):
        self.max_retries = 3
        self.base_timeout = 30  # Timeout de base en secondes
        self.backoff_factor = 2  # Facteur d'augmentation du délai entre les retries
        self.max_timeout = 60   # Timeout maximum
        
    def execute_with_retry(self, func, *args, **kwargs) -> Tuple[bool, str, Optional[str]]:
        """
        Exécute une fonction avec système de retry automatique
        
        Args:
            func: Fonction à exécuter (généralement un appel API)
            *args, **kwargs: Arguments pour la fonction
            
        Returns:
            Tuple[bool, str, Optional[str]]: (succès, message, message_id)
        """
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                # Calculer le timeout pour cette tentative
                timeout = min(self.base_timeout * (self.backoff_factor ** attempt), self.max_timeout)
                
                logger.info(f"🔄 Tentative {attempt + 1}/{self.max_retries + 1} (timeout: {timeout}s)")
                
                # Exécuter la fonction avec le timeout adaptatif
                if 'timeout' in kwargs:
                    kwargs['timeout'] = timeout
                
                result = func(*args, **kwargs)
                
                # Si on arrive ici, c'est un succès
                if attempt > 0:
                    logger.info(f"✅ Succès après {attempt + 1} tentatives")
                
                return result
                
            except requests.exceptions.Timeout as e:
                last_error = f"Timeout après {timeout}s (tentative {attempt + 1})"
                logger.warning(f"⏱️ {last_error}")
                
                # Attendre avant le retry (sauf pour la dernière tentative)
                if attempt < self.max_retries:
                    wait_time = (attempt + 1) * 2  # 2s, 4s, 6s
                    logger.info(f"⏳ Attente {wait_time}s avant retry...")
                    time.sleep(wait_time)
                    
            except requests.exceptions.ConnectionError as e:
                last_error = f"Erreur de connexion (tentative {attempt + 1})"
                logger.warning(f"🔌 {last_error}")
                
                if attempt < self.max_retries:
                    wait_time = (attempt + 1) * 3  # 3s, 6s, 9s
                    time.sleep(wait_time)
                    
            except Exception as e:
                last_error = f"Erreur inattendue: {str(e)}"
                logger.error(f"❌ {last_error}")
                break  # Pas de retry pour les autres erreurs
        
        # Si on arrive ici, tous les retries ont échoué
        logger.error(f"💥 Échec définitif après {self.max_retries + 1} tentatives: {last_error}")
        return False, f"Échec après {self.max_retries + 1} tentatives - {last_error}", None
    
    def check_service_health(self, base_url: str) -> bool:
        """
        Vérifie la santé du service WaChap
        
        Args:
            base_url: URL de base de l'API WaChap
            
        Returns:
            bool: True si le service répond
        """
        try:
            response = requests.get(f"{base_url}", timeout=10)
            return response.status_code == 200
        except Exception:
            return False
    
    def get_fallback_config(self, original_region: str) -> Optional[str]:
        """
        Retourne une région de fallback en cas d'échec
        
        Args:
            original_region: Région originale qui a échoué
            
        Returns:
            str: Région de fallback ou None
        """
        fallback_map = {
            'system': 'chine',  # Si système échoue → Chine
            'mali': 'chine',    # Si Mali échoue → Chine  
            'chine': 'system'   # Si Chine échoue → Système
        }
        
        fallback = fallback_map.get(original_region)
        if fallback:
            logger.info(f"🔄 Fallback: {original_region} → {fallback}")
            
        return fallback

class CircuitBreaker:
    """
    Implémente un circuit breaker pour éviter les appels répétés vers un service défaillant
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
    
    def is_circuit_open(self, service_key: str) -> bool:
        """
        Vérifie si le circuit est ouvert pour un service
        """
        cache_key = f"circuit_breaker_{service_key}"
        circuit_data = cache.get(cache_key, {'failures': 0, 'last_failure': None})
        
        # Si pas assez d'échecs, circuit fermé
        if circuit_data['failures'] < self.failure_threshold:
            return False
            
        # Si timeout de récupération dépassé, essayer de fermer le circuit
        if circuit_data['last_failure']:
            time_since_failure = time.time() - circuit_data['last_failure']
            if time_since_failure > self.recovery_timeout:
                logger.info(f"🔓 Circuit breaker: tentative de récupération pour {service_key}")
                # Reset partiel pour permettre un test
                circuit_data['failures'] = self.failure_threshold - 1
                cache.set(cache_key, circuit_data, timeout=3600)
                return False
        
        logger.warning(f"⚠️ Circuit breaker OUVERT pour {service_key}")
        return True
    
    def record_success(self, service_key: str):
        """Enregistre un succès - ferme le circuit"""
        cache_key = f"circuit_breaker_{service_key}"
        cache.delete(cache_key)
        logger.info(f"✅ Circuit breaker fermé pour {service_key}")
    
    def record_failure(self, service_key: str):
        """Enregistre un échec"""
        cache_key = f"circuit_breaker_{service_key}"
        circuit_data = cache.get(cache_key, {'failures': 0, 'last_failure': None})
        
        circuit_data['failures'] += 1
        circuit_data['last_failure'] = time.time()
        
        cache.set(cache_key, circuit_data, timeout=3600)
        
        if circuit_data['failures'] >= self.failure_threshold:
            logger.warning(f"🚨 Circuit breaker OUVERT pour {service_key} ({circuit_data['failures']} échecs)")

# Instances globales
timeout_handler = TimeoutHandler()
circuit_breaker = CircuitBreaker()
