from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_bootstrap_runtime_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap_runtime.py"
    module_name = "tests.unit._bootstrap_runtime"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


bootstrap_runtime = _load_bootstrap_runtime_module()

LOCAL_AIC = "1.2.156.3088.1.1.34C2.478BDF.3GF546.0JU4"
REGISTRY_AIC = "1.2.156.3088.1.1.34C2.478BDF.3GF547.0JU5"
AGENT_AIC = "1.2.156.3088.1.1.34C2.478BDF.3GF548.0JU6"


def test_discover_demo_leader_runtime_reads_install_layout(tmp_path: Path) -> None:
    acs_path = tmp_path / "leader" / "atr" / "acs.json"
    acs_path.parent.mkdir(parents=True)
    (tmp_path / "leader" / "scenario" / "expert" / "tour").mkdir(parents=True)
    acs_path.write_text(
        json.dumps({"name": "旅游助理智能体", "aic": ""}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    runtime_spec = bootstrap_runtime.discover_demo_leader_runtime(tmp_path)

    assert runtime_spec.install_dir == tmp_path
    assert runtime_spec.leader_dir == tmp_path / "leader"
    assert runtime_spec.atr_dir == tmp_path / "leader" / "atr"
    assert runtime_spec.acs_path == acs_path
    assert runtime_spec.name == "旅游助理智能体"


def test_discover_demo_leader_runtime_requires_acs_json(tmp_path: Path) -> None:
    (tmp_path / "leader" / "atr").mkdir(parents=True)
    (tmp_path / "leader" / "scenario" / "expert" / "tour").mkdir(parents=True)

    with pytest.raises(bootstrap_runtime.BootstrapError, match="demo-leader ACS 文件"):
        bootstrap_runtime.discover_demo_leader_runtime(tmp_path)


def test_build_demo_leader_result_contains_runtime_file_paths(tmp_path: Path) -> None:
    runtime_spec = bootstrap_runtime.DemoLeaderRuntimeSpec(
        install_dir=tmp_path,
        leader_dir=tmp_path / "leader",
        scenario_dir=tmp_path / "leader" / "scenario" / "expert" / "tour",
        atr_dir=tmp_path / "leader" / "atr",
        acs_path=tmp_path / "leader" / "atr" / "acs.json",
        name="旅游助理智能体",
    )

    result = bootstrap_runtime.build_demo_leader_result(
        tmp_path / "bootstrap-artifacts" / "demo-leader",
        runtime_spec,
        "1.2.156.3088.1.1.TEST",
    )

    assert result["profile"] == "demo-leader"
    assert result["install_dir"] == str(tmp_path)
    assert result["leader_dir"] == str(tmp_path / "leader")
    assert result["aic"] == "1.2.156.3088.1.1.TEST"
    assert result["files"] == {
        "acs": str(tmp_path / "leader" / "atr" / "acs.json"),
        "client_cert": str(tmp_path / "leader" / "atr" / "client.pem"),
        "client_key": str(tmp_path / "leader" / "atr" / "client.key"),
        "trust_bundle": str(tmp_path / "leader" / "atr" / "trust-bundle.pem"),
    }


def test_build_parser_accepts_demo_leader_install_dir() -> None:
    parser = bootstrap_runtime.build_parser()

    args = parser.parse_args(["demo-leader", "--install-dir", "/opt/demo-leader"])

    assert args.command == "demo-leader"
    assert args.install_dir == "/opt/demo-leader"


def test_build_parser_accepts_rabbitmq_install_dir() -> None:
    parser = bootstrap_runtime.build_parser()

    args = parser.parse_args(["rabbitmq", "--install-dir", "/opt/rabbitmq"])

    assert args.command == "rabbitmq"
    assert args.install_dir == "/opt/rabbitmq"


def test_build_parser_accepts_redis_install_dir() -> None:
    parser = bootstrap_runtime.build_parser()

    args = parser.parse_args(["redis", "--install-dir", "/opt/redis"])

    assert args.command == "redis"
    assert args.install_dir == "/opt/redis"


@pytest.mark.parametrize(
    ("argv", "install_dir"),
    [
        (["rabbitmq", "--install-dir", "/opt/rabbitmq"], "/opt/rabbitmq"),
        (["redis", "--install-dir", "/opt/redis"], "/opt/redis"),
        (["demo-partner", "--install-dir", "/opt/demo-partner"], "/opt/demo-partner"),
        (["demo-leader", "--install-dir", "/opt/demo-leader"], "/opt/demo-leader"),
    ],
)
def test_resolve_server_install_dirs_ignores_missing_command_specific_attrs(
    argv: list[str],
    install_dir: str,
) -> None:
    parser = bootstrap_runtime.build_parser()
    args = parser.parse_args(argv)

    registry_install_dir, mq_auth_install_dir = bootstrap_runtime.resolve_server_install_dirs(args)

    assert registry_install_dir is None
    assert mq_auth_install_dir is None
    assert args.install_dir == install_dir


def test_build_rabbitmq_result_contains_infra_file_paths(tmp_path: Path) -> None:
    result = bootstrap_runtime.build_rabbitmq_result(
        tmp_path / "bootstrap-artifacts" / "rabbitmq",
        "1.2.156.3088.1.1.RABBITMQ",
    )

    assert result["profile"] == "rabbitmq"
    assert result["aic"] == "1.2.156.3088.1.1.RABBITMQ"
    assert result["files"] == {
        "server_cert": str(tmp_path / "bootstrap-artifacts" / "rabbitmq" / "rabbitmq-server.pem"),
        "server_key": str(tmp_path / "bootstrap-artifacts" / "rabbitmq" / "rabbitmq-server.key"),
        "client_cert": str(tmp_path / "bootstrap-artifacts" / "rabbitmq" / "rabbitmq-client.pem"),
        "client_key": str(tmp_path / "bootstrap-artifacts" / "rabbitmq" / "rabbitmq-client.key"),
        "ca_bundle": str(tmp_path / "bootstrap-artifacts" / "rabbitmq" / "acps-root-ca.pem"),
    }


def test_build_redis_result_contains_infra_file_paths(tmp_path: Path) -> None:
    result = bootstrap_runtime.build_redis_result(
        tmp_path / "bootstrap-artifacts" / "redis",
        "1.2.156.3088.1.1.REDIS",
    )

    assert result["profile"] == "redis"
    assert result["aic"] == "1.2.156.3088.1.1.REDIS"
    assert result["files"] == {
        "server_cert": str(tmp_path / "bootstrap-artifacts" / "redis" / "redis-server.pem"),
        "server_key": str(tmp_path / "bootstrap-artifacts" / "redis" / "redis-server.key"),
        "ca_bundle": str(tmp_path / "bootstrap-artifacts" / "redis" / "acps-root-ca.pem"),
    }


def _acs(*, aic: str = "", url: str = "https://partner.example/agents/{AIC}/inbox") -> dict:
    return {
        "name": "demo-agent",
        "version": "1.0.0",
        "aic": aic,
        "active": True,
        "lastModifiedTime": "2026-01-01T00:00:00Z",
        "description": "demo",
        "endPoints": [{"type": "https", "url": url}],
        "skills": [{"id": "skill-b"}, {"id": "skill-a"}],
    }


def _registration_spec(tmp_path: Path, acs: dict | None = None):
    acs_path = tmp_path / "agent.json"
    acs_path.write_text(json.dumps(acs or _acs(), ensure_ascii=False), encoding="utf-8")
    return bootstrap_runtime.RegistrationSpec("demo-agent", acs_path, ())


def _check_payload(
    status: str,
    *,
    acs: dict | None = None,
    aic: str = REGISTRY_AIC,
    disabled: bool = False,
    agent_id: str = "agent-current",
):
    if status == "missing":
        return {"status": "missing", "name": "demo-agent", "version": "1.0.0", "aic": None}
    return {
        "status": status,
        "approval_status": status.upper(),
        "agent_id": agent_id,
        "aic": aic,
        "is_disabled": disabled,
        "registry_acs": acs or _acs(aic=aic, url=f"https://partner.example/agents/{aic}/inbox"),
        "registry_acs_hash": "registry-hash",
    }


class _CommandScript:
    def __init__(self, **responses):
        self.responses = {name: list(values) for name, values in responses.items()}
        self.operations: list[str] = []

    def __call__(self, command, **_kwargs):
        if "check" in command:
            operation = "check"
        elif "save" in command:
            operation = "save"
        elif "submit" in command:
            operation = "submit"
        elif "approve" in command:
            operation = "approve"
        elif "enable" in command:
            operation = "enable"
        elif "sync" in command:
            operation = "sync"
        elif "delete" in command:
            operation = "delete"
        else:  # pragma: no cover - makes unexpected command changes obvious
            raise AssertionError(f"unexpected command: {command}")
        self.operations.append(operation)
        queue = self.responses.get(operation, [])
        if not queue:
            raise AssertionError(f"no response configured for {operation}: {command}")
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _run_registration(monkeypatch, spec, script):
    monkeypatch.setattr(bootstrap_runtime, "run_json_command", script)
    return bootstrap_runtime.ensure_registration(
        spec,
        cli_bin="acps-cli",
        config_path=Path("config.toml"),
        approval_comments="bootstrap",
    )


def _approval_responses(remote_acs: dict | None = None):
    return {
        "submit": [{"approval_status": "PENDING", "agent_id": "agent-current"}],
        "approve": [{"approval_status": "APPROVED", "agent_id": "agent-current", "aic": REGISTRY_AIC}],
        "sync": [{"status": "synced", "agent_id": "agent-current", "aic": REGISTRY_AIC}],
    }


def test_normalize_acs_ignores_only_root_registry_fields() -> None:
    local = _acs(aic="", url="https://partner.example/agents/{aic}/inbox")
    remote = _acs(aic=REGISTRY_AIC, url=f"https://partner.example/agents/{REGISTRY_AIC}/inbox")
    remote["active"] = False
    remote["lastModifiedTime"] = "2027-02-02T00:00:00Z"

    assert bootstrap_runtime.compare_acs_business_content(
        local, remote, agent_aic=REGISTRY_AIC
    )[0]

    remote["skills"][0]["active"] = False
    assert not bootstrap_runtime.compare_acs_business_content(
        local, remote, agent_aic=REGISTRY_AIC
    )[0]


def test_normalize_acs_preserves_list_order_and_ignores_dict_key_order() -> None:
    local = _acs()
    reordered_dict = json.loads(json.dumps(local, sort_keys=True))
    assert bootstrap_runtime.compare_acs_business_content(local, reordered_dict)[0]

    reordered_list = json.loads(json.dumps(local))
    reordered_list["skills"].reverse()
    equivalent, differences = bootstrap_runtime.compare_acs_business_content(local, reordered_list)
    assert not equivalent
    assert any("$.skills" in item for item in differences)


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://partner.example/agents/{aic}/inbox",
        "https://partner.example/agents/{AIC}/inbox",
        f"https://partner.example/agents/{LOCAL_AIC}/inbox",
        f"https://partner.example/agents/{REGISTRY_AIC}/inbox",
        f"https://partner.example/agents/{AGENT_AIC}/inbox",
    ],
)
def test_endpoint_known_aic_forms_are_equivalent(remote_url: str) -> None:
    local = _acs(aic=LOCAL_AIC, url="https://partner.example/agents/{AIC}/inbox")
    remote = _acs(aic=REGISTRY_AIC, url=remote_url)

    assert bootstrap_runtime.compare_acs_business_content(
        local, remote, agent_aic=AGENT_AIC
    )[0]


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://other.example/agents/{AIC}/inbox",
        "https://partner.example/different/{AIC}/inbox",
        "https://partner.example/agents/{AIC}/messages",
    ],
)
def test_endpoint_business_changes_are_not_equivalent(remote_url: str) -> None:
    equivalent, differences = bootstrap_runtime.compare_acs_business_content(
        _acs(), _acs(aic=REGISTRY_AIC, url=remote_url), agent_aic=REGISTRY_AIC
    )
    assert not equivalent
    assert "$.endPoints[0].url" in differences


