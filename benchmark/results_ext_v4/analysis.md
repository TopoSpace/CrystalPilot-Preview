# CrystalPilot capability-boundary analysis

101 cases | solved 44/101 (44%) | SG top-1 75% (76/101) | mean R1 0.145 | mean human R1 0.04

### By chemistry category

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| mof | 38 | 55% (21/38) | 87% (33/38) | 0.121 | 0.085 |
| organic | 28 | 61% (17/28) | 89% (25/28) | 0.15 | 0.104 |
| inorganic | 13 | 8% (1/13) | 31% (4/13) | 0.176 | 0.145 |
| hard-P1 | 5 | 0% (0/5) | 20% (1/5) | 0.176 | 0.142 |
| hard-twin | 5 | 20% (1/5) | 40% (2/5) | 0.186 | 0.151 |
| hard-pseudo | 4 | 0% (0/4) | 75% (3/4) | 0.181 | 0.129 |
| hard-large | 4 | 50% (2/4) | 100% (4/4) | 0.16 | 0.11 |
| hard-disorder | 4 | 50% (2/4) | 100% (4/4) | 0.115 | 0.063 |

### By vendor family

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| Bruker | 63 | 49% (31/63) | 76% (48/63) | 0.134 | 0.094 |
| Oxford-Agilent | 12 | 33% (4/12) | 75% (9/12) | 0.135 | 0.094 |
| Nonius | 12 | 33% (4/12) | 67% (8/12) | 0.174 | 0.136 |
| Rigaku | 8 | 38% (3/8) | 75% (6/8) | 0.19 | 0.146 |
| Stoe | 5 | 20% (1/5) | 80% (4/5) | 0.175 | 0.136 |
| other | 1 | 100% (1/1) | 100% (1/1) | 0.133 | 0.07 |

### By crystal system (reference)

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| monoclinic | 59 | 49% (29/59) | 81% (48/59) | 0.139 | 0.101 |
| triclinic | 20 | 40% (8/20) | 65% (13/20) | 0.153 | 0.111 |
| orthorhombic | 13 | 46% (6/13) | 77% (10/13) | 0.138 | 0.094 |
| trigonal | 4 | 0% (0/4) | 50% (2/4) | 0.252 | 0.206 |
| hexagonal | 3 | 0% (0/3) | 67% (2/3) | 0.124 | 0.079 |
| tetragonal | 2 | 50% (1/2) | 50% (1/2) | 0.139 | 0.109 |

### By reflection count

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| <5k | 49 | 57% (28/49) | 76% (37/49) | 0.154 | 0.114 |
| <15k | 30 | 30% (9/30) | 77% (23/30) | 0.134 | 0.092 |
| <2k | 18 | 39% (7/18) | 67% (12/18) | 0.129 | 0.096 |
| >=15k | 4 | 0% (0/4) | 100% (4/4) | 0.225 | 0.162 |

### By cell volume (Å³)

| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |
|---|---|---|---|---|---|
| <3k | 52 | 50% (26/52) | 73% (38/52) | 0.144 | 0.105 |
| <1k | 27 | 37% (10/27) | 59% (16/27) | 0.149 | 0.113 |
| <10k | 17 | 35% (6/17) | 100% (17/17) | 0.14 | 0.093 |
| >=10k | 5 | 40% (2/5) | 100% (5/5) | 0.16 | 0.11 |

### Failure taxonomy

| failure mode | n | example cases |
|---|---|---|
| wrong space group | 22 | cod_2108128, cod_2108685, cod_2210622, cod_2216484 |
| near miss (metric threshold) | 16 | cod_2019928, cod_2020889, cod_2022918, cod_2207435 |
| solution did not refine (R1>0.20) | 7 | cod_2210623, cod_2221198, cod_2016126, cod_2220196 |
| pipeline-error | 6 | cod_2020930, cod_2021706, cod_2200897, cod_1560983 |
| heavy ok, light atoms wrong/missing | 4 | cod_2015536, cod_2021267, cod_2021268, cod_2104873 |
| wrong solution (low atom match) | 1 | cod_2108482 |
| crash: RuntimeError | 1 | cod_2108510 |

### Worst cases (unsolved, by atom-match)

