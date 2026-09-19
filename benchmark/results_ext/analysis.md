# CrystalPilot capability-boundary analysis

101 cases | solved 42/101 (42%) | SG top-1 82% (83/101) | mean R1 0.159 | mean human R1 0.04

### By chemistry category

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| mof | 38 | 50% (19/38) | 87% (33/38) | 0.119 | 0.083 |
| organic | 28 | 54% (15/28) | 89% (25/28) | 0.176 | 0.13 |
| inorganic | 13 | 8% (1/13) | 54% (7/13) | 0.223 | 0.192 |
| hard-P1 | 5 | 40% (2/5) | 100% (5/5) | 0.104 | 0.07 |
| hard-twin | 5 | 20% (1/5) | 60% (3/5) | 0.351 | 0.309 |
| hard-pseudo | 4 | 0% (0/4) | 75% (3/4) | 0.185 | 0.134 |
| hard-large | 4 | 50% (2/4) | 100% (4/4) | 0.159 | 0.11 |
| hard-disorder | 4 | 50% (2/4) | 75% (3/4) | 0.114 | 0.061 |

### By vendor family

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| Bruker | 63 | 46% (29/63) | 87% (55/63) | 0.15 | 0.11 |
| Oxford-Agilent | 12 | 33% (4/12) | 67% (8/12) | 0.148 | 0.108 |
| Nonius | 12 | 33% (4/12) | 75% (9/12) | 0.168 | 0.13 |
| Rigaku | 8 | 38% (3/8) | 75% (6/8) | 0.221 | 0.177 |
| Stoe | 5 | 20% (1/5) | 80% (4/5) | 0.187 | 0.149 |
| other | 1 | 100% (1/1) | 100% (1/1) | 0.133 | 0.07 |

### By crystal system (reference)

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| monoclinic | 59 | 47% (28/59) | 85% (50/59) | 0.161 | 0.123 |
| triclinic | 20 | 35% (7/20) | 90% (18/20) | 0.158 | 0.114 |
| orthorhombic | 13 | 46% (6/13) | 85% (11/13) | 0.142 | 0.098 |
| trigonal | 4 | 0% (0/4) | 50% (2/4) | 0.227 | 0.182 |
| hexagonal | 3 | 0% (0/3) | 33% (1/3) | 0.143 | 0.099 |
| tetragonal | 2 | 50% (1/2) | 50% (1/2) | 0.14 | 0.109 |

### By reflection count

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| <5k | 49 | 55% (27/49) | 86% (42/49) | 0.162 | 0.122 |
| <15k | 30 | 30% (9/30) | 83% (25/30) | 0.141 | 0.099 |
| <2k | 18 | 33% (6/18) | 67% (12/18) | 0.174 | 0.141 |
| >=15k | 4 | 0% (0/4) | 100% (4/4) | 0.225 | 0.162 |

### By cell volume (Å³)

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| <3k | 52 | 46% (24/52) | 81% (42/52) | 0.158 | 0.119 |
| <1k | 27 | 37% (10/27) | 78% (21/27) | 0.175 | 0.138 |
| <10k | 17 | 35% (6/17) | 88% (15/17) | 0.14 | 0.093 |
| >=10k | 5 | 40% (2/5) | 100% (5/5) | 0.159 | 0.11 |

### Failure taxonomy

| failure mode | n | example cases |
|---|---|---|
| wrong space group | 16 | cod_2020889, cod_2021267, cod_2203769, cod_2210339 |
| near miss (metric threshold) | 15 | cod_2019928, cod_2022918, cod_2207435, cod_2014409 |
| solution did not refine (R1>0.20) | 12 | cod_2210623, cod_2216484, cod_2221198, cod_2215805 |
| pipeline-error | 7 | cod_2020930, cod_2021706, cod_2108685, cod_2200897 |
| heavy ok, light atoms wrong/missing | 5 | cod_2015536, cod_2021268, cod_2108128, cod_2220958 |
| wrong solution (low atom match) | 2 | cod_2108482, cod_2011217 |
| crash: RuntimeError | 1 | cod_2108510 |
| crash: initial refinement failed | 1 | cod_1577466 |

### Worst cases (unsolved, by atom-match)

