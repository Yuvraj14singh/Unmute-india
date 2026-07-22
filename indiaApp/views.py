from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
import hashlib, json, logging, secrets
from urllib import parse, request as urllib_request
from .forms import GooglePetitionSupportForm, ListeningRequestForm, PetitionSignatureForm, PublicQuestionForm, VolunteerForm
from .models import AccountabilityEvent, AuthorityResponse, AuditLog, EvidenceDocument, ListeningRequest, Petition, PetitionSignature, PromiseTracker, PublicQuestion, Story, StoryReaction, StudentDemand, SupportResource
from .utils import mask_email, request_fingerprint

logger = logging.getLogger(__name__)

GOOGLE_SUPPORT_UNAVAILABLE = 'Verified support is temporarily unavailable.'


def _missing_google_support_settings():
    values = {
        'GOOGLE_CLIENT_ID': settings.GOOGLE_CLIENT_ID,
        'TURNSTILE_SITE_KEY': settings.TURNSTILE_SITE_KEY,
        'TURNSTILE_SECRET_KEY': settings.TURNSTILE_SECRET_KEY,
    }
    return [name for name, value in values.items() if not value]


def _verify_turnstile(token, remote_ip=''):
    payload = {'secret': settings.TURNSTILE_SECRET_KEY, 'response': token}
    if remote_ip:
        payload['remoteip'] = remote_ip
    req = urllib_request.Request(
        'https://challenges.cloudflare.com/turnstile/v0/siteverify',
        data=parse.urlencode(payload).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    with urllib_request.urlopen(req, timeout=10) as response:
        result = json.loads(response.read().decode())
    if not result.get('success'):
        raise ValueError('turnstile_invalid')
    expected_host = parse.urlparse(settings.SITE_URL).hostname
    returned_host = result.get('hostname')
    if not settings.TURNSTILE_TEST_MODE and expected_host and returned_host and returned_host != expected_host:
        raise ValueError('turnstile_hostname')
    return {'hostname': returned_host or '', 'action': result.get('action', '')}


def _verify_google_credential(credential):
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    claims = id_token.verify_oauth2_token(
        credential,
        google_requests.Request(),
        settings.GOOGLE_CLIENT_ID,
    )
    if claims.get('iss') not in ('accounts.google.com', 'https://accounts.google.com'):
        raise ValueError('google_issuer')
    if not claims.get('sub') or not claims.get('email'):
        raise ValueError('google_identity')
    if claims.get('email_verified') is not True:
        raise PermissionError('google_email_unverified')
    return {
        'sub': str(claims['sub']),
        'email': str(claims['email']).strip().casefold(),
        'issuer': claims['iss'],
    }

def home(request):
    return render(request, 'core/home.html', {'stories': public_stories()[:3], 'events': AccountabilityEvent.objects.order_by('-event_date')[:3], 'featured_petition':Petition.objects.filter(petition_status='published',is_featured=True).order_by('-published_at').first()})

def simple_page(request, page):
    allowed = {'about','privacy','terms','guidelines','contact','support','help-me-say-it','accountability','evidence','petition'}
    if page not in allowed: return redirect('home')
    return render(request, f'core/{page}.html', {'events': AccountabilityEvent.objects.order_by('-event_date'), 'resources': SupportResource.objects.filter(verified=True)})

def accountability(request):
    question_form = PublicQuestionForm(prefix='question')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'question':
            question_form = PublicQuestionForm(request.POST, prefix='question')
            if question_form.is_valid():
                question_form.save(); messages.success(request, 'Your question is now waiting for moderation. Thank you for raising it responsibly.'); return redirect('accountability')
    context = {
        'events': AccountabilityEvent.objects.filter(published=True, verification_status__iexact='Verified').order_by('-event_date'),
        'evidence_items': EvidenceDocument.objects.filter(published=True, verified=True).order_by('-document_date')[:6],
        'questions': PublicQuestion.objects.filter(approved=True).order_by('-upvotes','-created_at')[:8],
        'promises': PromiseTracker.objects.filter(verified=True).order_by('-promise_date'),
        'responses': AuthorityResponse.objects.filter(published=True).order_by('-created_at'),
        'question_form': question_form,
        'featured_petition': Petition.objects.filter(petition_status='published', is_featured=True).order_by('-published_at').first(),
        'active_petitions': Petition.objects.filter(petition_status='published').order_by('-is_featured','-published_at')[:6],
        'student_demands': StudentDemand.objects.filter(is_published=True).order_by('display_order','priority'),
    }
    return render(request, 'core/accountability.html', context)

def _masked_email_for_log(email):
    local, _, domain = (email or '').partition('@')
    return f'{local[:1]}***@{domain}' if domain else 'invalid-email'


def _petition_email(request, signature, raw_token):
    if not settings.DEBUG and settings.EMAIL_BACKEND.endswith('console.EmailBackend'):
        raise ImproperlyConfigured('A real email backend is required for petition verification.')
    relative_url = reverse('petition_verify', args=[raw_token])
    verify_url = f'{settings.SITE_URL}{relative_url}' if settings.SITE_URL else request.build_absolute_uri(relative_url)
    site_root = settings.SITE_URL or request.build_absolute_uri('/').rstrip('/')
    context = {'supporter_name':signature.name, 'petition_title':signature.petition.title, 'verification_url':verify_url, 'logo_url':f'{site_root}/static/images/brand/unmute-india.webp'}
    subject = f'Verify your support for {signature.petition.title} | Unmute India'
    text = render_to_string('emails/petition_verification.txt', context)
    html = render_to_string('emails/petition_verification.html', context)
    email = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [signature.normalized_email])
    email.attach_alternative(html, 'text/html')
    logger.info('Verification email attempt started signature=%s petition=%s.', signature.pk, signature.petition_id)
    sent = email.send(fail_silently=False)
    if sent != 1:
        raise RuntimeError('The verification email provider did not accept the message.')
    recipient_domain = signature.email.rsplit('@', 1)[-1].lower()
    logger.info(
        'Petition verification email accepted by SMTP for signature=%s recipient_domain=%s.',
        signature.pk,
        recipient_domain,
    )
    return sent

