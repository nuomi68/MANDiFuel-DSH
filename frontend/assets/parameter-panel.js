const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// All labels, identifiers, units, ranges and options come from the agent schema.
// This renderer knows input types, not application parameters or shape names.
export function parameterMarkup(control,value,prefix=''){
 const c=control,id=escape(prefix+'display-'+c.id),label=escape(c.label),unit=c.unit?` <small class="parameter-unit">${escape(c.unit)}</small>`:'',help=c.help?`<small class="parameter-help">${escape(c.help)}</small>`:'';
 let input;
 if(c.type==='toggle')input=`<input id="${id}" data-control="${escape(c.id)}" type="checkbox" ${value?'checked':''}>`;
 else if(c.type==='select')input=`<select id="${id}" data-control="${escape(c.id)}">${Array.isArray(value)?'<option selected disabled>自定义色带</option>':''}${(c.options||[]).map(o=>`<option value="${escape(o.value)}" ${value===o.value?'selected':''}>${escape(o.label)}</option>`).join('')}</select>`;
 else input=`<input id="${id}" data-control="${escape(c.id)}" type="${['range','color','number','text'].includes(c.type)?c.type:'text'}" value="${escape(value??'')}" ${c.min!==undefined?`min="${c.min}"`:''} ${c.max!==undefined?`max="${c.max}"`:''} ${['number','range'].includes(c.type)?`step="${c.step??'any'}"`:''}>`;
 if(c.type==='range')return `<div class="setting-slider"><label for="${id}"><span>${label}${unit}</span><output id="${escape(prefix)}output-${escape(c.id)}" data-control-output="${escape(c.id)}">${escape(value)}</output></label>${input}${help}</div>`;
 return `<label class="setting-row" for="${id}"><span>${label}${unit}${help}</span>${input}</label>`;
}

export function renderParameterPanel(container,controls,valueFor,prefix=''){
 let group=null;
 container.innerHTML=controls.map(c=>{
  let heading='';if(c.group&&c.group!==group){group=c.group;heading=`<h3 class="parameter-control-group">${escape(group)}</h3>`;}
  return heading+parameterMarkup(c,valueFor(c),prefix);
 }).join('')||'<p class="setting-group-empty">当前没有需要调整的参数</p>';
}
