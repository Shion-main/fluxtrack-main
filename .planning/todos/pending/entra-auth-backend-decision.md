---
created: 2026-07-03
phase_target: 8
source: user decision (2026-07-03) — "follow what's on the credentials"
tags: [auth, entra, phase-8]
---

# Phase 8 auth: use python-social-auth AzureADTenantOAuth2 (match registered redirect URI)

**Decision (user, 2026-07-03):** FluxTrack's Entra sign-in will use
`social-auth-app-django`'s `AzureADTenantOAuth2` backend, NOT a custom MSAL/PKCE
flow. Reason: the Azure app registration's redirect URI is already set to
`http://localhost:8000/auth/complete/azuread-tenant-oauth2/`, which is exactly
python-social-auth's callback convention. Following the credentials = conform the
app to that backend rather than changing the Azure redirect URI.

**Verified 2026-07-03:** client-credentials flow against the tenant returned a
valid token — tenant id, client id, and secret are all correct and working.

## What Phase 8 must do
- Add `social-auth-app-django` to `requirements.txt`.
- Add `social_django` to `INSTALLED_APPS`; add
  `social_core.backends.azuread_tenant.AzureADTenantOAuth2` to
  `AUTHENTICATION_BACKENDS` (keep `ModelBackend` for the break-glass superuser).
- Wire URLs so `/auth/complete/azuread-tenant-oauth2/` resolves (include
  `social_django.urls` under the `auth/` prefix) — this is the registered callback.
- Read creds from `.env` (already present): `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY`,
  `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET`, `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID`.
- Map the Entra object id to `User.azure_oid`; enforce the "no provisioned User =
  refused" gate (Phase 8 success criterion 2) via the social-auth pipeline.
- Enable PKCE (`SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_USE_PKCE = True`) to satisfy the
  roadmap's "Authorization Code + PKCE" wording — social-core supports PKCE on this
  backend, so the roadmap criterion and this backend are compatible.
- Add the production redirect URI (https, real host) to the Azure app registration
  before cutover; **rotate the client secret** (current value was shared in a chat
  transcript — dev-only).

## Watch-outs
- Roadmap Phase 8 SC-1 says "Authorization Code + PKCE" — reconcile by enabling PKCE
  as above; no conflict, just make it explicit in the Phase 8 plan.
- `.env.example` / `requirements.txt` comments say Entra is "Phase 2" — stale; the
  roadmap defers it to Phase 8. Fix the comments when auth lands.
