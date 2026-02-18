"""
Tâches Celery pour l'envoi asynchrone de notifications
Version unifiée pour toutes les apps (agent_chine, agent_mali, admin, client)
"""

import logging
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from .models import Notification, NotificationTask
from .services import NotificationService
from .utils import format_cfa
from .error_classifier import classify_wachap_error
from .alert_system import check_notification_health

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def retry_failed_notifications_task():
    """
    Tâche Celery Beat pour relancer automatiquement les notifications échouées
    Exécutée périodiquement (toutes les 30 minutes)
    """
    from django.db.models import Q
    
    try:
        now = timezone.now()
        max_retries = 10
        limit = 100  # Limiter pour éviter surcharge
        
        # Récupérer les notifications éligibles
        notifications_to_retry = Notification.objects.filter(
            Q(statut='echec') &
            Q(prochaine_tentative__lte=now) &
            Q(nombre_tentatives__lt=max_retries)
        ).select_related('destinataire')[:limit]
        
        count = notifications_to_retry.count()
        
        if count == 0:
            logger.info("✅ Aucune notification à relancer")
            return {'success': True, 'retried': 0, 'message': 'Aucune notification à relancer'}
        
        logger.info(f"🔄 Début retry automatique : {count} notification(s) à traiter")
        
        stats = {'queued': 0, 'errors': 0}
        
        for notification in notifications_to_retry:
            try:
                # Lancer la tâche d'envoi individuelle
                send_individual_notification.delay(notification.id)
                stats['queued'] += 1
            except Exception as e:
                stats['errors'] += 1
                logger.error(f"❌ Erreur lors du retry notification {notification.id}: {str(e)}")
        
        logger.info(
            f"✅ Retry automatique terminé : {stats['queued']} mis en file, "
            f"{stats['errors']} erreurs"
        )
        
        return {
            'success': True,
            'retried': stats['queued'],
            'errors': stats['errors'],
            'total': count
        }
        
    except Exception as e:
        error_msg = f"Erreur lors du retry automatique : {str(e)}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}


@shared_task(bind=True)
def check_notification_health_task():
    """
    Tâche Celery Beat pour vérifier la santé du système de notifications
    Exécutée périodiquement pour détecter les défaillances critiques
    """
    try:
        logger.info("💚 Début vérification santé notifications")
        check_notification_health()
        logger.info("✅ Vérification santé notifications terminée")
        return {'success': True, 'message': 'Vérification santé terminée'}
    except Exception as e:
        error_msg = f"Erreur lors de la vérification santé : {str(e)}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def send_individual_notification(self, notification_id):
    """
    Tâche Celery pour envoyer une notification individuelle de façon asynchrone
    
    Args:
        notification_id (int): ID de la notification à envoyer
        
    Returns:
        dict: Résultat de l'envoi avec succès/échec et détails
    """
    try:
        # Récupérer la notification
        notification = Notification.objects.get(id=notification_id)
        
        # Marquer comme en cours de traitement
        notification.statut = 'en_attente'
        notification.save(update_fields=['statut'])
        
        # Envoyer la notification via le service
        success = False
        error_message = None
        
        if notification.type_notification == 'whatsapp':
            success, message_id = NotificationService._send_whatsapp(
                user=notification.destinataire,
                message=notification.message,
                categorie=notification.categorie,
                title=notification.titre,
            )
        elif notification.type_notification == 'sms':
            success, message_id = NotificationService._send_sms(
                user=notification.destinataire,
                message=notification.message
            )
        elif notification.type_notification == 'email':
            success, message_id = NotificationService._send_email(
                user=notification.destinataire,
                message=notification.message,
                title=notification.titre
            )
        
        # Mettre à jour le statut selon le résultat
        if success:
            notification.marquer_comme_envoye(message_id if 'message_id' in locals() else None)
            logger.info(f"Notification {notification_id} envoyée avec succès à {notification.destinataire.telephone}")
            return {
                'success': True,
                'notification_id': notification_id,
                'message_id': message_id if 'message_id' in locals() else None,
                'recipient': notification.destinataire.telephone
            }
        else:
            # Classifier l'erreur pour déterminer si temporaire ou permanente
            error_classification = classify_wachap_error(
                error_type='general_error',
                error_message=notification.erreur_envoi or "Échec d'envoi"
            )
            
            error_type = 'permanent' if not error_classification['should_retry'] else 'temporaire'
            notification.marquer_comme_echec(
                erreur=notification.erreur_envoi or "Échec d'envoi via le service de notification",
                erreur_type=error_type
            )
            
            logger.error(
                f"Échec envoi notification {notification_id}: {notification.erreur_envoi} "
                f"(classifié: {error_classification['classification']})"
            )
            
            # Relancer la tâche si erreur temporaire et pas au max de tentatives
            if error_classification['should_retry'] and self.request.retries < self.max_retries:
                raise Exception(f"Retry notification {notification_id}")
            
            return {
                'success': False,
                'notification_id': notification_id,
                'error': notification.erreur_envoi,
                'error_type': error_type,
                'recipient': notification.destinataire.telephone
            }
            
    except Notification.DoesNotExist:
        error_msg = f"Notification {notification_id} introuvable"
        logger.error(error_msg)
        return {
            'success': False,
            'notification_id': notification_id,
            'error': error_msg
        }
    except Exception as e:
        error_msg = f"Erreur lors de l'envoi notification {notification_id}: {str(e)}"
        logger.error(error_msg)
        
        # Si c'est un retry, marquer la notification comme échouée définitivement
        if self.request.retries >= self.max_retries:
            try:
                notification = Notification.objects.get(id=notification_id)
                notification.marquer_comme_echec(error_msg)
            except:
                pass
        
        # Relancer si possible
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2 ** self.request.retries))  # Backoff exponentiel
        
        return {
            'success': False,
            'notification_id': notification_id,
            'error': error_msg
        }


