(()=>{
  const csrf=()=>document.querySelector('[name=csrfmiddlewaretoken]')?.value||'';
  document.querySelectorAll('[data-reaction-form]').forEach(form=>form.addEventListener('submit',async e=>{
    e.preventDefault(); const button=form.querySelector('button'); if(button.disabled)return; button.disabled=true;
    try{const body=new FormData(form);body.set('json','1');const r=await fetch(form.action,{method:'POST',headers:{'X-Requested-With':'XMLHttpRequest'},body});const data=await r.json();if(!r.ok)throw Error();button.setAttribute('aria-pressed',String(data.active));button.classList.toggle('active',data.active);button.querySelector('[data-reaction-count]').textContent=data.count}catch{button.setAttribute('aria-label','Could not update support. Try again.')}finally{button.disabled=false}
  }));
  const formatTime=value=>{const seconds=Math.max(0,Math.floor(value||0));return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`};
  document.querySelectorAll('[data-video-player]').forEach(player=>{
    const video=player.querySelector('video'),play=player.querySelector('.video-play'),mute=player.querySelector('.video-mute'),bar=player.querySelector('.video-progress i'),time=player.querySelector('.video-time');
    const sync=()=>{const playing=!video.paused&&!video.ended;player.classList.toggle('is-playing',playing);play.textContent=playing?'Ⅱ':'▶';play.setAttribute('aria-label',playing?'Pause video':'Play video');bar.style.width=`${video.duration?video.currentTime/video.duration*100:0}%`;time.textContent=formatTime(video.currentTime)};
    const toggle=()=>video.paused?video.play():video.pause();
    play.addEventListener('click',e=>{e.stopPropagation();toggle()});video.addEventListener('click',e=>{e.stopPropagation();toggle()});
    mute.addEventListener('click',e=>{e.stopPropagation();video.muted=!video.muted;mute.classList.toggle('is-unmuted',!video.muted);mute.setAttribute('aria-pressed',String(video.muted));mute.setAttribute('aria-label',video.muted?'Unmute video':'Mute video');mute.querySelector('span').textContent=video.muted?'⌁':'♪';mute.querySelector('b').textContent=video.muted?'Muted':'Sound on'});
    video.addEventListener('timeupdate',sync);video.addEventListener('play',sync);video.addEventListener('pause',sync);video.addEventListener('ended',sync);
  });
  document.querySelectorAll('.video-story-card').forEach(card=>{
    card.addEventListener('click',e=>{if(!e.target.closest('a,button,form,[data-video-player]'))location.href=card.dataset.detailUrl});
    card.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target===card){e.preventDefault();location.href=card.dataset.detailUrl}});
  });
  const overlay=document.querySelector('[data-comments-overlay]'); if(!overlay)return;
  const modal=overlay.querySelector('.comments-modal'),list=overlay.querySelector('[data-comments-list]'),status=overlay.querySelector('[data-comments-status]'),count=overlay.querySelector('[data-comments-count]'),compose=overlay.querySelector('[data-comment-compose]'),more=overlay.querySelector('[data-comments-more]');
  let storyId=null,page=1,lastFocus=null;
  const esc=s=>{const d=document.createElement('div');d.textContent=s;return d.innerHTML};
  const render=c=>`<article class="response"><header><b>${esc(c.name)}</b><time>${esc(c.created)}</time></header><p>${esc(c.body)}</p><div><button data-comment-like="${c.id}">♡ Support ${c.likes}</button><button data-reply="${c.id}">Reply</button><button data-report="${c.id}">Report</button></div>${c.replies.map(r=>`<article class="reply"><header><b>${esc(r.name)}</b><time>${esc(r.created)}</time></header><p>${esc(r.body)}</p><button data-comment-like="${r.id}">♡ Support ${r.likes}</button><button data-report="${r.id}">Report</button></article>`).join('')}</article>`;
  async function load(reset=false){if(reset){page=1;list.innerHTML='';status.textContent='Loading supportive responses…'}const r=await fetch(`/stories/${storyId}/comments/?page=${page}`);const data=await r.json();status.textContent='';count.textContent=`${data.count} supportive response${data.count===1?'':'s'}`;if(!data.comments.length&&page===1)list.innerHTML='<p>No supportive responses yet.</p>';else list.insertAdjacentHTML('beforeend',data.comments.map(render).join(''));more.hidden=!data.has_next;compose.hidden=data.comments_mode==='none';if(data.comments_mode==='none')status.textContent='Comments are disabled for this post.'}
  function open(button){lastFocus=button;storyId=button.dataset.story;overlay.hidden=false;document.body.classList.add('modal-open');overlay.querySelector('h2').textContent=button.dataset.title||'Supportive responses';overlay.querySelector('[data-comments-close]').focus();load(true)}
  function close(){overlay.hidden=true;document.body.classList.remove('modal-open');lastFocus?.focus()}
  document.addEventListener('click',async e=>{
    const opener=e.target.closest('[data-comments-open]');if(opener)return open(opener);
    if(e.target.closest('[data-comments-close]')||e.target===overlay)return close();
    const reply=e.target.closest('[data-reply]');if(reply){compose.parent.value=reply.dataset.reply;compose.querySelector('textarea').focus();status.textContent='Replying to this response. Replies are one level deep.';return}
    const like=e.target.closest('[data-comment-like]');if(like){like.disabled=true;try{const r=await fetch(`/comments/${like.dataset.commentLike}/react/`,{method:'POST',headers:{'X-CSRFToken':csrf()}});const d=await r.json();like.textContent=`${d.active?'♥':'♡'} Support ${d.count}`}finally{like.disabled=false}return}
    const report=e.target.closest('[data-report]');if(report){const reason=prompt('Report reason: harassment, privacy, unsafe, spam, hate, or other');if(!reason)return;const body=new URLSearchParams({reason});const r=await fetch(`/comments/${report.dataset.report}/report/`,{method:'POST',headers:{'X-CSRFToken':csrf(),'Content-Type':'application/x-www-form-urlencoded'},body});const d=await r.json();status.textContent=d.message||'Unable to send report.'}
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!overlay.hidden)close();if(e.key==='Tab'&&!overlay.hidden){const f=[...modal.querySelectorAll('button:not([hidden]),input,textarea')].filter(x=>!x.disabled);if(e.shiftKey&&document.activeElement===f[0]){e.preventDefault();f.at(-1).focus()}else if(!e.shiftKey&&document.activeElement===f.at(-1)){e.preventDefault();f[0].focus()}}});
  more.addEventListener('click',()=>{page++;load()});
  compose.addEventListener('submit',async e=>{e.preventDefault();const button=compose.querySelector('[type=submit]');button.disabled=true;const r=await fetch(`/stories/${storyId}/comment/`,{method:'POST',body:new FormData(compose)});const d=await r.json();status.textContent=d.message;if(r.ok){compose.reset();compose.parent.value='';await load(true);status.textContent=d.message;const opener=document.querySelector(`[data-comments-open][data-story="${storyId}"] span`);if(opener)opener.textContent=String(Number(opener.textContent||0)+1)}button.disabled=false});
})();
