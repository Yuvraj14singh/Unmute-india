from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
from django.utils.text import slugify
import logging
from .models import *

logger = logging.getLogger(__name__)

@admin.register(ListeningRequest)
class ListeningRequestAdmin(admin.ModelAdmin):
    change_list_template='admin/indiaApp/listeningrequest/change_list.html'
    change_form_template='admin/indiaApp/listeningrequest/change_form.html'
    list_display=('submission_summary','format_badge','status_badge','public_sharing_badge','publication_badge','safety_badge','assigned_to','created_at','row_actions')
    list_filter=('kind','status','publication_status','public_sharing_consent','anonymous','safety_flag')
    search_fields=('public_id','title','message')
    readonly_fields=('public_id','tracking_code','privacy','public_sharing_consent','publication_status','published_story','reviewed_by','reviewed_at','consent_at','public_consent_withdrawn_at','created_at','updated_at')
    date_hierarchy='created_at'
    ordering=('-safety_flag','-created_at')
    list_per_page=30
    actions=('approve_and_publish','mark_private_only','decline_publication','unpublish_selected','assign_to_me','mark_under_review')
    fieldsets=(
        ('Submission overview', {'fields':('public_id','kind','created_at','status','assigned_to')}),
        ('Private submission', {'fields':('title','category','message','media','anonymous','wants_reply','support_preference','privacy','consent_at')}),
        ('Public sharing review', {'fields':('public_sharing_consent','public_consent_withdrawn_at','comment_preference','privacy_review_complete','safety_flag','publication_status','published_story','reviewed_by','reviewed_at','moderation_notes'), 'description':'Only submissions with explicit public-sharing consent may be published. Review and remove personal details before approval.'}),
        ('Record', {'fields':('updated_at',)}),
    )

    def get_deleted_objects(self, objs, request):
        deleted, counts, permissions, protected=super().get_deleted_objects(objs,request)
        if any(item.published_story_id and item.publication_status == 'published' for item in objs):
            deleted.insert(0,format_html(
                '<strong>This submission is currently published. '
                'Deleting it will unpublish it and remove it from Unmuted Voices.</strong>'
            ))
        return deleted,counts,permissions,protected

    def get_urls(self):
        urls=super().get_urls()
        custom=[
            path('<path:object_id>/preview/',self.admin_site.admin_view(self.preview_view),name='indiaApp_listeningrequest_preview'),
            path('<path:object_id>/publish/',self.admin_site.admin_view(self.publish_view),name='indiaApp_listeningrequest_publish'),
            path('<path:object_id>/unpublish/',self.admin_site.admin_view(self.unpublish_view),name='indiaApp_listeningrequest_unpublish'),
            path('<path:object_id>/keep-private/',self.admin_site.admin_view(self.keep_private_view),name='indiaApp_listeningrequest_keep_private'),
            path('<path:object_id>/reject-public/',self.admin_site.admin_view(self.reject_public_view),name='indiaApp_listeningrequest_reject_public'),
        ]
        return custom+urls

    def changeform_view(self,request,object_id=None,form_url='',extra_context=None):
        item=self.get_object(request,object_id) if object_id else None
        reasons=[]
        if item:
            if not item.public_sharing_consent: reasons.append('This submission does not have public-sharing consent.')
            if item.safety_flag: reasons.append('This item is safety-flagged and cannot be published.')
            if item.kind not in ('text','audio','video'): reasons.append('This submission format cannot be published.')
            if item.kind=='text' and not item.message.strip(): reasons.append('Add valid text content before publishing.')
            if item.kind in ('audio','video') and not item.media: reasons.append(f'Attach a valid {item.get_kind_display().lower()} file before publishing.')
            if not self.has_change_permission(request,item): reasons.append('Your staff account does not have permission to publish.')
        context={**(extra_context or {}),'publication_reasons':reasons,'publication_eligible':bool(item and not reasons)}
        return super().changeform_view(request,object_id,form_url,context)

    def changelist_view(self,request,extra_context=None):
        qs=self.get_queryset(request)
        counts={
            'total':qs.count(),'new':qs.filter(status='new').count(),
            'active':qs.filter(status__in=('assigned','active')).count(),
            'text':qs.filter(kind='text').count(),'audio':qs.filter(kind='audio').count(),
            'video':qs.filter(kind='video').count(),
            'review':qs.filter(publication_status='review').count(),
            'published':qs.filter(publication_status='published').count(),
            'flagged':qs.filter(safety_flag=True).count(),
        }
        return super().changelist_view(request,{**(extra_context or {}),'workspace_subtitle':'Review private submissions, reply safely and approve consented public voices.','summary_counts':counts})

    @admin.display(description='Submission',ordering='public_id')
    def submission_summary(self,obj):
        excerpt=obj.title or ' '.join(obj.message.split())[:64] or f'{obj.get_kind_display()} submission'
        return format_html('<strong class="submission-id">#{}</strong><span class="submission-excerpt">{}</span><small>{}</small>',str(obj.public_id)[:8],excerpt,'Anonymous' if obj.anonymous else 'Identity protected')
    @admin.display(description='Format',ordering='kind')
    def format_badge(self,obj): return format_html('<span class="admin-badge format-{}">{}</span>',obj.kind,obj.get_kind_display())
    @admin.display(description='Status',ordering='status')
    def status_badge(self,obj): return format_html('<span class="admin-badge status-{}">{}</span>',obj.status,obj.get_status_display())
    @admin.display(description='Public sharing',ordering='public_sharing_consent')
    def public_sharing_badge(self,obj):
        label='Approved' if obj.publication_status=='published' else ('Review requested' if obj.public_sharing_consent else 'No consent')
        return format_html('<span class="admin-badge consent-{}">{}</span>','yes' if obj.public_sharing_consent else 'no',label)
    @admin.display(description='Publication',ordering='publication_status')
    def publication_badge(self,obj):
        if obj.published_story_id and obj.publication_status=='published':
            return format_html('<a class="admin-badge publication-published" href="{}">View public post</a>',reverse('story_detail',args=[obj.published_story.slug]))
        return format_html('<span class="admin-badge publication-{}">{}</span>',obj.publication_status,obj.get_publication_status_display())
    @admin.display(description='Safety',ordering='safety_flag')
    def safety_badge(self,obj): return format_html('<span class="admin-badge safety-{}">{}</span>','flagged' if obj.safety_flag else 'clear','Flagged' if obj.safety_flag else 'Clear')
    @admin.display(description='Actions')
    def row_actions(self,obj):
        review=reverse('admin:indiaApp_listeningrequest_change',args=[obj.pk])
        preview=reverse('admin:indiaApp_listeningrequest_preview',args=[obj.pk])
        controls=[format_html('<a class="row-action" href="{}">Review</a>',review),format_html('<a class="row-action" href="{}">Preview</a>',preview)]
        if obj.publication_status=='published':
            controls.append(format_html('<a class="row-action danger" href="{}">Unpublish</a>',reverse('admin:indiaApp_listeningrequest_unpublish',args=[obj.pk])))
        elif self._eligible(obj):
            controls.append(format_html('<a class="row-action publish" href="{}">Publish</a>',reverse('admin:indiaApp_listeningrequest_publish',args=[obj.pk])))
        return format_html('<div class="row-actions">{}</div>',format_html(''.join(str(x) for x in controls)))

    def _eligible(self,item):
        valid_content=bool(item.message.strip()) if item.kind=='text' else bool(item.media)
        return item.kind in ('text','audio','video') and item.public_sharing_consent and not item.safety_flag and valid_content

    def _publish(self,request,item):
        if not self.has_change_permission(request,item) or not self._eligible(item): return False,'Consent, safety or content requirements are not complete.'
        previous=item.publication_status
        with transaction.atomic():
            # The confirmed Approve & Publish action is the staff privacy-review decision.
            item.privacy_review_complete=True
            story=item.published_story or Story()
            excerpt=' '.join(item.message.split())[:72]
            story.title=item.title or story.title or excerpt or f'Anonymous {item.get_kind_display()} message'
            story.slug=story.slug or f"{slugify(story.title)[:48]}-{item.public_id.hex[:8]}"
            story.body=item.message.strip() or f'An anonymous student shared this {item.get_kind_display().lower()} message.'
            story.display_name='Anonymous Student' if item.anonymous else 'Student'
            story.story_format={'audio':'voice','video':'video'}.get(item.kind,'text')
            story.comment_mode=item.comment_preference
            story.source_was_listening_request=True
            story.approved=True; story.moderation_status='published'; story.public_consent=True
            story.privacy_review_complete=True; story.removed_at=None; story.published_at=story.published_at or timezone.now()
            # ListeningRequest.media and Story.public_media use the same configured
            # storage. Reuse the existing storage key instead of opening/copying a
            # potentially large file. This is atomic, idempotent and works with
            # Render filesystems as well as remote object-storage backends.
            if item.media:
                story.public_media.name=item.media.name
            story.save()
            item.privacy_review_complete=True; item.publication_status='published'; item.published_story=story
            item.reviewed_by=request.user; item.reviewed_at=timezone.now()
            item.save(update_fields=('privacy_review_complete','publication_status','published_story','reviewed_by','reviewed_at','updated_at'))
            AuditLog.objects.create(actor=request.user,action=f'Published ListeningRequest ({previous} → published)',object_reference=f'ListeningRequest:{item.pk}:Story:{story.pk}')
        return True,'Published in Unmuted Voices.'

    def _unpublish(self,request,item,reason='Staff moderation decision'):
        if not self.has_change_permission(request,item) or not item.published_story_id: return False
        previous=item.publication_status
        with transaction.atomic():
            story=item.published_story
            story.removed_at=timezone.now(); story.moderation_status='archived'; story.approved=False
            story.save(update_fields=('removed_at','moderation_status','approved','updated_at'))
            item.publication_status='removed'; item.reviewed_by=request.user; item.reviewed_at=timezone.now()
            item.save(update_fields=('publication_status','reviewed_by','reviewed_at','updated_at'))
            AuditLog.objects.create(actor=request.user,action=f'Unpublished ListeningRequest ({previous} → removed): {reason[:60]}',object_reference=f'ListeningRequest:{item.pk}:Story:{story.pk}')
        return True

    @admin.action(description='Approve & publish selected consented submissions')
    def approve_and_publish(self, request, queryset):
        published=skipped=failed=0
        for item in queryset.select_related('published_story'):
            try:
                # Choosing this explicit approval action completes the staff privacy review.
                if item.public_sharing_consent and not item.safety_flag:
                    item.privacy_review_complete=True
                    item.save(update_fields=('privacy_review_complete','updated_at'))
                ok,_=self._publish(request,item)
                if ok: published+=1
                else: skipped+=1
            except Exception: failed+=1
        if published:
            self.message_user(request, f'{published} submission(s) approved and published in Unmuted Voices.', messages.SUCCESS)
        if skipped:
            self.message_user(request, f'{skipped} submission(s) skipped because public consent was absent, already decided, or not awaiting review.', messages.WARNING)
        if failed:
            self.message_user(request, f'{failed} submission(s) could not be published. Check media storage and server logs.', messages.ERROR)

    @admin.action(description='Decline public publication for selected submissions')
    def decline_publication(self, request, queryset):
        eligible=queryset.exclude(publication_status='published')
        count=eligible.update(publication_status='rejected',reviewed_by=request.user,reviewed_at=timezone.now())
        if count:
            AuditLog.objects.create(actor=request.user, action=f'Declined {count} public sharing request(s)', object_reference='ListeningRequest bulk action')
        self.message_user(request, f'{count} public sharing request(s) declined; their private support records remain protected.', messages.SUCCESS)

    @admin.action(description='Mark selected private-only')
    def mark_private_only(self,request,queryset):
        eligible=queryset.exclude(publication_status='published'); count=eligible.update(publication_status='private',reviewed_by=request.user,reviewed_at=timezone.now())
        AuditLog.objects.create(actor=request.user,action=f'Marked {count} ListeningRequests private-only',object_reference='ListeningRequest bulk action')
        self.message_user(request,f'{count} submission(s) kept private.',messages.SUCCESS)
    @admin.action(description='Unpublish selected')
    def unpublish_selected(self,request,queryset):
        count=sum(1 for item in queryset.select_related('published_story') if self._unpublish(request,item))
        self.message_user(request,f'{count} public voice(s) unpublished; private originals were preserved.',messages.SUCCESS)
    @admin.action(description='Mark selected under review')
    def mark_under_review(self,request,queryset):
        count=queryset.exclude(publication_status='published').update(status='active',publication_status='review',reviewed_by=request.user,reviewed_at=timezone.now())
        AuditLog.objects.create(actor=request.user,action=f'Marked {count} ListeningRequests under review',object_reference='ListeningRequest bulk action')
        self.message_user(request,f'{count} submission(s) marked under review.',messages.SUCCESS)
    @admin.action(description='Assign selected to my listener profile')
    def assign_to_me(self,request,queryset):
        profile=ListenerProfile.objects.filter(user=request.user).first()
        if not profile:
            self.message_user(request,'Create a Listener Profile for this staff account before assigning requests.',messages.ERROR)
            return
        count=queryset.update(assigned_to=profile,status='assigned')
        AuditLog.objects.create(actor=request.user,action=f'Assigned {count} ListeningRequests to listener',object_reference=f'ListenerProfile:{profile.pk}')
        self.message_user(request,f'{count} submission(s) assigned to {profile.display_name}.',messages.SUCCESS)

    def preview_view(self,request,object_id):
        item=get_object_or_404(ListeningRequest,pk=object_id)
        if not self.has_view_permission(request,item): raise PermissionDenied
        return render(request,'admin/indiaApp/listeningrequest/preview.html',{'item':item,'title':'Public preview','opts':self.model._meta})
    def publish_view(self,request,object_id):
        item=get_object_or_404(ListeningRequest,pk=object_id)
        if request.method=='POST':
            try:
                ok,message=self._publish(request,item)
            except Exception:
                logger.exception('ListeningRequest publication failed request_id=%s kind=%s',item.pk,item.kind)
                ok=False
                message='This media could not be published safely. The private submission is unchanged; please retry or verify that its uploaded file is still available.'
            self.message_user(request,message,messages.SUCCESS if ok else messages.ERROR)
            return HttpResponseRedirect(reverse('admin:indiaApp_listeningrequest_change',args=[item.pk]))
        return render(request,'admin/indiaApp/listeningrequest/confirm_action.html',{'item':item,'action_name':'Publish','prompt':'Approve this submission for public sharing?','warning':'This creates or restores one public Unmuted Voices post after privacy review.','opts':self.model._meta})
    def unpublish_view(self,request,object_id):
        item=get_object_or_404(ListeningRequest,pk=object_id)
        if request.method=='POST':
            ok=self._unpublish(request,item,request.POST.get('reason','')); self.message_user(request,'Public post unpublished; private submission preserved.' if ok else 'This item could not be unpublished.',messages.SUCCESS if ok else messages.ERROR)
            return HttpResponseRedirect(reverse('admin:indiaApp_listeningrequest_change',args=[item.pk]))
        return render(request,'admin/indiaApp/listeningrequest/confirm_action.html',{'item':item,'action_name':'Unpublish','prompt':'Remove this voice from public view?','warning':'The original private submission and audit history will remain stored.','require_reason':True,'opts':self.model._meta})

    def _private_decision(self,request,item,status,label,reason=''):
        if not self.has_change_permission(request,item): raise PermissionDenied
        previous=item.publication_status
        if item.publication_status=='published':
            self._unpublish(request,item,reason or label)
            item.refresh_from_db()
        item.publication_status=status; item.reviewed_by=request.user; item.reviewed_at=timezone.now()
        item.save(update_fields=('publication_status','reviewed_by','reviewed_at','updated_at'))
        AuditLog.objects.create(actor=request.user,action=f'{label} ListeningRequest ({previous} → {status}){": "+reason[:60] if reason else ""}',object_reference=f'ListeningRequest:{item.pk}:Story:{item.published_story_id or "none"}')

    def keep_private_view(self,request,object_id):
        item=get_object_or_404(ListeningRequest,pk=object_id)
        if request.method=='POST':
            self._private_decision(request,item,'private','Kept private',request.POST.get('reason',''))
            self.message_user(request,'Submission marked private-only. No private content was deleted.',messages.SUCCESS)
            return HttpResponseRedirect(reverse('admin:indiaApp_listeningrequest_change',args=[item.pk]))
        return render(request,'admin/indiaApp/listeningrequest/confirm_action.html',{'item':item,'action_name':'Keep Private','prompt':'Keep this submission private-only?','warning':'It will not appear in Unmuted Voices. The protected source record remains available to authorised staff.','opts':self.model._meta})

    def reject_public_view(self,request,object_id):
        item=get_object_or_404(ListeningRequest,pk=object_id)
        if request.method=='POST':
            self._private_decision(request,item,'rejected','Rejected public sharing',request.POST.get('reason',''))
            self.message_user(request,'Public sharing rejected; the private submission was preserved.',messages.SUCCESS)
            return HttpResponseRedirect(reverse('admin:indiaApp_listeningrequest_change',args=[item.pk]))
        return render(request,'admin/indiaApp/listeningrequest/confirm_action.html',{'item':item,'action_name':'Reject Public Sharing','prompt':'Reject this public-sharing request?','warning':'This does not delete or expose the private submission.','require_reason':True,'opts':self.model._meta})

