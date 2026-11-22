# ==============================================================================
# Oracle Cloud Infrastructure (OCI) — Always Free ARM Ampere A1 (0 EUR / mois)
# 4 OCPU + 24 Go RAM + 200 Go stockage — idéal pour Nexus + Postgres + Langfuse
# ==============================================================================

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
}

provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.oci_private_key_path
  region           = var.region
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_vcn" "nexus_vcn" {
  compartment_id = var.compartment_ocid
  cidr_block     = "10.0.0.0/16"
  display_name   = "nexus-vcn"
  dns_label      = "nexusvcn"
}

resource "oci_core_internet_gateway" "nexus_igw" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.nexus_vcn.id
  display_name   = "nexus-igw"
}

resource "oci_core_route_table" "nexus_rt" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.nexus_vcn.id
  display_name   = "nexus-rt"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.nexus_igw.id
  }
}

resource "oci_core_security_list" "nexus_sl" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.nexus_vcn.id
  display_name   = "nexus-zero-trust-sl"

  # Trafic sortant autorisé (APIs LLM, Discord WebSocket, Tailscale DERP/UDP)
  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }

  # SSH temporaire pour le bootstrap (désactivable dès que Tailscale SSH est actif)
  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 22
      max = 22
    }
  }
}

resource "oci_core_subnet" "nexus_subnet" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.nexus_vcn.id
  cidr_block        = "10.0.1.0/24"
  display_name      = "nexus-subnet"
  route_table_id    = oci_core_route_table.nexus_rt.id
  security_list_ids = [oci_core_security_list.nexus_sl.id]
}

resource "oci_core_instance" "nexus_arm" {
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  compartment_id      = var.compartment_ocid
  display_name        = "nexus-agents-arm"
  shape               = "VM.Standard.A1.Flex"

  # Quotas Always Free max : 4 OCPU & 24 Go RAM (0 EUR)
  shape_config {
    ocpus         = 4
    memory_in_gbs = 24
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = 100
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.nexus_subnet.id
    assign_public_ip = true
  }

  metadata = {
    ssh_authorized_keys = file(var.ssh_public_key_path)
    user_data = base64encode(templatefile("${path.module}/../cloud-init.yaml", {
      tailscale_authkey = var.tailscale_authkey
    }))
  }
}

output "instance_public_ip" {
  description = "IP publique de l'instance OCI ARM Always Free"
  value       = oci_core_instance.nexus_arm.public_ip
}
