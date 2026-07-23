import os
import uuid
import hashlib
import secrets
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

def private_upload(instance, filename):
    return f'private/{uuid.uuid4().hex}{os.path.splitext(filename)[1].lower()}'

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True

class UserProfile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name = models.CharField(max_length=80, blank=True)
    anonymous_preferred = models.BooleanField(default=True)
    email_updates = models.BooleanField(default=True)

class ListenerProfile(TimeStampedModel):
    ROLES = [('student','Student Listener'),('senior','Senior Listener'),('counsellor','Verified Counsellor'),('legal','Legal Support Volunteer'),('academic','Academic Support Volunteer'),('coordinator','Support Coordinator'),('moderator','Moderator'),('admin','Super Admin')]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name = models.CharField(max_length=80)
    role = models.CharField(max_length=20, choices=ROLES, default='student')
    introduction = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    available = models.BooleanField(default=True)
    max_active_conversations = models.PositiveSmallIntegerField(default=5)

class ListeningRequest(TimeStampedModel):
    TYPES = [('text','Text'),('audio','Audio'),('video','Video')]
    NEEDS = [('listen','Just listen'),('reply','Send a supportive reply'),('think','Help me think through this'),('trusted','Help me talk to someone I trust'),('unsure','I am not sure')]
    STATUS = [('new','New'),('assigned','Assigned'),('active','Active'),('closed','Closed')]
    PUBLICATION_STATUS = [('private','Private — not submitted for publication'),('review','Public sharing review requested'),('published','Approved and published'),('rejected','Public sharing declined'),('removed','Unpublished by staff')]
    CATEGORIES = [('unsaid','Something I cannot tell anyone'),('exam','Exam pressure'),('family','Family pressure'),('college','College or coaching pressure'),('confession','Personal confession'),('protest','Protest or accountability experience'),('message','A message for other students'),('hope','Hope or recovery'),('other','Other')]
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=10, choices=TYPES, default='text')
    message = models.TextField(blank=True)
    media = models.FileField(upload_to=private_upload, blank=True, validators=[FileExtensionValidator(['mp3','m4a','wav','ogg','webm','mp4','mov'])])
    anonymous = models.BooleanField(default=True)
    wants_reply = models.BooleanField(default=True)
    support_preference = models.CharField(max_length=12, choices=NEEDS, blank=True)
    privacy = models.CharField(max_length=20, default='private', editable=False)
    status = models.CharField(max_length=12, choices=STATUS, default='new', db_index=True)
    assigned_to = models.ForeignKey(ListenerProfile, null=True, blank=True, on_delete=models.SET_NULL)
    safety_flag = models.BooleanField(default=False, db_index=True)
    consent_at = models.DateTimeField(null=True, blank=True)
    public_sharing_consent = models.BooleanField(default=False, db_index=True, help_text='The student explicitly allowed this submission to be reviewed for anonymous public sharing.')
    publication_status = models.CharField(max_length=12, choices=PUBLICATION_STATUS, default='private', db_index=True)
    published_story = models.OneToOneField('Story', null=True, blank=True, related_name='source_listening_request', on_delete=models.SET_NULL)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name='reviewed_listening_requests', on_delete=models.SET_NULL)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    tracking_code = models.CharField(max_length=16, unique=True, null=True, blank=True, editable=False)
    title = models.CharField(max_length=140, blank=True)
    category = models.CharField(max_length=30, choices=CATEGORIES, blank=True)
    comment_preference = models.CharField(max_length=10, choices=[('support','Supportive comments allowed'),('advice','Advice welcome'),('none','No comments')], default='support')
    public_consent_withdrawn_at = models.DateTimeField(null=True, blank=True)
    moderation_notes = models.TextField(blank=True)
    privacy_review_complete = models.BooleanField(default=False)
    def save(self, *args, **kwargs):
        if not self.tracking_code:
            while True:
                code = 'UNM-' + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
                if not type(self).objects.filter(tracking_code=code).exists():
                    self.tracking_code = code
                    break
        super().save(*args, **kwargs)

@receiver(pre_delete, sender=ListeningRequest)
def remove_published_story_with_submission(sender, instance, **kwargs):
    """Archive the public copy before SET_NULL can make it look independent."""
    if instance.published_story_id:
        Story.objects.filter(pk=instance.published_story_id).update(
            approved=False,
            moderation_status='archived',
            removed_at=timezone.now(),
            updated_at=timezone.now(),
        )
        AuditLog.objects.create(
            action='Unpublished public Story because source ListeningRequest was deleted',
            object_reference=f'ListeningRequest:{instance.pk}:Story:{instance.published_story_id}',
        )

