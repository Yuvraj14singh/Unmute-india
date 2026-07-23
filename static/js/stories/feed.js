(()=>{
  const csrf=()=>document.querySelector('[name=csrfmiddlewaretoken]')?.value||'';
  const esc=value=>{const node=document.createElement('div');node.textContent=value||'';return node.innerHTML};
  const formatTime=value=>{const seconds=Math.max(0,Math.floor(value||0));return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`};

  document.querySelectorAll('[data-reaction-form]').forEach(form=>form.addEventListener('submit',async event=>{
    event.preventDefault();const button=form.querySelector('button');if(button.disabled)return;button.disabled=true;
    try{const body=new FormData(form);body.set('json','1');const response=await fetch(form.action,{method:'POST',headers:{'X-Requested-With':'XMLHttpRequest'},body});const data=await response.json();if(!response.ok)throw Error();button.setAttribute('aria-pressed',String(data.active));button.classList.toggle('active',data.active);button.querySelector('[data-reaction-count]').textContent=data.count}finally{button.disabled=false}
  }));

  document.querySelectorAll('[data-video-player]').forEach(player=>{
    const video=player.querySelector('video'),play=player.querySelector('.video-play'),mute=player.querySelector('.video-mute'),bar=player.querySelector('.video-progress i'),time=player.querySelector('.video-time');
    const sync=()=>{const playing=!video.paused&&!video.ended;player.classList.toggle('is-playing',playing);play.textContent=playing?'Ⅱ':'▶';play.setAttribute('aria-label',playing?'Pause video':'Play video');bar.style.width=`${video.duration?video.currentTime/video.duration*100:0}%`;time.textContent=formatTime(video.currentTime)};
    const toggle=()=>video.paused?video.play():video.pause();
    play.addEventListener('click',event=>{event.stopPropagation();toggle()});video.addEventListener('click',event=>{event.stopPropagation();toggle()});
    mute.addEventListener('click',event=>{event.stopPropagation();video.muted=!video.muted;mute.classList.toggle('is-unmuted',!video.muted);mute.setAttribute('aria-pressed',String(video.muted));mute.setAttribute('aria-label',video.muted?'Unmute video':'Mute video');mute.querySelector('span').textContent=video.muted?'⌁':'♪';mute.querySelector('b').textContent=video.muted?'Muted':'Sound on'});
    ['timeupdate','play','pause','ended'].forEach(name=>video.addEventListener(name,sync));
  });
  document.querySelectorAll('.video-story-card').forEach(card=>{
    card.addEventListener('click',event=>{if(!event.target.closest('a,button,form,[data-video-player]'))location.href=card.dataset.detailUrl});
    card.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target===card){event.preventDefault();location.href=card.dataset.detailUrl}});
  });

  const overlay=document.querySelector('[data-comments-overlay]');if(!overlay)return;
  const modal=overlay.querySelector('.comments-modal'),scroll=overlay.querySelector('.comments-scroll'),list=overlay.querySelector('[data-comments-list]'),status=overlay.querySelector('[data-comments-status]'),count=overlay.querySelector('[data-comments-count]'),compose=overlay.querySelector('[data-comment-compose]'),more=overlay.querySelector('[data-comments-more]'),replyBox=overlay.querySelector('[data-reply-context]'),reportSheet=overlay.querySelector('[data-report-sheet]'),reportForm=overlay.querySelector('[data-report-form]');
  let storyId=null,page=1,lastFocus=null,reportFocus=null,submitting=false;

  const responseMarkup=comment=>`<article class="response" data-comment="${comment.id}"><div class="response-main"><div class="response-avatar" aria-hidden="true">${esc(comment.name).charAt(0).toUpperCase()||'A'}</div><div class="response-content"><header><b>${esc(comment.name)}</b><time>${esc(comment.created)}</time></header><p>${esc(comment.body)}</p><div class="response-actions"><button data-comment-like="${comment.id}" aria-pressed="false">♡ Support <span>${comment.likes}</span></button><button data-reply="${comment.id}" data-reply-name="${esc(comment.name)}">Reply</button><button data-report="${comment.id}">Report</button></div></div></div>${comment.replies.length?`<div class="reply-thread">${comment.replies.map(reply=>`<article class="reply" data-comment="${reply.id}"><div class="response-avatar" aria-hidden="true">${esc(reply.name).charAt(0).toUpperCase()||'A'}</div><div class="response-content"><header><b>${esc(reply.name)}</b><time>${esc(reply.created)}</time></header><p>${esc(reply.body)}</p><div class="response-actions"><button data-comment-like="${reply.id}" aria-pressed="false">♡ Support <span>${reply.likes}</span></button><span class="reply-thread-label">Thread reply</span><button data-report="${reply.id}">Report</button></div></div></article>`).join('')}</div>`:''}</article>`;

  async function load(reset=false){
    if(reset){page=1;list.innerHTML='<div class="comments-skeleton"><i></i><i></i><i></i></div>';status.textContent='Loading supportive responses…'}
    try{const response=await fetch(`/stories/${storyId}/comments/?page=${page}`);const data=await response.json();if(!response.ok)throw Error();if(reset)list.innerHTML='';status.textContent='';count.textContent=`${data.count} response${data.count===1?'':'s'}`;if(!data.comments.length&&page===1)list.innerHTML='<div class="comments-empty"><span>◇</span><p>No supportive responses yet.</p><small>You can be the first to respond with care.</small></div>';else list.insertAdjacentHTML('beforeend',data.comments.map(responseMarkup).join(''));more.hidden=!data.has_next;compose.hidden=data.comments_mode==='none';if(data.comments_mode==='none')status.textContent='Comments are disabled for this post.'}
    catch{status.textContent='Responses could not be loaded. Please try again.'}
  }
  function setContext(button){
    overlay.querySelector('[data-comments-format]').textContent=button.dataset.format||'Post';
    overlay.querySelector('#comments-title').textContent=button.dataset.title||'Supportive responses';
    overlay.querySelector('[data-comments-author]').textContent=button.dataset.author||'Anonymous student';
    const context=overlay.querySelector('[data-comments-context]'),format=(button.dataset.format||'').toLowerCase(),media=button.dataset.media,excerpt=button.dataset.excerpt;
    if(format==='voice'&&media)context.innerHTML=`<audio controls preload="metadata" src="${esc(media)}"></audio>`;
    else if(format==='video'&&media)context.innerHTML=`<div class="comments-video-context"><video muted preload="metadata" src="${esc(media)}"></video><span>▶ Video message</span></div>`;
    else context.innerHTML=`<p>${esc(excerpt)}</p>`;
    context.hidden=!(media||excerpt);
  }
  function cancelReply(){compose.parent.value='';replyBox.hidden=true;replyBox.querySelector('[data-reply-name]').textContent='Anonymous student'}
  function open(button){lastFocus=button;storyId=button.dataset.story;setContext(button);cancelReply();overlay.hidden=false;document.body.classList.add('modal-open');overlay.querySelector('[data-comments-close]').focus();load(true)}
  function close(){if(!reportSheet.hidden){closeReport();return}overlay.hidden=true;document.body.classList.remove('modal-open');cancelReply();lastFocus?.focus()}
  function openReport(button){reportFocus=button;reportForm.reset();reportForm.comment_id.value=button.dataset.report;reportSheet.hidden=false;reportSheet.querySelector('input[name=reason]').focus()}
  function closeReport(){reportSheet.hidden=true;reportFocus?.focus()}

  document.addEventListener('click',async event=>{
    const opener=event.target.closest('[data-comments-open]');if(opener)return open(opener);
    if(event.target.closest('[data-comments-close]')||event.target===overlay)return close();
    if(event.target.closest('[data-reply-cancel]'))return cancelReply();
    const reply=event.target.closest('[data-reply]');if(reply){compose.parent.value=reply.dataset.reply;replyBox.hidden=false;replyBox.querySelector('[data-reply-name]').textContent=reply.dataset.replyName||'Anonymous student';compose.body.focus();return}
    const like=event.target.closest('[data-comment-like]');if(like){if(like.disabled)return;like.disabled=true;const old=Number(like.querySelector('span').textContent);const wasActive=like.getAttribute('aria-pressed')==='true';like.setAttribute('aria-pressed',String(!wasActive));like.querySelector('span').textContent=String(old+(wasActive?-1:1));try{const response=await fetch(`/comments/${like.dataset.commentLike}/react/`,{method:'POST',headers:{'X-CSRFToken':csrf()}});const data=await response.json();if(!response.ok)throw Error();like.setAttribute('aria-pressed',String(data.active));like.querySelector('span').textContent=data.count;like.firstChild.textContent=`${data.active?'♥':'♡'} Support `}catch{like.setAttribute('aria-pressed',String(wasActive));like.querySelector('span').textContent=old}finally{like.disabled=false}return}
    const report=event.target.closest('[data-report]');if(report)return openReport(report);
    if(event.target.closest('[data-report-close]'))return closeReport();
  });
  overlay.querySelector('[data-name-toggle]').addEventListener('click',event=>{const row=overlay.querySelector('[data-name-row]'),show=row.hidden;row.hidden=!show;event.currentTarget.setAttribute('aria-expanded',String(show));event.currentTarget.textContent=show?'Hide display name':'Add display name';if(show)row.querySelector('input').focus()});
  more.addEventListener('click',()=>{page++;load()});
  compose.body.addEventListener('input',()=>{compose.body.style.height='auto';compose.body.style.height=`${Math.min(compose.body.scrollHeight,112)}px`});
  compose.body.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();compose.requestSubmit()}});
  compose.addEventListener('submit',async event=>{event.preventDefault();if(submitting)return;submitting=true;const button=compose.querySelector('[type=submit]'),label=button.querySelector('span');button.disabled=true;label.textContent='Sending…';try{const response=await fetch(`/stories/${storyId}/comment/`,{method:'POST',body:new FormData(compose)});const data=await response.json();if(!response.ok)throw Error();const parent=compose.parent.value;compose.body.value='';compose.body.style.height='auto';cancelReply();await load(true);status.textContent=data.approved?(parent?'Your reply is now visible.':'Your response is now visible.'):'Your response was sent for moderation.';const opener=document.querySelector(`[data-comments-open][data-story="${storyId}"] span`);if(opener)opener.textContent=String(Number(opener.textContent||0)+1);scroll.scrollTop=parent?scroll.scrollHeight:0}catch{status.textContent='Your response could not be sent. Please check it and try again.'}finally{submitting=false;button.disabled=false;label.textContent='Send'}});
  reportForm.addEventListener('submit',async event=>{event.preventDefault();const button=reportForm.querySelector('[type=submit]');button.disabled=true;try{const body=new FormData(reportForm);const id=body.get('comment_id');body.delete('comment_id');const response=await fetch(`/comments/${id}/report/`,{method:'POST',headers:{'X-CSRFToken':csrf()},body});const data=await response.json();if(!response.ok)throw Error();closeReport();status.textContent=data.message}catch{reportSheet.querySelector('p').textContent='The report could not be sent. Please try again.'}finally{button.disabled=false}});
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&!overlay.hidden)return close();
    if(event.key==='Tab'&&!overlay.hidden){const scope=reportSheet.hidden?modal:reportSheet;const focusable=[...scope.querySelectorAll('button:not([hidden]):not([disabled]),input:not([hidden]),textarea,a[href]')].filter(node=>node.offsetParent!==null);if(!focusable.length)return;if(event.shiftKey&&document.activeElement===focusable[0]){event.preventDefault();focusable.at(-1).focus()}else if(!event.shiftKey&&document.activeElement===focusable.at(-1)){event.preventDefault();focusable[0].focus()}}
  });
})();
