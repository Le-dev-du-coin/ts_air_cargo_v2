from django import forms
from .models import Depense


class DepenseForm(forms.ModelForm):
    class Meta:
        model = Depense
        fields = ["montant", "motif", "type_depense", "date"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "montant": forms.NumberInput(attrs={"min": "0", "step": "100"}),
        }
