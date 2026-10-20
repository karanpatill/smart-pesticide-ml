"""Find minimum TFLM arena sizes with one driver PROCESS per probe (crash == does not fit).
Usage (WSL): python3 arena_search.py DRIVER MODEL INPUT"""
import json, subprocess, sys
drv, model, inp = sys.argv[1:4]
BIG = 1 << 20

def ok(*args):
    r = subprocess.run([drv, model, inp, *map(str, args)], capture_output=True, text=True,
                       env={"TFLM_QUIET": "1"})
    return r.returncode == 0 and "STATUS OK" in r.stdout

def min_size(pred, lo=0, hi=BIG):
    assert pred(hi), "does not fit even at upper bound"
    while hi - lo > 16:
        mid = ((lo + hi) // 2) & ~15
        if mid <= lo:
            break
        if pred(mid): hi = mid
        else: lo = mid
    return hi

single = min_size(lambda n: ok("single", n))
pers = min_size(lambda n: ok("split", n, BIG))
nonp = min_size(lambda n: ok("split", BIG, n))
print(json.dumps({"min_single_arena": single, "min_persistent_arena": pers,
                  "min_non_persistent_arena": nonp, "split_minima_together_ok": ok("split", pers, nonp),
                  "resolution_bytes": 16}, indent=1))