@pytest.mark.parametrize(
    ("aic_present", "aic_value", "url_token"),
    [
        (True, None, "none-token"),
        (False, None, "missing-token"),
        (True, "", "empty-token"),
        (True, "   ", "whitespace-token"),
        (True, "1", "1"),
        (True, "api", "api"),
        (True, "old", "old"),
        (True, "partner.example", "partner.example"),
        (True, "1.2.156.3088.1.1.34C2.478BDF.3GF546", "3GF546"),
    ],
)
def test_invalid_aic_values_are_not_used_for_endpoint_replacement(
    aic_present: bool,
    aic_value: object,
    url_token: str,
) -> None:
    url = f"https://partner.example/agents/{url_token}/inbox"
    local = _acs(url=url)
    if aic_present:
        local["aic"] = aic_value
    else:
        local.pop("aic")

    normalized = bootstrap_runtime.normalize_acs_for_comparison(
        local,
        known_aics=(aic_value,) if isinstance(aic_value, str) else (),
    )

    assert normalized["endPoints"][0]["url"] == url


def test_valid_full_aic_is_used_for_endpoint_replacement() -> None:
    local = _acs(aic=LOCAL_AIC, url=f"https://partner.example/agents/{LOCAL_AIC}/inbox")

    normalized = bootstrap_runtime.normalize_acs_for_comparison(local, known_aics=(LOCAL_AIC,))

    assert normalized["endPoints"][0]["url"] == "https://partner.example/agents/{AIC}/inbox"


