"""Lightweight IFC (STEP) parser for the BIM Cloud Pipeline POC.

Parses ISO-10303-21 IFC files without external dependencies and extracts:
  - project / site / building / storey / space spatial structure
  - building elements (walls, slabs, roofs, doors, windows, ...)
  - property sets, quantities, materials, classifications, containment
  - tessellated geometry (IFCTRIANGULATEDFACESET) and extruded solids

Output is a plain dict ready to be serialised to structured metadata JSON and
used to build GLB/GLTF derivatives.
"""
from __future__ import annotations

import re
import math

# --------------------------------------------------------------------------- #
# STEP tokenizer + recursive-descent parser
# --------------------------------------------------------------------------- #

_NUM = r'[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?'
_ENUM = r'\.[A-Z][A-Z0-9_]*\.'
_STR = r"'(?:[^']|'')*'"
_REF = r'#\d+'
_IDENT = r'[A-Za-z_][A-Za-z0-9_]*'

TOKEN_RE = re.compile(
    rf'(?P<ref>{_REF})|(?P<enum>{_ENUM})|(?P<str>{_STR})|'
    rf'(?P<num>{_NUM})|(?P<ident>{_IDENT})|'
    rf'(?P<op>\(|\)|,|=|;|\$|\*)'
)


def _enum_value(tok: str):
    name = tok.strip('.')
    if name == 'T':
        return True
    if name == 'F':
        return False
    if name == 'U':
        return None
    return name


def tokenize(text: str):
    tokens = []
    for m in TOKEN_RE.finditer(text):
        kind = m.lastgroup
        val = m.group()
        if kind == 'ref':
            tokens.append(('ref', int(val[1:])))
        elif kind == 'enum':
            tokens.append(('val', _enum_value(val)))
        elif kind == 'str':
            tokens.append(('val', val[1:-1].replace("''", "'")))
        elif kind == 'num':
            tokens.append(('val', float(val)))
        elif kind == 'ident':
            tokens.append(('ident', val))
        elif kind == 'op':
            tokens.append((val, val))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, op):
        kind, val = self.next()
        if kind != op:
            raise ValueError(f"expected {op!r}, got {kind!r}/{val!r}")

    def parse_file(self):
        entities = {}
        while self.i < len(self.t):
            kind, val = self.peek()
            if kind is None:
                break
            if kind == 'ref':
                self.next()
                self.expect('=')
                ident_kind, type_name = self.next()
                if ident_kind != 'ident':
                    raise ValueError(f"expected type name, got {ident_kind}")
                args = self.parse_list()
                self.expect(';')
                entities[val] = (type_name, args)
            else:
                # skip stray punctuation (HEADER, ISO-10303-21, etc.)
                self.next()
        return entities

    def parse_list(self):
        self.expect('(')
        items = []
        while True:
            kind, val = self.peek()
            if kind == ')':
                self.next()
                break
            if kind == ',':
                self.next()
                continue
            items.append(self.parse_value())
        return items

    def parse_value(self):
        kind, val = self.peek()
        if kind == '(':
            return self.parse_list()
        if kind == 'ref':
            self.next()
            return val
        if kind == 'val':
            self.next()
            return val
        if kind == '$':
            self.next()
            return None
        if kind == '*':
            self.next()
            return '*'
        if kind == ',':
            raise ValueError("unexpected comma in value")
        if kind == 'ident':
            # possible typed value e.g. IFCLABEL('x') or IFCLENGTHMEASURE(1.0)
            self.next()
            if self.peek()[0] == '(':
                args = self.parse_list()
                return ('typed', val, args)
            return val
        raise ValueError(f"unexpected token {kind!r}/{val!r}")


def parse_ifc(text: str) -> dict:
    """Return {int_id: (type_name, [args...])}."""
    tokens = tokenize(text)
    return _Parser(tokens).parse_file()


# --------------------------------------------------------------------------- #
# Semantic extraction
# --------------------------------------------------------------------------- #

