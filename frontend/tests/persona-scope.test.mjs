import test from 'node:test';
import assert from 'node:assert/strict';
import {apply} from '../../dsh/mandifuel-shell-env.mjs';
test('solver persona replaces interactive defaults and preserves private presentation roles',async()=>{
 const hooks={};apply({on:(name,fn)=>hooks[name]=fn,systemPrompt:{section(){}},shellEnv:{register(){}}});
 const original={sections:[{name:'deployment:persona',text:'private UI role'}]};
 const privateResult=await hooks['system-prompt/assemble'](original,{agent:{session:{header:{origin:'subagent'}}}},async()=>original);
 assert.equal(privateResult.sections[0].text,'private UI role');
 const main=await hooks['system-prompt/assemble'](original,{agent:{session:{header:{origin:'interactive'}}}},async()=>original);
 assert.match(main.sections[0].text,/OFFBEAT 计算运行助手/);
});
