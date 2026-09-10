#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env
from lib.topology import (
    build_desired_topology,
    render_topology_json,
    render_topology_markdown,
    render_topology_infrastructure_mermaid,
    render_topology_ascii_overview,
)


def write_private_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
        temporary.replace(path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Render desired infrastructure topology from config.yaml")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--output-dir", required=True, help="Private runtime output directory")
    args = parser.parse_args()

    topology = build_desired_topology(load_env(args.config))
    output_dir = Path(args.output_dir)
    json_path = output_dir / "topology.json"
    markdown_path = output_dir / "topology.md"
    text_path = output_dir / "topology.txt"
    infrastructure_mermaid_path = output_dir / "topology.mmd"
    write_private_text(json_path, render_topology_json(topology))
    write_private_text(markdown_path, render_topology_markdown(topology))
    write_private_text(text_path, render_topology_ascii_overview(topology))
    write_private_text(infrastructure_mermaid_path, render_topology_infrastructure_mermaid(topology))
    print(json_path)
    print(markdown_path)
    print(text_path)
    print(infrastructure_mermaid_path)


if __name__ == "__main__":
    main()
