export function presentationActivity(task){
 if(!task||task.draft)return{active:false,state:'idle',label:''};
 const computing=['queued','starting','running','importing'].includes(task.status);
 const presenting=['queued','running','waiting'].includes(task.presenter?.state);
 return{active:computing||presenting,state:computing?'computing':presenting?task.presenter.state:'idle',label:''};
}

// Temporary end-of-results placeholders; existing result cards stay untouched.
export class PresentationActivity{
 constructor(host){this.host=host;}
 update(task){
  const activity=presentationActivity(task);
  this.host.hidden=!activity.active;
  this.host.dataset.state=activity.state;
  this.host.setAttribute('aria-busy',String(activity.active));
 }
}
