# Security

CSV Forecasts processes local CSV files with byte, row, and series limits. The loopback server checks Host and Origin, uses a random token for requests, and applies a connection timeout. Optional TimesFM mode requires a local checkpoint and the pinned package version. The app records a SHA-256 digest for the selected weights. That digest identifies the file; it is not an approval check unless you compare it with a trusted expected value. Local CSV files and reports are plaintext.

Use your Mac’s disk encryption to protect saved files. The native app has an ad-hoc code signature. This lets the installer check whether its files changed. It does not prove who made the app. The build is not notarized.

Report security issues through [GitHub private vulnerability reporting](https://github.com/gmperkinsmba/csv-forecasts/security/advisories/new).