def _issue_token(request, signature):
    previous_token = signature.verification_token
    previous_token_created_at = signature.token_created_at
    raw = secrets.token_urlsafe(32)
    now = timezone.now()
    signature.verification_token = hashlib.sha256(raw.encode()).hexdigest()
    signature.token_created_at = now
    # Store the token before sending so the URL is immediately usable, but do not
    # mark the attempt as sent or start its cooldown until SMTP accepts it.
    signature.save(update_fields=['verification_token','token_created_at','normalized_email','verified'])
    logger.info('Petition token created signature=%s petition=%s.', signature.pk, signature.petition_id)
    try:
        logger.info('Petition email helper called signature=%s.', signature.pk)
        sent = _petition_email(request, signature, raw)
    except Exception as exc:
        # A failed delivery must not invalidate a previously delivered link.
        signature.verification_token = previous_token
        signature.token_created_at = previous_token_created_at
        signature.save(update_fields=['verification_token', 'token_created_at'])
        PetitionSignature.objects.filter(pk=signature.pk).update(verification_email_failures=F('verification_email_failures') + 1)
        AuditLog.objects.create(action='Verification email failed', object_reference=f'PetitionSignature:{signature.pk}')
        logger.exception('Petition email exception signature=%s type=%s.', signature.pk, type(exc).__name__)
        raise
    sent_at = timezone.now()
    signature.verification_email_sent_at = sent_at
    signature.resend_available_at = sent_at + timezone.timedelta(minutes=5)
    signature.verification_email_attempts += 1
    signature.save(update_fields=['verification_email_sent_at','resend_available_at','verification_email_attempts'])
    logger.info('Petition email send result signature=%s sent=%s.', signature.pk, sent)
    AuditLog.objects.create(action='Verification email sent', object_reference=f'PetitionSignature:{signature.pk}')

