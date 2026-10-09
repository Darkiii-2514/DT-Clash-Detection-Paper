"""Export structural + MEP elements of a host model and its links to JSON Lines.

Output (one folder per export):
    meta.json            model, links, transforms, levels, timings
    elements.jsonl       one element per line (geometry in metres, host coords)
    revit_reference.jsonl  structural/MEP pairs Revit itself reports as intersecting
                           (ElementIntersectsSolidFilter) - used as detection ground truth

All coordinates are transformed into the HOST document's internal coordinate
system and converted from feet to metres, so elements from different links
can be compared directly.
"""
from __future__ import print_function

import json
import numbers
import re
import os
import time

from Autodesk.Revit import DB

FT = 0.3048
FT3 = FT ** 3

STRUCT_BICS = [
    DB.BuiltInCategory.OST_StructuralColumns,
    DB.BuiltInCategory.OST_StructuralFraming,
    DB.BuiltInCategory.OST_StructuralFoundation,
    DB.BuiltInCategory.OST_Floors,
    DB.BuiltInCategory.OST_Walls,
]
MEP_BICS = [
    DB.BuiltInCategory.OST_DuctCurves,
    DB.BuiltInCategory.OST_DuctFitting,
    DB.BuiltInCategory.OST_DuctAccessory,
    DB.BuiltInCategory.OST_FlexDuctCurves,
    DB.BuiltInCategory.OST_PipeCurves,
    DB.BuiltInCategory.OST_PipeFitting,
    DB.BuiltInCategory.OST_PipeAccessory,
    DB.BuiltInCategory.OST_FlexPipeCurves,
    DB.BuiltInCategory.OST_CableTray,
    DB.BuiltInCategory.OST_CableTrayFitting,
    DB.BuiltInCategory.OST_Conduit,
    DB.BuiltInCategory.OST_ConduitFitting,
    DB.BuiltInCategory.OST_MechanicalEquipment,
    DB.BuiltInCategory.OST_Sprinklers,
]
MAX_TRIANGLES = 20000


# ---------------------------------------------------------------- helpers
def dumps(obj):
    """Minimal JSON writer: IronPython 2.7's json chokes on non-ASCII Revit names
    (e.g. German model content), so escape every non-ASCII char as \\uXXXX ourselves."""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, numbers.Integral):
        return str(int(obj))
    if isinstance(obj, float):
        return repr(obj) if obj == obj and obj not in (float("inf"), float("-inf")) else "null"
    if isinstance(obj, dict):
        return "{" + ",".join(_jstr(k) + ":" + dumps(v) for k, v in obj.items()) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(dumps(v) for v in obj) + "]"
    return _jstr(obj)


