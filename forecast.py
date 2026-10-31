"""CSV validation and leakage-safe baseline evaluation."""
from __future__ import annotations
import csv, io, math, statistics, time
from datetime import datetime

MAX_BYTES = 2_000_000
MAX_ROWS = 50_000

def parse_csv(raw: str, timestamp: str, value: str, series_col: str = "", covariates=None):
    if len(raw.encode("utf-8")) > MAX_BYTES: raise ValueError("CSV is larger than 2 MB")
    reader = csv.DictReader(io.StringIO(raw))
    headers = reader.fieldnames or []
    if timestamp not in headers or value not in headers: raise ValueError("Choose timestamp and value columns from the CSV header")
    covariates = covariates or []
    rows=[]
    for n,row in enumerate(reader):
        if n >= MAX_ROWS: raise ValueError("CSV exceeds 50,000 rows")
        try: dt=datetime.fromisoformat(row[timestamp].strip().replace("Z","+00:00"))
        except Exception: raise ValueError(f"Invalid timestamp on CSV row {n+2}")
        rawv=row[value].strip()
        try: y=float(rawv) if rawv else None
        except ValueError: raise ValueError(f"Value on row {n+2} is not numeric")
        if y is not None and not math.isfinite(y): raise ValueError(f"Value on row {n+2} must be finite")
        rows.append({"t":dt,"y":y,"series":row.get(series_col,"").strip() if series_col else "Series 1","covariates":{k:row.get(k,"") for k in covariates}})
    if not rows: raise ValueError("CSV has no data rows")
    groups={}
    for r in rows: groups.setdefault(r["series"] or "Series 1",[]).append(r)
    details=[]
    for name,rs in groups.items():
        rs.sort(key=lambda r:r["t"])
        dups=sum(1 for a,b in zip(rs,rs[1:]) if a["t"]==b["t"])
        if dups: raise ValueError(f"Series {name}: {dups} duplicate timestamp pairs. Resolve duplicates in the CSV, then reload.")
        deltas=[(b["t"]-a["t"]).total_seconds() for a,b in zip(rs,rs[1:]) if b["t"]>a["t"]]
        cadence=statistics.median(deltas) if deltas else None
        gaps=0
        if cadence:
            expanded=[]
            for idx,r in enumerate(rs):
                expanded.append(r)
                if idx+1<len(rs):
                    delta=(rs[idx+1]["t"]-r["t"]).total_seconds(); steps=max(1,round(delta/cadence))
                    if abs(delta-steps*cadence)>max(1,cadence*.02): raise ValueError(f"Series {name}: timestamps do not follow a stable cadence. Normalize the time grid before forecasting.")
                    if len(expanded)+steps>MAX_ROWS: raise ValueError(f"Series {name}: cadence expansion exceeds {MAX_ROWS} rows")
                    for k in range(1,steps):
                        expanded.append({"t":r["t"]+(rs[idx+1]["t"]-r["t"])*(k/steps),"y":None,"series":name,"covariates":{}}); gaps+=1
            rs=expanded
        missing=sum(r["y"] is None for r in rs)
        details.append({"name":name,"rows":len(rs),"duplicates":dups,"gaps":gaps,"missing":missing,"cadence_seconds":cadence,"start":rs[0]["t"].isoformat(),"end":rs[-1]["t"].isoformat(),"rows_data":rs})
    return headers,details

def repair_missing(series, method):
    vals=[r["y"] for r in series]
    if not any(v is None for v in vals): return vals
    known=[v for v in vals if v is not None]
    if not known: raise ValueError("Cannot repair a series with no numeric values")
    out=vals[:]
    if method=="zero": return [0.0 if x is None else x for x in out]
    if method=="mean": fill=statistics.mean(known); return [fill if x is None else x for x in out]
    if method!="linear": raise ValueError("Choose an explicit missing-value repair")
    for i,x in enumerate(out):
        if x is None:
            left=next((j for j in range(i-1,-1,-1) if out[j] is not None),None)
            right=next((j for j in range(i+1,len(out)) if out[j] is not None),None)
            if left is None: out[i]=out[right]
            elif right is None: out[i]=out[left]
            else: out[i]=out[left]+(out[right]-out[left])*(i-left)/(right-left)
    return out

def evaluate(values, horizon, season=1, folds=5, repair="linear"):
    n=len(values); horizon=int(horizon); season=max(1,int(season)); folds=min(8,max(3,int(folds)))
    if horizon<1 or horizon>60: raise ValueError("Horizon must be between 1 and 60 steps")
    if n < horizon*(folds+1)+season: raise ValueError(f"Need at least {horizon*(folds+1)+season} repaired observations for {folds} folds")
    fold_results={"Last value":[],"Seasonal naive":[]}; scales=[]; started=time.perf_counter()
    # Origins are ascending, and each training window ends strictly before its test window.
    origins=[n-horizon*(folds-i) for i in range(folds)]
    for origin in origins:
        raw_train=values[:origin]; train=repair_missing([{"y":v} for v in raw_train],repair) if any(v is None for v in raw_train) else raw_train; actual=values[origin:origin+horizon]
        preds={"Last value":[train[-1]]*horizon,"Seasonal naive":[train[-season+i%season] for i in range(horizon)]}
        for method,p in preds.items():
            scored=[(a,b) for a,b in zip(actual,p) if a is not None]
            fold_results[method].extend(abs(a-b) for a,b in scored)
        scales.append(statistics.mean(abs(train[i]-train[i-season]) for i in range(season,len(train))) if len(train)>season else 0)
    elapsed=(time.perf_counter()-started)*1000
    summary={}
    for method,errs in fold_results.items():
        # Use the mean training-only seasonal scale across evaluated folds.
        if not errs: raise ValueError("No observed targets were available in the backtest windows")
        scale=statistics.mean(scales) if scales else 0
        summary[method]={"mae":statistics.mean(errs),"mase":statistics.mean(errs)/scale if scale>0 else None,"folds":folds,"observations":len(errs)}
    winner=min(summary,key=lambda x:summary[x]["mae"])
    final_values=repair_missing([{"y":v} for v in values],repair) if any(v is None for v in values) else values
    base=final_values[-season:]
    forecast=[base[i%season] for i in range(horizon)] if winner=="Seasonal naive" else [final_values[-1]]*horizon
    return {"methods":summary,"winner":winner,"forecast":forecast,"interval_radius":None,"observed_coverage":None,"runtime_ms":elapsed,"origins":origins,"fold_bounds":[[0,o,o+horizon] for o in origins],"scale":scale}
