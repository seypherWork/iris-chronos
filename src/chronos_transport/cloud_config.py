"""Pure cloud plan contract shared by deployment tools; no keys, writes or provider calls."""
from pathlib import Path
from .cloud_budget import CloudBudgetPolicy, canonical, digest
from .cloud_models import validate_selection
from .deployment import Profile
from . import guard
SCHEMA = "chronos.cloud-provider-plan.v1"

def require(value, code):
    if not value: raise ValueError(code)

def schema_digest():
    schema = guard.strict_json((Path(__file__).with_name("extraction-schema.json")).read_bytes())
    require(schema["properties"]["schema_version"]["enum"] == [guard.EXTRACTION_CONTRACT], "SCHEMA_MISMATCH")
    return digest(schema)


def validate(value):
    require(type(value) is dict and set(value) == {"schema_version", "profile", "policy", "model_review"}
            and value["schema_version"] == SCHEMA, "INVALID_PLAN")
    profile = Profile.parse(canonical(value["profile"]))
    policy = CloudBudgetPolicy.parse(canonical(value["policy"]))
    require(profile.schema_sha256 == schema_digest(), "SCHEMA_MISMATCH")
    require(canonical(value["model_review"]) == canonical(validate_selection(profile, policy)), "MODEL_REVIEW_CHANGED")
    return profile, policy


def parse_plan(raw):
    require(type(raw) in (bytes, str) and len(raw) <= 8192, "INVALID_CLOUD_PLAN_SIZE")
    try: value = guard.strict_json(raw)
    except guard.Rejected: raise ValueError("INVALID_CLOUD_PLAN_JSON") from None
    validate(value)
    return value
