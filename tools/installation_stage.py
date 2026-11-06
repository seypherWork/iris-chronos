"""Create or verify a new installation staging tree. No accounts, allowance or services."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import argparse
import json
import os
import re

import installation_plan as planner

STATUS="STAGED_FILES_ONLY_NOT_INSTALLED"
RECEIPT="stage-receipt.json"
ROOT_NAMES={"app","data","guard","profile.json","config.json",RECEIPT}
RECEIPT_FIELDS={"schema_version","status","root","staging_id","created_at","bundle_manifest_sha256",
                "profile_sha256","profile_file_sha256","config_file_sha256","data_identity","guard_identity",
                "allowance_initialized","account_changes","native_calls","model_calls"}


class StagingError(ValueError):
    pass


def require(value,code):
    if not value:raise StagingError(code)


def write_new(path,raw):
    planner.bundle.web._directories(path.parent)
    with path.open("xb") as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    require(planner.bundle.web._read(path)==raw,"STAGED_WRITE_MISMATCH")


def path_identity(path):
    s=planner.bundle.web._plain(path,directory=True)
    return [s.st_dev,s.st_ino]


def stage(source,expected_sha,target,profile_raw,web_origin,native_guard_base_url, *, cloud_plan_raw=None):
    source,checked,manifest=planner.checked_bundle(source,expected_sha)
    planner.host_path(str(target))
    target=planner.bundle.web._path(target)
    planner.bundle.web._directories(target.parent)
    require(not os.path.lexists(target),"STAGE_DESTINATION_EXISTS")
    require(not target.is_relative_to(source) and not source.is_relative_to(target),"STAGE_OVERLAPS_SOURCE")
    profile=planner.Profile.parse(profile_raw)
    schema=planner.bundle.web_json(planner.bundle.web._read(source/"src/chronos_transport/extraction-schema.json"))
    config={"version":3,"deployment_id":profile.deployment_id,"host_bundle":str(target/"app"),
            "host_data_root":str(target/"data"),"host_guard_state":str(target/"guard"),"web_origin":web_origin,"native_guard_base_url":native_guard_base_url}
    # All semantic validation happens before the first destination mutation.
    plan=planner.bind_plan(config,manifest,checked["manifest_sha256"],profile_raw,schema,cloud_plan_raw=cloud_plan_raw)
    catalogue=planner.bundle.catalogue(include_license=os.path.lexists(source/"LICENSE"))
    files={name:planner.bundle.web._read(source/name) for name in catalogue|{planner.bundle.MANIFEST}}
    planner.bundle.verify(source,expected_sha)
    require(all(planner.bundle.web._read(source/name)==raw for name,raw in files.items()),"STAGE_SOURCE_CHANGED")
    # A unique directory is our reservation. Partial output is retained on failure.
    target.mkdir(exist_ok=False)
    try:
        (target/"app").mkdir(exist_ok=False)
        (target/"data").mkdir(exist_ok=False)
        (target/"guard").mkdir(exist_ok=False)
        for name,raw in sorted(files.items()):
            dest=target/"app"/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            write_new(dest,raw)
        config_raw=planner.bundle.json_bytes(config)
        write_new(target/"config.json",config_raw)
        raw=profile_raw.encode("utf-8") if type(profile_raw) is str else profile_raw
        write_new(target/"profile.json",raw)
        if cloud_plan_raw is not None:
            cloud_raw=cloud_plan_raw.encode("utf-8") if type(cloud_plan_raw) is str else cloud_plan_raw
            write_new(target/"cloud-plan.json",cloud_raw)
        receipt={"schema_version":"chronos.install-stage.v3","status":STATUS,"root":str(target),
                 "staging_id":uuid4().hex,"created_at":datetime.now(timezone.utc).isoformat(),
                 "bundle_manifest_sha256":expected_sha,"profile_sha256":profile.digest,
                 "profile_file_sha256":sha256(raw).hexdigest(),"config_file_sha256":sha256(config_raw).hexdigest(),
                 "data_identity":path_identity(target/"data"),"guard_identity":path_identity(target/"guard"),"allowance_initialized":False,
                 "account_changes":0,"native_calls":0,"model_calls":0}
        if cloud_plan_raw is not None:
            receipt.update(cloud_plan_file_sha256=plan["cloud_plan_file_sha256"],
                           cloud_plan_sha256=plan["cloud_plan_sha256"])
        # Receipt last: absence/partial receipt is never an authorized staged tree.
        write_new(target/RECEIPT,planner.bundle.json_bytes(receipt))
        verified=verify_stage(target,expected_sha)
        require(verified["plan_sha256"]==plan["plan_sha256"],"STAGED_PLAN_CHANGED")
        return receipt
    except (OSError,ValueError) as exc:
        raise StagingError("STAGE_FAILED_PARTIAL_PRESERVED") from exc


def verify_stage(root,expected_sha):
    planner.host_path(str(root))
    root=planner.bundle.web._path(root)
    planner.bundle.web._directories(root)
    names={p.name for p in root.iterdir()}
    has_cloud="cloud-plan.json" in names
    require(names == ROOT_NAMES | ({"cloud-plan.json"} if has_cloud else set()),"STAGE_ROOT_CONTENTS_CHANGED")
    receipt_fields=RECEIPT_FIELDS | ({"cloud_plan_file_sha256","cloud_plan_sha256"} if has_cloud else set())
    raw_receipt=planner.bundle.web._read(root/RECEIPT)
    receipt=planner.bundle.web_json(raw_receipt)
    require(type(receipt) is dict and set(receipt)==receipt_fields and
            receipt["schema_version"]=="chronos.install-stage.v3" and receipt["status"]==STATUS,
            "INVALID_STAGE_RECEIPT")
    require(receipt["root"]==str(root) and receipt["bundle_manifest_sha256"]==expected_sha,
            "STAGE_IDENTITY_CHANGED")
    require(type(receipt["staging_id"]) is str and re.fullmatch("[a-f0-9]{32}",receipt["staging_id"]) is not None,
            "INVALID_STAGE_ID")
    require(type(receipt["created_at"]) is str and len(receipt["created_at"])<60,"INVALID_STAGE_TIME")
    require(receipt["allowance_initialized"] is False and all(type(receipt[k]) is int and receipt[k]==0
            for k in ("account_changes","native_calls","model_calls")),"UNSUPPORTED_STAGE_EXECUTION_CLAIM")
    require(not os.path.lexists(root/"app/runtime"),"STAGE_RUNTIME_ALREADY_EXISTS")
    actual,checked,manifest=planner.checked_bundle(root/"app",expected_sha)
    config_raw=planner.bundle.web._read(root/"config.json")
    profile_raw=planner.bundle.web._read(root/"profile.json")
    require(sha256(config_raw).hexdigest()==receipt["config_file_sha256"] and
            sha256(profile_raw).hexdigest()==receipt["profile_file_sha256"],"STAGE_CONFIG_BYTES_CHANGED")
    cloud_plan_raw=planner.bundle.web._read(root/"cloud-plan.json") if has_cloud else None
    if has_cloud:
        require(sha256(cloud_plan_raw).hexdigest()==receipt["cloud_plan_file_sha256"],"CLOUD_PLAN_BYTES_CHANGED")
    config=planner.parse_config(config_raw)
    require(config["host_bundle"]==str(root/"app") and config["host_data_root"]==str(root/"data")
            and config["host_guard_state"]==str(root/"guard"),"STAGE_PATH_BINDING_CHANGED")
    data=root/"data"
    require(path_identity(data)==receipt["data_identity"],"STAGE_DATA_DIRECTORY_REPLACED")
    require(not any(data.iterdir()),"STAGE_DATA_NOT_EMPTY")
    guard=root/"guard"
    require(path_identity(guard)==receipt["guard_identity"],"STAGE_GUARD_DIRECTORY_REPLACED")
    require(not any(guard.iterdir()),"STAGE_GUARD_NOT_EMPTY")
    # Both writable directories must be unused. This is not a runtime verifier.
    schema=planner.bundle.web_json(planner.bundle.web._read(actual/"src/chronos_transport/extraction-schema.json"))
    plan=planner.bind_plan(config,manifest,checked["manifest_sha256"],profile_raw,schema,cloud_plan_raw=cloud_plan_raw)
    require(plan["profile_sha256"]==receipt["profile_sha256"],"STAGE_PROFILE_CHANGED")
    if has_cloud:
        require(plan["cloud_plan_sha256"]==receipt["cloud_plan_sha256"],"CLOUD_PLAN_BINDING_CHANGED")
    return plan


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    create=sub.add_parser("create")
    for name in ("bundle","target","profile"):create.add_argument("--"+name,required=True,type=str if name=="target" else Path)
    for name in ("bundle-sha256","web-origin","native-guard-base-url"):create.add_argument("--"+name,required=True)
    create.add_argument("--cloud-plan",type=Path)
    check=sub.add_parser("verify")
    check.add_argument("--stage-root",required=True)
    check.add_argument("--bundle-sha256",required=True)
    args=p.parse_args(argv)
    try:
        if args.command=="create":
            receipt=stage(args.bundle,args.bundle_sha256,args.target,args.profile.read_bytes(),args.web_origin,args.native_guard_base_url,
                          cloud_plan_raw=args.cloud_plan.read_bytes() if args.cloud_plan else None)
            result={"status":receipt["status"],"stage_root":receipt["root"],"bundle_manifest_sha256":receipt["bundle_manifest_sha256"]}
        else:
            plan=verify_stage(args.stage_root,args.bundle_sha256)
            result={"status":STATUS,"stage_root":str(args.stage_root),"plan_sha256":plan["plan_sha256"]}
        result.update(installed=False,ready_for_apply=False,account_changes=0,model_calls=0,allowance_initialized=False)
        print(json.dumps(result));return 0
    except (ValueError,KeyError,TypeError,OSError) as exc:
        code=str(exc) if isinstance(exc,(StagingError,planner.PlanError,planner.bundle.web.StageError)) else type(exc).__name__
        print(json.dumps({"status":"STAGING_REJECTED","code":code,"installed":False,"ready_for_apply":False}))
        return 1


if __name__=="__main__":raise SystemExit(main())