@shared_task(bind=True)
def send_bulk_received_colis_notifications(self, colis_ids_list, notification_type='lot_arrived', message_template=None, initiated_by_id=None):
    """
    Tâche Celery pour envoyer des notifications seulement aux colis spécifiquement réceptionnés
    
    Args:
        colis_ids_list (list): Liste des IDs des colis réceptionnés
        notification_type (str): Type de notification (défaut: 'lot_arrived')
        message_template (str, optional): Template personnalisé du message
        initiated_by_id (int, optional): ID de l'utilisateur qui a initié la tâche
        
    Returns:
        dict: Statistiques d'envoi
    """
    task_record = None
    
    try:
        from agent_chine_app.models import Colis
        
        # Récupérer les colis réceptionnés uniquement
        colis_list = Colis.objects.filter(
            id__in=colis_ids_list
        ).select_related('client__user', 'lot').all()
        
        if not colis_list:
            return {
                'success': False,
                'error': 'Aucun colis trouvé dans la liste fournie',
                'colis_ids': colis_ids_list
            }
        
        # Récupérer le lot depuis le premier colis (ils sont du même lot)
        lot = colis_list[0].lot
        
        # Créer l'enregistrement de suivi de la tâche
        task_record = NotificationTask.objects.create(
            task_id=self.request.id,
            task_type=f'bulk_received_{notification_type}',
            lot_reference=lot,
            initiated_by_id=initiated_by_id,
            message_template=message_template or '',
            total_notifications=len(colis_ids_list)
        )
        
        task_record.mark_as_started()
        
        clients_map = {}
        notifications_created = []
        
        # Messages templates (même que l'original mais pour colis réceptionnés)
        messages_templates = {
            'lot_arrived': {
                'title': 'Colis arrivé au Mali',
                'template': """📍 Bonne nouvelle ! Votre colis est arrivé !

Votre colis {numero_suivi} du lot {numero_lot} est arrivé au Mali.

📅 Date d'arrivée: {date_arrivee}

Équipe TS Air Cargo""",
                'categorie': 'colis_arrive'
            }
        }
        
        template_info = messages_templates.get(notification_type, messages_templates['lot_arrived'])
        final_template = message_template or template_info['template']
        
        # Construire la map client -> liste de colis RÉCEPTIONNÉS seulement
        for colis in colis_list:
            client = colis.client
            data = clients_map.setdefault(client.id, {
                'client': client,
                'user': client.user,
                'colis': []
            })
            data['colis'].append(colis)

        # Créer une notification par client pour ses colis réceptionnés
        for _, data in clients_map.items():
            client = data['client']
            colis_du_client = data['colis']
            numeros = [c.numero_suivi for c in colis_du_client]
            numeros_bullets = "\n".join([f"- {num}" for num in numeros])
            multi = len(numeros) > 1

            # Préparer les variables communes
            template_vars = {
                'numero_suivi': numeros[0] if numeros else '',
                'numero_lot': lot.numero_lot,
                'date_arrivee': lot.date_arrivee.strftime('%d/%m/%Y à %H:%M') if hasattr(lot, 'date_arrivee') and lot.date_arrivee else '',
            }

            # Adapter le message selon le nombre de colis
            if multi:
                header = f"📍 Bonne nouvelle ! Vos colis sont arrivés !\n\nVos colis du lot {lot.numero_lot} sont arrivés au Mali.\n📅 Date d'arrivée: {template_vars['date_arrivee']}"
                formatted_message = f"{header}\n\nColis arrivés:\n{numeros_bullets}\n\nÉquipe TS Air Cargo"
            else:
                try:
                    formatted_message = final_template.format(**template_vars)
                except KeyError as e:
                    formatted_message = final_template
                    logger.warning(f"Variable manquante dans template: {e}")

            # Ajouter info de développement si nécessaire
            if getattr(settings, 'DEBUG', False):
                formatted_message = f"""[MODE DEV] {template_info['title']}

👤 Client: {client.user.get_full_name()}
📞 Téléphone: {client.user.telephone}

{formatted_message}

Merci de votre confiance !
Équipe TS Air Cargo 🚀"""

            # Créer la notification en base (une par client)
            notification = Notification.objects.create(
                destinataire=client.user,
                type_notification='whatsapp',
                categorie=template_info['categorie'],
                titre=template_info['title'],
                message=formatted_message,
                telephone_destinataire=client.user.telephone,
                email_destinataire=client.user.email or '',
                statut='en_attente',
                lot_reference=lot
            )

            notifications_created.append(notification.id)
        
        # Mettre à jour le nombre total réel
        task_record.total_notifications = len(notifications_created)
        task_record.save(update_fields=['total_notifications'])
        
        # Envoyer toutes les notifications de façon asynchrone
        sent_count = 0
        failed_count = 0
        
        for notif_id in notifications_created:
            try:
                send_individual_notification.delay(notif_id)
                sent_count += 1
            except Exception as e:
                logger.error(f"Erreur lors du lancement de la tâche pour notification {notif_id}: {e}")
                failed_count += 1
        
        # Mettre à jour les statistiques
        task_record.update_progress(sent_count=sent_count, failed_count=failed_count)
        
        # Marquer la tâche comme terminée
        result_data = {
            'colis_ids': colis_ids_list,
            'notification_type': notification_type,
            'total_notifications': len(notifications_created),
            'notifications_queued': sent_count,
            'queue_failures': failed_count,
            'clients_count': len(clients_map)
        }
        
        task_record.mark_as_completed(
            success=True,
            result_data=result_data
        )
        
        logger.info(f"Tâche de notification ciblée terminée pour {len(colis_ids_list)} colis réceptionnés: {sent_count} notifications en file d'attente")
        
        return result_data
        
    except Exception as e:
        error_msg = f"Erreur lors de l'envoi ciblé pour colis {colis_ids_list}: {str(e)}"
        logger.error(error_msg)
        
        if task_record:
            task_record.mark_as_completed(
                success=False,
                error_message=error_msg
            )
        
        return {
            'success': False,
            'error': error_msg,
            'colis_ids': colis_ids_list
        }


