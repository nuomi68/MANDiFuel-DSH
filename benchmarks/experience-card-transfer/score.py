"""Verify submitted numbers and solver evidence, then compare old and new retrieval."""
import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path

from materials import EXPECTED_TIME, TESTS, TRAIN, numeric, save
from trial import ARMS, HOST_ARM
from analyze import close, lines, native_exit_evidence, oknum, trace_info
from experience_rag import query_experience

LABELS={"skill_only":"仅 Skill","old_cards":"Skill + 旧卡","new_cards":"Skill + 新卡"}


def trace_details(folder):
    result=[]
    query_calls=set()
    final=""
    path,=(folder/"traces").rglob("session.jsonl")
    for line in path.open():
        row=json.loads(line)
        d=row.get("data",{})
        if row["type"]=="tool/call" and d.get("name") in ("bash","terminal"):
            if "experience_rag.py" in str(d["arguments"]) or "dual_query.py" in str(d["arguments"]):
                query_calls.add(d["callId"])
        elif row["type"]=="tool/result":
            message=d["message"]
            if message.get("source",{}).get("callId") not in query_calls:
                continue
            for part in message["content"]:
                for v in part.get("content",[]):
                    text=v.get("text","")
                    match=re.search(r'\{\s*"status"\s*:',text)
                    if not match:
                        continue
                    try:
                        payload,end=json.JSONDecoder().raw_decode(text[match.start():])
                    except ValueError:
                        continue
                    if payload.get("interface")!="mandifuel-experience-rag.v1":
                        continue
                    result.append(dict(query=payload["query"],valid=payload["status"]=="ok",characters=end,
                                       ids=[x["child"]["id"] for x in payload["results"]]))
        elif row["type"]=="assistant/message":
            final=" ".join(p.get("text","") for p in d["message"]["content"] if p.get("type")=="text")
    return result, final


def executed(t, folder):
    ws=folder/"workspace"
    exits=[x for x in lines(ws/"solver-exits.jsonl") if x.get("kind")=="solve"]
    starts=[x for x in lines(ws/"solver-starts.jsonl") if x.get("kind")=="solve"]
    natives=native_exit_evidence(folder,ws)
    if t[3]!="solve":
        return not (starts or exits or natives), None, ""
    sessions=[(Path(x["case_root"]).resolve(),ws/"execution-evidence"/x["id"]/"solver.log")
              for x in exits if x["exit_code"]==0] + list(natives.items())
    for case,log in reversed(sessions):
        if not case.is_relative_to(ws) or case.is_relative_to(ws/"source-case"):
            continue
        if not log.exists():
            log=case/"log.offbeat"
        if not log.is_file() or not re.search(r"(?im)^\s*end\s*$",log.read_text(errors="replace")):
            continue
        frames=[]
        for path in case.iterdir():
            if path.is_dir():
                try:
                    frames.append(float(path.name))
                except ValueError:
                    pass
        if not frames or not math.isclose(max(frames),EXPECTED_TIME[t[0]],rel_tol=1e-9):
            continue
        try:
            raw=numeric(t,case)
        except (OSError,ValueError):
            continue
        return True,raw,str(case.relative_to(ws))
    return False,None,""


def score(t, arm, root, refs):
    tid=t[0]
    folder=root/arm/tid/HOST_ARM[arm]
    response=folder/"workspace/answer.json"
    try:
        answer=json.loads(response.read_text())
    except (OSError,ValueError):
        answer={}
    if not isinstance(answer,dict):
        answer={}
    run=json.loads((folder/"run.json").read_text())
    telemetry=trace_info(folder)
    preflight=json.loads((folder/"preflight.json").read_text())
    if (telemetry["configs"]!=[["deepseek-official","deepseek-v4-flash","high"]] or
        telemetry["session_count"]!=1 or telemetry["messages_with_usage"]!=telemetry["model_messages"] or
        not preflight["isolation"]["passed"] or preflight["frontend_plugin_present"] or telemetry["ui_or_subagent_tools"]):
        raise ValueError(f"Inconsistent backend trace: {tid}/{arm}")
    if telemetry["total_tokens"]!=sum(telemetry[k] for k in ("cached_input","uncached_input","model_output")):
        raise ValueError("Token accounting mismatch")
    requests,citation=trace_details(folder)
    execution,raw,case=executed(t,folder)
    a,b=answer.get("a"),answer.get("b")
    checks=[close(a,refs[0]),close(b,refs[1])]
    raw_checks=None if raw is None else [close(x,y) for x,y in zip(raw,refs)]
    passed=(run.get("exit_code")==0 and not run.get("timed_out") and telemetry["turn_ends"]==["completed"]
            and run["source_unchanged"] and oknum(a) and oknum(b) and isinstance(answer.get("source"),str)
            and bool(answer["source"].strip()) and execution)
    ids=[cid for response in requests for cid in response["ids"]]
    cited=[cid for cid in ids if cid.split(":",1)[1] in citation or cid.split(":",1)[1] in str(answer.get("source",""))]
    return dict(id=tid,title=t[1],arm=arm,task_pass=passed,physics_pass=passed and all(checks),
                a=a,b=b,refs=refs,checks=checks,raw_checks=raw_checks,raw=raw,case=case,execution_ok=execution,
                rag_calls=telemetry["rag_invocations"],rag_confirmed=telemetry["rag_observed_returns"],
                retrieval=requests,cited_ids=sorted(set(cited)),source=answer.get("source",""),
                tokens=telemetry["total_tokens"],uncached=telemetry["uncached_input"],cached=telemetry["cached_input"],
                output=telemetry["model_output"],tools=telemetry["tool_calls"],messages=telemetry["model_messages"])


