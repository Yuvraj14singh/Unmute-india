from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch
from pathlib import Path
from .forms import GooglePetitionSupportForm
from .models import CommentReaction, CommentReport, ListeningRequest, Petition, PetitionSignature, PublicQuestion, Story, StoryComment
from .utils import compact_count

class PublicPageTests(TestCase):
    def test_core_pages_load(self):
        for name in ['home','talk','stories','safety']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_one_sentence_private_submission(self):
        response = self.client.post(reverse('share', args=['text']), {'message':'I am scared.','anonymous':'on','wants_reply':'on','consent':'on'})
        self.assertRedirects(response, reverse('received'))
        item = ListeningRequest.objects.get()
        self.assertEqual(item.privacy, 'private')
        self.assertTrue(item.anonymous)
        self.assertFalse(item.public_sharing_consent)
        self.assertEqual(item.publication_status, 'private')

    def test_staff_can_publish_only_an_explicitly_consented_submission(self):
        staff = get_user_model().objects.create_superuser('moderator', 'moderator@example.com', 'safe-test-password')
        consented = ListeningRequest.objects.create(
            kind='text',
            message='A student story approved for the public feed.',
            public_sharing_consent=True,
            publication_status='review',
        )
        private = ListeningRequest.objects.create(
            kind='text',
            message='This must stay private.',
            public_sharing_consent=False,
            publication_status='private',
        )
        self.client.force_login(staff)
        response = self.client.post(reverse('admin:indiaApp_listeningrequest_changelist'), {
            'action':'approve_and_publish',
            '_selected_action':[consented.pk, private.pk],
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        consented.refresh_from_db(); private.refresh_from_db()
        self.assertEqual(consented.publication_status, 'published')
        self.assertIsNotNone(consented.published_story_id)
        self.assertTrue(consented.published_story.is_public)
        self.assertEqual(private.publication_status, 'private')
        self.assertIsNone(private.published_story_id)
        self.assertContains(self.client.get(reverse('stories')), 'A student story approved for the public feed.')
        self.assertNotContains(self.client.get(reverse('stories')), 'This must stay private.')

    def test_private_story_not_in_feed(self):
        Story.objects.create(body='Private draft',slug='private',approved=False)
        self.assertNotContains(self.client.get(reverse('stories')), 'Private draft')

    def test_support_page_and_public_story_detail(self):
        self.assertEqual(self.client.get(reverse('page', args=['support'])).status_code, 200)
        story = Story.objects.create(body='A moderated public story.', slug='heard-story', approved=True, moderation_status='published', public_consent=True, privacy_review_complete=True)
        self.assertContains(self.client.get(reverse('stories')), 'A moderated public story.')
        self.assertEqual(self.client.get(reverse('story_detail', args=[story.slug])).status_code, 200)

    def test_dashboard_requires_staff(self):
        user=get_user_model().objects.create_user('student',password='testpass123')
        self.client.login(username='student',password='testpass123')
        self.assertEqual(self.client.get(reverse('dashboard')).status_code,302)

    def test_accountability_page_and_moderated_question(self):
        self.assertEqual(self.client.get(reverse('accountability')).status_code, 200)
        response = self.client.post(reverse('accountability'), {
            'action':'question', 'question-question':'Who is responsible?',
            'question-anonymous':'on', 'question-consent':'on',
        })
        self.assertRedirects(response, reverse('accountability'))
        self.assertFalse(PublicQuestion.objects.get().approved)

    @override_settings(GOOGLE_CLIENT_ID='client', TURNSTILE_SITE_KEY='site', TURNSTILE_SECRET_KEY='secret')
    def test_petition_uses_google_without_public_email_field(self):
        petition=Petition.objects.filter(petition_status='published').first()
        response=self.client.get(reverse('petition_detail',args=[petition.slug]))
        self.assertContains(response, 'Verify one genuine support per Google account.')
        self.assertContains(response, 'cf-turnstile')
        self.assertNotContains(response, 'name="email"')
        self.assertNotContains(response, 'verification email will be sent')
        self.assertNotContains(response, 'verified-email-row')
        self.assertNotContains(response, 'form-response show')
        self.assertContains(response, 'type="hidden" name="website"', html=False)

    @override_settings(GOOGLE_CLIENT_ID='client', TURNSTILE_SITE_KEY='site', TURNSTILE_SECRET_KEY='secret')
    def test_petition_google_button_has_one_stable_container_and_script(self):
        petition=Petition.objects.filter(petition_status='published').first()
        response=self.client.get(reverse('petition_detail',args=[petition.slug]))
        self.assertContains(response, 'id="google-signin-button"', count=1)
        self.assertContains(response, 'https://accounts.google.com/gsi/client', count=1)

    def test_google_frontend_is_single_render_and_uses_mobile_safe_popup_mode(self):
        source=(Path(__file__).resolve().parent.parent / 'static/js/accountability/petition_detail.js').read_text()
        self.assertIn('let googleInitialized = false', source)
        self.assertIn('let googleButtonRendered = false', source)
        self.assertIn('if (googleInitialized || googleButtonRendered) return', source)
        self.assertIn('use_fedcm_for_button: false', source)
        self.assertIn('itp_support: true', source)
        self.assertIn('googleShell.getBoundingClientRect().width', source)

    def test_google_button_css_is_stable_and_clickable(self):
        source=(Path(__file__).resolve().parent.parent / 'static/css/accountability/petition_detail.css').read_text()
        self.assertIn('.google-button-shell>div,.google-button-shell iframe', source)
        self.assertIn('pointer-events:auto!important', source)
        self.assertIn('animation:none!important', source)

class PetitionSystemTests(TestCase):
    def setUp(self):
        self.petition=Petition.objects.create(title='Test petition',slug='test-petition',short_heading='Test',summary='Summary',primary_demand='Action',petition_status='published',allow_signatures=True)

    def support_data(self, **overrides):
        data={'name':'Student','supporter_type':'student','consent':'on','credential':'raw-google-token','turnstile_token':'turnstile-token'}
        data.update(overrides); return data

    @property
    def support_url(self): return reverse('google_petition_support',args=[self.petition.slug])

    def identity(self, sub='google-123', email='Student@Example.com'):
        return {'sub':sub,'email':email.strip().casefold(),'issuer':'https://accounts.google.com'}

    @override_settings(GOOGLE_CLIENT_ID='client',TURNSTILE_SITE_KEY='site',TURNSTILE_SECRET_KEY='secret')
    @patch('indiaApp.views._verify_turnstile', return_value={'hostname':'unmute-india.onrender.com'})
    @patch('indiaApp.views._verify_google_credential')
    def test_valid_google_support_counts_once_and_stores_no_token(self, google, turnstile):
        google.return_value=self.identity()
        response=self.client.post(self.support_url,self.support_data())
        self.assertTrue(response.json()['ok']); self.assertFalse(response.json()['duplicate'])
        signature=PetitionSignature.objects.get()
        self.assertTrue(signature.is_verified); self.assertEqual(signature.verification_method,'google')
        self.assertEqual(signature.google_subject,'google-123'); self.assertEqual(signature.verified_email,'student@example.com')
        self.assertNotIn('raw-google-token',str(signature.verification_metadata)); self.assertEqual(self.petition.verified_count,1)
        duplicate=self.client.post(self.support_url,self.support_data()).json()
        self.assertTrue(duplicate['duplicate']); self.assertEqual(PetitionSignature.objects.count(),1); self.assertEqual(self.petition.verified_count,1)

    def test_google_form_requires_every_security_field(self):
        for missing in ('name','supporter_type','consent','credential','turnstile_token'):
            data=self.support_data(); data.pop(missing)
            form=GooglePetitionSupportForm(data)
            self.assertFalse(form.is_valid(),missing); self.assertIn(missing,form.errors)

    @override_settings(GOOGLE_CLIENT_ID='client',TURNSTILE_SITE_KEY='site',TURNSTILE_SECRET_KEY='secret')
    @patch('indiaApp.views._verify_turnstile', side_effect=ValueError('invalid'))
    def test_invalid_turnstile_creates_nothing(self, verify):
        response=self.client.post(self.support_url,self.support_data())
        self.assertEqual(response.status_code,400); self.assertTrue(response.json()['reset_turnstile']); self.assertFalse(PetitionSignature.objects.exists())

    @override_settings(GOOGLE_CLIENT_ID='client',TURNSTILE_SITE_KEY='site',TURNSTILE_SECRET_KEY='secret')
    @patch('indiaApp.views._verify_turnstile', return_value={})
    @patch('indiaApp.views._verify_google_credential', side_effect=ValueError('invalid audience or expired'))
    def test_invalid_wrong_audience_or_expired_google_token_creates_nothing(self, google, turnstile):
        response=self.client.post(self.support_url,self.support_data())
        self.assertEqual(response.status_code,400); self.assertFalse(PetitionSignature.objects.exists())

    @override_settings(GOOGLE_CLIENT_ID='client',TURNSTILE_SITE_KEY='site',TURNSTILE_SECRET_KEY='secret')
    @patch('indiaApp.views._verify_turnstile', return_value={})
    @patch('indiaApp.views._verify_google_credential', side_effect=PermissionError('unverified'))
    def test_unverified_google_email_is_rejected(self, google, turnstile):
        response=self.client.post(self.support_url,self.support_data())
        self.assertContains(response,'does not have a verified email',status_code=400); self.assertFalse(PetitionSignature.objects.exists())

    @override_settings(GOOGLE_CLIENT_ID='client',TURNSTILE_SITE_KEY='site',TURNSTILE_SECRET_KEY='secret')
    @patch('indiaApp.views._verify_turnstile', return_value={})
    @patch('indiaApp.views._verify_google_credential')
    @patch('indiaApp.views.AuditLog.objects.create', side_effect=RuntimeError('database audit failure'))
    def test_transaction_rolls_back_if_commit_path_fails(self, audit, google, turnstile):
        google.return_value=self.identity()
        response=self.client.post(self.support_url,self.support_data())
        self.assertEqual(response.status_code,503)
        self.assertFalse(PetitionSignature.objects.exists())

    @override_settings(GOOGLE_CLIENT_ID='',TURNSTILE_SITE_KEY='',TURNSTILE_SECRET_KEY='')
    def test_missing_production_configuration_disables_support(self):
        response=self.client.post(self.support_url,self.support_data())
        self.assertEqual(response.status_code,503); self.assertFalse(PetitionSignature.objects.exists())

    def test_expired_token_fails_safely(self):
        import hashlib
        raw = 'expired-secure-token'
        signature = PetitionSignature.objects.create(petition=self.petition,name='Student',email='expired@example.com',supporter_type='student',consent=True,verification_token=hashlib.sha256(raw.encode()).hexdigest(),token_created_at=timezone.now()-timezone.timedelta(hours=25))
        response = self.client.get(reverse('petition_verify', args=[raw]))
        self.assertContains(response, 'discontinued')
        signature.refresh_from_db(); self.assertFalse(signature.is_verified)

    def test_legacy_verified_counts_but_pending_and_removed_do_not(self):
        PetitionSignature.objects.create(petition=self.petition,name='Legacy',email='legacy@example.com',supporter_type='teacher',consent=True,is_verified=True,verified_at=timezone.now(),moderation_status='valid')
        PetitionSignature.objects.create(petition=self.petition,name='Pending',email='pending@example.com',supporter_type='student',consent=True,is_verified=False,moderation_status='pending')
        PetitionSignature.objects.create(petition=self.petition,name='Spam',email='spam@example.com',supporter_type='citizen',consent=True,is_verified=True,moderation_status='spam')
        PetitionSignature.objects.create(petition=self.petition,name='Removed',email='removed@example.com',supporter_type='parent',consent=True,is_verified=True,moderation_status='removed',removed_at='2026-01-01T00:00:00Z')
        self.assertEqual(self.petition.verified_count,1)

    def test_compact_count(self):
        expected={999:'999',1000:'1K',1250:'1.2K',10000:'10K',100000:'100K',1000000:'1M',10000000:'10M',1000000000:'1B'}
        for value,label in expected.items(): self.assertEqual(compact_count(value),label)

    def test_draft_not_public_and_closed_rejects(self):
        draft=Petition.objects.create(title='Draft',slug='draft',short_heading='Draft',summary='Draft',primary_demand='Draft',petition_status='draft')
        self.assertEqual(self.client.get(reverse('petition_detail',args=[draft.slug])).status_code,404)
        self.petition.petition_status='closed'; self.petition.save()
        response=self.client.post(self.support_url,self.support_data())
        self.assertEqual(response.status_code,400)

class DedicatedStoryPageTests(TestCase):
    def public_story(self,slug,format_='text',topic='hope',body='Approved showcase story'):
        return Story.objects.create(slug=slug,title=slug.replace('-',' ').title(),body=body,story_format=format_,topic=topic,approved=True,moderation_status='published',public_consent=True,privacy_review_complete=True)

    def test_all_dedicated_story_routes_load(self):
        names=['stories','text_stories','voice_stories','video_stories','hope_stories','exam_pressure_stories','family_pressure_stories','college_life_stories','coaching_pressure_stories','protest_experience_stories']
        for name in names: self.assertEqual(self.client.get(reverse(name)).status_code,200,name)

    def test_formats_and_topics_are_scoped(self):
        text=self.public_story('public-text','text','exam','Visible text exam story')
        voice=self.public_story('public-voice','voice','hope','Visible voice hope story')
        video=self.public_story('public-video','video','protest','Visible protest video')
        self.assertContains(self.client.get(reverse('text_stories')),'Visible text exam story')
        self.assertNotContains(self.client.get(reverse('text_stories')),'Visible voice hope story')
        self.assertContains(self.client.get(reverse('voice_stories')),'Public Voice')
        self.assertContains(self.client.get(reverse('video_stories')),'Visible protest video')
        self.assertContains(self.client.get(reverse('exam_pressure_stories')),'Visible text exam story')
        self.assertNotContains(self.client.get(reverse('exam_pressure_stories')),'Visible voice hope story')

    def test_unapproved_or_unconsented_story_never_appears(self):
        Story.objects.create(slug='private-story',title='Never Public',body='Sensitive private content',approved=False,moderation_status='draft')
        Story.objects.create(slug='no-consent',title='No Consent',body='No consent content',approved=True,moderation_status='published',public_consent=False,privacy_review_complete=True)
        for name in ('stories','text_stories','hope_stories'):
            response=self.client.get(reverse(name)); self.assertNotContains(response,'Sensitive private content'); self.assertNotContains(response,'No consent content')

    def test_duplicate_reaction_is_prevented(self):
        story=self.public_story('reaction-story')
        url=reverse('react',args=[story.pk])
        self.client.post(url,{'reaction':'with_you','next':reverse('stories')})
        self.client.post(url,{'reaction':'with_you','next':reverse('stories')})
        self.assertEqual(story.reactions.count(),1)

    def test_comments_follow_owner_preference(self):
        story=self.public_story('comments-closed'); story.comment_mode='none'; story.save()
        response=self.client.post(reverse('story_comment',args=[story.pk]),{'body':'I am listening.'})
        self.assertEqual(response.status_code,403)

class UnmutedVoicesUpgradeTests(TestCase):
    def setUp(self):
        self.story=Story.objects.create(slug='public-voice',title='A public voice',body='What someone needed to say.',approved=True,moderation_status='published',public_consent=True,privacy_review_complete=True,published_at=timezone.now())

    def test_public_name_and_format_only_navigation(self):
        response=self.client.get(reverse('stories'))
        self.assertContains(response,'Unmuted Voices')
        self.assertContains(response,reverse('voices_text'))
        self.assertNotContains(response,'Hope Stories')

    def test_tracking_code_is_private_and_unpredictable(self):
        item=ListeningRequest.objects.create(message='Private by default.')
        self.assertRegex(item.tracking_code,r'^UNM-[A-HJ-NP-Z2-9]{6}$')
        self.assertNotIn(str(item.pk),item.tracking_code)

    def test_pending_reply_is_not_public_and_depth_is_limited(self):
        parent=StoryComment.objects.create(story=self.story,body='I hear you.',approved=True,status='approved')
        response=self.client.post(reverse('story_comment',args=[self.story.pk]),{'body':'You are not alone.','parent':parent.pk})
        self.assertEqual(response.status_code,200)
        self.assertNotContains(self.client.get(reverse('story_comments',args=[self.story.pk])),'You are not alone.')
        reply=StoryComment.objects.get(parent=parent)
        response=self.client.post(reverse('story_comment',args=[self.story.pk]),{'body':'A nested reply.','parent':reply.pk})
        self.assertEqual(response.status_code,404)

    def test_comment_reaction_toggles_and_report_enters_review(self):
        comment=StoryComment.objects.create(story=self.story,body='Support.',approved=True,status='approved')
        url=reverse('comment_react',args=[comment.pk])
        self.assertTrue(self.client.post(url).json()['active'])
        self.assertFalse(self.client.post(url).json()['active'])
        self.assertEqual(CommentReaction.objects.count(),0)
        response=self.client.post(reverse('comment_report',args=[comment.pk]),{'reason':'privacy'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(CommentReport.objects.get().status,'pending')

    def test_consent_withdrawal_unpublishes_without_deleting(self):
        item=ListeningRequest.objects.create(message='Private source',public_sharing_consent=True,publication_status='published',published_story=self.story)
        response=self.client.post(reverse('withdraw_consent'),{'tracking_code':item.tracking_code})
        self.assertEqual(response.status_code,200)
        self.story.refresh_from_db(); item.refresh_from_db()
        self.assertIsNotNone(self.story.removed_at)
        self.assertFalse(item.public_sharing_consent)
        self.assertTrue(ListeningRequest.objects.filter(pk=item.pk).exists())

# Create your tests here.
