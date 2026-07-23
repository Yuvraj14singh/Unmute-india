(()=>{
  const sidebar=document.querySelector('#nav-sidebar');
  const table=sidebar?.querySelector('.module table');
  if(table){
    const rows=[...table.querySelectorAll('tr')];
    const groups={
      Authentication:['Users','Groups'],
      Listening:['Listening requests','Conversation messages','Listener profiles','Volunteer applications'],
      Stories:['Storys','Stories','Story comments','Story reactions','Comment reports','Comment reactions'],
      Accountability:['Petitions','Petition signatures','Accountability events','Public questions','Evidence documents','Promise trackers','Authority responses','Student demands'],
      System:['Audit logs','User profiles','Support resources']
    };
    const host=document.createElement('div');host.className='workspace-nav-groups';
    Object.entries(groups).forEach(([label,names])=>{
      const matching=rows.filter(row=>names.some(name=>row.textContent.trim().toLowerCase().startsWith(name.toLowerCase())));
      if(!matching.length)return;
      const details=document.createElement('details');details.open=matching.some(row=>row.classList.contains('current-model'));
      const summary=document.createElement('summary');summary.textContent=label;details.append(summary);
      const list=document.createElement('div');matching.forEach(row=>list.append(...row.children));details.append(list);host.append(details);
    });
    table.closest('.module').replaceWith(host);
  }
  const filter=document.querySelector('#changelist-filter');
  if(filter){
    const button=document.createElement('button');button.type='button';button.className='admin-filter-toggle';button.textContent='Filters';button.setAttribute('aria-expanded',String(innerWidth>1100));filter.before(button);
    button.addEventListener('click',()=>{filter.classList.toggle('filter-open');button.setAttribute('aria-expanded',String(filter.classList.contains('filter-open')))});
    filter.querySelectorAll('details').forEach(group=>{if(group.querySelector('.selected'))group.open=true});
  }
})();
