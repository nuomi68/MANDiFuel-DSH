export function fieldSummary(values){
 let min=Infinity,max=-Infinity;
 for(const value of values){min=Math.min(min,value);max=Math.max(max,value);}
 return {min,max,uniform:values.length>0&&min===max};
}
