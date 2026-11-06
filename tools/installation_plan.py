"""Read-only installation planner. No apply command, services or account changes."""
from hashlib import sha256
from pathlib import Path, PureWindowsPath, PurePosixPath
import argparse
import json
import os
import re
import sys
from urllib.parse import urlsplit

import application_bundle as bundle

ROOT = Path(__file__).resolve().parents[1]
_import_path_before = list(sys.path)
try:
    sys.path.insert(0,str(ROOT/"src"))
    from chronos_transport.deployment import Profile
    from chronos_transport.guard import validate_profile_schema
    from chronos_transport.cloud_config import parse_plan as parse_cloud_plan
finally:
    sys.path[:] = _import_path_before
    del _import_path_before

FIELDS = {"version","deployment_id","host_bundle","host_data_root","host_guard_state","web_origin","native_guard_base_url"}


class PlanError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise PlanError(code)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True)


def digest(value):
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def parse_config(raw):
    require(type(raw) in (bytes,str) and len(raw)<=8192, "INVALID_CONFIG_SIZE")
    value=bundle.web_json(raw.encode("utf-8") if type(raw) is str else raw)
    require(type(value) is dict and set(value)==FIELDS, "INVALID_CONFIG_FIELDS")
    require(type(value["version"]) is int and value["version"]==3, "INVALID_CONFIG_VERSION")
    require(type(value["deployment_id"]) is str and re.fullmatch("[a-f0-9]{32}",value["deployment_id"]) is not None, "INVALID_DEPLOYMENT_ID")
    return value


def _local_path(value, *, windows):
    """Validate lexical local paths without normalizing unsafe components away.

    The explicit flavour supports unit tests; actual installation always uses
    host_path and the current host OS. Filesystem/link checks remain separate.
    """
    require(type(value) is str and 1<len(value)<240, "INVALID_HOST_PATH")
    require(not any(ord(c)<32 or ord(c)==127 for c in value), "INVALID_HOST_PATH_CHARACTER")
    if windows:
        path=PureWindowsPath(value)
        require(re.match(r"^[A-Za-z]:[/\\]",value) is not None and path.is_absolute()
                and re.fullmatch(r"[A-Za-z]:",path.drive) is not None, "LOCAL_ABSOLUTE_HOST_PATH_REQUIRED")
        parts=value.replace("\\","/").split("/")
        require(all(p not in {".","..",""} for p in parts), "UNSAFE_HOST_PATH")
        require(not any(":" in p for p in path.parts[1:]), "UNSAFE_HOST_PATH")
        require(not any(any(c in '<>"|?*' for c in p) for p in path.parts[1:]), "INVALID_WINDOWS_PATH_CHARACTER")
        require(not any(p.rstrip(". ")!=p for p in path.parts[1:]), "UNSAFE_HOST_PATH")
        require(not any(PureWindowsPath(p).is_reserved() for p in path.parts[1:]), "RESERVED_HOST_PATH")
    else:
        require(value.startswith("/") and not value.startswith("//") and "\\" not in value,
                "LOCAL_ABSOLUTE_HOST_PATH_REQUIRED")
        require(all(p not in {".","..",""} for p in value[1:].split("/")), "UNSAFE_HOST_PATH")
        path=PurePosixPath(value)
    return path


def host_path(value):
    """Accept only local absolute paths of this host, not a fixed drive letter."""
    return _local_path(value,windows=os.name=="nt")


def origin(value):
    require(type(value) is str and len(value)<=160, "INVALID_WEB_ORIGIN")
    try:
        parsed=urlsplit(value);port=parsed.port
    except ValueError:
        raise PlanError("INVALID_WEB_ORIGIN") from None
    require(parsed.scheme in {"http","https"} and parsed.hostname in {"127.0.0.1","localhost","::1"}
            and parsed.username is None and parsed.password is None and not parsed.path
            and not parsed.query and not parsed.fragment, "LOOPBACK_ORIGIN_REQUIRED")
    require(type(port) is int and 1024<=port<=65535, "EXPLICIT_NONPRIVILEGED_WEB_PORT_REQUIRED")
    host="[::1]" if parsed.hostname=="::1" else parsed.hostname
    require(value==f"{parsed.scheme}://{host}:{port}", "NONCANONICAL_WEB_ORIGIN")
    return port


# The build154 native installer inventories these known names. This is still
# a plan: it does not prove mappings, successful installation or authorization.
KNOWN_NATIVE_CATALOGUE = "Chronos.Deployment.NativeInstall.Spec/Inspect:154:v4:25"
KNOWN_NATIVE_TARGET_COUNT = 25
UNRESOLVED_NATIVE_EFFECTS = ()


