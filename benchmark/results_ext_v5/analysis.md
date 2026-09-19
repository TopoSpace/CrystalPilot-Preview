# CrystalPilot capability-boundary analysis

101 cases | solved 48/101 (48%) | SG top-1 88% (89/101) | mean R1 0.141 | mean human R1 0.04

### By chemistry category

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| mof | 38 | 55% (21/38) | 89% (34/38) | 0.117 | 0.082 |
| organic | 28 | 64% (18/28) | 89% (25/28) | 0.157 | 0.11 |
| inorganic | 13 | 8% (1/13) | 77% (10/13) | 0.194 | 0.163 |
| hard-P1 | 5 | 40% (2/5) | 100% (5/5) | 0.104 | 0.07 |
| hard-twin | 5 | 40% (2/5) | 60% (3/5) | 0.181 | 0.146 |
| hard-pseudo | 4 | 0% (0/4) | 100% (4/4) | 0.13 | 0.078 |
| hard-large | 4 | 50% (2/4) | 100% (4/4) | 0.159 | 0.11 |
| hard-disorder | 4 | 50% (2/4) | 100% (4/4) | 0.115 | 0.063 |

### By vendor family

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| Bruker | 63 | 52% (33/63) | 90% (57/63) | 0.135 | 0.095 |
| Oxford-Agilent | 12 | 42% (5/12) | 83% (10/12) | 0.127 | 0.087 |
| Nonius | 12 | 42% (5/12) | 83% (10/12) | 0.163 | 0.124 |
| Rigaku | 8 | 38% (3/8) | 75% (6/8) | 0.19 | 0.146 |
| Stoe | 5 | 20% (1/5) | 100% (5/5) | 0.139 | 0.101 |
| other | 1 | 100% (1/1) | 100% (1/1) | 0.133 | 0.07 |

### By crystal system (reference)

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| monoclinic | 59 | 51% (30/59) | 92% (54/59) | 0.142 | 0.104 |
| triclinic | 20 | 50% (10/20) | 90% (18/20) | 0.143 | 0.1 |
| orthorhombic | 13 | 54% (7/13) | 77% (10/13) | 0.135 | 0.092 |
| trigonal | 4 | 0% (0/4) | 75% (3/4) | 0.227 | 0.182 |
| hexagonal | 3 | 0% (0/3) | 100% (3/3) | 0.064 | 0.02 |
| tetragonal | 2 | 50% (1/2) | 50% (1/2) | 0.139 | 0.109 |

### By reflection count

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| <5k | 49 | 63% (31/49) | 88% (43/49) | 0.147 | 0.107 |
| <15k | 30 | 30% (9/30) | 87% (26/30) | 0.124 | 0.083 |
| <2k | 18 | 44% (8/18) | 89% (16/18) | 0.145 | 0.112 |
| >=15k | 4 | 0% (0/4) | 100% (4/4) | 0.225 | 0.162 |

### By cell volume (Å³)

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| <3k | 52 | 50% (26/52) | 85% (44/52) | 0.14 | 0.102 |
| <1k | 27 | 52% (14/27) | 89% (24/27) | 0.147 | 0.111 |
| <10k | 17 | 35% (6/17) | 94% (16/17) | 0.133 | 0.086 |
| >=10k | 5 | 40% (2/5) | 100% (5/5) | 0.159 | 0.11 |

### Failure taxonomy

| failure mode | n | example cases |
|---|---|---|
| near miss (metric threshold) | 18 | cod_2019928, cod_2020889, cod_2022918, cod_2207435 |
| solution did not refine (R1>0.20) | 11 | cod_2210623, cod_2216484, cod_2221198, cod_2215805 |
| wrong space group | 8 | cod_2108482, cod_2108685, cod_2210622, cod_2220958 |
| heavy ok, light atoms wrong/missing | 6 | cod_2015536, cod_2021267, cod_2021268, cod_2108128 |
| pipeline-error | 6 | cod_2020930, cod_2021706, cod_2200897, cod_1560983 |
| wrong solution (low atom match) | 3 | cod_2011217, cod_2104205, cod_2207378 |
| crash: RuntimeError | 1 | cod_2108510 |

### Worst cases (unsolved, by atom-match)

