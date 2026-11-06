"""Read one explicitly installed provider; never select a fallback or probe it."""
import importlib.util
from pathlib import Path
import time
HERE = Path(__file__).resolve().parent
RUNTIME = Path("/opt/chronos/runtime")


def sibling(name):
    path = HERE / (name + ".py")
    if path.resolve() != path: raise ValueError("LINKED_PROVIDER_HELPER")
    spec = importlib.util.spec_from_file_location("chronos_installed_"+name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def status(ident, *, runtime=RUNTIME):
    cloud = sibling("cloud_provider")
    root = cloud.directory(runtime)
    names = {p.name for p in root.iterdir()}
    if names == {"local-provider"}:
        observed = sibling("local_provider").status(ident, runtime=root)
        profile, allowance = observed["profile"], observed["allowance"]
        binding = observed["profile_sha256"]
        current = None
    elif names == {"cloud-provider"}:
        value, ledger = cloud.state(ident, runtime=root)
        observed = cloud.summary(value, ledger)
        profile, allowance = value["profile"], observed["allowance"]
        binding = observed["plan_sha256"]
        now = time.time_ns() // 1000
        current = ledger.policy.created_at_us <= now < ledger.policy.expires_at_us
    else:
        raise ValueError("EXACTLY_ONE_OWNED_PROVIDER_REQUIRED")
    return {"schema_version":"chronos.provider-state.v1", "status":"CONFIGURED_NOT_PROBED",
            "profile":profile, "profile_sha256":observed["profile_sha256"],
            "binding_sha256":binding, "provider_kind":profile["provider"], "allowance":allowance,
            "budget_policy_current":current, "transport_checked":False, "model_tested":False, "ready":False}
