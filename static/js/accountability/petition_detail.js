const petitionForm = document.querySelector('[data-petition-form]');
let petitionTurnstileToken = '';

window.petitionTurnstileReady = token => {
  petitionTurnstileToken = token;
  window.dispatchEvent(new Event('petition-verification-change'));
};
window.petitionTurnstileExpired = () => {
  petitionTurnstileToken = '';
  window.dispatchEvent(new Event('petition-verification-change'));
};

if (petitionForm) {
  const name = petitionForm.querySelector('[name=name]');
  const role = petitionForm.querySelector('[name=supporter_type]');
  const consent = petitionForm.querySelector('[name=consent]');
  const googleShell = petitionForm.querySelector('[data-google-button]');
  const guidance = petitionForm.querySelector('[data-guidance]');
  const status = petitionForm.querySelector('.form-response');
  const detailsStep = document.querySelector('[data-step-details]');
  const humanStep = document.querySelector('[data-step-human]');
  const googleStep = document.querySelector('[data-step-google]');
  const clientId = petitionForm.dataset.googleClientId;
  let submitting = false;
  let googleReady = false;

  const showError = (field, message) => {
    const target = petitionForm.querySelector(`[data-error="${field}"]`);
    if (target) target.textContent = message;
  };
  const valid = (show = false) => {
    const checks = {name: Boolean(name.value.trim()), supporter_type: Boolean(role.value), consent: consent.checked, turnstile_token: Boolean(petitionTurnstileToken)};
    const detailsReady = checks.name && checks.supporter_type && checks.consent;
    if (show) {
      showError('name', checks.name ? '' : 'Please enter your name.');
      showError('supporter_type', checks.supporter_type ? '' : 'Select your role.');
      showError('consent', checks.consent ? '' : 'Please confirm your consent.');
      showError('turnstile_token', checks.turnstile_token ? '' : 'Complete the security check.');
    }
    const ready = Object.values(checks).every(Boolean) && googleReady && !submitting;
    googleShell.classList.toggle('is-disabled', !ready);
    googleShell.setAttribute('aria-disabled', String(!ready));
    detailsStep?.classList.toggle('is-complete', detailsReady);
    humanStep?.classList.toggle('is-complete', checks.turnstile_token);
    detailsStep?.querySelector('small')?.replaceChildren(detailsReady ? 'Complete' : 'Pending');
    humanStep?.querySelector('small')?.replaceChildren(checks.turnstile_token ? 'Complete' : 'Pending');
    googleStep?.classList.toggle('is-ready', ready);
    googleStep?.querySelector('small')?.replaceChildren(ready ? 'Ready' : 'Not counted yet');
    if (!checks.name) guidance.textContent = 'Enter your name to begin.';
    else if (!checks.supporter_type) guidance.textContent = 'Select your role.';
    else if (!checks.consent) guidance.textContent = 'Confirm your consent to continue.';
    else if (!checks.turnstile_token) guidance.textContent = 'Complete the human check.';
    else if (!googleReady) guidance.textContent = 'Loading secure Google verification…';
    else guidance.textContent = 'Ready — continue with Google to add your support.';
    return ready;
  };
  const resetTurnstile = () => {
    petitionTurnstileToken = '';
    if (window.turnstile) window.turnstile.reset();
    valid();
  };
  const renderSuccess = data => {
    petitionForm.hidden = true;
    const panel = document.querySelector('[data-verified-success]');
    panel.hidden = false;
    panel.querySelector('[data-success-petition]').textContent = data.petition_title || document.title.split('|')[0].trim();
    panel.querySelector('[data-success-count]').textContent = `${data.verified_count} verified supporters`;
    panel.querySelector('[data-success-role]').textContent = data.role || 'Verified supporter';
    document.querySelector('[data-signature-count]').textContent = data.verified_count;
    document.querySelector('[data-signature-label]').textContent = `${data.verified_count} verified supporter${data.verified_count === 1 ? '' : 's'}`;
  };
  const submitCredential = async credential => {
    if (submitting || !valid(true)) return;
    submitting = true;
    googleShell.classList.add('is-disabled');
    guidance.textContent = 'Verifying and adding your support…';
    googleStep?.classList.add('is-working');
    googleStep?.querySelector('small')?.replaceChildren('Verifying…');
    status.textContent = '';
    const payload = new FormData(petitionForm);
    payload.set('credential', credential);
    payload.set('turnstile_token', petitionTurnstileToken);
    try {
      const response = await fetch(petitionForm.action, {method:'POST', body:payload, headers:{'X-Requested-With':'XMLHttpRequest'}});
      const data = await response.json();
      if (data.ok) {
        if (data.duplicate) {
          status.textContent = data.message;
          status.className = 'form-response show';
          document.querySelector('[data-signature-count]').textContent = data.verified_count;
        } else renderSuccess(data);
      } else {
        status.textContent = data.message || 'We could not verify your support right now. Your support has not been counted.';
        status.className = 'form-response show error';
        if (data.reset_turnstile) resetTurnstile();
      }
    } catch (error) {
      status.textContent = 'We could not verify your support right now. Your support has not been counted.';
      status.className = 'form-response show error';
      resetTurnstile();
    } finally {
      submitting = false;
      googleStep?.classList.remove('is-working');
      valid();
    }
  };
  const initialiseGoogle = () => {
    if (!window.google?.accounts?.id) return window.setTimeout(initialiseGoogle, 100);
    window.google.accounts.id.initialize({client_id:clientId, ux_mode:'popup', use_fedcm_for_button:true, callback:response => {
      guidance.textContent = 'Waiting for Google verification…';
      if (!response?.credential) {
        status.textContent = 'Google verification was not completed. You can try again.';
        status.className = 'form-response show error';
        return;
      }
      submitCredential(response.credential);
    }});
    window.google.accounts.id.renderButton(googleShell, {theme:'outline', size:'large', type:'standard', shape:'pill', text:'continue_with', width:320, click_listener:() => {
      guidance.textContent = 'Waiting for Google verification…';
      status.textContent = '';
    }});
    googleReady = true;
    valid();
  };
  petitionForm.addEventListener('submit', event => event.preventDefault());
  petitionForm.addEventListener('input', () => valid());
  petitionForm.addEventListener('change', () => valid());
  window.addEventListener('petition-verification-change', () => valid());
  initialiseGoogle();
}

document.querySelectorAll('[data-share-url]').forEach(button => button.addEventListener('click', async () => {
  const url = button.dataset.shareUrl || location.href;
  try {
    if (navigator.share) await navigator.share({title:document.title, url});
    else { await navigator.clipboard.writeText(url); button.textContent = 'Link copied'; }
  } catch (error) {}
}));

requestAnimationFrame(() => document.querySelectorAll('.goal-track i').forEach(bar => {
  bar.style.width = bar.style.getPropertyValue('--progress');
}));