def petition_detail(request, slug):
    petition = get_object_or_404(Petition, slug=slug, petition_status__in=['published','paused','closed'])
    form = GooglePetitionSupportForm(request.POST or None)
    if request.method == 'POST':
        return JsonResponse({'ok':False,'message':'Email verification has been discontinued. Please use Google verification.'}, status=410)
    supporters = petition.signatures.filter(is_verified=True, verified_at__isnull=False, moderation_status='valid', is_removed=False, removed_at__isnull=True).order_by('-verified_at')[:8]
    related = Petition.objects.filter(petition_status='published').exclude(pk=petition.pk)[:3]
    canonical_url = request.build_absolute_uri(petition.get_absolute_url())
    # The featured resignation campaign uses a deployment-safe static cover.
    # User-uploaded media lives on Render's ephemeral filesystem unless an
    # external media store is configured, so it must not be the only copy of
    # this campaign's hero/share image.
    if petition.slug == 'demand-resignation-dharmendra-pradhan':
        hero_image_url = static(
            'images/accountability/dharmendra-pradhan-resign.png'
        )
    elif petition.cover_image:
        hero_image_url = petition.cover_image.url
    else:
        hero_image_url = ''
    social_image_url = (
        request.build_absolute_uri(f'{hero_image_url}?v=20260723')
        if hero_image_url
        else ''
    )
    missing_verification_settings = _missing_google_support_settings()
    verification_available = not missing_verification_settings
    if not verification_available:
        logger.error('Google petition support disabled: missing environment variables: %s.', ', '.join(missing_verification_settings))
    return render(request, 'accountability/petition_detail.html', {'petition':petition,'form':form,'verified_count':petition.verified_count,'supporters':supporters,'related_petitions':related,'canonical_url':canonical_url,'hero_image_url':hero_image_url,'social_image_url':social_image_url,'google_client_id':settings.GOOGLE_CLIENT_ID,'turnstile_site_key':settings.TURNSTILE_SITE_KEY,'verification_available':verification_available,'google_support_url':reverse('google_petition_support', args=[petition.slug])})


