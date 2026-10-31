# TimesFM Forecast Studio

First principle: Compare every forecast with a simple baseline, using only data available before its test window.

TimesFM Forecast Studio imports time-series CSVs, checks data quality, runs rolling-origin backtests, and exports a PDF report. Its installed Mac app starts and stops its local server with the window.

## Install and run the Mac app

This build targets macOS. Python 3.12 is used for the local build environment.

```sh
python3.12 -m venv .desktop-venv
.desktop-venv/bin/python -m pip install -r requirements-desktop.lock.txt
.desktop-venv/bin/python build_desktop.py
.desktop-venv/bin/python install_desktop.py
```

Open `~/Applications/TimesFM Forecast Studio.app` from Finder. Close the window or press Command-Q to stop the app and its local listener. To uninstall, move that app to Trash. The installer preserves a previous owned copy beside the replacement and refuses to replace an unrelated app.

PyInstaller applies an ad-hoc signature. The app has no Apple Developer ID signature and is not notarized. macOS may ask you to approve opening it.

User data stays in memory for the current app session. The app does not save CSVs or credentials. The desktop app includes the pinned TimesFM 2.5 and PyTorch runtime; model weights are not included. A selected checkpoint stays at its existing local path.

## Optional browser development

For source work, create a virtual environment and install `requirements.txt`, then run:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

To use TimesFM mode in the source server, install `requirements-timesfm.txt` into that same `.venv` before starting the server. The packaged Mac app already includes the pinned TimesFM and PyTorch runtime.

The development server binds to http://127.0.0.1:8321. The installed app uses an ephemeral loopback port and does not attach to a running browser server.

## Forecasts and reports

Choose a timestamp and value column. Optional series and covariate columns are previewed. The app infers cadence and flags duplicates, gaps, and missing targets. Choose an explicit missing-value repair before backtesting. The horizon is bounded, and the report includes observed history, forecast dates, methods, evaluation counts, input hash, and model provenance when applicable.

Baseline mode works without model weights. It reports point forecasts and scale-safe metrics, but does not report prediction intervals or coverage. MASE uses a training-only seasonal-naive scale and reports n/a when that scale is zero. Backtests need at least three folds and fail when the history is too short.

TimesFM 2.5 mode evaluates model forecasts on the same rolling-origin folds and uses model quantiles for observed coverage. The Mac app bundles TimesFM 2.0.2 and PyTorch 2.15.0; it does not bundle checkpoint weights.

To use TimesFM mode:

1. Download `model.safetensors` from the official [TimesFM 2.5 PyTorch checkpoint](https://huggingface.co/google/timesfm-2.5-200m-pytorch/tree/1d952420fba87f3c6dee4f240de0f1a0fbc790e3) into a local folder.
2. In the app, choose **TimesFM 2.5 local checkpoint** and enter the full path to `model.safetensors` or its containing folder.
3. Optionally verify the file with `shasum -a 256`. The pinned revision is `1d952420fba87f3c6dee4f240de0f1a0fbc790e3`; its file SHA-256 is `2f776efe6245e42b24bc4153ffdf61810140210e4bd3b01fb21f7aa779ab6ce8`.

The checkpoint is Apache-2.0 licensed and about 925 MB. The app loads it from the local path; it does not contact Hugging Face, use Hugging Face credentials, or silently fall back to a baseline under the TimesFM name. TimesFM 3.0 weights are outside this adapter's scope.

## Settings

There are no credentials or remote-service settings. The Settings panel explains model status and report assumptions. A local TimesFM checkpoint path is used only for the selected run and is not saved.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

## Build notices

`build_desktop.py` writes readable notices for the Python runtime and all installed build dependencies into the app. It uses the full pinned dependency lock and verified fallback license texts under `third_party_licenses/`. The TimesFM package and PyTorch are included in the desktop bundle; checkpoint weights are user-provided and remain outside it.
