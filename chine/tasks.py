import os
import logging
from celery import shared_task
from django.utils import timezone
from django.core.files.base import ContentFile
from django.conf import settings
from core.models import Colis, Lot, BackgroundTask, Client

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def process_colis_creation(self, task_record_id):
    task_record = BackgroundTask.objects.get(pk=task_record_id)
    task_record.status = BackgroundTask.Status.PROCESSING
    task_record.started_at = timezone.now()
    task_record.task_id = self.request.id
    task_record.save()

    try:
        params = task_record.parameters
        lot = Lot.objects.get(pk=params["lot_id"])
        client = Client.objects.get(pk=params["client_id"])

        colis = Colis(
            lot=lot,
            country=lot.country,
            client=client,
            type_colis=params["type_colis"],
            nombre_pieces=params["nombre_pieces"],
            description=params["description"],
            poids=params["poids"],
            longueur=params["longueur"],
            largeur=params["largeur"],
            hauteur=params["hauteur"],
            cbm=params["cbm"],
            prix_final=params["prix_final"],
            est_paye=params["est_paye"],
        )

        # Handle photo if temp path provided
        temp_photo_path = params.get("temp_photo_path")
        if temp_photo_path and os.path.exists(temp_photo_path):
            with open(temp_photo_path, "rb") as f:
                colis.photo.save(
                    os.path.basename(temp_photo_path), ContentFile(f.read()), save=False
                )
            # Cleanup temp file
            try:
                os.remove(temp_photo_path)
            except Exception as e:
                logger.error(f"Error removing temp file {temp_photo_path}: {e}")

        colis.save()

        task_record.status = BackgroundTask.Status.SUCCESS
        task_record.completed_at = timezone.now()
        task_record.save()

    except Exception as e:
        logger.exception("Error in process_colis_creation")
        task_record.status = BackgroundTask.Status.FAILURE
        task_record.error_message = str(e)
        task_record.completed_at = timezone.now()
        task_record.save()
        raise e
