# Desired Topology: full-example

> Status: desired configuration only; runtime state and reachability are not verified.

## Architecture Map

```mermaid
flowchart LR
  actor_operator_workstation_974971eaa5["Operator / rinstall"]
  endpoint_endpoint_ssh_jump_f7b7c2ca2d["SSH jump<br/>example-operator-jump<br/>external unresolved"]
  host_bastion1_fd65cf69ce["Bastion<br/>bastion1<br/>DNS · DHCP · proxy · SSH transit"]
  subgraph monitoring["Monitoring"]
    direction TB
    host_prom1_abf2e7bd7a["Monitoring host<br/>prom1"]
  end
  cluster_cluster_rke2_rancher_de77c71a50["RKE2 / Rancher cluster<br/>rancher1 primary<br/>rancher2<br/>rancher3"]
  endpoint_endpoint_rancher_0637b61772["Rancher endpoint<br/>rancher.full-example.example.invalid<br/>HTTPS / 443<br/>external exposure: unresolved"]
  subgraph downstream["Downstream environments"]
    direction TB
    consumer_consumer_downstream_vlan565_dfc74929d4["Downstream nodes<br/>VLAN 565<br/>external lifecycle"]
    consumer_consumer_downstream_vlan566_30b7d29b35["Downstream nodes<br/>VLAN 566<br/>external lifecycle"]
  end
  endpoint_endpoint_vcenter_bba77268c7["vSphere<br/>runtime endpoint unresolved"]
  endpoint_endpoint_terraform_backend_a27fbcb411["Terraform state backend<br/>GitLab"]
  actor_operator_workstation_974971eaa5 --> endpoint_endpoint_ssh_jump_f7b7c2ca2d
  endpoint_endpoint_ssh_jump_f7b7c2ca2d --> host_bastion1_fd65cf69ce
  host_bastion1_fd65cf69ce --> host_prom1_abf2e7bd7a
  host_bastion1_fd65cf69ce --> cluster_cluster_rke2_rancher_de77c71a50
  cluster_cluster_rke2_rancher_de77c71a50 --> endpoint_endpoint_rancher_0637b61772
  consumer_consumer_downstream_vlan565_dfc74929d4 --> endpoint_endpoint_rancher_0637b61772
  consumer_consumer_downstream_vlan566_30b7d29b35 --> endpoint_endpoint_rancher_0637b61772
  actor_operator_workstation_974971eaa5 --> endpoint_endpoint_vcenter_bba77268c7
  actor_operator_workstation_974971eaa5 --> endpoint_endpoint_terraform_backend_a27fbcb411
```

## Infrastructure Topology

```mermaid
flowchart TB
  network_management_288965a1f2["Management<br/>192.0.2.0/24"]
  host_bastion1_fd65cf69ce["bastion1<br/>customer: 198.51.100.4/28<br/>management: 192.0.2.10/24"]
  network_customer_b6c4586387["Customer network<br/>198.51.100.0/28"]
  host_prom1_abf2e7bd7a["prom1<br/>198.51.100.6"]
  subgraph rancher_cluster["Rancher cluster"]
    direction LR
    host_rancher1_d47e6b0e07["rancher1<br/>198.51.100.11"]
    host_rancher2_bcc55a020f["rancher2<br/>198.51.100.12"]
    host_rancher3_bbbf0c319b["rancher3<br/>198.51.100.13"]
  end
  subgraph downstream["Downstream networks"]
    direction LR
    network_downstream_vlan565_8ed6786137["VLAN 565<br/>203.0.113.32/27<br/>bastion: 203.0.113.34<br/>gateway: 203.0.113.33"]
    network_downstream_vlan566_d2bd8ff235["VLAN 566<br/>203.0.113.64/27<br/>bastion: 203.0.113.66<br/>gateway: 203.0.113.65"]
  end
  network_management_288965a1f2 --- host_bastion1_fd65cf69ce
  host_bastion1_fd65cf69ce --- network_customer_b6c4586387
  network_customer_b6c4586387 --- host_prom1_abf2e7bd7a
  network_customer_b6c4586387 --- host_rancher1_d47e6b0e07
  network_customer_b6c4586387 --- host_rancher2_bcc55a020f
  network_customer_b6c4586387 --- host_rancher3_bbbf0c319b
  host_bastion1_fd65cf69ce --- network_downstream_vlan565_8ed6786137
  host_bastion1_fd65cf69ce --- network_downstream_vlan566_d2bd8ff235
```

## Network Topology — Mermaid