def make_plan(config, manifest, manifest_sha256, profile, schema, *, cloud_plan_raw=None):
    config=parse_config(canonical(config))
    require(type(manifest_sha256) is str and re.fullmatch("[a-f0-9]{64}",manifest_sha256) is not None, "INVALID_BUNDLE_DIGEST")
    require(manifest["schema_version"]==bundle.SCHEMA and manifest["status"]==bundle.STATUS
            and manifest["installed"] is False and manifest["required_iris_build"]=="2026.3.0AI.154.0", "UNSUPPORTED_BUNDLE")
    # Re-parse programmatically supplied profiles too.
    profile=Profile.parse(canonical(profile.public()))
    cloud = None
    if profile.provider == "ollama":
        require(cloud_plan_raw is None, "LOCAL_PROVIDER_CANNOT_HAVE_CLOUD_PLAN")
        validate_profile_schema(schema,profile)
    else:
        require(cloud_plan_raw is not None, "EXPLICIT_CLOUD_PLAN_REQUIRED")
        cloud = parse_cloud_plan(cloud_plan_raw)
        require(canonical(cloud["profile"]) == canonical(profile.public()), "CLOUD_PROFILE_MISMATCH")
        require(profile.schema_sha256 == digest(schema), "CLOUD_SCHEMA_MISMATCH")
    require(profile.version==3 and profile.response_contract=="chronos.preference-extraction.v1", "E1_PROFILE_REQUIRED")
    require(config["deployment_id"]==profile.deployment_id, "DEPLOYMENT_PROFILE_MISMATCH")
    host_bundle,host_data=host_path(config["host_bundle"]),host_path(config["host_data_root"])
    require(host_bundle!=host_data and not host_data.is_relative_to(host_bundle)
            and not host_bundle.is_relative_to(host_data), "DATA_AND_BUNDLE_MUST_BE_SEPARATE")
    host_guard=host_path(config["host_guard_state"])
    for other in (host_bundle,host_data):
        require(host_guard!=other and not host_guard.is_relative_to(other)
                and not other.is_relative_to(host_guard), "GUARD_STORAGE_MUST_BE_SEPARATE")
    web_port=origin(config["web_origin"])
    require(config["native_guard_base_url"]=="http://127.0.0.1:11512/v1/", "SHARED_LOOPBACK_GUARD_REQUIRED")
    guard_port=11512
    require(web_port != guard_port and (cloud is not None or len({web_port,guard_port,profile.local_port})==3), "LOCAL_LISTENER_PORT_CONFLICT")
    require(cloud is not None or profile.provider=="ollama" and profile.local_port==11434, "LOCAL_COMPOSE_PROVIDER_REQUIRED")
    api=manifest["api_base"]
    require(type(api) is str and re.fullmatch(r"/csp/chronos(?:-[a-z0-9-]+)?/",api) is not None, "BUNDLE_API_BASE_NOT_INSTALLABLE")
    ident=config["deployment_id"]
    short=ident[:12]
    namespace="CHRONOS_"+short.upper()
    prefix="Chronos_"+short
    resource="%DB_"+prefix
    temporary_resource=resource+"_TEMP"
    access=prefix+"_Access"
    roles={prefix+"_Base":[resource+":RW",temporary_resource+":RW","%DB_IRISSYS:R",access+":U"],
           prefix+"_Read":["Chronos_Read:U"],
           prefix+"_Approve":["Chronos_Approve:U"],
           prefix+"_Python":["%Service_EmbeddedPython:U"]}
    users={prefix+"_Reader":[prefix+"_Base",prefix+"_Read"],
           prefix+"_Operator":[prefix+"_Base",prefix+"_Read",prefix+"_Approve"]}
    state=host_guard/("cloud-provider" if cloud is not None else "local-provider")
    root="/durable/chronos/"+ident
    secondary_resource="%DB_"+namespace+"SECONDARY"
    # These are explicit planned mutations, NOT executable shell commands.
    planned={
        "namespace":namespace,
        "data_root":root,
        "databases":{
            "main":{"name":namespace,"directory":root+"/db/","resource":resource,"journal":3},
            "temporary":{"name":namespace+"_TEMP","directory":root+"/temp/","resource":temporary_resource,"journal":2},
            "secondary":{"name":namespace+"SECONDARY","directory":root+"/db/"+namespace.lower()+"secondary/","resource":secondary_resource,"journal":3}},
        "default_web_application":{"path":"/csp/"+namespace.lower(),"created_implicitly_by_namespace":True,
                                   "required_final_enabled":False,"closure_phase":"AFTER_NAMESPACE_CREATION"},
        "owned_resources":[resource,temporary_resource,secondary_resource,access],
        "shared_resources":{name:{"public_permission":"", "accepted_descriptions":["Owned Chronos HTTP laboratory","Chronos supervised recovery application"],
                                  "if_present":"VERIFY_AND_REUSE_WITHOUT_MODIFICATION",
                                  "if_absent":"PROPOSE_CREATION_IN_EXPLICIT_APPROVAL_SCOPE"}
                            for name in ("Chronos_Read","Chronos_Approve")},
        "roles":roles,"users":users,
        "account_initial_state":"DISABLED_PASSWORD_SET_PRIVATELY",
        "web_application":{"path":api.rstrip("/"),"config_application":api,"origin":config["web_origin"],
                           "dispatch_class":"Chronos.Web.API","event_class":"Chronos.Web.Events",
                           "initially_enabled":False,"session_timeout_seconds":3600,"access_resource":access,
                           "authentication_methods":["PASSWORD"],"authe_enabled":32,"use_cookies":2,"cookie_path":api,
                           "session_scope":2,"user_cookie_scope":2,"group_by_id":0,"csp_zen_enabled":True,
                           "application_only_matching_role":prefix+"_Read:"+prefix+"_Python"},
        "production":{"class":"Chronos.App.Production","initially_started":False,
                      "python_root":"/opt/chronos/src","data_root":"/durable/chronos/"+ident+"/owned-destinations"},
        "model":{"base_url":config["native_guard_base_url"],"model":profile.model,
                 "profile_sha256":profile.digest,"response_contract":profile.response_contract,
                 "reasoning_effort":profile.reasoning_effort},
        "mounts":[{"host":str(host_bundle),"container":"/opt/chronos/bundle","read_only":True},
                  {"host":str(host_bundle/"src"),"container":"/opt/chronos/src","read_only":True},
                  {"host":str(host_bundle/"deployment"),"container":"/opt/chronos/deployment","read_only":True},
                  {"host":str(host_bundle/"tools"),"container":"/opt/chronos/tools","read_only":True},
                  {"host":str(host_data),"container":"/durable","read_only":False},
                  {"host":str(host_guard),"container":"/opt/chronos/runtime","read_only":False}],
        "guard":{"listen":"127.0.0.1:11512","state_directory":str(state),"allowance":str(state/"allowance.sqlite"),"profile":str(state/("plan.json" if cloud is not None else "profile.json")),
                 "profile_sha256":profile.digest,"request_limit":profile.request_limit,
                 "initialize_only_if_absent":True,"reset_allowed":False},
        "host_data_root":str(host_data),"host_guard_state":str(host_guard)}
    if cloud is not None:
        planned["guard"].update(provider="openai-chat-json", cloud_plan_sha256=digest(cloud),
                                budget_policy=cloud["policy"], key_input="PRIVATE_INTERACTIVE_CONSOLE_ONLY",
                                initialize_authorization="EXACT_CLOUD_PLAN_DIGEST", budget_initialized=False)
    return {"schema_version":"chronos.install-plan.v3","status":"PLAN_ONLY_NOT_APPLIED",
            "bundle_manifest_sha256":manifest_sha256,"configuration_sha256":digest(config),
            "profile_sha256":profile.digest,"required_iris_build":manifest["required_iris_build"],
            "planned":planned,"requires_owned_names_and_data_paths_absent":True,
            "known_native_catalogue":KNOWN_NATIVE_CATALOGUE,"planned_target_count":KNOWN_NATIVE_TARGET_COUNT,
            "native_scope_complete":False,
            "unresolved_native_effects":list(UNRESOLVED_NATIVE_EFFECTS),
            "blockers":[
                        "HUMAN_APPROVAL_OF_EXACT_ACCOUNT_AND_RESOURCE_SCOPE",
                        "LIVE_IMAGE_VERSION_NAMESPACE_DATABASE_AND_ACCOUNT_PREFLIGHT",
                        "FIXED_ORIGIN_AND_OWNED_GUARD_NETWORK_PATH_NOT_VERIFIED",
                        ("CLOUD_PAID_AUTHORIZATION_PRIVATE_KEY_TLS_AND_PROVIDER_NOT_VERIFIED" if cloud is not None
                         else "LOCAL_MODEL_COMPATIBILITY_AND_RESOURCE_HEADROOM_NOT_VERIFIED"),
                        "NATIVE_INSTALLATION_NOT_EXECUTED_OR_VERIFIED"],
            "account_changes":0,"native_calls":0,"model_calls":0,"applied":False,"ready_for_apply":False}


