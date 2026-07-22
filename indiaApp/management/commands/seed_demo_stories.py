from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from indiaApp.models import Story

class Command(BaseCommand):
    help='Create a small, clearly labelled development-only story showcase.'
    def handle(self,*args,**options):
        if not settings.DEBUG: raise CommandError('Demo content is disabled when DEBUG=False.')
        examples=[
            ('demo-text-story','Example Story: I finally wrote one honest sentence','text','family','This is demonstration content for the public text-story interface. It is not a real student submission.'),
            ('demo-voice-story','Demo Voice Story','voice','heard','Demo Content. A local audio file may be attached by staff to preview accessible controls.'),
            ('demo-video-story','Demo Video Story','video','college','Demo Content. A safe local video file may be attached by staff to preview the video layout.'),
            ('demo-exam-pressure','Example Story: My result was not my whole life','text','exam','This example exists only to preview the exam-pressure page and is not a real testimonial.'),
            ('demo-hope-story','Example Story: I asked someone to listen','text','hope','This example exists only to preview the hope page. It does not claim to describe a real person.'),
        ]
        for slug,title,format_,topic,body in examples:
            Story.objects.update_or_create(slug=slug,defaults={'title':title,'body':body,'story_format':format_,'topic':topic,'display_name':'Demo Content','approved':True,'moderation_status':'published','public_consent':True,'privacy_review_complete':True,'published_at':timezone.now(),'is_demo':True,'comment_mode':'none'})
        self.stdout.write(self.style.SUCCESS('Created or updated 5 clearly labelled demo stories.'))
