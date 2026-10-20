@echo off
cd /d "%~dp0"
echo ========================================================
echo  SMART PESTICIDE RESIDUE DETECTION SYSTEM - 1-CLICK FLASH
echo ========================================================
echo.
echo Connecting to STM32F407 via ST-LINK...
"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=4000 -d fv_app_final_presentation.bin 0x08000000 -v -rst
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Flashing failed! Check ST-LINK connection and try again.
) else (
    echo.
    echo [SUCCESS] Firmware programmed successfully! Board restarted.
)
echo.
pause
