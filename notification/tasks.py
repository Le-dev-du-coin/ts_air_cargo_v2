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
    self, user_id, message, categorie="autre", titre="", media_url=None
):
    """
    Tâche asynchrone pour envoyer une notification avec retry
    """
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
        )

        if not success:
            # Retry si échec temporaire
            raise self.retry(countdown=60 * (2**self.request.retries))

    except Exception as e:
        logger.error(f"Error in send_notification_async: {e}")
        raise self.retry(exc=e)


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

    colis_to_remind = (
        Colis.objects.filter(
            status="ARRIVE",
            updated_at__lte=threshold_date,  # updated_at est mis à jour quand statut change en ARRIVE
            # On peut aussi utiliser un champ date_arrivee s'il existe (il existe sur Lot, pas explicite sur Colis, mais updated_at fait l'affaire si statut changé)
        )
        .exclude(
            # Exclure ceux déjà notifiés récemment pour éviter le spam quotidien ?
            # Pour l'instant on envoie une fois par jour si toujours pas récupéré.
            # Ou on vérifie s'il y a déjà une notif "rappel_colis" récente ?
            notifications__categorie="rappel_colis",
            notifications__date_creation__gte=timezone.now()
            - timezone.timedelta(hours=20),
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
