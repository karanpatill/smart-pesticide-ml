# READ-ONLY ST-LINK check (Windows PowerShell). Never connects to the target MCU.
# 1. Windows PnP state of the ST-LINK (VID 0483)   2. STM32CubeProgrammer CLI presence
# 3. Probe enumeration only: `STM32_Programmer_CLI -l st-link` (lists probes; no -c, so no SWD/target access).
# Does NOT flash, erase, reset, change option bytes, connect to the target, or upgrade ST-LINK firmware.
$ErrorActionPreference = 'Continue'
"=== 1. ST-LINK USB device ==="
$dev = Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match 'VID_0483' }
if (-not $dev) { "No VID_0483 device known to Windows (ST-LINK not plugged in?)" }
$dev | Select-Object Status, Class, FriendlyName, InstanceId, Problem | Format-List | Out-String -Width 200
"=== 2. STM32CubeProgrammer CLI ==="
$cli = @('C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe',
         'C:\Program Files (x86)\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe') |
       Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $cli) { "STM32_Programmer_CLI.exe NOT FOUND"; exit 1 }
"FOUND: $cli"
& $cli --version
"=== 3. Probe enumeration (no target connection) ==="
& $cli -l st-link
"exit code: $LASTEXITCODE"
