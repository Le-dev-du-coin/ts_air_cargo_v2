from django import template
from django.urls import reverse, NoReverseMatch

register = template.Library()


@register.simple_tag(takes_context=True)
def transport_url(context, viewname, *args, **kwargs):
    """
    Résout une URL et lui préfixe automatiquement /maritime/ ou /aerien/
    en fonction du mode de transport de la requête courante.

    Usage dans le template :
        {% load transport_tags %}
        {% transport_url 'mali:dashboard' %}
        {% transport_url 'mali:lot_transit_detail' pk=lot.pk %}
    """
    request = context.get("request")

    try:
        url = reverse(viewname, args=args, kwargs=kwargs)
    except NoReverseMatch:
        return "#"

    if request and getattr(request, "is_maritime", False):
        # En mode Maritime : préfixer avec /maritime
        # L'URL de base est /mali/... → /maritime/mali/...
        return f"/maritime{url}"
    else:
        # En mode Aérien : préfixer avec /aerien
        return f"/aerien{url}"