| case | category | true SG | used SG | R1 | human R1 | match | failure |
|---|---|---|---|---|---|---|---|
| cod_2020930 | mof | P 1 21/n 1 | P 1 21/n 1 | - | 0.0267 | - | pipeline-error |
| cod_2021706 | mof | P 1 21/n 1 | P 1 21/n 1 | - | 0.0353 | - | pipeline-error |
| cod_2220958 | mof | P n a 21 | P n a m | 0.1976 | 0.0338 | 0.0 | wrong space group |
| cod_2200897 | organic | P 1 21 1 | P 1 21 1 | - | 0.0342 | - | pipeline-error |
| cod_1560983 | inorganic | P 1 21/c 1 | P n c m | - | 0.0415 | - | pipeline-error |
| cod_2104205 | inorganic | I 1 a 1 | I 1 2/c 1 | 0.1537 | 0.0226 | 0.0 | wrong space group |
| cod_2108510 | inorganic | R 3 2 :H | - | - | 0.0231 | - | crash: RuntimeError |
| cod_2021406 | hard-large | C 2 2 21 | C 2 2 21 | - | 0.0693 | - | pipeline-error |
| cod_2020639 | hard-twin | P 1 21/c 1 | P 1 21/c 1 | - | 0.0893 | - | pipeline-error |
| cod_2020921 | hard-twin | P 1 21/c 1 | A b a 2 (2*y,-x,y+z) | 0.2745 | 0.0384 | 0.0 | wrong space group |
| cod_2022987 | hard-twin | P 1 21/c 1 | P 2 c m | 0.193 | 0.0329 | 0.0 | wrong space group |
| cod_2108482 | mof | C 1 2/c 1 | C 1 2/n 1 | 0.1757 | 0.0312 | 0.075 | wrong solution (low atom match) |
| cod_2015536 | mof | P 1 21/c 1 | P 1 21/c 1 | 0.0667 | 0.037 | 0.131 | heavy ok, light atoms wrong/missing |
| cod_2211653 | inorganic | C 1 2/c 1 | C 1 2/n 1 | 0.2372 | 0.0328 | 0.143 | solution did not refine (R1>0.20) |
| cod_2020318 | hard-large | C 1 2 1 | C 1 2 1 | 0.2758 | 0.0521 | 0.203 | solution did not refine (R1>0.20) |
| cod_2011217 | inorganic | P 1 2/c 1 | P 1 c 1 | 0.1452 | 0.026 | 0.208 | wrong space group |
| cod_2108685 | mof | P -1 | P 1 | 0.2561 | 0.0236 | 0.256 | wrong space group |
| cod_2021267 | mof | P 65 | P 65 | 0.0375 | 0.052 | 0.258 | heavy ok, light atoms wrong/missing |
| cod_2210623 | mof | P c c a | P c c a | 0.4043 | 0.0446 | 0.281 | solution did not refine (R1>0.20) |
| cod_2021268 | mof | P 61 | P 61 | 0.0437 | 0.04 | 0.409 | heavy ok, light atoms wrong/missing |
| cod_2220196 | organic | P -1 | P -1 | 0.3138 | 0.0748 | 0.435 | solution did not refine (R1>0.20) |
| cod_2104873 | hard-P1 | P 1 | P 1 | 0.1667 | 0.0269 | 0.606 | heavy ok, light atoms wrong/missing |
| cod_2213662 | hard-pseudo | P 1 21 1 | P 1 21/m 1 | 0.3239 | 0.039 | 0.611 | wrong space group |
| cod_2017665 | inorganic | P -3 | P 3 | 0.4269 | 0.0476 | 0.703 | wrong space group |
| cod_2018446 | hard-disorder | P 32 2 1 | P 32 2 1 | 0.0687 | 0.0406 | 0.703 | near miss (metric threshold) |
| cod_2108128 | mof | C 1 2 1 | C 1 2/m 1 | 0.236 | 0.0335 | 0.704 | wrong space group |
| cod_2019928 | mof | P 1 2/c 1 | P 1 2/c 1 | 0.0949 | 0.0384 | 0.722 | near miss (metric threshold) |
| cod_2016126 | organic | P 1 21 1 | P 1 21 1 | 0.2629 | 0.0391 | 0.8 | solution did not refine (R1>0.20) |
| cod_2216484 | mof | P 1 21/n 1 | P 1 2/n 1 | 0.3109 | 0.0469 | 0.833 | wrong space group |
| cod_2016244 | inorganic | P 21 21 21 | P n m a | 0.1581 | 0.0216 | 0.833 | wrong space group |
| cod_2018533 | organic | P 1 21/n 1 | P 1 21/n 1 | 0.1058 | 0.0279 | 0.842 | near miss (metric threshold) |
| cod_1550313 | organic | P 21 21 21 | P 1 21/m 1 | 0.1507 | 0.0666 | 0.861 | wrong space group |
| cod_2216510 | hard-disorder | P -1 | P -1 | 0.2158 | 0.0614 | 0.873 | solution did not refine (R1>0.20) |
| cod_2215805 | organic | P -1 | P 1 | 0.1645 | 0.0539 | 0.913 | wrong space group |
| cod_2020889 | mof | C 1 2/c 1 | C 1 2/c 1 | 0.0459 | 0.0208 | 0.923 | near miss (metric threshold) |
| cod_2218002 | hard-pseudo | P 1 21/c 1 | P 1 21/c 1 | 0.1741 | 0.0734 | 0.927 | near miss (metric threshold) |
| cod_2200648 | hard-P1 | P 1 | P -1 | 0.1439 | 0.038 | 0.95 | wrong space group |
| cod_2022918 | mof | C 1 2/c 1 | C 1 2/n 1 | 0.131 | 0.0345 | 1.0 | near miss (metric threshold) |
| cod_2207435 | mof | C 1 2/c 1 | C 1 2/n 1 | 0.1267 | 0.0273 | 1.0 | near miss (metric threshold) |
| cod_2210622 | mof | I -4 | I 41/a :1 | 0.1572 | 0.037 | 1.0 | wrong space group |