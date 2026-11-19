"""Build the transferable candidate cards and freeze held-out engineering inputs."""
import csv
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUNS = REPO / "runs"
TRAIN = RUNS / "three-arm-20-20261119-01"
sys.path.insert(0, str(REPO / "benchmarks/three-arm-20"))
sys.path.insert(0, str(REPO / "rag/experience"))
from run import pairs
from reference import Case
from experience_rag import build_index

WB = RUNS / "workbench"
HYDROGEN = RUNS / "threeway-experience-20261116-03/C_new_Hydrogen/bare/workspace/case-hydrogen-ingress-1000d/postProcessing/average/0/volFieldValue.dat"
# ID, title, input, operation, prompt, units
TESTS = [
    ("H01", "稳态热棒的总功率与区平均温度", WB/"task-f3c643e3ddf74c9c/workspace/case", "solve",
     "保留已有载荷和输入的结束时刻，从初态完成该导热算例。求计算域发热总功率，以及终态燃料区按单元体积加权的平均温度。", ["W","K"]),
    ("H02", "压力球壳的外缘单元与等效应力", WB/"task-f6ec62ccb0664b97/workspace/case-fix1", "solve",
     "保持球壳给定载荷和终点从初态实际求解。求终态全体单元最大 von Mises 应力，以及距球心最远单元的有符号径向位移（球心在原点，向外为正）。", ["MPa","µm"]),
    ("H03", "扩散期间剩余库存及峰值下降", WB/"task-89e4bb8920014eb2/workspace/case", "field",
     "按所给两个保存帧，计算晚帧与早帧全计算域铯库存之比，并给出单元浓度峰值从早帧到晚帧的下降量。", ["1","mol/m³"]),
    ("H04", "双材料应力分位数与区平均", WB/"task-aeb6f94d47d4495e/workspace/cases/E150", "field",
     "从应力内场逐单元求 von Mises 值。计算 inner 区按单元等权的 95% 分位数（排序后按 (N−1)p 线性插值），以及 outer 区按单元体积加权的平均值。", ["MPa","MPa"]),
    ("H05", "包壳析出氢的峰值份额与出现时刻", HYDROGEN, "log",
     "根据所给包壳氢的原生体积平均日志，在所有完整采样行中求析出氢占两相之和的最大百分比，并给出首次检出非零析出氢的采样时刻。时间沿用日志中的天。", ["%","d"]),
    ("H06", "由氧化层观测推回载荷温度", WB/"task-581ee8249124498a/workspace/bisection-record.csv", "table",
     "在氧化厚度最接近且分居 24 µm 两侧的观测之间作线性插值，求对应温度和这段厚度对温度的斜率。", ["K","µm/K"]),
    ("H07", "稳态迭代中的界面功率闭合", WB/"task-634128ddd15d4eb2/workspace/results/boundary_power_history.csv", "table",
     "从求解器外迭代的边界功率序列，给出最后一行燃料外侧与包壳内侧的有符号功率和，再给出包壳外侧功率最后三行的极差。表中各功率均保留求解器原号。", ["W","W"]),
    ("H08", "分层换热样本的离散程度", WB/"task-44a5e43a3ac04d95/workspace/samples.csv", "table",
     "根据各层等权的热隙换热系数样本，求总体标准差以及四分位距。两个分位数均按排序位置 (N−1)p 作线性插值。", ["W/(m²·K)","W/(m²·K)"]),
]
TABLE_COLS = {"H06":["T_K","oxide_um"], "H07":["outer_iteration","fuelOuter","cladInner","cladOuter"], "H08":["stratum","h_W_m2K"]}
FIELDS = {"H03":(["4000","22000"],"Cs"), "H04":(["1"],"sigma")}
EXPECTED_TIME = {"H01":1, "H02":10}


def save(file, payload):
    file.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n")


def cards(plugin):
    dest = plugin/"rag/experience/data"
    parents, children, audit = [], [], []
    scores = {row["id"]:row for row in json.loads((TRAIN/"scores.json").read_text()) if row["arm"]=="skill"}
    with (HERE/"cards.tsv").open() as f:
        for i, item in enumerate(csv.DictReader(f, delimiter="\t"), 21):
            tid = item["task"]
            row = scores[tid]
            if not row["physics_pass"] or not row["input_preserved"]:
                raise ValueError(f"Unverified training artifact: {tid}")
            folder = TRAIN/tid/"skill"
            trace, = (folder/"traces").rglob("session.jsonl")
            answer = folder/"workspace/answer.json"
            identifier = f"knowledge:K{i:02d}"
            source = str(trace.relative_to(REPO))
            parents.append(dict(id=identifier, record_type="parent", title=item["title"], context=item["context"],
                                approved_for_rag=False, source_question_server=str((TRAIN/tid/"task.txt").relative_to(REPO))))
            children.append(dict(id=identifier+":01", parent_id=identifier, record_type="child", position=1,
                                 kind=item["terms"], text=item["guidance"], review_status="pass", approved_for_rag=True,
                                 review_reason="已核对来源会话、交付和独立数值评分；适用范围见上下文。", role="guidance",
                                 source_groups=[dict(group_id="source:skill",run=TRAIN.name,arm="skill",task_status="completed",
                                                     session_status="completed",source_session=source)]))
            audit.append(dict(id=identifier, task=tid, source_session=source, answer=str(answer.relative_to(REPO)),
                              answer_sha256=hashlib.sha256(answer.read_bytes()).hexdigest(),
                              trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest(),
                              reviewed_arms=["bare","skill","skill_rag"], evidence_arm="skill",
                              exception="经验组延长了终点，成功的 Skill 组保留原终点" if tid=="S01" else None))
    if len(parents)!=20 or {r["task"] for r in audit}!=set(scores):
        raise ValueError("Training coverage mismatch")
    save(dest/"reviewed_corpus.json",dict(schema_version="mandifuel-experience-corpus.v1",parents=parents,children=children))
    build_index(dest/"reviewed_corpus.json",dest/"experience_index.json")
    return audit