def checked_bundle(bundle_path, expected_sha):
    actual=bundle.web._path(bundle_path)
    checked=bundle.verify(actual,expected_sha)
    manifest=bundle.web_json(bundle.web._read(actual/bundle.MANIFEST))
    # The source tools and the bundled ones must be the same reviewed revision.
    for rel in ("tools/application_bundle.py","tools/stage_web.py","tools/installation_plan.py",
                "tools/installation_preflight.py","tools/installation_stage.py",
                "src/chronos_transport/deployment.py","src/chronos_transport/guard.py",
                "deployment/NativeInstall.cls","deployment/compose.yaml","deployment/local_provider.py",
                "src/chronos_transport/cloud_config.py","src/chronos_transport/cloud_models.py",
                "src/chronos_transport/cloud_budget.py","deployment/cloud_provider.py",
                "deployment/provider_state.py","deployment/compose.cloud.yaml") :
        require(sha256(bundle.web._read(ROOT/rel)).hexdigest()==manifest["source_sha256"][rel], "PLANNER_DEPENDENCY_DRIFT")
    return actual,checked,manifest


def bind_plan(config, manifest, manifest_sha256, profile_raw, schema, *, cloud_plan_raw=None):
    profile=Profile.parse(profile_raw)
    plan=make_plan(config,manifest,manifest_sha256,profile,schema,cloud_plan_raw=cloud_plan_raw)
    plan["planner_source_sha256"]=sha256(bundle.web._read(Path(__file__))).hexdigest()
    plan["profile_file_sha256"]=sha256(profile_raw.encode() if type(profile_raw) is str else profile_raw).hexdigest()
    if cloud_plan_raw is not None:
        plan["cloud_plan_file_sha256"]=sha256(cloud_plan_raw.encode() if type(cloud_plan_raw) is str else cloud_plan_raw).hexdigest()
        plan["cloud_plan_sha256"]=digest(parse_cloud_plan(cloud_plan_raw))
    plan["plan_sha256"]=digest(plan)
    return plan