def replay(root):
    audit=json.loads((root/"card-audit.json").read_text())
    rows=[]
    for card in audit:
        tid=card["task"]
        requests,_=trace_details(TRAIN/tid/"skill_rag")
        if len(requests)!=1:
            raise ValueError(f"Missing original query: {tid}")
        old=requests[0]
        group=root/"new_cards/plugin/rag/experience/data"
        current=query_experience(old["query"],limit=3,corpus_path=group/"reviewed_corpus.json",index_path=group/"experience_index.json")
        entries=[x["child"]["id"] for x in current["results"]]
        matched=card["id"]+":01"
        rows.append(dict(task=tid,query=old["query"],old=old["ids"],new=entries,matched=matched,
                         correct_position=entries.index(matched)+1 if matched in entries else None))
    return rows


def summarize(rows):
    result={}
    for arm in ARMS:
        group=[r for r in rows if r["arm"]==arm]
        result[arm]={k:sum(x[k] for x in group) for k in ("tokens","cached","uncached","output","messages","tools","task_pass","physics_pass")}
        result[arm]["numeric_matches"]=sum(sum(r["checks"]) for r in group)
        result[arm]["retrieved"]=sum(r["rag_confirmed"]>0 for r in group)
        result[arm]["named_hit"]=sum(bool(r["cited_ids"]) for r in group)
        result[arm]["median_tokens"]=statistics.median(r["tokens"] for r in group)
        result[arm]["response_chars_median"]=statistics.median([v["characters"] for r in group for v in r["retrieval"]] or [0])
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("root",type=Path)
    args=p.parse_args()
    root=args.root.resolve()
    progress=json.loads((root/"progress.json").read_text())
    if {(r["task_id"],r["group"]) for r in progress}!={(t[0],a) for t in TESTS for a in ARMS} or any("infrastructure_error" in r for r in progress):
        raise SystemExit("Incomplete cohort, inspect progress.json")
    refs=json.loads((root/"reference.json").read_text())
    rows=[score(t,a,root,refs[t[0]]) for t in TESTS for a in ARMS]
    if any(r["rag_calls"] for r in rows if r["arm"]=="skill_only"):
        raise ValueError("Unexpected experience retrieval in control")
    save(root/"scores.json",rows)
    save(root/"training-query-replay.json",replay(root))
    save(root/"summary.json",summarize(rows))
    fields=["题号","任务","配置","任务成功","物理符合","量A","参考A","单位A","量B","参考B","单位B","总token","非缓存输入","缓存输入","输出","工具次数","经验调用","可见命中","说明中完整出现的命中子条目ID（含排除项）","取数说明"]
    units={t[0]:t[-1] for t in TESTS}
    with (root/"逐题明细.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f)
        w.writerow(fields)
        for r in rows:
            u=units[r["id"]]
            w.writerow([r["id"],r["title"],LABELS[r["arm"]],r["task_pass"],r["physics_pass"],r["a"],r["refs"][0],u[0],r["b"],r["refs"][1],u[1],
                        r["tokens"],r["uncached"],r["cached"],r["output"],r["tools"],r["rag_calls"],
                        " | ".join(k for v in r["retrieval"] for k in v["ids"])," | ".join(r["cited_ids"]),r["source"]])
    print(json.dumps(summarize(rows),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
