import shlex


def bastion_proxy_environment(config):
    return {
        "HTTP_PROXY": f"http://{config['bastion']['service_ip']}:{config['bastion']['squid_http_port']}",
        "HTTPS_PROXY": f"http://{config['bastion']['service_ip']}:{config['bastion']['squid_http_port']}",
        "NO_PROXY": ",".join(config["proxy"]["no_proxy"]),
    }


def bastion_proxy_exports(config):
    if "upstream" not in config["proxy"]:
        return ""
    return "; ".join(
        f"export {key}={shlex.quote(str(value))}"
        for key, value in bastion_proxy_environment(config).items()
    ) + "; "
