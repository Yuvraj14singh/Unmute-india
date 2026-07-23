from django import forms
from .models import ListeningRequest, PetitionSignature, PublicQuestion, VolunteerApplication

class ListeningRequestForm(forms.ModelForm):
    consent = forms.BooleanField(required=True, label='I understand this is private support, not an emergency service.')
    public_sharing_consent = forms.BooleanField(required=False, label='You may review this for anonymous public sharing. Nothing is published until staff approval and a privacy review.')
    class Meta:
        model = ListeningRequest
        fields = ['title','message','media','category','anonymous','wants_reply','support_preference','comment_preference','public_sharing_consent']
        widgets = {'message': forms.Textarea(attrs={'placeholder':'Write whatever is on your mind…','rows':9,'maxlength':'5000'}), 'support_preference': forms.RadioSelect, 'comment_preference': forms.RadioSelect}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['comment_preference'].required = False
        self.fields['comment_preference'].initial = 'support'
    def clean_media(self):
        file = self.cleaned_data.get('media')
        if file and file.size > 25 * 1024 * 1024:
            raise forms.ValidationError('Please choose a file smaller than 25 MB.')
        return file
    def clean(self):
        cleaned = super().clean()
        cleaned['comment_preference'] = cleaned.get('comment_preference') or 'support'
        media = cleaned.get('media')
        kind = getattr(self.instance, 'kind', '') or self.data.get('kind', '')
        if kind in ('audio','image','video') and not media:
            article = 'an' if kind in ('audio','image') else 'a'
            self.add_error('media', f'Please record or choose {article} {kind} file before submitting.')
        if media:
            ext = media.name.rsplit('.', 1)[-1].lower() if '.' in media.name else ''
            allowed = {'audio': {'mp3','m4a','wav','ogg','webm'}, 'image': {'jpg','jpeg','png','webp'}, 'video': {'webm','mp4','mov'}}
            if kind in allowed and ext not in allowed[kind]:
                self.add_error('media', 'This file format is not supported.')
        return cleaned

class VolunteerForm(forms.ModelForm):
    commitment = forms.BooleanField(
        required=True,
        label='I understand that this is a peer-support role, not counselling, and that applications are reviewed before any access is given.',
    )
    class Meta:
        model = VolunteerApplication
        fields = ['name','email','motivation']
        labels = {
            'name': 'Your name',
            'email': 'Email address',
            'motivation': 'Why would you like to volunteer?',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder':'Your name','autocomplete':'name'}),
            'email': forms.EmailInput(attrs={'placeholder':'you@example.com','autocomplete':'email'}),
            'motivation': forms.Textarea(attrs={'placeholder':'Tell us what draws you to this work and how you would listen responsibly…','rows':6}),
        }

class PublicQuestionForm(forms.ModelForm):
    class Meta:
        model = PublicQuestion
        fields = ['question','name','state','anonymous','consent']
        widgets = {'question': forms.Textarea(attrs={'rows':4,'placeholder':'Ask one clear question…'}), 'name':forms.TextInput(attrs={'placeholder':'Optional'}), 'state':forms.TextInput(attrs={'placeholder':'Optional'})}

class PetitionSignatureForm(forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    consent = forms.BooleanField(required=True, label='I confirm that I support this petition and agree to email verification.')
    class Meta:
        model = PetitionSignature
        fields = ['name','email','supporter_type','consent']
        widgets = {
            'name': forms.TextInput(attrs={'autocomplete':'name'}),
            'email': forms.EmailInput(attrs={'autocomplete':'email'}),
        }
    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name: raise forms.ValidationError('Please enter your name.')
        return name
    def clean_supporter_type(self):
        role = self.cleaned_data.get('supporter_type', '')
        if not role: raise forms.ValidationError('Select your role.')
        return role
    def clean_website(self):
        if self.cleaned_data.get('website'): raise forms.ValidationError('Invalid submission.')
        return ''


class GooglePetitionSupportForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'placeholder': 'Your name',
            'autocomplete': 'name',
        }),
    )
    supporter_type = forms.ChoiceField(
        choices=PetitionSignature.SUPPORTER_TYPES,
        widget=forms.Select(attrs={'aria-label': 'Your role'}),
    )
    consent = forms.BooleanField(required=True)
    credential = forms.CharField(required=True)
    turnstile_token = forms.CharField(required=True)
    # Honeypot: it must never be visible or browser-autofilled as a user field.
    website = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={
            'autocomplete': 'off',
            'tabindex': '-1',
            'aria-hidden': 'true',
        }),
    )

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError('Please enter your name.')
        return name

    def clean_supporter_type(self):
        role = self.cleaned_data['supporter_type']
        if not role:
            raise forms.ValidationError('Select your role.')
        return role

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Invalid submission.')
        return ''