@shared_task(bind=True)
def send_bulk_lot_notifications(self, lot_id, notification_type, message_template=None, initiated_by_id=None):
    """
    Tâche Celery pour envoyer des notifications en masse pour un lot
    
    Args:
        lot_id (int): ID du lot concerné
        notification_type (str): Type de notification ('lot_closed', 'lot_shipped', 'lot_arrived', 'lot_delivered')
        message_template (str, optional): Template personnalisé du message
        initiated_by_id (int, optional): ID de l'utilisateur qui a initié la tâche
        
    Returns:
        dict: Statistiques d'envoi
    """
    task_record = None
    
    try:
        # Importer les modèles ici pour éviter les imports circulaires
        from agent_chine_app.models import Lot
        
        # Récupérer le lot
        lot = Lot.objects.get(id=lot_id)
        
        # Créer l'enregistrement de suivi de la tâche
        task_record = NotificationTask.objects.create(
            task_id=self.request.id,
            task_type=f'bulk_{notification_type}',
            lot_reference=lot,
            initiated_by_id=initiated_by_id,
            message_template=message_template or '',
            total_notifications=lot.colis.count()
        )
        
        task_record.mark_as_started()
        
        # Récupérer tous les colis du lot et regrouper par client (agrégation)
        colis_list = lot.colis.select_related('client__user').all()
        clients_map = {}
        notifications_created = []
        
        # Déterminer le message selon le type
        messages_templates = {
            'lot_closed': {
                'title': 'Lot fermé - Prêt à expédier',
                'template': """📦 Lot fermé - Prêt à expédier !

Votre colis {numero_suivi} dans le lot {numero_lot} est maintenant prêt à être expédié.

Vous recevrez une notification lors de l'expédition.

Équipe TS Air Cargo""",
                'categorie': 'lot_expedie'
            },
            'lot_shipped': {
                'title': 'Colis expédié - En transit',
                'template': """🚚 Colis expédié - En transit !

Votre colis {numero_suivi} a été expédié dans le lot {numero_lot}.

📅 Date d'expédition: {date_expedition}

Votre colis est maintenant en route vers le Mali.
Vous recevrez une notification à son arrivée.

Équipe TS Air Cargo""",
                'categorie': 'colis_en_transit'
            },
            'lot_arrived': {
                'title': 'Colis arrivé au Mali',
                'template': """📍 Bonne nouvelle ! Votre colis est arrivé !

Votre colis {numero_suivi} du lot {numero_lot} est arrivé au Mali.

📅 Date d'arrivée: {date_arrivee}

Équipe TS Air Cargo""",
                'categorie': 'colis_arrive'
            },
            'lot_delivered': {
                'title': 'Colis livré avec succès',
                'template': """✅ Livraison réussie !

Votre colis {numero_suivi} du lot {numero_lot} a été livré avec succès.

📅 Date de livraison: {date_livraison}

Merci d'avoir choisi TS Air Cargo pour vos envois !

Équipe TS Air Cargo""",
                'categorie': 'colis_livre'
            }
        }
        
        # Utiliser le template personnalisé ou celui par défaut
        template_info = messages_templates.get(notification_type, messages_templates['lot_closed'])
        final_template = message_template or template_info['template']
        
        # Construire la map client -> liste de colis
        for colis in colis_list:
            client = colis.client
            data = clients_map.setdefault(client.id, {
                'client': client,
                'user': client.user,
                'colis': []
            })
            data['colis'].append(colis)

        # Créer une notification par client en agrégeant les numéros de suivi
        for _, data in clients_map.items():
            client = data['client']
            colis_du_client = data['colis']
            numeros = [c.numero_suivi for c in colis_du_client]
            numeros_bullets = "\n".join([f"- {num}" for num in numeros])
            multi = len(numeros) > 1

            # Préparer les variables communes
            template_vars = {
                'numero_suivi': numeros[0] if numeros else '',
                'numero_lot': lot.numero_lot,
                'date_expedition': lot.date_expedition.strftime('%d/%m/%Y à %H:%M') if lot.date_expedition else '',
                'date_arrivee': lot.date_arrivee.strftime('%d/%m/%Y à %H:%M') if hasattr(lot, 'date_arrivee') and lot.date_arrivee else '',
                'date_livraison': timezone.now().strftime('%d/%m/%Y à %H:%M'),
            }

            # Générer un message adapté lot_closed / lot_shipped avec agrégation
            if notification_type in ['lot_closed', 'lot_shipped']:
                try:
                    base_message = final_template.format(**template_vars)
                except KeyError as e:
                    base_message = final_template
                    logger.warning(f"Variable manquante dans template: {e}")

                if multi:
                    # Adapter wording au pluriel et ajouter la liste des numéros
                    if notification_type == 'lot_closed':
                        header = f"📦 Lot fermé - Prêt à expédier !\n\nVos colis dans le lot {lot.numero_lot} sont maintenant prêts à être expédiés."
                    else:  # lot_shipped
                        header = f"🚚 Colis expédiés - En transit !\n\nVos colis du lot {lot.numero_lot} ont été expédiés.\n📅 Date d'expédition: {template_vars['date_expedition']}"

                    formatted_message = f"{header}\n\nColis concernés:\n{numeros_bullets}\n\nÉquipe TS Air Cargo"
                else:
                    # Message mono-colis (conserver template existant)
                    formatted_message = base_message
            else:
                # Pour les autres types (arrivée/livraison), conserver le message existant tel quel
                try:
                    formatted_message = final_template.format(**template_vars)
                except KeyError as e:
                    formatted_message = final_template
                    logger.warning(f"Variable manquante dans template: {e}")

            # Ajouter info de développement si nécessaire
            if getattr(settings, 'DEBUG', False):
                formatted_message = f"""[MODE DEV] {template_info['title']}

👤 Client: {client.user.get_full_name()}
📞 Téléphone: {client.user.telephone}

{formatted_message}

Merci de votre confiance !
Équipe TS Air Cargo 🚀"""

            # Créer la notification en base (une par client)
            notification = Notification.objects.create(
                destinataire=client.user,
                type_notification='whatsapp',
                categorie=template_info['categorie'],
                titre=template_info['title'],
                message=formatted_message,
                telephone_destinataire=client.user.telephone,
                email_destinataire=client.user.email or '',
                statut='en_attente',
                lot_reference=lot
            )

            notifications_created.append(notification.id)
        
        # Mettre à jour le nombre total réel
        task_record.total_notifications = len(notifications_created)
        task_record.save(update_fields=['total_notifications'])
        
        # Envoyer toutes les notifications de façon asynchrone
        sent_count = 0
        failed_count = 0
        
        for notif_id in notifications_created:
            try:
                # Lancer la tâche d'envoi individuelle
                send_individual_notification.delay(notif_id)
                sent_count += 1
            except Exception as e:
                logger.error(f"Erreur lors du lancement de la tâche pour notification {notif_id}: {e}")
                failed_count += 1
        
        # Mettre à jour les statistiques
        task_record.update_progress(sent_count=sent_count, failed_count=failed_count)
        
        # Marquer la tâche comme terminée
        result_data = {
            'lot_id': lot_id,
            'notification_type': notification_type,
            'total_notifications': len(notifications_created),
            'notifications_queued': sent_count,
            'queue_failures': failed_count,
            'clients_count': len(clients_map)
        }
        
        task_record.mark_as_completed(
            success=True,
            result_data=result_data
        )
        
        logger.info(f"Tâche de notification de masse terminée pour lot {lot.numero_lot}: {sent_count} notifications en file d'attente")
        
        return result_data
        
    except Exception as e:
        error_msg = f"Erreur lors de l'envoi en masse pour lot {lot_id}: {str(e)}"
        logger.error(error_msg)
        
        if task_record:
            task_record.mark_as_completed(
                success=False,
                error_message=error_msg
            )
        
        return {
            'success': False,
            'error': error_msg,
            'lot_id': lot_id
        }