@receiver(post_save, sender=ListeningRequest)
def unpublish_story_when_source_becomes_ineligible(sender, instance, **kwargs):
    if not instance.published_story_id:
        return
    has_content=bool(instance.message.strip()) if instance.kind == 'text' else bool(instance.media)
    remains_public=(
        instance.public_sharing_consent
        and instance.public_consent_withdrawn_at is None
        and instance.privacy_review_complete
        and not instance.safety_flag
        and instance.publication_status == 'published'
        and has_content
    )
    if remains_public:
        return
    changed=Story.objects.filter(
        pk=instance.published_story_id,
        moderation_status='published',
    ).update(
        approved=False,
        moderation_status='archived',
        removed_at=timezone.now(),
        updated_at=timezone.now(),
    )
    if changed:
        type(instance).objects.filter(pk=instance.pk,publication_status='published').update(
            publication_status='removed',
            updated_at=timezone.now(),
        )
        AuditLog.objects.create(
            action='Unpublished public Story because source became ineligible',
            object_reference=f'ListeningRequest:{instance.pk}:Story:{instance.published_story_id}',
        )

class ConversationMessage(TimeStampedModel):
    request = models.ForeignKey(ListeningRequest, related_name='replies', on_delete=models.CASCADE)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    body = models.TextField()
    internal = models.BooleanField(default=False)

class Story(TimeStampedModel):
    MODES = [('support','Support only'),('advice','Advice welcome'),('none','No comments')]
    FORMATS = [('text','Text'),('voice','Voice'),('video','Video')]
    TOPICS = [('heard','Needed to be heard'),('alone','I thought I was alone'),('listened','Someone listened to me'),('hope','I did not give up'),('message','To another student'),('exam','Exam pressure'),('family','Family pressure'),('college','College life'),('coaching','Coaching pressure'),('protest','Protest experience')]
    title = models.CharField(max_length=140, blank=True)
    body = models.TextField()
    slug = models.SlugField(unique=True)
    display_name = models.CharField(max_length=80, blank=True)
    age_group = models.CharField(max_length=40, blank=True)
    state = models.CharField(max_length=80, blank=True)
    story_format = models.CharField(max_length=10, choices=FORMATS, default='text', db_index=True)
    topic = models.CharField(max_length=20, choices=TOPICS, default='heard', db_index=True)
    public_media = models.FileField(upload_to='stories/', blank=True, validators=[FileExtensionValidator(['mp3','m4a','wav','ogg','webm','mp4','mov'])])
    transcript = models.TextField(blank=True)
    duration = models.CharField(max_length=12, blank=True)
    content_warning = models.CharField(max_length=180, blank=True)
    face_hidden = models.BooleanField(default=False)
    audio_only = models.BooleanField(default=False)
    approved = models.BooleanField(default=False, db_index=True)
    comment_mode = models.CharField(max_length=10, choices=MODES, default='support')
    moderation_status = models.CharField(max_length=12, choices=[('draft','Draft'),('review','Pending Review'),('published','Published'),('rejected','Rejected'),('archived','Archived')], default='review', db_index=True)
    public_consent = models.BooleanField(default=False, db_index=True)
    privacy_review_complete = models.BooleanField(default=False, db_index=True)
    location_consented = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    removed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    featured = models.BooleanField(default=False, db_index=True)
    thumbnail = models.ImageField(upload_to='story_thumbnails/', blank=True)
    is_demo = models.BooleanField(default=False, db_index=True)
    source_was_listening_request = models.BooleanField(default=False, db_index=True, editable=False)
    def __str__(self): return self.title or f'{self.get_story_format_display()} story #{self.pk}'
    @property
    def is_public(self): return self.approved and self.moderation_status == 'published' and self.public_consent and self.privacy_review_complete and not self.removed_at

class StoryReaction(TimeStampedModel):
    REACTIONS = [('with_you','I am with you'),('not_alone','You are not alone'),('listening','I am listening'),('valid','Your feelings are valid'),('strength','Sending strength'),('attention','This needs attention')]
    story = models.ForeignKey(Story, related_name='reactions', on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40)
    anonymous_key = models.CharField(max_length=64, blank=True, db_index=True)
    reaction = models.CharField(max_length=16, choices=REACTIONS)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['story','session_key','reaction'], name='unique_story_reaction'),
            models.UniqueConstraint(fields=['story','anonymous_key','reaction'], condition=~Q(anonymous_key=''), name='unique_anonymous_story_reaction'),
        ]

