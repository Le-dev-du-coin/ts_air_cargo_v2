import logging
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from .models import Notification, ConfigurationNotification
from .services.notification_service import notification_service
from .services.wachap_monitor import wachap_monitor
from .services.alert_system import alert_system
from django.apps import apps

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification_async(
    self, user_id, message, categorie="autre", titre="", media_url=None, region=None
):
    """
    Tâche asynchrone pour envoyer une notification avec retry.
    En cas d'échec définitif (max_retries atteint), la notification reste en BDD
    avec statut 'echec' pour être relancée par retry_failed_notifications_periodic.
    """
    from celery.exceptions import MaxRetriesExceededError

    try:
        # Récupérer l'utilisateur (User ou Client)
        User = apps.get_model(settings.AUTH_USER_MODEL)
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            logger.error(f"User {user_id} not found for notification")
            return

        success, notification = notification_service.send_notification(
            destinataire=user,
            message=message,
            categorie=categorie,
            titre=titre,
            media_url=media_url,
            region=region,
        )

        if not success:
            # Retry avec backoff exponentiel
            try:
                raise self.retry(countdown=60 * (2**self.request.retries))
            except MaxRetriesExceededError:
                # Max retries atteint : la notification est déjà en statut 'echec'
                # en BDD, elle sera reprise par retry_failed_notifications_periodic
                logger.warning(
                    f"[send_notification_async] Max retries atteint pour user_id={user_id}. "
                    f"La notification sera relancée par la file d'attente."
                )
                return

    except MaxRetriesExceededError:
        logger.warning(
            f"[send_notification_async] MaxRetriesExceeded (user_id={user_id}). "
            f"File d'attente prendra le relais."
        )
    except Exception as e:
        logger.error(f"[send_notification_async] Erreur inattendue: {e}")
        try:
            raise self.retry(exc=e, countdown=60 * (2**self.request.retries))
        except MaxRetriesExceededError:
            logger.warning(
                f"[send_notification_async] Max retries atteint sur exception pour user_id={user_id}."
            )


@shared_task
def check_wachap_status_periodic():
    """Vérifie l'état des instances WaChap (toutes les 15min)"""
    return wachap_monitor.run_monitoring_check()


@shared_task
def check_system_health_periodic():
    """Vérifie la santé du système de notification (horaire)"""
    alert_system.check_and_alert()


@shared_task
def send_parcel_reminders_periodic():
    """
    Envoie les rappels automatiques pour les colis arrivés non récupérés.
    Configuration (délai, activation) gérée dans ConfigurationNotification.
    """
    config = ConfigurationNotification.get_solo()
    if not config.rappels_actifs:
        return "Rappels désactivés"

    # Récupérer le modèle Colis
    Colis = apps.get_model("core", "Colis")

    # Calculer la date limite (ARRIVE depuis X jours)
    # Ex: Si délai = 3 jours, on cherche les colis arrivés avant (Maintenant - 3 jours)
    # Et qui sont toujours statut ARRIVE
    threshold_date = timezone.now() - timezone.timedelta(days=config.delai_rappel_jours)

    # Anti-spam : exclure les clients déjà notifiés dans les 20 dernières heures
    recent_cutoff = timezone.now() - timezone.timedelta(hours=20)
    clients_recemment_notifies = (
        Notification.objects.filter(
            categorie="rappel_colis",
            date_creation__gte=recent_cutoff,
        )
        .values_list("user_id", flat=True)
        .distinct()
    )

    colis_to_remind = (
        Colis.objects.filter(
            status="ARRIVE",
            updated_at__lte=threshold_date,
        )
        .exclude(
            client__user_id__in=clients_recemment_notifies,
        )
        .select_related("client", "client__user")
    )

    # Grouper par client
    reminders_data = {}

    for colis in colis_to_remind:
        client = colis.client
        if not client or not client.user:
            continue

        user_id = client.user.id

        if user_id not in reminders_data:
            reminders_data[user_id] = {
                "user": client.user,
                "client": client,
                "colis_list": [],
                "total_montant": 0,
            }

        # Calcul montant
        montant_a_payer = (colis.prix_final or 0) - (colis.montant_jc or 0)

        reminders_data[user_id]["colis_list"].append(colis)
        reminders_data[user_id]["total_montant"] += max(0, montant_a_payer)

    count_notifs = 0

    for user_id, data in reminders_data.items():
        user = data["user"]
        colis_list = data["colis_list"]
        total_montant = data["total_montant"]
        nb_colis = len(colis_list)

        # Liste des codes (max 5 pour pas surcharger)
        refs = [c.reference for c in colis_list[:5]]
        if nb_colis > 5:
            refs.append("...")
        liste_ref = ", ".join(refs)

        formatted_total = "{:,.0f} FCFA".format(total_montant).replace(",", " ")

        # Message
        if nb_colis == 1:
            # Mode simple
            colis = colis_list[0]
            montant_colis = (colis.prix_final or 0) - (colis.montant_jc or 0)
            fmt_montant = "{:,.0f} FCFA".format(max(0, montant_colis)).replace(",", " ")
            message = config.template_rappel.format(
                numero_suivi=colis.reference,
                jours=config.delai_rappel_jours,
                client_nom=data["client"].nom,
                montant=fmt_montant,
            )
            titre = f"Rappel Colis {colis.reference}"
        else:
            # Mode groupé
            message = config.template_rappel_groupe.format(
                client_nom=data["client"].nom,
                nombre_colis=nb_colis,
                jours=config.delai_rappel_jours,
                liste_ref=liste_ref,
                total_montant=formatted_total,
            )
            titre = f"Rappel : {nb_colis} Colis disponibles"

        # Envoyer notif
        notification_service.send_notification(
            destinataire=user,
            message=message,
            categorie="rappel_colis",
            titre=titre,
        )
        count_notifs += 1

    return f"Rappels envoyés: {count_notifs} clients notifiés for {len(colis_to_remind)} colis."


