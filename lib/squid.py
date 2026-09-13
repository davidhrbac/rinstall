from ipaddress import ip_address
import shlex


SQUID_VENDOR_CONFIG = "/etc/squid/squid.conf"
SQUID_WRAPPER_CONFIG = "/etc/squid/rinstall.conf"
SQUID_SYSCONFIG = "/etc/sysconfig/squid"
SQUID_CANDIDATE_CONFIG = "/run/rinstall-squid.conf"
SQUID_CONF_VALUE_PATTERN = r"^[[:space:]]*SQUID_CONF[[:space:]]*=[[:space:]]*\"?([^\"]*)\"?[[:space:]]*$"


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


def effective_squid_config_command(path):
    return f"sed -n -E 's|{SQUID_CONF_VALUE_PATTERN}|\\1|p' {path} | sed -n '$p'"


def squid_transition_command(upstream_enabled):
    desired_config = SQUID_WRAPPER_CONFIG if upstream_enabled else SQUID_VENDOR_CONFIG
    desired_line = f'SQUID_CONF="{desired_config}"'
    quoted_desired_line = shlex.quote(desired_line)
    sysconfig_path = '"$sysconfig"'

    if upstream_enabled:
        return " ".join(
            [
                "set -eu;",
                f"candidate={shlex.quote(SQUID_CANDIDATE_CONFIG)};",
                f"sysconfig={shlex.quote(SQUID_SYSCONFIG)};",
                f"wrapper={shlex.quote(SQUID_WRAPPER_CONFIG)};",
                "trap 'rm -f \"$candidate\"' EXIT;",
                f"current_squid_conf=$({effective_squid_config_command(sysconfig_path)});",
                "case \"$current_squid_conf\" in /etc/squid/squid.conf|/etc/squid/rinstall.conf) ;; *) printf '%s\\n' \"proxy.upstream cannot take ownership of Squid because SQUID_CONF points to an unmanaged configuration: ${current_squid_conf:-<unset>}\" >&2; exit 1 ;; esac;",
                "restart_needed=0;",
                f"if ! grep -Fx {quoted_desired_line} \"$sysconfig\" >/dev/null 2>&1; then restart_needed=1; fi;",
                "if ! cmp -s \"$candidate\" \"$wrapper\"; then restart_needed=1; fi;",
                "if [ \"$restart_needed\" -eq 0 ]; then exit 0; fi;",
                f"squid -k parse -f {shlex.quote(SQUID_CANDIDATE_CONFIG)};",
                "wrapper_tmp=$(mktemp /etc/squid/.rinstall.conf.XXXXXX);",
                "cp -p \"$candidate\" \"$wrapper_tmp\";",
                "mv -f \"$wrapper_tmp\" \"$wrapper\";",
                f"if grep -Eq '^[[:space:]]*SQUID_CONF[[:space:]]*=' \"$sysconfig\"; then sed -i -E 's|^[[:space:]]*SQUID_CONF[[:space:]]*=.*$|{desired_line}|' \"$sysconfig\"; else printf '\\n%s\\n' {quoted_desired_line} >> \"$sysconfig\"; fi;",
                "if systemctl is-active --quiet squid; then systemctl restart squid; fi;",
            ]
        )

    return " ".join(
        [
            "set -eu;",
            f"sysconfig={shlex.quote(SQUID_SYSCONFIG)};",
            f"wrapper={shlex.quote(SQUID_WRAPPER_CONFIG)};",
            f"current_squid_conf=$({effective_squid_config_command(sysconfig_path)});",
            "if [ \"$current_squid_conf\" != \"$wrapper\" ]; then rm -f \"$wrapper\"; exit 0; fi;",
            f"if grep -Eq '^[[:space:]]*SQUID_CONF[[:space:]]*=' \"$sysconfig\"; then sed -i -E 's|^[[:space:]]*SQUID_CONF[[:space:]]*=.*$|{desired_line}|' \"$sysconfig\"; else printf '\\n%s\\n' {quoted_desired_line} >> \"$sysconfig\"; fi;",
            "if systemctl is-active --quiet squid; then systemctl restart squid; fi;",
            "rm -f \"$wrapper\";",
        ]
    )
