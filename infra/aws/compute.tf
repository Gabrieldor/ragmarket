# Latest Ubuntu 22.04 LTS ARM64 AMI (Canonical official)
data "aws_ami" "ubuntu_arm" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_key_pair" "market_intel" {
  key_name   = "market-intel"
  public_key = file(var.ssh_public_key_path)
}

resource "aws_instance" "market_intel" {
  ami                    = data.aws_ami.ubuntu_arm.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.market_intel.id
  vpc_security_group_ids = [aws_security_group.market_intel.id]
  key_name               = aws_key_pair.market_intel.key_name
  iam_instance_profile   = aws_iam_instance_profile.market_intel.name

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  # Add 2GB swap so Playwright/Chromium doesn't OOM on 2GB RAM
  user_data = <<-EOF
    #!/bin/bash
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  EOF

  tags = { Name = "market-intel" }
}
