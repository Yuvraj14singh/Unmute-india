from django.contrib import admin
from .models import *

@admin.register(ListeningRequest)
class ListeningRequestAdmin(admin.ModelAdmin):
    list_display=('public_id','kind','status','anonymous','safety_flag','assigned_to','created_at')
    list_filter=('kind','status','anonymous','safety_flag')
    search_fields=('public_id','message')
    readonly_fields=('public_id','privacy','created_at','updated_at')
    list_editable=('status','assigned_to')
    date_hierarchy='created_at'
    ordering=('-safety_flag','-created_at')
    list_per_page=30

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

admin.site.register([UserProfile, ListenerProfile, ConversationMessage, StoryReaction, StoryComment, AccountabilityEvent, EvidenceDocument, PublicQuestion, PromiseTracker, AuthorityResponse, SupportResource, VolunteerApplication, AuditLog])
admin.site.site_header = 'Unmute India moderation'
admin.site.site_title = 'Unmute India Staff'
admin.site.index_title = 'Moderation and platform operations'

# Register your models here.
