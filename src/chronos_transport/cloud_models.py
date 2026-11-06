"""Reviewed protocol/rate reference, not availability, invoice or model quality proof.

No default selection, alias resolution, calls or downloads. Re-review official
prices before authorizing a plan; higher rate ceilings may be supplied explicitly.
"""
if __package__:
    from .deployment import DeploymentError
else:
    from deployment import DeploymentError

MODELS = {
    "gpt-6-luna": (275_000, 825_000),
    "gpt-6-sol": (5_500_000, 16_500_000),
}

def reviewed_model(model):
    if type(model) is not str or model not in MODELS:
        raise DeploymentError("CLOUD_MODEL_NOT_REVIEWED")
    incoming, outgoing = MODELS[model]
    return {
        "model": model, "reviewed_on": "2026-10-30",
        "model_context_tokens": 1_050_000, "max_completion_tokens": 2048,
        "input_rate_floor_micro_usd_per_million": incoming,
        "output_rate_floor_micro_usd_per_million": outgoing,
        "reasoning_effort": "none", "temperature": 0,
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "model_source": "https://developers.openai.com/api/docs/models/" + model,
        "protocol_source": "https://developers.openai.com/api/docs/guides/latest-model",
        "rate_basis": "Standard; full context; long-context and cache-write premiums; regional premium; no cached-input discount",
        "live_tested": False, "billing_verified": False,
    }

def validate_selection(profile, policy):
    card = reviewed_model(profile.model)
    policy.validate_profile(profile)
    if (profile.reasoning_effort != "none"
            or policy.model_context_tokens != card["model_context_tokens"]
            or policy.input_micro_usd_per_million_tokens < card["input_rate_floor_micro_usd_per_million"]
            or policy.output_micro_usd_per_million_tokens < card["output_rate_floor_micro_usd_per_million"]):
        raise DeploymentError("CLOUD_REVIEWED_LIMITS_REQUIRED")
    return card
