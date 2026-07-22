from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch
from .forms import GooglePetitionSupportForm
from .models import ListeningRequest, Petition, PetitionSignature, PublicQuestion, Story
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

# Create your tests here.
