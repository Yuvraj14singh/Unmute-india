from django.db import migrations
from django.utils import timezone

def preserve_public_stories(apps, schema_editor):
    Story=apps.get_model('indiaApp','Story')
    for story in Story.objects.filter(approved=True):
        story.moderation_status='published'
        story.public_consent=True
        story.privacy_review_complete=True
        story.published_at=story.created_at or timezone.now()
        story.save(update_fields=['moderation_status','public_consent','privacy_review_complete','published_at'])

class Migration(migrations.Migration):
    dependencies=[('indiaApp','0008_story_featured_story_is_demo_and_more')]
    operations=[migrations.RunPython(preserve_public_stories,migrations.RunPython.noop)]
