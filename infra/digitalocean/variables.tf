variable "do_token" {
  description = "DigitalOcean API Token (crédits GitHub Student)"
  type        = string
  sensitive   = true
}

variable "ssh_public_key_path" {
  description = "Chemin vers ta clé publique SSH (ex: ~/.ssh/id_ed25519.pub)"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "region" {
  description = "Région DigitalOcean (fra1 = Francfort, ams3 = Amsterdam)"
  type        = string
  default     = "fra1"
}

variable "droplet_size" {
  description = "Taille du Droplet (s-2vcpu-4gb recommandé si tu actives Langfuse)"
  type        = string
  default     = "s-2vcpu-4gb"
}

variable "tailscale_authkey" {
  description = "Clé d'auth Tailscale réutilisable/éphémère (optionnelle au premier boot)"
  type        = string
  sensitive   = true
  default     = ""
}
