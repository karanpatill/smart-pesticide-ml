for t in git make cmake g++ gcc clang unzip curl python3; do printf "%-8s %s\n" "$t" "$(command -v $t || echo MISSING)"; done
