#!/usr/bin/env python3
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env
from lib.topology import (
    build_desired_topology,
    render_topology_architecture_mermaid,
    render_topology_ascii_overview,
    render_topology_markdown,
    render_topology_network_mermaid,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--docs-dir", required=True)
    args = parser.parse_args()
    topology = build_desired_topology(load_env(args.config))
    expected = {
        "topology.md": render_topology_markdown(topology),
        "architecture.mmd": render_topology_architecture_mermaid(topology),
        "network-topology.mmd": render_topology_network_mermaid(topology),
        "topology.txt": render_topology_ascii_overview(topology),
    }
    docs_dir = Path(args.docs_dir)
    with TemporaryDirectory() as temporary:
        generated_dir = Path(temporary)
        for name, content in expected.items():
            (generated_dir / name).write_bytes(content.encode())
        generated_names = {path.name for path in generated_dir.iterdir()}
        actual_names = {path.name for path in docs_dir.iterdir()} if docs_dir.exists() else set()
        if actual_names != generated_names:
            raise SystemExit(
                f"topology docs file set differs: expected={sorted(generated_names)} actual={sorted(actual_names)}"
            )
        for name in generated_names:
            if (docs_dir / name).read_bytes() != (generated_dir / name).read_bytes():
                raise SystemExit(f"topology docs are stale: {docs_dir / name}")


if __name__ == "__main__":
    main()