| case | category | true SG | used SG | R1 | human R1 | match | failure |
|---|---|---|---|---|---|---|---|
| cod_2020930 | mof | P 1 21/n 1 | P 1 21/n 1 | - | 0.0267 | - | pipeline-error |
| cod_2021706 | mof | P 1 21/n 1 | P 1 21/n 1 | - | 0.0353 | - | pipeline-error |
| cod_2108482 | mof | C 1 2/c 1 | C 1 n 1 | 0.0566 | 0.0312 | 0.0 | wrong space group |
| cod_2220958 | mof | P n a 21 | P n a m | 0.1976 | 0.0338 | 0.0 | wrong space group |
| cod_2200897 | organic | P 1 21 1 | P 1 21 1 | - | 0.0342 | - | pipeline-error |
| cod_1560983 | inorganic | P 1 21/c 1 | P n c m | - | 0.0415 | - | pipeline-error |
| cod_2104205 | inorganic | I 1 a 1 | I 1 c 1 | 0.1207 | 0.0226 | 0.0 | wrong solution (low atom match) |
| cod_2108510 | inorganic | R 3 2 :H | - | - | 0.0231 | - | crash: RuntimeError |
| cod_2021406 | hard-large | C 2 2 21 | C 2 2 21 | - | 0.0693 | - | pipeline-error |
| cod_2020639 | hard-twin | P 1 21/c 1 | P 1 21/c 1 | - | 0.0893 | - | pipeline-error |
| cod_2020921 | hard-twin | P 1 21/c 1 | A b a 2 (2*y,-x,y+z) | 0.2745 | 0.0384 | 0.0 | wrong space group |
| cod_2022987 | hard-twin | P 1 21/c 1 | P 2 c m | 0.193 | 0.0329 | 0.0 | wrong space group |
| cod_2015536 | mof | P 1 21/c 1 | P 1 21/c 1 | 0.0667 | 0.037 | 0.131 | heavy ok, light atoms wrong/missing |
| cod_2211653 | inorganic | C 1 2/c 1 | C 1 2/n 1 | 0.2372 | 0.0328 | 0.143 | solution did not refine (R1>0.20) |
| cod_2011217 | inorganic | P 1 2/c 1 | P 1 2/c 1 | 0.1468 | 0.026 | 0.163 | wrong solution (low atom match) |
| cod_2020318 | hard-large | C 1 2 1 | C 1 2 1 | 0.2758 | 0.0521 | 0.203 | solution did not refine (R1>0.20) |
| cod_2216484 | mof | P 1 21/n 1 | P 1 21/n 1 | 0.3507 | 0.0469 | 0.25 | solution did not refine (R1>0.20) |
| cod_2108685 | mof | P -1 | P 1 | 0.2561 | 0.0236 | 0.256 | wrong space group |
| cod_2021267 | mof | P 65 | P 65 | 0.0375 | 0.052 | 0.258 | heavy ok, light atoms wrong/missing |
| cod_2210623 | mof | P c c a | P c c a | 0.4043 | 0.0446 | 0.281 | solution did not refine (R1>0.20) |
| cod_2220037 | organic | P -1 | P -1 | 0.3522 | 0.0606 | 0.294 | solution did not refine (R1>0.20) |
| cod_2207378 | inorganic | P 63 m c | P 63 m c | 0.112 | 0.0422 | 0.333 | wrong solution (low atom match) |
| cod_2215805 | organic | P -1 | P -1 | 0.3473 | 0.0539 | 0.348 | solution did not refine (R1>0.20) |
| cod_2021268 | mof | P 61 | P 61 | 0.0437 | 0.04 | 0.409 | heavy ok, light atoms wrong/missing |
| cod_2108128 | mof | C 1 2 1 | C 1 2 1 | 0.1814 | 0.0335 | 0.5 | heavy ok, light atoms wrong/missing |
| cod_2022996 | inorganic | C 1 2/m 1 | C 1 2/m 1 | 0.2633 | 0.026 | 0.6 | solution did not refine (R1>0.20) |
| cod_2104873 | hard-P1 | P 1 | P 1 | 0.1667 | 0.0269 | 0.606 | heavy ok, light atoms wrong/missing |
| cod_2013470 | inorganic | C 1 2/m 1 | C 1 2/m 1 | 0.4196 | 0.0264 | 0.667 | solution did not refine (R1>0.20) |
| cod_2015958 | hard-P1 | P 1 | P 1 | 0.0613 | 0.0179 | 0.688 | heavy ok, light atoms wrong/missing |
| cod_2018446 | hard-disorder | P 32 2 1 | P 32 2 1 | 0.0687 | 0.0406 | 0.703 | near miss (metric threshold) |
| cod_2019928 | mof | P 1 2/c 1 | P 1 2/c 1 | 0.0949 | 0.0384 | 0.722 | near miss (metric threshold) |
| cod_2016126 | organic | P 1 21 1 | P 1 21/m 1 | 0.3331 | 0.0391 | 0.8 | wrong space group |
| cod_2016244 | inorganic | P 21 21 21 | P n m a | 0.1581 | 0.0216 | 0.833 | wrong space group |
| cod_2018533 | organic | P 1 21/n 1 | P 1 21/n 1 | 0.1058 | 0.0279 | 0.842 | near miss (metric threshold) |
| cod_2017665 | inorganic | P -3 | P -3 | 0.3541 | 0.0476 | 0.857 | solution did not refine (R1>0.20) |
| cod_2216510 | hard-disorder | P -1 | P -1 | 0.2158 | 0.0614 | 0.873 | solution did not refine (R1>0.20) |
| cod_2020889 | mof | C 1 2/c 1 | C 1 2/c 1 | 0.0459 | 0.0208 | 0.923 | near miss (metric threshold) |
| cod_2218002 | hard-pseudo | P 1 21/c 1 | P 1 21/c 1 | 0.1741 | 0.0734 | 0.927 | near miss (metric threshold) |
| cod_2213662 | hard-pseudo | P 1 21 1 | P 1 21 1 | 0.1199 | 0.039 | 0.944 | near miss (metric threshold) |
| cod_2022918 | mof | C 1 2/c 1 | C 1 2/n 1 | 0.131 | 0.0345 | 1.0 | near miss (metric threshold) |