PRODUCT_TYPES = {
    # spatial
    'IFCPROJECT', 'IFCSITE', 'IFCBUILDING', 'IFCBUILDINGSTOREY', 'IFCSPACE',
    'IFCSPATIALZONE', 'IFCZONE',
    # building elements
    'IFCWALL', 'IFCWALLSTANDARDCASE', 'IFCWALLELEMENTEDCASE', 'IFCSLAB',
    'IFCSLABSTANDARDCASE', 'IFCROOF', 'IFCDOOR', 'IFCDOORSTANDARDCASE',
    'IFCWINDOW', 'IFCWINDOWSTANDARDCASE', 'IFCCOLUMN', 'IFCCOLUMNSTANDARDCASE',
    'IFCBEAM', 'IFCBEAMSTANDARDCASE', 'IFCSTAIR', 'IFCRAILING', 'IFCRAMP',
    'IFCMEMBER', 'IFCMEMBERSTANDARDCASE', 'IFCPLATE', 'IFCCOVERING',
    'IFCFOOTING', 'IFCPILE', 'IFCBUILDINGELEMENTPART', 'IFCBUILDINGELEMENTPROXY',
    'IFCFURNITURE', 'IFCFURNISHINGELEMENT', 'IFCSYSTEMFURNITUREELEMENT',
    'IFCCHIMNEY', 'IFCOPENINGELEMENT',
    # MEP / distribution
    'IFCFLOWTERMINAL', 'IFCFLOWSEGMENT', 'IFCFLOWFITTING', 'IFCFLOWCONTROLLER',
    'IFCDISTRIBUTIONELEMENT', 'IFCDISTRIBUTIONFLOWELEMENT',
    'IFCELECTRICALELEMENT', 'IFCEQUIPMENTELEMENT', 'IFCTRANSPORTELEMENT',
    # other
    'IFCANNOTATION', 'IFCDISCRETEACCESSORY', 'IFCFASTENER', 'IFCMECHANICALFASTENER',
}

CATEGORY_MAP = {
    'IFCWALL': 'wall', 'IFCWALLSTANDARDCASE': 'wall', 'IFCWALLELEMENTEDCASE': 'wall',
    'IFCSLAB': 'slab', 'IFCSLABSTANDARDCASE': 'slab',
    'IFCROOF': 'roof', 'IFCDOOR': 'door', 'IFCDOORSTANDARDCASE': 'door',
    'IFCWINDOW': 'window', 'IFCWINDOWSTANDARDCASE': 'window',
    'IFCCOLUMN': 'column', 'IFCCOLUMNSTANDARDCASE': 'column',
    'IFCBEAM': 'beam', 'IFCBEAMSTANDARDCASE': 'beam',
    'IFCSTAIR': 'stair', 'IFCRAILING': 'railing', 'IFCRAMP': 'ramp',
    'IFCMEMBER': 'member', 'IFCMEMBERSTANDARDCASE': 'member',
    'IFCPLATE': 'plate', 'IFCCOVERING': 'covering',
    'IFCFOOTING': 'footing', 'IFCPILE': 'pile',
    'IFCBUILDINGELEMENTPART': 'part', 'IFCBUILDINGELEMENTPROXY': 'proxy',
    'IFCFURNITURE': 'furniture', 'IFCFURNISHINGELEMENT': 'furniture',
    'IFCSYSTEMFURNITUREELEMENT': 'furniture', 'IFCCHIMNEY': 'chimney',
    'IFCOPENINGELEMENT': 'opening', 'IFCSPACE': 'space', 'IFCSPATIALZONE': 'zone',
    'IFCZONE': 'zone', 'IFCBUILDINGSTOREY': 'storey', 'IFCBUILDING': 'building',
    'IFCSITE': 'site', 'IFCPROJECT': 'project',
}


def _name(ent):
    return ent[2] if len(ent) > 2 else None


def _text(val):
    if val is None:
        return None
    if isinstance(val, tuple) and val[0] == 'typed':
        inner = val[2]
        return _text(inner[0]) if inner else None
    if isinstance(val, str):
        return val
    return None


