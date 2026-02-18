from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from .models import Notification, ConfigurationNotification, NotificationTask


@admin.register(NotificationTask)
class NotificationTaskAdmin(admin.ModelAdmin):
    """
    Administration des tâches de notifications pour le monitoring
    Interface pour suivre les notifications par lot
    """
    list_display = [
        'task_id_short',
        'task_type',
        'lot_reference',
        'status_badge',
        'progress_bar',
        'success_rate_display',
        'created_at',
        'duration_display',
        'initiated_by'
    ]
    
    list_filter = [
        'task_status',
        'task_type', 
        'created_at',
        'lot_reference__statut',
        'notification_method'
    ]
    
    search_fields = [
        'task_id',
        'lot_reference__numero_lot',
        'client_reference__user__first_name',
        'client_reference__user__last_name',
        'initiated_by__first_name',
        'initiated_by__last_name'
    ]
    
    readonly_fields = [
        'task_id',
        'created_at',
        'started_at', 
        'completed_at',
        'duration_display',
        'success_rate_display',
        'result_data_display'
    ]
    
    ordering = ['-created_at']
    
    def task_id_short(self, obj):
        """Affiche une version raccourcie du task_id"""
        return f"{obj.task_id[:8]}..." if obj.task_id else "-"
    task_id_short.short_description = "Task ID"
    
    def status_badge(self, obj):
        """Affiche le statut avec des couleurs"""
        color_map = {
            'PENDING': '#ffc107',  # Jaune
            'STARTED': '#17a2b8',  # Bleu
            'SUCCESS': '#28a745',  # Vert
            'FAILURE': '#dc3545',  # Rouge
            'RETRY': '#fd7e14',    # Orange
            'REVOKED': '#6c757d'   # Gris
        }
        color = color_map.get(obj.task_status, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_task_status_display()
        )
    status_badge.short_description = "Statut"
    
    def progress_bar(self, obj):
        """Affiche une barre de progression"""
        if obj.total_notifications == 0:
            return format_html('<span style="color: #6c757d;">Aucune notification</span>')
        
        success_rate = obj.success_rate
        color = '#28a745' if success_rate >= 80 else '#ffc107' if success_rate >= 50 else '#dc3545'
        
        return format_html(
            '''
            <div style="width: 100px; background: #e9ecef; border-radius: 3px; overflow: hidden;">
                <div style="width: {}%; background: {}; height: 20px; text-align: center; color: white; font-size: 11px; line-height: 20px;">
                    {}/{}
                </div>
            </div>
            ''',
            success_rate,
            color,
            obj.notifications_sent,
            obj.total_notifications
        )
    progress_bar.short_description = "Progression"
    
    def success_rate_display(self, obj):
        """Affiche le taux de succès"""
        rate = obj.success_rate
        color = '#28a745' if rate >= 80 else '#ffc107' if rate >= 50 else '#dc3545'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.1f}%</span>',
            color,
            rate
        )
    success_rate_display.short_description = "Taux de succès"
    
    def duration_display(self, obj):
        """Affiche la durée d'exécution"""
        duration = obj.duration
        if duration:
            total_seconds = int(duration.total_seconds())
            minutes, seconds = divmod(total_seconds, 60)
            return f"{minutes}m {seconds}s"
        elif obj.started_at:
            return "En cours..."
        return "-"
    duration_display.short_description = "Durée"
    
    def result_data_display(self, obj):
        """Affiche les données de résultat formatées"""
        if obj.result_data:
            return format_html('<pre>{}</pre>', str(obj.result_data))
        return "-"
    result_data_display.short_description = "Résultats"
    
    def get_queryset(self, request):
        """Optimise les requêtes avec select_related"""
        return super().get_queryset(request).select_related(
            'lot_reference',
            'client_reference__user',
            'initiated_by'
        )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """
    Administration des notifications individuelles
    """
    list_display = [
        'destinataire',
        'type_notification',
        'categorie',
        'status_badge',
        'date_creation',
        'date_envoi',
        'nombre_tentatives',
        'lot_reference',
        'colis_reference'
    ]
    
    list_filter = [
        'statut',
        'type_notification',
        'categorie',
        'date_creation',
        'nombre_tentatives'
    ]
    
    search_fields = [
        'destinataire__first_name',
        'destinataire__last_name',
        'destinataire__telephone',
        'titre',
        'lot_reference__numero_lot',
        'colis_reference__numero_suivi'
    ]
    
    readonly_fields = [
        'date_creation',
        'date_envoi',
        'date_lecture',
        'message_id_externe'
    ]
    
    ordering = ['-date_creation']
    
    def status_badge(self, obj):
        """Affiche le statut avec des couleurs"""
        color_map = {
            'en_attente': '#ffc107',  # Jaune
            'envoye': '#28a745',      # Vert
            'echec': '#dc3545',       # Rouge
            'lu': '#17a2b8'           # Bleu
        }
        color = color_map.get(obj.statut, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_statut_display()
        )
    status_badge.short_description = "Statut"
    
    def get_queryset(self, request):
        """Optimise les requêtes"""
        return super().get_queryset(request).select_related(
            'destinataire',
            'lot_reference',
            'colis_reference'
        )


@admin.register(ConfigurationNotification)
class ConfigurationNotificationAdmin(admin.ModelAdmin):
    """
    Administration de la configuration des notifications
    """
    list_display = [
        'nom_configuration',
        'wachap_chine_active',
        'wachap_mali_active',
        'sms_active',
        'email_active',
        'active',
        'date_modification'
    ]
    
    list_filter = [
        'active',
        'wachap_chine_active',
        'wachap_mali_active',
        'sms_active',
        'email_active'
    ]
    
    readonly_fields = ['date_creation', 'date_modification']
    
    fieldsets = (
        ('Configuration Générale', {
            'fields': ('nom_configuration', 'active')
        }),
        ('WaChap - Instance Chine', {
            'fields': (
                'wachap_chine_active',
                'wachap_chine_access_token',
                'wachap_chine_instance_id',
                'wachap_chine_webhook_url'
            )
        }),
        ('WaChap - Instance Mali', {
            'fields': (
                'wachap_mali_active',
                'wachap_mali_access_token', 
                'wachap_mali_instance_id',
                'wachap_mali_webhook_url'
            )
        }),
        ('Configuration SMS', {
            'fields': (
                'sms_active',
                'orange_sms_api_key',
                'orange_sms_api_url',
                'orange_sms_sender_id'
            )
        }),
        ('Configuration Email', {
            'fields': (
                'email_active',
                'email_smtp_host',
                'email_smtp_port',
                'email_smtp_user',
                'email_smtp_password',
                'email_use_tls'
            )
        }),
        ('Paramètres Avancés', {
            'fields': (
                'max_tentatives_envoi',
                'delai_entre_tentatives'
            )
        }),
        ('Templates de Messages', {
            'classes': ('collapse',),
            'fields': (
                'template_colis_cree',
                'template_lot_expedie',
                'template_colis_arrive',
                'template_colis_livre'
            )
        }),
        ('Métadonnées', {
            'classes': ('collapse',),
            'fields': ('date_creation', 'date_modification')
        })
    )
