import sys, subprocess, struct
sys.path.insert(0, 'tools/firmware')
import read_selftest as rs

addr_cycle, sz_cycle = rs.symbol('reports/firmware/gcc/fv_app_final_presentation.elf', 'g_cycle')
cmd = [rs.CLI, '-c', 'port=SWD', 'freq=2000', 'mode=HOTPLUG', '-r32', hex(addr_cycle), str(sz_cycle)]
r = subprocess.run(cmd, capture_output=True, text=True)
b = rs.parse_r32(r.stdout, addr_cycle, sz_cycle)

for off in range(0, len(b) - 176, 4):
    lines = [b[off + i*22 : off + (i+1)*22].split(b'\x00')[0].decode('ascii', errors='ignore') for i in range(8)]
    if any('===' in l or 'FRUIT' in l or 'Banana' in l or 'Guava' in l or 'SYSTEM' in l or 'Fruit' in l for l in lines):
        print(f'=== OLED Screen Content (Offset {off}) ===')
        for idx, l in enumerate(lines):
            print(f'Row {idx+1}: \"{l}\"')
        break
