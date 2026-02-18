# Generated migration for SMS tracking

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('notifications_app', '0004_alter_configurationnotification_twilio_account_sid_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SMSLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('destinataire_telephone', models.CharField(max_length=20, verbose_name='Numéro destinataire')),
                ('message', models.TextField(verbose_name='Contenu du SMS')),
                ('provider', models.CharField(choices=[('orange', 'Orange SMS'), ('twilio', 'Twilio'), ('aws_sns', 'AWS SNS')], default='orange', max_length=20, verbose_name='Provider')),
                ('statut', models.CharField(choices=[('pending', 'En attente'), ('sent', 'Envoyé'), ('delivered', 'Délivré'), ('failed', 'Échec'), ('expired', 'Expiré')], default='pending', max_length=20, verbose_name='Statut')),
                ('message_id', models.CharField(blank=True, max_length=255, null=True, verbose_name='ID du message')),
                ('error_message', models.TextField(blank=True, null=True, verbose_name="Message d'erreur")),
                ('cost', models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True, verbose_name='Coût (FCFA)')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Date de création')),
                ('sent_at', models.DateTimeField(blank=True, null=True, verbose_name="Date d'envoi")),
                ('delivered_at', models.DateTimeField(blank=True, null=True, verbose_name='Date de livraison')),
                ('metadata', models.JSONField(blank=True, default=dict, verbose_name='Métadonnées')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sms_logs', to=settings.AUTH_USER_MODEL, verbose_name='Utilisateur')),
            ],
            options={
                'verbose_name': 'Log SMS',
                'verbose_name_plural': 'Logs SMS',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['destinataire_telephone'], name='notificatio_destina_sms_idx'),
                    models.Index(fields=['statut'], name='notificatio_statut_sms_idx'),
                    models.Index(fields=['created_at'], name='notificatio_created_sms_idx'),
                ],
            },
        ),
    ]
