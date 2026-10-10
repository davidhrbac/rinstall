from pathlib import Path

from lib.squid import (
    SQUID_CANDIDATE_CONFIG,
    SQUID_VENDOR_CONFIG,
    SQUID_WRAPPER_CONFIG,
    effective_squid_config_command,
    render_upstream_wrapper,
    squid_transition_command,
)


def test_upstream_wrapper_uses_exact_hostname_vcenter_acl():
    rendered = render_upstream_wrapper(
        {"host": "proxy.example.internal", "port": 9090},
        "vcenter.example.internal",
    )

    assert f"include {SQUID_VENDOR_CONFIG}" in rendered
    assert "cache_peer proxy.example.internal parent 9090 0 no-query default name=rinstall_upstream" in rendered
    assert "acl rinstall_direct_vcenter dstdomain vcenter.example.internal" in rendered
    assert "dstdomain .example.internal" not in rendered
    assert "cache_peer_access rinstall_upstream deny rinstall_direct_vcenter" in rendered
    assert "cache_peer_access rinstall_upstream allow all" in rendered
    assert "always_direct allow rinstall_direct_vcenter" in rendered
    assert "never_direct allow all" in rendered


def test_deploy_bootstrap_uses_pinned_or_latest_helm_and_upstream_bootstrap_proxy():
    deploy = (Path(__file__).parents[1] / "pyinfra/deploy.py").read_text()

    assert "helm_version=$(asdf latest helm)" in deploy
    assert "config['rancher']['helm_version']" in deploy
    assert 'asdf set -u helm \\\"$helm_version\\\"' in deploy
    assert "asdf current helm; asdf which helm; helm version" in deploy
    assert "--setopt=proxy=" not in deploy
    assert 'DNF_CONFIG = "/etc/dnf/dnf.conf"' in deploy
    assert 'name="Configure DNF upstream proxy"' in deploy
    assert 'line=r"^[[:space:]]*proxy[[:space:]]*=.*$"' in deploy
    assert "replace=f\"proxy=http://{upstream['host']}:{upstream['port']}\"" in deploy
    assert 'name="Render bastion proxy environment"' in deploy
    assert 'name="Ensure bastion proxy environment"' not in deploy
    assert "proxy_exports" not in deploy
    assert ". /etc/profile.d/proxy.sh" not in deploy
    assert "extra_install_args" not in deploy
    assert deploy.count('name="Render bastion proxy environment"') == 1
    assert deploy.index('name="Configure DNF upstream proxy"') < deploy.index('name="Install bastion services"')
    assert deploy.index("asdf plugin add helm") < deploy.index("helm_version=$(asdf latest helm)")


def test_bootstrap_dnf_and_bastion_proxy_changes_are_upstream_only():
    deploy = (Path(__file__).parents[1] / "pyinfra/deploy.py").read_text()

    assert "if upstream is not None:" in deploy
    assert 'upstream = config["proxy"].get("upstream")' in deploy
    assert 'path=DNF_CONFIG' in deploy
    assert 'dest="/etc/profile.d/proxy.sh"' in deploy


def test_upstream_wrapper_uses_exact_ip_vcenter_acl():
    rendered = render_upstream_wrapper(
        {"host": "proxy.example.internal", "port": 9090},
        "192.0.2.42",
    )

    assert "acl rinstall_direct_vcenter dst 192.0.2.42/32" in rendered
    assert "dstdomain" not in rendered


def test_upstream_enable_validates_candidate_and_changes_only_squid_conf():
    command = squid_transition_command(True)

    assert f"squid -k parse -f {SQUID_CANDIDATE_CONFIG}" in command
    assert f"{SQUID_WRAPPER_CONFIG}" in command
    assert "sed -i -E" in command
    assert "SQUID_OPTS" not in command
    assert "systemctl restart squid" in command


def test_upstream_refuses_unmanaged_active_squid_config():
    command = squid_transition_command(True)

    assert f"case \"$current_squid_conf\" in /etc/squid/squid.conf|{SQUID_WRAPPER_CONFIG}" in command
    assert "proxy.upstream cannot take ownership of Squid" in command
    assert "${current_squid_conf:-<unset>}" in command


def test_upstream_change_compares_candidate_and_restarts_only_when_needed():
    command = squid_transition_command(True)

    assert 'cmp -s "$candidate" "$wrapper"' in command
    assert 'if [ "$restart_needed" -eq 0 ]; then exit 0; fi;' in command
    assert "reload_needed" not in command


def test_upstream_disable_restores_vendor_config_and_removes_wrapper():
    command = squid_transition_command(False)

    assert f'SQUID_CONF="{SQUID_VENDOR_CONFIG}"' in command
    assert f'rm -f "$wrapper"' in command
    assert SQUID_CANDIDATE_CONFIG not in command
    assert "SQUID_OPTS" not in command
    assert 'current_squid_conf=$(' in command
    assert 'if [ "$current_squid_conf" != "$wrapper" ]' in command


def test_effective_squid_config_parser_accepts_quoted_and_unquoted_values():
    command = effective_squid_config_command("/etc/sysconfig/squid")

    assert 'sed -n -E' in command
    assert 'SQUID_CONF' in command
    assert 'sed -n \'$p\'' in command


def test_direct_mode_only_reconciles_an_active_rinstall_config():
    deploy = (Path(__file__).parents[1] / "pyinfra/deploy.py").read_text()

    assert 'current_squid_conf == SQUID_WRAPPER_CONFIG' in deploy
    assert 'elif wrapper_present:' in deploy
    assert 'current_wrapper_conf' not in deploy