class StoryComment(TimeStampedModel):
    STATUSES = [('pending','Pending'),('approved','Approved'),('rejected','Rejected'),('spam','Spam'),('removed','Removed')]
    story = models.ForeignKey(Story, related_name='comments', on_delete=models.CASCADE)
    parent = models.ForeignKey('self', null=True, blank=True, related_name='replies', on_delete=models.CASCADE)
    display_name = models.CharField(max_length=80, blank=True)
    body = models.TextField(max_length=800)
    approved = models.BooleanField(default=False, db_index=True)
    status = models.CharField(max_length=10, choices=STATUSES, default='pending', db_index=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    thread_locked = models.BooleanField(default=False)
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parent and (self.parent.parent_id or self.parent.story_id != self.story_id):
            raise ValidationError({'parent':'Replies may be nested one level only.'})
    @property
    def is_public(self):
        return self.approved and self.status == 'approved' and not self.removed_at

class CommentReaction(TimeStampedModel):
    comment = models.ForeignKey(StoryComment, related_name='reactions', on_delete=models.CASCADE)
    session_key_hash = models.CharField(max_length=64)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['comment','session_key_hash'], name='unique_comment_reaction')]

class CommentReport(TimeStampedModel):
    REASONS = [('harassment','Harassment'),('privacy','Reveals identity/private details'),('unsafe','Unsafe advice'),('spam','Spam'),('hate','Hate or abuse'),('other','Other')]
    comment = models.ForeignKey(StoryComment, related_name='reports', on_delete=models.CASCADE)
    reason = models.CharField(max_length=12, choices=REASONS)
    details = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=12, choices=[('pending','Pending'),('reviewed','Reviewed'),('dismissed','Dismissed')], default='pending', db_index=True)
    session_key_hash = models.CharField(max_length=64)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['comment','session_key_hash'], name='unique_comment_report')]

class AccountabilityEvent(TimeStampedModel):
    CATEGORIES = [('exam','Exam conducted'),('allegation','Paper leak allegation'),('response','Official response'),('investigation','Investigation'),('reexam','Re-exam'),('protest','Student protest'),('police','Police action'),('statement','Minister statement'),('court','Court update'),('reform','Reform announcement'),('other','Other')]
    SOURCE_TYPES = [('official','Official record'),('court','Court document'),('video','Source video'),('news','News report'),('other','Other source')]
    title = models.CharField(max_length=180)
    event_date = models.DateField()
    summary = models.TextField()
    why_it_matters = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORIES, default='other')
    source_url = models.URLField(blank=True)
    source_name = models.CharField(max_length=160, blank=True)
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPES, default='other')
    related_document_url = models.URLField(blank=True)
    related_video_url = models.URLField(blank=True)
    published = models.BooleanField(default=False, db_index=True)
    verification_status = models.CharField(max_length=30, default='Awaiting verification')

class EvidenceDocument(TimeStampedModel):
    TYPES = [('notice','Official notice'),('statement','Government statement'),('court','Court document'),('news','News report'),('video','Protest video'),('student','Student evidence')]
    title = models.CharField(max_length=180)
    document_date = models.DateField()
    source_name = models.CharField(max_length=160)
    source_url = models.URLField()
    evidence_type = models.CharField(max_length=20, choices=TYPES)
    summary = models.TextField(blank=True)
    verified = models.BooleanField(default=False, db_index=True)
    published = models.BooleanField(default=False, db_index=True)

class PublicQuestion(TimeStampedModel):
    question = models.TextField(max_length=500)
    name = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    anonymous = models.BooleanField(default=True)
    consent = models.BooleanField(default=False)
    approved = models.BooleanField(default=False, db_index=True)
    upvotes = models.PositiveIntegerField(default=0)

