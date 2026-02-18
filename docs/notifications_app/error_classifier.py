"""
Classificateur d'erreurs pour les notifications WhatsApp
Détermine si une erreur est temporaire (retry possible) ou permanente
"""

import logging
import re

logger = logging.getLogger(__name__)


class NotificationErrorClassifier:
    """
    Classifie les erreurs de notifications pour déterminer la stratégie de retry
    """
    
    # Codes HTTP considérés comme erreurs temporaires (worth retrying)
    TEMPORARY_HTTP_CODES = {
        408,  # Request Timeout
        429,  # Too Many Requests
        500,  # Internal Server Error
        502,  # Bad Gateway
        503,  # Service Unavailable
        504,  # Gateway Timeout
    }
    
    # Codes HTTP considérés comme erreurs permanentes (don't retry)
    PERMANENT_HTTP_CODES = {
        400,  # Bad Request (numéro invalide, données incorrectes)
        401,  # Unauthorized (token invalide, abonnement expiré)
        403,  # Forbidden (accès refusé)
        404,  # Not Found
        405,  # Method Not Allowed
        410,  # Gone
    }
    
    # Types d'erreurs considérées comme temporaires
    TEMPORARY_ERROR_TYPES = {
        'timeout',
        'connection_error',
        'network_error',
        'ssl_error',
        'http_503',
        'http_502',
        'http_504',
        'http_429',
        'http_408',
        'http_500',
    }
    
    # Types d'erreurs considérées comme permanentes
    PERMANENT_ERROR_TYPES = {
        'http_401',
        'http_403',
        'http_400',
        'http_404',
        'config_error',
        'instance_inactive',
    }
    
    # Mots-clés dans les messages d'erreur indiquant une erreur permanente
    PERMANENT_ERROR_KEYWORDS = [
        'unauthorized',
        'forbidden',
        'invalid phone',
        'invalid number',
        'token expired',
        'subscription expired',
        'account suspended',
        'not found',
        'bad request',
    ]
    
    @classmethod
    def classify_error(cls, error_type: str, error_message: str, http_code: int = None) -> dict:
        """
        Classifie une erreur et retourne des informations sur la stratégie de gestion
        
        Args:
            error_type: Type d'erreur (ex: 'timeout', 'http_401')
            error_message: Message d'erreur complet
            http_code: Code HTTP optionnel
            
        Returns:
            dict: {
                'is_temporary': bool,
                'should_retry': bool,
                'should_alert_admin': bool,
                'classification': str,
                'recommendation': str
            }
        """
        is_temporary = cls._is_temporary_error(error_type, error_message, http_code)
        
        result = {
            'is_temporary': is_temporary,
            'should_retry': is_temporary,
            'should_alert_admin': not is_temporary,
            'classification': 'temporaire' if is_temporary else 'permanent',
            'recommendation': cls._get_recommendation(error_type, is_temporary)
        }
        
        # Cas spéciaux nécessitant des alertes même si temporaires
        if cls._requires_admin_alert(error_type, error_message):
            result['should_alert_admin'] = True
        
        logger.info(
            f"Erreur classifiée: type={error_type}, "
            f"classification={result['classification']}, "
            f"retry={result['should_retry']}, "
            f"alert={result['should_alert_admin']}"
        )
        
        return result
    
    @classmethod
    def _is_temporary_error(cls, error_type: str, error_message: str, http_code: int = None) -> bool:
        """Détermine si l'erreur est temporaire"""
        
        # Vérifier les types d'erreurs connus
        if error_type in cls.PERMANENT_ERROR_TYPES:
            return False
        
        if error_type in cls.TEMPORARY_ERROR_TYPES:
            return True
        
        # Vérifier les codes HTTP si fournis
        if http_code:
            if http_code in cls.PERMANENT_HTTP_CODES:
                return False
            if http_code in cls.TEMPORARY_HTTP_CODES:
                return True
        
        # Analyser le message d'erreur pour des mots-clés permanents
        error_msg_lower = error_message.lower()
        for keyword in cls.PERMANENT_ERROR_KEYWORDS:
            if keyword in error_msg_lower:
                return False
        
        # Par défaut, considérer comme temporaire (principe de précaution)
        return True
    
    @classmethod
    def _requires_admin_alert(cls, error_type: str, error_message: str) -> bool:
        """
        Détermine si l'erreur nécessite une alerte admin immédiate
        même si elle est temporaire
        """
        # Alertes pour problèmes critiques
        critical_keywords = [
            'subscription',
            'token expired',
            'unauthorized',
            'forbidden',
            'suspended',
        ]
        
        error_msg_lower = error_message.lower()
        return any(keyword in error_msg_lower for keyword in critical_keywords)
    
    @classmethod
    def _get_recommendation(cls, error_type: str, is_temporary: bool) -> str:
        """Retourne une recommandation d'action"""
        
        if not is_temporary:
            if 'http_401' in error_type or 'http_403' in error_type:
                return "Vérifier l'abonnement WaChap et renouveler si nécessaire"
            elif 'http_400' in error_type:
                return "Vérifier la validité du numéro de téléphone"
            elif 'config_error' in error_type:
                return "Vérifier la configuration WaChap (token, instance_id)"
            else:
                return "Erreur permanente : vérifier les logs et contacter le support"
        else:
            if 'timeout' in error_type:
                return "Problème de réseau temporaire, retry automatique programmé"
            elif 'http_429' in error_type:
                return "Rate limit atteint, retry après délai"
            else:
                return "Erreur temporaire, retry automatique programmé"


def classify_wachap_error(error_type: str, error_message: str, http_code: int = None) -> dict:
    """
    Fonction utilitaire pour classifier une erreur WaChap
    
    Usage:
        result = classify_wachap_error('timeout', 'Connection timeout after 15s')
        if result['should_retry']:
            # Programmer retry
        if result['should_alert_admin']:
            # Envoyer alerte
    """
    return NotificationErrorClassifier.classify_error(error_type, error_message, http_code)
