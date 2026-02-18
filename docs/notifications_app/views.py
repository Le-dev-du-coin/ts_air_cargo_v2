from django.shortcuts import render, get_object_or_404
import logging
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
import json

from .models import Notification
from .services import NotificationService

logger = logging.getLogger(__name__)

@login_required
def notifications_list_view(request):
    """
    Afficher la liste des notifications de l'utilisateur connecté
    """
    # Récupérer les notifications de l'utilisateur
    notifications = Notification.objects.filter(
        destinataire=request.user,
        type_notification='in_app'
    ).select_related('expediteur', 'colis_reference', 'lot_reference')
    
    # Filtrage par statut
    statut_filter = request.GET.get('statut', '')
    if statut_filter:
        notifications = notifications.filter(statut=statut_filter)
    
    # Filtrage par catégorie
    categorie_filter = request.GET.get('categorie', '')
    if categorie_filter:
        notifications = notifications.filter(categorie=categorie_filter)
    
    # Recherche
    search_query = request.GET.get('search', '')
    if search_query:
        notifications = notifications.filter(
            Q(titre__icontains=search_query) |
            Q(message__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(notifications, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistiques
    total_notifications = Notification.objects.filter(
        destinataire=request.user,
        type_notification='in_app'
    ).count()
    
    non_lues = Notification.objects.filter(
        destinataire=request.user,
        type_notification='in_app',
        statut='envoye'
    ).count()
    
    context = {
        'notifications': page_obj,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'total_notifications': total_notifications,
        'non_lues': non_lues,
        'statut_filter': statut_filter,
        'categorie_filter': categorie_filter,
        'search_query': search_query,
        'statut_choices': Notification.STATUT_CHOICES,
        'categorie_choices': Notification.CATEGORIE_CHOICES,
        'title': 'Mes Notifications',
    }
    return render(request, 'notifications_app/notifications_list.html', context)

@login_required
def notification_detail_view(request, notification_id):
    """
    Afficher les détails d'une notification
    """
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        destinataire=request.user,
        type_notification='in_app'
    )
    
    # Marquer comme lue automatiquement
    if notification.statut == 'envoye':
        notification.marquer_comme_lu()
    
    context = {
        'notification': notification,
        'title': f'Notification - {notification.titre}',
    }
    return render(request, 'notifications_app/notification_detail.html', context)

@login_required
@require_http_methods(["POST"])
def mark_notification_read_api(request, notification_id):
    """
    API pour marquer une notification comme lue
    """
    try:
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            destinataire=request.user,
            type_notification='in_app'
        )
        
        notification.marquer_comme_lu()
        
        return JsonResponse({
            'success': True,
            'message': 'Notification marquée comme lue'
        })
        
    except Exception as e:
        logger.error(f"Erreur création notification in-app: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
@require_http_methods(["POST"])
def mark_all_notifications_read_api(request):
    """
    API pour marquer toutes les notifications comme lues
    """
    try:
        notifications = Notification.objects.filter(
            destinataire=request.user,
            type_notification='in_app',
            statut='envoye'
        )
        
        count = notifications.count()
        for notification in notifications:
            notification.marquer_comme_lu()
        
        return JsonResponse({
            'success': True,
            'message': f'{count} notification(s) marquée(s) comme lue(s)',
            'count': count
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def notifications_count_api(request):
    """
    API pour récupérer le nombre de notifications non lues
    """
    try:
        count = Notification.objects.filter(
            destinataire=request.user,
            type_notification='in_app',
            statut='envoye'
        ).count()
        
        return JsonResponse({
            'success': True,
            'count': count
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def notifications_recent_api(request):
    """
    API pour récupérer les notifications récentes (5 dernières)
    """
    try:
        notifications = Notification.objects.filter(
            destinataire=request.user,
            type_notification='in_app'
        ).select_related('colis_reference', 'lot_reference')[:5]
        
        notifications_data = []
        for notif in notifications:
            notifications_data.append({
                'id': notif.id,
                'titre': notif.titre,
                'message': notif.message[:100] + ('...' if len(notif.message) > 100 else ''),
                'categorie': notif.get_categorie_display(),
                'statut': notif.statut,
                'date_creation': notif.date_creation.isoformat(),
                'lien_action': notif.lien_action,
                'is_read': notif.statut == 'lu'
            })
        
        return JsonResponse({
            'success': True,
            'notifications': notifications_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def send_in_app_notification(user, title, message, categorie, colis=None, lot=None, transfert=None, lien_action=""):
    """
    Fonction utilitaire pour créer une notification in-app
    """
    try:
        notification = Notification.objects.create(
            destinataire=user,
            type_notification='in_app',
            categorie=categorie,
            titre=title,
            message=message,
            lien_action=lien_action,
            colis_reference=colis,
            lot_reference=lot,
            transfert_reference=transfert,
            statut='envoye'  # Les notifications in-app sont directement "envoyées"
        )
        return True
    except Exception as e:
        logger.error(f"Erreur création notification in-app: {e}")
        return False
