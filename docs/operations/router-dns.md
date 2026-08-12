# Pointing the router's DNS at the cluster

One configuration step, performed by the operator during installation. After it,
the customer never touches DNS again.

## Why this step exists

Internal hostnames (`homebridge.<domain>`, `mqtt.<domain>`, …) resolve to an
address on the customer's own LAN. Three ways to deliver that answer were
considered; only this one works end to end:

| | why not |
|---|---|
| Publish public A records with the private address | Cloudflare refuses to serve RFC1918 answers for zones it hosts. Measured: the API accepts the record, the authoritative NS returns NXDOMAIN, while a record with a public address created in the same breath resolves immediately. |
| mDNS / `.local` | Resolvers only route `.local` to multicast, so every hostname would have to change — and `.local` cannot hold a public TLS certificate, so anything with a login shows a certificate error unless a private CA is installed on every device. |
| Delegate a subdomain to another DNS provider | Works, but adds a second provider and its credentials, and puts an extra label in every hostname. |

`k8s-gateway` answers those names correctly. It just has to be asked, and a
resolver is only asked if something points at it.

## What to set

Set the LAN's **DNS server** to the cluster's shared LAN address — the same
address `envoy-internal` and `mqtt` use. Find it with:

```sh
kubectl -n network get svc k8s-gateway \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}{"\n"}'
```

There are three ways to deliver that, and they fail very differently.

| | internal names | when the cluster is down |
|---|---|---|
| **Conditional forwarding** — send only `<domain>` to the cluster | all of them, automatically | only internal names break |
| Per-host records on the router | each one added by hand | only those names break |
| DHCP DNS server → the cluster | all of them, automatically | **the whole LAN loses DNS** |

**Prefer conditional forwarding.** `k8s-gateway` forwards queries for domains it
does not serve, so pointing the LAN's DNS server at it puts every lookup in the
house through this cluster — and a cluster that is down then takes the internet
with it. That is the failure mode this design rejected elsewhere (D3) when it
declined to put the appliance in the network path.

UniFi's UDM/UDR run dnsmasq underneath, which supports `server=/<domain>/<addr>`
natively; whether the UI exposes it depends on the version. If it does not, add
the handful of internal hostnames as local DNS records instead and accept the
manual step — it is still safer than making the cluster answer for everything.

Only use the DHCP DNS server route on a cluster where losing DNS with the
cluster is acceptable, and say so in the handover notes if you do.

## Pin the address before you set it

On an appliance the address is chosen by ARP probing (`lan-address-probe`),
which by default re-checks it and may reselect if something else starts
answering for it. **Once it is written into a router, it is an external
contract**: a reselection would leave the router pointing at nothing, and every
internal name would fail at once with nothing in the cluster looking wrong.

So before configuring the router, promote the discovered address to a declared
one:

```yaml
# cluster.yaml
lan_shared_addr: "10.9.x.y"   # the address the probe settled on
```

Re-render and push. From then on the address is fixed, and a collision is
reported for a human to act on rather than silently worked around.

## Verify

From a LAN client — a laptop on Wi-Fi, not the node:

```sh
# should return the cluster's LAN address
nslookup internal.<domain>
```

If it returns nothing, the DHCP lease has not been renewed yet. Reconnect the
client to the network and try again before changing anything.

## What happens if it is lost

A router reset, a replacement unit, or an ISP-pushed configuration all silently
undo this step. Every internal hostname stops resolving on the LAN while the
cluster itself stays perfectly healthy — which is exactly the kind of failure
nobody attributes correctly.

The daily health check asks the router directly and reports
`LAN cannot resolve internal names` as a FAIL, which also withholds the dead-man
ping. Re-doing the step above is the fix.
