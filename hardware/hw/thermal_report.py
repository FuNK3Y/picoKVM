"""Proof that every pad KiCad flags as starved_thermal (with the default
minimum of 2 spokes) is joined to the solid In1 GND plane, through its
plated barrel or a track to its own via.  Output: out/thermal_justification.md
(run: python3 hw/thermal_report.py > out/thermal_justification.md)."""
import pcbnew, os
mm=pcbnew.ToMM; MM=pcbnew.FromMM
b=pcbnew.LoadBoard('out/kvm_board.kicad_pcb'); b.BuildConnectivity()
L={pcbnew.F_Cu:"F.Cu",pcbnew.In1_Cu:"In1.Cu (GND plane)",pcbnew.B_Cu:"B.Cu"}
zones={(z.GetLayer()):z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname()=="GND"}
def fill_hits(item, layer):
    z=zones.get(layer)
    if not z: return False
    sh=item.GetEffectiveShape(layer)
    return z.GetFilledPolysList(layer).Collide(sh.GetBoundingBox() if False else sh) if hasattr(z.GetFilledPolysList(layer),"Collide") else False
def touches_fill(item, layer):
    z=zones[layer]; polys=z.GetFilledPolysList(layer)
    s=pcbnew.SHAPE_POLY_SET(); item.TransformShapeToPolygon(s, layer, 0, MM(0.005), pcbnew.ERROR_OUTSIDE)
    s.BooleanIntersection(polys)
    return s.Area()>0
PADS=[('C24', '2'), ('J9', '15'), ('R2', '2'), ('U10', '1'), ('U13', '8'), ('U9', '1')]
tracks=[t for t in b.GetTracks() if t.GetNetname()=="GND"]
vias=[t for t in tracks if t.GetClass()=="PCB_VIA"]
out=["| pad | type | connection to the In1 GND plane | other GND copper |","|---|---|---|---|"]
for ref,pin in PADS:
    p=[q for q in b.FindFootprintByReference(ref).Pads() if q.GetNumber()==pin][0]
    pos=(round(mm(p.GetPosition().x),2), round(mm(p.GetPosition().y),2))
    if p.GetAttribute()==pcbnew.PAD_ATTRIB_PTH:
        inner = touches_fill(p, pcbnew.In1_Cu)
        outer=[L[l] for l in (pcbnew.F_Cu,pcbnew.B_Cu) if touches_fill(p,l)]
        out.append(f"| {ref}.{pin} {pos} | plated through-hole (drill {mm(p.GetDrillSize().x):.2f} mm) | barrel joined to In1 fill: **{'yes' if inner else 'NO'}** | spokes into {', '.join(outer) or 'none'} |")
    else:
        mine=[t for t in tracks if t.GetClass()=="PCB_TRACK" and (p.HitTest(t.GetStart()) or p.HitTest(t.GetEnd()))]
        ends=[]
        for t in mine:
            for e in (t.GetStart(),t.GetEnd()):
                for v in vias:
                    if v.GetPosition()==e or v.HitTest(e): ends.append(v)
        vtxt=", ".join(f"via ({mm(v.GetPosition().x):.2f}, {mm(v.GetPosition().y):.2f}) on In1 fill: {'yes' if touches_fill(v,pcbnew.In1_Cu) else 'NO'}" for v in ends)
        sib=[q for q in p.GetParentFootprint().Pads() if q.GetNumber()!=pin and q.GetNetname()=="GND"]
        bridge=[]
        for q in sib:
            if any(q.HitTest(t.GetStart()) or q.HitTest(t.GetEnd()) for t in mine):
                qt=[t for t in tracks if t.GetClass()=="PCB_TRACK" and (q.HitTest(t.GetStart()) or q.HitTest(t.GetEnd()))]
                qv=[v for t in qt for e in (t.GetStart(),t.GetEnd()) for v in vias if v.HitTest(e)]
                bridge.append(f"{ref}.{q.GetNumber()}" + (f" (whose via ({mm(qv[0].GetPosition().x):.2f}, {mm(qv[0].GetPosition().y):.2f}) is on In1 fill: {'yes' if touches_fill(qv[0],pcbnew.In1_Cu) else 'NO'})" if qv else ""))
        out.append(f"| {ref}.{pin} {pos} | SMD | {len(mine)} track(s); {vtxt or 'no via on its own track'}{'; track to '+', '.join(bridge) if bridge else ''} | spoke into F.Cu pour: {'yes' if touches_fill(p,pcbnew.F_Cu) else 'no'} |")
print("\n".join(out), flush=True)
# outer-pour pieces that touch one of these pads and nothing else (islands)
for ref,pin in PADS:
    p=[q for q in b.FindFootprintByReference(ref).Pads() if q.GetNumber()==pin][0]
    ps=pcbnew.SHAPE_POLY_SET(); 
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        if not p.IsOnLayer(layer): continue
        ps=pcbnew.SHAPE_POLY_SET(); p.TransformShapeToPolygon(ps, layer, 0, MM(0.005), pcbnew.ERROR_OUTSIDE)
        polys=zones[layer].GetFilledPolysList(layer)
        for i in range(polys.OutlineCount()):
            s=pcbnew.SHAPE_POLY_SET(); s.AddOutline(polys.Outline(i))
            inter=pcbnew.SHAPE_POLY_SET(s); inter.BooleanIntersection(ps)
            if inter.Area()<=0: continue
            others=[q for fp in b.GetFootprints() for q in fp.Pads() if q.GetNetname()=="GND" and q.IsOnLayer(layer) and s.Collide(q.GetPosition()) and not (fp.GetReference()==ref and q.GetNumber()==pin)]
            vin=[v for v in vias if s.Collide(v.GetPosition())]
            if not others and not vin:
                bb=s.BBox()
                print(f"ISLAND {ref}.{pin} {pcbnew.LayerName(layer)}: {s.Area()/1e12:.2f} mm2 at ({mm(bb.GetLeft()):.1f},{mm(bb.GetTop()):.1f})-({mm(bb.GetRight()):.1f},{mm(bb.GetBottom()):.1f}), grounded only through {ref}.{pin}", flush=True)
os._exit(0)
