from django import forms
from .models import ListeningRequest, PetitionSignature, PublicQuestion, VolunteerApplication

class ListeningRequestForm(forms.ModelForm):
    consent = forms.BooleanField(required=True, label='I understand this is private support, not an emergency service.')
    class Meta:
        model = ListeningRequest
        fields = ['message','media','anonymous','wants_reply','support_preference']
        widgets = {'message': forms.Textarea(attrs={'placeholder':'Write whatever is on your mind…','rows':9}), 'support_preference': forms.RadioSelect}
    def clean_media(self):
        file = self.cleaned_data.get('media')
        if file and file.size > 25 * 1024 * 1024:
            raise forms.ValidationError('Please choose a file smaller than 25 MB.')
        return file

class VolunteerForm(forms.ModelForm):
    class Meta:
        model = VolunteerApplication
        fields = ['name','email','motivation']

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