@admin.register(Petition)
class PetitionAdmin(admin.ModelAdmin):
    list_display=('title','petition_status','petition_category','is_featured','allow_signatures','signature_total','published_at')
    list_filter=('petition_status','petition_category','is_featured','allow_signatures')
    search_fields=('title','summary','target_person','target_authority')
    prepopulated_fields={'slug':('title',)}
    readonly_fields=('created_at','updated_at','published_at')
    fieldsets=((None,{'fields':('title','slug','eyebrow_text','short_heading','summary','cover_image')}),('Petition content',{'fields':('full_description','why_it_matters','primary_demand','additional_demands','questions','disclaimer')}),('Target and classification',{'fields':('target_person','target_authority','petition_category')}),('Publishing',{'fields':('petition_status','allow_signatures','is_featured','hide_supporter_names','signature_goal','start_date','end_date','published_at')}),('Messages',{'classes':('collapse',),'fields':('confirmation_email_content','verification_success_message','share_message','closing_statement')}),('Submission and response',{'classes':('collapse',),'fields':('submitted_to','authority_name','submission_date','submission_method','reference_number','submission_document','public_note','response_status','response_date','response_document','response_summary','follow_up_date')}))
    def signature_total(self,obj): return obj.verified_count
    def save_model(self,request,obj,form,change):
        from django.utils import timezone
        from django.core.exceptions import PermissionDenied
        publishing = obj.petition_status in ('published','paused','closed','archived')
        if publishing and not request.user.has_perm('indiaApp.publish_petition') and not request.user.is_superuser:
            raise PermissionDenied('You may edit drafts, but only a Petition Manager can publish or change a live petition.')
        if not change: obj.created_by=request.user
        obj.updated_by=request.user
        if obj.petition_status=='published' and not obj.published_at: obj.published_at=timezone.now()
        super().save_model(request,obj,form,change)
        AuditLog.objects.create(actor=request.user,action='Updated petition' if change else 'Created petition',object_reference=f'Petition:{obj.pk}:{obj.petition_status}')

