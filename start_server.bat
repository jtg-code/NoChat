@echo off
cd /d "%~dp0"
if exist "server\target\release\nochat-server.exe" (
    "server\target\release\nochat-server.exe"
) else (
    cargo run --release --manifest-path "server\Cargo.toml"
)
pause

