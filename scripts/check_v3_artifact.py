#!/usr/bin/env python3
"""Validate v3 look, scene, directing, shot, and unit-delivery artifacts."""
import argparse, json
from pathlib import Path
from shotdesigner.casting import validate_actor_identity_set, validate_casting_brief, validate_role_profile
from shotdesigner.lookdev import validate_component, validate_look_state_plan
from shotdesigner.scene_design import validate_scene_functional_brief, validate_scene_map_binding, validate_view_set
from shotdesigner.directing_map import validate_routes
from shotdesigner.v3_gates import (
    validate_director_analysis, validate_editorial_plan, validate_executable_unit_plan,
    validate_media_implementation_plan, validate_planned_unit_plan, validate_production_spec,
    validate_shot_plan, validate_unit_delivery,
)

def read(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("kind", choices=("director-analysis","media-plan","production-spec","planned-units","role-profile","casting-brief","actor-identity-set","look-state-plan","look-component","scene-functional-brief","scene-view-set","scene-map","directing-map","shot-plan","editorial-plan","executable-units","unit-delivery")); p.add_argument("artifact",type=Path); p.add_argument("--ledger",type=Path); p.add_argument("--related",type=Path); p.add_argument("--script-refs",nargs="*",default=[]); p.add_argument("--allow-legacy-design-basis", action="store_true", help="read-only validation for pre-design-basis artifacts; never enables production"); a=p.parse_args()
    value=read(a.artifact); ledger=read(a.ledger) if a.ledger else {}
    if a.kind=="director-analysis": errors=validate_director_analysis(value,set(a.script_refs))
    elif a.kind=="media-plan": errors=validate_media_implementation_plan(value)
    elif a.kind=="production-spec": errors=validate_production_spec(value)
    elif a.kind=="planned-units": errors=validate_planned_unit_plan(value,a.script_refs)
    elif a.kind=="role-profile": errors=validate_role_profile(value,set(a.script_refs))
    elif a.kind=="casting-brief": errors=validate_casting_brief(value,set(a.script_refs))
    elif a.kind=="actor-identity-set": errors=validate_actor_identity_set(value,ledger,read(a.related)) if a.related else ["--related casting brief is required"]
    elif a.kind=="look-state-plan": errors=validate_look_state_plan(value,set(a.script_refs) if a.script_refs else None,allow_legacy=a.allow_legacy_design_basis)
    elif a.kind=="look-component": errors=validate_component(value,allow_legacy=a.allow_legacy_design_basis)
    elif a.kind=="scene-functional-brief": errors=validate_scene_functional_brief(value,allow_legacy=a.allow_legacy_design_basis)
    elif a.kind=="scene-view-set": errors=validate_view_set(value,ledger)
    elif a.kind=="scene-map": errors=validate_scene_map_binding(value,read(a.related)) if a.related else ["--related view set is required"]
    elif a.kind=="directing-map": errors=validate_routes(value)
    elif a.kind=="shot-plan": errors=validate_shot_plan(value,set(a.script_refs))
    elif a.kind=="editorial-plan": errors=validate_editorial_plan(value,value.get("unit_id"))
    elif a.kind=="executable-units": errors=validate_executable_unit_plan(value,read(a.related),ledger) if a.related else ["--related preliminary plan is required"]
    else: errors=validate_unit_delivery(value,ledger)
    print(json.dumps({"status":"失败" if errors else "通过","errors":errors},ensure_ascii=False,indent=2)); return 1 if errors else 0
if __name__=="__main__": raise SystemExit(main())