@pytest.mark.parametrize("invalid_aic", ["1", "api", "old", "partner.example"])
def test_invalid_aic_cannot_hide_endpoint_business_change(invalid_aic: str) -> None:
    local = _acs(aic=invalid_aic, url=f"https://partner.example/agents/{invalid_aic}/inbox")
    remote = _acs(aic=REGISTRY_AIC, url=f"https://partner.example/agents/{REGISTRY_AIC}/inbox")

    equivalent, differences = bootstrap_runtime.compare_acs_business_content(
        local,
        remote,
        agent_aic=REGISTRY_AIC,
    )

    assert not equivalent
    assert "$.endPoints[0].url" in differences


def test_first_registration_follows_check_save_submit_approve(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[_check_payload("missing"), _check_payload("draft"), _check_payload("approved")],
        save=[{"approval_status": "DRAFT", "agent_id": "agent-current"}],
        **_approval_responses(),
    )

    assert _run_registration(monkeypatch, spec, script) == REGISTRY_AIC
    assert script.operations == ["check", "save", "check", "submit", "approve", "check", "sync"]


@pytest.mark.parametrize("initial_status", ["draft", "rejected"])
def test_editable_registration_updates_then_approves(monkeypatch, tmp_path: Path, initial_status: str) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[_check_payload(initial_status), _check_payload(initial_status), _check_payload("approved")],
        save=[{"approval_status": initial_status.upper(), "agent_id": "agent-current"}],
        **_approval_responses(),
    )

    assert _run_registration(monkeypatch, spec, script) == REGISTRY_AIC
    assert script.operations == ["check", "save", "check", "submit", "approve", "check", "sync"]


