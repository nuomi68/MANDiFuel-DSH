"""Apply the user's revised solve-count policy without changing physical tasks."""
import re


def render_prompt(original, original_cap, effective_cap):
    if original_cap == 0 or effective_cap == original_cap:
        return original, {'mode': 'original', 'original_cap': original_cap, 'effective_cap': original_cap}
    parts=re.split(r'([。！？\n])',original);kept=[];removed=[]
    for i in range(0,len(parts),2):
        clause=parts[i];punct=parts[i+1] if i+1<len(parts) else ''
        count_clause=(bool(re.search(r'OFFBEAT|真实启动|真实求解|总启动|启动上限',clause,re.I))
                      and bool(re.search(r'最多|至多|上限|不超过|别超过|不超',clause))
                      and bool(re.search(r'\d+\s*次',clause)))
        fallback=bool(re.search(r'预算不够|预算不足|次数不够|次数不足|次数用完',clause))
        if count_clause:
            removed.append(clause+punct)
        elif fallback:
            removed.append(clause+punct)
            kept.append('若确认无法通过任务范围内的输入修复继续，保留已有数据并说明具体阻塞与未完成项。')
        else:kept.append(clause+punct)
    limit='不设次数上限' if effective_cap is None else f'最多 {effective_cap} 次'
    policy=(f'本轮运行政策：OFFBEAT 真实启动{limit}。可修复的输入错误应依据运行日志修改后继续求解，'
            '每次失败保留输入、日志和退出凭据；成功的结果复用。原题物理要求、源只读及任务写入边界保持。\n\n')
    return policy+''.join(kept),{'mode':'solve_limit_override','original_cap':original_cap,
                              'effective_cap':effective_cap,'removed_clauses':removed,'policy_text':policy}