def _num(val):
    if isinstance(val, (int, float)):
        return float(val)
    return None


def _ref(val):
    return val if isinstance(val, int) else None


class IFC2JSON:
    """Extracts a structured, neutral BIM description from parsed entities."""

    def __init__(self, entities: dict):
        self.e = entities

    # ---- helpers ---------------------------------------------------------- #
    def _get(self, rid):
        if rid is None:
            return None
        return self.e.get(rid)

    def _type(self, rid):
        e = self._get(rid)
        return e[0] if e else None

    def _entities_of(self, *types):
        out = []
        for rid, (t, args) in self.e.items():
            if t in types:
                out.append(rid)
        return out

    def _point(self, rid):
        e = self._get(rid)
        if not e or e[0] != 'IFCCARTESIANPOINT':
            return None
        return [float(v) for v in e[1][0][:3]]

    def _direction(self, rid):
        e = self._get(rid)
        if not e or e[0] != 'IFCDIRECTION':
            return None
        return [float(v) for v in e[1][0][:3]]

    def _product_placement_rep(self, rid):
        """Return (placement_id, representation_id) for a product entity."""
        e = self._get(rid)
        if not e:
            return None, None
        args = e[1]
        if len(args) < 7:
            return None, None
        pl = _ref(args[5])
        rep = _ref(args[6])
        return pl, rep

    # ---- placement -------------------------------------------------------- #
    def _axis2placement_matrix(self, rid):
        e = self._get(rid)
        if not e or e[0] != 'IFCAXIS2PLACEMENT3D':
            return _identity()
        args = e[1]
        loc = self._point(_ref(args[0])) or [0.0, 0.0, 0.0]
        axis = self._direction(_ref(args[1])) or [0.0, 0.0, 1.0]
        refd = self._direction(_ref(args[2])) or [1.0, 0.0, 0.0]
        z = _normalize(axis)
        x = _normalize(refd)
        y = _cross(z, x)
        # ensure orthonormal x (y already perpendicular to z)
        x = _cross(y, z)
        m = _identity()
        for row in range(3):
            m[row][0] = x[row]
            m[row][1] = y[row]
            m[row][2] = z[row]
            m[row][3] = loc[row]
        return m

    def _placement_matrix(self, rid):
        if rid is None:
            return _identity()
        cached = getattr(self, '_placement_cache', None)
        if cached is None:
            cached = {}
            self._placement_cache = cached
        if rid in cached:
            return cached[rid]
        e = self._get(rid)
        if not e or e[0] != 'IFCLOCALPLACEMENT':
            cached[rid] = _identity()
            return cached[rid]
        rel_to = _ref(e[1][0])
        rel_place = _ref(e[1][1])
        parent = self._placement_matrix(rel_to)
        local = self._axis2placement_matrix(rel_place)
        cached[rid] = _matmul(parent, local)
        return cached[rid]

    # ---- colours ---------------------------------------------------------- #
    def _colour_of_item(self, item_rid):
        """Resolve an IFCCOLOURRGB for a representation item via IfcStyledItem."""
        for rid, (t, args) in self.e.items():
            if t == 'IFCSTYLEDITEM' and len(args) >= 2:
                if _ref(args[0]) == item_rid:
                    styles = args[1] if isinstance(args[1], list) else []
                    for s in styles:
                        c = self._colour_of_style(_ref(s))
                        if c:
                            return c
        return None

    def _colour_of_style(self, style_rid):
        e = self._get(style_rid)
        if not e:
            return None
        if e[0] == 'IFCSURFACESTYLE':
            for s in (e[1][2] if len(e[1]) > 2 and isinstance(e[1][2], list) else []):
                c = self._colour_of_style(_ref(s))
                if c:
                    return c
        if e[0] == 'IFCSURFACESTYLERENDERING':
            if len(e[1]) >= 1:
                return self._colour_rgb(_ref(e[1][0]))
        return None

    def _colour_rgb(self, rid):
        e = self._get(rid)
        if not e or e[0] != 'IFCCOLOURRGB':
            return None
        args = e[1]
        return [float(args[1]), float(args[2]), float(args[3])]

    # ---- materials -------------------------------------------------------- #
    def _material_of(self, product_rid):
        for rid, (t, args) in self.e.items():
            if t == 'IFCRELASSOCIATESMATERIAL' and len(args) >= 6:
                rel_objs = args[4]
                if isinstance(rel_objs, list) and product_rid in [_ref(x) for x in rel_objs]:
                    mat = self._get(_ref(args[5]))
                    if mat and mat[0] == 'IFCMATERIAL':
                        return _text(mat[1][0])
        return None

    # ---- type ------------------------------------------------------------- #
    def _type_of(self, product_rid):
        for rid, (t, args) in self.e.items():
            if t == 'IFCRELDEFINESBYTYPE' and len(args) >= 6:
                rel_objs = args[4]
                if isinstance(rel_objs, list) and product_rid in [_ref(x) for x in rel_objs]:
                    typ = self._get(_ref(args[5]))
                    if typ:
                        return typ[0], _text(typ[1][2]) if len(typ[1]) > 2 else None
        return None, None

    # ---- properties & quantities ------------------------------------------ #
    def _property_sets_of(self, product_rid):
        sets = {}
        for rid, (t, args) in self.e.items():
            if t == 'IFCRELDEFINESBYPROPERTIES' and len(args) >= 6:
                rel_objs = args[4]
                if not (isinstance(rel_objs, list) and product_rid in [_ref(x) for x in rel_objs]):
                    continue
                pset = self._get(_ref(args[5]))
                if not pset:
                    continue
                if pset[0] == 'IFCPROPERTYSET':
                    name = _text(pset[1][2]) if len(pset[1]) > 2 else None
                    props = {}
                    for p in (pset[1][4] if len(pset[1]) > 4 and isinstance(pset[1][4], list) else []):
                        pe = self._get(_ref(p))
                        if not pe:
                            continue
                        if pe[0] == 'IFCPROPERTYSINGLEVALUE':
                            props[_text(pe[1][0])] = self._prop_value(pe[1][2])
                        elif pe[0] == 'IFCPROPERTYENUMERATEDVALUE':
                            vals = pe[1][2]
                            props[_text(pe[1][0])] = [_text(v) for v in vals] if isinstance(vals, list) else _text(vals)
                    sets[name] = props
                elif pset[0] == 'IFCELEMENTQUANTITY':
                    name = _text(pset[1][2]) if len(pset[1]) > 2 else None
                    quants = {}
                    for q in (pset[1][4] if len(pset[1]) > 4 and isinstance(pset[1][4], list) else []):
                        qe = self._get(_ref(q))
                        if not qe:
                            continue
                        qname = _text(qe[1][0]) if len(qe[1]) > 0 else None
                        qval = _num(qe[1][3]) if len(qe[1]) > 3 else None
                        quants[qname] = qval
                    sets[name] = quants
        return sets

    def _prop_value(self, val):
        if val is None:
            return None
        if isinstance(val, tuple) and val[0] == 'typed':
            inner = val[2]
            return inner[0] if inner else None
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, str):
            return val
        return str(val)

    # ---- classification ---------------------------------------------------- #
    def _classification_of(self, product_rid):
        for rid, (t, args) in self.e.items():
            if t == 'IFCRELASSOCIATESCLASSIFICATION' and len(args) >= 6:
                rel_objs = args[4]
                if isinstance(rel_objs, list) and product_rid in [_ref(x) for x in rel_objs]:
                    ref = self._get(_ref(args[5]))
                    if ref and ref[0] == 'IFCCLASSIFICATIONREFERENCE':
                        return _text(ref[1][1])  # identification
        return None

    # ---- containment ------------------------------------------------------- #
    def _container_of(self, product_rid):
        for rid, (t, args) in self.e.items():
            if t == 'IFCRELCONTAINEDINSPATIALSTRUCTURE' and len(args) >= 6:
                rel_objs = args[4]
                if isinstance(rel_objs, list) and product_rid in [_ref(x) for x in rel_objs]:
                    return _ref(args[5])
        return None

    # ---- geometry ---------------------------------------------------------- #
    def _representation_items(self, rep_rid):
        """Walk IfcProductDefinitionShape -> IfcShapeRepresentation -> items."""
        e = self._get(rep_rid)
        if not e:
            return []
        if e[0] == 'IFCPRODUCTDEFINITIONSHAPE':
            items = []
            for rep in (e[1][2] if len(e[1]) > 2 and isinstance(e[1][2], list) else []):
                items.extend(self._representation_items(_ref(rep)))
            return items
        if e[0] == 'IFCSHAPEREPRESENTATION':
            return [_ref(x) for x in (e[1][3] if len(e[1]) > 3 and isinstance(e[1][3], list) else [])]
        return []

    def _triangulated_faceset(self, item_rid):
        e = self._get(item_rid)
        if not e or e[0] != 'IFCTRIANGULATEDFACESET':
            return None
        args = e[1]
        coords_id = _ref(args[0])
        coord_ent = self._get(coords_id)
        if not coord_ent:
            return None
        points = coord_ent[1][0]
        indices = args[3] if len(args) > 3 and isinstance(args[3], list) else []
        verts = [[float(v) for v in p[:3]] for p in points]
        tris = [[int(i) - 1 for i in tri[:3]] for tri in indices]
        return verts, tris

    def _extruded_solid(self, item_rid):
        e = self._get(item_rid)
        if not e or e[0] != 'IFCEXTRUDEDAREASOLID':
            return None
        args = e[1]
        swept = self._get(_ref(args[0]))
        depth = float(args[3]) if len(args) > 3 and args[3] is not None else 0.0
        direction = self._direction(_ref(args[2])) or [0.0, 0.0, 1.0]
        position = self._axis2placement_matrix(_ref(args[1])) if len(args) > 1 else _identity()
        if not swept:
            return None
        profile = []
        if swept[0] == 'IFCRECTANGLEPROFILEDEF':
            xd = float(swept[1][3]) / 2.0
            yd = float(swept[1][4]) / 2.0
            profile = [[-xd, -yd], [xd, -yd], [xd, yd], [-xd, yd]]
        elif swept[0] == 'IFCARBITRARYCLOSEDPROFILEDEF':
            outer = self._get(_ref(swept[1][2]))
            if outer and outer[0] == 'IFCPOLYLINE':
                profile = [[float(v) for v in self._point(_ref(p))[:2]] for p in outer[1][0]]
        elif swept[0] == 'IFCCIRCLEPROFILEDEF':
            r = float(swept[1][3])
            profile = [[r * math.cos(a), r * math.sin(a)] for a in _arange(0, 2 * math.pi, 24)]
        if not profile or len(profile) < 3:
            return None
        return {'profile': profile, 'depth': depth, 'direction': direction, 'position': position}


