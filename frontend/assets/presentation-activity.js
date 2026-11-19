export function presentationActivity(task){
 if(!task||task.draft)return{active:false,state:'idle',label:''};
 const computing=['queued','starting','running','importing'].includes(task.status);
 const presenting=['queued','running','waiting'].includes(task.presenter?.state);
 return{active:computing||presenting,state:computing?'computing':presenting?task.presenter.state:'idle',label:''};
}

// Temporary end-of-results placeholders; existing result cards stay untouched.
export class PresentationActivity{
 constructor(host,issue){this.host=host;this.issue=issue;}
 update(task){
  const activity=presentationActivity(task);
  this.host.hidden=!activity.active;
  this.host.dataset.state=activity.state;
  this.host.setAttribute('aria-busy',String(activity.active));
  if(this.issue){
   const status=task?.presenter?.state;
   const show=!task?.draft&&['error','warning'].includes(status);
   this.issue.hidden=!show;
   this.issue.textContent=show?[status==='error'?'展示未完成':'展示待确认',task.presenter.message].filter(Boolean).join(' · '):'';
  }
 }
}
