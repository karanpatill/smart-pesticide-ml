================================================================================
SMART PESTICIDE RESIDUE DETECTION SYSTEM — CLIENT OPERATIONAL GUIDE
================================================================================

1. STAND-ALONE OPERATION (NO LAPTOP REQUIRED):
--------------------------------------------------------------------------------
The firmware and TinyML models are permanently flashed onto the STM32F407VET6 
internal Flash memory. The system runs autonomously as a standalone embedded device.

Step 1: Power On
  - Connect a standard 5V power supply or USB cable (from power bank or 5V adapter) 
    to the board power header.
  - The board boots within 2 seconds.

Step 2: Startup Display
  - The SSD1306 OLED screen will turn on and display the baseline telemetry:
      Row 0: Fruit:NOFRUIT/UNKNOWN
      Row 1: Cond:UNCERTAIN
      Row 2: Grade:UNCERTAIN
      Row 3: Shelf:UNCERTAIN
      Row 4: Risk:UNCERTAIN
      Row 5: pH[live] MQ[live]
      Row 6: T[live]C RH[live]%

Step 3: Presenting Fruit Sample
  - Hold or place the fruit sample (Banana, Apple, Guava, Tomato, Brinjal) 
    10 to 15 cm directly in front of the OV2640 camera lens in ambient room lighting.
  - Within 2 seconds (refresh interval), the TinyML model will output:
      Row 0: Fruit: [Name] [Confidence]
      Row 1: Cond: fresh / spoiled
      Row 2: Grade: Good / Average / Poor
      Row 3: Shelf: [Days] [Stage]
      Row 4: Risk: LOW / MEDIUM / HIGH
      Row 5: [Live Wash Water pH & Gas VOC Reading]
      Row 6: [Live Temperature & Humidity]

Step 4: Standby Reset
  - Remove the fruit. The display automatically resets back to Standby within 
    one cycle (2 seconds).

--------------------------------------------------------------------------------
2. RE-FLASHING / RESTORE INSTRUCTIONS (OPTIONAL BACKUP):
--------------------------------------------------------------------------------
If you ever need to re-program the microcontroller:
1. Connect the ST-LINK programmer to the board's SWD header (GND, SWCLK, SWDIO, 3V3).
2. Connect ST-LINK to PC USB.
3. Double-click "1-Click-Flash.bat".
4. The script will automatically flash "fv_app_final_presentation.bin" to 0x08000000 
   and perform a hardware reset.

--------------------------------------------------------------------------------
3. INCLUDED DELIVERABLES:
--------------------------------------------------------------------------------
- fv_app_final_presentation.bin: Production firmware binary with multi-sensor fusion.
- board_flash_512K_original_backup.bin: Original factory firmware backup.
- SMART_PESTICIDE_SOFTWARE_HANDOVER_SPECIFICATION.pdf: Complete 2-page engineering 
  architecture report (for project file / submission).
- 1-Click-Flash.bat: Automated flashing tool.
================================================================================
