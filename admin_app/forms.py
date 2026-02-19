from django import forms
from notification.models import ConfigurationNotification


class NotificationConfigAdminForm(forms.ModelForm):
    """
    Formulaire d'administration — API WaChap V4.
    1 clé secrète globale + 1 accountId par région.
    """

    class Meta:
        model = ConfigurationNotification
        fields = [
            # Clé secrète globale V4
            "wachap_v4_secret_key",
            # AccountId par région
            "wachap_account_chine",
            "wachap_account_mali",
            "wachap_account_cote_divoire",
            "wachap_account_system",
            # Contacts système
            "developer_phone",
            "test_phone_number",
            "security_code",
        ]
        widgets = {
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
            "test_phone_number": forms.TextInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}
            ),
        }