```mermaid
flowchart TB
  network_management_288965a1f2["Management<br/>192.0.2.0/24<br/>VMware: EXAMPLE_MANAGEMENT_NETWORK<br/>bastion: 192.0.2.10"]
  host_bastion1_fd65cf69ce["bastion1<br/>multi-homed<br/>not a router"]
  network_customer_b6c4586387["Customer<br/>198.51.100.0/28<br/>VMware: EXAMPLE_CUSTOMER_NETWORK<br/>bastion: 198.51.100.4<br/>gateway: 198.51.100.1"]
  host_prom1_abf2e7bd7a["prom1<br/>198.51.100.6"]
  subgraph cluster_cluster_rke2_rancher_de77c71a50["RKE2 / Rancher"]
    direction TB
    host_rancher1_d47e6b0e07["rancher1 primary<br/>198.51.100.11"]
    host_rancher2_bcc55a020f["rancher2<br/>198.51.100.12"]
    host_rancher3_bbbf0c319b["rancher3<br/>198.51.100.13"]
  end
  subgraph downstream_downstream_vlan565_8ed6786137["VLAN 565"]
    direction TB
    network_downstream_vlan565_8ed6786137["VLAN 565<br/>203.0.113.32/27<br/>VMware: EXAMPLE_DOWNSTREAM_NETWORK_565<br/>bastion: 203.0.113.34"]
    consumer_consumer_downstream_vlan565_dfc74929d4["Downstream nodes<br/>DHCP 203.0.113.36-203.0.113.61<br/>external lifecycle"]
    external_endpoint_gateway_vlan565_97aa5a5c3b["External gateway<br/>203.0.113.33"]
  end
  network_downstream_vlan565_8ed6786137 --- consumer_consumer_downstream_vlan565_dfc74929d4
  network_downstream_vlan565_8ed6786137 --- external_endpoint_gateway_vlan565_97aa5a5c3b
  subgraph downstream_downstream_vlan566_d2bd8ff235["VLAN 566"]
    direction TB
    network_downstream_vlan566_d2bd8ff235["VLAN 566<br/>203.0.113.64/27<br/>VMware: EXAMPLE_DOWNSTREAM_NETWORK_566<br/>bastion: 203.0.113.66"]
    consumer_consumer_downstream_vlan566_30b7d29b35["Downstream nodes<br/>DHCP 203.0.113.68-203.0.113.93<br/>external lifecycle"]
    external_endpoint_gateway_vlan566_8cbaf7cad8["External gateway<br/>203.0.113.65"]
  end
  network_downstream_vlan566_d2bd8ff235 --- consumer_consumer_downstream_vlan566_30b7d29b35
  network_downstream_vlan566_d2bd8ff235 --- external_endpoint_gateway_vlan566_8cbaf7cad8
  host_bastion1_fd65cf69ce --- network_customer_b6c4586387
  network_management_288965a1f2 --- host_bastion1_fd65cf69ce
  network_customer_b6c4586387 --- host_prom1_abf2e7bd7a
  network_customer_b6c4586387 --- host_rancher1_d47e6b0e07
  network_customer_b6c4586387 --- host_rancher2_bcc55a020f
  network_customer_b6c4586387 --- host_rancher3_bbbf0c319b
  host_bastion1_fd65cf69ce --- network_downstream_vlan565_8ed6786137
  host_bastion1_fd65cf69ce --- network_downstream_vlan566_d2bd8ff235
  network_customer_b6c4586387 -. "external routing / firewall" .-> network_downstream_vlan565_8ed6786137
  network_customer_b6c4586387 -. "external routing / firewall" .-> network_downstream_vlan566_d2bd8ff235
```

## Network Topology — Graphviz

![Network topology](network-topology.svg)

This is temporary evaluation output.

## Environment

| Environment | Rancher URL | Domain | RKE2 | Rancher | cert-manager |
| --- | --- | --- | --- | --- | --- |
| full-example | rancher.full-example.example.invalid | full-example.example.invalid | v1.35.7+rke2r1 | 2.14.4 | v1.21.1 |

## Hosts

| Host | FQDN | Roles | Customer IP | Management IP | SSH target |
| --- | --- | --- | --- | --- | --- |
| bastion1 | bastion1.rancher.full-example.example.invalid | bastion | 198.51.100.4 | 192.0.2.10 | 192.0.2.10 |
| prom1 | prom1.rancher.full-example.example.invalid | prometheus | 198.51.100.6 | not attached | 198.51.100.6 |
| rancher1 | rancher1.rancher.full-example.example.invalid | rancher | 198.51.100.11 | not attached | 198.51.100.11 |
| rancher2 | rancher2.rancher.full-example.example.invalid | rancher | 198.51.100.12 | not attached | 198.51.100.12 |
| rancher3 | rancher3.rancher.full-example.example.invalid | rancher | 198.51.100.13 | not attached | 198.51.100.13 |

