"""Run all three configurations on the same held-out inputs using DSH headless."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import random
import shutil
import subprocess

from materials import HERE, REPO, TRAIN, TESTS, cards, numeric, pairs, save, snapshot
import run as previous


ARMS = ("skill_only","old_cards","new_cards")
HOST_ARM = {"skill_only":"skill","old_cards":"skill_rag","new_cards":"skill_rag"}


def launch(cohort, workers, timeout):
    cohort.mkdir(parents=True,mode=0o700,exist_ok=False)
    plugins={}
    for group in ARMS:
        src=TRAIN/("skills-without-experience" if group=="skill_only" else "frozen-plugin")
        plugins[group]=cohort/group/"plugin"
        shutil.copytree(src, plugins[group])
        (plugins[group]/"rag/experience/data/review_decisions.json").unlink(missing_ok=True)
    save(cohort/"card-audit.json",cards(plugins["new_cards"]))
    old, new = [pairs.hashes(plugins[k]) for k in ("old_cards","new_cards")]
    changed={name for name in set(old)|set(new) if old.get(name)!=new.get(name)}
    if changed!={"rag/experience/data/reviewed_corpus.json","rag/experience/data/experience_index.json"}:
        raise ValueError(f"Unequal software between RAG arms: {changed}")
    material=cohort/"inputs"
    references={}
    definitions=[]
    for t in TESTS:
        tid=t[0]
        dst=material/tid/"source-case"
        snapshot(t,dst)
        if t[3]=="solve":
            cal=material/"calibration"/tid
            shutil.copytree(dst,cal)
            command='source "$1"; source "$MANDIFUEL_OPENFOAM_BASHRC" >/dev/null 2>&1; export PATH="$MANDIFUEL_OFFBEAT_BIN:$PATH"; exec bash Allrun'
            with (cal/"calibration.log").open("wb") as log:
                subprocess.run(["bash","-c",command,"calibration",REPO/"configs/launcher.env"],cwd=cal,
                                     stdout=log,stderr=subprocess.STDOUT,timeout=360,check=True)

            archived=numeric(t,t[2])
            refs=numeric(t,material/"calibration"/tid)
            if not all(math.isclose(x,y,rel_tol=.005,abs_tol=1e-12) for x,y in zip(archived,refs)):
                raise ValueError(f"Calibration mismatch: {tid}, {archived}, {refs}")
        else:
            refs=numeric(t,dst)
        references[tid]=refs
        definitions.append(dict(id=tid,source=str(t[2].relative_to(REPO)),input_hashes=pairs.hashes(dst),
                                question=previous.prompt(t),title=t[1],mode=t[3],units=t[-1]))
    save(cohort/"reference.json",references)
    cells=[(t,g) for t in TESTS for g in ARMS]
    random.Random(202611191).shuffle(cells)
    manifest=dict(model="deepseek-official/deepseek-v4-flash",reasoning="high",frontend=False,workers=workers,
                  timeout=timeout,replicates=1,started=pairs.now(),arms=ARMS,tasks=definitions,
                  source_training=TRAIN.name,software_differences=sorted(changed),
                  order=[(t[0],g) for t,g in cells],hashes={g:pairs.hashes(p) for g,p in plugins.items()},
                  rule="task: completed turn, source unchanged, finite a/b and nonempty source, solve has verified normal exit, native marker, given endpoint and independently readable field; read-only has no solve. Physics: task success and both values match max(.005*abs(ref),1e-12). All assigned cells included.")
    save(cohort/"manifest.json",manifest)
    shutil.copytree(HERE,cohort/"definition",ignore=shutil.ignore_patterns("__pycache__"))
    envs={}
    for g in ARMS:
        d=cohort/g
        for file in ("manifest.json","reference.json"):
            (d/file).hardlink_to(cohort/file)
        for t in TESTS:
            sub=d/t[0]
            sub.mkdir()
            shutil.copytree(material/t[0]/"source-case",sub/"source-case")
            (sub/"task.txt").write_text(previous.prompt(t)+"\n")
            pair=(plugins["old_cards"] if g=="skill_only" else plugins[g],plugins["skill_only"])
            task,env=previous.prepare(t,HOST_ARM[g],d,pair)
            policy=d/t[0]/HOST_ARM[g]/"launch-config/isolation.json"
            conf=json.loads(policy.read_text())
            conf["denied_probe_files"]=[p for p in conf["denied_probe_files"] if not p.endswith("/bare/workspace/request.txt")]
            neighbor=ARMS[(ARMS.index(g)+1)%len(ARMS)]
            conf["denied_probe_files"].append(str(cohort/neighbor/t[0]/HOST_ARM[neighbor]/"workspace/request.txt"))
            conf["denied_probe_files"] += [str(TRAIN/"scores.json"),str(cohort/"card-audit.json")]
            for other in ARMS:
                if other!=g:
                    conf["denied_probe_files"].append(str(plugins[other]/"dsh/run-assistant-persona.md"))
            save(policy,conf)
            envs[t[0],g]=task,env
    def execute(t,g):
        task,env=envs[t[0],g]
        d=cohort/g
        arm=HOST_ARM[g]
        try:
            pairs.preflight(task,arm,d,env)
            return dict(group=g,**pairs.run(task,arm,d,env,timeout))
        finally:
            previous.remove_temporary_auth(d/t[0]/arm)
    records=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(execute,t,g):(t[0],g) for t,g in cells}
        for future in as_completed(futures):
            tid,g=futures[future]
            try:
                item=future.result()
            except Exception as exc:
                item=dict(group=g,task_id=tid,infrastructure_error=str(exc))
            records.append(item)
            previous.save(cohort/"progress.json",records)
    print(f"finished {len(records)}",flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("cohort",type=Path)
    p.add_argument("--workers",type=int,default=12)
    p.add_argument("--timeout",type=int,default=1200)
    args=p.parse_args()
    launch(args.cohort.resolve(),args.workers,args.timeout)