@require_POST
def google_petition_support(request, slug):
    petition = get_object_or_404(Petition, slug=slug, petition_status__in=['published','paused','closed'])
    if not petition.accepts_signatures:
        return JsonResponse({'ok':False,'message':'This petition is not accepting signatures.'}, status=400)
    missing_verification_settings = _missing_google_support_settings()
    if missing_verification_settings:
        logger.error('Google petition support request rejected: missing environment variables: %s.', ', '.join(missing_verification_settings))
        return JsonResponse({'ok':False,'message':GOOGLE_SUPPORT_UNAVAILABLE}, status=503)
    data = request.POST.copy()
    data['turnstile_token'] = request.POST.get('turnstile_token') or request.POST.get('cf-turnstile-response', '')
    logger.info(
        'Google petition support received petition=%s credential=%s turnstile=%s.',
        petition.pk,
        bool(request.POST.get('credential')),
        bool(data['turnstile_token']),
    )
    form = GooglePetitionSupportForm(data)
    if not form.is_valid():
        logger.warning('Google petition support form rejected petition=%s fields=%s.', petition.pk, sorted(form.errors.keys()))
        return JsonResponse({'ok':False,'message':'Please complete every required field and security check.','errors':form.errors.get_json_data()}, status=400)
    try:
        turnstile = _verify_turnstile(form.cleaned_data['turnstile_token'], request.META.get('REMOTE_ADDR', ''))
    except Exception as exc:
        logger.warning('Turnstile verification failed petition=%s type=%s.', petition.pk, type(exc).__name__)
        return JsonResponse({'ok':False,'reset_turnstile':True,'message':'We could not complete the security check. Please refresh and try again.'}, status=400)
    try:
        identity = _verify_google_credential(form.cleaned_data['credential'])
    except PermissionError:
        logger.warning('Google credential rejected petition=%s reason=missing_verified_email.', petition.pk)
        return JsonResponse({'ok':False,'reset_turnstile':True,'message':'This Google account does not have a verified email.'}, status=400)
    except Exception as exc:
        reason = 'audience_mismatch' if 'audience' in str(exc).casefold() else 'invalid_or_expired'
        logger.warning('Google credential verification failed petition=%s type=%s reason=%s.', petition.pk, type(exc).__name__, reason)
        return JsonResponse({'ok':False,'reset_turnstile':True,'message':'We could not verify this Google account. Please try again.'}, status=400)
    now = timezone.now()
    email = identity['email']
    try:
        with transaction.atomic():
            duplicate = PetitionSignature.objects.select_for_update().filter(petition=petition, google_subject=identity['sub']).first()
            if not duplicate:
                duplicate = PetitionSignature.objects.select_for_update().filter(petition=petition, normalized_email=email, is_verified=True).first()
            if duplicate:
                logger.info('Duplicate Google petition support prevented petition=%s signature=%s.', petition.pk, duplicate.pk)
                PetitionSignature.objects.filter(pk=duplicate.pk).update(duplicate_attempts=F('duplicate_attempts') + 1)
                AuditLog.objects.create(action='Duplicate Google support prevented', object_reference=f'PetitionSignature:{duplicate.pk}')
                return JsonResponse({'ok':True,'duplicate':True,'message':'You have already added your verified support to this petition.','verified_count':petition.verified_count})
            signature = PetitionSignature.objects.select_for_update().filter(petition=petition, normalized_email=email, is_verified=False).first()
            if signature is None:
                signature = PetitionSignature(petition=petition, email=email, normalized_email=email)
            signature.name = form.cleaned_data['name']
            signature.supporter_type = form.cleaned_data['supporter_type']
            signature.consent = True
            signature.google_subject = identity['sub']
            signature.verified_email = email
            signature.verification_method = 'google'
            signature.is_verified = True
            signature.verified = True
            signature.verified_at = now
            signature.google_verified_at = now
            signature.turnstile_verified_at = now
            signature.moderation_status = 'valid'
            signature.is_removed = False
            signature.removed_at = None
            signature.ip_hash = request_fingerprint(request.META.get('REMOTE_ADDR',''), settings.SECRET_KEY)
            signature.user_agent_hash = request_fingerprint(request.META.get('HTTP_USER_AGENT',''), settings.SECRET_KEY)
            signature.verification_metadata = {'google_issuer':identity['issuer'],'turnstile_hostname':turnstile.get('hostname','')}
            signature.save()
            AuditLog.objects.create(action='Google support verified', object_reference=f'PetitionSignature:{signature.pk}')
    except IntegrityError:
        existing = PetitionSignature.objects.filter(petition=petition).filter(Q(google_subject=identity['sub']) | Q(normalized_email=email, is_verified=True)).first()
        if existing:
            return JsonResponse({'ok':True,'duplicate':True,'message':'You have already added your verified support to this petition.','verified_count':petition.verified_count})
        logger.exception('Google petition support integrity failure petition=%s.', petition.pk)
        return JsonResponse({'ok':False,'reset_turnstile':True,'message':'We could not verify your support right now. Your support has not been counted.'}, status=503)
    except Exception:
        logger.exception('Google petition support transaction failed petition=%s.', petition.pk)
        return JsonResponse({'ok':False,'reset_turnstile':True,'message':'We could not verify your support right now. Your support has not been counted.'}, status=503)
    petition.refresh_from_db()
    return JsonResponse({'ok':True,'duplicate':False,'message':'Your support is verified.','verified_count':petition.verified_count,'role':signature.get_supporter_type_display(),'petition_title':petition.title})

