"""
Services de notifications pour ts_air_cargo
Version nettoyée - Migration WaChap complète
"""

import logging
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from .models import Notification
from .wachap_service import wachap_service

logger = logging.getLogger(__name__)

def get_colis_details_for_notification(colis):
    """
    Génère les détails d'un colis pour les notifications
    Retourne la description adaptée selon le type de transport et type de colis
    
    Args:
        colis: Instance du modèle Colis
        
    Returns:
        str: Description formatée (ex: "⚖️ Poids: 5 kg" ou "📱 Téléphone(s): 2 pièce(s)")
    """
    if colis.type_transport == 'bateau':
        return f"📊Dimensions: {colis.longueur}x{colis.largeur}x{colis.hauteur} cm"
    elif hasattr(colis, 'type_colis') and colis.type_colis in ['telephone', 'electronique']:
        # Tarif à la pièce
        type_display = 'Téléphone(s)' if colis.type_colis == 'telephone' else 'Électronique(s)'
        quantite = getattr(colis, 'quantite_pieces', 1)
        return f"📱 {type_display}: {quantite} pièce(s)"
    else:
        # Cargo ou express standard
        return f"⚖️ Poids: {colis.poids} kg"

class NotificationService:
    """
    Service centralisé pour l'envoi de notifications
    Migration complète vers WaChap - Twilio supprimé
    """
    
    @staticmethod
    def send_notification(user, message, method='whatsapp', title="Notification TS Air Cargo", categorie='information_generale', sender_role=None):
        """
        Envoie une notification à un utilisateur
        
        Args:
            user: Instance utilisateur
            message: Contenu du message
            method: Méthode d'envoi ('whatsapp', 'sms', 'email', 'in_app')
            title: Titre de la notification
            categorie: Catégorie de la notification
            sender_role: Rôle de l'expéditeur pour le routage WaChap
        """
        try:
            # Enregistrer la notification en base avec les bons champs
            notification = Notification.objects.create(
                destinataire=user,
                type_notification=method,
                categorie=categorie,
                titre=title,
                message=message,
                telephone_destinataire=user.telephone,
                email_destinataire=user.email or '',
                statut='en_attente'
            )
            
            # Envoyer selon la méthode choisie
            success = False
            message_id = None
            
            if method == 'whatsapp':
                success, message_id = NotificationService._send_whatsapp(user, message, categorie=categorie, title=title, sender_role=sender_role)
            elif method == 'sms':
                success, message_id = NotificationService._send_sms(user, message)
            elif method == 'email':
                success, message_id = NotificationService._send_email(user, message, title)
            elif method == 'in_app':
                success = True  # Déjà enregistré en base
            
            # Mettre à jour le statut de la notification
            if success:
                notification.marquer_comme_envoye(message_id)
                logger.info(f"Notification envoyée à {user.telephone} via {method}")
            else:
                notification.marquer_comme_echec("Échec d'envoi")
                logger.error(f"Échec envoi notification à {user.telephone} via {method}")
            
            return success
            
        except Exception as e:
            logger.error(f"Erreur envoi notification à {user.telephone}: {str(e)}")
            return False
    
    @staticmethod
    def _send_whatsapp(user, message, categorie=None, title=None, sender_role=None):
        """
        Envoie un message WhatsApp via WaChap
        """
        try:
            # Déterminer le numéro de destination
            dev_mode = getattr(settings, 'DEBUG', False)
            admin_phone = getattr(settings, 'ADMIN_PHONE', '').strip()
            test_phone = admin_phone if (dev_mode and admin_phone) else None
            destination_phone = test_phone or user.telephone
            
            logger.debug(
                "WA DEBUG _send_whatsapp: original=%s destination=%s dev=%s admin_phone_set=%s categorie=%s title=%s sender_role=%s",
                user.telephone, destination_phone, dev_mode, bool(admin_phone), categorie, title, sender_role
            )

            # Déterminer le type de message
            message_type = 'notification'
            if categorie in ['creation_compte', 'reinitialisation_mot_de_passe', 'otp', 'system', 'information_systeme']:
                if categorie in ['creation_compte', 'reinitialisation_mot_de_passe']:
                    message_type = 'account'
                elif categorie == 'otp':
                    message_type = 'otp'
                else:
                    message_type = 'system'
            elif title and ('OTP' in title or 'Compte' in title or 'Système' in title or 'Réinitialisation' in title or 'mot de passe' in title):
                if 'OTP' in title: message_type = 'otp'
                elif 'Compte' in title or 'Réinitialisation' in title or 'mot de passe' in title: message_type = 'account'
                elif 'Système' in title: message_type = 'system'

            # Déterminer le rôle de l'expéditeur, en donnant la priorité à celui qui est passé en paramètre
            final_sender_role = sender_role
            if not final_sender_role:
                final_sender_role = 'system' if message_type in ['otp', 'account', 'system'] else getattr(user, 'role', None)

            # Forcer l'instance selon la catégorie métier (priorité produit)
            region_override = None
            if categorie in {'colis_cree', 'lot_expedie', 'colis_en_transit'}:
                region_override = 'chine'
            elif categorie in {'colis_arrive', 'colis_livre'}:
                region_override = 'mali'
            
            # Enrichir le message en mode développement pour identification
            if test_phone and test_phone != user.telephone:
                enriched_message = f"""[DEV] Message pour: {user.get_full_name()}
Tél réel: {user.telephone}

---
{message}
---
TS Air Cargo - Mode Développement"""
            else:
                enriched_message = message
            
            # Envoyer via WaChap
            success, result_message, message_id = wachap_service.send_message_with_type(
                phone=destination_phone,
                message=enriched_message,
                message_type=message_type,
                sender_role=final_sender_role,
                region=region_override
            )
            
            if success:
                logger.info(
                    "WA OK: to_user=%s via=%s type=%s sender_role=%s msg_id=%s result=%s",
                    user.telephone, destination_phone, message_type, final_sender_role, message_id, result_message
                )
                return True, message_id
            else:
                logger.error(
                    "WA ERROR: to_user=%s via=%s type=%s sender_role=%s result=%s",
                    user.telephone, destination_phone, message_type, final_sender_role, result_message
                )
                return False, None
                
        except Exception as e:
            logger.error(f"Erreur WhatsApp WaChap pour {user.telephone}: {str(e)}")
            return False, None
    
    @staticmethod
    def _send_sms(user, message):
        """
        Envoie un SMS via le service SMS configuré (Twilio, AWS SNS, Orange Mali)
        """
        try:
            from .sms_service import SMSService
            
            # Vérifier si le service SMS est configuré
            if not SMSService.is_configured():
                logger.warning(f"Service SMS non configuré, simulation pour {user.telephone}")
                return True, 'sms_simulation_id'
            
            # Envoyer le SMS réel
            success, message_id = SMSService.send_sms(user.telephone, message)
            
            if success:
                logger.info(f"SMS envoyé à {user.telephone}, ID: {message_id}")
            else:
                logger.error(f"Échec envoi SMS à {user.telephone}: {message_id}")
            
            return success, message_id
            
        except Exception as e:
            logger.error(f"Erreur envoi SMS à {user.telephone}: {str(e)}")
            return False, str(e)
        
    @staticmethod
    def send_sms(telephone, message):
        """
        Méthode publique pour envoyer un SMS directement
        Utilise le vrai service SMS si configuré, sinon WaChap
        
        Args:
            telephone: Numéro de téléphone
            message: Message à envoyer
            
        Returns:
            bool: True si l'envoi a réussi, False sinon
        """
        try:
            from .sms_service import SMSService
            
            # Essayer d'abord le vrai SMS si configuré
            if SMSService.is_configured():
                success, message_id = SMSService.send_sms(telephone, message)
                if success:
                    logger.info(f"SMS réel envoyé avec succès à {telephone}")
                    return True
                else:
                    logger.warning(f"Échec SMS réel, tentative WaChap pour {telephone}")
            
            # Fallback sur WaChap
            from .wachap_service import wachap_service
            success, result, _ = wachap_service.send_message_with_type(
                phone=telephone,
                message=message,
                message_type='account',
                sender_role='system'
            )
            
            if success:
                logger.info(f"SMS WaChap envoyé avec succès à {telephone}")
                return True
            else:
                logger.error(f"Échec d'envoi du SMS à {telephone}: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du SMS à {telephone}: {str(e)}")
            return False
    
    @staticmethod
    def _send_email(user, message, title):
        """
        Envoie un email
        """
        try:
            send_mail(
                subject=title,
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@ts-aircargo.com'),
                recipient_list=[user.email],
                fail_silently=False,
            )
            logger.info(f"Email envoyé à {user.email}")
            return True, 'email_sent'
        except Exception as e:
            logger.error(f"Erreur envoi email à {user.email}: {str(e)}")
            return False, None
    
    @staticmethod
    def send_client_creation_notification(user, temp_password, sender_role=None, is_reset=False):
        """
        Notification pour la création ou la réinitialisation d'un compte client
        
        Args:
            user: L'utilisateur concerné
            temp_password: Le mot de passe temporaire
            sender_role: Le rôle de l'expéditeur (optionnel)
            is_reset: Si True, c'est une réinitialisation de mot de passe
            
        Returns:
            bool: Succès de l'envoi
        """
        try:
            # Déterminer le type de message
            if is_reset:
                title = "🔑 Réinitialisation de mot de passe"
                welcome_msg = "Votre mot de passe a été réinitialisé avec succès."
                categorie = 'reinitialisation_mot_de_passe'
            else:
                title = "👋 Bienvenue chez TS Air Cargo"
                welcome_msg = "Votre compte client a été créé avec succès."
                categorie = 'creation_compte'

            # Préparer le message
            message = (
                f"{title}\n\n"
                f"{welcome_msg}\n\n"
                f"👤 Identifiant: {user.telephone}\n"
                f"🔑 Mot de passe temporaire: {temp_password}\n\n"
                f"🔒 Pour des raisons de sécurité, veuillez changer votre mot de passe dès votre première connexion.\n\n"
                f"Merci de votre confiance! 🚚"
            )
            
            # Envoyer la notification
            return NotificationService.send_notification(
                user=user,
                message=message,
                method='whatsapp',
                title=title,
                categorie=categorie,
                sender_role=sender_role
            )
            
        except Exception as e:
            logger.error(f"Erreur envoi notification création/reset à {user.telephone}: {str(e)}")
            return False
    
    @staticmethod
    def send_critical_notification(user, temp_password, notification_type='password_reset', sender_role=None):
        """
        Envoie une notification critique via WhatsApp (WaChap)
        L'envoi SMS via Orange API sera configuré ultérieurement
        Utilisé pour les notifications importantes comme la réinitialisation de mot de passe
        
        Args:
            user: L'utilisateur concerné
            temp_password: Le mot de passe temporaire
            notification_type: Type de notification ('password_reset', 'account_creation')
            sender_role: Rôle de l'expéditeur pour le routage WaChap
            
        Returns:
            dict: {
                'whatsapp': bool (succès WhatsApp),
                'sms': bool (succès SMS - False pour l'instant),
                'success': bool (au moins un canal a réussi)
            }
        """
        try:
            # Déterminer le contenu selon le type
            if notification_type == 'password_reset':
                title = "🔑 Réinitialisation de mot de passe"
                welcome_msg = "Votre mot de passe a été réinitialisé avec succès."
                categorie = 'reinitialisation_mot_de_passe'
            else:
                title = "👋 Bienvenue chez TS Air Cargo"
                welcome_msg = "Votre compte client a été créé avec succès."
                categorie = 'creation_compte'
            
            # Préparer le message
            message = (
                f"{title}\n\n"
                f"{welcome_msg}\n\n"
                f"👤 Identifiant: {user.telephone}\n"
                f"🔑 Mot de passe temporaire: {temp_password}\n\n"
                f"🔒 Pour des raisons de sécurité, veuillez changer votre mot de passe dès votre première connexion.\n\n"
                f"Merci de votre confiance! 🚚"
            )
            
            # Résultats d'envoi
            results = {
                'whatsapp': False,
                'sms': False,
                'success': False
            }
            
            # Envoyer via WhatsApp (WaChap)
            try:
                whatsapp_success = NotificationService.send_notification(
                    user=user,
                    message=message,
                    method='whatsapp',
                    title=title,
                    categorie=categorie,
                    sender_role=sender_role
                )
                results['whatsapp'] = whatsapp_success
                results['success'] = whatsapp_success
                logger.info(f"WhatsApp critique envoyé à {user.telephone}: {whatsapp_success}")
            except Exception as e:
                logger.error(f"Erreur WhatsApp critique pour {user.telephone}: {str(e)}")
            
            # Envoyer via SMS (Orange API) si configuré
            try:
                from .orange_sms_service import orange_sms_service
                from .models import SMSLog
                
                if orange_sms_service.is_configured():
                    # Version courte pour SMS (limite de caractères)
                    sms_message = (
                        f"{title}\n"
                        f"Identifiant: {user.telephone}\n"
                        f"Mot de passe: {temp_password}\n"
                        f"Changez-le dès votre première connexion.\n"
                        f"TS Air Cargo"
                    )
                    
                    # Enregistrer le log SMS
                    sms_log = SMSLog.objects.create(
                        user=user,
                        destinataire_telephone=user.telephone,
                        message=sms_message,
                        provider='orange',
                        statut='pending',
                        metadata={'type': notification_type}
                    )
                    
                    # Envoyer le SMS
                    sms_success, message_id, response_data = orange_sms_service.send_sms(user.telephone, sms_message)
                    
                    if sms_success:
                        sms_log.mark_as_sent(message_id)
                        results['sms'] = True
                        logger.info(f"SMS Orange envoyé à {user.telephone}: {message_id}")
                    else:
                        sms_log.mark_as_failed(message_id)
                        logger.error(f"SMS Orange échoué pour {user.telephone}: {message_id}")
                else:
                    logger.debug("Orange SMS non configuré, envoi SMS non disponible")
            except Exception as e:
                logger.error(f"Erreur SMS Orange pour {user.telephone}: {str(e)}")
            
            # Au moins un canal doit réussir
            results['success'] = results['whatsapp'] or results['sms']
            
            logger.info(
                f"Notification critique pour {user.telephone}: "
                f"WA={results['whatsapp']}, SMS={results['sms']}, Succès={results['success']}"
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Erreur envoi notification critique à {user.telephone}: {str(e)}")
            return {'whatsapp': False, 'sms': False, 'success': False}
    
    @staticmethod
    def send_urgent_notification(user, message, title="🚨 Notification Urgente"):
        """
        Envoie une notification urgente avec formatage spécial
        """
        urgent_message = f"""🚨 URGENT - TS Air Cargo

{message}

⏰ {timezone.now().strftime('%d/%m/%Y à %H:%M')}
📞 Contactez-nous si nécessaire.

Équipe TS Air Cargo"""

        return NotificationService.send_notification(
            user=user,
            message=urgent_message,
            method='whatsapp',
            title=title,
            categorie='urgente'
        )
    
    @staticmethod
    def send_report_notification(recipient_phone, report_type, date, summary):
        """
        Envoie une notification de rapport automatique
        """
        message = f"""📊 Rapport {report_type} TS Air Cargo

📅 Date: {date}
📈 Résumé: {summary}

Le rapport détaillé est disponible sur la plateforme.

Équipe TS Air Cargo"""

        return NotificationService.send_whatsapp_message(recipient_phone, message)
    
    @staticmethod
    def send_lot_reception_notification(lot, agent_mali):
        """
        Envoie des notifications aux clients lors de la réception d'un lot au Mali
        
        Args:
            lot: Instance du lot réceptionné
            agent_mali: Agent qui a réceptionné le lot
            
        Returns:
            dict: Statistiques d'envoi
        """
        try:
            # Récupérer tous les clients uniques du lot
            colis_list = lot.colis.select_related('client__user').all()
            clients_notifies = set()  # Pour éviter les doublons
            notifications_envoyees = 0
            
            for colis in colis_list:
                client = colis.client
                
                # Éviter les doublons si un client a plusieurs colis dans le même lot
                if client.id in clients_notifies:
                    continue
                clients_notifies.add(client.id)
                
                # Générer les détails du colis (poids ou pièces)
                details_colis = get_colis_details_for_notification(colis)
                
                # Préparer le message personnalisé
                message = f"""🉟🇮 Excellente nouvelle !

Votre colis du lot {lot.numero_lot} est arrivé à Bamako !

📅 Date d'arrivée: {timezone.now().strftime('%d/%m/%Y à %H:%M')}
📦 Numéro de suivi: {colis.numero_suivi}
{details_colis}

Nous vous contacterons bientôt pour organiser la livraison.

Équipe TS Air Cargo Mali 🚀"""
                
                # Envoyer la notification
                success = NotificationService.send_notification(
                    user=client.user,
                    message=message,
                    method='whatsapp',
                    title='Colis arrivé au Mali',
                    categorie='colis_arrive'
                )
                
                if success:
                    notifications_envoyees += 1
            
            logger.info(f"Notifications d'arrivée envoyées pour le lot {lot.numero_lot}: {notifications_envoyees} clients notifiés")
            
            return {
                'success': True,
                'lot_id': lot.id,
                'clients_count': len(clients_notifies),
                'notifications_sent': notifications_envoyees
            }
            
        except Exception as e:
            error_msg = f"Erreur lors de l'envoi des notifications d'arrivée pour le lot {lot.numero_lot}: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg,
                'lot_id': getattr(lot, 'id', None)
            }
    
    @staticmethod
    def retry_notifications_for_lot(lot, initiated_by=None):
        """
        Réessaie l'envoi de toutes les notifications échouées ou en attente pour un lot
        
        Args:
            lot: Instance du lot concerné
            initiated_by: Utilisateur qui a déclenché le retry (optionnel)
            
        Returns:
            dict: Statistiques du retry {
                'success': bool,
                'total_notifications': int,
                'sent': int,
                'failed': int,
                'already_sent': int,
                'details': list
            }
        """
        try:
            # Récupérer toutes les notifications échouées ou en attente pour les colis du lot
            notifications = Notification.objects.filter(
                lot_reference=lot,
                statut__in=['echec', 'en_attente']
            ).select_related('destinataire', 'colis_reference')
            
            total = notifications.count()
            sent_count = 0
            failed_count = 0
            details = []
            
            logger.info(
                f"Début retry notifications pour lot {lot.numero_lot}: "
                f"{total} notification(s) à renvoyer. Initialisé par: {initiated_by or 'Système'}"
            )
            
            # Renvoyer chaque notification
            for notif in notifications:
                try:
                    # Réinitialiser le nombre de tentatives et la date de prochaine tentative
                    notif.nombre_tentatives = 0
                    notif.prochaine_tentative = timezone.now()
                    notif.save(update_fields=['nombre_tentatives', 'prochaine_tentative'])
                    
                    # Renvoyer selon le type
                    success = False
                    message_id = None
                    
                    if notif.type_notification == 'whatsapp':
                        success, message_id = NotificationService._send_whatsapp(
                            notif.destinataire,
                            notif.message,
                            categorie=notif.categorie,
                            title=notif.titre
                        )
                    elif notif.type_notification == 'sms':
                        success, message_id = NotificationService._send_sms(
                            notif.destinataire,
                            notif.message
                        )
                    elif notif.type_notification == 'email':
                        success, message_id = NotificationService._send_email(
                            notif.destinataire,
                            notif.message,
                            notif.titre
                        )
                    
                    # Mettre à jour le statut
                    if success:
                        notif.marquer_comme_envoye(message_id)
                        sent_count += 1
                        details.append({
                            'notification_id': notif.id,
                            'destinataire': notif.destinataire.get_full_name(),
                            'telephone': notif.telephone_destinataire,
                            'status': 'sent',
                            'colis': notif.colis_reference.numero_suivi if notif.colis_reference else None
                        })
                        logger.info(
                            f"Notification {notif.id} renvoyée avec succès à "
                            f"{notif.destinataire.telephone} (msg_id: {message_id})"
                        )
                    else:
                        notif.marquer_comme_echec(
                            f"Retry échoué - API indisponible ou erreur réseau",
                            erreur_type='temporaire'
                        )
                        failed_count += 1
                        details.append({
                            'notification_id': notif.id,
                            'destinataire': notif.destinataire.get_full_name(),
                            'telephone': notif.telephone_destinataire,
                            'status': 'failed',
                            'colis': notif.colis_reference.numero_suivi if notif.colis_reference else None
                        })
                        logger.error(
                            f"Notification {notif.id} retry échoué pour "
                            f"{notif.destinataire.telephone}"
                        )
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(
                        f"Erreur retry notification {notif.id}: {str(e)}"
                    )
                    details.append({
                        'notification_id': notif.id,
                        'destinataire': notif.destinataire.get_full_name() if notif.destinataire else 'Inconnu',
                        'telephone': notif.telephone_destinataire,
                        'status': 'error',
                        'error': str(e)
                    })
            
            # Compter les notifications déjà envoyées (pour info)
            already_sent = Notification.objects.filter(
                lot_reference=lot,
                statut='envoye'
            ).count()
            
            success = sent_count > 0 or total == 0
            
            logger.info(
                f"Fin retry lot {lot.numero_lot}: "
                f"{sent_count}/{total} envoyées, {failed_count} échecs, "
                f"{already_sent} déjà envoyées"
            )
            
            return {
                'success': success,
                'total_notifications': total,
                'sent': sent_count,
                'failed': failed_count,
                'already_sent': already_sent,
                'details': details
            }
            
        except Exception as e:
            error_msg = f"Échec retry notifications lot {lot.numero_lot}: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg,
                'total_notifications': 0,
                'sent': 0,
                'failed': 0,
                'already_sent': 0,
                'details': []
            }
