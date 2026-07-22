from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch
from .forms import PetitionSignatureForm
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

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', SITE_URL='https://unmute.example')
    def test_petition_signature_requires_email_verification(self):
        petition=Petition.objects.filter(petition_status='published').first()
        response=self.client.post(reverse('petition_detail',args=[petition.slug]),{'name':'A Student','email':'student@example.com','supporter_type':'student','consent':'on'})
        self.assertEqual(response.status_code,200)
        signature=PetitionSignature.objects.get(email='student@example.com')
        self.assertFalse(signature.is_verified)
        self.assertEqual(petition.verified_count,0)
        self.assertEqual(len(mail.outbox),1)
        self.assertEqual(mail.outbox[0].to, ['student@example.com'])
        self.assertEqual(mail.outbox[0].subject, f'Verify your support for {petition.title} | Unmute India')
        self.assertIn('https://unmute.example/petitions/verify/', mail.outbox[0].body)
        self.assertNotIn('localhost', mail.outbox[0].body)
        self.assertNotContains(response, 'Please wait five minutes')

class PetitionSystemTests(TestCase):
    def setUp(self):
        self.petition=Petition.objects.create(title='Test petition',slug='test-petition',short_heading='Test',summary='Summary',primary_demand='Action',petition_status='published',allow_signatures=True)

    def signature_data(self, email='Student@Example.com '):
        return {'name':'Student','email':email,'supporter_type':'student','consent':'on'}

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', SITE_URL='https://unmute-india.onrender.com')
    def test_new_submission_sends_once_without_cooldown_or_resend_message(self):
        response = self.client.post(reverse('petition_detail', args=[self.petition.slug]), self.signature_data())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertIn('Verification email sent', response.json()['message'])
        self.assertNotIn('wait five minutes', response.json()['message'].lower())
        self.assertNotIn('new verification email', response.json()['message'].lower())
        self.assertEqual(PetitionSignature.objects.filter(petition=self.petition).count(), 1)
        signature = PetitionSignature.objects.get(petition=self.petition)
        self.assertEqual(signature.normalized_email, 'student@example.com')
        self.assertFalse(signature.is_verified)
        self.assertIsNotNone(signature.verification_email_sent_at)
        self.assertIsNotNone(signature.resend_available_at)
        self.assertEqual(self.petition.verified_count, 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['student@example.com'])
        self.assertIn('https://unmute-india.onrender.com/petitions/verify/', mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_pending_duplicate_obeys_cooldown_then_sends_one_new_email(self):
        url = reverse('petition_detail', args=[self.petition.slug])
        self.client.post(url, self.signature_data())
        signature = PetitionSignature.objects.get(petition=self.petition)
        first_token = signature.verification_token

        cooldown = self.client.post(url, self.signature_data())
        self.assertEqual(cooldown.status_code, 429)
        self.assertEqual(cooldown.json()['message'], 'Please wait five minutes before requesting another email.')
        self.assertEqual(PetitionSignature.objects.filter(petition=self.petition).count(), 1)
        self.assertEqual(len(mail.outbox), 1)

        signature.resend_available_at = timezone.now() - timezone.timedelta(seconds=1)
        signature.save(update_fields=['resend_available_at'])
        resent = self.client.post(url, self.signature_data())
        self.assertEqual(resent.status_code, 200)
        self.assertTrue(resent.json()['ok'])
        signature.refresh_from_db()
        self.assertNotEqual(signature.verification_token, first_token)
        self.assertEqual(PetitionSignature.objects.filter(petition=self.petition).count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_verified_duplicate_sends_nothing(self):
        url = reverse('petition_detail', args=[self.petition.slug])
        self.client.post(url, self.signature_data())
        signature = PetitionSignature.objects.get(petition=self.petition)
        signature.is_verified = True
        signature.verified = True
        signature.verified_at = timezone.now()
        signature.moderation_status = 'valid'
        signature.save()
        mail.outbox.clear()

        response = self.client.post(url, self.signature_data())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['message'], 'This email has already verified support for this petition.')
        self.assertEqual(PetitionSignature.objects.filter(petition=self.petition).count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_form_has_only_required_public_fields(self):
        form=PetitionSignatureForm()
        self.assertNotIn('state',form.fields)
        for field in ('name','email','supporter_type','consent'): self.assertTrue(form.fields[field].required)

    def test_invalid_name_email_role_and_consent(self):
        form=PetitionSignatureForm({'name':'  ','email':'bad','supporter_type':'','consent':''})
        self.assertFalse(form.is_valid())
        self.assertTrue({'name','email','supporter_type','consent'}.issubset(form.errors))

    @patch('indiaApp.views._petition_email', side_effect=ConnectionError('SMTP unavailable'))
    def test_email_failure_is_not_reported_as_success(self, mocked_email):
        response = self.client.post(reverse('petition_detail', args=[self.petition.slug]), {
            'name': 'Student', 'email': 'pending@example.com',
            'supporter_type': 'student', 'consent': 'on',
        })
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertFalse(payload['ok'])
        self.assertTrue(payload['pending'])
        signature = PetitionSignature.objects.get()
        self.assertFalse(signature.is_verified)
        self.assertIsNone(signature.verification_email_sent_at)
        self.assertIsNone(signature.resend_available_at)
        self.assertNotIn('Verification email sent', payload['message'])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_token_counts_once_and_duplicate_is_blocked(self):
        url=reverse('petition_detail',args=[self.petition.slug])
        data={'name':'Student','email':'STUDENT@example.com ','supporter_type':'student','consent':'on'}
        self.assertTrue(self.client.post(url,data).json()['ok'])
        signature=PetitionSignature.objects.get(petition=self.petition)
        self.assertEqual(signature.normalized_email,'student@example.com')
        token=mail.outbox[0].body.split('/petitions/verify/')[1].split('/')[0]
        self.assertEqual(self.client.get(reverse('petition_verify',args=[token])).status_code,200)
        signature.refresh_from_db(); self.assertTrue(signature.is_verified); self.assertEqual(self.petition.verified_count,1)
        self.client.get(reverse('petition_verify',args=[token]))
        self.assertEqual(self.petition.verified_count,1)
        self.client.session.flush()
        duplicate=self.client.post(url,data).json()
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(PetitionSignature.objects.filter(petition=self.petition).count(), 1)

    def test_expired_token_fails_safely(self):
        import hashlib
        raw = 'expired-secure-token'
        signature = PetitionSignature.objects.create(petition=self.petition,name='Student',email='expired@example.com',supporter_type='student',consent=True,verification_token=hashlib.sha256(raw.encode()).hexdigest(),token_created_at=timezone.now()-timezone.timedelta(hours=25))
        response = self.client.get(reverse('petition_verify', args=[raw]))
        self.assertContains(response, 'expired')
        signature.refresh_from_db(); self.assertFalse(signature.is_verified)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_resend_rotates_token_and_obscures_unknown_email(self):
        url = reverse('petition_detail', args=[self.petition.slug])
        self.client.post(url, {'name':'Student','email':'rotate@example.com','supporter_type':'student','consent':'on'})
        signature = PetitionSignature.objects.get(email='rotate@example.com')
        old = mail.outbox[-1].body.split('/petitions/verify/')[1].split('/')[0]
        signature.resend_available_at = timezone.now()-timezone.timedelta(seconds=1); signature.save(update_fields=['resend_available_at'])
        response = self.client.post(reverse('petition_resend', args=[self.petition.slug]), {'email':'rotate@example.com'})
        self.assertTrue(response.json()['ok'])
        new = mail.outbox[-1].body.split('/petitions/verify/')[1].split('/')[0]
        self.assertNotEqual(old, new)
        self.assertContains(self.client.get(reverse('petition_verify', args=[old])), 'invalid')
        self.assertContains(self.client.get(reverse('petition_verify', args=[new])), 'now verified')
        unknown = self.client.post(reverse('petition_resend', args=[self.petition.slug]), {'email':'unknown@example.com'})
        self.assertEqual(unknown.status_code, 200)
        self.assertNotContains(unknown, 'not found')

    def test_spam_and_removed_signatures_do_not_count(self):
        PetitionSignature.objects.create(petition=self.petition,name='Spam',email='spam@example.com',supporter_type='citizen',consent=True,is_verified=True,moderation_status='spam')
        PetitionSignature.objects.create(petition=self.petition,name='Removed',email='removed@example.com',supporter_type='parent',consent=True,is_verified=True,moderation_status='removed',removed_at='2026-01-01T00:00:00Z')
        self.assertEqual(self.petition.verified_count,0)

    def test_compact_count(self):
        expected={999:'999',1000:'1K',1250:'1.2K',10000:'10K',100000:'100K',1000000:'1M',10000000:'10M',1000000000:'1B'}
        for value,label in expected.items(): self.assertEqual(compact_count(value),label)

    def test_draft_not_public_and_closed_rejects(self):
        draft=Petition.objects.create(title='Draft',slug='draft',short_heading='Draft',summary='Draft',primary_demand='Draft',petition_status='draft')
        self.assertEqual(self.client.get(reverse('petition_detail',args=[draft.slug])).status_code,404)
        self.petition.petition_status='closed'; self.petition.save()
        response=self.client.post(reverse('petition_detail',args=[self.petition.slug]),{'name':'A','email':'a@example.com','supporter_type':'other','consent':'on'})
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
