from lib.proxy import bastion_proxy_environment, bastion_proxy_exports


def config_with_proxy(upstream=True):
    config = {
        "bastion": {"service_ip": "198.51.100.4", "squid_http_port": 3128},
        "proxy": {"no_proxy": ["127.0.0.0/8", "rancher.example.internal"]},
    }
    if upstream:
        config["proxy"]["upstream"] = {"host": "proxy.example.internal", "port": 9090}
    return config


def test_bastion_proxy_environment_uses_only_the_bastion_endpoint():
    assert bastion_proxy_environment(config_with_proxy()) == {
        "HTTP_PROXY": "http://198.51.100.4:3128",
        "HTTPS_PROXY": "http://198.51.100.4:3128",
        "NO_PROXY": "127.0.0.0/8,rancher.example.internal",
    }


def test_bastion_proxy_exports_are_disabled_in_direct_mode():
    assert bastion_proxy_exports(config_with_proxy(upstream=False)) == ""


def test_bastion_proxy_exports_are_local_squid_only_in_upstream_mode():
    assert bastion_proxy_exports(config_with_proxy()) == (
        "export HTTP_PROXY=http://198.51.100.4:3128; "
        "export HTTPS_PROXY=http://198.51.100.4:3128; "
        "export NO_PROXY=127.0.0.0/8,rancher.example.internal; "
    )
