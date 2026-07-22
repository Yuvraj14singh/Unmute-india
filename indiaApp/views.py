from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
import hashlib, secrets
from .forms import ListeningRequestForm, PetitionSignatureForm, PublicQuestionForm, VolunteerForm
from .models import AccountabilityEvent, AuthorityResponse, AuditLog, EvidenceDocument, ListeningRequest, Petition, PetitionSignature, PromiseTracker, PublicQuestion, Story, StoryReaction, StudentDemand, SupportResource
from .utils import request_fingerprint

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

def _petition_email(request, signature, raw_token):
    verify_url = request.build_absolute_uri(reverse('petition_verify', args=[raw_token]))
    context = {'name':signature.name, 'petition':signature.petition, 'verification_url':verify_url}
    subject = f'Confirm your support for: {signature.petition.title}'
    text = render_to_string('accountability/email/verify.txt', context)
    html = render_to_string('accountability/email/verify.html', context)
    email = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [signature.email])
    email.attach_alternative(html, 'text/html')
    email.send()

def _issue_token(request, signature):
    raw = secrets.token_urlsafe(32)
    signature.verification_token = hashlib.sha256(raw.encode()).hexdigest()
    signature.token_created_at = timezone.now()
    signature.save(update_fields=['verification_token','token_created_at','normalized_email','verified'])
    _petition_email(request, signature, raw)

def petition_detail(request, slug):
    petition = get_object_or_404(Petition, slug=slug, petition_status__in=['published','paused','closed'])
    form = PetitionSignatureForm(request.POST or None)
    if request.method == 'POST':
        if not petition.accepts_signatures:
            return JsonResponse({'ok':False,'message':'This petition is not accepting signatures.'}, status=400)
        last = request.session.get('petition_submit_at', 0)
        if timezone.now().timestamp() - last < 10:
            return JsonResponse({'ok':False,'message':'Please wait a moment before trying again.'}, status=429)
        if form.is_valid():
            email = form.cleaned_data['email'].strip().casefold()
            existing = PetitionSignature.objects.filter(petition=petition, normalized_email=email).first()
            if existing:
                message = 'You have already supported this petition.' if existing.is_verified else 'Your support is waiting for email verification. Please check your inbox.'
                return JsonResponse({'ok':False,'duplicate':True,'pending':not existing.is_verified,'message':message,'resend_url':reverse('petition_resend', args=[petition.slug])})
            try:
                with transaction.atomic():
                    signature = form.save(commit=False)
                    signature.petition = petition
                    signature.normalized_email = email
                    signature.moderation_status = 'pending'
                    signature.ip_hash = request_fingerprint(request.META.get('REMOTE_ADDR',''), settings.SECRET_KEY)
                    signature.user_agent_hash = request_fingerprint(request.META.get('HTTP_USER_AGENT',''), settings.SECRET_KEY)
                    signature.save()
                _issue_token(request, signature)
                request.session['petition_submit_at'] = timezone.now().timestamp()
                request.session['pending_petition_email'] = email
            except IntegrityError:
                return JsonResponse({'ok':False,'duplicate':True,'message':'This email has already been submitted for this petition.'}, status=409)
            return JsonResponse({'ok':True,'message':'Check your email to confirm your support.\n\nYour signature will be counted only after you click the verification link.'})
        return JsonResponse({'ok':False,'errors':form.errors.get_json_data()}, status=400)
    supporters = petition.signatures.filter(is_verified=True, moderation_status='valid', removed_at__isnull=True).order_by('-verified_at')[:8]
    related = Petition.objects.filter(petition_status='published').exclude(pk=petition.pk)[:3]
    canonical_url = request.build_absolute_uri(petition.get_absolute_url())
    social_image_url = request.build_absolute_uri(petition.cover_image.url) if petition.cover_image else ''
    return render(request, 'accountability/petition_detail.html', {'petition':petition,'form':form,'verified_count':petition.verified_count,'supporters':supporters,'related_petitions':related,'canonical_url':canonical_url,'social_image_url':social_image_url})

def petition_verify(request, token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    signature = PetitionSignature.objects.filter(verification_token=token_hash).select_related('petition').first()
    state = 'invalid'
    if signature:
        expiry = int(getattr(settings, 'PETITION_VERIFICATION_EXPIRY_HOURS', 48))
        expired = not signature.token_created_at or timezone.now() > signature.token_created_at + timezone.timedelta(hours=expiry)
        if signature.is_verified:
            state = 'already'
        elif not expired and not signature.removed_at:
            with transaction.atomic():
                locked = PetitionSignature.objects.select_for_update().get(pk=signature.pk)
                if not locked.is_verified:
                    locked.is_verified = True; locked.verified = True; locked.verified_at = timezone.now(); locked.moderation_status = 'valid'
                    locked.save(update_fields=['is_verified','verified','verified_at','moderation_status','normalized_email'])
                signature = locked
            state = 'verified'
    return render(request, 'accountability/verification_result.html', {'signature':signature,'state':state,'verified_count':signature.petition.verified_count if signature else 0})

@require_POST
def petition_resend(request, slug):
    petition = get_object_or_404(Petition, slug=slug, petition_status__in=['published','paused','closed'])
    email = request.POST.get('email','').strip().casefold()
    signature = PetitionSignature.objects.filter(petition=petition, normalized_email=email, is_verified=False, removed_at__isnull=True).first()
    if not signature: return JsonResponse({'ok':False,'message':'No pending signature was found.'}, status=404)
    if signature.token_created_at and timezone.now() < signature.token_created_at + timezone.timedelta(minutes=5):
        return JsonResponse({'ok':False,'message':'Please wait five minutes before requesting another email.'}, status=429)
    _issue_token(request, signature)
    return JsonResponse({'ok':True,'message':'A new verification email has been sent.'})

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
        'valid_signatures': signatures.filter(is_verified=True, moderation_status='valid', removed_at__isnull=True).count(),
    })

# Create your views here.
