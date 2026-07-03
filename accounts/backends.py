"""Custom python-social-auth backend for Microsoft Entra ID.

D-02 / Pitfall 1: the stock ``AzureADTenantOAuth2`` does NOT inherit
``BaseOAuth2PKCE``, so ``SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_USE_PKCE = True`` is
silently ignored — the flow runs as plain Authorization Code and never emits a
``code_challenge``. Mixing ``BaseOAuth2PKCE`` in FIRST (before the Azure backend
in the MRO) makes ``auth_params`` / ``auth_complete_params`` actually add the
PKCE challenge/verifier while still calling ``super()`` to preserve the
Azure-specific params.

The subclass keeps ``name = 'azuread-tenant-oauth2'`` (inherited, not
overridden), so the registered callback URL
``/auth/complete/azuread-tenant-oauth2/`` and every
``SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_*`` setting prefix are unchanged.
"""
from social_core.backends.azuread_tenant import AzureADTenantOAuth2
from social_core.backends.oauth import BaseOAuth2PKCE


class AzureADTenantOAuth2PKCE(BaseOAuth2PKCE, AzureADTenantOAuth2):
    """Single-tenant Entra ID backend with real PKCE (D-02, Pitfall 1)."""

    DEFAULT_USE_PKCE = True