def petition_verify(request, token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    signature = PetitionSignature.objects.filter(verification_token=token_hash).select_related('petition').first()
    state = 'invalid'
    if signature:
        expiry = int(getattr(settings, 'PETITION_VERIFICATION_EXPIRY_HOURS', 24))
        expired = not signature.token_created_at or timezone.now() > signature.token_created_at + timezone.timedelta(hours=expiry)
        if signature.is_verified:
            state = 'already'
            AuditLog.objects.create(action='Duplicate verification attempted', object_reference=f'PetitionSignature:{signature.pk}')
        else:
            state = 'discontinued'
            AuditLog.objects.create(action='Legacy verification link opened after discontinuation', object_reference=f'PetitionSignature:{signature.pk}')
    return render(request, 'accountability/verification_result.html', {'signature':signature,'state':state,'verified_count':signature.petition.verified_count if signature else 0})

@require_POST
def petition_resend(request, slug):
    get_object_or_404(Petition, slug=slug, petition_status__in=['published','paused','closed'])
    return JsonResponse({'ok':False,'message':'Email verification has been discontinued. Please use Google verification on the petition page.'}, status=410)

def talk(request):
    return render(request, 'listening/start.html', {'stories': public_stories()[:3]})

def share(request, kind='text'):
    if kind not in {'text','audio','video'}: kind = 'text'
    if request.method == 'POST':
        form = ListeningRequestForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False); item.kind = kind
            item.user = request.user if request.user.is_authenticated else None
            item.consent_at = timezone.now(); item.save()
            request.session['last_submission'] = str(item.public_id)
            return redirect('received')
        messages.error(request, 'Your message could not be sent yet, but what you wrote is still safe. You can try again.')
    else: form = ListeningRequestForm(initial={'anonymous':True,'wants_reply':True})
    return render(request, f'listening/{kind}_share.html', {'form':form, 'kind':kind})

def received(request): return render(request, 'listening/received.html', {'reference':request.session.get('last_submission')})

def safety(request):
    return render(request, 'support/safety.html', {'resources':SupportResource.objects.filter(verified=True)})

def stories(request):
    queryset = public_stories()
    return render(request, 'stories/feed.html', {'stories':queryset[:12], 'featured_stories':queryset.filter(featured=True)[:3]})

def public_stories():
    return Story.objects.filter(approved=True, moderation_status='published', public_consent=True, privacy_review_complete=True, removed_at__isnull=True).annotate(reaction_count=Count('reactions', distinct=True), comment_count=Count('comments', filter=Q(comments__approved=True), distinct=True)).order_by('-featured','-published_at','-created_at')

def story_format_page(request, story_format):
    templates={'text':'stories/text_stories.html','voice':'stories/voice_stories.html','video':'stories/video_stories.html'}
    if story_format not in templates: return redirect('stories')
    page=Paginator(public_stories().filter(story_format=story_format), 8 if story_format!='video' else 4).get_page(request.GET.get('page'))
    return render(request,templates[story_format],{'page_obj':page,'stories':page.object_list,'story_format':story_format})

TOPIC_PAGES={
    'hope':('stories/hope_stories.html','Hope Stories'),
    'exam':('stories/exam_pressure.html','Exam Pressure'),
    'family':('stories/family_pressure.html','Family Pressure'),
    'college':('stories/college_life.html','College Life'),
    'coaching':('stories/coaching_pressure.html','Coaching Pressure'),
    'protest':('stories/protest_experience.html','Protest Experience'),
    'message':('stories/message_to_students.html','Message to Students'),
}
def story_topic_page(request, topic):
    if topic not in TOPIC_PAGES: return redirect('stories')
    template,title=TOPIC_PAGES[topic]
    queryset=public_stories().filter(topic=topic)
    page=Paginator(queryset,9).get_page(request.GET.get('page'))
    return render(request,template,{'page_obj':page,'stories':page.object_list,'featured':queryset.first(),'text_stories':queryset.filter(story_format='text')[:4],'voice_stories':queryset.filter(story_format='voice')[:3],'video_stories':queryset.filter(story_format='video')[:3],'topic_title':title,'topic_key':topic})

