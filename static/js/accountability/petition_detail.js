const form = document.querySelector('[data-petition-form]');

if (form) {
  const name = form.querySelector('[name=name]');
  const email = form.querySelector('[name=email]');
  const role = form.querySelector('[name=supporter_type]');
  const consent = form.querySelector('[name=consent]');
  const button = form.querySelector('[type=submit]');
  const response = form.querySelector('.form-response');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
  const validEmail = value => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
  const showError = (field, message) => {
    const target = form.querySelector(`[data-error="${field}"]`);
    if (target) target.textContent = message;
  };
  const validate = (show = false) => {
    const checks = {name: !!name.value.trim(), email: validEmail(email.value), supporter_type: !!role.value, consent: consent.checked};
    button.disabled = !Object.values(checks).every(Boolean);
    if (show) {
      showError('name', checks.name ? '' : 'Please enter your name.');
      showError('email', checks.email ? '' : 'Enter a valid email address.');
      showError('supporter_type', checks.supporter_type ? '' : 'Select your role.');
      showError('consent', checks.consent ? '' : 'Please confirm your consent.');
    }
    return !button.disabled;
  };
  form.addEventListener('input', () => validate());
  form.addEventListener('change', () => validate());
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!validate(true)) return;
    button.disabled = true;
    button.textContent = 'Sending Confirmation…';
    response.className = 'form-response';
    try {
      const result = await fetch(location.href, {method: 'POST', body: new FormData(form), headers: {'X-Requested-With': 'XMLHttpRequest'}});
      const data = await result.json();
      response.textContent = data.message || 'Please check the form and try again.';
      response.className = `form-response show${data.ok ? '' : ' error'}`;
      if (data.ok) {
        button.textContent = 'Check Your Email';
        form.reset();
      } else {
        button.textContent = 'Add My Support';
        validate();
        if (data.pending && data.resend_url) {
          const pendingEmail = email.value.trim();
          const resend = document.createElement('button');
          resend.type = 'button'; resend.className = 'resend-link'; resend.textContent = 'Resend Verification Email';
          resend.addEventListener('click', async () => {
            resend.disabled = true; resend.textContent = 'Sending…';
            const payload = new FormData(); payload.append('email', pendingEmail); payload.append('csrfmiddlewaretoken', csrf);
            const sent = await fetch(data.resend_url, {method: 'POST', body: payload});
            const sentData = await sent.json(); response.textContent = sentData.message; resend.remove();
          });
          response.append(document.createElement('br'), resend);
        }
      }
    } catch (error) {
      response.textContent = 'We could not submit this right now. Please try again.';
      response.className = 'form-response show error';
      button.textContent = 'Add My Support'; validate();
    }
  });
  validate();
}

document.querySelectorAll('[data-share-url]').forEach(button => button.addEventListener('click', async () => {
  const url = button.dataset.shareUrl || location.href;
  try {
    if (navigator.share) await navigator.share({title: document.title, url});
    else { await navigator.clipboard.writeText(url); button.textContent = 'Link copied'; }
  } catch (error) {}
}));

requestAnimationFrame(() => document.querySelectorAll('.goal-track i').forEach(bar => {
  bar.style.width = bar.style.getPropertyValue('--progress');
}));