# --------------------------------------------------------------------------- #
# Small numeric helpers (pure python, no numpy requirement)
# --------------------------------------------------------------------------- #

def _identity():
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    if n == 0:
        return [0.0, 0.0, 0.0]
    return [c / n for c in v]


def _cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _matmul(a, b):
    r = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            r[i][j] = sum(a[i][k] * b[k][j] for k in range(4))
    return r


def _apply(m, p):
    x, y, z = p
    return [
        m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
        m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
        m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
    ]


def _arange(start, stop, steps):
    out = []
    step = (stop - start) / steps
    for i in range(steps):
        out.append(start + step * i)
    return out


# --------------------------------------------------------------------------- #
# Top-level extraction
# --------------------------------------------------------------------------- #

def extract_model(text: str) -> dict:
    entities = parse_ifc(text)
    x = IFC2JSON(entities)

    # header / schema
    schema = 'IFC'
    for (t, args) in entities.values():
        if t == 'IFCPROJECT':
            # find units
            pass

    project = None
    sites = []
    buildings = []
    storeys = []
    spaces = []
    zones = []
    elements = []

    # spatial elements
    for rid in _sorted(entities):
        t, args = entities[rid]
        if t not in PRODUCT_TYPES:
            continue
        gid = args[0] if args and isinstance(args[0], str) else None
        name = _text(args[2]) if len(args) > 2 else None
        desc = _text(args[3]) if len(args) > 3 else None
        objtype = _text(args[4]) if len(args) > 4 else None
        tag = _text(args[7]) if len(args) > 7 else None
        cat = CATEGORY_MAP.get(t, t.lower().replace('ifc', ''))

        pl, rep = x._product_placement_rep(rid)

        if t == 'IFCPROJECT':
            project = {
                'globalId': gid, 'name': name, 'description': desc,
                'schema': schema, 'units': _extract_units(entities),
            }
            continue
        if t == 'IFCSITE':
            sites.append({'id': rid, 'globalId': gid, 'name': name, 'description': desc})
            continue
        if t == 'IFCBUILDING':
            buildings.append({'id': rid, 'globalId': gid, 'name': name, 'description': desc})
            continue
        if t == 'IFCBUILDINGSTOREY':
            storeys.append({'id': rid, 'globalId': gid, 'name': name, 'description': desc})
            continue
        if t in ('IFCSPACE', 'IFCSPATIALZONE', 'IFCZONE'):
            entry = {'id': rid, 'globalId': gid, 'name': name, 'description': desc,
                     'objectType': objtype}
            if t == 'IFCSPACE':
                spaces.append(entry)
            else:
                zones.append(entry)
            # spaces are also included as elements (they have geometry/metadata)
            elements.append(_element_entry(x, rid, t, gid, name, desc, objtype, tag, cat, pl, rep))
            continue

        elements.append(_element_entry(x, rid, t, gid, name, desc, objtype, tag, cat, pl, rep))

    # link containers
    for el in elements:
        container = x._container_of(el['id'])
        if container is not None:
            el['containedIn'] = _resolve_container_name(container, entities, storeys, buildings, sites, spaces)

    # sort elements by category then name
    elements.sort(key=lambda e: (e['category'], e.get('name') or ''))

    return {
        'schema': 'bim-metadata',
        'version': '1.0',
        'project': project,
        'spatialStructure': {
            'sites': sites, 'buildings': buildings, 'storeys': storeys,
            'spaces': spaces, 'zones': zones,
        },
        'elements': elements,
        'stats': _stats(elements),
    }


