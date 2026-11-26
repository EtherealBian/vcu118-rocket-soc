"""Counter and CRC checks shared between simulation and physical captures."""
import re
from statistics import median

# CRCs independently reproduced by the unmodified POSIX program at four iterations.
GOLD = {0: (0xe714, 0x1fd7, 0x8e3a, 0x9f95), 0x3415: (0xe3c1, 0x0747, 0x8d84, 0x19d9)}
START = 'CPUWIN_START v1 diagnostic_only'
END = 'CPUWIN_PASS sets=2 samples=3 not_a_score'
ROW = re.compile(r'CPUWIN seed=(\d+) sample=(\d+) iterations=4 cycles=(\d+) retired=(\d+) list=(\d+) matrix=(\d+) state=(\d+) final=(\d+)')


def windows(lines):
    if len(lines) != 8 or lines[0] != START or lines[-1] != END:
        raise ValueError('invalid diagnostic epoch or unexpected output')
    results = {k: [] for k in GOLD}
    for line, (sample, seed) in zip(lines[1:7], ((j, k) for j in range(3) for k in GOLD)):
        m = ROW.fullmatch(line)
        if not m: raise ValueError('malformed window row')
        k, j, cycles, retired, *crcs = map(int, m.groups())
        if (k, j) != (seed, sample) or tuple(crcs) != GOLD[k] or min(cycles, retired) <= 0:
            raise ValueError('window sequence, CRC or counter mismatch')
        results[k].append({'sample': j, 'cycles': cycles, 'retired': retired})
    def stats(rs):
        return dict(samples=rs, median_cycles_per_iteration=median(r['cycles']/4 for r in rs),
                    median_retired_per_iteration=median(r['retired']/4 for r in rs),
                    median_ipc=round(median(r['retired']/r['cycles'] for r in rs), 6))
    return dict(performance_seed=stats(results[0]), validation_seed=stats(results[0x3415]))