def test_pending_equivalent_skips_save_and_continues_approval(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[_check_payload("pending"), _check_payload("approved")],
        approve=[{"approval_status": "APPROVED", "agent_id": "agent-current", "aic": REGISTRY_AIC}],
        sync=[{"status": "synced", "agent_id": "agent-current", "aic": REGISTRY_AIC}],
    )

    assert _run_registration(monkeypatch, spec, script) == REGISTRY_AIC
    assert script.operations == ["check", "approve", "check", "sync"]


def test_pending_changed_fails_without_mutation(monkeypatch, tmp_path: Path) -> None:
    local = _acs()
    remote = _acs(aic=REGISTRY_AIC)
    remote["description"] = "changed remotely"
    spec = _registration_spec(tmp_path, local)
    script = _CommandScript(check=[_check_payload("pending", acs=remote)])

    with pytest.raises(bootstrap_runtime.BootstrapError, match=r"ACS.*不一致"):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check"]


def test_approved_equivalent_is_registration_no_op_and_reuses_aic(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[_check_payload("approved")],
        sync=[{"status": "synced", "agent_id": "agent-current", "aic": REGISTRY_AIC}],
    )

    assert _run_registration(monkeypatch, spec, script) == REGISTRY_AIC
    assert script.operations == ["check", "sync"]


