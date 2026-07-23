from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch
from pathlib import Path
from io import StringIO
import tempfile
from django.core.management import call_command
from .forms import GooglePetitionSupportForm
from .models import AuditLog, CommentReaction, CommentReport, ListeningRequest, Petition, PetitionSignature, PrivateIdentity, PublicQuestion, Story, StoryComment, StoryReaction
from .private_identity import google_subject_hash, merge_guest_activity, provision_signature_identity, resolve_google_identity
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

    def test_media_validation_is_shown_locally_without_generic_top_banner(self):
        response=self.client.post(reverse('share',args=['audio']),{'consent':'on','anonymous':'on'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Please record or choose an audio file before submitting.')
        self.assertNotContains(response,'Your message could not be sent yet')

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
        media='' if format_ == 'text' else f'stories/{slug}.webm'
        return Story.objects.create(slug=slug,title=slug.replace('-',' ').title(),body=body,story_format=format_,topic=topic,public_media=media,approved=True,moderation_status='published',public_consent=True,privacy_review_complete=True)

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

    def test_format_pages_use_compact_cards_and_filter_by_publication_date(self):
        first=self.public_story('first-day-story',body='Visible on first day')
        second=self.public_story('second-day-story',body='Visible on second day')
        first.published_at=timezone.datetime(2026,7,22,10,tzinfo=timezone.utc)
        second.published_at=timezone.datetime(2026,7,23,10,tzinfo=timezone.utc)
        first.save(update_fields=('published_at','updated_at'))
        second.save(update_fields=('published_at','updated_at'))
        response=self.client.get(reverse('voices_text'),{'date':'2026-07-22'})
        self.assertContains(response,'Visible on first day')
        self.assertNotContains(response,'Visible on second day')
        self.assertContains(response,'story-grid--shelf')
        self.assertContains(response,'story-date-filter')

    def test_unapproved_or_unconsented_story_never_appears(self):
        Story.objects.create(slug='private-story',title='Never Public',body='Sensitive private content',approved=False,moderation_status='draft')
        Story.objects.create(slug='no-consent',title='No Consent',body='No consent content',approved=True,moderation_status='published',public_consent=False,privacy_review_complete=True)
        for name in ('stories','text_stories','hope_stories'):
            response=self.client.get(reverse(name)); self.assertNotContains(response,'Sensitive private content'); self.assertNotContains(response,'No consent content')

    def test_story_reaction_toggles_for_same_anonymous_browser(self):
        story=self.public_story('reaction-story')
        url=reverse('react',args=[story.pk])
        added=self.client.post(url,{'reaction':'with_you','json':'1'},HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()
        self.assertTrue(added['active']); self.assertEqual(added['count'],1)
        removed=self.client.post(url,{'reaction':'with_you','json':'1'},HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()
        self.assertFalse(removed['active']); self.assertEqual(removed['count'],0)
        self.assertEqual(story.reactions.count(),0)

    def test_different_anonymous_browsers_can_react_and_state_renders(self):
        story=self.public_story('two-browser-reaction')
        url=reverse('react',args=[story.pk])
        first=self.client
        second=self.client_class()
        first.post(url,{'json':'1'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        second.post(url,{'json':'1'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(StoryReaction.objects.filter(story=story).count(),2)
        response=first.get(reverse('voices_text'))
        self.assertContains(response,'aria-pressed="true"')
        self.assertContains(response,'data-reaction-count aria-live="polite">2')

    def test_unpublished_story_reaction_rejected_and_get_does_not_mutate(self):
        story=self.public_story('not-reactable')
        url=reverse('react',args=[story.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertFalse(StoryReaction.objects.exists())
        story.moderation_status='archived'; story.approved=False; story.removed_at=timezone.now(); story.save()
        self.assertEqual(self.client.post(url,{'json':'1'}).status_code,404)
        self.assertFalse(StoryReaction.objects.exists())

    def test_anonymous_cookie_is_private_and_database_stores_only_its_hmac(self):
        story=self.public_story('private-cookie-reaction')
        response=self.client.post(reverse('react',args=[story.pk]),{'json':'1'})
        cookie=response.cookies['unmute_anonymous_id']
        raw_identifier=cookie.value
        reaction=StoryReaction.objects.get(story=story)
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'],'Lax')
        self.assertEqual(int(cookie['max-age']),365 * 24 * 60 * 60)
        self.assertNotEqual(reaction.anonymous_key,raw_identifier)
        self.assertNotIn(raw_identifier,reaction.anonymous_key)
        self.assertEqual(len(reaction.anonymous_key),64)

    def test_story_reaction_requires_csrf_token(self):
        story=self.public_story('csrf-reaction')
        csrf_client=Client(enforce_csrf_checks=True)
        response=csrf_client.post(reverse('react',args=[story.pk]),{'json':'1'})
        self.assertEqual(response.status_code,403)
        self.assertFalse(StoryReaction.objects.exists())

    def test_comments_follow_owner_preference(self):
        story=self.public_story('comments-closed'); story.comment_mode='none'; story.save()
        response=self.client.post(reverse('story_comment',args=[story.pk]),{'body':'I am listening.'})
        self.assertEqual(response.status_code,403)

@override_settings(PRIVATE_IDENTITY_HMAC_KEY='identity-test-secret',GOOGLE_CLIENT_ID='client')
class PrivateIdentitySystemTests(TestCase):
    def setUp(self):
        self.petition=Petition.objects.create(
            title='Private identity petition',slug='private-identity-petition',
            short_heading='Support safely',summary='Summary',primary_demand='Demand',
            petition_status='published',
        )

    def signature(self, **overrides):
        values={
            'petition':self.petition,'name':'Existing supporter',
            'email':'existing@example.com','verified_email':'existing@example.com',
            'supporter_type':'student','consent':True,'is_verified':True,
            'verified':True,'verified_at':timezone.now(),'moderation_status':'valid',
            'verification_method':'google','google_subject':'stable-google-sub',
            'google_verified_at':timezone.now(),
        }
        values.update(overrides)
        return PetitionSignature.objects.create(**values)

    def public_story(self, slug='identity-story'):
        return Story.objects.create(
            slug=slug,title='Private sync story',body='Public body',
            approved=True,moderation_status='published',public_consent=True,
            privacy_review_complete=True,published_at=timezone.now(),
        )

    def attach(self, client, identity):
        session=client.session
        session['private_identity_id']=identity.pk
        session.save()

    def test_existing_signature_migration_preserves_record_and_count(self):
        signature=self.signature()
        before={field:getattr(signature,field) for field in (
            'name','email','verified_email','supporter_type','consent','verified_at',
            'petition_id','moderation_status','verification_method','google_verified_at',
        )}
        count_before=self.petition.verified_count
        identity,created=provision_signature_identity(signature)
        signature.refresh_from_db()
        self.assertTrue(created)
        self.assertEqual(identity.identity_status,'confirmed_google')
        self.assertEqual(before,{field:getattr(signature,field) for field in before})
        self.assertEqual(self.petition.verified_count,count_before)

    def test_email_only_legacy_signature_is_provisional_and_idempotent(self):
        signature=self.signature(
            google_subject='',verification_method='email_legacy',
            google_verified_at=None,
        )
        first,_=provision_signature_identity(signature)
        signature.refresh_from_db()
        second,created=provision_signature_identity(signature)
        self.assertEqual(first.pk,second.pk)
        self.assertFalse(created)
        self.assertEqual(first.identity_status,'provisional_legacy')
        self.assertEqual(PetitionSignature.objects.count(),1)

    def test_migration_command_twice_does_not_duplicate_or_leak_email(self):
        self.signature()
        output=StringIO()
        call_command('migrate_existing_petition_identities',stdout=output)
        call_command('migrate_existing_petition_identities',stdout=output)
        self.assertEqual(PrivateIdentity.objects.count(),1)
        self.assertEqual(PetitionSignature.objects.count(),1)
        self.assertNotIn('existing@example.com',output.getvalue())
        self.assertIn('Duplicate signatures created: 0',output.getvalue())

    def test_same_google_subject_resolves_same_identity_without_signature(self):
        first=resolve_google_identity('same-sub','person@example.com',consent=True)
        second=resolve_google_identity('same-sub','person@example.com',consent=True)
        other=resolve_google_identity('other-sub','other@example.com',consent=True)
        self.assertEqual(first.pk,second.pk)
        self.assertNotEqual(first.pk,other.pk)
        self.assertFalse(PetitionSignature.objects.exists())

    @patch('indiaApp.views._verify_google_credential')
    def test_my_space_verification_rotates_session_and_never_signs_petition(self, verify):
        verify.return_value={'sub':'restore-sub','email':'restore@example.com','issuer':'accounts.google.com'}
        legacy_submission=ListeningRequest.objects.create(
            kind='text',
            message='Created before private identity support',
        )
        session=self.client.session
        session['last_submission']=str(legacy_submission.public_id)
        session.save()
        old_key=self.client.session.session_key
        response=self.client.post(reverse('my_space_google_sync'),{'credential':'raw-token','sync_consent':'1'})
        self.assertEqual(response.status_code,200)
        self.assertFalse(PetitionSignature.objects.exists())
        self.assertNotEqual(self.client.session.session_key,old_key)
        self.assertNotIn('raw-token',str(PrivateIdentity.objects.values().first()))
        legacy_submission.refresh_from_db()
        self.assertIsNotNone(legacy_submission.private_identity_id)

    @patch('indiaApp.views._verify_google_credential')
    def test_my_space_page_issues_csrf_cookie_for_google_callback(self, verify):
        verify.return_value={'sub':'csrf-restore','email':'csrf@example.com','issuer':'accounts.google.com'}
        browser=Client(enforce_csrf_checks=True)
        page=browser.get(reverse('my_space'))
        self.assertEqual(page.status_code,200)
        self.assertIn('csrftoken',page.cookies)
        self.assertContains(page,'name="csrfmiddlewaretoken"')
        token=str(page.context['csrf_token'])
        response=browser.post(
            reverse('my_space_google_sync'),
            {'credential':'credential','sync_consent':'1'},
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['ok'])

    def test_cross_device_reaction_state_and_toggle(self):
        identity=resolve_google_identity('cross-device','cross@example.com',consent=True)
        story=self.public_story()
        laptop=Client(); mobile=Client()
        self.attach(laptop,identity); self.attach(mobile,identity)
        url=reverse('react',args=[story.pk])
        self.assertTrue(laptop.post(url,{'json':'1'}).json()['active'])
        page=mobile.get(reverse('voices_text'))
        self.assertContains(page,'aria-pressed="true"')
        result=mobile.post(url,{'json':'1'}).json()
        self.assertFalse(result['active'])
        self.assertEqual(result['count'],0)

    def test_cross_device_response_support_state_and_toggle(self):
        identity=resolve_google_identity('response-device','response@example.com',consent=True)
        story=self.public_story('response-sync-story')
        comment=StoryComment.objects.create(story=story,body='Supportive response',approved=True,status='approved')
        laptop=Client(); mobile=Client()
        self.attach(laptop,identity); self.attach(mobile,identity)
        url=reverse('comment_react',args=[comment.pk])
        self.assertTrue(laptop.post(url).json()['active'])
        payload=mobile.get(reverse('story_comments',args=[story.pk])).json()
        self.assertTrue(payload['comments'][0]['active'])
        result=mobile.post(url).json()
        self.assertFalse(result['active'])
        self.assertEqual(result['count'],0)

    def test_guest_activity_merge_is_idempotent_and_avoids_duplicate(self):
        identity=resolve_google_identity('merge-sub','merge@example.com',consent=True)
        story=self.public_story('merge-story')
        StoryReaction.objects.create(story=story,session_key='guest'[:40],anonymous_key='guest',reaction='with_you')
        StoryReaction.objects.create(story=story,session_key='confirmed'[:40],private_identity=identity,reaction='with_you')
        submission=ListeningRequest.objects.create(kind='text',message='Private guest text',guest_key='guest')
        merge_guest_activity(identity,'guest')
        merge_guest_activity(identity,'guest')
        self.assertEqual(StoryReaction.objects.filter(story=story).count(),1)
        submission.refresh_from_db()
        self.assertEqual(submission.private_identity,identity)
        self.assertEqual(submission.guest_key,'')

    def test_my_space_isolated_between_identities(self):
        first=resolve_google_identity('owner-one','one@example.com',consent=True)
        second=resolve_google_identity('owner-two','two@example.com',consent=True)
        ListeningRequest.objects.create(kind='text',message='Only owner one can see this phrase',private_identity=first)
        owner=Client(); stranger=Client()
        self.attach(owner,first); self.attach(stranger,second)
        self.assertContains(owner.get(reverse('my_space')),'Only owner one')
        self.assertNotContains(stranger.get(reverse('my_space')),'Only owner one')

    def test_existing_verified_session_claims_its_last_legacy_submission(self):
        identity=resolve_google_identity('legacy-owner','legacy-owner@example.com',consent=True)
        submission=ListeningRequest.objects.create(kind='text',message='Legacy browser submission')
        self.attach(self.client,identity)
        session=self.client.session
        session['last_submission']=str(submission.public_id)
        session.save()
        response=self.client.get(reverse('my_space'))
        self.assertContains(response,'Legacy browser submission')
        submission.refresh_from_db()
        self.assertEqual(submission.private_identity,identity)

    def test_my_space_filters_submission_types_and_invalid_type_is_safe(self):
        identity=resolve_google_identity('filter-owner','filter@example.com',consent=True)
        ListeningRequest.objects.create(kind='text',title='Written title',message='Written body',private_identity=identity)
        ListeningRequest.objects.create(kind='audio',title='Audio title',message='Audio description',private_identity=identity)
        ListeningRequest.objects.create(kind='video',title='Video title',message='Video description',private_identity=identity)
        self.attach(self.client,identity)
        written=self.client.get(reverse('my_space'),{'type':'text'})
        self.assertContains(written,'Written title')
        self.assertContains(written,'Written body')
        self.assertNotContains(written,'Audio title')
        audio=self.client.get(reverse('my_space'),{'type':'audio'})
        self.assertContains(audio,'Audio title')
        self.assertNotContains(audio,'Video title')
        video=self.client.get(reverse('my_space'),{'type':'video'})
        self.assertContains(video,'Video title')
        invalid=self.client.get(reverse('my_space'),{'type':'not-real'})
        self.assertEqual(invalid.context['active_type'],'text')
        self.assertContains(invalid,'Written title')

    def test_my_space_card_escapes_html_renders_emoji_and_safe_title_fallback(self):
        identity=resolve_google_identity('render-owner','render@example.com',consent=True)
        ListeningRequest.objects.create(
            kind='text',
            title='<script>alert(1)</script>',
            message='Actual message 😡 <img src=x onerror=alert(2)>',
            private_identity=identity,
        )
        ListeningRequest.objects.create(kind='text',title='',message='',private_identity=identity)
        self.attach(self.client,identity)
        response=self.client.get(reverse('my_space'),{'type':'text'})
        self.assertContains(response,'&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response,'<script>alert(1)</script>')
        self.assertContains(response,'Actual message 😡')
        self.assertContains(response,'Untitled written voice')

    def test_my_space_status_and_published_date_are_consistent(self):
        identity=resolve_google_identity('status-owner','status@example.com',consent=True)
        story=self.public_story('published-source')
        item=ListeningRequest.objects.create(
            kind='text',title='Published item',message='Body',
            private_identity=identity,publication_status='published',
            published_story=story,
        )
        self.attach(self.client,identity)
        response=self.client.get(reverse('my_space'),{'type':'text'})
        self.assertContains(response,'Published')
        self.assertContains(response,'Public')
        self.assertContains(response,timezone.localdate(story.published_at).strftime('%d %b %Y'))
        self.assertNotContains(response,'>New<')

    def test_my_space_paginates_twelve_per_category(self):
        identity=resolve_google_identity('page-owner','page@example.com',consent=True)
        for index in range(13):
            ListeningRequest.objects.create(kind='text',title=f'Entry {index:02d}',message='Body',private_identity=identity)
        self.attach(self.client,identity)
        first=self.client.get(reverse('my_space'),{'type':'text'})
        self.assertEqual(len(first.context['submissions']),12)
        self.assertContains(first,'Load more')
        second=self.client.get(reverse('my_space'),{'type':'text','page':2})
        self.assertEqual(len(second.context['submissions']),1)

    def test_sign_out_removes_private_submission_access(self):
        identity=resolve_google_identity('signout-owner','signout@example.com',consent=True)
        ListeningRequest.objects.create(kind='text',title='Private after signout',message='Body',private_identity=identity)
        self.attach(self.client,identity)
        response=self.client.post(reverse('my_space_sign_out'))
        self.assertRedirects(response,reverse('my_space'))
        self.assertNotContains(self.client.get(reverse('my_space')),'Private after signout')

    def test_private_media_route_rejects_another_identity(self):
        owner=resolve_google_identity('media-owner','media-owner@example.com',consent=True)
        stranger=resolve_google_identity('media-stranger','media-stranger@example.com',consent=True)
        item=ListeningRequest.objects.create(
            kind='audio',title='Private audio',media='private/protected.mp3',
            private_identity=owner,
        )
        self.attach(self.client,stranger)
        self.assertEqual(self.client.get(reverse('my_space_media',args=[item.public_id])).status_code,404)

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

    def test_reply_is_immediately_public_and_depth_is_limited(self):
        parent=StoryComment.objects.create(story=self.story,body='I hear you.',approved=True,status='approved')
        response=self.client.post(reverse('story_comment',args=[self.story.pk]),{'body':'You are not alone.','parent':parent.pk})
        self.assertEqual(response.status_code,200)
        self.assertContains(self.client.get(reverse('story_comments',args=[self.story.pk])),'You are not alone.')
        reply=StoryComment.objects.get(parent=parent)
        self.assertTrue(reply.approved)
        self.assertEqual(reply.status,'approved')
        response=self.client.post(reverse('story_comment',args=[self.story.pk]),{'body':'A nested reply.','parent':reply.pk})
        self.assertEqual(response.status_code,404)

    def test_comment_is_immediately_visible_without_staff_approval(self):
        response=self.client.post(reverse('story_comment',args=[self.story.pk]),{'body':'Thank you for sharing this.'})
        self.assertTrue(response.json()['approved'])
        comment=StoryComment.objects.get(body='Thank you for sharing this.')
        self.assertTrue(comment.approved)
        self.assertEqual(comment.status,'approved')
        self.assertContains(self.client.get(reverse('story_comments',args=[self.story.pk])),'Thank you for sharing this.')

    def test_comment_pagination_never_repeats_last_page(self):
        StoryComment.objects.create(story=self.story,body='Only response',approved=True,status='approved')
        first=self.client.get(reverse('story_comments',args=[self.story.pk]),{'page':1}).json()
        beyond=self.client.get(reverse('story_comments',args=[self.story.pk]),{'page':2}).json()
        self.assertEqual(len(first['comments']),1)
        self.assertFalse(first['has_next'])
        self.assertEqual(beyond['comments'],[])
        self.assertFalse(beyond['has_next'])
        css=Path('static/css/stories/comments.css').read_text()
        self.assertIn('.comments-more[hidden]{display:none!important}',css)

    def test_response_support_toggles_and_persists_per_browser(self):
        comment=StoryComment.objects.create(story=self.story,body='Support me',approved=True,status='approved')
        url=reverse('comment_react',args=[comment.pk])
        added=self.client.post(url).json()
        self.assertTrue(added['active']); self.assertEqual(added['count'],1)
        payload=self.client.get(reverse('story_comments',args=[self.story.pk])).json()
        self.assertTrue(payload['comments'][0]['active'])
        removed=self.client.post(url).json()
        self.assertFalse(removed['active']); self.assertEqual(removed['count'],0)
        self.assertEqual(CommentReaction.objects.filter(comment=comment).count(),0)

    def test_different_browsers_support_response_independently(self):
        comment=StoryComment.objects.create(story=self.story,body='Two supporters',approved=True,status='approved')
        url=reverse('comment_react',args=[comment.pk])
        self.client.post(url)
        self.client_class().post(url)
        self.assertEqual(CommentReaction.objects.filter(comment=comment).count(),2)

    def test_removed_response_cannot_receive_support(self):
        comment=StoryComment.objects.create(story=self.story,body='Removed',approved=False,status='removed',removed_at=timezone.now())
        self.assertEqual(self.client.post(reverse('comment_react',args=[comment.pk])).status_code,404)
        self.assertFalse(CommentReaction.objects.exists())

    def test_video_card_uses_custom_controls_and_links_to_detail(self):
        self.story.story_format='video'
        self.story.public_media.name='stories/public-video.webm'
        self.story.save(update_fields=('story_format','public_media','updated_at'))
        response=self.client.get(reverse('voices_video'))
        self.assertContains(response,'data-video-player')
        self.assertContains(response,'video-mute')
        self.assertContains(response,reverse('story_detail',args=[self.story.slug]))
        self.assertNotContains(response,'<video controls',html=False)

    def test_reusable_comments_modal_is_present_for_every_format(self):
        for name in ('voices_text','voices_voice','voices_video'):
            response=self.client.get(reverse(name))
            self.assertContains(response,'data-comments-overlay',count=1)
            self.assertContains(response,'comments-scroll')
            self.assertContains(response,'comments-composer')
            self.assertContains(response,'data-reply-context')
            self.assertContains(response,'data-report-sheet')
            self.assertContains(response,'data-name-sheet')
            self.assertContains(response,'Choose display name')
            self.assertContains(response,'Stay anonymous')

    def test_comment_openers_carry_compact_post_context(self):
        response=self.client.get(reverse('voices_text'))
        self.assertContains(response,'data-format="Text"')
        self.assertContains(response,'data-author=')
        self.assertContains(response,'data-excerpt=')

    def test_feed_uses_equal_height_aligned_shelves(self):
        response=self.client.get(reverse('stories'))
        self.assertContains(response,'Written Voices')
        self.assertContains(response,'Audio Stories')
        self.assertContains(response,'Video Stories')
        css=Path('static/css/stories/feed_shelves.css').read_text()
        self.assertIn('height: 100%',css)
        self.assertIn('align-items: stretch',css)
        self.assertIn('flex-direction: column',css)
        self.assertIn('margin-top: auto',css)
        self.assertIn('-webkit-line-clamp: 2',css)
        self.assertIn('-webkit-line-clamp: 4',css)
        self.assertNotIn('min-height: 100vh',css)
        self.assertNotIn(':has(',css)
        self.assertIn('grid-template-columns: minmax(0, 1fr) !important',css)
        responsive=Path('static/css/responsive.css').read_text()
        self.assertNotIn('.story-card form button:nth-child(n+2)',responsive)

    def test_missing_media_story_does_not_render(self):
        missing=Story.objects.create(slug='missing-audio',title='Broken audio card',body='No media',story_format='voice',approved=True,moderation_status='published',public_consent=True,privacy_review_complete=True)
        self.assertNotContains(self.client.get(reverse('stories')),missing.title)

    def test_comments_styles_define_desktop_and_mobile_panel_constraints(self):
        source=(Path(__file__).resolve().parent.parent/'static/css/stories/comments.css').read_text()
        self.assertIn('width:min(780px',source)
        self.assertIn('max-height:84vh',source)
        self.assertIn('.comments-scroll{min-height:0;overflow-y:auto',source)
        self.assertIn('.comments-composer',source)
        self.assertIn('max-height:88svh',source)

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

class AdminPublicationWorkspaceTests(TestCase):
    def setUp(self):
        self.media_dir=tempfile.TemporaryDirectory()
        self.media_override=override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.staff=get_user_model().objects.create_superuser('workspace-admin','workspace@example.com','safe-password')
        self.client.force_login(self.staff)
    def tearDown(self):
        self.media_override.disable()
        self.media_dir.cleanup()
        super().tearDown()

    def request(self,kind='text',consent=True,**kwargs):
        defaults={'kind':kind,'message':'A reviewed public message.','public_sharing_consent':consent,'privacy_review_complete':True,'publication_status':'review'}
        defaults.update(kwargs)
        return ListeningRequest.objects.create(**defaults)

    def test_changelist_search_filter_and_summary_load(self):
        self.request(title='Find this request')
        url=reverse('admin:indiaApp_listeningrequest_changelist')
        response=self.client.get(url,{'q':'Find this','kind':'text'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Listening Requests')
        self.assertContains(response,'Public review requested')

    def test_preview_is_public_safe(self):
        item=self.request()
        response=self.client.get(reverse('admin:indiaApp_listeningrequest_preview',args=[item.pk]))
        self.assertContains(response,'A reviewed public message.')
        self.assertNotContains(response,item.tracking_code)
        self.assertNotContains(response,'moderation_notes')

    def test_private_submission_cannot_publish_without_consent(self):
        item=self.request(consent=False,publication_status='private')
        response=self.client.post(reverse('admin:indiaApp_listeningrequest_publish',args=[item.pk]),follow=True)
        self.assertEqual(response.status_code,200)
        item.refresh_from_db()
        self.assertIsNone(item.published_story_id)

    def test_explicit_approval_completes_privacy_review_but_safety_flag_blocks(self):
        incomplete=self.request(privacy_review_complete=False)
        flagged=self.request(safety_flag=True)
        response=self.client.post(reverse('admin:indiaApp_listeningrequest_publish',args=[incomplete.pk]),follow=True)
        self.assertEqual(response.status_code,200)
        incomplete.refresh_from_db()
        self.assertTrue(incomplete.privacy_review_complete)
        self.assertIsNotNone(incomplete.published_story_id)
        response=self.client.post(reverse('admin:indiaApp_listeningrequest_publish',args=[flagged.pk]),follow=True)
        self.assertEqual(response.status_code,200)
        flagged.refresh_from_db()
        self.assertIsNone(flagged.published_story_id)
        detail=self.client.get(reverse('admin:indiaApp_listeningrequest_change',args=[flagged.pk]))
        self.assertContains(detail,'safety-flagged and cannot be published')
        self.assertContains(detail,'Approve &amp; Publish')

    def test_publish_button_is_active_before_privacy_checkbox_is_saved(self):
        item=self.request(privacy_review_complete=False)
        response=self.client.get(reverse('admin:indiaApp_listeningrequest_change',args=[item.pk]))
        self.assertContains(response,'publish-primary')
        self.assertContains(response,'Will complete on approval')

    def test_detail_page_has_all_public_sharing_actions_and_readable_state(self):
        item=self.request()
        response=self.client.get(reverse('admin:indiaApp_listeningrequest_change',args=[item.pk]))
        for label in ('Public Sharing Actions','Approve &amp; Publish','Keep Private','Reject Public Sharing','Unpublish','Preview Public Post','Not published'):
            self.assertContains(response,label)

    def test_text_audio_and_video_map_to_public_formats(self):
        items=[
            self.request(kind='text'),
            self.request(kind='audio',message='',media=SimpleUploadedFile('voice.webm',b'audio-bytes',content_type='audio/webm')),
            self.request(kind='video',message='',media=SimpleUploadedFile('video.webm',b'video-bytes',content_type='video/webm')),
        ]
        for item in items:
            self.client.post(reverse('admin:indiaApp_listeningrequest_publish',args=[item.pk]))
            item.refresh_from_db()
        self.assertEqual([item.published_story.story_format for item in items],['text','voice','video'])
        self.assertContains(self.client.get(reverse('voices_text')),'A reviewed public message.')
        self.assertEqual(Story.objects.count(),3)
        self.assertEqual(items[1].published_story.public_media.name,items[1].media.name)
        self.assertEqual(items[2].published_story.public_media.name,items[2].media.name)

    def test_audio_and_video_publish_without_reopening_or_copying_media(self):
        for kind in ('audio','video'):
            item=self.request(kind=kind,message='',media=SimpleUploadedFile(f'{kind}.webm',b'media-bytes',content_type=f'{kind}/webm'))
            with patch('django.db.models.fields.files.FieldFile.open',side_effect=OSError('storage does not allow reopening')):
                response=self.client.post(reverse('admin:indiaApp_listeningrequest_publish',args=[item.pk]))
            self.assertEqual(response.status_code,302)
            item.refresh_from_db()
            self.assertEqual(item.publication_status,'published')
            self.assertEqual(item.published_story.public_media.name,item.media.name)

    def test_repeated_publish_is_idempotent_and_audited(self):
        item=self.request()
        url=reverse('admin:indiaApp_listeningrequest_publish',args=[item.pk])
        self.client.post(url); self.client.post(url)
        item.refresh_from_db()
        self.assertEqual(Story.objects.count(),1)
        self.assertIsNotNone(item.published_story_id)
        self.assertTrue(AuditLog.objects.filter(actor=self.staff,object_reference__contains=f'ListeningRequest:{item.pk}').exists())

    def test_anonymous_and_comment_preferences_are_preserved(self):
        item=self.request(anonymous=True,comment_preference='none')
        self.client.post(reverse('admin:indiaApp_listeningrequest_publish',args=[item.pk]))
        item.refresh_from_db()
        self.assertEqual(item.published_story.display_name,'Anonymous Student')
        self.assertEqual(item.published_story.comment_mode,'none')

    def test_keep_private_and_reject_create_audit_entries(self):
        private=self.request(); rejected=self.request()
        self.client.post(reverse('admin:indiaApp_listeningrequest_keep_private',args=[private.pk]))
        self.client.post(reverse('admin:indiaApp_listeningrequest_reject_public',args=[rejected.pk]),{'reason':'Privacy concerns'})
        private.refresh_from_db(); rejected.refresh_from_db()
        self.assertEqual(private.publication_status,'private')
        self.assertEqual(rejected.publication_status,'rejected')
        self.assertTrue(AuditLog.objects.filter(action__startswith='Kept private').exists())
        self.assertTrue(AuditLog.objects.filter(action__startswith='Rejected public sharing').exists())

    def test_unpublish_hides_public_post_and_preserves_private_source(self):
        item=self.request()
        self.client.post(reverse('admin:indiaApp_listeningrequest_publish',args=[item.pk]))
        story=item.__class__.objects.get(pk=item.pk).published_story
        self.client.post(reverse('admin:indiaApp_listeningrequest_unpublish',args=[item.pk]),{'reason':'Privacy request'})
        item.refresh_from_db(); story.refresh_from_db()
        self.assertEqual(item.publication_status,'removed')
        self.assertIsNotNone(story.removed_at)
        self.assertTrue(ListeningRequest.objects.filter(pk=item.pk).exists())
        self.assertNotContains(self.client.get(reverse('voices_text')),'A reviewed public message.')

    def test_deleting_source_archives_public_story_and_writes_audit(self):
        item=self.request()
        self.client.post(reverse('admin:indiaApp_listeningrequest_publish',args=[item.pk]))
        item.refresh_from_db(); story_id=item.published_story_id
        item.delete()
        story=Story.objects.get(pk=story_id)
        self.assertEqual(story.moderation_status,'archived')
        self.assertFalse(story.approved)
        self.assertIsNotNone(story.removed_at)
        self.assertNotContains(self.client.get(reverse('stories')),story.title)
        self.assertTrue(AuditLog.objects.filter(object_reference__contains=f'Story:{story_id}',action__contains='source ListeningRequest was deleted').exists())

    def test_source_consent_safety_status_and_media_control_visibility(self):
        item=self.request(kind='audio',message='',media=SimpleUploadedFile('voice.webm',b'audio',content_type='audio/webm'))
        self.client.post(reverse('admin:indiaApp_listeningrequest_publish',args=[item.pk]))
        item.refresh_from_db(); story=item.published_story
        self.assertContains(self.client.get(reverse('voices_voice')),story.title)
        item.safety_flag=True
        item.save()
        story.refresh_from_db(); item.refresh_from_db()
        self.assertEqual(item.publication_status,'removed')
        self.assertEqual(story.moderation_status,'archived')
        self.assertNotContains(self.client.get(reverse('voices_voice')),story.title)

    def test_non_staff_cannot_use_publication_actions(self):
        self.client.logout()
        response=self.client.post(reverse('admin:indiaApp_listeningrequest_publish',args=[self.request().pk]))
        self.assertEqual(response.status_code,302)

# Create your tests here.
