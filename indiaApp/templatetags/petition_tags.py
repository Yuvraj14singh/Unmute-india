from django import template
from indiaApp.utils import compact_count

register = template.Library()
register.filter('compact_count', compact_count)
