"""Organizer-only numeric references. No model calls and no use of actor answers."""
import bisect,csv,math,re,statistics,sys
from pathlib import Path
from tasks import ROOT,RUNS,TASKS,sources,frames
sys.path.insert(0,str(ROOT/'lib'))
from mandifuel_verify.case import Case
def times(p):
    valid=[]
    for f in p.iterdir():
        if f.is_dir():
            try:valid.append((float(f.name),f.name))
            except ValueError:pass
    return [s for _,s in sorted(valid)]
def interp(x,y,target):
    pairs=sorted(zip(x,y));xs,ys=zip(*pairs);i=bisect.bisect_left(xs,target)
    if not 0<i<len(xs):raise ValueError('unbracketed target')
    slope=(ys[i]-ys[i-1])/(xs[i]-xs[i-1])
    return ys[i-1]+slope*(target-xs[i-1]),slope
def values(t,source=None):
    tid,title,sk,mode,_,units=t
    p=(Path(source) if source else RUNS/sources[sk]).resolve()
    if mode=='table':
        if tid=='P15':
            f=p if p.is_file() else p/'observations.dat'
            rows=[list(map(float,l.split())) for l in f.read_text().splitlines() if l.strip() and not l.startswith('#') and len(l.split())==4]
            _,css,cpp,ctot=rows[-1]; assert abs(css+cpp-ctot)<0.01
            return [css,cpp/(css+cpp)]
        rows=list(csv.DictReader((p if p.is_file() else p/'observations.csv').open()))
        def col(k):return [float(r[k]) for r in rows]
        if tid=='D17':return interp(col('u_interface_um'),col('E_inner_GPa'),2.05)[0],1/interp(col('u_interface_um'),col('E_inner_GPa'),2.05)[1]
        if tid=='D18':
            y=sorted(col('fuel_T_max_K'));return statistics.pstdev(y),interp(range(len(y)),y,.9*(len(y)-1))[0]
        if tid=='D19':
            q=interp(col('fuel_T_max_K'),col('lhgr_W_per_m'),1350)[0];return q,interp(col('lhgr_W_per_m'),col('cladding_T_volavg_K'),q)[0]
        x=col('r_hole_mm');a,b=x.index(min(x)),x.index(max(x));area=col('fuel_area_m2');T=col('T_hole_wall_K')
        return (1-area[b]/area[a])*100,T[a]-T[b]
    ts=frames[tid][0] if tid in frames else times(p)
    c=Case(p,time=ts[-1])
    if tid=='S08':
        text=(p/c.time/'uniform/gapGas').read_text()
        def vol(name,part):return float(re.search(r'^'+name+r' \(in the '+part+r'\)\s+([0-9.eE+\-]+);',text,re.M)[1])
        return vol('gapVolume','OFFBEAT model'),sum(vol(n,'corresponding 360 degree rod') for n in ('topPlenumVolume','bottomPlenumVolume'))
    g=c.geometry;v=g['volumes'];z=g['zones']
    def field(k,component=0,time=None):return [r[component] for r in c.field(k,time=time)]
    def mean(vals,ids):return sum(vals[i]*v[i] for i in ids)/sum(v[i] for i in ids)
    def peak(vals,zone):return max(vals[i] for i in z[zone])
    def release(time):return 1-mean(field('Cs',time=time),range(len(v)))
    def surface(case,k,patch,comp=0):
        faces=case.geometry['patches'][patch]['faces']
        if k in ('D','oxideThickness'):
            raw=(case.root/case.time/k).read_text()
            section=re.search(r"(?m)^    "+re.escape(patch)+r"\s*\{([\s\S]*?)^    \}",raw)
            matches=re.findall(r"(?m)^\s*value\s+uniform\s+([^;]+);",section[1])
            parsed=[tuple(map(float,v.strip().strip('()').split())) for v in matches]
            if not parsed or len(set(parsed))!=1:raise ValueError(f'{patch}: missing or conflicting values')
            vals=[parsed[0]]*len(faces)
        else:vals=case.boundary(k,patch)
        weights=[math.dist(case.geometry['areas'][i],(0,0,0)) for i in faces]
        if k=='D':
            radial=[sum(a*b for a,b in zip(row,g['faceCentres'][i]))/math.dist(g['faceCentres'][i],(0,0,0)) for row,i in zip(vals,faces)]
        else:radial=[row[comp] for row in vals]
        return sum(a*b for a,b in zip(radial,weights))/sum(weights)
    if tid=='S01':return peak(field('T'),'fuel'),sum(a*b for a,b in zip(field('Q'),v))
    if tid=='S02':return [surface(c,'D',patch)*1e6 for patch in ('inner','outer')]
    if tid=='S03':return peak(field('T'),'fuel'),mean(field('T'),z['fuel'])-mean(field('T',time=ts[1]),z['fuel'])
    if tid=='S04':return max(field('Cs')),release(c.time)
    if tid=='S05':return [peak(field('DCyl'),zone)*1e6 for zone in ('inner','outer')]
    if tid=='S06':return max(field('epsilonCreepEq')),max(field('sigmaEq'))/1e6
    if tid=='S07':return [surface(Case(p,time=s),'oxideThickness','cladOuter')*1e6 for s in ts[-2:]]
    if tid=='P09':
        radii=[math.dist(pt,(0,0,0)) for pt in g['centres']];cs=field('Cs');i=min(z['Kernel'],key=lambda i:abs(radii[i]-230e-6))
        return cs[i],mean(cs,z['Buffer'])
    if tid=='P10':return [mean(field('T'),z[k]) for k in ('fuel','cladding')]
    if tid=='P11':
        i=min(range(len(v)),key=lambda k:math.dist(g['centres'][k],(0,0,0)));pt=g['centres'][i];x,y,z1=[a/math.dist(pt,(0,0,0)) for a in pt]
        xx,xy,xz,yy,yz,zz=c.field('sigma')[i];rr=x*x*xx+y*y*yy+z1*z1*zz+2*(x*y*xy+x*z1*xz+y*z1*yz)
        return rr/1e6,(xx+yy+zz-rr)/2e6
    if tid=='P12':
        vm=[math.sqrt(((a-d)**2+(d-f)**2+(f-a)**2)/2+3*(b*b+cc*cc+e*e))/1e6 for a,b,cc,d,e,f in c.field('sigma')]
        return [peak(vm,k) for k in ('inner','outer')]
    if tid=='P13':return surface(c,'T','fuelOuter'),peak(field('T'),'fuel')
    if tid=='P14':
        delta=1e4*(max(field('fastFluence'))-max(field('fastFluence',time=ts[0])))
        return delta,delta/(float(ts[-1])-float(ts[0]))
    if tid=='P16':
        fs=[release(s) for s in ts];return interp(fs,list(map(float,ts)),.5)[0],fs[-1]
    raise ValueError(tid)
if __name__=='__main__':
    for t in TASKS:print(t[0],values(t),flush=True)
