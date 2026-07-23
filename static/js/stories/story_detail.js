document.querySelectorAll('.detail-media video').forEach(video=>{
  video.addEventListener('play',()=>{
    document.querySelectorAll('.detail-media video').forEach(other=>{
      if(other!==video)other.pause();
    });
  });
});
