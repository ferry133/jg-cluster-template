package config

import (
	"net"
	"list"
)

#Config: {
	// Who this cluster is for. No default: an unmigrated config must fail here
	// rather than be rendered under an assumed profile.
	//   appliance  zero customer-supplied fields; single node; operator-managed
	//   prosumer   customer has a NAS and some infrastructure of their own
	//   full       expert operates it directly; today's behaviour
	deployment_profile: "appliance" | "prosumer" | "full"

	// Where stateful data lives. Databases always want block storage regardless
	// of this — it selects what bulk media and file shares use.
	storage_backend: "local-path" | "nfs"

	// An appliance has no NAS to configure and nobody to configure it.
	if deployment_profile == "appliance" {
		storage_backend: "local-path"
	}

	// How this cluster's machines are provisioned. Declared rather than inferred:
	// nodes.yaml is materialised automatically for every repo (makejinja aborts on
	// a missing data file), so its presence proves nothing about the path.
	provisioning_path: "omni" | "talos"

	// The manual path needs per-node IP, NIC and disk selectors that a zero-IT
	// customer cannot supply, so reject the combination at validation time
	// instead of failing later during bootstrap.
	if deployment_profile == "appliance" {
		provisioning_path: "omni"
	}

	// Omni supplies the machine config, so a node list there is meaningless and
	// would silently render an unused talconfig. The manual path needs at least one.
	if provisioning_path == "omni" {
		nodes: []
	}
	if provisioning_path == "talos" {
		nodes: list.MinItems(1)
	}

	node_cidr: net.IPCIDR & !=cluster_pod_cidr & !=cluster_svc_cidr
	node_dns_servers?: [...net.IPv4]
	node_ntp_servers?: [...net.IPv4]
	node_default_gateway?: net.IPv4 & !=""
	node_vlan_tag?: string & !=""
	cluster_pod_cidr: *"10.42.0.0/16" | net.IPCIDR & !=node_cidr & !=cluster_svc_cidr
	// No default: the correct value differs per provisioning path (manual Talos
	// clusters use 10.43.0.0/16, Omni-provisioned clusters 10.96.0.0/12), and
	// coredns_cluster_ip is derived from it. Guessing wrong yields a coredns
	// clusterIP outside the service CIDR, which fails only after the cluster is
	// up — so require it and fail in `cue vet` instead.
	cluster_svc_cidr: net.IPCIDR & !=node_cidr & !=cluster_pod_cidr
	cluster_api_tls_sans?: [...net.FQDN]

	// LoadBalancer / VIP addresses.
	//
	// Under `appliance` these are not declared at all: the single LAN-facing
	// address is discovered at runtime (see the lan-address-allocation spec),
	// envoy-external needs no LoadBalancer because cloudflared reaches it by
	// in-cluster DNS name, and the API is reached through the Omni proxy.
	// Declaring them there would be a value nothing reads.
	cluster_api_addr?:         net.IPv4
	cluster_gateway_addr?:     net.IPv4
	cluster_dns_gateway_addr?: net.IPv4
	cloudflare_gateway_addr?:  net.IPv4

	if deployment_profile != "appliance" {
		cluster_api_addr:         net.IPv4
		cluster_gateway_addr:     net.IPv4 & !=cluster_api_addr & !=cluster_dns_gateway_addr & !=cloudflare_gateway_addr
		cluster_dns_gateway_addr: net.IPv4 & !=cluster_api_addr & !=cluster_gateway_addr & !=cloudflare_gateway_addr
		cloudflare_gateway_addr:  net.IPv4 & !=cluster_api_addr & !=cluster_gateway_addr & !=cluster_dns_gateway_addr
	}

	// Setting one of these on an appliance is a mistake worth catching: it looks
	// like it configures something but nothing reads it.
	if deployment_profile == "appliance" {
		cluster_api_addr?:         _|_
		cluster_gateway_addr?:     _|_
		cluster_dns_gateway_addr?: _|_
		cloudflare_gateway_addr?:  _|_
		mqtt_lb_ip?:               _|_
	}
	repository_name: string & !="" & !="ferry133/xxxxxx" & !="ferry133/jg-base"
	repository_branch?: string & !=""
	repository_visibility?: *"public" | "private"
	cloudflare_domain: net.FQDN
	cloudflare_token: string
	github_webhook_token?: string & !=""
	cilium_bgp_router_addr?: net.IPv4 & !=""
	cilium_bgp_router_asn?: string & !=""
	cilium_bgp_node_asn?: string & !=""
	cilium_loadbalancer_mode?: *"dsr" | "snat"
	// NAS — only meaningful when bulk storage is NFS-backed. nas_coding_path
	// stays optional even then: without it the claude-code workspace falls back
	// to the profile's default storage class.
	nas_server?: net.IPv4 & !=""
	nas_path?: string & !=""
	nas_coding_path?: string & !=""

	if storage_backend == "nfs" {
		nas_server: net.IPv4 & !=""
		nas_path: string & !=""
	}
	cluster_name: string & !=""
	coredns_cluster_ip?: net.IPv4

	// Off-site backup. A single-node appliance on local disk has no redundancy,
	// so losing the disk loses the database and the agent's accumulated context.
	// Required there rather than opt-in: rendering a cluster whose data is
	// unprotected should not be possible.
	backup_r2_bucket?: string & !=""
	backup_r2_endpoint?: string & !=""
	backup_r2_access_key_id?: string & !=""
	backup_r2_secret_access_key?: string & !=""

	if deployment_profile == "appliance" {
		backup_r2_bucket: string & !=""
		backup_r2_endpoint: string & !=""
		backup_r2_access_key_id: string & !=""
		backup_r2_secret_access_key: string & !=""
	}
	extras?: [...string]
	freepbx_mysql_root_password?: string & !=""
	freepbx_mysql_password?: string & !=""
	claudecode_postgres_password?: string & !=""
	claude_code_database_url?: string
	// claudecode/claude-code (base app on every cluster). claude_instances
	// defaults to ["im"] at render time; ttyd_credential is only unused when
	// claudecode_auth0_* switches the instances to OIDC login.
	claude_instances?: [...string]
	ttyd_credential?: string & !=""
	claudecode_auth0_domain?: string & !=""
	claudecode_auth0_client_id?: string & !=""
	claudecode_auth0_client_secret?: string & !=""
	claudecode_oauth2_cookie_secret?: string & !=""
	claudecode_allowed_emails?: string & !=""
	talos_mcp_config?: string & !=""
	talos_mcp_sa_key?: string & !=""
	talos_mcp_omni_endpoint?: string & !=""
	postgres_password?: string & !=""
	trello_api_key?: string
	trello_api_token?: string
	trello_board_id?: string
	line_channel_access_token?: string
	line_channel_secret?: string
	line_notify_group_id?: string
	anthropic_api_key?: string
	database_url?: string
	synophoto_auth0_domain?: string
	synophoto_auth0_client_id?: string
	synophoto_auth0_client_secret?: string
	synophoto_allowed_emails?: string
	synophoto_flask_secret_key?: string
	synophoto_nas_username?: string
	synophoto_nas_password?: string
	omni_gpg_key?: string
	mqtt_lb_ip?: net.IPv4 & !=""
	ingress_nginx_lb_ip?: net.IPv4 & !=""
	cloudflare_lan_tunnel_token?: string & !=""
	// monitoring/daily-check (base app on every cluster). Fields stay optional:
	// an unconfigured cluster's CronJob exits 0 with a "not configured" log
	// line instead of failing daily, so nothing breaks until these are set.
	daily_check_smtp_host?:             string
	daily_check_smtp_port?:             string
	daily_check_smtp_username?:         string
	daily_check_smtp_password?:         string
	daily_check_smtp_from?:             string
	daily_check_notify_email_to?:       string
	daily_check_healthchecks_ping_url?: string
	daily_check_endpoints?:             string
}

#Config