## Networks

| Network | Kind | VMware network | CIDR | VLAN | Bastion IP | Gateway |
| --- | --- | --- | --- | --- | --- | --- |
| customer | local/customer | EXAMPLE_CUSTOMER_NETWORK | 198.51.100.0/28 | - | - | 198.51.100.1 |
| management | management | EXAMPLE_MANAGEMENT_NETWORK | 192.0.2.0/24 | - | - | - |
| downstream:vlan565 | downstream | EXAMPLE_DOWNSTREAM_NETWORK_565 | 203.0.113.32/27 | 565 | 203.0.113.34 | 203.0.113.33 |
| downstream:vlan566 | downstream | EXAMPLE_DOWNSTREAM_NETWORK_566 | 203.0.113.64/27 | 566 | 203.0.113.66 | 203.0.113.65 |

## Key Connectivity

```text
Rancher nodes -> Downstream nodes       TCP/22
Downstream -> same-VLAN bastion IP      TCP/UDP 53
Downstream -> bastion DHCP service      UDP 67/68
```

## Resolved Connectivity

| Source | Destination | Protocol | Purpose |
| --- | --- | --- | --- |
| vlan565 (203.0.113.32/27) | bastion1:vlan565 (203.0.113.34) | TCP/UDP 53 | DNS for downstream nodes |
| rancher1 (198.51.100.11), rancher2 (198.51.100.12), rancher3 (198.51.100.13) | vlan565 (203.0.113.32/27) | TCP 22 | Administrator SSH from Rancher nodes to downstream nodes |
| vlan565 (203.0.113.32/27) | bastion1:vlan565 (203.0.113.34) | UDP 68 -> 67 | Downstream DHCP request |
| bastion1:vlan565 (203.0.113.34) | vlan565 (203.0.113.32/27) | UDP 67 -> 68 | Downstream DHCP response |
| vlan566 (203.0.113.64/27) | bastion1:vlan566 (203.0.113.66) | TCP/UDP 53 | DNS for downstream nodes |
| rancher1 (198.51.100.11), rancher2 (198.51.100.12), rancher3 (198.51.100.13) | vlan566 (203.0.113.64/27) | TCP 22 | Administrator SSH from Rancher nodes to downstream nodes |
| vlan566 (203.0.113.64/27) | bastion1:vlan566 (203.0.113.66) | UDP 68 -> 67 | Downstream DHCP request |
| bastion1:vlan566 (203.0.113.66) | vlan566 (203.0.113.64/27) | UDP 67 -> 68 | Downstream DHCP response |

## Details

<details>
<summary>Interface and bastion service details</summary>

| Host | Interface | Network | Kind | Address | Addressing |
| --- | --- | --- | --- | --- | --- |
| bastion1 | customer | customer | local/customer | 198.51.100.4/28 | static |
| bastion1 | management | management | management | 192.0.2.10/24 | static |
| prom1 | customer | customer | local/customer | 198.51.100.6/28 | static |
| rancher1 | customer | customer | local/customer | 198.51.100.11/28 | static |
| rancher2 | customer | customer | local/customer | 198.51.100.12/28 | static |
| rancher3 | customer | customer | local/customer | 198.51.100.13/28 | static |
| bastion1 | vlan565 | downstream:vlan565 | downstream | 203.0.113.34/27 | static |
| bastion1 | vlan566 | downstream:vlan566 | downstream | 203.0.113.66/27 | static |

| Service | Network | Endpoint | Proto/Port | Purpose |
| --- | --- | --- | --- | --- |
| proxy | customer | 198.51.100.4 | TCP 3128 | HTTP and HTTPS forward proxy for local services |
| dns | customer | 198.51.100.4 | TCP/UDP 53 | DNS for local nodes |
| dns | downstream:vlan565 | 203.0.113.34 | TCP/UDP 53 | DNS for downstream nodes on the same VLAN |
| dhcp | downstream:vlan565 | 203.0.113.34 | UDP 67/68 | DHCP for downstream nodes on the same VLAN |
| dns | downstream:vlan566 | 203.0.113.66 | TCP/UDP 53 | DNS for downstream nodes on the same VLAN |
| dhcp | downstream:vlan566 | 203.0.113.66 | UDP 67/68 | DHCP for downstream nodes on the same VLAN |

</details>

## Notes

- Desired topology only; provider state, guest runtime state, and network reachability are not verified.
- `not attached` means that the host has no interface on that network.
- External SSH jump-host details are intentionally not represented here.
- `topology.mmd` and `topology.txt` are secondary support artifacts.