def _jstr(s):
    try:
        s = unicode(s)  # noqa: F821  (IronPython 2.7)
    except NameError:
        s = str(s)
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif o > 0xffff:                       # astral char (CPython 3): surrogate pair
            o -= 0x10000
            out.append("\\u%04x\\u%04x" % (0xd800 + (o >> 10), 0xdc00 + (o & 0x3ff)))
        elif o < 0x20 or o > 0x7e:
            out.append("\\u%04x" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def id_val(eid):
    """ElementId -> int (Revit 2024+ uses .Value; older .IntegerValue)."""
    try:
        return int(eid.Value)
    except AttributeError:
        return int(eid.IntegerValue)


def name_of(elem):
    if elem is None:
        return None
    try:
        return DB.Element.Name.__get__(elem)
    except Exception:
        try:
            return elem.Name
        except Exception:
            return None


def bic_name(elem):
    cat = elem.Category
    if cat is None:
        return None
    try:
        return str(cat.BuiltInCategory)  # Revit 2023+
    except Exception:
        import System
        return str(System.Enum.ToObject(DB.BuiltInCategory, id_val(cat.Id)))


def _param(elem, bip):
    """bip may be a BuiltInParameter or its name; unknown names (API drift) give None."""
    if isinstance(bip, str):
        bip = getattr(DB.BuiltInParameter, bip, None)
        if bip is None:
            return None
    try:
        return elem.get_Parameter(bip)
    except Exception:
        return None


def p_double(elem, bip, scale=FT):
    p = _param(elem, bip)
    if p is None or not p.HasValue or p.StorageType != DB.StorageType.Double:
        return None
    return round(p.AsDouble() * scale, 5)


def p_str(elem, bip):
    p = _param(elem, bip)
    if p is None or not p.HasValue:
        return None
    s = p.AsValueString() if p.StorageType != DB.StorageType.String else p.AsString()
    return s


def p_int(elem, bip):
    p = _param(elem, bip)
    if p is None or not p.HasValue or p.StorageType != DB.StorageType.Integer:
        return None
    return p.AsInteger()


def lookup_double(elem, names, scale=FT):
    """First numeric parameter found by name on the instance, then its type."""
    doc = elem.Document
    etype = doc.GetElement(elem.GetTypeId())
    for holder in (elem, etype):
        if holder is None:
            continue
        for n in names:
            p = holder.LookupParameter(n)
            if p is not None and p.HasValue and p.StorageType == DB.StorageType.Double:
                return round(p.AsDouble() * scale, 5)
    return None


def xyz(t, p):
    q = t.OfPoint(p)
    return [round(q.X * FT, 4), round(q.Y * FT, 4), round(q.Z * FT, 4)]


# ---------------------------------------------------------------- geometry
_GEOM_OPTS = None


def geom_options():
    global _GEOM_OPTS
    if _GEOM_OPTS is None:
        o = DB.Options()
        o.DetailLevel = DB.ViewDetailLevel.Fine
        o.ComputeReferences = False
        o.IncludeNonVisibleObjects = False
        _GEOM_OPTS = o
    return _GEOM_OPTS


def iter_solids(geom):
    if geom is None:
        return
    for g in geom:
        if isinstance(g, DB.Solid):
            if g.Volume > 1e-9 and g.Faces.Size > 0:
                yield g
        elif isinstance(g, DB.GeometryInstance):
            for s in iter_solids(g.GetInstanceGeometry()):
                yield s


def element_solids(elem):
    return list(iter_solids(elem.get_Geometry(geom_options())))


_TESS = None


def tess_controls():
    global _TESS
    if _TESS is None:
        c = DB.SolidOrShellTessellationControls()
        c.LevelOfDetail = 0.3
        c.MinAngleInTriangle = 0.0
        _TESS = c
    return _TESS


def mesh_of_solids(solids, t):
    """Indexed triangle mesh (metres, host coords) of a list of solids."""
    verts, faces, index = [], [], {}

    def vid(p):
        v = xyz(t, p)
        k = (v[0], v[1], v[2])
        i = index.get(k)
        if i is None:
            i = len(verts)
            index[k] = i
            verts.append(v)
        return i

    for s in solids:
        try:
            tri = DB.SolidUtils.TessellateSolidOrShell(s, tess_controls())
            for ci in range(tri.ShellComponentCount):
                comp = tri.GetShellComponent(ci)
                local = [vid(comp.GetVertex(k)) for k in range(comp.VertexCount)]
                for k in range(comp.TriangleCount):
                    tr = comp.GetTriangle(k)
                    faces.append([local[tr.VertexIndex0], local[tr.VertexIndex1], local[tr.VertexIndex2]])
        except Exception:
            # fallback: per-face triangulation (not guaranteed watertight)
            for f in s.Faces:
                m = f.Triangulate(0.5)
                for k in range(m.NumTriangles):
                    tr = m.get_Triangle(k)
                    faces.append([vid(tr.get_Vertex(0)), vid(tr.get_Vertex(1)), vid(tr.get_Vertex(2))])
        if len(faces) > MAX_TRIANGLES:
            return verts, faces, True
    return verts, faces, False


# ---------------------------------------------------------------- classification
def is_structural(elem, bic):
    if bic in ("OST_StructuralColumns", "OST_StructuralFraming", "OST_StructuralFoundation"):
        return True
    if bic == "OST_Floors":
        return p_int(elem, DB.BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL) == 1
    if bic == "OST_Walls":
        return p_int(elem, DB.BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT) == 1
    return False


def structural_props(elem, bic):
    d = {}
    if isinstance(elem, DB.FamilyInstance):
        try:
            d["struct_type"] = str(elem.StructuralType)
        except Exception:
            pass
        try:
            d["struct_usage"] = str(elem.StructuralUsage)
        except Exception:
            pass
        try:
            d["material_type"] = str(elem.StructuralMaterialType)
        except Exception:
            pass
        d["section_h"] = (p_double(elem, DB.BuiltInParameter.STRUCTURAL_SECTION_COMMON_HEIGHT)
                          or lookup_double(elem, ["h", "d", "Height", "Depth"]))
        d["section_b"] = (p_double(elem, DB.BuiltInParameter.STRUCTURAL_SECTION_COMMON_WIDTH)
                          or lookup_double(elem, ["b", "bf", "Width"]))
        d["web_t"] = p_double(elem, "STRUCTURAL_SECTION_ISHAPE_WEBTHICKNESS")
        d["flange_t"] = p_double(elem, "STRUCTURAL_SECTION_ISHAPE_FLANGETHICKNESS")
        d["cut_length"] = p_double(elem, DB.BuiltInParameter.STRUCTURAL_FRAME_CUT_LENGTH)
    if bic == "OST_Floors":
        d["thickness"] = p_double(elem, DB.BuiltInParameter.FLOOR_ATTR_THICKNESS_PARAM)
    if bic == "OST_Walls":
        d["thickness"] = p_double(elem, DB.BuiltInParameter.WALL_ATTR_WIDTH_PARAM)
        d["wall_usage"] = p_str(elem, DB.BuiltInParameter.WALL_STRUCTURAL_USAGE_PARAM)
    d["material"] = p_str(elem, DB.BuiltInParameter.STRUCTURAL_MATERIAL_PARAM)
    d["volume"] = p_double(elem, DB.BuiltInParameter.HOST_VOLUME_COMPUTED, FT3)
    return dict((k, v) for k, v in d.items() if v is not None)


def mep_props(elem):
    B = DB.BuiltInParameter
    d = {
        "diameter": p_double(elem, B.RBS_CURVE_DIAMETER_PARAM),
        "outer_diameter": p_double(elem, B.RBS_PIPE_OUTER_DIAMETER) or p_double(elem, B.RBS_CONDUIT_OUTER_DIAM_PARAM),
        "width": p_double(elem, B.RBS_CURVE_WIDTH_PARAM) or p_double(elem, B.RBS_CABLETRAY_WIDTH_PARAM),
        "height": p_double(elem, B.RBS_CURVE_HEIGHT_PARAM) or p_double(elem, B.RBS_CABLETRAY_HEIGHT_PARAM),
        "insulation": p_double(elem, B.RBS_REFERENCE_INSULATION_THICKNESS),
        "system": p_str(elem, B.RBS_SYSTEM_CLASSIFICATION_PARAM),
        "system_type": p_str(elem, B.RBS_DUCT_SYSTEM_TYPE_PARAM) or p_str(elem, B.RBS_PIPING_SYSTEM_TYPE_PARAM),
    }
    return dict((k, v) for k, v in d.items() if v is not None)


def level_of(elem):
    doc = elem.Document
    B = DB.BuiltInParameter
    for bip in (B.INSTANCE_REFERENCE_LEVEL_PARAM, B.FAMILY_BASE_LEVEL_PARAM, B.LEVEL_PARAM,
                B.RBS_START_LEVEL_PARAM, B.WALL_BASE_CONSTRAINT, B.SCHEDULE_LEVEL_PARAM):
        try:
            p = elem.get_Parameter(bip)
        except Exception:
            continue
        if p is not None and p.HasValue and p.StorageType == DB.StorageType.ElementId:
            lv = doc.GetElement(p.AsElementId())
            if isinstance(lv, DB.Level):
                return name_of(lv)
    try:
        lv = doc.GetElement(elem.LevelId)
        if isinstance(lv, DB.Level):
            return name_of(lv)
    except Exception:
        pass
    return None


def location_of(elem, t):
    loc = elem.Location
    if isinstance(loc, DB.LocationCurve):
        c = loc.Curve
        return {"kind": "curve", "p0": xyz(t, c.GetEndPoint(0)), "p1": xyz(t, c.GetEndPoint(1))}
    if isinstance(loc, DB.LocationPoint):
        return {"kind": "point", "p": xyz(t, loc.Point)}
    return None


def joins_of(elem, tag):
    """Elements Revit itself joins to this one (framing end joins + geometry joins)."""
    out = set()
    loc = elem.Location
    if isinstance(loc, DB.LocationCurve) and isinstance(elem, DB.FamilyInstance):
        for end in (0, 1):
            try:
                for j in loc.get_ElementsAtJoin(end):
                    out.add("%s:%s" % (tag, j.UniqueId))
            except Exception:
                pass
    try:
        for jid in DB.JoinGeometryUtils.GetJoinedElements(elem.Document, elem):
            j = elem.Document.GetElement(jid)
            if j is not None:
                out.add("%s:%s" % (tag, j.UniqueId))
    except Exception:
        pass
    return sorted(out)


def bbox_of(elem, t):
    bb = elem.get_BoundingBox(None)
    if bb is None:
        return None
    pts = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                pts.append(xyz(t, bb.Transform.OfPoint(DB.XYZ(x, y, z))))
    mins = [min(p[i] for p in pts) for i in range(3)]
    maxs = [max(p[i] for p in pts) for i in range(3)]
    return mins + maxs


# ---------------------------------------------------------------- collection
def multicat_filter(bics):
    from System.Collections.Generic import List
    lst = List[DB.BuiltInCategory]()
    for b in bics:
        lst.Add(b)
    return DB.ElementMulticategoryFilter(lst)


def collect(doc, bics):
    return (DB.FilteredElementCollector(doc)
            .WherePasses(multicat_filter(bics))
            .WhereElementIsNotElementType()
            .ToElements())


def doc_tag(doc):
    """Stable document tag used in element uids: file name, spaces -> underscores."""
    return os.path.splitext(os.path.basename(doc.PathName or doc.Title))[0].replace(" ", "_")


def transform_rows(t):
    """4x3 transform (origin + basis) in metres, for reproducibility of link placement."""
    return {"origin": [round(t.Origin.X * FT, 6), round(t.Origin.Y * FT, 6), round(t.Origin.Z * FT, 6)],
            "basis_x": [round(t.BasisX.X, 9), round(t.BasisX.Y, 9), round(t.BasisX.Z, 9)],
            "basis_y": [round(t.BasisY.X, 9), round(t.BasisY.Y, 9), round(t.BasisY.Z, 9)],
            "basis_z": [round(t.BasisZ.X, 9), round(t.BasisZ.Y, 9), round(t.BasisZ.Z, 9)]}


def doc_sources(host, tag_of_host):
    """[(tag, doc, transform_to_host, link_instance_name)] for host + loaded links."""
    out = [(tag_of_host, host, DB.Transform.Identity, None)]
    seen = set()
    for li in DB.FilteredElementCollector(host).OfClass(DB.RevitLinkInstance):
        ld = li.GetLinkDocument()
        if ld is None:
            continue
        tag = doc_tag(ld)
        if tag in seen:  # same link placed twice: keep first instance only
            continue
        seen.add(tag)
        out.append((tag, ld, li.GetTotalTransform(), name_of(li)))
    return out


def element_record(elem, tag, t, role):
    bic = bic_name(elem)
    doc = elem.Document
    etype = doc.GetElement(elem.GetTypeId())
    rec = {
        "uid": "%s:%s" % (tag, elem.UniqueId),
        "id": id_val(elem.Id),
        "doc": tag,
        "role": role,
        "bic": bic,
        "category": elem.Category.Name if elem.Category else None,
        "family": getattr(etype, "FamilyName", None) if etype is not None else None,
        "type": name_of(etype),
        "level": level_of(elem),
        "location": location_of(elem, t),
        "bbox": bbox_of(elem, t),
    }
    rec["props"] = structural_props(elem, bic) if role == "structural" else mep_props(elem)
    if role == "structural":
        rec["joins"] = joins_of(elem, tag)
    solids = element_solids(elem)
    verts, faces, truncated = mesh_of_solids(solids, t)
    rec["mesh"] = {"v": verts, "f": faces, "truncated": truncated, "n_solids": len(solids)}
    return rec, solids


# ---------------------------------------------------------------- reference (Revit-native) intersections
def solid_outline(solid):
    bb = solid.GetBoundingBox()
    pts = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                pts.append(bb.Transform.OfPoint(DB.XYZ(x, y, z)))
    lo = DB.XYZ(min(p.X for p in pts), min(p.Y for p in pts), min(p.Z for p in pts))
    hi = DB.XYZ(max(p.X for p in pts), max(p.Y for p in pts), max(p.Z for p in pts))
    return DB.Outline(lo, hi)


def reference_pairs(struct_items, mep_sources, out):
    """For every structural solid, ask Revit which MEP elements intersect it."""
    mep_filter = multicat_filter(MEP_BICS)
    n = 0
    for (suid, solids, ts) in struct_items:
        for (mtag, mdoc, tm) in mep_sources:
            tx = tm.Inverse.Multiply(ts)  # structural doc coords -> MEP doc coords
            hits = set()
            for s in solids:
                try:
                    st = DB.SolidUtils.CreateTransformed(s, tx)
                    col = (DB.FilteredElementCollector(mdoc)
                           .WherePasses(mep_filter)
                           .WhereElementIsNotElementType()
                           .WherePasses(DB.BoundingBoxIntersectsFilter(solid_outline(st)))
                           .WherePasses(DB.ElementIntersectsSolidFilter(st)))
                    for e in col:
                        hits.add("%s:%s" % (mtag, e.UniqueId))
                except Exception:
                    continue
            for h in sorted(hits):
                out.write(dumps({"structural": suid, "mep": h}) + "\n")
                n += 1
    return n


# ---------------------------------------------------------------- entry point
_UID_RE = re.compile(r'"uid":"((?:[^"\\]|\\.)*)"')


def _resume_state(path):
    """Complete records left by an interrupted export: ({uid: truncated_flag}, [lines]).
    A record counts only if its line is whole (newline-terminated JSON object)."""
    done, lines = {}, []
    if not os.path.exists(path):
        return done, lines
    with open(path) as f:
        for line in f:
            if not line.endswith("\n"):
                break                                   # torn final write
            s = line.rstrip("\n")
            if not (s.startswith("{") and s.endswith("}")):
                continue
            m = _UID_RE.search(s)
            if m and m.group(1) not in done:
                done[m.group(1)] = 1 if '"truncated":true' in s else 0
                lines.append(line)
    return done, lines


def export(host, out_dir, host_tag=None, with_reference=True, struct_from_host_only=True, log=print,
           resume=False):
    """struct_from_host_only: take structural elements only from the host model, so
    'structural' floors/walls duplicated in an architectural link are not double counted."""
    t0 = time.time()
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    host_tag = host_tag or doc_tag(host)
    sources = doc_sources(host, host_tag)
    meta = {
        "host": host.PathName,
        "host_tag": host_tag,
        "revit_version": host.Application.VersionNumber,
        "revit_build": host.Application.VersionBuild,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "units": "m",
        "sources": [],
        "levels": [],
        "counts": {},
    }
    for lv in DB.FilteredElementCollector(host).OfClass(DB.Level):
        meta["levels"].append({"name": name_of(lv), "elevation": round(lv.Elevation * FT, 4)})

    struct_items, mep_sources = [], []
    n_struct = n_mep = n_trunc = 0
    path = os.path.join(out_dir, "elements.jsonl")
    done, kept = _resume_state(path) if resume else ({}, [])
    if done:
        log("resuming: %d complete records kept from a previous export" % len(done))
    cat_time = {}
    with open(path, "w") as f:
        for line in kept:
            f.write(line)
        f.flush()
        written = 0
        for (tag, doc, t, li_name) in sources:
            src = {"tag": tag, "path": doc.PathName, "link_instance": li_name,
                   "transform": transform_rows(t), "n_struct": 0, "n_mep": 0}
            struct_elems = collect(doc, STRUCT_BICS) if (doc is host or not struct_from_host_only) else []
            for e in struct_elems:
                bic = bic_name(e)
                if not is_structural(e, bic):
                    continue
                uid = "%s:%s" % (tag, e.UniqueId)
                if uid in done:
                    # already on disk: only rebuild the solids the reference check needs
                    struct_items.append((uid, element_solids(e), t))
                    src["n_struct"] += 1
                    n_trunc += done[uid]
                    continue
                try:
                    rec, solids = element_record(e, tag, t, "structural")
                except Exception as ex:
                    log("skip %s %s: %s" % (tag, id_val(e.Id), ex))
                    continue
                if not rec["mesh"]["f"]:
                    continue
                f.write(dumps(rec) + "\n")
                written += 1
                struct_items.append((rec["uid"], solids, t))
                src["n_struct"] += 1
                n_trunc += rec["mesh"]["truncated"]
            mep = collect(doc, MEP_BICS)
            log("%s: %d MEP elements to export" % (tag, len(mep)))
            t_src = time.time()
            for k, e in enumerate(mep):
                if k and k % 250 == 0:
                    log("  %s: %d/%d MEP (%.0f s)" % (tag, k, len(mep), time.time() - t_src))
                uid = "%s:%s" % (tag, e.UniqueId)
                if uid in done:
                    src["n_mep"] += 1
                    n_trunc += done[uid]
                    continue
                te = time.time()
                try:
                    rec, _ = element_record(e, tag, t, "mep")
                except Exception as ex:
                    log("skip %s %s: %s" % (tag, id_val(e.Id), ex))
                    continue
                dt = time.time() - te
                bic = rec.get("bic")
                cat_time[bic] = cat_time.get(bic, 0.0) + dt
                if dt > 5.0:
                    log("slow element %s %s %s/%s: %.1f s, %d triangles" % (
                        tag, id_val(e.Id), bic, rec.get("family"), dt, len(rec["mesh"]["f"])))
                if not rec["mesh"]["f"]:
                    continue
                f.write(dumps(rec) + "\n")
                written += 1
                if written % 100 == 0:
                    f.flush()          # an interrupted export can resume from here
                src["n_mep"] += 1
                n_trunc += rec["mesh"]["truncated"]
            if src["n_mep"]:
                mep_sources.append((tag, doc, t))
            n_struct += src["n_struct"]
            n_mep += src["n_mep"]
            meta["sources"].append(src)
            log("%-40s struct=%5d  mep=%5d" % (tag, src["n_struct"], src["n_mep"]))
    if cat_time:
        log("MEP export time by category: " + ", ".join(
            "%s %.0f s" % (k, v) for k, v in sorted(cat_time.items(), key=lambda kv: -kv[1])))
    meta["resumed_records"] = len(done)
    meta["counts"] = {"structural": n_struct, "mep": n_mep, "truncated_meshes": n_trunc}
    meta["t_export_s"] = round(time.time() - t0, 2)

    if with_reference:
        t1 = time.time()
        with open(os.path.join(out_dir, "revit_reference.jsonl"), "w") as f:
            meta["counts"]["reference_pairs"] = reference_pairs(struct_items, mep_sources, f)
        meta["t_reference_s"] = round(time.time() - t1, 2)

    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        f.write(dumps(meta))
    log("export done: %s" % dumps(meta["counts"]))
    return meta
