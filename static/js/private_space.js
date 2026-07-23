document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-space-tab]').forEach(button=>{
    button.addEventListener('click',()=>{
      document.querySelectorAll('[data-space-tab]').forEach(item=>item.classList.toggle('active',item===button));
      document.querySelectorAll('[data-space-panel]').forEach(panel=>panel.hidden=panel.dataset.spacePanel!==button.dataset.spaceTab);
    });
  });
  const config=window.unmuteMySpace;
  const mount=document.querySelector('#my-space-google');
  if(!config||!mount) return;
  const status=document.querySelector('[data-space-status]');
  const csrf=document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1]||'';
  const draw=()=>{
    if(!window.google?.accounts?.id) return setTimeout(draw,100);
    google.accounts.id.initialize({client_id:config.clientId,callback:async({credential})=>{
      const consent=document.querySelector('[data-sync-consent]');
      if(!consent.checked){status.textContent='Choose “Enable private sync” first.';return;}
      status.textContent='Restoring your private activity…';
      const body=new URLSearchParams({credential,sync_consent:'1'});
      try{
        const response=await fetch(config.url,{method:'POST',headers:{'X-CSRFToken':decodeURIComponent(csrf),'X-Requested-With':'XMLHttpRequest'},body});
        const contentType=response.headers.get('content-type')||'';
        if(!contentType.includes('application/json')){
          throw new Error(response.status===403?'Your secure session expired. Refresh this page and try again.':'Private activity could not be restored right now. Please try again.');
        }
        const data=await response.json();
        if(!response.ok) throw new Error(data.message||'Verification failed.');
        location.assign(data.redirect);
      }catch(error){status.textContent=error.message;}
    }});
    google.accounts.id.renderButton(mount,{theme:'outline',size:'large',width:Math.min(360,mount.clientWidth||360),text:'continue_with'});
  };
  draw();
});
