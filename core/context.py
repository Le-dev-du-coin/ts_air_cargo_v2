import contextvars

# Variable de contexte thread-safe pour stocker le mode de transport actif ('AERIEN' ou 'BATEAU')
_transport_mode = contextvars.ContextVar('transport_mode', default=None)

def get_current_transport_mode():
    """Récupère le mode de transport actif pour le thread/la requête en cours"""
    return _transport_mode.get()

def set_current_transport_mode(mode):
    """Définit le mode de transport actif (AERIEN ou BATEAU)"""
    return _transport_mode.set(mode)

def clear_current_transport_mode(token):
    """Réinitialise la variable de contexte à sa valeur précédente"""
    _transport_mode.reset(token)