class Petition(TimeStampedModel):
    CATEGORIES = [('resignation','Resignation'),('accountability','Accountability'),('investigation','Investigation'),('exam_reform','Examination Reform'),('student_protection','Student Protection'),('public_apology','Public Apology'),('compensation','Compensation'),('institutional_action','Institutional Action'),('other','Other')]
    STATUSES = [('draft','Draft'),('review','Under Review'),('published','Published'),('paused','Paused'),('closed','Closed'),('archived','Archived')]
    title = models.CharField(max_length=220)
    slug = models.SlugField(unique=True)
    eyebrow_text = models.CharField(max_length=100, blank=True)
    short_heading = models.CharField(max_length=220)
    summary = models.TextField()
    full_description = models.TextField(blank=True)
    why_it_matters = models.TextField(blank=True)
    primary_demand = models.TextField()
    additional_demands = models.TextField(blank=True, help_text='One demand per line.')
    questions = models.TextField(blank=True, help_text='One question per line.')
    disclaimer = models.TextField(blank=True)
    confirmation_email_content = models.TextField(blank=True)
    verification_success_message = models.CharField(max_length=240, blank=True)
    share_message = models.CharField(max_length=280, blank=True)
    closing_statement = models.CharField(max_length=240, blank=True)
    target_person = models.CharField(max_length=160, blank=True)
    target_authority = models.CharField(max_length=180, blank=True)
    petition_category = models.CharField(max_length=30, choices=CATEGORIES, default='other')
    cover_image = models.ImageField(upload_to='petitions/', blank=True)
    petition_status = models.CharField(max_length=20, choices=STATUSES, default='draft', db_index=True)
    signature_goal = models.PositiveIntegerField(default=1000)
    allow_signatures = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False, db_index=True)
    hide_supporter_names = models.BooleanField(default=False)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    submitted_to = models.CharField(max_length=180, blank=True)
    authority_name = models.CharField(max_length=180, blank=True)
    submission_date = models.DateField(null=True, blank=True)
    submission_method = models.CharField(max_length=100, blank=True)
    reference_number = models.CharField(max_length=100, blank=True)
    submission_document = models.FileField(upload_to='petition_documents/', blank=True)
    public_note = models.TextField(blank=True)
    response_status = models.CharField(max_length=30, default='not_submitted', choices=[('not_submitted','Not Submitted'),('submitted','Submitted'),('acknowledged','Acknowledged'),('no_response','No Response'),('partial','Partial Response'),('full','Full Response'),('rejected','Rejected'),('follow_up','Follow-Up Required')])
    response_date = models.DateField(null=True, blank=True)
    response_document = models.FileField(upload_to='petition_responses/', blank=True)
    response_summary = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name='petitions_created', on_delete=models.SET_NULL)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name='petitions_updated', on_delete=models.SET_NULL)
    def __str__(self): return self.title
    def get_absolute_url(self): return reverse('petition_detail', args=[self.slug])
    @property
    def accepts_signatures(self): return self.petition_status == 'published' and self.allow_signatures
    @property
    def demand_list(self): return [x.strip() for x in self.additional_demands.splitlines() if x.strip()]
    @property
    def question_list(self): return [x.strip() for x in self.questions.splitlines() if x.strip()]
    @property
    def verified_count(self):
        if self.petition_status != 'published': return 0
        return self.signatures.filter(is_verified=True, verified_at__isnull=False, moderation_status='valid', is_removed=False, removed_at__isnull=True).count()
    class Meta:
        permissions = [('publish_petition','Can publish, pause, reopen and close petitions'),('view_petition_analytics','Can view petition analytics')]