@shared_task(bind=True)
def process_pending_notifications(self):
    """
    Tâche périodique pour traiter les notifications en attente de retry
    À programmer avec celery beat
    """
    try:
        # Rechercher les notifications échouées prêtes pour un retry
        now = timezone.now()
        retry_notifications = Notification.objects.filter(
            statut='echec',
            nombre_tentatives__lt=3,  # Maximum 3 tentatives
            prochaine_tentative__lte=now
        )
        
        retry_count = 0
        for notification in retry_notifications[:50]:  # Limiter à 50 par batch
            try:
                send_individual_notification.delay(notification.id)
                retry_count += 1
            except Exception as e:
                logger.error(f"Erreur relance notification {notification.id}: {e}")
        
        logger.info(f"Relancé {retry_count} notifications en retry")
        return {
            'success': True,
            'retried_count': retry_count
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du traitement des notifications en attente: {e}")
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def cleanup_old_notifications():
    """
    Tâche de nettoyage des anciennes notifications et tâches
    À programmer hebdomadairement
    """
    try:
        # Supprimer les notifications anciennes (> 6 mois)
        cutoff_date = timezone.now() - timezone.timedelta(days=180)
        
        old_notifications = Notification.objects.filter(
            date_creation__lt=cutoff_date,
            statut__in=['envoye', 'lu', 'echec']
        )
        notifications_deleted = old_notifications.count()
        old_notifications.delete()
        
        # Supprimer les tâches terminées anciennes (> 3 mois)
        task_cutoff = timezone.now() - timezone.timedelta(days=90)
        old_tasks = NotificationTask.objects.filter(
            created_at__lt=task_cutoff,
            task_status__in=['SUCCESS', 'FAILURE']
        )
        tasks_deleted = old_tasks.count()
        old_tasks.delete()
        
        logger.info(f"Nettoyage: {notifications_deleted} notifications et {tasks_deleted} tâches supprimées")
        
        return {
            'success': True,
            'notifications_deleted': notifications_deleted,
            'tasks_deleted': tasks_deleted
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage: {e}")
        return {
            'success': False,
            'error': str(e)
        }


# Tâches spécialisées pour l'app agent_chine (utilisant les tâches génériques ci-dessus)

@shared_task
def notify_colis_created(colis_id, initiated_by_id=None):
    """
    Notification pour la création d'un colis (app agent_chine)
    """
    try:
        from agent_chine_app.models import Colis
        
        colis = Colis.objects.select_related('client__user', 'lot').get(id=colis_id)
        client = colis.client
        
        # Détails selon le type de transport et type de colis
        from notifications_app.services import get_colis_details_for_notification
        details_transport = get_colis_details_for_notification(colis)
        
        # Message d'invitation à se connecter pour voir l'image
        photo_message = ""
        if colis.image:
            photo_message = "\n\n📷 Une photo de votre colis a été prise.\n💻 Connectez-vous à votre compte client pour la consulter."
        
        # Préparer le message avec le prix effectif (respecte le prix manuel)
        prix_effectif = colis.get_prix_effectif()
        
        if getattr(settings, 'DEBUG', True):
            message = f"""✅ [MODE DEV] Nouveau colis enregistré !

👤 Client: {client.user.get_full_name()}
📞 Téléphone: {client.user.telephone}

📦 Colis: {colis.numero_suivi}
🚚 Type: {colis.get_type_transport_display()}
📦 Lot: {colis.lot.numero_lot}
📍 Statut: {colis.get_statut_display()}
💰 Prix: {format_cfa(prix_effectif)} FCFA

{details_transport}{photo_message}

🌐 Accédez à votre espace: https://ts-aircargo.com

Merci de votre confiance !
Équipe TS Air Cargo 🚀"""
        else:
            message = f"""✅ Votre colis {colis.numero_suivi} a été enregistré dans le lot {colis.lot.numero_lot}. Type: {colis.get_type_transport_display()}. Prix: {format_cfa(prix_effectif)} FCFA. {details_transport}{photo_message}

🌐 Accédez à votre espace: https://ts-aircargo.com"""
        
        # Créer la notification
        notification = Notification.objects.create(
            destinataire=client.user,
            type_notification='whatsapp',
            categorie='colis_cree',
            titre="Colis Enregistré",
            message=message,
            telephone_destinataire=client.user.telephone,
            email_destinataire=client.user.email or '',
            statut='en_attente',
            colis_reference=colis,
            lot_reference=colis.lot
        )
        
        # Envoyer de façon asynchrone
        send_individual_notification.delay(notification.id)
        
        return {
            'success': True,
            'notification_id': notification.id,
            'colis_id': colis_id
        }
        
    except Exception as e:
        logger.error(f"Erreur notification création colis {colis_id}: {e}")
        return {
            'success': False,
            'error': str(e),
            'colis_id': colis_id
        }


@shared_task
def notify_colis_updated(colis_id, initiated_by_id=None):
    """
    Notification pour la modification d'un colis (app agent_chine)
    """
    try:
        from agent_chine_app.models import Colis
        
        colis = Colis.objects.select_related('client__user').get(id=colis_id)
        client = colis.client
        
        message = f"🔄 Votre colis {colis.numero_suivi} a été modifié. Nouveau statut: {colis.get_statut_display()}"
        
        # Créer la notification
        notification = Notification.objects.create(
            destinataire=client.user,
            type_notification='whatsapp',
            categorie='information_generale',
            titre="Colis Modifié",
            message=message,
            telephone_destinataire=client.user.telephone,
            email_destinataire=client.user.email or '',
            statut='en_attente',
            colis_reference=colis
        )
        
        # Envoyer de façon asynchrone
        send_individual_notification.delay(notification.id)
        
        return {
            'success': True,
            'notification_id': notification.id,
            'colis_id': colis_id
        }
        
    except Exception as e:
        logger.error(f"Erreur notification modification colis {colis_id}: {e}")
        return {
            'success': False,
            'error': str(e),
            'colis_id': colis_id
        }


@shared_task
def notify_lot_received_mali(lot_id, agent_mali_id=None):
    """
    Notification pour l'arrivée d'un lot au Mali (app agent_mali)
    """
    try:
        from agent_chine_app.models import Lot
        from authentication.models import CustomUser
        
        lot = Lot.objects.select_related().get(id=lot_id)
        agent_mali = None
        
        if agent_mali_id:
            try:
                agent_mali = CustomUser.objects.get(id=agent_mali_id)
            except CustomUser.DoesNotExist:
                pass
        
        # Utiliser le service pour envoyer les notifications
        from notifications_app.services import NotificationService
        result = NotificationService.send_lot_reception_notification(lot, agent_mali)
        
        logger.info(f"Tâche notification arrivée Mali - Lot {lot.numero_lot}: {result}")
        
        return result
        
    except Exception as e:
        error_msg = f"Erreur tâche notification arrivée Mali pour lot {lot_id}: {str(e)}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'lot_id': lot_id
        }


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 30})
def send_otp_async(self, phone_number, otp_code, cache_key=None, user_id=None):
    """
    Tâche asynchrone pour envoyer un OTP via WhatsApp
    Améliore la résilience et évite les plantages de l'interface utilisateur
    
    Args:
        phone_number: Numéro de téléphone destinataire
        otp_code: Code OTP à envoyer
        cache_key: Clé cache pour mettre à jour le statut
        user_id: ID utilisateur pour logging
    
    Returns:
        dict: Résultat de l'envoi avec statut et message user-friendly
    """
    from .wachap_service import send_whatsapp_otp
    from django.core.cache import cache
    from django.utils import timezone
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        # Mettre à jour le statut en cache : envoi en cours
        if cache_key:
            otp_data = cache.get(cache_key, {})
            otp_data.update({
                'status': 'sending',
                'sending_started_at': timezone.now().isoformat()
            })
            cache.set(cache_key, otp_data, timeout=600)
        
        logger.info(f"🔄 Envoi OTP asynchrone vers {phone_number} (tentative {self.request.retries + 1}/4)")
        
        # Envoi de l'OTP
        success, raw_message = send_whatsapp_otp(phone_number, otp_code)
        
        # Messages utilisateur-friendly (masquer les détails techniques)
        if success:
            user_message = "Code de vérification envoyé avec succès"
            final_status = 'sent'
            logger.info(f"✅ OTP envoyé avec succès vers {phone_number}")
        else:
            # Convertir les erreurs techniques en messages compréhensibles
            if "timeout" in raw_message.lower():
                user_message = "Service temporairement indisponible. Nouvelle tentative en cours..."
            elif "invalid" in raw_message.lower() or "invalidé" in raw_message.lower():
                user_message = "Service de messagerie en maintenance. Réessayez dans quelques minutes."
            elif "network" in raw_message.lower() or "connexion" in raw_message.lower():
                user_message = "Problème de connexion. Nouvelle tentative automatique..."
            else:
                user_message = "Erreur temporaire. Nous réessayons automatiquement..."
            
            final_status = 'failed'
            logger.error(f"❌ Échec envoi OTP vers {phone_number}: {raw_message}")
            
            # Déclencher un retry automatique si pas encore max retries
            if self.request.retries < 3:
                logger.warning(f"⏳ Retry #{self.request.retries + 2} dans 30 secondes...")
                raise Exception(f"Retry OTP: {raw_message}")
        
        # Mettre à jour le statut final en cache
        if cache_key:
            otp_data = cache.get(cache_key, {})
            otp_data.update({
                'status': final_status,
                'user_message': user_message,
                'completed_at': timezone.now().isoformat(),
                'attempts': self.request.retries + 1
            })
            cache.set(cache_key, otp_data, timeout=600)
        
        return {
            'success': success,
            'user_message': user_message,
            'phone_number': phone_number,
            'attempts': self.request.retries + 1,
            'final_attempt': True
        }
        
    except Exception as e:
        logger.error(f"💥 Erreur critique envoi OTP vers {phone_number}: {str(e)}")
        
        # Statut d'échec définitif si on est au dernier retry
        if self.request.retries >= 3:
            if cache_key:
                otp_data = cache.get(cache_key, {})
                otp_data.update({
                    'status': 'failed_final',
                    'user_message': 'Impossible d\'envoyer le code actuellement. Contactez le support.',
                    'completed_at': timezone.now().isoformat(),
                    'attempts': self.request.retries + 1
                })
                cache.set(cache_key, otp_data, timeout=600)
            
            return {
                'success': False,
                'user_message': 'Impossible d\'envoyer le code actuellement. Contactez le support.',
                'phone_number': phone_number,
                'attempts': self.request.retries + 1,
                'final_attempt': True
            }
        else:
            # Re-raise pour déclencher le retry automatique
            raise e