def _sorted(entities):
    return sorted(entities.keys())


def _element_entry(x, rid, t, gid, name, desc, objtype, tag, cat, pl, rep):
    type_name, _ = x._type_of(rid)
    material = x._material_of(rid)
    classification = x._classification_of(rid)
    psets = x._property_sets_of(rid)

    geometry = _extract_geometry(x, rid, pl, rep)

    is_virtual = (
        (name and name.lower() in ('origin', 'geo-reference'))
        or (objtype and objtype.lower() == 'origin')
        or (material and material.lower().startswith('virtual'))
    )

    return {
        'id': rid,
        'globalId': gid,
        'ifcType': t,
        'category': cat,
        'name': name,
        'description': desc,
        'objectType': objtype,
        'typeName': type_name,
        'material': material,
        'tag': tag,
        'classification': classification,
        'properties': psets,
        'isVirtual': is_virtual,
        'geometry': geometry,
    }


def _extract_geometry(x, rid, pl, rep):
    placement = x._placement_matrix(pl) if pl else _identity()
    verts_all = []
    tris_all = []
    colors = []
    rep_items = x._representation_items(rep)
    for item in rep_items:
        e = x._get(item)
        if not e:
            continue
        color = x._colour_of_item(item) or [0.8, 0.8, 0.8]
        if e[0] == 'IFCTRIANGULATEDFACESET':
            fs = x._triangulated_faceset(item)
            if not fs:
                continue
            verts, tris = fs
            base = len(verts_all)
            for v in verts:
                verts_all.append(_apply(placement, v))
            for tri in tris:
                if any(i >= len(verts) or i < 0 for i in tri):
                    continue
                tris_all.append([base + tri[0], base + tri[1], base + tri[2]])
                colors.append(color)
        elif e[0] == 'IFCEXTRUDEDAREASOLID':
            ex = x._extruded_solid(item)
            if not ex:
                continue
            ev, et = _extrude(ex['profile'], ex['depth'], ex['direction'])
            m = _matmul(placement, ex['position'])
            base = len(verts_all)
            for v in ev:
                verts_all.append(_apply(m, v))
            for tri in et:
                tris_all.append([base + tri[0], base + tri[1], base + tri[2]])
                colors.append(color)

    if not verts_all:
        return None
    return {
        'vertexCount': len(verts_all),
        'triangleCount': len(tris_all),
        'vertices': verts_all,
        'triangles': tris_all,
        'colors': colors,
        'color': colors[0] if colors else [0.8, 0.8, 0.8],
    }


