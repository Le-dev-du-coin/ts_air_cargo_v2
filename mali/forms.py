from django import forms
from notification.models import ConfigurationNotification


class NotificationConfigForm(forms.ModelForm):
    """
    Formulaire agent Mali : rappels automatiques + numéro de rapport journalier.
    Les credentials API WaChap sont gérés par l'administrateur.
    """

    class Meta:
        model = ConfigurationNotification
        fields = [
            "rappels_actifs",
            "delai_rappel_jours",
            "template_rappel",
            "admin_mali_phone",
        ]
        widgets = {
            "template_rappel": forms.Textarea(
                attrs={"rows": 4, "class": "w-full border-gray-300 rounded-md"}
            ),
            "delai_rappel_jours": forms.NumberInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}
            ),
            "admin_mali_phone": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "+223XXXXXXXX",
                }
            ),
        }