def snapshot(t, dst):
    tid, _, source, mode, _, _ = t
    dst.mkdir(parents=True)
    if mode=="solve":
        for name in ("0","system","constant"):
            shutil.copytree(source/name, dst/name, ignore=shutil.ignore_patterns("polyMesh","*.bak","*.orig"))
        steps = ["blockMesh > log.blockMesh 2>&1"]
        if (dst/"system/changeDictionaryDict").exists():
            steps.append("changeDictionary > log.changeDictionary 2>&1")
        (dst/"Allrun").write_text("#!/usr/bin/env bash\nset -eu\n"+"\n".join(steps)+"\noffbeat > log.offbeat 2>&1\n")
    elif mode=="field":
        shutil.copytree(source/"constant/polyMesh",dst/"constant/polyMesh")
        frames, field = FIELDS[tid]
        for time in frames:
            (dst/time).mkdir()
            shutil.copyfile(source/time/field,dst/time/field)
            if (source/time/"polyMesh").exists():
                shutil.copytree(source/time/"polyMesh",dst/time/"polyMesh")
    elif mode=="log":
        shutil.copyfile(source,dst/"observations.dat")
    else:
        with source.open() as src, (dst/"observations.csv").open("w",newline="") as out:
            writer=csv.DictWriter(out,fieldnames=TABLE_COLS[tid],extrasaction="ignore")
            writer.writeheader()
            writer.writerows(csv.DictReader(src))


def quantile(values, p):
    seq=sorted(values)
    pos=(len(seq)-1)*p
    i=math.floor(pos)
    return seq[i]+(pos-i)*(seq[math.ceil(pos)]-seq[i])


def numeric(t, folder):
    tid=t[0]
    if tid=="H05":
        data=[list(map(float,s.split())) for s in (folder/"observations.dat").read_text().splitlines() if not s.lstrip().startswith("#") and len(s.split())==4]
        return max(100*b/(a+b) for _,a,b,_ in data if a+b), next(tm for tm,_,b,_ in data if b>0)
    if t[3]=="table":
        import statistics
        with (folder/"observations.csv").open() as stream:
            rows=[{k:float(v) for k,v in s.items()} for s in csv.DictReader(stream)]
        if tid=="H06":
            pts=sorted((s["oxide_um"],s["T_K"]) for s in rows)
            (xa,ya),(xb,yb)=next((a,b) for a,b in zip(pts,pts[1:]) if a[0]<=24<=b[0])
            return ya+(24-xa)*(yb-ya)/(xb-xa),(xb-xa)/(yb-ya)
        if tid=="H07":
            vals=[s["cladOuter"] for s in rows[-3:]]
            return rows[-1]["fuelOuter"]+rows[-1]["cladInner"],max(vals)-min(vals)
        h=[s["h_W_m2K"] for s in rows]
        return statistics.pstdev(h),quantile(h,.75)-quantile(h,.25)
    tm={"H01":"1","H02":"10","H03":"22000","H04":"1"}[tid]
    c=Case(folder.resolve(),time=tm)
    if tid=="H03":
        def inventory(time):
            f=Case(folder.resolve(),time=time)
            x=[v[0] for v in f.field("Cs")]
            return sum(a*b for a,b in zip(x,f.geometry["volumes"])),max(x)
        early,late=map(inventory,FIELDS[tid][0])
        return late[0]/early[0],early[1]-late[1]
    g=c.geometry
    vols=g["volumes"]
    def mean(x,ids):
        return sum(x[i]*vols[i] for i in ids)/sum(vols[i] for i in ids)
    if tid=="H01":
        return sum(v[0]*w for v,w in zip(c.field("Q"),vols)),mean([x[0] for x in c.field("T")],g["zones"]["fuel"])
    if tid=="H02":
        i=max(range(len(vols)),key=lambda j:math.hypot(*g["centres"][j]))
        coord=g["centres"][i]
        return max(v[0] for v in c.field("sigmaEq"))/1e6,1e6*sum(v*x for v,x in zip(c.field("D")[i],coord))/math.hypot(*coord)
    vm=[math.sqrt(((a-d)**2+(d-f)**2+(f-a)**2)/2+3*(b*b+h*h+e*e))/1e6 for a,b,h,d,e,f in c.field("sigma")]
    return quantile([vm[i] for i in g["zones"]["inner"]],.95),mean(vm,g["zones"]["outer"])