class PetitionSignature(TimeStampedModel):
    SUPPORTER_TYPES = [('','Select your role'),('student','Student'),('parent','Parent'),('teacher','Teacher'),('educator','Educator'),('volunteer','Volunteer'),('citizen','Citizen'),('other','Other')]
    MODERATION = [('pending','Pending'),('valid','Valid'),('rejected','Rejected'),('duplicate','Duplicate'),('spam','Spam'),('removed','Removed')]
    VERIFICATION_METHODS = [('email_legacy','Legacy Email'),('google','Google')]
    petition = models.ForeignKey(Petition, null=True, related_name='signatures', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    email = models.EmailField()
    normalized_email = models.EmailField(db_index=True, default='')
    state = models.CharField(max_length=80, blank=True)
    supporter_type = models.CharField(max_length=12, choices=SUPPORTER_TYPES)
    consent = models.BooleanField(default=False)
    verified = models.BooleanField(default=False, db_index=True)
    is_verified = models.BooleanField(default=False, db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_token = models.CharField(max_length=64, blank=True)
    token_created_at = models.DateTimeField(null=True, blank=True)
    verification_email_sent_at = models.DateTimeField(null=True, blank=True)
    verification_email_attempts = models.PositiveIntegerField(default=0)
    verification_email_failures = models.PositiveIntegerField(default=0)
    duplicate_attempts = models.PositiveIntegerField(default=0)
    resend_available_at = models.DateTimeField(null=True, blank=True)
    moderation_status = models.CharField(max_length=12, choices=MODERATION, default='pending', db_index=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    is_removed = models.BooleanField(default=False, db_index=True)
    removal_reason = models.CharField(max_length=240, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    user_agent_hash = models.CharField(max_length=64, blank=True)
    google_subject = models.CharField(max_length=255, blank=True, db_index=True)
    verified_email = models.EmailField(blank=True)
    verification_method = models.CharField(max_length=20, choices=VERIFICATION_METHODS, default='email_legacy', db_index=True)
    google_verified_at = models.DateTimeField(null=True, blank=True)
    turnstile_verified_at = models.DateTimeField(null=True, blank=True)
    verification_metadata = models.JSONField(default=dict, blank=True)
    def save(self, *args, **kwargs):
        self.normalized_email = self.email.strip().casefold()
        self.email = self.email.strip()
        self.verified = self.is_verified
        super().save(*args, **kwargs)
    @property
    def verification_token_hash(self): return self.verification_token
    @property
    def verification_token_created_at(self): return self.token_created_at
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['petition','normalized_email'], name='unique_email_per_petition'),
            models.UniqueConstraint(fields=['petition','google_subject'], condition=~models.Q(google_subject=''), name='unique_google_subject_per_petition'),
        ]
        permissions = [('moderate_petition_signatures','Can moderate petition signatures'),('manually_verify_signature','Can manually verify a petition signature')]

class PetitionSource(TimeStampedModel):
    STATUSES = [('required','Source Required'),('review','Under Review'),('verified','Verified'),('disputed','Disputed'),('outdated','Outdated')]
    petition = models.ForeignKey(Petition, related_name='sources', on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    url = models.URLField()
    organisation = models.CharField(max_length=160, blank=True)
    publication_date = models.DateField(null=True, blank=True)
    verification_status = models.CharField(max_length=12, choices=STATUSES, default='required')
    internal_reviewer_note = models.TextField(blank=True)

class PetitionUpdate(TimeStampedModel):
    petition = models.ForeignKey(Petition, related_name='updates', on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    body = models.TextField()
    published = models.BooleanField(default=False)

class StudentDemand(TimeStampedModel):
    STATUSES = [('raised','Raised'),('submitted','Submitted'),('awaiting','Awaiting Response'),('partial','Partially Addressed'),('addressed','Addressed'),('rejected','Rejected'),('none','No Public Response')]
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=80, blank=True)
    priority = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=12, choices=STATUSES, default='raised')
    related_petition = models.ForeignKey(Petition, null=True, blank=True, on_delete=models.SET_NULL)
    source_url = models.URLField(blank=True)
    source_title = models.CharField(max_length=180, blank=True)
    is_featured = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)
    def __str__(self): return self.title

class PromiseTracker(TimeStampedModel):
    STATUSES = [('announced','Announced'),('pending','Pending'),('partial','Partially completed'),('complete','Completed'),('contradicted','Contradicted'),('none','No update')]
    promise = models.CharField(max_length=220)
    promise_date = models.DateField()
    expected_action = models.TextField()
    current_status = models.CharField(max_length=20, choices=STATUSES, default='announced')
    source_url = models.URLField()
    verified = models.BooleanField(default=False, db_index=True)

class AuthorityResponse(TimeStampedModel):
    STATUSES = [('not_sent','Not sent'),('sent','Sent'),('none','No response'),('partial','Partial response'),('full','Full response'),('disputed','Disputed response')]
    question = models.TextField()
    authority = models.CharField(max_length=180)
    date_sent = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default='not_sent')
    response_date = models.DateField(null=True, blank=True)
    response_text = models.TextField(blank=True)
    response_source_url = models.URLField(blank=True)
    follow_up_needed = models.BooleanField(default=False)
    published = models.BooleanField(default=False, db_index=True)

class SupportResource(TimeStampedModel):
    name = models.CharField(max_length=120)
    description = models.TextField()
    url = models.URLField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    verified = models.BooleanField(default=False)
    reviewed_at = models.DateField(null=True, blank=True)
    audience = models.CharField(max_length=160, blank=True)
    availability = models.CharField(max_length=120, blank=True)
    official_source = models.URLField(blank=True)

class VolunteerApplication(TimeStampedModel):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    motivation = models.TextField()
    status = models.CharField(max_length=20, default='new')

class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=160)
    object_reference = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

# Create your models here.