def plan_files(bundle_path, expected_sha, config_raw, profile_raw, *, cloud_plan_raw=None):
    actual,checked,manifest=checked_bundle(bundle_path,expected_sha)
    config=parse_config(config_raw)
    require(host_path(config["host_bundle"])==host_path(str(actual)), "HOST_BUNDLE_PATH_MISMATCH")
    host_data=Path(config["host_data_root"])
    bundle.web._directories(host_data.parent)
    require(not host_data.exists() and not host_data.is_symlink(), "HOST_DATA_PATH_EXISTS")
    state=Path(config["host_guard_state"])
    bundle.web._directories(state.parent)
    require(not state.exists() and not state.is_symlink(), "GUARD_STATE_ALREADY_EXISTS")
    schema=bundle.web_json(bundle.web._read(actual/"src/chronos_transport/extraction-schema.json"))
    return bind_plan(config,manifest,checked["manifest_sha256"],profile_raw,schema,cloud_plan_raw=cloud_plan_raw)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle",required=True,type=Path)
    parser.add_argument("--bundle-sha256",required=True)
    parser.add_argument("--config",required=True,type=Path)
    parser.add_argument("--profile",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--cloud-plan",type=Path)
    args=parser.parse_args(argv)
    try:
        plan=plan_files(args.bundle,args.bundle_sha256,args.config.read_bytes(),args.profile.read_bytes(),
                        cloud_plan_raw=args.cloud_plan.read_bytes() if args.cloud_plan else None)
        # Only creates the requested report. No target data directory or allowance is made.
        with args.output.open("x",encoding="utf-8") as f:
            json.dump(plan,f,sort_keys=True,ensure_ascii=True,indent=2)
        print(json.dumps({"status":plan["status"],"plan_sha256":plan["plan_sha256"],
                          "profile_sha256":plan["profile_sha256"],"native_scope_complete":False,"applied":False,"ready_for_apply":False}))
        return 0
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print(json.dumps({"status":"PLAN_REJECTED","code":str(exc) if isinstance(exc,(PlanError,bundle.web.StageError)) else type(exc).__name__}))
        return 1


if __name__=="__main__":
    raise SystemExit(main())
