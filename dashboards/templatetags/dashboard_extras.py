from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Safe dict lookup for templates. Accepts numeric or string keys."""
    if dictionary is None:
        return None
    try:
        try:
            k = int(key)
        except Exception:
            k = key
        return dictionary.get(k)
    except Exception:
        return None
