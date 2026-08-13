## ADDED Requirements

### Requirement: Only LAN-reachable services consume LAN addresses

Services that no LAN client ever reaches SHALL NOT consume an address from the customer's LAN subnet. `cluster_api_addr` is reached through the Omni proxy and SHALL NOT consume a LAN address under the `appliance` profile, and `cloudflare_gateway_addr` SHALL NOT exist.

`envoy-external` is not such a service, even though `cloudflared` reaches it by in-cluster DNS name rather than by its address. `k8s-gateway` answers a hostname from whatever address its parent Gateway holds, so every externally routed name resolves, on the LAN, to `envoy-external`'s address. Making it a ClusterIP hands LAN clients an address they cannot reach — measured on jgt-appliance, `im.janncot.cc` resolved to `10.98.111.177`. It SHALL be a LoadBalancer under every profile.

Nor can it share the LAN-facing address: it listens on the same 80/443 as `envoy-internal`, and Cilium only shares an address between services whose ports do not collide. So an appliance consumes two LAN addresses, not one.

#### Scenario: Externally routed names resolve to a reachable address
- **WHEN** a LAN client resolves a hostname routed through `envoy-external` on an appliance
- **THEN** it receives a single address within the node's own subnet, and an HTTPS request to that address reaches the backend with a valid certificate

#### Scenario: Operator override retained
- **WHEN** a `full` profile cluster explicitly sets `cluster_api_addr` or `cloudflare_gateway_addr` in `cluster.yaml`
- **THEN** the explicit values are used and today's LoadBalancer behaviour is preserved unchanged

### Requirement: LAN-facing services share a single address

`envoy-internal`, `mqtt`, and (when enabled) `k8s-gateway` SHALL share one LAN address. Their listening ports do not overlap (80/443 TCP, 1883 TCP, 53 UDP+TCP), so a single address serves all three. Together with `envoy-external`, which cannot join them, the number of LAN addresses an appliance consumes SHALL be exactly two.

Sharing SHALL be enabled whenever the profile is `appliance`, not only once an address is declared. An appliance discovers its addresses, so keying the sharing key off a declared address left each service on jg-base's own per-service default — and those differ per service, so nothing shared and every service after the first sat `<pending>`.

#### Scenario: One address serves all LAN-facing services
- **WHEN** an appliance cluster is reconciled with `envoy-internal` and `mqtt` deployed
- **THEN** both Services report the same `status.loadBalancer.ingress[0].ip`

#### Scenario: Sharing annotations are present on every participating service
- **WHEN** any one of the sharing services is missing `lbipam.cilium.io/sharing-cross-namespace`
- **THEN** that service receives no address and reports `cilium.io/IPAMRequestSatisfied=False` with reason `already_allocated_incompatible_service`, while the other services keep theirs

#### Scenario: Port collision surfaces as an unsatisfied condition
- **WHEN** a service requesting the shared address declares a port already claimed on that address
- **THEN** that service receives no address and reports `cilium.io/IPAMRequestSatisfied=False` with reason `already_allocated_incompatible_service`, rather than being assigned a second LAN address

### Requirement: The address pool contains only deliberately allocated addresses

The `CiliumLoadBalancerIPPool` SHALL contain only the addresses this cluster has deliberately claimed. A pool spanning the whole node CIDR lets any Service that omits an address annotation draw an arbitrary address from the customer's LAN, and it also lets a port collision silently consume a second address instead of reporting failure. Constraining the pool is what makes both failures observable.

#### Scenario: Pool is narrow
- **WHEN** an appliance cluster's LB-IPAM pool is inspected
- **THEN** its blocks contain only the discovered address(es), not the node CIDR

#### Scenario: Unannotated service cannot take a LAN address
- **WHEN** a Service of type LoadBalancer is created without an address annotation and no pool address is free
- **THEN** it receives no address and reports an unsatisfied IPAM condition, rather than being assigned an arbitrary address from the customer's LAN

### Requirement: LAN address is discovered, not configured

For the `appliance` profile the LAN address SHALL be obtained automatically and MUST NOT be a `cluster.yaml` field. The discovery component SHALL emit its result as a `CiliumLoadBalancerIPPool` resource.

#### Scenario: Address discovered on first reconcile
- **WHEN** an appliance cluster reconciles for the first time on an unknown LAN
- **THEN** a `CiliumLoadBalancerIPPool` containing exactly two addresses within the node's own subnet is created, and every LAN-facing Service binds to one of them

#### Scenario: No address is requested while none is declared
- **WHEN** an appliance renders with no `lan_shared_addr`
- **THEN** no Service carries an `lbipam.cilium.io/ips` annotation, so allocation comes from the discovered pool — jg-base's `0.0.0.0` fallback is a request LB-IPAM can never satisfy and would leave the service `<pending>` forever

#### Scenario: Discovery result is stable across restarts
- **WHEN** the discovery component restarts
- **THEN** it reproduces the same address rather than selecting a new one, and existing Service assignments are unchanged

### Requirement: Allocation mechanism is replaceable behind the pool interface

The initial implementation SHALL discover a free address by ARP probing the node's subnet. Its only contract with the rest of the system is the emitted `CiliumLoadBalancerIPPool`. A later DHCP lease-holder implementation MUST be substitutable without changes to Cilium configuration, Service annotations, templates, or CUE schema.

#### Scenario: Probe implementation emits the contract
- **WHEN** the ARP-probe implementation completes discovery
- **THEN** its sole cluster-visible output is a `CiliumLoadBalancerIPPool`, with no Service or HelmRelease field carrying the discovered address

#### Scenario: Swap does not ripple
- **WHEN** the probe implementation is replaced by a DHCP lease-holder that emits the same pool
- **THEN** no template, CUE field, or `jg-base` manifest outside the discovery component requires modification

### Requirement: Address conflicts are detected and reported

The discovery component SHALL continue to monitor the chosen address after assignment. An ARP-probed address can later collide with a device that was powered off at probe time; this MUST surface as an operator-visible signal rather than as unexplained LAN service failures.

#### Scenario: Post-assignment collision detected
- **WHEN** another host on the LAN begins answering ARP for the assigned address
- **THEN** the conflict is recorded in the daily health report and raised to the operator

#### Scenario: Conflict triggers re-selection
- **WHEN** a collision is confirmed
- **THEN** a new free address is selected, the pool is updated, and the change is logged with both the old and new address