@shared_task
def retry_failed_notifications_periodic():
    """
    File d'attente WhatsApp : retente l'envoi des notifications en échec.
    - Récupère toutes les Notification avec statut='echec' et prochaine_tentative <= now()
    - Tente de les renvoyer via wachap_service
    - Met à jour le statut (envoye / echec avec backoff / echec_permanent si >= 5 tentatives)
    Appelée toutes les 5 minutes par le beat schedule, et sur reconnexion d'une instance.
    """
    from .services.wachap_service import wachap_service

    notifications_to_retry = Notification.objects.filter(
        statut="echec",
        prochaine_tentative__lte=timezone.now(),
    ).exclude(nombre_tentatives__gte=5)

    count_success = 0
    count_fail = 0

    for notification in notifications_to_retry:
        if not notification.telephone_destinataire:
            notification.marquer_comme_echec(
                "Pas de numéro de téléphone", erreur_type="permanent"
            )
            count_fail += 1
            continue

        # Déterminer le type de message
        msg_type = "text"

        # Incrémenter le compteur avant l'envoi
        notification.nombre_tentatives += 1
        notification.save(update_fields=["nombre_tentatives"])

        try:
            success, error_msg, message_id = wachap_service.send_message_with_type(
                phone=notification.telephone_destinataire,
                message=notification.message,
                message_type=msg_type,
            )

            if success:
                notification.marquer_comme_envoye(message_id)
                count_success += 1
                logger.info(
                    f"[Retry] Notification {notification.id} renvoyée avec succès à "
                    f"{notification.telephone_destinataire}"
                )
            else:
                notification.marquer_comme_echec(error_msg)
                count_fail += 1
                logger.warning(
                    f"[Retry] Notification {notification.id} - échec #{notification.nombre_tentatives}: {error_msg}"
                )

        except Exception as e:
            notification.marquer_comme_echec(str(e))
            count_fail += 1
            logger.error(f"[Retry] Exception sur notification {notification.id}: {e}")

    total = count_success + count_fail
    logger.info(f"[Retry] Terminé: {count_success}/{total} renvoyées avec succès.")
    return f"Retry terminé: {count_success} succès, {count_fail} échecs sur {total} tentatives."