def _extrude(profile, depth, direction):
    """Triangulate a 2D polygon extruded along `direction` by `depth`.

    Returns (vertices, triangles) in local coordinates.
    """
    # front (z=0) and back (z=depth) faces, plus side walls
    rot = _rotation_to_z(direction)
    n = len(profile)
    verts = []
    for (px, py) in profile:
        verts.append(_apply(rot, [px, py, 0.0]))
    for (px, py) in profile:
        verts.append(_apply(rot, [px, py, depth]))
    tris = []
    # side walls (quad -> 2 triangles), using 1-based wrap
    for i in range(n):
        j = (i + 1) % n
        a, b = i, j
        c, d = n + j, n + i
        tris.append([a, b, c])
        tris.append([a, c, d])
    # caps (fan triangulation)
    for i in range(1, n - 1):
        tris.append([0, i, i + 1])            # front
        tris.append([n, n + i + 1, n + i])    # back (wound opposite)
    return verts, tris


def _rotation_to_z(direction):
    """Build a rotation matrix mapping +Z to `direction`."""
    z = _normalize(direction)
    # pick an axis orthogonal to z
    ref = [0.0, 0.0, 1.0]
    if abs(z[2]) > 0.999:
        ref = [1.0, 0.0, 0.0]
    x = _normalize(_cross(ref, z))
    y = _cross(z, x)
    m = _identity()
    for row in range(3):
        m[row][0] = x[row]
        m[row][1] = y[row]
        m[row][2] = z[row]
    return m


