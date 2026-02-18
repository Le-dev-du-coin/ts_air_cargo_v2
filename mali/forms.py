from django import forms
from notification.models import ConfigurationNotification


class NotificationConfigForm(forms.ModelForm):
    class Meta:
        model = ConfigurationNotification
        fields = [
            "rappels_actifs",
            "delai_rappel_jours",
            "template_rappel",
            "wachap_mali_access_token",
            "wachap_mali_instance_id",
            "wachap_chine_access_token",
            "wachap_chine_instance_id",
            "wachap_system_access_token",
            "wachap_system_instance_id",
            "developer_phone",
            "security_code",
        ]
        widgets = {
            "template_rappel": forms.Textarea(
                attrs={"rows": 3, "class": "w-full border-gray-300 rounded-md"}
            ),
            "template_rappel_groupe": forms.Textarea(
                attrs={"rows": 3, "class": "w-full border-gray-300 rounded-md"}
            ),
            "delai_rappel_jours": forms.NumberInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}
            ),
            "wachap_mali_access_token": forms.PasswordInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}, render_value=True
            ),
            "wachap_mali_instance_id": forms.PasswordInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}, render_value=True
            ),
            "wachap_chine_access_token": forms.PasswordInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}, render_value=True
            ),
            "wachap_chine_instance_id": forms.PasswordInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}, render_value=True
            ),
            "wachap_system_access_token": forms.PasswordInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}, render_value=True
            ),
            "wachap_system_instance_id": forms.PasswordInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}, render_value=True
            ),
            "security_code": forms.PasswordInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}, render_value=True
            ),
            "developer_phone": forms.TextInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}
            ),
        }