| case | category | true SG | used SG | R1 | human R1 | match | failure |
|---|---|---|---|---|---|---|---|
| cod_2020930 | mof | P 1 21/n 1 | P 1 21/n 1 | - | 0.0267 | - | pipeline-error |
| cod_2021706 | mof | P 1 21/n 1 | P 1 21/n 1 | - | 0.0353 | - | pipeline-error |
| cod_2108685 | mof | P -1 | P -1 | - | 0.0236 | - | pipeline-error |
| cod_2200897 | organic | P 1 21 1 | P 1 21 1 | - | 0.0342 | - | pipeline-error |
| cod_1560983 | inorganic | P 1 21/c 1 | P n c m | - | 0.0415 | - | pipeline-error |
| cod_2104205 | inorganic | I 1 a 1 | I 1 2/c 1 | 0.1537 | 0.0226 | 0.0 | wrong space group |
| cod_2108510 | inorganic | R 3 2 :H | - | - | 0.0231 | - | crash: RuntimeError |
| cod_2021406 | hard-large | C 2 2 21 | C 2 2 21 | - | 0.0693 | - | pipeline-error |
| cod_1577466 | hard-twin | P 1 21 1 | P 1 21 1 | - | 0.0165 | - | crash: initial refinement failed |
| cod_2020639 | hard-twin | P 1 21/c 1 | P 1 21/c 1 | - | 0.0893 | - | pipeline-error |
| cod_2020921 | hard-twin | P 1 21/c 1 | C m c a (2*y,z,x+y) | 0.4922 | 0.0384 | 0.0 | wrong space group |
| cod_2022987 | hard-twin | P 1 21/c 1 | P m c m | 0.3948 | 0.0329 | 0.0 | wrong space group |
| cod_2108482 | mof | C 1 2/c 1 | C 1 2/n 1 | 0.1757 | 0.0312 | 0.075 | wrong solution (low atom match) |
| cod_2211653 | inorganic | C 1 2/c 1 | C 1 2/n 1 | 0.2372 | 0.0328 | 0.143 | solution did not refine (R1>0.20) |
| cod_2011217 | inorganic | P 1 2/c 1 | P 1 2/c 1 | 0.1468 | 0.026 | 0.163 | wrong solution (low atom match) |
| cod_2015536 | mof | P 1 21/c 1 | P 1 21/c 1 | 0.0776 | 0.037 | 0.18 | heavy ok, light atoms wrong/missing |
| cod_2020318 | hard-large | C 1 2 1 | C 1 2 1 | 0.2758 | 0.0521 | 0.203 | solution did not refine (R1>0.20) |
| cod_2216484 | mof | P 1 21/n 1 | P 1 21/n 1 | 0.3507 | 0.0469 | 0.25 | solution did not refine (R1>0.20) |
| cod_2210623 | mof | P c c a | P c c a | 0.4043 | 0.0446 | 0.281 | solution did not refine (R1>0.20) |
| cod_2220037 | organic | P -1 | P -1 | 0.4251 | 0.0606 | 0.294 | solution did not refine (R1>0.20) |
| cod_2021267 | mof | P 65 | P 61 | 0.0341 | 0.052 | 0.303 | wrong space group |
| cod_2215805 | organic | P -1 | P -1 | 0.3473 | 0.0539 | 0.348 | solution did not refine (R1>0.20) |
| cod_2021268 | mof | P 61 | P 61 | 0.0437 | 0.04 | 0.409 | heavy ok, light atoms wrong/missing |
| cod_2220196 | organic | P -1 | P -1 | 0.3308 | 0.0748 | 0.435 | solution did not refine (R1>0.20) |
| cod_2108128 | mof | C 1 2 1 | C 1 2 1 | 0.1814 | 0.0335 | 0.5 | heavy ok, light atoms wrong/missing |
| cod_2220958 | mof | P n a 21 | P n a 21 | 0.1052 | 0.0338 | 0.591 | heavy ok, light atoms wrong/missing |
| cod_2022996 | inorganic | C 1 2/m 1 | C 1 2/m 1 | 0.2633 | 0.026 | 0.6 | solution did not refine (R1>0.20) |
| cod_2104873 | hard-P1 | P 1 | P 1 | 0.167 | 0.0269 | 0.606 | heavy ok, light atoms wrong/missing |
| cod_2213662 | hard-pseudo | P 1 21 1 | P 1 21/m 1 | 0.3425 | 0.039 | 0.611 | wrong space group |
| cod_2012296 | organic | P -1 | P 1 | 0.1512 | 0.0533 | 0.667 | wrong space group |
| cod_2013470 | inorganic | C 1 2/m 1 | C 1 2/m 1 | 0.46 | 0.0264 | 0.667 | solution did not refine (R1>0.20) |
| cod_2019928 | mof | P 1 2/c 1 | P 1 2/c 1 | 0.0949 | 0.0384 | 0.694 | near miss (metric threshold) |
| cod_2018446 | hard-disorder | P 32 2 1 | P 31 2 1 | 0.0685 | 0.0406 | 0.703 | wrong space group |
| cod_2203769 | mof | P -1 | P 1 | 0.0926 | 0.0261 | 0.733 | wrong space group |
| cod_2016126 | organic | P 1 21 1 | P 1 21/m 1 | 0.3331 | 0.0391 | 0.8 | wrong space group |
| cod_2016244 | inorganic | P 21 21 21 | P n m a | 0.1575 | 0.0216 | 0.833 | wrong space group |
| cod_2018533 | organic | P 1 21/n 1 | P 1 21/n 1 | 0.1058 | 0.0279 | 0.842 | near miss (metric threshold) |
| cod_2017665 | inorganic | P -3 | P -3 | 0.3541 | 0.0476 | 0.857 | solution did not refine (R1>0.20) |
| cod_1550313 | organic | P 21 21 21 | P 1 21/m 1 | 0.2941 | 0.0666 | 0.861 | wrong space group |
| cod_2216510 | hard-disorder | P -1 | P -1 | 0.2158 | 0.0614 | 0.873 | solution did not refine (R1>0.20) |