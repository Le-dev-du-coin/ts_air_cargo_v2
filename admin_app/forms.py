from django import forms
from notification.models import ConfigurationNotification


class NotificationConfigAdminForm(forms.ModelForm):
    """
    Formulaire d'administration — API WaChap V4 + Alertes Email/SMTP.
    1 clé secrète globale + 1 accountId par région + config SMTP Hostinger.
    """

    class Meta:
        model = ConfigurationNotification
        fields = [
            # Application globale
            "app_version",
            # WaChap V4
            "wachap_v4_secret_key",
            "wachap_account_chine",
            "wachap_account_mali",
            "wachap_account_cote_divoire",
            "wachap_account_system",
            # Contacts & Sécurité
            "developer_phone",
            "developer_email",
            "test_phone_number",
            "security_code",
            # SMTP
            "smtp_host",
            "smtp_port",
            "smtp_user",
            "smtp_password",
            "smtp_use_ssl",
        ]
        widgets = {
            "app_version": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "V2.0.1",
                }
            ),
            "wachap_v4_secret_key": forms.PasswordInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "sk_...",
                },
                render_value=True,
            ),
            "wachap_account_chine": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "acc_chine_...",
                }
            ),
            "wachap_account_mali": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "acc_mali_...",
                }
            ),
            "wachap_account_cote_divoire": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "acc_ci_...",
                }
            ),
            "wachap_account_system": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "acc_system_...",
                }
            ),
            "security_code": forms.PasswordInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}, render_value=True
            ),
            "developer_phone": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "+223XXXXXXXX",
                }
            ),
            "developer_email": forms.EmailInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "dev@ts-aircargo.com",
                }
            ),
            "test_phone_number": forms.TextInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}
            ),
            "smtp_host": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "smtp.hostinger.com",
                }
            ),
            "smtp_port": forms.NumberInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}
            ),
            "smtp_user": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "noreply@ts-aircargo.com",
                }
            ),
            "smtp_password": forms.PasswordInput(
                attrs={"class": "w-full border-gray-300 rounded-md"},
                render_value=True,
            ),
        }
