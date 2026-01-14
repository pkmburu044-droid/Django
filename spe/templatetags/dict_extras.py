from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Return the value for a dictionary key."""
    return dictionary.get(key)
