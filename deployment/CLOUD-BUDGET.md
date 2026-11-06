# Cloud budget prerequisite — offline implementation, not an enabled provider

This component supplies monetary authorization for CHR-I07. It does not by itself
enable inference. The [transport](CLOUD-TRANSPORT.md) and optional
[private-console launcher](CLOUD-PROVIDER.md) are implemented source; native cloud
configuration is wired in source but compilation and actual provider/TLS execution
are still unverified. The existing
local guard rejects remote profiles. No model or positive budget is auto-selected.

## What is implemented

src/chronos_transport/cloud_budget.py contains CloudBudgetPolicy and
CloudAllowance, with no network dependencies. The policy binds one exact E1
profile digest to an explicit USD budget, rates, model context ceiling and a
validity interval of at most24hours. Only a version3 openai-chat-json E1 profile
with an exact reviewed current ID or dated ID is accepted at the ledger layer.
The public launcher additionally requires the reviewed model catalogue; a date
suffix alone is not evidence of compatibility or availability.

All monetary values are integer microdollars:1 USD =1,000,000 micro-USD. Zero
budget is valid configuration and grants zero calls. Zero/negative rates,
floating-point money, bool-as-integer, extra fields, duplicate JSON keys,
nonfinite values, endpoints and credentials are rejected. No secret belongs in
this policy or the profile. Parse errors do not echo supplied values.

The operator must check current provider pricing, model availability, context
limit and output capabilities before authorizing a policy. The reservation per
attempt is rounded UP and uses the FULL declared model context window at the
uncached-input rate, plus2,048 output tokens at the output rate. It does not
estimate tokens from characters and does not assume a cache discount. It may
therefore reserve much more than a small real request ultimately costs.

These are conservative reservations under declared rates, NOT a verified
provider invoice or an unconditional hard cap on the account bill. Taxes,
exchange rates, provider price changes and calls from other applications are
outside this ledger. A request-count limit is not a monetary limit.

## Authority, persistence and failure

Creating the separate SQLite ledger requires the exact approved policy digest;
each claim requires it again. The digest scopes consent; possession of a public
digest does not prove that a human approved expenditure. An explicitly authorized
launcher/credential boundary must enforce actual approval before network use.
The optional launcher requires separate explicit activation; no paid activation
has occurred. Its private namespace is the caller trust boundary.

Within one BEGIN IMMEDIATE transaction the ledger verifies immutable profile and
policy, checks consent/window/deadline, rejects reused request IDs, checks both
remaining request count and remaining money, inserts IN_FLIGHT with the full
reservation, then commits before returning a receipt. Reopen requires the exact
same policy and profile. A changed model, limit, rate, budget or expiry cannot
silently replace them.

VERIFIED_STOP, FAILED and UNCERTAIN all retain the reservation. First terminal
result wins; later observations do not refund money or requests. A process exit
after commit leaves IN_FLIGHT spent. A reused ID never grants another claim.
An unknown or incomplete ledger is preserved and refused; no repair/reset or
recreation is performed automatically. Expired authorization still permits
status and terminal observation, but no new claim.

The deployment must protect the ledger path and parents against other users,
links and replacement. A filesystem administrator can alter or copy databases
and is not prevented by SQLite or a hash. Do not delete/recreate a ledger to
renew the budget; explicit renewed-authorization lifecycle is still pending.

## Source requirements and remaining paid-execution validation

The transport and launcher implement items1-6 in source. Actual TLS, private-key
console, isolation and native/provider runtime proof remain required for all.

1. An explicitly approved startup flow that privately receives a restricted key;
   no key in arguments, profile, messages, logs, screenshots or the source bundle.
2. Current pinned-model capability/rate/context validation. No fallback model.
3. Fixed HTTPS endpoint, certificate/hostname verification, no redirect or
   caller-supplied host, no insecure TLS switch. Bounded DNS/connect/read and
   cancellation; no automatic retries.
4. Convert the native request into supported Chat Completions parameters while
   preserving the complete local E1 validation. The official schema is a subset
   of JSON Schema: provider schema adaptation must not weaken host acceptance.
5. Revalidate deadline/authorization immediately before dispatch, including after
   a slow SQLite commit. A timeout does not prove the provider did not bill.
6. Enforce text-only/no tools, one result, fixed2,048 completion cap, no unapproved
   premium tier, and validate usage/model/finish_reason/refusal. Quarantine
   inconsistent usage; never automatically refund a reservation.
7. Native AI Hub154, private key input, actual provider and clean-install proof,
   then compare genuine agent outputs with the rules. Unit tests are not that
   evidence. Source/UI must label cloud capability unavailable until complete.

## References inspected30October2026

- https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- https://developers.openai.com/api/docs/guides/structured-outputs

The current API documents max_completion_tokens; the native request currently
uses max_tokens. It documents store=false as controlling storage for particular
provider products, not as proof of zero retention. GPT-4.1 model pages inspected
in this session are marked deprecated, so they are not chosen as the judge's
new default. No published rate is hard-coded as a forever-current guarantee.
