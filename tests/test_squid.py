from lib.squid import (
    SQUID_VENDOR_CONFIG,
    content_hash,
    render_upstream_wrapper,
    squid_transition_command,
)


def test_direct_mode_has_no_squid_policy_transition():
    command = squid_transition_command(False)

    assert f"squid -k parse -f {SQUID_VENDOR_CONFIG}" in command
    assert "rinstall-squid.conf" not in command
    assert 'SQUID_CONF=\"/etc/squid/squid.conf\"' in command


def test_upstream_wrapper_uses_exact_hostname_vcenter_acl():
    rendered = render_upstream_wrapper(
        {"host": "proxy.example.internal", "port": 9090},
        "vcenter.t18.zone1.fiocp.internal",
    )

    assert "include /etc/squid/squid.conf" in rendered
    assert "cache_peer proxy.example.internal parent 9090 0 no-query default name=rinstall_upstream" in rendered
    assert "acl rinstall_direct_vcenter dstdomain vcenter.t18.zone1.fiocp.internal" in rendered
    assert "dstdomain .t18.zone1.fiocp.internal" not in rendered
    assert "cache_peer_access rinstall_upstream deny rinstall_direct_vcenter" in rendered
    assert "cache_peer_access rinstall_upstream allow all" in rendered
    assert "always_direct allow rinstall_direct_vcenter" in rendered
    assert "never_direct allow all" in rendered


def test_upstream_wrapper_uses_exact_ip_vcenter_acl_and_supports_ipv6_parent():
    rendered = render_upstream_wrapper(
        {"host": "2001:db8::42", "port": 9090},
        "192.0.2.42",
    )

    assert "cache_peer [2001:db8::42] parent 9090" in rendered
    assert "acl rinstall_direct_vcenter dst 192.0.2.42/32" in rendered
    assert "dstdomain" not in rendered


def test_content_hash_is_stable_for_idempotence_checks():
    content = render_upstream_wrapper(
        {"host": "proxy.example.internal", "port": 9090},
        "vcenter.example.internal",
    )

    assert content_hash(content) == content_hash(content)
