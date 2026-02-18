from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    # Pages principales
    path('', views.notifications_list_view, name='list'),
    path('<int:notification_id>/', views.notification_detail_view, name='detail'),
    
    # APIs AJAX
    path('api/count/', views.notifications_count_api, name='count_api'),
    path('api/recent/', views.notifications_recent_api, name='recent_api'),
    path('api/<int:notification_id>/mark-read/', views.mark_notification_read_api, name='mark_read_api'),
    path('api/mark-all-read/', views.mark_all_notifications_read_api, name='mark_all_read_api'),
]