def story_detail(request, slug):
    story = get_object_or_404(public_stories(), slug=slug)
    related=public_stories().filter(topic=story.topic).exclude(pk=story.pk)[:3]
    return render(request, 'stories/detail.html', {'story':story, 'comments':story.comments.filter(approved=True), 'related_stories':related})

@require_POST
def story_comment(request, pk):
    story=get_object_or_404(public_stories(),pk=pk)
    if story.comment_mode=='none': return JsonResponse({'ok':False,'message':'Comments are disabled for this story.'},status=403)
    body=request.POST.get('body','').strip()
    if not body or len(body)>800: return JsonResponse({'ok':False,'message':'Please write a comment between 1 and 800 characters.'},status=400)
    comment=story.comments.create(display_name=request.POST.get('display_name','').strip()[:80],body=body,approved=False)
    return JsonResponse({'ok':True,'message':'Your supportive comment is waiting for moderation.','comment_id':comment.pk})

def react(request, pk):
    if request.method == 'POST':
        if not request.session.session_key: request.session.create()
        story = get_object_or_404(public_stories(), pk=pk)
        reaction = request.POST.get('reaction')
        if reaction in dict(StoryReaction.REACTIONS): StoryReaction.objects.get_or_create(story=story, session_key=request.session.session_key, reaction=reaction)
    return redirect(request.POST.get('next') or 'stories')

def volunteer(request):
    form = VolunteerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid(): form.save(); return render(request,'core/volunteer.html',{'sent':True,'form':VolunteerForm()})
    return render(request,'core/volunteer.html',{'form':form})

@user_passes_test(lambda u: u.is_staff)
def dashboard(request):
    queue = ListeningRequest.objects.select_related('assigned_to').order_by('-safety_flag','created_at')
    petitions = Petition.objects.all()
    signatures = PetitionSignature.objects.all()
    return render(request,'dashboard/index.html',{
        'queue': queue,
        'new_count': queue.filter(status='new').count(),
        'active_count': queue.filter(status__in=['assigned', 'active']).count(),
        'safety_count': queue.filter(safety_flag=True).count(),
        'closed_count': queue.filter(status='closed').count(),
        'petition_count': petitions.count(),
        'petition_drafts': petitions.filter(petition_status='draft').count(),
        'petition_published': petitions.filter(petition_status='published').count(),
        'petition_paused': petitions.filter(petition_status='paused').count(),
        'petition_closed': petitions.filter(petition_status='closed').count(),
        'pending_signatures': signatures.filter(is_verified=False, moderation_status='pending').count(),
        'valid_signatures': signatures.filter(is_verified=True, verified_at__isnull=False, moderation_status='valid', is_removed=False, removed_at__isnull=True).count(),
        'google_signatures': signatures.filter(verification_method='google', is_verified=True, moderation_status='valid', is_removed=False).count(),
        'legacy_signatures': signatures.filter(verification_method='email_legacy', is_verified=True, moderation_status='valid', is_removed=False).count(),
        'email_failures': signatures.filter(verification_email_failures__gt=0).count(),
        'resend_attempts': signatures.filter(verification_email_attempts__gt=1).count(),
        'duplicate_attempts': signatures.filter(duplicate_attempts__gt=0).count(),
        'removed_signatures': signatures.filter(Q(is_removed=True)|Q(removed_at__isnull=False)).count(),
        'role_distribution': signatures.filter(is_verified=True, is_removed=False).values('supporter_type').annotate(total=Count('pk')).order_by('-total'),
        'latest_verified': signatures.filter(is_verified=True, is_removed=False).order_by('-verified_at')[:6],
    })

# Create your views here.
