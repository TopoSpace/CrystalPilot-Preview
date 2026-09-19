import math
import sys

import gemmi


def frac_key(xyz):
    return tuple(round(v % 1.0, 6) for v in xyz)


def expanded_positions(structure, site):
    seen = set()
    positions = []
    xyz = [site.fract.x, site.fract.y, site.fract.z]
    for op_index, op in enumerate(structure.spacegroup.operations()):
        transformed = op.apply_to_xyz(xyz)
        key = frac_key(transformed)
        if key not in seen:
            seen.add(key)
            positions.append((op_index, key))
    return positions


def nearest_vector(cell, origin, target):
    raw = [target[i] - origin[i] for i in range(3)]
    shift = tuple(-math.floor(v + 0.5) for v in raw)
    wrapped = [raw[i] + shift[i] for i in range(3)]
    cart = cell.orthogonalize(gemmi.Fractional(*wrapped))
    distance = math.sqrt(cart.x * cart.x + cart.y * cart.y + cart.z * cart.z)
    return distance, (cart.x, cart.y, cart.z), shift


def angle(v1, v2):
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(a * a for a in v2))
    value = max(-1.0, min(1.0, dot / (n1 * n2)))
    return math.degrees(math.acos(value))


structure = gemmi.read_small_structure(sys.argv[1])
cu = next(site for site in structure.sites if site.element.name == "Cu")
origin = (cu.fract.x, cu.fract.y, cu.fract.z)

contacts = []
for site in structure.sites:
    if site.element.name != "O":
        continue
    for op_index, xyz in expanded_positions(structure, site):
        distance, vector, shift = nearest_vector(structure.cell, origin, xyz)
        if distance <= 3.0:
            contacts.append((distance, site.label, op_index + 1, shift, xyz, vector))

contacts.sort()
print(f"space_group={structure.spacegroup_hm}")
print("Cu--O contacts <= 3.0 A")
for distance, label, op_index, shift, xyz, vector in contacts:
    print(
        f"{label:4s} {distance:7.4f} A  symop={op_index} shift={shift} "
        f"image=({xyz[0]:.6f},{xyz[1]:.6f},{xyz[2]:.6f})"
    )

print("Nearest framework C atoms to each coordinating O")
for distance, label, op_index, shift, xyz, vector in contacts:
    if distance > 2.50:
        continue
    c_neighbors = []
    for c_site in structure.sites:
        if c_site.element.name != "C":
            continue
        for c_op_index, c_xyz in expanded_positions(structure, c_site):
            c_distance, _, c_shift = nearest_vector(structure.cell, xyz, c_xyz)
            if c_distance <= 1.80:
                c_neighbors.append((c_distance, c_site.label, c_op_index + 1, c_shift))
    c_neighbors.sort()
    description = ", ".join(
        f"{c_label} {c_distance:.4f} A (symop={c_op}, shift={c_shift})"
        for c_distance, c_label, c_op, c_shift in c_neighbors
    )
    print(f"{label:4s}: {description or 'no C within 1.80 A'}")

print("Cu multiplicity around each coordinating O")
for distance, label, op_index, shift, xyz, vector in contacts:
    if distance > 2.50:
        continue
    metal_neighbors = []
    for cu_op_index, cu_xyz in expanded_positions(structure, cu):
        cu_distance, cu_vector, cu_shift = nearest_vector(structure.cell, xyz, cu_xyz)
        if cu_distance <= 2.60:
            metal_neighbors.append((cu_distance, cu_op_index + 1, cu_shift, cu_xyz, cu_vector))
    metal_neighbors.sort()
    description = ", ".join(
        f"Cu1 {cu_distance:.4f} A (symop={cu_op}, shift={cu_shift})"
        for cu_distance, cu_op, cu_shift, _, _ in metal_neighbors
    )
    print(f"{label:4s}: {description}")
    if len(metal_neighbors) == 2:
        bridge_angle = angle(metal_neighbors[0][4], metal_neighbors[1][4])
        print(f"      Cu-{label}-Cu angle: {bridge_angle:.2f} deg")

coord = [item for item in contacts if item[0] <= 2.50]
print(f"CN(2.50 A)={len(coord)}")
print("O--Cu--O angles for contacts <= 2.50 A")
for i in range(len(coord)):
    for j in range(i + 1, len(coord)):
        a = angle(coord[i][5], coord[j][5])
        if a >= 150.0 or a <= 40.0:
            print(f"{coord[i][1]}[{i + 1}]-Cu-{coord[j][1]}[{j + 1}] {a:.2f} deg")
largest_angles = sorted(
    angle(coord[i][5], coord[j][5])
    for i in range(len(coord))
    for j in range(i + 1, len(coord))
)[-2:]
tau5 = (largest_angles[1] - largest_angles[0]) / 60.0
print(f"Addison tau5={tau5:.3f} (0=square pyramidal, 1=trigonal bipyramidal)")

cu_contacts = []
for op_index, xyz in expanded_positions(structure, cu):
    distance, _, shift = nearest_vector(structure.cell, origin, xyz)
    if 0.01 < distance <= 6.0:
        cu_contacts.append((distance, op_index + 1, shift, xyz))
cu_contacts.sort()
print("Cu--Cu contacts <= 6.0 A")
for distance, op_index, shift, xyz in cu_contacts:
    print(f"{distance:7.4f} A  symop={op_index} shift={shift} image={xyz}")

# Brown-Altermatt Cu(II)-O parameters, included as a diagnostic only.
bvs = sum(math.exp((1.679 - item[0]) / 0.37) for item in coord)
print(f"Cu(II)-O bond-valence sum (R0=1.679, B=0.37): {bvs:.3f}")
