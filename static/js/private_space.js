document.addEventListener('DOMContentLoaded',()=>{
  const formatAudioTime=value=>{
    if(!Number.isFinite(value))return '--:--';
    const seconds=Math.max(0,Math.floor(value));
    return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
  };
  document.querySelectorAll('[data-space-audio]').forEach(player=>{
    const audio=player.querySelector('audio');
    const play=player.querySelector('[data-audio-play]');
    const mute=player.querySelector('[data-audio-mute]');
    const progress=player.querySelector('[data-audio-progress]');
    const current=player.querySelector('[data-audio-current]');
    const duration=player.querySelector('[data-audio-duration]');
    const sync=()=>{
      play.textContent=audio.paused?'▶':'Ⅱ';
      play.setAttribute('aria-label',audio.paused?'Play audio':'Pause audio');
      current.textContent=formatAudioTime(audio.currentTime);
      duration.textContent=formatAudioTime(audio.duration);
      if(!progress.matches(':active'))progress.value=audio.duration?Math.round(audio.currentTime/audio.duration*1000):0;
    };
    play.addEventListener('click',()=>{
      document.querySelectorAll('[data-space-audio] audio').forEach(other=>{if(other!==audio)other.pause()});
      if(audio.paused)audio.play().catch(()=>{});else audio.pause();
    });
    mute.addEventListener('click',()=>{
      audio.muted=!audio.muted;
      mute.textContent=audio.muted?'×':'♪';
      mute.setAttribute('aria-pressed',String(audio.muted));
      mute.setAttribute('aria-label',audio.muted?'Unmute audio':'Mute audio');
    });
    progress.addEventListener('input',()=>{if(audio.duration)audio.currentTime=Number(progress.value)/1000*audio.duration});
    ['loadedmetadata','durationchange','timeupdate','play','pause','ended'].forEach(name=>audio.addEventListener(name,sync));
    sync();
  });
  document.querySelectorAll('[data-space-dialog-open]').forEach(button=>{
    button.addEventListener('click',()=>{
      const dialog=document.getElementById(button.dataset.spaceDialogOpen);
      if(dialog?.showModal) dialog.showModal();
    });
  });
  document.querySelectorAll('.space-dialog').forEach(dialog=>{
    dialog.querySelector('[data-space-dialog-close]')?.addEventListener('click',()=>dialog.close());
    dialog.addEventListener('click',event=>{
      if(event.target===dialog) dialog.close();
    });
  });
  const config=window.unmuteMySpace;
  const mount=document.querySelector('#my-space-google');
  if(!config||!mount) return;
  const status=document.querySelector('[data-space-status]');
  const csrf=document.querySelector('[data-space-sync-token] input[name="csrfmiddlewaretoken"]')?.value||'';
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
