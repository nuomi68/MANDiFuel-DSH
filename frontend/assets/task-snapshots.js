// Both SSE subscriptions and recovery reads can deliver the same task.
// Persisted server versions keep delayed messages from reversing its lifecycle.
export class TaskSnapshots{
 constructor(){this.tasks=new Map();}
 accept(meta){
  const previous=this.tasks.get(meta.id);
  if(previous&&Number.isInteger(previous.stateVersion)&&(!Number.isInteger(meta.stateVersion)||meta.stateVersion<previous.stateVersion))return false;
  this.tasks.set(meta.id,meta);return true;
 }
 get(id){return this.tasks.get(id);}
}