@admin.register(PetitionSignature)
class PetitionSignatureAdmin(admin.ModelAdmin):
    list_display=('name','masked_email','supporter_type','petition','verification_label','is_verified','moderation_status','verified_at','created_at')
    list_filter=('petition','verification_method','is_verified','moderation_status','supporter_type')
    search_fields=('name','email','normalized_email','google_subject')
    readonly_fields=('normalized_email','google_subject','verified_email','verification_method','google_verified_at','turnstile_verified_at','verification_metadata','verification_token','token_created_at','verification_email_sent_at','verification_email_attempts','verification_email_failures','duplicate_attempts','resend_available_at','is_verified','verified','verified_at','ip_hash','user_agent_hash','created_at','updated_at')
    actions=('mark_valid','flag_for_review','mark_spam','reject_signatures','remove_signatures','restore_signatures','export_verified')
    def _moderate(self,request,queryset,status):
        count=queryset.update(moderation_status=status)
        AuditLog.objects.create(actor=request.user,action=f'Marked {count} signatures {status}',object_reference='PetitionSignature bulk action')
    @admin.action(description='Mark selected signatures valid')
    def mark_valid(self,request,queryset): self._moderate(request,queryset,'valid')
    @admin.display(description='Protected email')
    def masked_email(self,obj):
        from .utils import mask_email
        return mask_email(obj.email)
    @admin.display(description='Verification')
    def verification_label(self,obj):
        if obj.verification_method == 'google' and obj.is_verified: return 'Google Verified'
        if obj.is_verified: return 'Legacy Email Verified'
        return 'Pending Legacy Email'
    @admin.action(description='Flag selected signatures for review')
    def flag_for_review(self,request,queryset): self._moderate(request,queryset,'pending')
    @admin.action(description='Mark selected signatures as spam')
    def mark_spam(self,request,queryset): self._moderate(request,queryset,'spam')
    @admin.action(description='Reject selected signatures')
    def reject_signatures(self,request,queryset): self._moderate(request,queryset,'rejected')
    @admin.action(description='Remove selected signatures')
    def remove_signatures(self,request,queryset):
        from django.utils import timezone
        count=queryset.update(moderation_status='removed',is_removed=True,removed_at=timezone.now())
        AuditLog.objects.create(actor=request.user,action=f'Removed {count} signatures',object_reference='PetitionSignature bulk action')
    @admin.action(description='Restore selected valid signatures')
    def restore_signatures(self,request,queryset):
        count=queryset.filter(is_verified=True).update(moderation_status='valid',is_removed=False,removed_at=None,removal_reason='')
        AuditLog.objects.create(actor=request.user,action=f'Restored {count} signatures',object_reference='PetitionSignature bulk action')
    @admin.action(description='Export selected verified signatures as CSV')
    def export_verified(self,request,queryset):
        import csv
        from django.http import HttpResponse
        response=HttpResponse(content_type='text/csv'); response['Content-Disposition']='attachment; filename="verified-petition-signatures.csv"'
        writer=csv.writer(response); writer.writerow(['Name','Email','Role','Petition','Verified at'])
        for item in queryset.filter(is_verified=True,moderation_status='valid',removed_at__isnull=True): writer.writerow([item.name,item.email,item.get_supporter_type_display(),item.petition,item.verified_at])
        AuditLog.objects.create(actor=request.user,action='Exported verified signatures',object_reference='PetitionSignature export')
        return response

