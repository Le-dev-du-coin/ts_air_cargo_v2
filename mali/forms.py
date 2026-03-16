from django import forms
from core.models import Colis
from notification.models import ConfigurationNotification

class ColisUpdateMaliForm(forms.ModelForm):
    class Meta:
        model = Colis
        fields = ["type_colis", "nombre_pieces", "poids", "cbm", "prix_kilo_manuel"]
        widgets = {
            "type_colis": forms.Select(
                attrs={
                    "class": "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                }
            ),
            "nombre_pieces": forms.NumberInput(
                attrs={
                    "class": "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm",
                    "min": "1",
                }
            ),
            "poids": forms.NumberInput(
                attrs={
                    "class": "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm",
                    "step": "0.01",
                }
            ),
            "cbm": forms.NumberInput(
                attrs={
                    "class": "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm",
                    "step": "0.0001",
                }
            ),
            "prix_kilo_manuel": forms.NumberInput(
                attrs={
                    "class": "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm",
                    "step": "0.1",
                }
            ),
        }

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
            "admin_mali_phone_2",
            "admin_mali_phone_3",
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
            "admin_mali_phone_2": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "+223XXXXXXXX",
                }
            ),
            "admin_mali_phone_3": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "+223XXXXXXXX",
                }
            ),
        }
