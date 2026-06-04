import logging
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
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
            logger.warning(
                f"[send_notification_async] Échec initial de l'envoi pour user_id={user_id}. "
                f"La notification est enregistrée en statut 'echec' et sera prise en charge par le retry périodique."
            )

    except Exception as e:
        logger.error(f"[send_notification_async] Erreur inattendue: {e}")


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
        .values_list("destinataire_id", flat=True)
        .distinct()
    )

    colis_to_remind = (
        Colis.objects.filter(
            status="ARRIVE",
            lot__date_arrivee__lte=threshold_date,
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
        if getattr(colis, 'paye_en_chine', False) or colis.est_paye:
            montant_a_payer = 0
        else:
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
            if getattr(colis, 'paye_en_chine', False) or colis.est_paye:
                montant_colis = 0
            else:
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


@shared_task(bind=True)
def retry_failed_notifications_periodic(self, force_retry_all=False, region=None):
    """
    File d'attente WhatsApp : retente l'envoi des notifications en échec.
    - Utilise un verrou (lock) de cache pour éviter les exécutions concurrentes de la même tâche.
    - Utilise select_for_update(skip_locked=True) pour garantir qu'une notification n'est traitée
      que par un seul worker à la fois.
    - Augmentation de la sécurité anti-boucle.
    """
    from .services.wachap_service import wachap_service

    lock_id = f"lock_retry_notifs_{region or 'all'}"
    # On évite que la même tâche tourne en plusieurs exemplaires
    if not cache.add(lock_id, self.request.id, 1800):  # 30 minutes max
        logger.info(f"[Retry] Tâche déjà en cours pour la région {region or 'all'}. Skip.")
        return "Already running"

    try:
        if force_retry_all:
            notifications_qs = Notification.objects.filter(
                statut__in=["echec", "echec_permanent"]
            )
        else:
            notifications_qs = Notification.objects.filter(
                statut="echec",
                prochaine_tentative__lte=timezone.now(),
            ).exclude(nombre_tentatives__gte=5)
            
        if region:
            notifications_qs = notifications_qs.filter(region=region)

        # Récupérer les IDs pour itérer sans tenir un verrou sur tout le queryset
        notification_ids = list(notifications_qs.values_list("id", flat=True))

        count_success = 0
        count_fail = 0

        for notif_id in notification_ids:
            # Traitement atomique par notification
            with transaction.atomic():
                # select_for_update(skip_locked=True) est crucial ici : 
                # si un autre worker traite déjà cette notif, on passe à la suivante.
                notification = (
                    Notification.objects.select_for_update(skip_locked=True)
                    .filter(pk=notif_id)
                    .first()
                )

                if not notification:
                    continue

                # --- MISE À JOUR DU NUMÉRO SI RÉPARÉ DANS LE PROFIL ---
                if notification.destinataire:
                    user = notification.destinataire
                    new_phone = ""
                    if hasattr(user, "client_profile") and user.client_profile:
                        new_phone = user.client_profile.telephone
                    elif user.phone:
                        new_phone = user.phone

                    if new_phone and new_phone != notification.telephone_destinataire:
                        logger.info(
                            f"[Retry] Mise à jour du numéro pour Notification {notification.id}: "
                            f"{notification.telephone_destinataire} -> {new_phone}"
                        )
                        notification.telephone_destinataire = new_phone
                        notification.save(update_fields=["telephone_destinataire"])

                if not notification.telephone_destinataire:
                    notification.marquer_comme_echec(
                        "Pas de numéro de téléphone", erreur_type="permanent"
                    )
                    count_fail += 1
                    continue

                # Remise à zéro puis incrément d'une relance forcée sur échec permanent
                if force_retry_all and notification.statut == "echec_permanent":
                    notification.nombre_tentatives = 1
                else:
                    # Incrémenter le compteur avant l'envoi
                    notification.nombre_tentatives += 1

                notification.save(update_fields=["nombre_tentatives"])

                try:
                    # Note : on utilise un timeout long (défini dans wachap_service)
                    success, error_msg, message_id = wachap_service.send_message_with_type(
                        phone=notification.telephone_destinataire,
                        message=notification.message,
                        message_type="text",
                        region=notification.region,
                    )

                    if success:
                        notification.marquer_comme_envoye(message_id)
                        count_success += 1
                        logger.info(
                            f"[Retry] Notification {notification.id} renvoyée avec succès à "
                            f"{notification.telephone_destinataire}"
                        )
                    else:
                        error_str = str(error_msg).lower()
                        if any(x in error_str for x in ["invalide", "n'existe pas", "incorrect"]):
                            notification.marquer_comme_echec(
                                "Numéro incorrect ou invalide", erreur_type="permanent"
                            )
                        else:
                            # Vérifier si le numéro est bien sur WhatsApp
                            is_on_wa = wachap_service.check_number_registered(
                                notification.telephone_destinataire, region=notification.region
                            )
                            if not is_on_wa:
                                error_msg = "Numéro non inscrit sur WA"
                                notification.marquer_comme_echec(
                                    error_msg, erreur_type="permanent"
                                )
                            else:
                                error_msg = f"{error_msg} (Inscrit sur WhatsApp)"
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

    finally:
        # Libération du verrou global de la tâche
        if cache.get(lock_id) == self.request.id:
            cache.delete(lock_id)


@shared_task
def send_daily_report_mali(target_date_str=None):
    """
    Rapport journalier Mali envoyé via WhatsApp.
    Si target_date_str est fourni (format 'YYYY-MM-DD'), calcule pour cette date.
    Sinon, calcule pour la date actuelle.
    """
    from .services.wachap_service import wachap_service

    config = ConfigurationNotification.get_solo()
    admin_phones = [
        config.admin_mali_phone,
        config.admin_mali_phone_2,
        config.admin_mali_phone_3,
    ]
    # Filtrer les numéros vides ou None
    valid_phones = [p for p in admin_phones if p]

    if not valid_phones:
        logger.info(
            "[RapportJour] Aucun admin_mali_phone configuré — rapport non envoyé."
        )
        return "Rapport non envoyé : aucun numéro d'admin Mali configuré."

    try:
        from django.db.models import Sum, F, Q, Value, ExpressionWrapper, DecimalField
        from django.db.models.functions import Coalesce
        from core.models import User, Client, Lot, Colis, AvoirMouvement, Country
        from report.finance_engine import FinanceEngine
        from decimal import Decimal

        if target_date_str:
            try:
                from datetime import datetime
                today = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            except ValueError:
                today = timezone.now().date()
        else:
            today = timezone.now().date()

        try:
            mali = Country.objects.get(code="ML")
        except Country.DoesNotExist:
            logger.error("[RapportJour] Pays Mali (code=ML) non trouvé en BDD.")
            return "Erreur : pays Mali non configuré."

        # --- CALCULS VIA LE MOTEUR CENTRALISÉ ---
        fin_stats = FinanceEngine.get_daily_summary(today, mali)

        # Détails par type (pour le message)
        def get_nb_ca(transport_type):
            qs = Colis.objects.filter(
                lot__destination=mali,
                lot__type_transport=transport_type
            ).filter(
                Q(encaissements__date=today) | 
                Q(date_encaissement=today) |
                Q(status="LIVRE", date_livraison=today, date_encaissement__isnull=True)
            ).distinct()
            
            nb = qs.count()
            # On somme les encaissements RÉELS du jour pour ce type
            from core.models import EncaissementColis
            ca_reels = EncaissementColis.objects.filter(
                colis__in=qs,
                date=today
            ).exclude(methode="AVANCE").aggregate(total=Sum("montant"))["total"] or 0
            
            # On ajoute les legacy pour la cohérence
            ca_legacy = qs.filter(
                date_encaissement=today,
                encaissements__isnull=True
            ).annotate(
                val=ExpressionWrapper(
                    F("prix_final") - Coalesce(F("montant_jc"), Value(0)),
                    output_field=DecimalField()
                )
            ).aggregate(total=Sum("val"))["total"] or 0

            return nb, Decimal(ca_reels) + Decimal(ca_legacy)

        nb_cargo, ca_cargo = get_nb_ca("CARGO")
        nb_express, ca_express = get_nb_ca("EXPRESS")
        nb_bateau, ca_bateau = get_nb_ca("BATEAU")

        total_recettes_colis = ca_cargo + ca_express + ca_bateau
        total_rechargements = fin_stats["total_rechargements_avoir"]
        total_recettes_global = fin_stats["total_recettes_jour"]
        
        total_depenses = fin_stats["total_depenses"]
        total_transferts = fin_stats["total_transferts"]
        total_sorties = fin_stats["total_sorties_jour"]

        solde_veille = fin_stats["solde_veille"]
        solde_caisse = fin_stats["solde_caisse_actuel"]

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
            f"💳 *RECHARGEMENTS AVOIR*\n"
            f"   • Total : {total_rechargements:,.0f} FCFA\n\n"
            f"{'─' * 30}\n"
            f"💰 *Total Recettes :* {total_recettes_global:,.0f} FCFA\n"
            f"💸 *Dépenses :* {total_depenses:,.0f} FCFA\n"
            f"🔄 *Transferts :* {total_transferts:,.0f} FCFA\n"
            f"{'─' * 30}\n"
            f"🏦 *Solde Veille :* {solde_veille:,.0f} FCFA\n"
            f"✅ *Solde Caisse :* {solde_caisse:,.0f} FCFA"
        )

        # --- Envoi WhatsApp ---
        results = []
        import time

        for phone in valid_phones:
            # Tentative de récupération de l'utilisateur associé au numéro
            admin_user = User.objects.filter(Q(phone=phone) | Q(client_profile__telephone=phone)).first()

            try:
                logger.info(f"[RapportJour] Envoi en cours vers {phone}...")
                
                # Création de la notification pour archivage et suivi des erreurs
                notification = Notification.objects.create(
                    destinataire=admin_user,
                    telephone_destinataire=phone,
                    message=message,
                    categorie="rapport_journalier",
                    titre=f"Rapport Journalier {date_str}",
                    region="mali",
                    statut="en_attente"
                )

                success, error, message_id = wachap_service.send_message(
                    phone=phone,
                    message=message,
                    region="mali",
                )

                if success:
                    notification.marquer_comme_envoye(message_id)
                    logger.info(
                        f"[RapportJour] Rapport envoyé à {phone} (ID: {message_id})"
                    )
                    results.append(f"Succès ({phone})")
                else:
                    notification.marquer_comme_echec(error)
                    logger.error(f"[RapportJour] Échec envoi à {phone}: {error}")
                    results.append(f"Échec ({phone}: {error})")

                # Délai de sécurité pour éviter les blocages API
                time.sleep(2)
            except Exception as e:
                if 'notification' in locals():
                    notification.marquer_comme_echec(str(e))
                logger.error(f"[RapportJour] Erreur critique lors de l'envoi à {phone}: {e}")
                results.append(f"Erreur critique ({phone}: {str(e)})")

        return " | ".join(results)

    except Exception as e:
        logger.error(f"[RapportJour] Exception: {e}", exc_info=True)
        return f"Erreur rapport journalier : {e}"


@shared_task
def cleanup_old_notifications_periodic():
    """
    Supprime de la base de données toutes les notifications avec statut 'envoye'
    datant de plus de 7 jours, afin d'économiser de l'espace disque.
    """
    from .models import Notification

    threshold_date = timezone.now() - timezone.timedelta(days=7)

    try:
        deleted_count, _ = Notification.objects.filter(
            statut="envoye", date_creation__lte=threshold_date
        ).delete()

        logger.info(
            f"[Cleanup] Suppression de {deleted_count} anciennes notifications terminée."
        )
        return f"Nettoyage terminé : {deleted_count} entrées supprimées."
    except Exception as e:
        logger.error(f"[Cleanup] Erreur lors du nettoyage : {e}")
        return f"Erreur nettoyage : {e}"


def perform_avoir_imputation_colis(colis, user):
    """
    Logique atomique pour imputer l'avoir d'un client sur un colis spécifique.
    Retourne (montant_impute, success, error_message)
    """
    from django.db import transaction
    from decimal import Decimal
    from django.apps import apps
    
    AvoirMouvement = apps.get_model("core", "AvoirMouvement")
    EncaissementColis = apps.get_model("core", "EncaissementColis")
    
    if not colis.client or colis.client.solde_avoir <= 0:
        return Decimal('0'), False, "Client sans avoir ou solde nul"
    
    # Si le colis est déjà marqué comme payé mais qu'il reste un montant (ex: douane ajoutée après)
    # ou s'il n'est pas marqué payé mais a un reste à payer nul (erreur Chine)
    if colis.reste_a_payer <= 0:
        if not colis.est_paye:
            colis.est_paye = True
            colis.save()
            return Decimal('0'), True, "Colis déjà soldé (Ajustement statut)"
        return Decimal('0'), False, "Colis déjà totalement payé"
        
    try:
        with transaction.atomic():
            # Verrouillage du client pour éviter les accès concurrents
            client = colis.client.__class__.objects.select_for_update().get(pk=colis.client.pk)
            
            montant_a_payer = colis.reste_a_payer
            montant_impute = min(montant_a_payer, client.solde_avoir)
            
            if montant_impute > 0:
                # 1. Déduction de l'avoir
                client.solde_avoir -= montant_impute
                client.save()
                
                # 2. Mise à jour du colis
                colis.reste_a_payer -= montant_impute
                if colis.reste_a_payer <= 0:
                    colis.est_paye = True
                    colis.reste_a_payer = 0
                
                colis.mode_paiement = "AVANCE"
                colis.paye_par_avance = True
                colis.save()
                
                # 3. Tracer l'encaissement
                EncaissementColis.objects.create(
                    colis=colis,
                    montant=montant_impute,
                    methode="AVANCE",
                    enregistre_par=user,
                    date=timezone.now().date()
                )
                
                # 4. Tracer le mouvement d'avoir
                AvoirMouvement.objects.create(
                    client=client,
                    montant=montant_impute,
                    type="CONSOMMATION",
                    colis=colis,
                    enregistre_par=user,
                    commentaire=f"Paiement auto (Lot {colis.lot.numero})"
                )
                return montant_impute, True, None
    except Exception as e:
        return Decimal('0'), False, str(e)
    
    return Decimal('0'), False, "Inconnu"


@shared_task
def impute_avoir_colis_async(colis_id, user_id):
    """
    Tâche asynchrone pour imputer l'avoir d'un client sur un colis spécifique.
    Accélère l'interface lors du pointage (Pointage -> Imputation en arrière-plan).
    """
    from django.apps import apps
    Colis = apps.get_model("core", "Colis")
    User = apps.get_model("core", "User")

    try:
        colis = Colis.objects.select_related('client', 'lot').get(pk=colis_id)
        user = User.objects.get(pk=user_id)
        
        if colis.client and colis.client.solde_avoir > 0 and colis.reste_a_payer > 0:
            mt, success, err = perform_avoir_imputation_colis(colis, user)
            if success:
                logger.info(f"Imputation auto réussie (Celery) pour {colis.reference} : {mt} FCFA")
            else:
                logger.error(f"Échec imputation auto (Celery) pour {colis.reference} : {err}")
    except Exception as e:
        logger.error(f"Erreur task impute_avoir_colis_async (Colis ID {colis_id}): {e}")


@shared_task
def impute_avoirs_lot_async(lot_id, user_id):
    """
    Tâche asynchrone pour imputer les avoirs des clients ayant des colis dans un lot spécifique.
    """
    from django.apps import apps
    Lot = apps.get_model("core", "Lot")
    User = apps.get_model("core", "User")

    try:
        lot = Lot.objects.prefetch_related('colis', 'colis__client').get(pk=lot_id)
        user = User.objects.get(pk=user_id)
        
        # On traite tous les colis du lot pour le log, même si déjà payés
        tous_colis = lot.colis.all().order_by("-prix_final")
        
        total_impute = 0
        skipped_count = 0
        
        logger.info(f"Début imputation lot {lot.numero} (ID: {lot.id}) - {tous_colis.count()} colis à vérifier")

        for c in tous_colis:
            client_name = str(c.client) if c.client else "Inconnu"
            
            # On ne filtre plus par est_paye ici pour permettre le rattrapage des douanes
            if c.reste_a_payer <= 0:
                if not c.est_paye:
                    c.est_paye = True
                    c.save()
                    logger.info(f"  > Colis {c.reference} ({client_name}) : Déjà soldé. Statut corrigé.")
                else:
                    logger.info(f"  > Colis {c.reference} ({client_name}) : Déjà payé. Ignoré.")
                skipped_count += 1
                continue
                
            if not c.client:
                logger.warning(f"  > Colis {c.reference} : Aucun client rattaché. Ignoré.")
                skipped_count += 1
                continue
                
            if c.client.solde_avoir <= 0:
                logger.info(f"  > Colis {c.reference} ({client_name}) : Solde avoir à 0. Ignoré.")
                skipped_count += 1
                continue
            
            # Si on arrive ici, on tente l'imputation
            if c.reste_a_payer > 0 and c.client and c.client.solde_avoir > 0:
                logger.info(f"  > Tentative imputation Colis {c.reference} ({client_name}) - Avoir: {c.client.solde_avoir}")
                mt, success, err = perform_avoir_imputation_colis(c, user)
                
                if success:
                    total_impute += mt
                    logger.info(f"    ✅ SUCCÈS : {mt} FCFA imputés sur {c.reference}")
                else:
                    logger.error(f"    ❌ ÉCHEC : {c.reference} - Erreur: {err}")
                    skipped_count += 1
            else:
                logger.info(f"    - Pas d'imputation nécessaire ou possible pour {c.reference}")
                skipped_count += 1
                    
        logger.info(f"=== FIN IMPUTATION LOT {lot.numero} ===")
        logger.info(f"Total Imputé : {total_impute} FCFA")
        logger.info(f"Colis ignorés/échoués : {skipped_count}")

    except Exception as e:
        logger.error(f"Erreur CRITIQUE imputation async lot {lot_id}: {e}")


@shared_task
def send_maintenance_reminder_periodic():
    """
    Rappel automatique du contrat de maintenance tous les 6 du mois.
    Message personnalisé et pro-humoristique pour l'Admin Mali.
    """
    config = ConfigurationNotification.get_solo()
    
    if not config.activer_rappel_maintenance:
        logger.info("[Maintenance] Rappel désactivé dans les paramètres.")
        return "Rappel désactivé."

    # Destinataire principal de l'admin Mali
    target_phone = config.admin_mali_phone
    if not target_phone:
        logger.warning("[Maintenance] Aucun numéro admin_mali_phone configuré.")
        return "Échec : Aucun numéro configuré."

    # Personnalisation avec le nom de l'admin Mali
    from core.models import User
    admin = User.objects.filter(role="ADMIN_MALI", is_active=True).first()
    admin_name = f"{admin.first_name} {admin.last_name}".strip() if admin else "Gérant"
    if not admin_name:
        admin_name = admin.username if admin else "Gérant"

    # Mois en cours en français
    import locale
    try:
        locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
    except:
        pass
    mois_actuel = timezone.now().strftime("%B %Y").capitalize()

    message = (
        f"Bonjour **Patron {admin_name}** ! 🛠️\n\n"
        f"C'est déjà le **6 du mois** ! L'heure est venue de faire le **paiement du contrat de maintenance** du système TS Air Cargo pour le mois de **{mois_actuel}**. 💳\n\n"
        f"Le développeur, c'est-à-dire moi **Salif SANOGO**, a pris la liberté d'ajouter ce petit rappel car il paraît que parfois vous **oubliez souvent** ! 😉\n\n"
        f"Bon début de journée et courage pour la gestion !\n"
        f"À très bientôt le mois prochain pour un nouveau message (et une nouvelle relance si besoin) ! 😂\n\n"
        f"——\n"
        f"_📩 Notification automatique ajoutée par votre développeur préféré pour vous aider à vous rappeler du paiement._"
    )

    from .services.wachap_service import wachap_service
    success, error, message_id = wachap_service.send_message(
        phone=target_phone,
        message=message,
        region="mali"
    )

    if success:
        logger.info(f"[Maintenance] Rappel envoyé avec succès à {target_phone}.")
        return f"Succès : Rappel envoyé à {admin_name}."
    else:
        logger.error(f"[Maintenance] Échec envoi rappel : {error}")
        return f"Échec : {error}"
