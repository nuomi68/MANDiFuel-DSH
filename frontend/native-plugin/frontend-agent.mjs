import {readFileSync} from 'node:fs';
const root=new URL('../agent/',import.meta.url),skillRoot=new URL('skills/operate-workbench-front-end/',root);
export function readFrontendRole(){return readFileSync(new URL('ROLE.md',root),'utf8');}
export const SKILL={name:'operate-workbench-front-end',description:'观察当前页面，在授权插槽内操作模型、图表、表格和参数，并核验实际渲染。'};
const resources=new Set(['SKILL.md','references/slot-protocol.md','references/layout.md','references/data.md','references/rendering.md','references/evidence.md']);
export function readSkill(resource='SKILL.md'){
 if(!resources.has(resource))throw new Error('未注册的前端技能资源');
 return{name:SKILL.name,resource,text:readFileSync(new URL(resource,skillRoot),'utf8')};
}
export const AGENT_RESULT_SCHEMA={type:'object',properties:{
 status:{type:'string',enum:['applied','unchanged','pending','partial','blocked']},summary:{type:'string'},revision:{type:'string'},
 comparisonException:{type:'object',properties:{kind:{type:'string',enum:['requested-format','incomparable-data']},reason:{type:'string'}},required:['kind','reason'],additionalProperties:false},
},required:['status','summary'],additionalProperties:false};
