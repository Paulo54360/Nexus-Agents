# ==============================================================================
# Microsoft Azure for Students (100 $ gratuits sans CB) — OpenTofu / Terraform
# Déploie une VM Ubuntu 24.04 Zero-Trust (0 port public ouvert, accès Tailscale)
# ==============================================================================

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

resource "azurerm_resource_group" "nexus" {
  name     = "rg-nexus-prod"
  location = var.location
  tags = {
    project = "nexus-agents"
    env     = "prod"
  }
}

resource "azurerm_virtual_network" "nexus" {
  name                = "vnet-nexus"
  address_space       = ["10.10.0.0/16"]
  location            = azurerm_resource_group.nexus.location
  resource_group_name = azurerm_resource_group.nexus.name
}

resource "azurerm_subnet" "nexus" {
  name                 = "snet-nexus"
  resource_group_name  = azurerm_resource_group.nexus.name
  virtual_network_name = azurerm_virtual_network.nexus.name
  address_prefixes     = ["10.10.1.0/24"]
}

resource "azurerm_public_ip" "nexus" {
  name                = "pip-nexus"
  location            = azurerm_resource_group.nexus.location
  resource_group_name = azurerm_resource_group.nexus.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

# Zero-Trust NSG: 0 inbound port allowed when Tailscale auth key is provided
resource "azurerm_network_security_group" "nexus" {
  name                = "nsg-nexus-zero-trust"
  location            = azurerm_resource_group.nexus.location
  resource_group_name = azurerm_resource_group.nexus.name

  dynamic "security_rule" {
    for_each = var.tailscale_authkey == "" ? [1] : []
    content {
      name                       = "AllowSSHBootstrap"
      priority                   = 100
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "22"
      source_address_prefix      = "*"
      destination_address_prefix = "*"
    }
  }
}

resource "azurerm_network_interface" "nexus" {
  name                = "nic-nexus"
  location            = azurerm_resource_group.nexus.location
  resource_group_name = azurerm_resource_group.nexus.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.nexus.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.nexus.id
  }
}

resource "azurerm_network_interface_security_group_association" "nexus" {
  network_interface_id      = azurerm_network_interface.nexus.id
  network_security_group_id = azurerm_network_security_group.nexus.id
}

resource "azurerm_linux_virtual_machine" "nexus" {
  name                = "vm-nexus-agents"
  resource_group_name = azurerm_resource_group.nexus.name
  location            = azurerm_resource_group.nexus.location
  size                = var.vm_size
  admin_username      = "deploy"

  network_interface_ids = [
    azurerm_network_interface.nexus.id,
  ]

  admin_ssh_key {
    username   = "deploy"
    public_key = file(pathexpand(var.ssh_public_key_path))
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64encode(templatefile("${path.module}/../cloud-init.yaml", {
    tailscale_authkey = var.tailscale_authkey
  }))
}

output "vm_public_ip" {
  description = "IP publique Azure (utiliser Tailscale `ssh deploy@nexus-vps` une fois prêt)"
  value       = azurerm_public_ip.nexus.ip_address
}
