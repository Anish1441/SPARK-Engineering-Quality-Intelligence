from __future__ import annotations
import numpy as np
import pandas as pd
def _num(df): return df.select_dtypes(include="number")
def _finite(s): return pd.to_numeric(s,errors="coerce").replace([np.inf,-np.inf],np.nan).dropna().to_numpy(float)
def robust_stats(s):
    x=_finite(s)
    if not len(x): return {"count":0,"mean":None,"median":None,"std":None,"min":None,"max":None,"mad":None}
    med=float(np.median(x)); mad=float(np.median(np.abs(x-med)))
    return {"count":len(x),"mean":float(np.mean(x)),"median":med,"std":float(np.std(x,ddof=1)) if len(x)>1 else 0.0,"min":float(np.min(x)),"max":float(np.max(x)),"mad":mad}
def dataset_health(df):
    n=len(df); missing=int(df.isna().sum().sum()); num=_num(df); cells=max(1,n*max(1,len(df.columns)))
    return {"rows":n,"columns":len(df.columns),"numeric_signals":len(num.columns),"missing_cells":missing,"duplicate_rows":int(df.duplicated().sum()),"completeness_pct":round(100*(1-missing/cells),1),"usable_numeric_signals":sum(num[c].notna().sum()>=3 for c in num.columns)}
def signal_control(df,column):
    if column not in df.columns: raise KeyError("Signal not found.")
    x=_finite(df[column])
    if len(x)<3: return {"signal":column,"eligible":False,"reason":"At least 3 finite observations are required.","values":[]}
    mean=float(np.mean(x)); std=float(np.std(x,ddof=1)); med=float(np.median(x)); mad=float(np.median(np.abs(x-med))); scale=1.4826*mad or std or 1.0
    rz=np.abs((x-med)/scale)
    return {"signal":column,"eligible":True,"mean":mean,"std":std,"ucl":mean+3*std,"center":mean,"lcl":mean-3*std,"median":med,"mad":mad,"values":[float(v) for v in x],"outlier_indices":[int(i) for i,v in enumerate(rz) if v>=3.5],"method":"Shewhart 3-sigma + robust MAD screen","note":"Descriptive screening limits; not engineering specifications."}
def record_assessment(df,index):
    if index<0 or index>=len(df): raise IndexError("Record index is out of range.")
    row=df.iloc[index]; contributors=[]; num=_num(df)
    for col in num.columns:
        vals=_finite(df[col])
        if len(vals)<3: continue
        value=pd.to_numeric(pd.Series([row[col]]),errors="coerce").iloc[0]
        if pd.isna(value): continue
        med=float(np.median(vals)); mad=float(np.median(np.abs(vals-med))); scale=1.4826*mad or float(np.std(vals)) or 1.0
        rz=abs(float(value)-med)/scale
        if rz>=2.5: contributors.append({"signal":str(col),"value":float(value),"baseline":med,"robust_z":round(rz,2)})
    contributors.sort(key=lambda x:x["robust_z"],reverse=True); raw=contributors[0]["robust_z"] if contributors else 0
    score=int(round(min(100,raw/5*100))); state="HIGH RISK" if score>=70 else "REVIEW" if score>=40 else "NORMAL"
    return {"record_index":index,"score":score,"state":state,"contributors":contributors[:5],"evidence_coverage":round(len(contributors)/max(1,len(num.columns))*100,1),"mode":"STATISTICAL SCREEN"}
def analyze_dataset(df):
    h=dataset_health(df); stability=[]; distributions=[]; correlations=[]; num=_num(df)
    for c in num.columns:
        s=signal_control(df,str(c)); distributions.append({"signal":str(c),"stats":robust_stats(df[c])}); stability.append({"signal":str(c),"mean":s.get("mean"),"std":s.get("std"),"outliers":len(s.get("outlier_indices",[])),"eligible":s.get("eligible",False)})
    corr=num.corr()
    for i,a in enumerate(corr.columns):
        for b in corr.columns[i+1:]:
            v=corr.loc[a,b]
            if pd.notna(v): correlations.append({"x":str(a),"y":str(b),"correlation":float(v)})
    correlations.sort(key=lambda z:abs(z["correlation"]),reverse=True)
    return {"health":h,"stability":stability,"distributions":distributions,"correlations":correlations[:20]}
def dataset_comparison(df):
    out=[]
    for c in _num(df).columns:
        s=df[c].dropna()
        if len(s): out.append({"signal":str(c),"mean":float(s.mean()),"median":float(s.median()),"std":float(s.std(ddof=1)) if len(s)>1 else 0.0})
    return {"signals":out}