class PetitionSourceInline(admin.TabularInline): model=PetitionSource; extra=0
class PetitionUpdateInline(admin.StackedInline): model=PetitionUpdate; extra=0
PetitionAdmin.inlines=(PetitionSourceInline,PetitionUpdateInline)

@admin.register(StudentDemand)
class StudentDemandAdmin(admin.ModelAdmin):
    list_display=('title','status','priority','is_published','is_featured','display_order')
    list_editable=('status','priority','is_published','is_featured','display_order')
    list_filter=('status','is_published','is_featured')

@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display=('title','story_format','topic','moderation_status','public_consent','privacy_review_complete','featured','published_at')
    list_filter=('story_format','topic','moderation_status','public_consent','privacy_review_complete','featured','is_demo')
    search_fields=('title','body','display_name','slug')
    prepopulated_fields={'slug':('title',)}
    readonly_fields=('created_at','updated_at')
    fieldsets=((None,{'fields':('title','slug','body','display_name','age_group','state','location_consented')}),('Format and media',{'fields':('story_format','topic','public_media','thumbnail','duration','transcript','face_hidden','audio_only')}),('Safety and publication',{'fields':('content_warning','comment_mode','approved','moderation_status','public_consent','privacy_review_complete','featured','published_at','removed_at','is_demo')}),('Record',{'fields':('created_at','updated_at')}))
    def save_model(self,request,obj,form,change):
        from django.utils import timezone
        if obj.moderation_status=='published' and obj.approved and obj.public_consent and obj.privacy_review_complete and not obj.published_at: obj.published_at=timezone.now()
        super().save_model(request,obj,form,change)
        AuditLog.objects.create(actor=request.user,action='Updated public story moderation' if change else 'Created story record',object_reference=f'Story:{obj.pk}:{obj.moderation_status}')

