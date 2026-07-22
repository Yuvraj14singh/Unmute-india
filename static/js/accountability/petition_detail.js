const petitionForm = document.querySelector('[data-petition-form]');
let petitionTurnstileToken = '';
let googleInitialized = false;
let googleButtonRendered = false;
let googleLoadAttempts = 0;

const notifyVerificationChange = () => {
  window.dispatchEvent(new Event('petition-verification-change'));
};

window.petitionTurnstileReady = token => {
  if (!token || token === petitionTurnstileToken) return;
  petitionTurnstileToken = token;
  notifyVerificationChange();
};

window.petitionTurnstileExpired = () => {
  if (!petitionTurnstileToken) return;
  petitionTurnstileToken = '';
  notifyVerificationChange();
};

if (petitionForm) {
  const name = petitionForm.querySelector('[name=name]');
  const role = petitionForm.querySelector('[name=supporter_type]');
  const consent = petitionForm.querySelector('[name=consent]');
  const googleShell = petitionForm.querySelector('#google-signin-button');
  const guidance = petitionForm.querySelector('[data-guidance]');
  const status = petitionForm.querySelector('.form-response');
  const activeStep = document.querySelector('[data-active-step]');
  const steps = {
    details: document.querySelector('[data-step-details]'),
    human: document.querySelector('[data-step-human]'),
    google: document.querySelector('[data-step-google]'),
  };
  const clientId = petitionForm.dataset.googleClientId;
  let submitting = false;
  let googleReady = false;
  let currentUiState = '';

  name.setAttribute('aria-describedby', 'name-error');
  role.setAttribute('aria-describedby', 'role-error');
  consent.setAttribute('aria-describedby', 'consent-error');

  const showError = (field, message) => {
    const target = petitionForm.querySelector(`[data-error="${field}"]`);
    const control = field === 'name' ? name : field === 'supporter_type' ? role : field === 'consent' ? consent : null;
    if (target && target.textContent !== message) target.textContent = message;
    if (control) control.setAttribute('aria-invalid', String(Boolean(message)));
  };

  const state = () => ({
    name: Boolean(name.value.trim()),
    supporter_type: Boolean(role.value),
    consent: consent.checked,
    turnstile_token: Boolean(petitionTurnstileToken),
  });

  const validate = (show = false) => {
    const checks = state();
    const detailsComplete = checks.name && checks.supporter_type && checks.consent;
    const ready = detailsComplete && checks.turnstile_token && googleReady && !submitting;

    if (show) {
      showError('name', checks.name ? '' : 'Please enter your name.');
      showError('supporter_type', checks.supporter_type ? '' : 'Please select your role.');
      showError('consent', checks.consent ? '' : 'Please confirm your consent.');
      showError('turnstile_token', checks.turnstile_token ? '' : 'Please complete the human check.');
    }

    const nextUiState = [detailsComplete, checks.turnstile_token, googleReady, submitting].join(':');
    if (nextUiState === currentUiState) return ready;
    currentUiState = nextUiState;

    steps.details?.classList.toggle('is-complete', detailsComplete);
    steps.human?.classList.toggle('is-complete', checks.turnstile_token);
    steps.google?.classList.toggle('is-active', detailsComplete && checks.turnstile_token);
    googleShell.classList.toggle('is-disabled', !ready);
    googleShell.setAttribute('aria-disabled', String(!ready));

    if (!detailsComplete) {
      activeStep.textContent = 'Complete your details';
      guidance.textContent = 'Complete your details first.';
    } else if (!checks.turnstile_token) {
      activeStep.textContent = 'Complete human check';
      guidance.textContent = 'Complete the human check to continue.';
    } else if (!googleReady) {
      activeStep.textContent = 'Loading Google verification';
      guidance.textContent = 'Loading secure Google verification…';
    } else if (submitting) {
      activeStep.textContent = 'Verifying your support';
      guidance.textContent = 'Verifying your support…';
    } else {
      activeStep.textContent = 'Verify with Google';
      guidance.textContent = 'Continue with Google to add your support.';
    }
    return ready;
  };

  const resetTurnstile = () => {
    petitionTurnstileToken = '';
    currentUiState = '';
    if (window.turnstile) window.turnstile.reset();
    validate();
  };

  const renderSuccess = data => {
    petitionForm.hidden = true;
    document.querySelector('.support-progress')?.setAttribute('hidden', '');
    activeStep?.setAttribute('hidden', '');
    const panel = document.querySelector('[data-verified-success]');
    panel.hidden = false;
    panel.querySelector('[data-success-petition]').textContent = data.petition_title || '';
    panel.querySelector('[data-success-count]').textContent = `${data.verified_count} verified supporter${data.verified_count === 1 ? '' : 's'}`;
    panel.querySelector('[data-success-role]').textContent = data.role || 'Verified supporter';
    document.querySelector('[data-signature-count]').textContent = data.verified_count;
    document.querySelector('[data-signature-label]').textContent = `${data.verified_count} verified supporter${data.verified_count === 1 ? '' : 's'}`;
  };

  const submitCredential = async credential => {
    if (submitting || !validate(true)) return;
    submitting = true;
    currentUiState = '';
    validate();
    status.className = 'form-response';
    status.textContent = '';
    const payload = new FormData(petitionForm);
    payload.set('credential', credential);
    payload.set('turnstile_token', petitionTurnstileToken);
    try {
      const response = await fetch(petitionForm.action, {
        method: 'POST',
        body: payload,
        headers: {'X-Requested-With': 'XMLHttpRequest'},
      });
      const data = await response.json();
      if (data.ok && !data.duplicate) {
        renderSuccess(data);
      } else if (data.ok && data.duplicate) {
        document.querySelector('[data-signature-count]').textContent = data.verified_count;
        status.textContent = data.message;
        status.className = 'form-response show';
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
      currentUiState = '';
      validate();
    }
  };

  const showGoogleLoadError = () => {
    if (googleInitialized || googleButtonRendered) return;
    status.textContent = 'Google verification could not load. Please refresh and try again.';
    status.className = 'form-response show error';
    guidance.textContent = 'Google verification could not load.';
  };

  const initialiseGoogle = () => {
    if (googleInitialized || googleButtonRendered) return;
    if (!window.google?.accounts?.id) {
      googleLoadAttempts += 1;
      if (googleLoadAttempts >= 100) return showGoogleLoadError();
      window.setTimeout(initialiseGoogle, 100);
      return;
    }

    googleInitialized = true;
    window.google.accounts.id.initialize({
      client_id: clientId,
      ux_mode: 'popup',
      callback: response => {
        if (!response?.credential) {
          status.textContent = 'Google verification was not completed.';
          status.className = 'form-response show error';
          return;
        }
        submitCredential(response.credential);
      },
    });

    if (!googleButtonRendered) {
      window.google.accounts.id.renderButton(googleShell, {
        theme: 'outline',
        size: 'large',
        type: 'standard',
        shape: 'pill',
        text: 'continue_with',
        width: Math.min(360, Math.max(260, googleShell.clientWidth || 320)),
        click_listener: () => {
          status.className = 'form-response';
          status.textContent = '';
        },
      });
      googleButtonRendered = true;
    }

    googleReady = true;
    currentUiState = '';
    validate();
  };

  petitionForm.addEventListener('submit', event => event.preventDefault());
  petitionForm.addEventListener('input', () => validate());
  petitionForm.addEventListener('change', () => validate());
  window.addEventListener('petition-verification-change', () => validate());
  initialiseGoogle();
}

document.querySelectorAll('[data-share-url]').forEach(button => button.addEventListener('click', async () => {
  const url = button.dataset.shareUrl || location.href;
  try {
    if (navigator.share) await navigator.share({title: document.title, url});
    else {
      await navigator.clipboard.writeText(url);
      button.textContent = 'Link copied';
    }
  } catch (error) {}
}));

requestAnimationFrame(() => document.querySelectorAll('.goal-track i').forEach(bar => {
  bar.style.width = bar.style.getPropertyValue('--progress');
}));
