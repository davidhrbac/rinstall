from hashlib import sha256
from ipaddress import ip_address
import shlex


SQUID_VENDOR_CONFIG = "/etc/squid/squid.conf"
SQUID_WRAPPER_CONFIG = "/etc/squid/rinstall.conf"
SQUID_SYSCONFIG = "/etc/sysconfig/squid"
SQUID_CANDIDATE_CONFIG = "/run/rinstall-squid.conf"


def _cache_peer_host(host):
    try:
        address = ip_address(host)
    except ValueError:
        return host
    return f"[{address}]" if address.version == 6 else str(address)


def _vcenter_acl(server):
    try:
        address = ip_address(server)
    except ValueError:
        return f"acl rinstall_direct_vcenter dstdomain {server}"
    return f"acl rinstall_direct_vcenter dst {address}/{address.max_prefixlen}"


def render_upstream_wrapper(upstream, vcenter_server):
    return "\n".join(
        [
            "# Managed by rinstall. Do not edit manually.",
            "",
            f"include {SQUID_VENDOR_CONFIG}",
            "",
            "cache_peer "
            f"{_cache_peer_host(upstream['host'])} parent {upstream['port']} "
            "0 no-query default name=rinstall_upstream",
            _vcenter_acl(vcenter_server),
            "",
            "cache_peer_access rinstall_upstream deny rinstall_direct_vcenter",
            "cache_peer_access rinstall_upstream allow all",
            "",
            "always_direct allow rinstall_direct_vcenter",
            "never_direct allow all",
            "",
        ]
    )


def content_hash(content):
    return sha256(content.encode()).hexdigest()


def squid_transition_command(upstream_enabled):
    desired_config = SQUID_WRAPPER_CONFIG if upstream_enabled else SQUID_VENDOR_CONFIG
    candidate_check = ""
    candidate_cleanup = ""
    if upstream_enabled:
        candidate_check = (
            f"if ! squid -k parse -f {shlex.quote(SQUID_CANDIDATE_CONFIG)}; then "
            "printf 'rinstall Squid candidate validation failed; active configuration was not changed\\n' >&2; "
            f"rm -f {shlex.quote(SQUID_CANDIDATE_CONFIG)}; exit 1; fi; "
        )
        candidate_cleanup = f"rm -f {shlex.quote(SQUID_CANDIDATE_CONFIG)}; "
    else:
        candidate_check = (
            f"if ! squid -k parse -f {shlex.quote(SQUID_VENDOR_CONFIG)}; then "
            "printf 'vendor Squid configuration validation failed; active configuration was not changed\\n' >&2; exit 1; fi; "
        )

    desired_line = f'SQUID_CONF="{desired_config}"'
    wrapper_install = (
        f"wrapper_tmp=$(mktemp /etc/squid/.rinstall.conf.XXXXXX); cp -a {shlex.quote(SQUID_CANDIDATE_CONFIG)} \"$wrapper_tmp\"; "
        "if command -v restorecon >/dev/null 2>&1; then restorecon -F \"$wrapper_tmp\"; fi; "
        "mv -f \"$wrapper_tmp\" \"$wrapper\"; "
        if upstream_enabled
        else "rm -f \"$wrapper\"; "
    )
    wrapper_compare = (
        "if ! cmp -s /run/rinstall-squid.conf \"$wrapper\"; then reload_needed=1; fi; "
        if upstream_enabled
        else ""
    )
    return "".join(
        [
            "set -eu; ",
            candidate_check,
            f"sysconfig={shlex.quote(SQUID_SYSCONFIG)}; wrapper={shlex.quote(SQUID_WRAPPER_CONFIG)}; ",
            'rollback=/run/rinstall-squid-rollback; rm -rf "$rollback"; mkdir -m 700 "$rollback"; ',
            'cp -a "$sysconfig" "$rollback/sysconfig"; ',
            'had_wrapper=0; if [ -e "$wrapper" ]; then had_wrapper=1; cp -a "$wrapper" "$rollback/wrapper"; fi; ',
            'was_active=0; if systemctl is-active --quiet squid; then was_active=1; fi; ',
            f'reload_needed=0; if ! grep -Fx {shlex.quote(desired_line)} "$sysconfig" >/dev/null 2>&1; then reload_needed=1; fi; ',
            wrapper_compare,
            'rollback() { ',
            'status=$?; ',
            'if [ "$status" -ne 0 ]; then ',
            'cp -a "$rollback/sysconfig" "$sysconfig"; ',
            'if [ "$had_wrapper" -eq 1 ]; then cp -a "$rollback/wrapper" "$wrapper"; else rm -f "$wrapper"; fi; ',
            'if [ "$was_active" -eq 1 ]; then systemctl reload squid || true; fi; ',
            "printf 'Squid activation failed; previous configuration was restored\\n' >&2; ",
            'fi; ',
            candidate_cleanup,
            'rm -rf "$rollback"; exit "$status"; }; trap rollback EXIT; ',
            f"if grep -Eq '^[[:space:]]*SQUID_CONF[[:space:]]*=' \"$sysconfig\"; then sed -i -E 's|^[[:space:]]*SQUID_CONF[[:space:]]*=.*$|{desired_line}|' \"$sysconfig\"; ",
            f'else printf \'\\n%s\\n\' {shlex.quote(desired_line)} >> "$sysconfig"; fi; ',
            wrapper_install,
            'if command -v restorecon >/dev/null 2>&1; then restorecon -F "$sysconfig"; fi; ',
            'if [ "$was_active" -eq 1 ] && [ "$reload_needed" -eq 1 ]; then systemctl reload squid; fi; ',
            'trap - EXIT; ',
            candidate_cleanup,
            'rm -rf "$rollback"',
        ]
    )
