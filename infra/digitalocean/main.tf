terraform {
  required_version = ">= 1.6.0"
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.40"
    }
  }
}

provider "digitalocean" {
  token = var.do_token
}

resource "digitalocean_ssh_key" "nexus" {
  name       = "nexus-deploy-key"
  public_key = file(var.ssh_public_key_path)
}

resource "digitalocean_droplet" "nexus" {
  name       = "nexus-agents-vps"
  region     = var.region
  size       = var.droplet_size
  image      = "ubuntu-24-04-x64"
  ssh_keys   = [digitalocean_ssh_key.nexus.fingerprint]
  monitoring = true
  tags       = ["nexus", "ai-agents", "devops"]

  user_data = templatefile("${path.module}/../cloud-init.yaml", {
    tailscale_authkey = var.tailscale_authkey
  })
}

output "droplet_public_ip" {
  description = "IP publique du VPS (utiliser Tailscale une fois connecté)"
  value       = digitalocean_droplet.nexus.ipv4_address
}
