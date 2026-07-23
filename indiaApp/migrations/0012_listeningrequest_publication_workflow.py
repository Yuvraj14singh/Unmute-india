from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('indiaApp', '0011_petitionsignature_google_subject_and_more'),
    ]

    operations = [
        migrations.AddField(model_name='listeningrequest', name='public_sharing_consent', field=models.BooleanField(default=False, db_index=True, help_text='The student explicitly allowed this submission to be reviewed for anonymous public sharing.')),
        migrations.AddField(model_name='listeningrequest', name='publication_status', field=models.CharField(choices=[('private', 'Private — not submitted for publication'), ('review', 'Public sharing review requested'), ('published', 'Approved and published'), ('rejected', 'Public sharing declined')], db_index=True, default='private', max_length=12)),
        migrations.AddField(model_name='listeningrequest', name='published_story', field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='source_listening_request', to='indiaApp.story')),
        migrations.AddField(model_name='listeningrequest', name='reviewed_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='listeningrequest', name='reviewed_by', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_listening_requests', to=settings.AUTH_USER_MODEL)),
    ]