def _extract_units(entities):
    units = {}
    for rid, (t, args) in entities.items():
        if t == 'IFCSIUNIT' and len(args) >= 2:
            utype = args[1]  # .LENGTHUNIT. etc
            prefix = args[2]
            name = args[3]
            units[utype] = f"{prefix}.{name}" if prefix else name
    return units


def _resolve_container_name(container_id, entities, storeys, buildings, sites, spaces):
    if container_id is None:
        return None
    ent = entities.get(container_id)
    if not ent:
        return None
    t = ent[0]
    name = _text(ent[1][2]) if len(ent[1]) > 2 else None
    if t == 'IFCBUILDINGSTOREY':
        return name
    if t == 'IFCBUILDING':
        return name
    if t == 'IFCSITE':
        return name
    if t == 'IFCSPACE':
        return name
    return name or t


def _stats(elements):
    by_category = {}
    total_tris = 0
    total_verts = 0
    for el in elements:
        cat = el['category']
        by_category[cat] = by_category.get(cat, 0) + 1
        g = el.get('geometry')
        if g:
            total_tris += g['triangleCount']
            total_verts += g['vertexCount']
    return {
        'totalElements': len(elements),
        'byCategory': dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
        'totalTriangles': total_tris,
        'totalVertices': total_verts,
    }
