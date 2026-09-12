# Instance Repository Fixture

This layout-only fixture represents a private instance repository:

- `config.yaml` is the desired configuration source of truth.
- `rinstall` is the pinned engine submodule.
- `docs/topology/` is created by `make -f rinstall/Makefile topology-docs` for committed support documentation.
- `.rinstall/` contains ignored private runtime artifacts.
- `.envrc` contains ignored runtime credentials and environment variables.

For a complete instance configuration, generate the four committed topology
files with:

```bash
make -f rinstall/Makefile topology-docs
make -f rinstall/Makefile topology-docs-check
```

The fixture configuration is intentionally incomplete and is not a provisioning
environment.