@admin.register(StoryComment)
class StoryCommentAdmin(admin.ModelAdmin):
    list_display=('story','display_name','status','parent','thread_locked','created_at')
    list_filter=('status','approved','thread_locked')
    actions=('approve','reject','remove','restore','mark_spam','lock_threads')
    def _set(self,request,queryset,status,approved=False,removed_at=None):
        count=queryset.update(status=status,approved=approved,removed_at=removed_at,approved_at=timezone.now() if approved else None)
        AuditLog.objects.create(actor=request.user,action=f'Moderated {count} public responses as {status}',object_reference='StoryComment bulk action')
    @admin.action(description='Approve selected responses')
    def approve(self,r,q): self._set(r,q,'approved',True)
    @admin.action(description='Reject selected responses')
    def reject(self,r,q): self._set(r,q,'rejected')
    @admin.action(description='Remove selected responses')
    def remove(self,r,q): self._set(r,q,'removed',False,timezone.now())
    @admin.action(description='Restore selected responses to approved')
    def restore(self,r,q): self._set(r,q,'approved',True)
    @admin.action(description='Mark selected responses as spam')
    def mark_spam(self,r,q): self._set(r,q,'spam')
    @admin.action(description='Lock selected threads')
    def lock_threads(self,r,q): q.update(thread_locked=True)

@admin.register(CommentReport)
class CommentReportAdmin(admin.ModelAdmin):
    list_display=('comment','reason','status','created_at')
    list_filter=('reason','status')
    readonly_fields=('comment','reason','details','session_key_hash','created_at','updated_at')

admin.site.register([UserProfile, ListenerProfile, ConversationMessage, StoryReaction, CommentReaction, AccountabilityEvent, EvidenceDocument, PublicQuestion, PromiseTracker, AuthorityResponse, SupportResource, VolunteerApplication, AuditLog])
admin.site.site_header = 'Unmute India moderation'
admin.site.site_title = 'Unmute India Staff'
admin.site.index_title = 'Moderation and platform operations'

# Register your models here.
