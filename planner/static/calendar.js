// Side-by-side lanes preserve access to overlapping class cards.
document.querySelectorAll('.time-day .time-body').forEach(day=>{
 const events=[...day.querySelectorAll('.time-event')].sort((a,b)=>+a.dataset.start-+b.dataset.start);
 let group=[],end=-1;
 function layout(){let lanes=[];for(const e of group){let lane=lanes.findIndex(t=>t<=+e.dataset.start);if(lane<0)lane=lanes.length;lanes[lane]=+e.dataset.end;e.dataset.lane=lane;}
 for(const e of group){e.style.left=(+e.dataset.lane*100/lanes.length)+'%';e.style.width=(100/lanes.length)+'%';}}
 for(const e of events){if(+e.dataset.start>=end){layout();group=[];end=-1;}group.push(e);end=Math.max(end,+e.dataset.end);}layout();
});
const scroll=document.querySelector('.timeline-scroll');if(scroll){const starts=[...scroll.querySelectorAll('[data-start]')].map(e=>+e.dataset.start);scroll.scrollTop=Math.max(0,(starts.length?Math.min(480,...starts):480)/60*64);}
