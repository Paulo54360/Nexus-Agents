variable "subscription_id" {
  description = "Azure Subscription ID (récupéré via `az account show --query id -o tsv`)"
  type        = string
}

variable "location" {
  description = "Région Azure (swedencentral = meilleur support B-series v2 sur Azure for Students)"
  type        = string
  default     = "swedencentral"
}

variable "vm_size" {
  description = "Taille VM (Standard_B2als_v2 = 2 vCPU AMD / 4 Go RAM ~14$/mois sur crédits Student)"
  type        = string
  default     = "Standard_B2als_v2"
}

variable "ssh_public_key_path" {
  description = "Chemin vers ta clé publique SSH RSA (Azure exige le format RSA)"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "tailscale_authkey" {
  description = "Clé d'auth Tailscale pour connexion Zero-Trust automatique (0 port public)"
  type        = string
  sensitive   = true
  default     = ""
}
