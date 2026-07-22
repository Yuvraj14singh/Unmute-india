const form = document.querySelector('[data-petition-form]');

if (form) {
  const name = form.querySelector('[name=name]');
  const email = form.querySelector('[name=email]');
  const role = form.querySelector('[name=supporter_type]');
  const consent = form.querySelector('[name=consent]');
  const button = form.querySelector('[type=submit]');
  const response = form.querySelector('.form-response');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
  let sending = false;
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
    if (sending || !validate(true)) return;
    sending = true;
    button.disabled = true;
    button.textContent = 'Sending verification email…';
    response.className = 'form-response';
    const submittedEmail = email.value.trim();
    try {
      const result = await fetch(location.href, {method: 'POST', body: new FormData(form), headers: {'X-Requested-With': 'XMLHttpRequest'}});
      const data = await result.json();
      response.textContent = data.ok
        ? `${data.message}\n\nSent to ${data.masked_email}. Your support will be counted after you verify your email.`
        : (data.message || 'Please check the form and try again.');
      response.className = `form-response show${data.ok ? '' : ' error'}`;
      if (data.ok) {
        button.textContent = 'Check Your Email';
        form.reset();
        const resend = document.createElement('button'); resend.type = 'button'; resend.className = 'resend-link';
        let remaining = Number(data.cooldown_seconds || 300);
        const paint = () => { resend.disabled = remaining > 0; resend.textContent = remaining > 0 ? `Resend available in ${Math.ceil(remaining / 60)} min` : 'Resend Verification Email'; };
        paint(); const timer = setInterval(() => { remaining -= 1; paint(); if (remaining <= 0) clearInterval(timer); }, 1000);
        resend.addEventListener('click', async () => { resend.disabled = true; resend.textContent = 'Sending…'; const payload = new FormData(); payload.append('email', submittedEmail); payload.append('csrfmiddlewaretoken', csrf); const sent = await fetch(data.resend_url, {method:'POST',body:payload}); const sentData = await sent.json(); response.firstChild.textContent = sentData.message; remaining = Number(sentData.cooldown_seconds || 300); paint(); });
        const back = document.createElement('a'); back.href = '#support'; back.textContent = 'Back to petition'; back.className = 'resend-link';
        response.append(document.createElement('br'), resend, ' ', back);
      } else {
        button.textContent = 'Add My Support';
        validate();
        if (data.pending && data.resend_url) {
          const pendingEmail = email.value.trim();
          const resend = document.createElement('button');
          resend.type = 'button'; resend.className = 'resend-link';
          let remaining = Number(data.cooldown_seconds || 0);
          const paint = () => { resend.disabled = remaining > 0; resend.textContent = remaining > 0 ? `Resend available in ${Math.ceil(remaining / 60)} min` : 'Resend Verification Email'; };
          paint(); const timer = remaining > 0 ? setInterval(() => { remaining -= 1; paint(); if (remaining <= 0) clearInterval(timer); }, 1000) : null;
          resend.addEventListener('click', async () => {
            resend.disabled = true; resend.textContent = 'Sending…';
            const payload = new FormData(); payload.append('email', pendingEmail); payload.append('csrfmiddlewaretoken', csrf);
            const sent = await fetch(data.resend_url, {method: 'POST', body: payload});
            const sentData = await sent.json(); response.textContent = sentData.message;
            if (sentData.ok) resend.remove(); else { remaining = Number(sentData.cooldown_seconds || 0); paint(); }
          });
          response.append(document.createElement('br'), resend);
        }
      }
    } catch (error) {
      response.textContent = 'We could not submit this right now. Please try again.';
      response.className = 'form-response show error';
      button.textContent = 'Add My Support'; validate();
    } finally { sending = false; }
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