def test_approved_changed_fails_with_version_guidance_and_no_mutation(monkeypatch, tmp_path: Path) -> None:
    remote = _acs(aic=REGISTRY_AIC)
    remote["description"] = "remote description"
    spec = _registration_spec(tmp_path)
    script = _CommandScript(check=[_check_payload("approved", acs=remote)])

    with pytest.raises(bootstrap_runtime.BootstrapError, match="version"):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check"]


def test_approved_with_missing_local_aic_reuses_registry_identity(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path, _acs(aic=""))
    script = _CommandScript(
        check=[_check_payload("approved", aic=REGISTRY_AIC)],
        sync=[{"status": "synced", "agent_id": "agent-current", "aic": REGISTRY_AIC}],
    )

    assert _run_registration(monkeypatch, spec, script) == REGISTRY_AIC
    assert "save" not in script.operations


def test_disabled_agent_is_enabled_then_rechecked_before_dispatch(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[_check_payload("approved", disabled=True), _check_payload("approved")],
        enable=[{"status": "enabled", "agent_id": "agent-current"}],
        sync=[{"status": "synced", "agent_id": "agent-current", "aic": REGISTRY_AIC}],
    )

    assert _run_registration(monkeypatch, spec, script) == REGISTRY_AIC
    assert script.operations == ["check", "enable", "check", "sync"]


@pytest.mark.parametrize("status", ["approved", "pending"])
def test_disabled_protected_status_with_changed_acs_fails_before_enable(
    monkeypatch,
    tmp_path: Path,
    status: str,
) -> None:
    remote = _acs(aic=REGISTRY_AIC)
    remote["description"] = "remote description"
    spec = _registration_spec(tmp_path)
    script = _CommandScript(check=[_check_payload(status, acs=remote, disabled=True)])

    with pytest.raises(bootstrap_runtime.BootstrapError, match=r"ACS.*不一致"):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check"]


def test_disabled_unknown_status_fails_before_enable(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(check=[_check_payload("archived", disabled=True)])

    with pytest.raises(bootstrap_runtime.BootstrapError, match="不支持的状态"):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check"]


@pytest.mark.parametrize("status", ["draft", "rejected"])
def test_disabled_editable_status_follows_full_sequence(
    monkeypatch,
    tmp_path: Path,
    status: str,
) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[
            _check_payload(status, disabled=True),
            _check_payload(status),
            _check_payload(status),
            _check_payload("approved"),
        ],
        enable=[{"status": "enabled", "agent_id": "agent-current"}],
        save=[{"approval_status": status.upper(), "agent_id": "agent-current"}],
        **_approval_responses(),
    )

    assert _run_registration(monkeypatch, spec, script) == REGISTRY_AIC
    assert script.operations == [
        "check",
        "enable",
        "check",
        "save",
        "check",
        "submit",
        "approve",
        "check",
        "sync",
    ]


def test_enable_recheck_rejects_changed_agent_id(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[
            _check_payload("approved", disabled=True),
            _check_payload("approved", agent_id="agent-replaced"),
        ],
        enable=[{"status": "enabled", "agent_id": "agent-current"}],
    )

    with pytest.raises(bootstrap_runtime.BootstrapError, match="agent_id"):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check", "enable", "check"]


def test_enable_recheck_compares_approved_acs_again(monkeypatch, tmp_path: Path) -> None:
    changed_remote = _acs(aic=REGISTRY_AIC)
    changed_remote["description"] = "changed during enable"
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[
            _check_payload("approved", disabled=True),
            _check_payload("approved", acs=changed_remote),
        ],
        enable=[{"status": "enabled", "agent_id": "agent-current"}],
    )

    with pytest.raises(bootstrap_runtime.BootstrapError, match=r"ACS.*不一致"):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check", "enable", "check"]


def test_unknown_status_fails_without_save_or_delete(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path)
    payload = _check_payload("archived")
    script = _CommandScript(check=[payload])

    with pytest.raises(bootstrap_runtime.BootstrapError, match="不支持的状态"):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check"]


def test_save_failure_text_is_not_used_to_delete_or_recreate(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[_check_payload("draft")],
        save=[bootstrap_runtime.BootstrapError("该状态禁止修改")],
    )

    with pytest.raises(bootstrap_runtime.BootstrapError, match="该状态禁止修改"):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check", "save"]


