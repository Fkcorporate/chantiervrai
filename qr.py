"""QR code sans dépendance (mode octet, correction M, versions 1 à 10 : jusqu'à 213 octets).
Sert à la double authentification : le QR se scanne depuis l'écran de l'ordinateur au lieu de taper la clé.
Rendu en SVG. Norme ISO/IEC 18004.
"""

# Codes de données et correction par version (niveau M) : (correction par bloc, [(nombre de blocs, octets de données)])
_BLOCKS = {1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
           6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
           10: (26, [(4, 43), (1, 44)])}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46], 10: [6, 28, 50]}

# Corps de Galois GF(256), polynôme 0x11D
_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs(data, n):
    gen = [1]
    for i in range(n):
        gen = [a ^ b for a, b in zip(gen + [0], [0] + [_mul(c, _EXP[i]) for c in gen])]
    rem = [0] * n
    for byte in data:
        f = byte ^ rem[0]
        rem = rem[1:] + [0]
        for j in range(n):
            rem[j] ^= _mul(gen[j + 1], f)
    return rem


def _codewords(data, ver):
    ec, groups = _BLOCKS[ver]
    cap = sum(n * k for n, k in groups)
    bits = [0, 1, 0, 0]                                        # mode octet
    cnt = 8 if ver < 10 else 16
    bits += [(len(data) >> i) & 1 for i in range(cnt - 1, -1, -1)]
    for b in data:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, cap * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    i = 0
    while len(words) < cap:                                    # octets de remplissage alternés
        words.append((0xEC, 0x11)[i % 2])
        i += 1
    blocks, pos = [], 0
    for n, k in groups:
        for _ in range(n):
            blocks.append(words[pos:pos + k])
            pos += k
    ecs = [_rs(b, ec) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        out += [b[i] for b in blocks if i < len(b)]
    for i in range(ec):
        out += [e[i] for e in ecs]
    return out


def _bch(value, poly, bits):
    v = value << bits
    deg = poly.bit_length() - 1
    while v.bit_length() - 1 >= deg:
        v ^= poly << (v.bit_length() - 1 - deg)
    return (value << bits) | v


_MASKS = [lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0, lambda r, c: (r + c) % 3 == 0,
          lambda r, c: (r // 2 + c // 3) % 2 == 0, lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
          lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0, lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0]


def _base(ver):
    n = 17 + 4 * ver
    m = [[None] * n for _ in range(n)]

    def finder(r0, c0):
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = r0 + r, c0 + c
                if 0 <= rr < n and 0 <= cc < n:
                    inside = 0 <= r <= 6 and 0 <= c <= 6
                    m[rr][cc] = inside and (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))
    finder(0, 0); finder(0, n - 7); finder(n - 7, 0)
    for i in range(8, n - 8):
        m[6][i] = m[i][6] = i % 2 == 0
    pos = _ALIGN[ver]
    last = len(pos) - 1
    for a, r in enumerate(pos):
        for b, c in enumerate(pos):
            if (a, b) in ((0, 0), (0, last), (last, 0)):           # pas sur les repères de coin
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = max(abs(dr), abs(dc)) != 1
    for i in range(9):                                         # réserve du format
        if m[8][i] is None:
            m[8][i] = False
        if m[i][8] is None:
            m[i][8] = False
    for i in range(8):
        m[8][n - 1 - i] = False
    for i in range(7):
        m[n - 1 - i][8] = False
    m[n - 8][8] = True                                         # module sombre
    if ver >= 7:
        v = _bch(ver, 0x1F25, 12)
        for i in range(18):
            bit = bool((v >> i) & 1)
            m[n - 11 + i % 3][i // 3] = bit
            m[i // 3][n - 11 + i % 3] = bit
    return m


def _place(base, words, mask):
    n = len(base)
    m = [row[:] for row in base]
    fixed = [[v is not None for v in row] for row in base]
    bits = [(w >> i) & 1 for w in words for i in range(7, -1, -1)]
    k, up, c = 0, True, n - 1
    while c > 0:
        if c == 6:
            c -= 1
        for i in range(n):
            r = n - 1 - i if up else i
            for cc in (c, c - 1):
                if not fixed[r][cc]:
                    b = bits[k] if k < len(bits) else 0
                    k += 1
                    m[r][cc] = bool(b) ^ _MASKS[mask](r, cc)
        up = not up
        c -= 2
    fmt = _bch((0b00 << 3) | mask, 0x537, 10) ^ 0x5412         # niveau M = 00
    fb = [bool((fmt >> i) & 1) for i in range(15)]
    for i in range(15):
        # copie autour du repère en haut à gauche
        if i < 6:
            m[i][8] = fb[i]
        elif i < 8:
            m[i + 1][8] = fb[i]
        else:
            m[8][14 - i if i > 8 else 7] = fb[i]
        # copie scindée en bas à gauche et en haut à droite
        if i < 8:
            m[8][n - 1 - i] = fb[i]
        else:
            m[n - 15 + i][8] = fb[i]
    return m


def _penalty(m):
    n, p = len(m), 0
    for grid in (m, list(map(list, zip(*m)))):
        for row in grid:
            run = 1
            for i in range(1, n):
                if row[i] == row[i - 1]:
                    run += 1
                else:
                    p += run - 2 if run >= 5 else 0
                    run = 1
            p += run - 2 if run >= 5 else 0
            s = "".join("1" if v else "0" for v in row)
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r + 1][c] == m[r][c + 1] == m[r + 1][c + 1]:
                p += 3
    dark = sum(v for row in m for v in row)
    p += 10 * (abs(dark * 100 // (n * n) - 50) // 5)
    return p


def matrix(text):
    data = text.encode("utf-8")
    for ver in range(1, 11):
        ec, groups = _BLOCKS[ver]
        cap = sum(n * k for n, k in groups)
        if 4 + (8 if ver < 10 else 16) + 8 * len(data) <= cap * 8:
            break
    else:
        raise ValueError("Texte trop long pour le QR code")
    words, base = _codewords(data, ver), _base(ver)
    return min((_place(base, words, k) for k in range(8)), key=_penalty)


def svg(text, size=220, dark="#0C2A1E", light="#FFFFFF"):
    m = matrix(text)
    n, quiet = len(m), 4
    path = "".join(f"M{c + quiet},{r + quiet}h1v1h-1z" for r in range(n) for c in range(n) if m[r][c])
    total = n + 2 * quiet
    size = total * max(3, round(size / total))     # un nombre entier de pixels par module : carrés nets, lecture fiable
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" width="{size}" height="{size}" '
            f'shape-rendering="crispEdges" role="img"><rect width="{total}" height="{total}" fill="{light}"/>'
            f'<path d="{path}" fill="{dark}"/></svg>')