@shared_task
def send_daily_report_mali():
    """
    Rapport journalier Mali envoyé à 23h50 via WhatsApp au numéro admin_mali_phone.
    Calcule les données du jour : Cargo, Express, Bateau, Dépenses, Transferts, Solde.
    """
    from .services.wachap_service import wachap_service

    config = ConfigurationNotification.get_solo()
    admin_phone = config.admin_mali_phone or config.developer_phone

    if not admin_phone:
        logger.info(
            "[RapportJour] Ni admin_mali_phone ni developer_phone configuré — rapport non envoyé."
        )
        return "Rapport non envoyé : aucun numéro destinataire configuré."

    try:
        from django.db.models import Sum, F
        from core.models import Country, Colis

        today = timezone.now().date()

        try:
            mali = Country.objects.get(code="ML")
        except Country.DoesNotExist:
            logger.error("[RapportJour] Pays Mali (code=ML) non trouvé en BDD.")
            return "Erreur : pays Mali non configuré."

        # --- Colis livrés aujourd'hui ---
        colis_livres = Colis.objects.filter(
            lot__destination=mali,
            status="LIVRE",
            est_paye=True,
            updated_at__date=today,
        )

        def stat(qs):
            nb = qs.count()
            ca = (
                qs.aggregate(total=Sum(F("prix_final") - F("montant_jc")))["total"] or 0
            )
            return nb, ca

        nb_cargo, ca_cargo = stat(colis_livres.filter(lot__type_transport="CARGO"))
        nb_express, ca_express = stat(
            colis_livres.filter(lot__type_transport="EXPRESS")
        )
        nb_bateau, ca_bateau = stat(colis_livres.filter(lot__type_transport="BATEAU"))
        total_recettes = ca_cargo + ca_express + ca_bateau

        # --- Dépenses & Transferts ---
        try:
            from report.models import Depense, TransfertArgent

            total_depenses = (
                Depense.objects.filter(pays=mali, date=today).aggregate(
                    total=Sum("montant")
                )["total"]
                or 0
            )
            total_transferts = (
                TransfertArgent.objects.filter(
                    pays_expediteur=mali, date=today
                ).aggregate(total=Sum("montant"))["total"]
                or 0
            )
        except Exception:
            total_depenses = 0
            total_transferts = 0

        total_sorties = total_depenses + total_transferts

        # --- Solde de la veille ---
        recettes_avant = (
            Colis.objects.filter(
                lot__destination=mali,
                status="LIVRE",
                est_paye=True,
                updated_at__date__lt=today,
            ).aggregate(total=Sum(F("prix_final") - F("montant_jc")))["total"]
            or 0
        )
        try:
            dep_avant = (
                Depense.objects.filter(pays=mali, date__lt=today).aggregate(
                    total=Sum("montant")
                )["total"]
                or 0
            )
            trans_avant = (
                TransfertArgent.objects.filter(
                    pays_expediteur=mali, date__lt=today
                ).aggregate(total=Sum("montant"))["total"]
                or 0
            )
        except Exception:
            dep_avant = trans_avant = 0

        solde_veille = recettes_avant - (dep_avant + trans_avant)
        solde_jour = solde_veille + total_recettes - total_sorties

        # --- Construction du message ---
        date_str = today.strftime("%d/%m/%Y")
        message = (
            f"📊 *RAPPORT JOURNALIER MALI — {date_str}*\n"
            f"{'─' * 30}\n\n"
            f"📦 *CARGO*\n"
            f"   • Colis livrés : {nb_cargo}\n"
            f"   • Recette : {ca_cargo:,.0f} FCFA\n\n"
            f"✈️ *EXPRESS*\n"
            f"   • Colis livrés : {nb_express}\n"
            f"   • Recette : {ca_express:,.0f} FCFA\n\n"
            f"🚢 *BATEAU*\n"
            f"   • Colis livrés : {nb_bateau}\n"
            f"   • Recette : {ca_bateau:,.0f} FCFA\n\n"
            f"{'─' * 30}\n"
            f"💰 *Total Recettes :* {total_recettes:,.0f} FCFA\n"
            f"💸 *Dépenses :* {total_depenses:,.0f} FCFA\n"
            f"🔄 *Transferts :* {total_transferts:,.0f} FCFA\n"
            f"{'─' * 30}\n"
            f"🏦 *Solde Veille :* {solde_veille:,.0f} FCFA\n"
            f"✅ *Solde Caisse :* {solde_jour:,.0f} FCFA"
        )

        # --- Envoi WhatsApp ---
        success, error, message_id = wachap_service.send_message(
            phone=admin_phone,
            message=message,
            region="mali",
        )

        if success:
            logger.info(
                f"[RapportJour] Rapport envoyé à {admin_phone} (ID: {message_id})"
            )
            return f"Rapport journalier envoyé à {admin_phone}."
        else:
            logger.error(f"[RapportJour] Échec envoi à {admin_phone}: {error}")
            return f"Échec envoi rapport : {error}"

    except Exception as e:
        logger.error(f"[RapportJour] Exception: {e}", exc_info=True)
        return f"Erreur rapport journalier : {e}"
