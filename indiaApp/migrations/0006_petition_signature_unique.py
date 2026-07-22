from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('indiaApp','0005_seed_editable_petition')]
    operations = [
        migrations.AddConstraint(
            model_name='petitionsignature',
            constraint=models.UniqueConstraint(fields=('petition','normalized_email'), name='unique_email_per_petition'),
        )
    ]
