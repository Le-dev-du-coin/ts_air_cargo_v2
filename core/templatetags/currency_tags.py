from django import template

register = template.Library()

@register.filter(name='fcfa')
def fcfa(value):
    try:
        if value is None:
            return "0 FCFA"
        # Format with space as thousand separator, no decimal
        return "{:,.0f} FCFA".format(float(value)).replace(',', ' ')
    except (ValueError, TypeError):
        return value