def test_bootstrap_runtime_has_no_dangerous_delete_or_error_text_fallback() -> None:
    source = Path(bootstrap_runtime.__file__).read_text(encoding="utf-8")

    assert '"delete"' not in source
    assert "clear_generated_state" not in source
    assert "is_approved_update_conflict" not in source
    assert "CANNOT BE UPDATED" not in source


@pytest.mark.parametrize("status", ["missing", "error", "unexpected"])
def test_sync_rejects_non_success_status(monkeypatch, tmp_path: Path, status: str) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[_check_payload("approved")],
        sync=[{"status": status, "agent_id": "agent-current", "aic": REGISTRY_AIC}],
    )

    with pytest.raises(bootstrap_runtime.BootstrapError, match="并发"):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check", "sync"]


def test_sync_rejects_changed_agent_id(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[_check_payload("approved")],
        sync=[{"status": "synced", "agent_id": "agent-replaced", "aic": REGISTRY_AIC}],
    )

    with pytest.raises(bootstrap_runtime.BootstrapError, match=r"agent-current.*agent-replaced"):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check", "sync"]


def test_sync_rejects_changed_aic(monkeypatch, tmp_path: Path) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[_check_payload("approved")],
        sync=[{"status": "synced", "agent_id": "agent-current", "aic": AGENT_AIC}],
    )

    with pytest.raises(bootstrap_runtime.BootstrapError, match=REGISTRY_AIC):
        _run_registration(monkeypatch, spec, script)

    assert script.operations == ["check", "sync"]


@pytest.mark.parametrize("status", ["synced", "unchanged"])
def test_sync_accepts_matching_identity(monkeypatch, tmp_path: Path, status: str) -> None:
    spec = _registration_spec(tmp_path)
    script = _CommandScript(
        check=[_check_payload("approved")],
        sync=[{"status": status, "agent_id": "agent-current", "aic": REGISTRY_AIC}],
    )

    assert _run_registration(monkeypatch, spec, script) == REGISTRY_AIC
    assert script.operations == ["check", "sync"]


PROFILE_ACS_SOURCES = [
    ("registry_service", Path("scripts/acs/registry-server-9002-service-acs.json")),
    ("registry_probe", Path("scripts/acs/registry-server-9002-probe-acs.json")),
    ("mq_service", Path("scripts/acs/mq-auth-server-acs.json")),
    ("mq_probe", Path("scripts/acs/healthcheck-client-acs.json")),
    ("rabbitmq", Path("scripts/acs/rabbitmq-acs.json")),
    ("redis", Path("scripts/acs/redis-acs.json")),
    ("demo_partner", Path("../demo-partner/partners/online/beijing_food/acs.json")),
    ("demo_leader", Path("../demo-leader/leader/atr/acs.json")),
]


@pytest.mark.parametrize(
    ("profile_name", "relative_acs_path"),
    PROFILE_ACS_SOURCES,
    ids=[item[0] for item in PROFILE_ACS_SOURCES],
)
def test_shared_registration_callers_reuse_equivalent_approved_agent(
    monkeypatch,
    tmp_path: Path,
    profile_name: str,
    relative_acs_path: Path,
) -> None:
    del profile_name
    source_path = Path(__file__).resolve().parents[2] / relative_acs_path
    local = json.loads(source_path.read_text(encoding="utf-8"))
    remote = json.loads(json.dumps(local))
    remote["aic"] = REGISTRY_AIC
    for endpoint in remote.get("endPoints", []):
        if isinstance(endpoint, dict) and isinstance(endpoint.get("url"), str):
            endpoint["url"] = endpoint["url"].replace("{AIC}", REGISTRY_AIC)
    spec = _registration_spec(tmp_path, local)
    script = _CommandScript(
        check=[_check_payload("approved", acs=remote)],
        sync=[{"status": "unchanged", "agent_id": "agent-current", "aic": REGISTRY_AIC}],
    )

    assert _run_registration(monkeypatch, spec, script) == REGISTRY_AIC
    assert script.operations == ["check", "sync"]
