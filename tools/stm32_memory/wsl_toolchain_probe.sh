for t in arm-none-eabi-gcc make cmake; do printf "WSL %-18s %s\n" "$t" "$(command -v $t || echo MISSING)"; done; ls /usr/lib/gcc/arm-none-eabi 2>/dev/null || echo "WSL: no arm-none-eabi gcc libs"
