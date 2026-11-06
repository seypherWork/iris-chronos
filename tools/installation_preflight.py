"""Read-only native installation preflight. No creation, compilation or apply."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import re
import subprocess

import installation_plan as planner

ABSENT_CODES = {"namespace":"420","database":"420","user":"838","role":"883",
                "resource":"892","shared_resource":"892","required_resource":"892","application":"869"}
CLASSES = {"namespace":"Config.Namespaces","database":"Config.Databases","user":"Security.Users",
           "role":"Security.Roles","resource":"Security.Resources","shared_resource":"Security.Resources",
           "required_resource":"Security.Resources","application":"Security.Applications"}
MARKER = "CHRONOS_INSTALL_PREFLIGHT:"
BUILD = re.compile(r"\b2026\.3\.0AI \(Build 154U\)")
INSPECT_FORMAT = '{"id":{{json .Id}},"running":{{json .State.Running}},"started_at":{{json .State.StartedAt}},"image":{{json .Image}},"ports":{{json .HostConfig.PortBindings}}}'


class PreflightError(ValueError):
    pass


def require(value, code):
    if not value:
        raise PreflightError(code)


def literal(value):
    require(type(value) is str and 0 < len(value) < 300 and
            re.fullmatch(r"[A-Za-z0-9%_./:\- ]+",value) is not None, "UNSAFE_NATIVE_LITERAL")
    return '"'+value+'"'


def targets(plan):
    require(plan["status"]=="PLAN_ONLY_NOT_APPLIED" and plan["applied"] is False and
            plan["ready_for_apply"] is False, "NOT_AN_UNAPPLIED_PLAN")
    require(plan.get("schema_version")=="chronos.install-plan.v3" and
            plan.get("known_native_catalogue")==planner.KNOWN_NATIVE_CATALOGUE and
            plan.get("planned_target_count")==planner.KNOWN_NATIVE_TARGET_COUNT and
            plan.get("native_scope_complete") is False and
            plan.get("unresolved_native_effects")==list(planner.UNRESOLVED_NATIVE_EFFECTS),
            "NATIVE_SCOPE_DECLARATION_REQUIRED")
    p=plan["planned"]
    rows=[{"kind":"namespace","name":p["namespace"]}]
    rows += [{"kind":"database","name":x["name"]} for x in p["databases"].values()]
    for kind,key in (("user","users"),("role","roles"),("resource","owned_resources"),
                     ("shared_resource","shared_resources")):
        rows += [{"kind":kind,"name":name} for name in p[key]]
    rows += [{"kind":"required_resource","name":name} for name in ("%Service_EmbeddedPython","%DB_IRISSYS")]
    rows += [{"kind":"application","name":p["web_application"]["path"]},
             {"kind":"application","name":p["default_web_application"]["path"]}]
    rows += [{"kind":"directory","name":p["data_root"]},
             {"kind":"directory","name":p["production"]["data_root"]}]
    rows += [{"kind":"directory","name":x["directory"]} for x in p["databases"].values()]
    require(len(rows)==planner.KNOWN_NATIVE_TARGET_COUNT and len({(r["kind"],r["name"]) for r in rows})==len(rows), "INVALID_TARGET_SET")
    for r in rows:literal(r["name"])
    return rows


def query_script(plan, nonce):
    require(type(nonce) is str and re.fullmatch(r"[a-f0-9]{32}",nonce) is not None, "INVALID_QUERY_ID")
    rows=targets(plan)
    lines=['set result={"schema":"chronos.native-install-preflight.v1","version":($ZVersion),"sys":($Namespace="%SYS")}',
           'set result.rows=[]']
    for item in rows:
        kind,name=item["kind"],item["name"]
        if kind=="directory":
            lines += [f'set row={{"kind":"directory","name":{literal(name)},"exists":(##class(%File).Exists({literal(name)}))}}',
                      'do result.rows.%Push(row)']
            continue
        # Suppress the returned object handle. No user/account property is read.
        lines += ['set found=0,sc=0,lookupError=0',
                  f'try {{ set found=##class({CLASSES[kind]}).Exists({literal(name)},,.sc) }} catch ex {{ set found=0,sc=0,lookupError=1 }}',
                  f'set row={{"kind":"{kind}","name":{literal(name)},"exists":(found),"ok":($Select(lookupError:0,1:$System.Status.IsOK(sc))),"codes":($Select(lookupError:"LOOKUP_EXCEPTION",1:$System.Status.GetErrorCodes(sc)))}}']
        if kind=="shared_resource":
            policy=plan["planned"]["shared_resources"][name]
            require(policy["public_permission"]=="", "SHARED_PUBLIC_PERMISSIONS_FORBIDDEN")
            descriptions=policy["accepted_descriptions"]
            require(type(descriptions) is list and 0<len(descriptions)<=3, "INVALID_SHARED_DESCRIPTIONS")
            conditions="||".join('($Get(p("Description"))='+literal(d)+')' for d in descriptions)
            lines += ['set row.compatible=0',
                      f'if found,$System.Status.IsOK(sc) {{ kill p set check=##class(Security.Resources).Get({literal(name)},.p) set row.compatible=$System.Status.IsOK(check)&&($Get(p("PublicPermission"))="")&&({conditions}) }}']
        lines += ['do result.rows.%Push(row)']
    lines += [f'write !,"{MARKER}{nonce}:",result.%ToJSON(),!',"halt"]
    return "\n".join(lines)+"\n"


def truth(value):
    require(type(value) in (int,bool) and value in (0,1), "INVALID_NATIVE_BOOLEAN")
    return bool(value)


def parse_native(stdout,nonce):
    require(type(stdout) is str and len(stdout)<=65536, "INVALID_NATIVE_OUTPUT_SIZE")
    require(re.search(r"<[^<>\r\n]{1,160}>|ERROR\s+#\d+|(?:^|\n)\s*ERROR\b",stdout) is None, "NATIVE_ERROR_OUTPUT")
    prefix=MARKER+nonce+":"
    lines=[line for line in stdout.splitlines() if line.startswith(prefix)]
    require(len(lines)==1, "NATIVE_RESULT_MISSING_OR_DUPLICATE")
    try:
        value=planner.bundle.web_json(lines[0][len(prefix):].encode("utf-8"))
    except (ValueError,UnicodeError) as exc:
        raise PreflightError("INVALID_NATIVE_JSON") from exc
    require(type(value) is dict and set(value)=={"schema","version","sys","rows"}
            and value["schema"]=="chronos.native-install-preflight.v1","INVALID_NATIVE_RESULT")
    return value


def assess(plan,result):
    require(type(result["version"]) is str and BUILD.search(result["version"]) is not None,"WRONG_IRIS_BUILD")
    require(truth(result["sys"]), "NATIVE_NAMESPACE_NOT_SYS")
    expected=targets(plan)
    require(type(result["rows"]) is list and len(result["rows"])==len(expected), "INCOMPLETE_NATIVE_TARGETS")
    observed={}
    for row in result["rows"]:
        require(type(row) is dict, "INVALID_NATIVE_ROW")
        key=(row.get("kind"),row.get("name"))
        require(key not in observed, "DUPLICATE_NATIVE_TARGET")
        observed[key]=row
    require(set(observed)=={(r["kind"],r["name"]) for r in expected}, "UNEXPECTED_NATIVE_TARGETS")
    checks=[]
    for item in expected:
        kind,name=item["kind"],item["name"];row=observed[(kind,name)]
        fields={"kind","name","exists"}
        if kind!="directory":fields|={"ok","codes"}
        if kind=="shared_resource":fields|={"compatible"}
        require(set(row)==fields, "UNEXPECTED_NATIVE_FIELDS")
        exists=truth(row["exists"])
        if kind=="directory":
            status="CONFLICT" if exists else "ABSENT"
        else:
            ok=truth(row["ok"]);codes=row["codes"]
            require(type(codes) is str and len(codes)<=200, "INVALID_NATIVE_STATUS_CODES")
            known_absent=not exists and not ok and codes==ABSENT_CODES[kind]
            known_present=exists and ok and codes==""
            if not (known_absent or known_present):
                status="LOOKUP_ERROR"
            elif kind=="shared_resource":
                compatible=truth(row["compatible"])
                status=("PRESENT_COMPATIBLE" if compatible else "CONFLICT") if known_present else "ABSENT_REQUIRES_APPROVAL"
            elif kind=="required_resource":
                status="PRESENT_REQUIRED" if known_present else "MISSING_REQUIRED"
            else:
                status="CONFLICT" if known_present else "ABSENT"
        checks.append({**item,"status":status})
    failures=[x for x in checks if x["status"] in {"CONFLICT","LOOKUP_ERROR","MISSING_REQUIRED"}]
    return {"schema_version":"chronos.install-preflight.v3",
            "status":"PREFLIGHT_CONFLICTS_OR_ERRORS" if failures else "PREFLIGHT_NAMES_CLEAR_FOR_REVIEW",
            "checks":checks,"blocking_checks":len(failures),"names_clear":not failures,
            "checked_scope":"LISTED_25_NAMES_ONLY","checked_target_count":len(expected),
            "native_scope_complete":False,
            "unresolved_native_effects":list(plan["unresolved_native_effects"]),
            "applied":False,"ready_for_apply":False,"plan_sha256":plan["plan_sha256"],
            "remaining_blockers":list(plan["blockers"]),
            "limits":["This is a read-only snapshot, not a reservation or installation.",
                      "The 25 known installer targets are listed; mappings, engine health and installation intent are not verified here.",
                      "Names/resources must be rechecked immediately before any authorized mutation.",
                      "Mount mapping, networking, native compilation, identity/login and model compatibility are not verified.",
                      "Shared resource absence is a new proposed creation requiring its own approved scope."]}


def inspect_container(docker,container,expected_image,expected_started,runner=subprocess.run):
    require(type(container) is str and re.fullmatch("[a-f0-9]{64}",container) is not None,"FULL_CONTAINER_ID_REQUIRED")
    require(type(expected_image) is str and re.fullmatch("sha256:[a-f0-9]{64}",expected_image) is not None,"IMAGE_ID_REQUIRED")
    require(type(expected_started) is str and re.fullmatch(r"[0-9T:.Z\-]{20,40}",expected_started) is not None,"START_ID_REQUIRED")
    # No full inspect output: env, credentials and unrelated containers are not read.
    run=runner([str(docker),"inspect","--format",INSPECT_FORMAT,container],capture_output=True,text=True,encoding="utf-8",check=False)
    require(run.returncode==0,"CONTAINER_INSPECT_FAILED")
    try:info=planner.bundle.web_json(run.stdout.encode("utf-8"))
    except (ValueError,UnicodeError) as exc:raise PreflightError("INVALID_CONTAINER_INSPECT") from exc
    require(type(info) is dict and set(info)=={"id","running","started_at","image","ports"},"INVALID_CONTAINER_INSPECT")
    require(info["id"]==container and info["running"] is True and info["started_at"]==expected_started
            and info["image"]==expected_image and info["ports"] in ({},None),"CONTAINER_IDENTITY_OR_EXPOSURE_CHANGED")
    return info


def execute_readonly(plan,docker,container,image,started,nonce,runner=subprocess.run):
    command=query_script(plan,nonce)
    before=inspect_container(docker,container,image,started,runner)
    # Fixed read-only statements, no load/compile/job/start or account methods.
    # No automatic timeout retry; the parent process retains the live handle.
    native=runner([str(docker),"exec","-i",container,"iris","session","IRIS","-U","%SYS"],
                  input=command,capture_output=True,text=True,encoding="utf-8",check=False)
    after=inspect_container(docker,container,image,started,runner)
    require(before==after,"CONTAINER_CHANGED_DURING_PREFLIGHT")
    require(native.returncode==0,"NATIVE_COMMAND_FAILED")
    require(not getattr(native,"stderr",""),"NATIVE_STDERR_NOT_EMPTY")
    result=assess(plan,parse_native(native.stdout,nonce))
    result.update(observed_at=datetime.now(timezone.utc).isoformat(),container=before,
                  query_sha256=sha256(command.encode("utf-8")).hexdigest(),
                  preflight_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                  native_read_sessions=1,account_changes=0,model_calls=0)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("bundle","config","profile","stage-root","cloud-plan"):p.add_argument("--"+name,type=Path)
    for name in ("output","docker"):p.add_argument("--"+name,required=True,type=Path)
    for name in ("bundle-sha256","container-id","expected-image","expected-started-at"):p.add_argument("--"+name,required=True)
    args=p.parse_args(argv)
    try:
        # An existing output must not trigger another read before we discover it.
        require(not args.output.exists() and not args.output.is_symlink(),"OUTPUT_ALREADY_EXISTS")
        planner.bundle.web._directories(args.output.parent)
        require(args.docker.is_file() and args.docker.is_absolute() and args.docker.name.lower()=="docker.exe","DOCKER_EXECUTABLE_REQUIRED")
        if args.stage_root is not None:
            require(args.bundle is None and args.config is None and args.profile is None and args.cloud_plan is None,"MIXED_PREFLIGHT_INPUTS")
            from installation_stage import verify_stage
            plan=verify_stage(args.stage_root,args.bundle_sha256)
        else:
            require(all(x is not None for x in (args.bundle,args.config,args.profile)),"FRESH_PREFLIGHT_INPUTS_REQUIRED")
            plan=planner.plan_files(args.bundle,args.bundle_sha256,args.config.read_bytes(),args.profile.read_bytes(),
                                    cloud_plan_raw=args.cloud_plan.read_bytes() if args.cloud_plan else None)
        from uuid import uuid4
        result=execute_readonly(plan,args.docker,args.container_id,args.expected_image,args.expected_started_at,uuid4().hex)
        with args.output.open("x",encoding="utf-8") as f:json.dump(result,f,sort_keys=True,indent=2)
        print(json.dumps({"status":result["status"],"output":str(args.output),"blocking_checks":result["blocking_checks"],
                          "native_scope_complete":False,"checked_scope":"LISTED_25_NAMES_ONLY",
                          "ready_for_apply":False,"account_changes":0,"model_calls":0}))
        return 0 if result["names_clear"] else 1
    except (ValueError,KeyError,TypeError,OSError) as exc:
        # Do not leak arbitrary native messages, paths, property values or payload.
        code=str(exc) if isinstance(exc,(PreflightError,planner.PlanError)) else type(exc).__name__
        print(json.dumps({"status":"PREFLIGHT_REJECTED","code":code,"ready_for_apply":False}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())


