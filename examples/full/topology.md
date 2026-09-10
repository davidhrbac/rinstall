# Desired Topology

> Status: desired configuration only; runtime state and reachability are not verified.

## Infrastructure Map

<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc" viewBox="0 0 980 478" width="980" height="478">
<title id="title">Desired infrastructure topology</title>
<desc id="desc">Environment full-example infrastructure attachment map</desc>
<style>
          .background { fill: #ffffff; }
          .management { fill: #e8eefc; stroke: #4969a8; stroke-width: 2; }
          .bastion { fill: #fff1c7; stroke: #8a6420; stroke-width: 2.5; }
          .network { fill: #f1f3f5; stroke: #6b7280; stroke-width: 2; }
          .monitoring { fill: #e4f5eb; stroke: #39735a; stroke-width: 2; }
          .rancher-cluster { fill: #e5f0ff; stroke: #315a8a; stroke-width: 2; }
          .downstream-group { fill: #faf7fd; stroke: #9b83ad; stroke-width: 1.5; stroke-dasharray: 6 4; }
          .downstream { fill: #f3e8ff; stroke: #76508f; stroke-width: 2; }
          .connector { stroke: #475569; stroke-width: 2.5; fill: none; }
          .heading { font: 600 15px sans-serif; fill: #1f2937; text-anchor: middle; }
          .box-label { font: 13px sans-serif; fill: #17202a; text-anchor: middle; }
          .row-name { font: 600 12px sans-serif; fill: #17202a; text-anchor: start; }
          .row-value { font: 12px sans-serif; fill: #334155; text-anchor: end; }
        </style>
<rect class="background" x="0" y="0" width="980" height="478" />
<g id="management-network">
<rect class="management" x="350" y="20" width="170" height="54" rx="9" />
<text class="box-label" x="435.0" y="43">Management</text>
<text class="box-label" x="435.0" y="61">192.0.2.0/24</text>
</g>
<polyline class="connector" data-connection="management-bastion" points="435,74 435,100" />
<g id="bastion">
<rect class="bastion" x="325" y="100" width="220" height="82" rx="9" />
<text class="box-label" x="435.0" y="123">bastion1</text>
<text class="box-label" x="435.0" y="141">customer: 198.51.100.4/28</text>
<text class="box-label" x="435.0" y="159">management: 192.0.2.10/24</text>
</g>
<g id="customer-network">
<rect class="network" x="80" y="235" width="200" height="58" rx="9" />
<text class="box-label" x="180.0" y="258">Customer network</text>
<text class="box-label" x="180.0" y="276">198.51.100.0/28</text>
</g>
<polyline class="connector" data-connection="bastion-customer" points="325,141 180,141 180,235" />
<polyline class="connector" data-connection="customer-monitoring" points="150,293 150,340" />
<polyline class="connector" data-connection="customer-rancher" points="250,293 250,320 400,320 400,340" />
<g id="monitoring">
<rect class="monitoring" x="45" y="340" width="190" height="68" rx="9" />
<text class="heading" x="140.0" y="362">Monitoring</text>
<text class="row-name" x="59" y="385">prom1</text>
<text class="row-value" x="221" y="385">198.51.100.6</text>
</g>
<g id="rancher-cluster">
<rect class="rancher-cluster" x="270" y="340" width="260" height="108" rx="9" />
<text class="heading" x="400.0" y="362">Rancher cluster</text>
<text class="row-name" x="286" y="385">rancher1</text>
<text class="row-value" x="514" y="385">198.51.100.11</text>
<text class="row-name" x="286" y="405">rancher2</text>
<text class="row-value" x="514" y="405">198.51.100.12</text>
<text class="row-name" x="286" y="425">rancher3</text>
<text class="row-value" x="514" y="425">198.51.100.13</text>
</g>
<g id="downstream-networks">
<rect class="downstream-group" x="570" y="215" width="394" height="136" rx="10" />
<text class="heading" x="767.0" y="238">Downstream networks</text>
<g id="downstream-vlan-565">
<rect class="downstream" x="586" y="249" width="174" height="88" rx="9" />
<text class="box-label" x="673.0" y="272">VLAN 565</text>
<text class="box-label" x="673.0" y="290">203.0.113.32/27</text>
<text class="box-label" x="673.0" y="308">bastion 203.0.113.34</text>
<text class="box-label" x="673.0" y="326">gateway 203.0.113.33</text>
</g>
<g id="downstream-vlan-566">
<rect class="downstream" x="774" y="249" width="174" height="88" rx="9" />
<text class="box-label" x="861.0" y="272">VLAN 566</text>
<text class="box-label" x="861.0" y="290">203.0.113.64/27</text>
<text class="box-label" x="861.0" y="308">bastion 203.0.113.66</text>
<text class="box-label" x="861.0" y="326">gateway 203.0.113.65</text>
</g>
</g>
<polyline class="connector" data-connection="bastion-downstream" points="545,141 558,141 558,245 570,245" />
</svg>

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
- `topology.mmd`, `connectivity.mmd`, and `topology.txt` are secondary support artifacts.
