"""v3 readiness compliance tests.

Validates the connector satisfies Atlan App Framework v3 requirements:
- App class shape (name ClassVar, no legacy decorators)
- All @task/@entrypoint I/O inherits from SDK Input/Output
- Credential registration via CredentialTypeRegistry
- Contract round-trip serialization
- MockSecretStore/MockStateStore construction
"""

import pytest
from application_sdk.app import Input, Output
from application_sdk.credentials import CredentialTypeRegistry
from application_sdk.testing.mocks import MockSecretStore, MockStateStore

import app.credentials  # noqa: F401 — side-effect: registers credential types


# ─── App class shape ─────────────────────────────────────────────────────────

def test_connector_has_name_classvar():
    from app.connector import GitHubConnector
    assert GitHubConnector.name == "github"


def test_connector_has_version_classvar():
    from app.connector import GitHubConnector
    assert GitHubConnector.version == "1.0.0"


def test_connector_extends_app():
    from application_sdk.app import App
    from app.connector import GitHubConnector
    assert issubclass(GitHubConnector, App)


# ─── SDK Input / Output base class compliance ─────────────────────────────────

@pytest.mark.parametrize("cls_name", [
    "AuthInput",
    "PreflightInput",
    "GitHubExtractionInput",
    "FetchSbomInput",
    "TransformInput",
    "GlossarySyncInput",
])
def test_input_classes_inherit_from_sdk_input(cls_name):
    import app.contracts as c
    cls = getattr(c, cls_name)
    assert issubclass(cls, Input), f"{cls_name} must inherit from application_sdk.app.Input"


@pytest.mark.parametrize("cls_name", [
    "AuthOutput",
    "PreflightOutput",
    "GitHubExtractionOutput",
    "FetchSbomOutput",
    "TransformOutput",
    "GlossarySyncOutput",
])
def test_output_classes_inherit_from_sdk_output(cls_name):
    import app.contracts as c
    cls = getattr(c, cls_name)
    assert issubclass(cls, Output), f"{cls_name} must inherit from application_sdk.app.Output"


# ─── Credential registry ──────────────────────────────────────────────────────

def test_github_token_credential_registered():
    r = CredentialTypeRegistry()
    cls = r.get_class("github_token")
    assert cls is not None
    assert cls.__name__ == "GitHubTokenCredential"


def test_atlan_api_token_builtin_registered():
    """Framework ships atlan_api_token built-in; we use it instead of a custom type."""
    r = CredentialTypeRegistry()
    cls = r.get_class("atlan_api_token")
    assert cls is not None
    assert cls.__name__ == "AtlanApiToken"


# ─── Contract round-trip (model_dump / model_validate) ───────────────────────

def test_auth_input_round_trip():
    from app.contracts import AuthInput
    original = AuthInput(credential={"token": "ghp_test"}, extraction_method="direct")
    dumped = original.model_dump()
    restored = AuthInput.model_validate(dumped)
    assert restored.credential == original.credential


def test_preflight_input_round_trip():
    from app.contracts import PreflightInput
    original = PreflightInput(organization="sony-telemetry", credential={"token": "ghp_test"})
    dumped = original.model_dump()
    restored = PreflightInput.model_validate(dumped)
    assert restored.organization == "sony-telemetry"


def test_extraction_output_round_trip():
    from app.contracts import GitHubExtractionOutput
    original = GitHubExtractionOutput(
        extraction_summary="ok",
        repos_count=5,
        wiki_pages_count=10,
        yaml_files_count=2,
    )
    dumped = original.model_dump()
    restored = GitHubExtractionOutput.model_validate(dumped)
    assert restored.repos_count == 5
    assert restored.wiki_pages_count == 10


def test_transform_output_round_trip():
    from app.contracts import TransformOutput
    original = TransformOutput(assets_created=42, repos_count=3)
    dumped = original.model_dump()
    restored = TransformOutput.model_validate(dumped)
    assert restored.assets_created == 42


def test_glossary_sync_output_round_trip():
    from app.contracts import GlossarySyncOutput
    original = GlossarySyncOutput(
        glossary_qn="default/github/1234",
        terms_created=10,
        summary="Synced 10 terms",
    )
    dumped = original.model_dump()
    restored = GlossarySyncOutput.model_validate(dumped)
    assert restored.terms_created == 10
    assert restored.summary == "Synced 10 terms"


# ─── MockSecretStore / MockStateStore construction ───────────────────────────

def test_connector_instantiation_with_mocks():
    """App should be constructible — no mandatory external stores at init time."""
    from app.connector import GitHubConnector
    # App.__init__ accepts no required args; mocks are injected via context at runtime.
    # Verify the class is instantiable without raising.
    connector = GitHubConnector()
    assert connector is not None


def test_mock_secret_store_provides_secrets():
    store = MockSecretStore(secrets={"ATLAN_API_KEY": "test-key"})
    # MockSecretStore stores the secrets dict; verify it is accessible
    assert store._secrets.get("ATLAN_API_KEY") == "test-key"


def test_mock_state_store_is_constructible():
    store = MockStateStore()
    assert store is not None
