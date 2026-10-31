"""Optional local-only TimesFM 2.5 PyTorch adapter."""
from pathlib import Path
import hashlib, time, statistics, math
from importlib import metadata

CHECKPOINT_ID="google/timesfm-2.5-200m-pytorch"
PACKAGE_VERSION="2.0.2"

def load(weights_path, max_context, max_horizon):
    if len(str(weights_path))>512: raise ValueError("TimesFM checkpoint path must be 512 characters or fewer")
    path=Path(weights_path).expanduser().resolve()
    if not path.exists(): raise ValueError("TimesFM weights path does not exist")
    weight_file=path/"model.safetensors" if path.is_dir() else path
    if not weight_file.is_file(): raise ValueError("Select a local TimesFM checkpoint file or directory containing model.safetensors")
    try:
        import numpy as np
        from timesfm import TimesFM_2p5_200M_torch, ForecastConfig
    except ImportError as e:
        raise ValueError("Install the pinned TimesFM 2.5 package and its PyTorch dependencies to enable this mode") from e
    try: installed=metadata.version("timesfm")
    except metadata.PackageNotFoundError as e: raise ValueError("Install the pinned TimesFM 2.5 package to enable this mode") from e
    if installed!=PACKAGE_VERSION: raise ValueError(f"TimesFM package {PACKAGE_VERSION} is pinned; found {installed}")
    model=TimesFM_2p5_200M_torch(torch_compile=False)
    started=time.perf_counter(); model.load_checkpoint(str(weight_file),torch_compile=False)
    model.compile(ForecastConfig(max_context=min(2048,max(128,max_context)),max_horizon=max_horizon,normalize_inputs=True,per_core_batch_size=1))
    digest=hashlib.sha256()
    with weight_file.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""): digest.update(block)
    return model, {"load_runtime_ms":(time.perf_counter()-started)*1000,"checkpoint_id":CHECKPOINT_ID,"checkpoint_sha256":digest.hexdigest(),"package_version":installed}

def predict(model, values, horizon):
    import numpy as np
    points,quantiles=model.forecast(horizon,[np.asarray(values,dtype=np.float32)])
    raw=quantiles[0].tolist()
    if any(len(row)!=10 for row in raw): raise ValueError("TimesFM 2.5 returned an unexpected quantile channel layout")
    # Channel 0 is the model's point output; channels 1..9 map to q0.1..q0.9.
    quantile_values=[row[1:10] for row in raw]
    return [float(x) for x in points[0]], quantile_values

def backtest(model, values, horizon, season, folds, repair_fn):
    n=len(values); origins=[n-horizon*(folds-i) for i in range(folds)]; errors=[]; hits=[]; scales=[]; started=time.perf_counter()
    for origin in origins:
        raw=values[:origin]; train=repair_fn(raw); actual=values[origin:origin+horizon]
        point,quantiles=predict(model,train,horizon)
        scales.append(statistics.mean(abs(train[i]-train[i-season]) for i in range(season,len(train))) if len(train)>season else 0)
        for j,y in enumerate(actual):
            if y is None: continue
            errors.append(abs(y-point[j]))
            # predict() removes channel 0, leaving configured q0.1..q0.9 channels.
            row=quantiles[j]
            if len(row)>=9: hits.append(row[0] <= y <= row[8])
    if not errors: raise ValueError("No observed targets were available in the TimesFM backtest windows")
    mean_scale=statistics.mean(scales) if scales else 0
    final_train=repair_fn(values); forecast,quantiles=predict(model,final_train,horizon)
    elapsed=(time.perf_counter()-started)*1000
    return {"mae":statistics.mean(errors),"mase":statistics.mean(errors)/mean_scale if mean_scale>0 else None,"folds":folds,"observations":len(errors),"observed_coverage":statistics.mean(hits) if hits else None,"forecast":forecast,"quantiles":quantiles,"quantile_levels":[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9],"runtime_ms":elapsed,"fold_bounds":[[0,o,o+horizon] for o in origins]}
