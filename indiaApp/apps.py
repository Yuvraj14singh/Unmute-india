from django.apps import AppConfig
from django.db.models.signals import post_migrate

def create_petition_roles(sender, **kwargs):
    from django.contrib.auth.models import Group, Permission
    roles = {
        'Petition Editor': ['add_petition','change_petition','view_petition'],
        'Petition Manager': ['add_petition','change_petition','view_petition','delete_petition','publish_petition','view_petition_analytics'],
        'Signature Moderator': ['view_petitionsignature','change_petitionsignature','moderate_petition_signatures'],
        'Super Admin': [],
    }
    for name, codenames in roles.items():
        group, _ = Group.objects.get_or_create(name=name)
        if codenames:
            group.permissions.set(Permission.objects.filter(content_type__app_label='indiaApp', codename__in=codenames))


class IndiaappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'indiaApp'
    def ready(self):
        post_migrate.connect(create_petition_roles, sender=self)
