"""v3 readiness + canonical-structure compliance tests.

Validates the connector satisfies Atlan App Framework v3 and matches the
canonical atlanhq/application-sdk topology:
- App class shape (name ClassVar, extends App)
- sync_glossary is the workflow @entrypoint; run_glossary_sync is its activity
- auth/preflight are Handler ops (GitHubConnectorHandler), NOT App @entrypoints
- All @task/@entrypoint I/O inherits from SDK Input/Output
- Credential registration via CredentialTypeRegistry
- Contract round-trip serialization
"""

import inspect

import pytest
from application_sdk.app import Input, Output
from application_sdk.credentials import CredentialTypeRegistry
from application_sdk.handler.base import Handler
from application_sdk.testing.mocks import MockSecretStore, MockStateStore

import app.credentials  # noqa: F401 — side-effect: registers credential types


# ─── App class shape ──────────────────────────────────────────────

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


# ─── Canonical workflow / handler topology ───────────────────────────────

def test_sync_glossary_workflow_and_activity_exist():
    """sync_glossary is the @entrypoint workflow; run_glossary_sync is its @task activity."""
    from app.connector import GitHubConnector
    assert inspect.iscoroutinefunction(GitHubConnector.sync_glossary)
    assert inspect.iscoroutinefunction(GitHubConnector.run_glossary_sync)


def test_auth_preflight_not_app_entrypoints():
    """auth/preflight moved to the Handler — must not be App methods."""
    from app.connector import GitHubConnector
    assert not hasattr(GitHubConnector, "auth")
    assert not hasattr(GitHubConnector, "preflight")


def test_handler_discovered_by_convention():
    """{AppClassName}Handler subclasses Handler so load_handler_class finds it."""
    from app.connector import GitHubConnectorHandler
    assert issubclass(GitHubConnectorHandler, Handler)


def test_handler_overrides_test_auth():
    from app.connector import GitHubConnectorHandler
    assert inspect.iscoroutinefunction(GitHubConnectorHandler.test_auth)


def test_workflow_input_inherits_sdk_input():
    from app.connector import SyncGlossaryFormInput
    assert issubclass(SyncGlossaryFormInput, Input)


# ─── SDK Input / Output base class compliance ─────────────────────────────

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


# ─── Credential registry ───────────────────────────────────────────

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


# ─── Contract round-trip (model_dump / model_validate) ──────────────────────

def test_auth_input_round_trip():
    from app.contracts import AuthInput
    original = AuthInput(credential={"token": "ghp_test"}, extraction_method="direct")
    restored = AuthInput.model_validate(original.model_dump())
    assert restored.credential == original.credential


def test_sync_glossary_form_input_round_trip():
    from app.connector import SyncGlossaryFormInput
    original = SyncGlossaryFormInput(
        github_token="ghp_x",
        atlan_api_key="key",
        repo_full_name="sony-telemetry/schema-registry",
    )
    restored = SyncGlossaryFormInput.model_validate(original.model_dump())
    assert restored.repo_full_name == "sony-telemetry/schema-registry"
    assert restored.glossary_name == "sony_telemetry"  # default applied
    assert restored.phase1_filter is True


def test_glossary_sync_output_round_trip():
    from app.contracts import GlossarySyncOutput
    original = GlossarySyncOutput(
        glossary_qn="default/github/1234",
        terms_created=10,
        summary="Synced 10 terms",
    )
    restored = GlossarySyncOutput.model_validate(original.model_dump())
    assert restored.terms_created == 10
    assert restored.summary == "Synced 10 terms"


# ─── MockSecretStore / MockStateStore construction ────────────────────────

def test_connector_instantiation():
    from app.connector import GitHubConnector
    connector = GitHubConnector()
    assert connector is not None


def test_mock_state_store_is_constructible():
    store = MockStateStore()
    assert store is not None
